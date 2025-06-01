#!/usr/bin/env python3
"""
Unified import script that uses existing infrastructure.
Replaces import_client_files.py with proper integration.
"""

import os
import sys
import json
import time
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.supabase_utils import SupabaseManager
from scripts.s3_storage import S3StorageManager
from scripts.celery_submission import submit_document_to_celery
# Config is loaded automatically when importing other modules


class ManifestImporter:
    """Import documents from manifest using existing infrastructure"""
    
    def __init__(self, manifest_path: str, project_id: str = None, 
                 max_workers: int = 4, batch_size: int = 50):
        """Initialize importer with manifest"""
        self.manifest_path = manifest_path
        self.project_id = project_id
        self.max_workers = max_workers
        self.batch_size = batch_size
        
        # Load manifest
        with open(manifest_path, 'r') as f:
            self.manifest = json.load(f)
        
        self.case_name = self.manifest['metadata']['case_name']
        self.base_path = Path(self.manifest['metadata']['base_path'])
        
        # Initialize components
        self.db_manager = SupabaseManager()
        self.s3_storage = S3StorageManager()
        
        # Session tracking
        self.session_id = None
        self.processed_count = 0
        self.failed_count = 0
        
        print(f"Initialized importer for case: {self.case_name}")
        print(f"Total files to import: {len(self.manifest['files'])}")
    
    def create_or_get_project(self) -> str:
        """Create or get existing project"""
        try:
            # Check if project exists
            result = self.db_manager.client.table('projects')\
                .select('*')\
                .eq('name', self.case_name)\
                .execute()
            
            if result.data:
                self.project_id = result.data[0]['id']
                print(f"Using existing project: {self.project_id}")
            else:
                # Create new project
                project_data = {
                    'name': self.case_name,
                    'metadata': {
                        'manifest_path': str(self.manifest_path),
                        'base_path': str(self.base_path),
                        'created_at': datetime.now().isoformat()
                    }
                }
                
                result = self.db_manager.client.table('projects')\
                    .insert(project_data)\
                    .execute()
                self.project_id = result.data[0]['id']
                print(f"Created new project: {self.project_id}")
            
            return self.project_id
            
        except Exception as e:
            print(f"Error managing project: {e}")
            raise
    
    def create_import_session(self) -> str:
        """Create import session in database"""
        try:
            session_data = {
                'case_name': self.case_name,
                'project_id': self.project_id,
                'manifest': self.manifest,
                'total_files': len(self.manifest['files']),
                'status': 'active'
            }
            
            result = self.db_manager.service_client.table('import_sessions')\
                .insert(session_data)\
                .execute()
            
            self.session_id = result.data[0]['id']
            print(f"Created import session: {self.session_id}")
            return self.session_id
            
        except Exception as e:
            print(f"Error creating import session: {e}")
            raise
    
    def record_cost(self, document_id: str, service: str, operation: str,
                   units: int, unit_cost: float, is_estimated: bool = True):
        """Record processing cost in database"""
        try:
            cost_data = {
                'import_session_id': self.session_id,
                'document_id': document_id,
                'service': service,
                'operation': operation,
                'units': units,
                'unit_cost': unit_cost,
                'total_cost': units * unit_cost,
                'is_estimated': is_estimated
            }
            
            self.db_manager.service_client.table('processing_costs')\
                .insert(cost_data)\
                .execute()
                
        except Exception as e:
            print(f"Warning: Failed to record cost: {e}")
    
    def import_files(self, dry_run: bool = False):
        """Import all files from manifest"""
        print("\n" + "="*60)
        print("STARTING IMPORT")
        print("="*60)
        
        # Create or get project
        if not self.project_id:
            self.create_or_get_project()
        
        # Create import session
        self.create_import_session()
        
        if dry_run:
            print("DRY RUN - No files will be processed")
            self._print_summary()
            return
        
        # Check for duplicates first
        self._check_existing_documents()
        
        # Process files by category
        processing_order = self.manifest['import_config']['processing_order']
        
        for category in processing_order:
            category_files = [
                f for f in self.manifest['files'] 
                if f['folder_category'] == category
            ]
            
            if category_files:
                print(f"\nProcessing {category} ({len(category_files)} files)...")
                self._process_batch(category_files)
        
        # Process remaining files
        remaining_files = [
            f for f in self.manifest['files']
            if f['folder_category'] not in processing_order
        ]
        
        if remaining_files:
            print(f"\nProcessing remaining files ({len(remaining_files)} files)...")
            self._process_batch(remaining_files)
        
        # Update session status
        self._complete_session()
        
        # Print summary
        self._print_summary()
    
    def _check_existing_documents(self):
        """Check for already imported documents"""
        print("\nChecking for existing documents...")
        
        # Get all file hashes from manifest
        file_hashes = {f['file_hash']: f['path'] for f in self.manifest['files']}
        
        # Query existing documents with matching hashes
        try:
            result = self.db_manager.client.table('source_documents')\
                .select('id, metadata')\
                .eq('project_id', self.project_id)\
                .execute()
            
            existing_count = 0
            for doc in result.data:
                if doc.get('metadata') and doc['metadata'].get('file_hash') in file_hashes:
                    existing_count += 1
                    file_path = file_hashes[doc['metadata']['file_hash']]
                    print(f"  Already imported: {file_path}")
            
            if existing_count > 0:
                print(f"\nFound {existing_count} already imported documents")
                response = input("Skip these files? (y/n): ")
                if response.lower() == 'y':
                    # Mark as skipped in manifest
                    for f in self.manifest['files']:
                        if f['file_hash'] in [d.get('metadata', {}).get('file_hash') 
                                             for d in result.data]:
                            f['skip'] = True
                            
        except Exception as e:
            print(f"Warning: Could not check existing documents: {e}")
    
    def _process_batch(self, files: List[Dict]):
        """Process a batch of files"""
        # Filter out skipped files
        files_to_process = [f for f in files if not f.get('skip', False)]
        
        if not files_to_process:
            print("  All files already processed")
            return
        
        # Process with thread pool
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = []
            
            for i in range(0, len(files_to_process), self.batch_size):
                batch = files_to_process[i:i + self.batch_size]
                print(f"  Processing batch {i//self.batch_size + 1} ({len(batch)} files)")
                
                for file_info in batch:
                    future = executor.submit(self._process_file, file_info)
                    futures.append((future, file_info))
                
                # Wait for batch to complete
                for future, file_info in futures:
                    try:
                        result = future.result(timeout=300)  # 5 min timeout
                        if result['status'] == 'success':
                            self.processed_count += 1
                        else:
                            self.failed_count += 1
                    except Exception as e:
                        print(f"    ✗ {file_info['filename']}: {str(e)}")
                        self.failed_count += 1
    
    def _process_file(self, file_info: Dict) -> Dict:
        """Process a single file"""
        file_path = self.base_path / file_info['path']
        
        try:
            # Upload to S3 (using UUID-based naming)
            print(f"    Uploading {file_info['filename']}...")
            # First create document entry to get UUID
            source_doc_id, doc_uuid = self.db_manager.create_source_document_entry(
                project_fk_id=self.project_id,
                project_uuid='',  # We'll get project UUID separately 
                original_file_path=file_info['path'],
                original_file_name=file_info['filename'],
                detected_file_type=file_info.get('mime_type', 'unknown')
            )
            
            # Upload to S3 with UUID naming
            s3_result = self.s3_storage.upload_document_with_uuid_naming(
                str(file_path),
                doc_uuid,
                file_info['filename']
            )
            s3_key = s3_result['s3_key']
            
            # Update document entry with S3 key
            self.db_manager.client.table('source_documents')\
                .update({'s3_key': s3_key})\
                .eq('document_uuid', doc_uuid)\
                .execute()
            
            # Update with import session and other metadata
            self.db_manager.client.table('source_documents')\
                .update({
                    'import_session_id': self.session_id,
                    'metadata': {
                        'original_path': file_info['path'],
                        'folder_category': file_info.get('folder_category'),
                        'case_name': self.case_name,
                        'file_hash': file_info['file_hash']
                    }
                })\
                .eq('document_uuid', doc_uuid)\
                .execute()
            
            # Submit to Celery
            task_id = submit_document_to_celery(
                doc_uuid,
                source_doc_id,
                s3_key,
                file_info.get('mime_type', 'unknown')
            )
            
            # Record estimated costs
            self._record_file_costs(doc_uuid, file_info)
            
            print(f"    ✓ {file_info['filename']} queued")
            
            return {
                'status': 'success',
                'document_uuid': doc_uuid,
                'task_id': task_id
            }
            
        except Exception as e:
            print(f"    ✗ {file_info['filename']}: {str(e)}")
            return {
                'status': 'failed',
                'error': str(e)
            }
    
    def _record_file_costs(self, doc_uuid: str, file_info: Dict):
        """Record estimated costs for file processing"""
        # S3 upload cost
        self.record_cost(doc_uuid, 's3', 'upload', 1, 0.000005, True)
        
        # OCR cost if needed
        if file_info.get('requires_ocr'):
            pages = file_info.get('estimated_pages', 1)
            self.record_cost(doc_uuid, 'textract', 'pages', pages, 0.015, True)
        
        # OpenAI costs (estimated)
        pages = file_info.get('estimated_pages', 1)
        extraction_tokens = pages * 500
        embedding_tokens = pages * 100
        
        self.record_cost(doc_uuid, 'openai', 'extraction', 
                        extraction_tokens, 0.00003, True)
        self.record_cost(doc_uuid, 'openai', 'embeddings', 
                        embedding_tokens, 0.0000001, True)
    
    def _complete_session(self):
        """Mark session as complete"""
        try:
            self.db_manager.service_client.table('import_sessions')\
                .update({
                    'status': 'completed',
                    'completed_at': datetime.now().isoformat(),
                    'processed_files': self.processed_count,
                    'failed_files': self.failed_count
                })\
                .eq('id', self.session_id)\
                .execute()
        except Exception as e:
            print(f"Warning: Failed to update session status: {e}")
    
    def _print_summary(self):
        """Print import summary"""
        print("\n" + "="*60)
        print("IMPORT SUMMARY")
        print("="*60)
        print(f"Case: {self.case_name}")
        print(f"Project ID: {self.project_id}")
        print(f"Session ID: {self.session_id}")
        print(f"Total files: {len(self.manifest['files'])}")
        print(f"Processed: {self.processed_count}")
        print(f"Failed: {self.failed_count}")
        
        # Get cost summary
        try:
            result = self.db_manager.service_client.table('import_sessions')\
                .select('total_cost, cost_breakdown')\
                .eq('id', self.session_id)\
                .single()\
                .execute()
            
            if result.data:
                print(f"\nEstimated costs:")
                total = result.data.get('total_cost', 0)
                breakdown = result.data.get('cost_breakdown', {})
                
                for service, cost in breakdown.items():
                    print(f"  {service}: ${cost:.2f}")
                print(f"  Total: ${total:.2f}")
        except:
            pass
        
        print("\n" + "="*60)
        print(f"\nMonitor progress at: http://localhost:5555")
        print(f"Or run: python scripts/check_celery_status.py")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='Import documents from manifest')
    parser.add_argument('manifest', help='Path to import manifest JSON')
    parser.add_argument('--project-id', help='Use existing project ID')
    parser.add_argument('--workers', type=int, default=4, help='Concurrent workers')
    parser.add_argument('--batch-size', type=int, default=50, help='Batch size')
    parser.add_argument('--dry-run', action='store_true', help='Dry run only')
    
    args = parser.parse_args()
    
    # Validate manifest exists
    if not os.path.exists(args.manifest):
        print(f"Error: Manifest not found: {args.manifest}")
        sys.exit(1)
    
    # Create importer
    importer = ManifestImporter(
        args.manifest,
        project_id=args.project_id,
        max_workers=args.workers,
        batch_size=args.batch_size
    )
    
    try:
        # Run import
        importer.import_files(dry_run=args.dry_run)
    except KeyboardInterrupt:
        print("\nImport interrupted")
    except Exception as e:
        print(f"\nImport failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()