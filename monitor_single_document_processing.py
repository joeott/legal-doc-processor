#!/usr/bin/env python3
"""
Monitor single document processing through the pipeline with detailed stage tracking.
This script processes one document and logs each stage for compliance verification.
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

# Setup environment
os.environ['FORCE_PROCESSING'] = 'true'
os.environ['SKIP_PDF_PREPROCESSING'] = 'true'
os.environ['VALIDATION_REDIS_METADATA_LEVEL'] = 'optional'
os.environ['VALIDATION_PROJECT_ASSOCIATION_LEVEL'] = 'optional'

from scripts.db import DatabaseManager
from scripts.cache import get_redis_manager
from scripts.pdf_tasks import extract_text_from_document
from scripts.intake_service import create_document_with_validation
from scripts.s3_storage import S3StorageManager
from sqlalchemy import text

# Configure detailed logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class PipelineMonitor:
    def __init__(self, document_path):
        self.document_path = document_path
        self.document_uuid = None
        self.project_uuid = None
        self.db = DatabaseManager(validate_conformance=False)
        self.redis = get_redis_manager()
        self.s3_manager = S3StorageManager()
        self.monitoring_data = {
            'start_time': datetime.now().isoformat(),
            'document_path': document_path,
            'stages': []
        }
        
    def log_stage(self, stage_name, script, function, status, details=None):
        """Log a processing stage"""
        stage_data = {
            'timestamp': datetime.now().isoformat(),
            'stage': stage_name,
            'script': script,
            'function': function,
            'status': status,
            'details': details or {}
        }
        self.monitoring_data['stages'].append(stage_data)
        logger.info(f"STAGE: {stage_name} | SCRIPT: {script} | FUNCTION: {function} | STATUS: {status}")
        if details:
            logger.info(f"DETAILS: {json.dumps(details, indent=2)}")
    
    def create_test_project(self):
        """Create a project for testing"""
        self.log_stage('Project Creation', 'monitor_single_document_processing.py', 
                      'create_test_project', 'started')
        
        session = next(self.db.get_session())
        try:
            project_name = f"MONITOR_TEST_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            self.project_uuid = str(uuid.uuid4())
            
            result = session.execute(text("""
                INSERT INTO projects (project_id, name, active, created_at)
                VALUES (:project_id, :name, true, NOW())
                RETURNING id
            """), {
                'project_id': self.project_uuid,
                'name': project_name
            })
            
            project_id = result.scalar()
            session.commit()
            
            self.log_stage('Project Creation', 'scripts/db.py', 
                          'DatabaseManager.execute', 'completed',
                          {'project_uuid': self.project_uuid, 'project_id': project_id})
            return project_id
            
        except Exception as e:
            self.log_stage('Project Creation', 'scripts/db.py', 
                          'DatabaseManager.execute', 'failed',
                          {'error': str(e)})
            raise
        finally:
            session.close()
    
    def upload_to_s3(self):
        """Upload document to S3"""
        self.log_stage('S3 Upload', 'scripts/s3_storage.py', 
                      'S3StorageManager.upload_file', 'started')
        
        try:
            filename = os.path.basename(self.document_path)
            s3_key = f"documents/{self.project_uuid}/{filename}"
            
            # Upload file
            result = self.s3_manager.upload_file(
                file_path=self.document_path,
                s3_key=s3_key
            )
            
            if result['success']:
                self.log_stage('S3 Upload', 'scripts/s3_storage.py', 
                             'S3StorageManager.upload_file', 'completed',
                             {'s3_key': s3_key, 'bucket': result.get('bucket', 'N/A')})
                return s3_key
            else:
                raise Exception(result.get('error', 'Unknown S3 error'))
                
        except Exception as e:
            self.log_stage('S3 Upload', 'scripts/s3_storage.py', 
                          'S3StorageManager.upload_file', 'failed',
                          {'error': str(e)})
            raise
    
    def create_document_record(self, s3_key, project_id):
        """Create document record in database"""
        self.log_stage('Document Creation', 'scripts/intake_service.py', 
                      'create_document_with_validation', 'started')
        
        try:
            # Prepare document data
            doc_data = {
                'document_uuid': str(uuid.uuid4()),
                'project_fk_id': project_id,
                'project_uuid': self.project_uuid,
                'original_file_name': os.path.basename(self.document_path),
                's3_key': s3_key,
                's3_bucket': os.environ.get('S3_PRIMARY_DOCUMENT_BUCKET', 'test-bucket'),
                's3_region': os.environ.get('S3_BUCKET_REGION', 'us-east-2'),
                'file_size_bytes': os.path.getsize(self.document_path),
                'detected_file_type': 'pdf',
                'metadata': {
                    'upload_timestamp': datetime.now().isoformat(),
                    'monitoring_run': True
                }
            }
            
            # Create document
            doc_uuid = create_document_with_validation(
                document_data=doc_data,
                db_manager=self.db,
                s3_manager=self.s3_manager
            )
            
            self.document_uuid = doc_uuid
            self.log_stage('Document Creation', 'scripts/intake_service.py', 
                          'create_document_with_validation', 'completed',
                          {'document_uuid': doc_uuid})
            return doc_uuid
            
        except Exception as e:
            self.log_stage('Document Creation', 'scripts/intake_service.py', 
                          'create_document_with_validation', 'failed',
                          {'error': str(e)})
            raise
    
    def trigger_ocr_processing(self):
        """Trigger OCR processing via Celery"""
        self.log_stage('OCR Processing', 'scripts/pdf_tasks.py', 
                      'extract_text_from_document.delay', 'started')
        
        try:
            # Trigger async OCR task
            result = extract_text_from_document.delay(str(self.document_uuid))
            
            self.log_stage('OCR Processing', 'scripts/pdf_tasks.py', 
                          'extract_text_from_document.delay', 'triggered',
                          {'task_id': result.id, 'document_uuid': str(self.document_uuid)})
            
            # Monitor task progress
            return self.monitor_task_progress(result)
            
        except Exception as e:
            self.log_stage('OCR Processing', 'scripts/pdf_tasks.py', 
                          'extract_text_from_document.delay', 'failed',
                          {'error': str(e)})
            raise
    
    def monitor_task_progress(self, celery_result):
        """Monitor Celery task progress"""
        start_time = time.time()
        timeout = 300  # 5 minutes
        
        while time.time() - start_time < timeout:
            # Check task status
            if celery_result.ready():
                if celery_result.successful():
                    result_data = celery_result.result
                    self.log_stage('Task Monitoring', 'celery', 
                                  'AsyncResult.result', 'completed',
                                  {'task_id': celery_result.id, 'result': str(result_data)[:200]})
                    return True
                else:
                    error = str(celery_result.info)
                    self.log_stage('Task Monitoring', 'celery', 
                                  'AsyncResult.result', 'failed',
                                  {'task_id': celery_result.id, 'error': error})
                    return False
            
            # Check document status in database
            session = next(self.db.get_session())
            try:
                result = session.execute(text("""
                    SELECT status, celery_status, processing_status, stage, error_message
                    FROM source_documents
                    WHERE document_uuid = :doc_uuid
                """), {'doc_uuid': self.document_uuid})
                
                row = result.fetchone()
                if row:
                    logger.info(f"Document Status: {row.status} | Celery: {row.celery_status} | Stage: {row.stage}")
                    
                # Check processing tasks
                task_result = session.execute(text("""
                    SELECT stage, status, celery_task_id, error_message
                    FROM processing_tasks
                    WHERE document_uuid = :doc_uuid
                    ORDER BY created_at DESC
                    LIMIT 5
                """), {'doc_uuid': self.document_uuid})
                
                for task_row in task_result:
                    logger.info(f"  Task: {task_row.stage} - {task_row.status}")
                
            finally:
                session.close()
            
            time.sleep(5)
        
        self.log_stage('Task Monitoring', 'celery', 
                      'AsyncResult.result', 'timeout',
                      {'task_id': celery_result.id, 'timeout_seconds': timeout})
        return False
    
    def check_pipeline_stages(self):
        """Check all pipeline stages after processing"""
        self.log_stage('Pipeline Verification', 'monitor_single_document_processing.py', 
                      'check_pipeline_stages', 'started')
        
        session = next(self.db.get_session())
        try:
            # Check document chunks
            chunks_result = session.execute(text("""
                SELECT COUNT(*) as chunk_count
                FROM document_chunks
                WHERE document_uuid = :doc_uuid
            """), {'doc_uuid': self.document_uuid})
            chunk_count = chunks_result.scalar()
            
            # Check entity mentions
            entities_result = session.execute(text("""
                SELECT COUNT(*) as entity_count
                FROM entity_mentions
                WHERE document_uuid = :doc_uuid
            """), {'doc_uuid': self.document_uuid})
            entity_count = entities_result.scalar()
            
            # Check canonical entities
            canonical_result = session.execute(text("""
                SELECT COUNT(DISTINCT ce.id) as canonical_count
                FROM canonical_entities ce
                JOIN entity_mentions em ON em.canonical_entity_uuid = ce.canonical_entity_uuid
                WHERE em.document_uuid = :doc_uuid
            """), {'doc_uuid': self.document_uuid})
            canonical_count = canonical_result.scalar()
            
            # Check relationships
            relationships_result = session.execute(text("""
                SELECT COUNT(*) as relationship_count
                FROM relationship_staging rs
                JOIN document_chunks dc ON rs.source_chunk_uuid = dc.chunk_uuid
                WHERE dc.document_uuid = :doc_uuid
            """), {'doc_uuid': self.document_uuid})
            relationship_count = relationships_result.scalar()
            
            self.log_stage('Pipeline Verification', 'scripts/db.py', 
                          'DatabaseManager.execute', 'completed',
                          {
                              'chunks': chunk_count,
                              'entity_mentions': entity_count,
                              'canonical_entities': canonical_count,
                              'relationships': relationship_count
                          })
            
        finally:
            session.close()
    
    def save_monitoring_report(self):
        """Save monitoring report to file"""
        self.monitoring_data['end_time'] = datetime.now().isoformat()
        
        report_path = f"/opt/legal-doc-processor/ai_docs/context_459_single_document_processing_monitor_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        with open(report_path, 'w') as f:
            json.dump(self.monitoring_data, f, indent=2)
        
        logger.info(f"Monitoring report saved to: {report_path}")
        return report_path
    
    def run(self):
        """Run the complete monitoring process"""
        try:
            # Step 1: Create project
            project_id = self.create_test_project()
            
            # Step 2: Upload to S3
            s3_key = self.upload_to_s3()
            
            # Step 3: Create document record
            doc_uuid = self.create_document_record(s3_key, project_id)
            
            # Step 4: Trigger OCR processing
            ocr_success = self.trigger_ocr_processing()
            
            # Step 5: Wait a bit for pipeline to complete
            if ocr_success:
                logger.info("Waiting 30 seconds for pipeline to complete...")
                time.sleep(30)
            
            # Step 6: Check pipeline stages
            self.check_pipeline_stages()
            
            # Step 7: Save report
            report_path = self.save_monitoring_report()
            
            return True
            
        except Exception as e:
            logger.error(f"Pipeline monitoring failed: {e}")
            self.monitoring_data['error'] = str(e)
            self.save_monitoring_report()
            return False

def main():
    """Main entry point"""
    if len(sys.argv) > 1:
        document_path = sys.argv[1]
    else:
        # Default document
        document_path = "/opt/legal-doc-processor/input_docs/Paul, Michael (Acuity)/Paul, Michael - Lora Prop Disclosure Stmt 10-21-24.pdf"
    
    if not os.path.exists(document_path):
        logger.error(f"Document not found: {document_path}")
        return 1
    
    logger.info(f"Starting pipeline monitoring for: {document_path}")
    
    monitor = PipelineMonitor(document_path)
    success = monitor.run()
    
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())