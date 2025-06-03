#!/usr/bin/env python3
"""Submit test document through Celery pipeline."""

import sys
import uuid
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.pdf_tasks import process_pdf_document
from scripts.db import DatabaseManager
from scripts.s3_storage import S3StorageManager
from scripts.core.schemas import SourceDocumentModel
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def create_test_pdf():
    """Create a minimal test PDF."""
    test_pdf_path = "/tmp/test_celery_doc.pdf"
    
    # Create a minimal valid PDF
    minimal_pdf = b'%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n3 0 obj\n<< /Type /Page /Parent 2 0 R /Resources 4 0 R /MediaBox [0 0 612 792] /Contents 5 0 R >>\nendobj\n4 0 obj\n<< /Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> >> >>\nendobj\n5 0 obj\n<< /Length 100 >>\nstream\nBT\n/F1 12 Tf\n50 750 Td\n(Test Legal Document) Tj\n50 700 Td\n(Case No: TEST-2024-001) Tj\nET\nendstream\nendobj\nxref\n0 6\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n0000000229 00000 n \n0000000328 00000 n \ntrailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n482\n%%EOF'
    
    with open(test_pdf_path, 'wb') as f:
        f.write(minimal_pdf)
    
    return test_pdf_path

def submit_test_document():
    """Submit a test document through the Celery pipeline."""
    
    logger.info("=== Celery Document Processing Test ===")
    
    try:
        # Create test PDF
        test_pdf_path = create_test_pdf()
        logger.info(f"Created test PDF: {test_pdf_path}")
        
        # Upload to S3
        s3_manager = S3StorageManager()
        doc_uuid = str(uuid.uuid4())
        s3_key = s3_manager.upload_document_with_uuid_naming(
            test_pdf_path,
            doc_uuid,
            'pdf'
        )
        logger.info(f"Uploaded to S3: {s3_key}")
        
        # Create database entry
        db = DatabaseManager()
        doc_model = SourceDocumentModel(
            document_uuid=uuid.UUID(doc_uuid),
            original_file_name="test_celery_doc.pdf",
            detected_file_type="application/pdf",
            s3_bucket=s3_manager.bucket_name,
            s3_key=s3_key,
            file_size_bytes=Path(test_pdf_path).stat().st_size,
            project_name="Celery Test Project",
            initial_processing_status="pending_intake",
            metadata={
                'test': True,
                'test_type': 'celery_submission',
                'timestamp': time.time()
            }
        )
        
        db_result = db.create_source_document(doc_model)
        if not db_result:
            logger.error("Failed to create document in database")
            return False
            
        logger.info(f"Created document in DB: {doc_uuid}")
        
        # Submit to Celery
        result = process_pdf_document.delay(
            document_uuid=doc_uuid,
            file_path=f"s3://{s3_manager.bucket_name}/{s3_key}",
            project_uuid=str(uuid.uuid4()),
            document_metadata={
                'name': 'Celery Test Document',
                'test': True,
                'submitted_at': time.time()
            }
        )
        
        logger.info(f"Submitted Celery task: {result.id}")
        logger.info(f"Document UUID: {doc_uuid}")
        logger.info("\nMonitoring Instructions:")
        logger.info("1. Check worker status: ./scripts/check_workers.sh")
        logger.info("2. Monitor logs: python scripts/monitor_logs.py tasks")
        logger.info(f"3. Track document: python scripts/monitor_logs.py document -d {doc_uuid}")
        logger.info(f"4. Check task status: celery -A scripts.celery_app inspect active")
        
        # Wait a bit and check initial status
        time.sleep(2)
        
        try:
            task_state = result.state
            logger.info(f"\nInitial task state: {task_state}")
            
            if task_state == 'PENDING':
                logger.info("Task is queued and waiting for a worker")
            elif task_state == 'STARTED':
                logger.info("Task has been picked up by a worker")
            elif task_state == 'SUCCESS':
                logger.info("Task completed successfully!")
                logger.info(f"Result: {result.get()}")
            elif task_state == 'FAILURE':
                logger.error("Task failed!")
                logger.error(f"Error: {result.info}")
                
        except Exception as e:
            logger.warning(f"Could not check task state: {e}")
            
        return True
        
    except Exception as e:
        logger.exception("Failed to submit test document")
        return False

if __name__ == "__main__":
    success = submit_test_document()
    sys.exit(0 if success else 1)