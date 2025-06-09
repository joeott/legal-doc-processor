#!/usr/bin/env python3
"""
Process a single document through the pipeline with detailed monitoring.
Based on batch_submit_2_documents.py but focused on monitoring each stage.
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
os.environ['PARAMETER_DEBUG'] = 'true'
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

class SingleDocumentProcessor:
    def __init__(self):
        self.db = DatabaseManager(validate_conformance=False)
        self.redis = get_redis_manager()
        self.s3_manager = S3StorageManager()
        self.test_project_id = None
        self.monitoring_data = {
            'start_time': datetime.now().isoformat(),
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
        logger.info(f"\n{'='*60}")
        logger.info(f"STAGE: {stage_name}")
        logger.info(f"SCRIPT: {script}")
        logger.info(f"FUNCTION: {function}")
        logger.info(f"STATUS: {status}")
        if details:
            logger.info(f"DETAILS: {json.dumps(details, indent=2)}")
        logger.info(f"{'='*60}\n")
    
    def create_test_project(self):
        """Create a project for testing"""
        self.log_stage('Project Creation', 'scripts/db.py', 
                      'DatabaseManager.execute', 'started')
        
        session = next(self.db.get_session())
        try:
            project_name = f"SINGLE_DOC_MONITOR_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
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
            
            self.log_stage('Project Creation', 'scripts/db.py', 
                          'DatabaseManager.execute', 'completed',
                          {'project_id': self.test_project_id, 'project_uuid': project_uuid})
            
            return self.test_project_id, project_uuid
            
        finally:
            session.close()
    
    def process_document(self, file_path):
        """Process a single document"""
        filename = os.path.basename(file_path)
        doc_uuid = str(uuid.uuid4())
        
        self.log_stage('Document Processing', 'scripts/intake_service.py', 
                      'create_document_with_validation', 'started',
                      {'filename': filename, 'document_uuid': doc_uuid})
        
        try:
            # Step 1: Upload to S3
            self.log_stage('S3 Upload', 'scripts/s3_storage.py', 
                          'upload_document_with_uuid_naming', 'started')
            
            upload_result = self.s3_manager.upload_document_with_uuid_naming(
                local_file_path=file_path,
                document_uuid=doc_uuid,
                original_filename=filename
            )
            
            self.log_stage('S3 Upload', 'scripts/s3_storage.py', 
                          'upload_document_with_uuid_naming', 'completed',
                          {
                              's3_key': upload_result['s3_key'],
                              's3_bucket': upload_result['s3_bucket'],
                              'file_size': upload_result['file_size']
                          })
            
            # Step 2: Create document record
            self.log_stage('Database Record Creation', 'scripts/intake_service.py', 
                          'create_document_with_validation', 'started')
            
            doc_data = {
                'document_uuid': doc_uuid,
                'project_fk_id': self.test_project_id,
                'original_file_name': filename,
                's3_key': upload_result['s3_key'],
                's3_bucket': upload_result['s3_bucket'],
                's3_region': upload_result['s3_region'],
                'file_size_bytes': upload_result['file_size'],
                'detected_file_type': 'pdf',
                'metadata': {
                    'upload_timestamp': datetime.now().isoformat(),
                    'monitoring_run': True,
                    'md5_hash': upload_result['md5_hash']
                }
            }
            
            created_uuid = create_document_with_validation(
                document_data=doc_data,
                db_manager=self.db,
                s3_manager=self.s3_manager
            )
            
            self.log_stage('Database Record Creation', 'scripts/intake_service.py', 
                          'create_document_with_validation', 'completed',
                          {'document_uuid': created_uuid})
            
            # Step 3: Trigger OCR processing
            self.log_stage('OCR Task Submission', 'scripts/pdf_tasks.py', 
                          'extract_text_from_document.delay', 'started')
            
            # Set Redis metadata for project association
            self.redis.set(
                f"doc:metadata:{doc_uuid}",
                json.dumps({'project_uuid': self.test_project_id}),
                ex=3600  # 1 hour TTL
            )
            
            # Trigger the OCR task
            result = extract_text_from_document.delay(doc_uuid)
            
            self.log_stage('OCR Task Submission', 'scripts/pdf_tasks.py', 
                          'extract_text_from_document.delay', 'completed',
                          {'task_id': result.id, 'document_uuid': doc_uuid})
            
            # Monitor the processing
            return self.monitor_processing(doc_uuid, result.id)
            
        except Exception as e:
            self.log_stage('Document Processing', 'ERROR', 
                          str(type(e).__name__), 'failed',
                          {'error': str(e)})
            logger.error(f"Failed to process document: {e}")
            return False
    
    def monitor_processing(self, doc_uuid, task_id):
        """Monitor document processing progress"""
        self.log_stage('Pipeline Monitoring', 'scripts/cli/monitor.py', 
                      'monitor_processing', 'started',
                      {'document_uuid': doc_uuid, 'task_id': task_id})
        
        start_time = time.time()
        max_wait = 300  # 5 minutes
        last_status = None
        last_stage = None
        
        while time.time() - start_time < max_wait:
            try:
                # Check document status
                session = next(self.db.get_session())
                try:
                    # Get document status
                    doc_result = session.execute(text("""
                        SELECT status, celery_status, processing_status, stage, error_message
                        FROM source_documents
                        WHERE document_uuid = :doc_uuid
                    """), {'doc_uuid': doc_uuid})
                    
                    doc_row = doc_result.fetchone()
                    if doc_row:
                        current_status = doc_row.celery_status or doc_row.status
                        current_stage = doc_row.stage
                        
                        # Log status changes
                        if current_status != last_status or current_stage != last_stage:
                            self.log_stage('Status Update', 'source_documents', 
                                          'database_query', 'update',
                                          {
                                              'status': current_status,
                                              'stage': current_stage,
                                              'error': doc_row.error_message
                                          })
                            last_status = current_status
                            last_stage = current_stage
                        
                        # Check if completed or failed
                        if current_status in ['completed', 'failed', 'error']:
                            break
                    
                    # Check processing tasks
                    task_result = session.execute(text("""
                        SELECT stage, status, celery_task_id, error_message, created_at
                        FROM processing_tasks
                        WHERE document_uuid = :doc_uuid
                        ORDER BY created_at DESC
                        LIMIT 10
                    """), {'doc_uuid': doc_uuid})
                    
                    tasks = []
                    for task_row in task_result:
                        tasks.append({
                            'stage': task_row.stage,
                            'status': task_row.status,
                            'task_id': task_row.celery_task_id,
                            'error': task_row.error_message,
                            'created': task_row.created_at.isoformat() if task_row.created_at else None
                        })
                    
                    if tasks:
                        self.log_stage('Processing Tasks', 'processing_tasks', 
                                      'database_query', 'update',
                                      {'tasks': tasks[:5]})  # Show latest 5 tasks
                    
                finally:
                    session.close()
                
                # Check Redis state
                redis_state = self.redis.get(f"doc:state:{doc_uuid}")
                if redis_state:
                    state_data = json.loads(redis_state)
                    self.log_stage('Redis State', 'scripts/cache.py', 
                                  'redis.get', 'retrieved',
                                  {'pipeline_state': state_data})
                
            except Exception as e:
                logger.error(f"Error monitoring: {e}")
            
            time.sleep(5)
        
        # Final status check
        return self.check_final_status(doc_uuid)
    
    def check_final_status(self, doc_uuid):
        """Check final processing status and results"""
        self.log_stage('Final Status Check', 'scripts/db.py', 
                      'check_final_status', 'started')
        
        session = next(self.db.get_session())
        try:
            # Check chunks
            chunks_result = session.execute(text("""
                SELECT COUNT(*) as count, 
                       SUM(LENGTH(text)) as total_chars,
                       AVG(LENGTH(text)) as avg_chars
                FROM document_chunks
                WHERE document_uuid = :doc_uuid
            """), {'doc_uuid': doc_uuid})
            chunks_row = chunks_result.fetchone()
            
            # Check entities
            entities_result = session.execute(text("""
                SELECT COUNT(*) as count,
                       COUNT(DISTINCT entity_type) as types,
                       COUNT(DISTINCT canonical_entity_uuid) as canonical
                FROM entity_mentions
                WHERE document_uuid = :doc_uuid
            """), {'doc_uuid': doc_uuid})
            entities_row = entities_result.fetchone()
            
            # Check relationships
            relationships_result = session.execute(text("""
                SELECT COUNT(*) as count,
                       COUNT(DISTINCT relationship_type) as types
                FROM relationship_staging rs
                JOIN document_chunks dc ON rs.source_chunk_uuid = dc.chunk_uuid
                WHERE dc.document_uuid = :doc_uuid
            """), {'doc_uuid': doc_uuid})
            relationships_row = relationships_result.fetchone()
            
            # Get final document status
            final_result = session.execute(text("""
                SELECT status, celery_status, processing_status, stage, 
                       error_message, raw_extracted_text IS NOT NULL as has_text,
                       updated_at
                FROM source_documents
                WHERE document_uuid = :doc_uuid
            """), {'doc_uuid': doc_uuid})
            final_row = final_result.fetchone()
            
            self.log_stage('Final Status Check', 'scripts/db.py', 
                          'check_final_status', 'completed',
                          {
                              'document': {
                                  'status': final_row.status if final_row else None,
                                  'celery_status': final_row.celery_status if final_row else None,
                                  'stage': final_row.stage if final_row else None,
                                  'has_text': final_row.has_text if final_row else False,
                                  'error': final_row.error_message if final_row else None
                              },
                              'chunks': {
                                  'count': chunks_row.count if chunks_row else 0,
                                  'total_chars': chunks_row.total_chars if chunks_row else 0,
                                  'avg_chars': float(chunks_row.avg_chars) if chunks_row and chunks_row.avg_chars else 0
                              },
                              'entities': {
                                  'mentions': entities_row.count if entities_row else 0,
                                  'types': entities_row.types if entities_row else 0,
                                  'canonical': entities_row.canonical if entities_row else 0
                              },
                              'relationships': {
                                  'count': relationships_row.count if relationships_row else 0,
                                  'types': relationships_row.types if relationships_row else 0
                              }
                          })
            
            # Determine success
            success = (final_row and 
                      final_row.celery_status in ['completed', 'success'] and
                      chunks_row and chunks_row.count > 0)
            
            return success
            
        finally:
            session.close()
    
    def save_monitoring_report(self):
        """Save the monitoring report"""
        self.monitoring_data['end_time'] = datetime.now().isoformat()
        
        # Create the report document
        report_content = f"""# Context 459: Single Document Processing Monitor

