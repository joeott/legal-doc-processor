#!/usr/bin/env python3
"""
Modified import script that targets a specific project UUID instead of creating new ones.
Based on import_from_manifest_fixed.py but with proper project targeting.
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

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Debug environment
print(f"ENV - SUPABASE_URL: {os.getenv('SUPABASE_URL')}")
print(f"ENV - SUPABASE_ANON_KEY: {os.getenv('SUPABASE_ANON_KEY')[:50] if os.getenv('SUPABASE_ANON_KEY') else 'NOT SET'}...")

from scripts.supabase_utils import SupabaseManager
from scripts.s3_storage import S3StorageManager
from scripts.celery_submission import submit_document_to_celery


class TargetedManifestImporter:
    """Import script that targets a specific project UUID"""
    
    def __init__(self, manifest_path: str, target_project_uuid: str, max_workers: int = 4, batch_size: int = 50):
        """Initialize importer with manifest and target project"""
        self.manifest_path = manifest_path
        self.target_project_uuid = target_project_uuid
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
        
        # Project association (will be set in verify_target_project)
        self.project_sql_id = None
        self.project_uuid = target_project_uuid
        self.project_name = None
        
        # Import session tracking
        self.session_id = None
        self.start_time = None
        
        # Progress tracking
        self.processed_count = 0
        self.failed_count = 0
        self.total_cost = 0.0
        self.progress_lock = threading.Lock()
        
        # Cost tracking by service
        self.costs_by_service = defaultdict(float)
        
        print(f"Initialized targeted importer for case: {self.case_name}")
        print(f"Target project UUID: {self.target_project_uuid}")
        print(f"Total files to import: {len(self.manifest['files'])}")
    
    def verify_target_project(self) -> Tuple[int, str]:
        """Verify target project exists and get its details"""
        try:
            # Look for the specific project by UUID
            result = self.db_manager.client.table('projects')\
                .select('id, projectId, name, metadata')\
                .eq('projectId', self.target_project_uuid)\
                .execute()
            
            if not result.data:
                raise ValueError(f"Target project not found: {self.target_project_uuid}")
            
            project_data = result.data[0]
            self.project_sql_id = project_data['id']
            self.project_uuid = project_data['projectId']
            self.project_name = project_data['name']
            
            print(f"✅ Target project verified:")
            print(f"   Name: {self.project_name}")
            print(f"   SQL ID: {self.project_sql_id}")
            print(f"   UUID: {self.project_uuid}")
            
            # Check for existing documents
            doc_count = self.db_manager.client.table('source_documents')\
                .select('id', count='exact')\
                .eq('project_fk_id', self.project_sql_id)\
                .execute()
            
            existing_docs = doc_count.count if hasattr(doc_count, 'count') else 0
            print(f"   Existing documents: {existing_docs}")
            
            return self.project_sql_id, self.project_uuid
                
        except Exception as e:
            print(f"❌ Error verifying target project: {e}")
            raise
    
    def create_import_session(self) -> str:
        """Create import session for the target project"""
        try:
            session_data = {
                'case_name': self.case_name,
                'project_id': self.project_sql_id,  # Use integer ID
                'manifest': self.manifest,
                'total_files': len(self.manifest['files']),
                'status': 'active'
            }
            
            result = self.db_manager.service_client.table('import_sessions')\
                .insert(session_data)\
                .execute()
            
            self.session_id = result.data[0]['id']
            print(f"✅ Created import session: {self.session_id}")
            print(f"   Associated with project: {self.project_name} (ID: {self.project_sql_id})")
            return self.session_id
            
        except Exception as e:
            print(f"❌ Error creating import session: {e}")
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
                
            # Track cumulative costs
            with self.progress_lock:
                self.total_cost += cost_data['total_cost']
                self.costs_by_service[service] += cost_data['total_cost']
                
        except Exception as e:
            # Don't fail import if cost tracking fails
            print(f"Warning: Failed to record cost: {e}")
    
    def _process_file(self, file_info: Dict) -> Dict:
        """Process a single file"""
        file_path = self.base_path / file_info['path']
        
        try:
            # Skip audio/video files if they somehow got through
            if file_info.get('mime_type', '').startswith(('audio/', 'video/')):
                print(f"    ⚠️  Skipping audio/video file: {file_info['filename']}")
                return {
                    'status': 'skipped',
                    'reason': 'audio/video excluded'
                }
            
            # Create document entry with target project
            source_doc_id, doc_uuid = self.db_manager.create_source_document_entry(
                project_fk_id=self.project_sql_id,      # Use target project ID
                project_uuid=self.project_uuid,         # Use target project UUID
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
                    'import_session_id': self.session_id
                })\
                .eq('document_uuid', doc_uuid)\
                .execute()
            
            # Submit to Celery for processing
            task_id, is_image = submit_document_to_celery(
                document_id=source_doc_id,
                document_uuid=doc_uuid,
                file_path=s3_key,
                file_type=os.path.splitext(file_info['filename'])[1][1:],  # Extension without dot
                file_name=file_info['filename'],
                project_sql_id=self.project_sql_id
            )
            
            # Record estimated costs
            self._record_file_costs(doc_uuid, file_info)
            
            print(f"    ✅ {file_info['filename']} queued successfully (Task: {task_id})")
            
            return {
                'status': 'success',
                'document_uuid': doc_uuid,
                'source_doc_id': source_doc_id,
                'task_id': task_id,
                'is_image': is_image
            }
            
        except Exception as e:
            print(f"    ❌ {file_info['filename']}: {str(e)}")
            return {
                'status': 'failed',
                'error': str(e)
            }
    
    def _record_file_costs(self, doc_uuid: str, file_info: Dict):
        """Record estimated costs for a file"""
        if 'estimated_cost' in file_info:
            for service, cost in file_info['estimated_cost'].items():
                if cost > 0:
                    self.record_cost(
                        doc_uuid,
                        service.replace('_', ' ').title(),
                        'Estimated',
                        1,
                        cost,
                        is_estimated=True
                    )
    
    def _process_batch(self, batch: List[Dict]) -> Dict[str, int]:
        """Process a batch of files concurrently"""
        results = {'success': 0, 'failed': 0, 'skipped': 0}
        
        print(f"\nProcessing batch of {len(batch)} files...")
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_file = {
                executor.submit(self._process_file, file_info): file_info
                for file_info in batch
            }
            
            for future in as_completed(future_to_file):
                file_info = future_to_file[future]
                result = future.result()
                
                results[result['status']] += 1
                
                with self.progress_lock:
                    if result['status'] == 'success':
                        self.processed_count += 1
                    elif result['status'] == 'failed':
                        self.failed_count += 1
        
        return results
    
    def import_files(self, dry_run: bool = False):
        """Import all files from manifest"""
        print("\n" + "="*60)
        print("STARTING TARGETED IMPORT")
        print("="*60)
        
        # Verify target project
        self.project_sql_id, self.project_uuid = self.verify_target_project()
        
        # Create import session
        self.create_import_session()
        
        if dry_run:
            print("\n✅ DRY RUN - No files will be processed")
            self._print_summary()
            return
        
        self.start_time = time.time()
        
        # Process files in batches
        files = self.manifest['files']
        total_batches = (len(files) + self.batch_size - 1) // self.batch_size
        
        for i in range(0, len(files), self.batch_size):
            batch = files[i:i + self.batch_size]
            batch_num = (i // self.batch_size) + 1
            
            print(f"\n{'='*60}")
            print(f"Batch {batch_num}/{total_batches}")
            print(f"{'='*60}")
            
            results = self._process_batch(batch)
            
            print(f"\nBatch results: Success={results['success']}, Failed={results['failed']}, Skipped={results['skipped']}")
            print(f"Total progress: {self.processed_count}/{len(files)} processed")
            
            # Update import session status
            self._update_session_status()
        
        # Final update
        self._finalize_import()
        self._print_summary()
    
    def _update_session_status(self):
        """Update import session with current progress"""
        try:
            self.db_manager.service_client.table('import_sessions')\
                .update({
                    'processed_files': self.processed_count,
                    'failed_files': self.failed_count,
                    'total_cost': self.total_cost,
                    'status': 'active'
                })\
                .eq('id', self.session_id)\
                .execute()
        except Exception as e:
            print(f"Warning: Failed to update session status: {e}")
    
    def _finalize_import(self):
        """Finalize import session"""
        duration = time.time() - self.start_time
        
        try:
            self.db_manager.service_client.table('import_sessions')\
                .update({
                    'processed_files': self.processed_count,
                    'failed_files': self.failed_count,
                    'total_cost': self.total_cost,
                    'processing_time_seconds': duration,
                    'status': 'completed',
                    'completed_at': datetime.now().isoformat()
                })\
                .eq('id', self.session_id)\
                .execute()
        except Exception as e:
            print(f"Warning: Failed to finalize session: {e}")
    
    def _print_summary(self):
        """Print import summary"""
        print("\n" + "="*60)
        print("IMPORT SUMMARY")
        print("="*60)
        print(f"Case: {self.case_name}")
        print(f"Project: {self.project_name}")
        print(f"Project ID: {self.project_sql_id}")
        print(f"Project UUID: {self.project_uuid}")
        print(f"Session ID: {self.session_id}")
        print(f"Total files: {len(self.manifest['files'])}")
        print(f"Processed: {self.processed_count}")
        print(f"Failed: {self.failed_count}")
        
        if self.start_time:
            duration = time.time() - self.start_time
            print(f"Duration: {duration:.1f} seconds")
            print(f"Rate: {self.processed_count / duration:.1f} files/second")
        
        print(f"\nEstimated costs:")
        for service, cost in self.costs_by_service.items():
            print(f"  {service}: ${cost:.4f}")
        print(f"  Total: ${self.total_cost:.4f}")
        
        print("\n" + "="*60)
        
        print("\nNext steps:")
        print("1. Monitor progress: python scripts/standalone_pipeline_monitor.py")
        print(f"2. Check session: python scripts/check_import_completion.py --session {self.session_id}")
        print("3. Flower dashboard: http://localhost:5555")


def main():
    parser = argparse.ArgumentParser(description='Import documents from manifest to target project')
    parser.add_argument('manifest', help='Path to manifest JSON file')
    parser.add_argument('--project-uuid', required=True, help='Target project UUID')
    parser.add_argument('--workers', type=int, default=4, help='Number of concurrent workers')
    parser.add_argument('--batch-size', type=int, default=50, help='Files per batch')
    parser.add_argument('--dry-run', action='store_true', help='Test run without processing')
    
    args = parser.parse_args()
    
    try:
        importer = TargetedManifestImporter(
            args.manifest,
            args.project_uuid,
            max_workers=args.workers,
            batch_size=args.batch_size
        )
        importer.import_files(dry_run=args.dry_run)
    except Exception as e:
        print(f"\n❌ Import failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()