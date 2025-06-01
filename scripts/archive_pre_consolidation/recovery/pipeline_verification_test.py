#!/usr/bin/env python3
"""
Pipeline Verification Test
Processes a controlled batch of documents to verify the fix and collect metrics
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts.supabase_utils import get_supabase_client
from scripts.celery_tasks.ocr_tasks import process_ocr
import logging
from datetime import datetime
import time
import json

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class PipelineVerificationTest:
    def __init__(self):
        self.client = get_supabase_client()
        self.start_time = None
        self.submitted_documents = []
        self.metrics = {
            'total_documents': 0,
            'submitted': 0,
            'successful': 0,
            'failed': 0,
            'by_type': {},
            'by_status': {},
            'processing_times': []
        }
    
    def get_test_batch(self, size=100):
        """Get a diverse batch of documents for testing"""
        # Get a mix of different file types
        result = self.client.table('source_documents').select(
            'id, document_uuid, original_file_name, s3_key, s3_bucket, detected_file_type, project_fk_id, file_size_bytes'
        ).eq('initial_processing_status', 'pending').neq('s3_key', None).neq('s3_bucket', None).limit(size).execute()
        
        documents = result.data
        
        # Analyze document types
        type_counts = {}
        for doc in documents:
            file_type = doc['detected_file_type']
            type_counts[file_type] = type_counts.get(file_type, 0) + 1
        
        logger.info(f"\nTest batch composition ({len(documents)} documents):")
        for file_type, count in sorted(type_counts.items()):
            logger.info(f"  {file_type}: {count}")
        
        return documents
    
    def submit_documents(self, documents):
        """Submit documents to the pipeline"""
        logger.info(f"\nSubmitting {len(documents)} documents to pipeline...")
        self.start_time = datetime.now()
        
        for i, doc in enumerate(documents):
            try:
                # Update status to pending_ocr
                self.client.table('source_documents').update({
                    'initial_processing_status': 'pending_ocr',
                    'error_message': None,
                    'last_modified_at': datetime.now().isoformat()
                }).eq('id', doc['id']).execute()
                
                # Prepare task parameters
                s3_uri = f"s3://{doc['s3_bucket']}/{doc['s3_key']}"
                task_params = {
                    'document_uuid': doc['document_uuid'],
                    'source_doc_sql_id': doc['id'],
                    'file_path': s3_uri,
                    'file_name': doc['original_file_name'],
                    'detected_file_type': doc['detected_file_type'],
                    'project_sql_id': doc['project_fk_id'] or 0
                }
                
                # Submit to Celery
                task = process_ocr.apply_async(kwargs=task_params, queue='ocr')
                
                # Update with task ID
                self.client.table('source_documents').update({
                    'celery_task_id': task.id,
                    'celery_status': 'submitted'
                }).eq('id', doc['id']).execute()
                
                self.submitted_documents.append({
                    'document_uuid': doc['document_uuid'],
                    'file_name': doc['original_file_name'],
                    'file_type': doc['detected_file_type'],
                    'file_size': doc.get('file_size_bytes', 0),
                    'task_id': task.id,
                    'submitted_at': datetime.now()
                })
                
                self.metrics['submitted'] += 1
                
                # Small delay to avoid overwhelming the system
                if i % 10 == 0:
                    logger.info(f"  Progress: {i+1}/{len(documents)}")
                time.sleep(0.1)
                
            except Exception as e:
                logger.error(f"  Failed to submit {doc['original_file_name']}: {e}")
                self.metrics['failed'] += 1
        
        logger.info(f"Submission complete: {self.metrics['submitted']} submitted, {self.metrics['failed']} failed")
    
    def wait_for_processing(self, timeout_minutes=10):
        """Wait for documents to process and collect metrics"""
        logger.info(f"\nWaiting up to {timeout_minutes} minutes for processing...")
        
        timeout = datetime.now().timestamp() + (timeout_minutes * 60)
        check_interval = 30  # seconds
        
        while datetime.now().timestamp() < timeout:
            # Check status of submitted documents
            doc_uuids = [d['document_uuid'] for d in self.submitted_documents]
            
            result = self.client.table('source_documents').select(
                'document_uuid, initial_processing_status, error_message'
            ).in_('document_uuid', doc_uuids).execute()
            
            status_counts = {}
            for doc in result.data:
                status = doc['initial_processing_status']
                status_counts[status] = status_counts.get(status, 0) + 1
            
            # Check if all documents are done processing
            processing_statuses = ['pending_ocr', 'ocr_processing', 'ocr_complete', 
                                 'text_processing', 'entity_processing']
            still_processing = sum(status_counts.get(s, 0) for s in processing_statuses)
            
            logger.info(f"\nStatus at {datetime.now().strftime('%H:%M:%S')}:")
            for status, count in sorted(status_counts.items()):
                logger.info(f"  {status}: {count}")
            
            if still_processing == 0:
                logger.info("All documents finished processing!")
                break
            
            logger.info(f"Still processing: {still_processing} documents")
            time.sleep(check_interval)
    
    def analyze_results(self):
        """Analyze the results and generate metrics"""
        logger.info("\n" + "="*60)
        logger.info("ANALYZING RESULTS")
        logger.info("="*60)
        
        # Get final status of all submitted documents
        doc_uuids = [d['document_uuid'] for d in self.submitted_documents]
        
        result = self.client.table('source_documents').select(
            'document_uuid, original_file_name, detected_file_type, initial_processing_status, error_message'
        ).in_('document_uuid', doc_uuids).execute()
        
        # Build lookup map
        results_map = {doc['document_uuid']: doc for doc in result.data}
        
        # Analyze each document
        success_statuses = ['completed', 'neo4j_node_created', 'graph_ready']
        
        for submitted_doc in self.submitted_documents:
            doc_result = results_map.get(submitted_doc['document_uuid'])
            if doc_result:
                status = doc_result['initial_processing_status']
                file_type = doc_result['detected_file_type']
                
                # Track by status
                self.metrics['by_status'][status] = self.metrics['by_status'].get(status, 0) + 1
                
                # Track by file type
                if file_type not in self.metrics['by_type']:
                    self.metrics['by_type'][file_type] = {'total': 0, 'success': 0, 'failed': 0}
                
                self.metrics['by_type'][file_type]['total'] += 1
                
                if status in success_statuses:
                    self.metrics['successful'] += 1
                    self.metrics['by_type'][file_type]['success'] += 1
                elif doc_result['error_message']:
                    self.metrics['failed'] += 1
                    self.metrics['by_type'][file_type]['failed'] += 1
        
        self.metrics['total_documents'] = len(self.submitted_documents)
        
        # Calculate processing time
        if self.start_time:
            total_time = (datetime.now() - self.start_time).total_seconds()
            self.metrics['total_processing_time'] = total_time
            self.metrics['avg_processing_time'] = total_time / len(self.submitted_documents) if self.submitted_documents else 0
    
    def generate_report(self):
        """Generate a detailed report of the test results"""
        logger.info("\n" + "="*60)
        logger.info("PIPELINE VERIFICATION REPORT")
        logger.info("="*60)
        
        # Overall metrics
        total = self.metrics['total_documents']
        successful = self.metrics['successful']
        failed = self.metrics['failed']
        success_rate = (successful / total * 100) if total > 0 else 0
        
        logger.info(f"\nOVERALL RESULTS:")
        logger.info(f"  Total documents: {total}")
        logger.info(f"  Successfully processed: {successful} ({success_rate:.1f}%)")
        logger.info(f"  Failed: {failed} ({failed/total*100:.1f}%)" if total > 0 else "  Failed: 0")
        logger.info(f"  Success rate: {success_rate:.1f}%")
        
        if 'total_processing_time' in self.metrics:
            logger.info(f"\nPROCESSING TIME:")
            logger.info(f"  Total time: {self.metrics['total_processing_time']:.1f} seconds")
            logger.info(f"  Average per document: {self.metrics['avg_processing_time']:.1f} seconds")
        
        # Results by file type
        logger.info(f"\nRESULTS BY FILE TYPE:")
        for file_type, stats in sorted(self.metrics['by_type'].items()):
            success_rate = (stats['success'] / stats['total'] * 100) if stats['total'] > 0 else 0
            logger.info(f"  {file_type}:")
            logger.info(f"    Total: {stats['total']}")
            logger.info(f"    Success: {stats['success']} ({success_rate:.1f}%)")
            logger.info(f"    Failed: {stats['failed']}")
        
        # Results by status
        logger.info(f"\nFINAL STATUS DISTRIBUTION:")
        for status, count in sorted(self.metrics['by_status'].items()):
            percentage = (count / total * 100) if total > 0 else 0
            logger.info(f"  {status}: {count} ({percentage:.1f}%)")
        
        # Save detailed report
        report_path = f"pipeline_verification_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_path, 'w') as f:
            json.dump(self.metrics, f, indent=2)
        logger.info(f"\nDetailed report saved to: {report_path}")
        
        return success_rate

def main():
    """Run the pipeline verification test"""
    
    # Get test batch size from command line or default to 100
    batch_size = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    
    logger.info("STARTING PIPELINE VERIFICATION TEST")
    logger.info(f"Batch size: {batch_size} documents")
    
    # Create test instance
    test = PipelineVerificationTest()
    
    # Get test batch
    documents = test.get_test_batch(batch_size)
    if not documents:
        logger.error("No documents found to test!")
        return
    
    # Submit documents
    test.submit_documents(documents)
    
    # Wait for processing
    test.wait_for_processing(timeout_minutes=10)
    
    # Analyze results
    test.analyze_results()
    
    # Generate report
    success_rate = test.generate_report()
    
    # Final verdict
    logger.info("\n" + "="*60)
    if success_rate >= 90:
        logger.info("✅ VERIFICATION PASSED - Pipeline is working correctly!")
    elif success_rate >= 70:
        logger.info("⚠️  VERIFICATION PARTIAL - Pipeline needs improvement")
    else:
        logger.info("❌ VERIFICATION FAILED - Pipeline has issues")
    logger.info("="*60)

if __name__ == "__main__":
    main()