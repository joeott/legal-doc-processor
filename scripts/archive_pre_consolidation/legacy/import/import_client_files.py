#!/usr/bin/env python3
"""
Import client files into the document processing system.

This script handles batch import with concurrent processing,
cost tracking, and comprehensive error handling.
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
import threading
from collections import defaultdict

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.supabase_utils import SupabaseManager
from scripts.s3_storage import S3DocumentStorage
from scripts.celery_submission import submit_document_to_celery
from scripts.import_tracker import ImportTracker, ImportStatus
from scripts.config import Config


class ClientFileImporter:
    """Import client files with concurrent processing."""
    
    def __init__(self, manifest_path: str, project_id: str = None, 
                 max_workers: int = 4, batch_size: int = 50):
        """Initialize importer with manifest."""
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
        self.s3_storage = S3DocumentStorage()
        self.tracker = ImportTracker()
        
        # Create or get project
        if not self.project_id:
            self._create_project()
        
        # Create import session
        self.session_id = self.tracker.create_session(
            self.case_name, 
            self.project_id,
            manifest_path
        )
        
        # Threading
        self.stats_lock = threading.Lock()
        self.stats = defaultdict(int)
        
        print(f"Initialized importer for case: {self.case_name}")
        print(f"Project ID: {self.project_id}")
        print(f"Session ID: {self.session_id}")
        print(f"Total files to import: {len(self.manifest['files'])}")
    
    def _create_project(self):
        """Create project in database."""
        try:
            # Check if project exists
            projects = self.db_manager.client.table('projects').select('*').eq('name', self.case_name).execute()
            
            if projects.data:
                self.project_id = projects.data[0]['id']
                print(f"Using existing project: {self.project_id}")
            else:
                # Create new project
                project_data = {
                    'name': self.case_name,
                    'description': f"Import from {self.manifest_path}",
                    'metadata': {
                        'import_session': self.session_id,
                        'base_path': str(self.base_path),
                        'created_at': datetime.now().isoformat()
                    }
                }
                
                result = self.db_manager.client.table('projects').insert(project_data).execute()
                self.project_id = result.data[0]['id']
                print(f"Created new project: {self.project_id}")
                
        except Exception as e:
            print(f"Error creating project: {e}")
            raise
    
    def import_files(self, skip_processed: bool = True, dry_run: bool = False):
        """Import all files from manifest."""
        print("\n" + "="*60)
        print("STARTING IMPORT")
        print("="*60)
        
        # Add all files to tracker
        print("Registering files in tracker...")
        for file_info in self.manifest['files']:
            self.tracker.add_document(self.session_id, file_info)
        
        if dry_run:
            print("DRY RUN - No files will be processed")
            return
        
        # Process files by category in order
        processing_order = self.manifest['import_config']['processing_order']
        
        for category in processing_order:
            category_files = [
                f for f in self.manifest['files'] 
                if f['folder_category'] == category
            ]
            
            if category_files:
                print(f"\nProcessing {category} ({len(category_files)} files)...")
                self._process_category(category, category_files, skip_processed)
        
        # Process any remaining files
        remaining_files = [
            f for f in self.manifest['files']
            if f['folder_category'] not in processing_order
        ]
        
        if remaining_files:
            print(f"\nProcessing remaining files ({len(remaining_files)} files)...")
            self._process_category('other', remaining_files, skip_processed)
        
        # Retry failed documents
        self._retry_failed_documents()
        
        # Mark session complete
        self.tracker.mark_session_complete(self.session_id)
        
        # Print final summary
        self._print_summary()
    
    def _process_category(self, category: str, files: List[Dict], skip_processed: bool):
        """Process files in a category."""
        # Get pending documents from tracker
        pending_docs = self.tracker.get_pending_documents(self.session_id, limit=len(files))
        
        # Filter to only this category
        category_pending = [
            doc for doc in pending_docs
            if any(f['file_hash'] == doc['file_hash'] for f in files)
        ]
        
        if not category_pending:
            print(f"  No pending files in {category}")
            return
        
        # Process in batches
        total_batches = (len(category_pending) + self.batch_size - 1) // self.batch_size
        
        for batch_num in range(total_batches):
            start_idx = batch_num * self.batch_size
            end_idx = min(start_idx + self.batch_size, len(category_pending))
            batch = category_pending[start_idx:end_idx]
            
            print(f"  Processing batch {batch_num + 1}/{total_batches} ({len(batch)} files)")
            self._process_batch(batch)
    
    def _process_batch(self, documents: List[Dict]):
        """Process a batch of documents concurrently."""
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all documents
            future_to_doc = {
                executor.submit(self._process_document, doc): doc
                for doc in documents
            }
            
            # Process results as they complete
            for future in as_completed(future_to_doc):
                doc = future_to_doc[future]
                try:
                    result = future.result()
                    with self.stats_lock:
                        self.stats['processed'] += 1
                except Exception as e:
                    print(f"    Error processing {doc['file_path']}: {e}")
                    with self.stats_lock:
                        self.stats['failed'] += 1
    
    def _process_document(self, doc_record: Dict) -> Dict:
        """Process a single document."""
        import_id = doc_record['import_id']
        file_path = self.base_path / doc_record['file_path']
        
        try:
            # Update status to processing
            self.tracker.update_document_status(import_id, ImportStatus.PROCESSING)
            
            # Parse metadata
            metadata = json.loads(doc_record['metadata']) if doc_record['metadata'] else {}
            
            # Upload to S3
            print(f"    Uploading {file_path.name}...")
            s3_key = self.s3_storage.upload_document(
                str(file_path),
                project_id=self.project_id,
                case_subfolder=metadata.get('folder_category', 'misc')
            )
            
            # Record S3 cost
            file_size_mb = doc_record['size_bytes'] / (1024 * 1024)
            self.tracker.record_cost(
                self.session_id,
                service='s3',
                operation='upload',
                units=1,
                unit_cost=0.005 / 1000,  # $0.005 per 1000 PUT requests
                import_id=import_id
            )
            
            # Create document entry in database
            doc_uuid, source_doc_id = self.db_manager.create_document_entry(
                filename=file_path.name,
                file_type=metadata.get('mime_type', 'unknown'),
                project_id=self.project_id,
                s3_key=s3_key,
                file_size=doc_record['size_bytes'],
                metadata={
                    'original_path': doc_record['file_path'],
                    'folder_category': metadata.get('folder_category'),
                    'case_name': self.case_name,
                    'import_session': self.session_id,
                    'file_hash': doc_record['file_hash']
                }
            )
            
            # Update tracker with upload info
            self.tracker.update_document_status(
                import_id,
                ImportStatus.UPLOADED,
                document_uuid=doc_uuid,
                source_doc_id=source_doc_id,
                s3_key=s3_key
            )
            
            # Submit to Celery for processing
            print(f"    Submitting {file_path.name} to processing queue...")
            task_id = submit_document_to_celery(
                doc_uuid,
                source_doc_id,
                s3_key,
                metadata.get('mime_type', 'unknown')
            )
            
            # Update status to queued
            self.tracker.update_document_status(import_id, ImportStatus.QUEUED)
            
            # Estimate processing costs
            self._estimate_document_costs(import_id, metadata)
            
            print(f"    ✓ {file_path.name} queued successfully")
            
            return {
                'import_id': import_id,
                'document_uuid': doc_uuid,
                'source_doc_id': source_doc_id,
                'task_id': task_id,
                'status': 'success'
            }
            
        except Exception as e:
            # Update tracker with error
            self.tracker.update_document_status(
                import_id,
                ImportStatus.FAILED,
                error=e
            )
            
            print(f"    ✗ {file_path.name} failed: {str(e)}")
            raise
    
    def _estimate_document_costs(self, import_id: int, metadata: Dict):
        """Estimate and record processing costs for a document."""
        mime_type = metadata.get('mime_type', 'unknown')
        estimated_pages = metadata.get('estimated_pages', 1)
        
        # Textract costs
        if metadata.get('requires_ocr'):
            self.tracker.record_cost(
                self.session_id,
                service='textract',
                operation='pages',
                units=estimated_pages,
                unit_cost=0.015,
                import_id=import_id,
                metadata={'estimated': True}
            )
        
        # OpenAI extraction costs (estimated)
        extraction_tokens = estimated_pages * 500  # ~500 tokens per page
        self.tracker.record_cost(
            self.session_id,
            service='openai',
            operation='extraction_tokens',
            units=extraction_tokens,
            unit_cost=0.03 / 1000,  # $0.03 per 1K tokens
            import_id=import_id,
            metadata={'estimated': True}
        )
        
        # OpenAI embedding costs (estimated)
        embedding_tokens = estimated_pages * 100  # ~100 tokens per page
        self.tracker.record_cost(
            self.session_id,
            service='openai',
            operation='embedding_tokens',
            units=embedding_tokens,
            unit_cost=0.0001 / 1000,  # $0.0001 per 1K tokens
            import_id=import_id,
            metadata={'estimated': True}
        )
    
    def _retry_failed_documents(self):
        """Retry failed documents."""
        failed_docs = self.tracker.get_failed_documents(self.session_id)
        
        if failed_docs:
            print(f"\nRetrying {len(failed_docs)} failed documents...")
            self._process_batch(failed_docs)
    
    def _print_summary(self):
        """Print import summary."""
        summary = self.tracker.get_import_summary(self.session_id)
        
        print("\n" + "="*60)
        print("IMPORT SUMMARY")
        print("="*60)
        
        session = summary['session']
        print(f"Case: {session['case_name']}")
        print(f"Project ID: {session['project_id']}")
        print(f"Total files: {session['total_files']}")
        print(f"Processed: {session['processed_files']}")
        print(f"Failed: {session['failed_files']}")
        print(f"Total cost: ${session['total_cost']:.2f}")
        
        if session['status_counts']:
            print("\nStatus breakdown:")
            for status, count in session['status_counts'].items():
                print(f"  {status}: {count}")
        
        if session['cost_breakdown']:
            print("\nCost breakdown:")
            for service, cost in session['cost_breakdown'].items():
                print(f"  {service}: ${cost:.2f}")
        
        if summary['time_stats']['total_time']:
            print(f"\nProcessing time:")
            print(f"  Total: {summary['time_stats']['total_time']:.1f} seconds")
            print(f"  Average: {summary['time_stats']['avg_time']:.1f} seconds/file")
        
        if session['recent_errors']:
            print(f"\nRecent errors:")
            for error in session['recent_errors'][:5]:
                print(f"  {error['file_path']}: {error['error_type']}")
        
        print("\n" + "="*60)
    
    def export_results(self, output_path: str = None):
        """Export import results."""
        if not output_path:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_path = f"import_results_{self.case_name}_{timestamp}.json"
        
        self.tracker.export_session_data(self.session_id, output_path)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Import client files')
    parser.add_argument('manifest', help='Path to import manifest JSON file')
    parser.add_argument('--project-id', help='Project ID (creates new if not specified)')
    parser.add_argument('--workers', type=int, default=4, help='Number of concurrent workers')
    parser.add_argument('--batch-size', type=int, default=50, help='Batch size for processing')
    parser.add_argument('--dry-run', action='store_true', help='Dry run without processing')
    parser.add_argument('--skip-processed', action='store_true', default=True,
                       help='Skip already processed files')
    parser.add_argument('--export', help='Export results to specified path')
    
    args = parser.parse_args()
    
    # Check manifest exists
    if not os.path.exists(args.manifest):
        print(f"Error: Manifest file not found: {args.manifest}")
        sys.exit(1)
    
    # Create importer
    importer = ClientFileImporter(
        args.manifest,
        project_id=args.project_id,
        max_workers=args.workers,
        batch_size=args.batch_size
    )
    
    try:
        # Run import
        importer.import_files(
            skip_processed=args.skip_processed,
            dry_run=args.dry_run
        )
        
        # Export results if requested
        if args.export:
            importer.export_results(args.export)
            
    except KeyboardInterrupt:
        print("\nImport interrupted by user")
        # Still export partial results
        importer.export_results()
    except Exception as e:
        print(f"\nImport failed: {e}")
        import traceback
        traceback.print_exc()
        # Export partial results
        importer.export_results()
        sys.exit(1)


if __name__ == '__main__':
    main()