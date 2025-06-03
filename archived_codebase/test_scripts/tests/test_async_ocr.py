#!/usr/bin/env python3
"""
Test script for async OCR processing with Textract.
"""

import os
import sys
import time
import uuid
from pathlib import Path

# Setup Python path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Load environment
from dotenv import load_dotenv
env_path = Path(__file__).parent.parent.parent / '.env'
load_dotenv(env_path)

import logging
from scripts.pdf_tasks import process_pdf_document, extract_text_from_document
from scripts.db import DatabaseManager
from scripts.cache import get_redis_manager, CacheKeys
from scripts.core.schemas import SourceDocumentModel, ProcessingStatus
from scripts.textract_job_manager import get_job_manager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_async_ocr():
    """Test async OCR processing flow."""
    logger.info("Starting async OCR test...")
    
    # Create test document
    db_manager = DatabaseManager(validate_conformance=False)
    redis_manager = get_redis_manager()
    
    # Test document UUID
    doc_uuid = str(uuid.uuid4())
    project_uuid = str(uuid.uuid4())
    
    # Create source document
    doc_model = SourceDocumentModel(
        document_uuid=doc_uuid,
        project_uuid=project_uuid,
        original_file_name="test_document.pdf",
        s3_bucket="samu-docs-private-upload",
        s3_key="test/test_document.pdf",
        processing_status="pending"
    )
    
    # Store in database
    logger.info(f"Creating document {doc_uuid}")
    result = db_manager.create_source_document(doc_model)
    if not result:
        logger.error("Failed to create source document")
        return
    
    # Simulate S3 path
    s3_path = f"s3://{doc_model.s3_bucket}/{doc_model.s3_key}"
    
    # Test 1: Start async OCR task
    logger.info("Testing async OCR task...")
    ocr_task = extract_text_from_document.apply_async(
        args=[doc_uuid, s3_path]
    )
    
    # Wait a moment and check state
    time.sleep(2)
    state_key = CacheKeys.DOC_STATE.format(document_uuid=doc_uuid)
    state = redis_manager.get_dict(state_key)
    
    logger.info(f"Document state after OCR start: {state}")
    
    # Check if job was started
    if state and state.get('ocr', {}).get('status') == 'processing':
        job_id = state['ocr'].get('metadata', {}).get('job_id')
        logger.info(f"✅ OCR job started successfully: {job_id}")
    else:
        logger.error("❌ OCR job not started properly")
    
    # Test 2: Check job manager
    job_manager = get_job_manager()
    
    # Get document from DB to check Textract fields
    doc = db_manager.get_source_document(doc_uuid)
    if doc and doc.textract_job_id:
        logger.info(f"✅ Textract job ID stored in database: {doc.textract_job_id}")
        logger.info(f"   Status: {doc.textract_job_status}")
    else:
        logger.warning("⚠️  Textract job ID not found in database")
    
    # Test 3: Full pipeline test
    logger.info("\nTesting full async pipeline...")
    pipeline_result = process_pdf_document.apply_async(
        args=[doc_uuid, s3_path, project_uuid],
        kwargs={'document_metadata': {'test': True}}
    )
    
    # Wait and check pipeline state
    time.sleep(2)
    state = redis_manager.get_dict(state_key)
    pipeline_state = state.get('pipeline', {}) if state else {}
    
    if pipeline_state.get('status') == 'processing':
        logger.info("✅ Pipeline started successfully in async mode")
        logger.info(f"   OCR task ID: {pipeline_state.get('metadata', {}).get('ocr_task_id')}")
    else:
        logger.error("❌ Pipeline not started properly")
    
    # Clean up
    logger.info("\nCleaning up test data...")
    db_manager.delete("source_documents", {"document_uuid": doc_uuid})
    redis_manager.delete(state_key)
    
    logger.info("\n✅ Async OCR test completed!")

if __name__ == "__main__":
    test_async_ocr()