#!/usr/bin/env python3
"""
Batch performance testing script for document processing pipeline.
Tests with increasing batch sizes: 1, 3, 10, 20 documents.
"""

import os
import sys
sys.path.insert(0, '/opt/legal-doc-processor')

import time
import json
import uuid
from datetime import datetime
from pathlib import Path
import logging

# Setup environment for optimal processing
os.environ['FORCE_PROCESSING'] = 'true'
os.environ['SKIP_PDF_PREPROCESSING'] = 'true'
os.environ['PARAMETER_DEBUG'] = 'false'  # Less logging for performance test
os.environ['VALIDATION_REDIS_METADATA_LEVEL'] = 'optional'
os.environ['VALIDATION_PROJECT_ASSOCIATION_LEVEL'] = 'optional'

from scripts.db import DatabaseManager
from scripts.cache import get_redis_manager
from scripts.pdf_tasks import extract_text_from_document
from scripts.intake_service import create_document_with_validation
from scripts.s3_storage import S3StorageManager
from sqlalchemy import text
import boto3

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class BatchPerformanceTester:
    def __init__(self):
        self.db = DatabaseManager(validate_conformance=False)
        self.redis = get_redis_manager()
        self.s3_manager = S3StorageManager()
        self.test_project_id = None
        self.results = {
            'test_date': datetime.now().isoformat(),
            'batch_results': []
        }
        
    def create_test_project(self):
        """Create a project for testing"""
        session = next(self.db.get_session())
        try:
            project_name = f"BATCH_PERF_TEST_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            project_uuid = str(uuid.uuid4())
            
            result = session.execute(text("""
                INSERT INTO projects (project_id, name, active, created_at)
                VALUES (:project_id, :name, true, NOW())
                RETURNING id
            """), {
                'project_id': project_uuid,
                'name': project_name
            })
            
            self.test_project_id = result.scalar()
            session.commit()
            logger.info(f"Created test project: {project_name} (ID: {self.test_project_id})")
            return self.test_project_id
            
        finally:
            session.close()
    
    def get_test_documents(self, count):
        """Get specified number of test documents"""
        # Discover available PDFs
        pdf_files = []
        root_dir = "/opt/legal-doc-processor/input_docs"
        
        for root, dirs, files in os.walk(root_dir):
            for file in files:
                if file.lower().endswith('.pdf'):
                    full_path = os.path.join(root, file)
                    try:
                        file_size = os.path.getsize(full_path)
                        # Skip very large files (>100MB) for performance testing
                        if file_size < 100 * 1024 * 1024:
                            pdf_files.append({
                                'path': full_path,
                                'filename': file,
                                'size_mb': round(file_size / (1024*1024), 2)
                            })
                    except:
                        pass
        
        # Sort by size and take requested count
        pdf_files.sort(key=lambda x: x['size_mb'])
        return pdf_files[:count]
    
    def upload_document_to_s3(self, file_path):
        """Upload document to S3 and return S3 info"""
        document_uuid = str(uuid.uuid4())
        filename = Path(file_path).name
        
        try:
            # Upload using S3StorageManager
            result = self.s3_manager.upload_document_with_uuid_naming(
                local_file_path=file_path,
                document_uuid=document_uuid,
                original_filename=filename
            )
            
            # Extract S3 info from result
            s3_key = result['s3_key']
            s3_bucket = result['s3_bucket']
            
            # Construct S3 URL
            s3_url = f"s3://{s3_bucket}/{s3_key}"
            
            return {
                'document_uuid': document_uuid,
                's3_url': s3_url,
                's3_key': s3_key,
                'success': True
            }
        except Exception as e:
            logger.error(f"Failed to upload {file_path}: {e}")
            return {'success': False, 'error': str(e)}
    
    def create_document_record(self, doc_info, file_info):
        """Create document record in database"""
        try:
            result = create_document_with_validation(
                document_uuid=doc_info['document_uuid'],
                filename=file_info['filename'],
                s3_bucket=os.environ.get('S3_PRIMARY_DOCUMENT_BUCKET'),
                s3_key=doc_info['s3_key'],
                project_id=self.test_project_id
            )
            return {'success': True, 'document_id': result['document_id']}
        except Exception as e:
            logger.error(f"Failed to create document record: {e}")
            return {'success': False, 'error': str(e)}
    
    def submit_document_for_processing(self, document_uuid, s3_url):
        """Submit document to Celery for processing"""
        try:
            # Add Redis metadata
            metadata = {
                'document_uuid': document_uuid,
                'project_id': self.test_project_id,
                'project_uuid': str(uuid.uuid4()),
                's3_url': s3_url,
                'created_at': datetime.now().isoformat(),
                'status': 'ready_for_processing'
            }
            
            metadata_key = f"doc:metadata:{document_uuid}"
            self.redis.store_dict(metadata_key, metadata)
            
            # Submit to Celery
            result = extract_text_from_document.apply_async(
                args=[document_uuid, s3_url]
            )
            
            return {
                'success': True,
                'task_id': result.id,
                'document_uuid': document_uuid
            }
        except Exception as e:
            logger.error(f"Failed to submit document: {e}")
            return {'success': False, 'error': str(e)}
    
    def monitor_document_progress(self, document_uuid, timeout=300):
        """Monitor a single document's progress through pipeline"""
        start_time = time.time()
        stages = {
            'ocr': None,
            'chunking': None,
            'entity_extraction': None,
            'entity_resolution': None,
            'relationship_building': None
        }
        
        while time.time() - start_time < timeout:
            # Check Redis state
            state_key = f"doc:state:{document_uuid}"
            state = self.redis.get_dict(state_key)
            
            if state:
                for stage in stages:
                    if stage in state and state[stage].get('status') == 'completed':
                        if stages[stage] is None:
                            stages[stage] = time.time() - start_time
                            logger.info(f"Document {document_uuid[:8]}: {stage} completed in {stages[stage]:.2f}s")
                
                # Check if all stages complete
                if all(v is not None for v in stages.values()):
                    return {
                        'success': True,
                        'total_time': time.time() - start_time,
                        'stages': stages
                    }
            
            # Check database status
            session = next(self.db.get_session())
            try:
                result = session.execute(text("""
                    SELECT status, 
                           COUNT(DISTINCT dc.id) as chunks,
                           COUNT(DISTINCT em.id) as entities
                    FROM source_documents sd
                    LEFT JOIN document_chunks dc ON sd.document_uuid = dc.document_uuid
                    LEFT JOIN entity_mentions em ON sd.document_uuid = em.document_uuid
                    WHERE sd.document_uuid = :uuid
                    GROUP BY sd.status
                """), {'uuid': document_uuid})
                
                row = result.fetchone()
                if row and row.status == 'completed':
                    return {
                        'success': True,
                        'total_time': time.time() - start_time,
                        'stages': stages,
                        'final_counts': {
                            'chunks': row.chunks,
                            'entities': row.entities
                        }
                    }
            finally:
                session.close()
            
            time.sleep(5)
        
        return {
            'success': False,
            'total_time': timeout,
            'stages': stages,
            'error': 'Timeout'
        }
    
    def run_batch_test(self, batch_size):
        """Run test with specified batch size"""
        logger.info(f"\n{'='*70}")
        logger.info(f"Testing with batch size: {batch_size}")
        logger.info(f"{'='*70}")
        
        batch_result = {
            'batch_size': batch_size,
            'start_time': datetime.now().isoformat(),
            'documents': []
        }
        
        # Get test documents
        test_docs = self.get_test_documents(batch_size)
        logger.info(f"Selected {len(test_docs)} documents for testing")
        
        # Upload and submit documents
        submitted_docs = []
        submit_start = time.time()
        
        for doc in test_docs:
            logger.info(f"Processing: {doc['filename']} ({doc['size_mb']}MB)")
            
            # Upload to S3
            upload_result = self.upload_document_to_s3(doc['path'])
            if not upload_result['success']:
                continue
            
            # Create database record
            db_result = self.create_document_record(upload_result, doc)
            if not db_result['success']:
                continue
            
            # Submit for processing
            submit_result = self.submit_document_for_processing(
                upload_result['document_uuid'],
                upload_result['s3_url']
            )
            
            if submit_result['success']:
                submitted_docs.append({
                    'document_uuid': upload_result['document_uuid'],
                    'filename': doc['filename'],
                    'size_mb': doc['size_mb'],
                    'task_id': submit_result['task_id']
                })
        
        submit_time = time.time() - submit_start
        logger.info(f"Submitted {len(submitted_docs)} documents in {submit_time:.2f}s")
        
        # Monitor progress
        if batch_size == 1 and submitted_docs:
            # Detailed monitoring for single document
            doc_info = submitted_docs[0]
            logger.info(f"\nDetailed monitoring for: {doc_info['filename']}")
            progress = self.monitor_document_progress(doc_info['document_uuid'], timeout=600)
            
            batch_result['documents'].append({
                **doc_info,
                **progress
            })
        else:
            # Batch monitoring
            start_monitor = time.time()
            completed = 0
            timeout = 600  # 10 minutes
            
            while time.time() - start_monitor < timeout and completed < len(submitted_docs):
                for doc in submitted_docs:
                    if 'completed' not in doc:
                        progress = self.monitor_document_progress(doc['document_uuid'], timeout=10)
                        if progress['success']:
                            doc['completed'] = True
                            doc['processing_time'] = progress['total_time']
                            completed += 1
                            logger.info(f"Completed {completed}/{len(submitted_docs)}: {doc['filename']}")
                
                if completed < len(submitted_docs):
                    time.sleep(5)
            
            batch_result['documents'] = submitted_docs
        
        batch_result['end_time'] = datetime.now().isoformat()
        batch_result['total_time'] = time.time() - submit_start
        batch_result['completed_count'] = sum(1 for d in submitted_docs if d.get('completed', False))
        
        self.results['batch_results'].append(batch_result)
        
        return batch_result
    
    def save_results(self):
        """Save test results to file"""
        filename = f"batch_performance_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(filename, 'w') as f:
            json.dump(self.results, f, indent=2)
        logger.info(f"\nResults saved to: {filename}")
        return filename

