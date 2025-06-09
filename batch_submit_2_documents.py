#!/usr/bin/env python3
"""
Submit exactly 2 documents for processing through the legal document pipeline.
Modified from batch_performance_test.py to process a fixed batch of 2 documents.
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
os.environ['PARAMETER_DEBUG'] = 'true'  # Enable debug logging
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

class DocumentSubmitter:
    def __init__(self):
        self.db = DatabaseManager(validate_conformance=False)
        self.redis = get_redis_manager()
        self.s3_manager = S3StorageManager()
        self.test_project_id = None
        self.submitted_documents = []
        
    def create_test_project(self):
        """Create a project for testing"""
        session = next(self.db.get_session())
        try:
            project_name = f"BATCH_2_DOCS_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
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
    
    def get_test_documents(self):
        """Get exactly 2 PDF documents for testing"""
        pdf_files = []
        
        # First, check test_single_doc directory
        test_doc_path = "/opt/legal-doc-processor/test_single_doc/Paul, Michael - Lora Prop Disclosure Stmt 10-21-24.pdf"
        if os.path.exists(test_doc_path):
            pdf_files.append({
                'path': test_doc_path,
                'filename': 'Paul, Michael - Lora Prop Disclosure Stmt 10-21-24.pdf',
                'size_mb': round(os.path.getsize(test_doc_path) / (1024*1024), 2)
            })
        
        # Then get one more from input_docs
        input_docs_path = "/opt/legal-doc-processor/input_docs/Paul, Michael (Acuity)"
        if os.path.exists(input_docs_path):
            # Get the first PDF from the main directory
            for file in os.listdir(input_docs_path):
                if file.lower().endswith('.pdf') and len(pdf_files) < 2:
                    full_path = os.path.join(input_docs_path, file)
                    try:
                        file_size = os.path.getsize(full_path)
                        pdf_files.append({
                            'path': full_path,
                            'filename': file,
                            'size_mb': round(file_size / (1024*1024), 2)
                        })
                        if len(pdf_files) >= 2:
                            break
                    except:
                        pass
        
        return pdf_files[:2]  # Ensure we only return 2
    
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
                's3_bucket': s3_bucket,
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
                s3_bucket=doc_info['s3_bucket'],
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
    
    def submit_batch(self):
        """Submit exactly 2 documents for processing"""
        logger.info("="*70)
        logger.info("SUBMITTING 2 DOCUMENTS FOR PROCESSING")
        logger.info(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("="*70)
        
        # Get test documents
        test_docs = self.get_test_documents()
        if len(test_docs) < 2:
            logger.error(f"Could only find {len(test_docs)} documents. Need 2.")
            return False
        
        logger.info(f"\nFound {len(test_docs)} documents to process:")
        for doc in test_docs:
            logger.info(f"  - {doc['filename']} ({doc['size_mb']}MB)")
        
        # Process each document
        for i, doc in enumerate(test_docs, 1):
            logger.info(f"\n--- Processing Document {i}/2 ---")
            logger.info(f"File: {doc['filename']}")
            
            # Upload to S3
            logger.info("Uploading to S3...")
            upload_result = self.upload_document_to_s3(doc['path'])
            if not upload_result['success']:
                logger.error(f"Failed to upload: {upload_result.get('error')}")
                continue
            
            logger.info(f"  Document UUID: {upload_result['document_uuid']}")
            logger.info(f"  S3 URL: {upload_result['s3_url']}")
            
            # Create database record
            logger.info("Creating database record...")
            db_result = self.create_document_record(upload_result, doc)
            if not db_result['success']:
                logger.error(f"Failed to create DB record: {db_result.get('error')}")
                continue
            
            logger.info(f"  Database ID: {db_result['document_id']}")
            
            # Submit for processing
            logger.info("Submitting to Celery pipeline...")
            submit_result = self.submit_document_for_processing(
                upload_result['document_uuid'],
                upload_result['s3_url']
            )
            
            if submit_result['success']:
                logger.info(f"  Task ID: {submit_result['task_id']}")
                self.submitted_documents.append({
                    'document_uuid': upload_result['document_uuid'],
                    'filename': doc['filename'],
                    'size_mb': doc['size_mb'],
                    'task_id': submit_result['task_id'],
                    's3_url': upload_result['s3_url'],
                    'submitted_at': datetime.now().isoformat()
                })
            else:
                logger.error(f"Failed to submit: {submit_result.get('error')}")
        
        return True
    
    def print_summary(self):
        """Print summary of submitted documents"""
        logger.info("\n" + "="*70)
        logger.info("SUBMISSION SUMMARY")
        logger.info("="*70)
        
        if not self.submitted_documents:
            logger.info("No documents were successfully submitted.")
            return
        
        logger.info(f"Project ID: {self.test_project_id}")
        logger.info(f"Documents submitted: {len(self.submitted_documents)}")
        
        for i, doc in enumerate(self.submitted_documents, 1):
            logger.info(f"\nDocument {i}:")
            logger.info(f"  Filename: {doc['filename']}")
            logger.info(f"  UUID: {doc['document_uuid']}")
            logger.info(f"  Task ID: {doc['task_id']}")
            logger.info(f"  Size: {doc['size_mb']}MB")
            logger.info(f"  Submitted: {doc['submitted_at']}")
        
        logger.info("\n" + "-"*70)
        logger.info("MONITORING COMMANDS:")
        logger.info("-"*70)
        
        logger.info("\n1. Monitor live pipeline status:")
        logger.info("   python scripts/cli/monitor.py live")
        
        logger.info("\n2. Check specific document status:")
        for doc in self.submitted_documents:
            logger.info(f"   python scripts/cli/monitor.py doc-status {doc['document_uuid']}")
        
        logger.info("\n3. Check Redis state:")
        for doc in self.submitted_documents:
            logger.info(f"   redis-cli get \"doc:state:{doc['document_uuid']}\" | jq .")
        
        logger.info("\n4. Query database for processing status:")
        logger.info("   psql -h localhost -p 5433 -U app_user -d legal_doc_processing -c \\")
        logger.info("   \"SELECT document_uuid, status, stage FROM processing_tasks \\")
        uuids = ','.join(["'" + d['document_uuid'] + "'" for d in self.submitted_documents])
        logger.info(f"    WHERE document_uuid IN ({uuids}) \\")
        logger.info("    ORDER BY created_at DESC;\"")
        
        logger.info("\n5. Check entity extraction results:")
        for doc in self.submitted_documents:
            logger.info(f"   psql -h localhost -p 5433 -U app_user -d legal_doc_processing -c \\")
            logger.info(f"   \"SELECT COUNT(*) FROM entity_mentions WHERE document_uuid = '{doc['document_uuid']}';\"")
        
        # Save submission info to file
        submission_file = f"batch_submission_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        submission_data = {
            'project_id': self.test_project_id,
            'submission_time': datetime.now().isoformat(),
            'documents': self.submitted_documents
        }
        
        with open(submission_file, 'w') as f:
            json.dump(submission_data, f, indent=2)
        
        logger.info(f"\nSubmission details saved to: {submission_file}")

def main():
    """Main entry point"""
    submitter = DocumentSubmitter()
    
    # Create test project
    submitter.create_test_project()
    
    # Submit documents
    if submitter.submit_batch():
        # Print summary
        submitter.print_summary()
    else:
        logger.error("Failed to submit documents")
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())