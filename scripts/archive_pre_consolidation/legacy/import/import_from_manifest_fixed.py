#!/usr/bin/env python3
"""
Fixed import script that properly handles project association and UUIDs.
Addresses all issues identified in context_140_import_troubleshoot.md
"""

import os
import sys
import json
import time
import argparse
import uuid
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
from collections import defaultdict

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.supabase_utils import SupabaseManager
from scripts.s3_storage import S3StorageManager
from scripts.celery_submission import submit_document_to_celery


class FixedManifestImporter:
    """Fixed import script with proper project association and UUID handling"""
    
    def __init__(self, manifest_path: str, max_workers: int = 4, batch_size: int = 50):
        """Initialize importer with manifest"""
        self.manifest_path = manifest_path
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
        
        # Project association (will be set in find_or_create_input_project)
        self.project_sql_id = None
        self.project_uuid = None
        
        # Session tracking
        self.session_id = None
        self.processed_count = 0
        self.failed_count = 0
        
        print(f"Initialized fixed importer for case: {self.case_name}")
        print(f"Total files to import: {len(self.manifest['files'])}")
    
    def find_or_create_input_project(self) -> Tuple[int, str]:
        """Find existing project for /input/ documents or create one"""
        try:
            # Look for existing project for input files
            result = self.db_manager.client.table('projects')\
                .select('id, projectId, name')\
                .ilike('name', '%Input%')\
                .order('id', desc=True)\
                .limit(1)\
                .execute()
            
            if result.data:
                project_sql_id = result.data[0]['id']
                project_uuid = result.data[0]['projectId']
                project_name = result.data[0]['name']
                
                # If project UUID is missing, generate one
                if not project_uuid:
                    project_uuid = str(uuid.uuid4())
                    self.db_manager.client.table('projects')\
                        .update({'projectId': project_uuid})\
                        .eq('id', project_sql_id)\
                        .execute()
                    print(f"Added UUID {project_uuid} to existing project")
                
                print(f"Using existing project: ID={project_sql_id}, UUID={project_uuid}, Name='{project_name}'")
                return project_sql_id, project_uuid
            else:
                # Create new project with proper UUID
                project_uuid = str(uuid.uuid4())
                project_data = {
                    'name': 'Legal Documents - Input Collection',
                    'projectId': project_uuid,
                    'metadata': {
                        'source': 'input_directory_import',
                        'description': 'Documents from /input/ directory',
                        'created_at': datetime.now().isoformat(),
                        'total_estimated_files': len(self.manifest['files'])
                    }
                }
                
                result = self.db_manager.client.table('projects')\
                    .insert(project_data)\
                    .execute()
                
                project_sql_id = result.data[0]['id']
                print(f"Created new project: ID={project_sql_id}, UUID={project_uuid}")
                return project_sql_id, project_uuid
                
        except Exception as e:
            print(f"Error managing project: {e}")
            raise
    
    def create_import_session(self) -> str:
        """Create import session with proper project association"""
        try:
            session_data = {
                'case_name': 'Legal Documents - Input Collection',
                'project_id': self.project_sql_id,  # Use integer ID
                'manifest': self.manifest,
                'total_files': len(self.manifest['files']),
                'status': 'active'
            }
            
            result = self.db_manager.service_client.table('import_sessions')\
                .insert(session_data)\
                .execute()
            
            self.session_id = result.data[0]['id']
            print(f"Created import session: {self.session_id}")
            print(f"Associated with project: {self.project_sql_id} ({self.project_uuid})")
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
        """Import all files with proper project association"""
        print("\n" + "="*60)
        print("STARTING FIXED IMPORT")
        print("="*60)
        
        # Find or create project FIRST
        self.project_sql_id, self.project_uuid = self.find_or_create_input_project()
        
        # Create import session
        self.create_import_session()
        
        if dry_run:
            print("DRY RUN - No files will be processed")
            self._print_summary()
            return
        
        # Check for existing documents
        self._check_existing_documents()
        
        # Process files by category
        processing_order = self.manifest['import_config']['processing_order']
        
        for category in processing_order:
            category_files = [
                f for f in self.manifest['files'] 
                if f['folder_category'] == category and not f.get('skip', False)
            ]
            
            if category_files:
                print(f"\nProcessing {category} ({len(category_files)} files)...")
                self._process_batch(category_files)
        
        # Process remaining files
        remaining_files = [
            f for f in self.manifest['files']
            if f['folder_category'] not in processing_order and not f.get('skip', False)
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
        
        try:
            # Get existing documents for this project
            result = self.db_manager.client.table('source_documents')\
                .select('id, original_file_name, document_uuid')\
                .eq('project_fk_id', self.project_sql_id)\
                .execute()
            
            existing_files = {doc['original_file_name'] for doc in result.data}
            
            if existing_files:
                print(f"Found {len(existing_files)} existing documents in project")
                
                # Mark files as skipped if they already exist
                skipped_count = 0
                for file_info in self.manifest['files']:
                    if file_info['filename'] in existing_files:
                        file_info['skip'] = True
                        skipped_count += 1
                
                if skipped_count > 0:
                    print(f"Marked {skipped_count} files as skipped (already imported)")
            else:
                print("No existing documents found in project")
                
        except Exception as e:
            print(f"Warning: Could not check existing documents: {e}")
    
    def _process_batch(self, files: List[Dict]):
        """Process a batch of files"""
        # Process with thread pool
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = []
            
            for i in range(0, len(files), self.batch_size):
                batch = files[i:i + self.batch_size]
                print(f"  Processing batch {i//self.batch_size + 1} ({len(batch)} files)")
                
                # Submit batch to thread pool
                batch_futures = []
                for file_info in batch:
                    future = executor.submit(self._process_file, file_info)
                    batch_futures.append((future, file_info))
                
                # Wait for batch to complete
                for future, file_info in batch_futures:
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
        """Process a single file with correct project association"""
        file_path = self.base_path / file_info['path']
        
        try:
            print(f"    Processing {file_info['filename']}...")
            
            # Create document entry with correct parameters
            source_doc_id, doc_uuid = self.db_manager.create_source_document_entry(
                project_fk_id=self.project_sql_id,      # Integer ID
                project_uuid=self.project_uuid,         # Proper UUID string
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
            
            # Update document with S3 key and session info
            self.db_manager.client.table('source_documents')\
                .update({
                    's3_key': s3_key,
                    'import_session_id': self.session_id,
                    'file_size_bytes': file_info['size_bytes']
                })\
                .eq('document_uuid', doc_uuid)\
                .execute()
            
            # Submit to Celery for processing
            task_id, success = submit_document_to_celery(
                document_id=source_doc_id,
                document_uuid=doc_uuid,
                file_path=s3_key,
                file_type=file_info.get('mime_type', 'unknown'),
                file_name=file_info['filename'],
                project_sql_id=self.project_sql_id
            )
            
            if not success:
                raise Exception(f"Failed to submit to Celery: {task_id}")
            
            # Record estimated costs
            self._record_file_costs(doc_uuid, file_info)
            
            print(f"    ✓ {file_info['filename']} queued successfully (Task: {task_id[:8]}...)")
            
            return {
                'status': 'success',
                'document_uuid': doc_uuid,
                'source_doc_id': source_doc_id,
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
        print(f"Project ID: {self.project_sql_id}")
        print(f"Project UUID: {self.project_uuid}")
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
                    print(f"  {service}: ${cost:.4f}")
                print(f"  Total: ${total:.4f}")
        except:
            pass
        
        print("\n" + "="*60)
        print(f"\nNext steps:")
        print(f"1. Monitor progress: python scripts/standalone_pipeline_monitor.py")
        print(f"2. Check session: python scripts/check_import_completion.py --session {self.session_id}")
        print(f"3. Flower dashboard: http://localhost:5555")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='Import documents from manifest (FIXED)')
    parser.add_argument('manifest', help='Path to import manifest JSON')
    parser.add_argument('--workers', type=int, default=4, help='Concurrent workers')
    parser.add_argument('--batch-size', type=int, default=50, help='Batch size')
    parser.add_argument('--dry-run', action='store_true', help='Dry run only')
    
    args = parser.parse_args()
    
    # Validate manifest exists
    if not os.path.exists(args.manifest):
        print(f"Error: Manifest not found: {args.manifest}")
        sys.exit(1)
    
    # Create importer
    importer = FixedManifestImporter(
        args.manifest,
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