def main():
    """Run batch performance tests"""
    print("="*70)
    print("DOCUMENT PROCESSING BATCH PERFORMANCE TEST")
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70)
    
    tester = BatchPerformanceTester()
    
    # Create test project
    tester.create_test_project()
    
    # Run tests with increasing batch sizes
    batch_sizes = [1, 3, 10, 20]
    
    for batch_size in batch_sizes:
        try:
            result = tester.run_batch_test(batch_size)
            
            # Summary for this batch
            print(f"\nBatch Size {batch_size} Summary:")
            print(f"  Documents submitted: {len(result['documents'])}")
            print(f"  Documents completed: {result['completed_count']}")
            print(f"  Total time: {result['total_time']:.2f}s")
            
            if batch_size > 1 and result['completed_count'] > 0:
                avg_time = result['total_time'] / result['completed_count']
                print(f"  Average time per document: {avg_time:.2f}s")
            
            # Wait between batches
            if batch_size < batch_sizes[-1]:
                print(f"\nWaiting 30 seconds before next batch...")
                time.sleep(30)
                
        except Exception as e:
            logger.error(f"Batch {batch_size} failed: {e}")
            import traceback
            traceback.print_exc()
    
    # Save results
    results_file = tester.save_results()
    
    print("\n" + "="*70)
    print("PERFORMANCE TEST COMPLETE")
    print(f"Results saved to: {results_file}")
    print("="*70)

if __name__ == "__main__":
    main()