## Date: {datetime.now().strftime('%B %d, %Y')}

## Executive Summary

This document provides detailed monitoring of a single document processed through the legal document pipeline, tracking each stage and the scripts/functions used.

## Document Details

- **File**: Paul, Michael - Lora Prop Disclosure Stmt 10-21-24.pdf
- **Processing Start**: {self.monitoring_data['start_time']}
- **Processing End**: {self.monitoring_data['end_time']}

## Processing Stages

"""
        
        # Add each stage
        for stage in self.monitoring_data['stages']:
            report_content += f"""
### {stage['stage']} - {stage['status'].upper()}

- **Time**: {stage['timestamp']}
- **Script**: `{stage['script']}`
- **Function**: `{stage['function']}`
"""
            if stage.get('details'):
                report_content += f"- **Details**:\n```json\n{json.dumps(stage['details'], indent=2)}\n```\n"
        
        # Add summary
        report_content += """
## Pipeline Flow Summary

Based on the monitoring, here's the order of script execution:

"""
        
        # Create script flow
        script_flow = {}
        for stage in self.monitoring_data['stages']:
            script = stage['script']
            if script not in script_flow:
                script_flow[script] = []
            script_flow[script].append(f"{stage['function']} ({stage['stage']})")
        
        for i, (script, functions) in enumerate(script_flow.items(), 1):
            report_content += f"{i}. **{script}**\n"
            for func in functions:
                report_content += f"   - {func}\n"
        
        # Save report
        report_path = f"/opt/legal-doc-processor/ai_docs/context_459_single_document_processing_monitor.md"
        with open(report_path, 'w') as f:
            f.write(report_content)
        
        logger.info(f"Monitoring report saved to: {report_path}")
        return report_path
    
    def run(self, document_path):
        """Run the complete process"""
        try:
            # Create project
            project_id, project_uuid = self.create_test_project()
            
            # Process document
            success = self.process_document(document_path)
            
            # Save report
            report_path = self.save_monitoring_report()
            
            if success:
                logger.info("\n✅ Document processing completed successfully!")
            else:
                logger.info("\n❌ Document processing failed or incomplete")
            
            return success
            
        except Exception as e:
            logger.error(f"Processing failed: {e}")
            self.save_monitoring_report()
            return False

def main():
    if len(sys.argv) > 1:
        document_path = sys.argv[1]
    else:
        document_path = "/opt/legal-doc-processor/input_docs/Paul, Michael (Acuity)/Paul, Michael - Lora Prop Disclosure Stmt 10-21-24.pdf"
    
    if not os.path.exists(document_path):
        logger.error(f"Document not found: {document_path}")
        return 1
    
    processor = SingleDocumentProcessor()
    success = processor.run(document_path)
    
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())