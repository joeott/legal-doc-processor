#!/usr/bin/env python3
"""Simple test to process document step by step"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Test parameters
doc_uuid = '0697af52-8bc6-4299-90ec-5d67b7eeb858'
bucket_name = 'samu-docs-private-upload'
s3_key = f'documents/{doc_uuid}.pdf'
file_path = f's3://{bucket_name}/{s3_key}'

logger.info(f"Testing OCR extraction for {file_path}")

# Step 1: Test OCR extraction directly
from scripts.ocr_extraction import extract_text_from_pdf
from scripts.db import DatabaseManager
from scripts.core.pdf_models import PDFDocumentModel, ProcessingStatus

try:
    # Create database manager
    db_manager = DatabaseManager(validate_conformance=False)
    
    # Get document from database
    with db_manager.get_session() as session:
        from sqlalchemy import text
        result = session.execute(
            text("SELECT * FROM source_documents WHERE document_uuid = :uuid"),
            {"uuid": doc_uuid}
        ).fetchone()
        
        if not result:
            logger.error(f"Document {doc_uuid} not found in database")
            sys.exit(1)
        
        doc_data = dict(result._mapping)
        logger.info(f"Found document: {doc_data['original_file_name']}")
        source_doc_id = doc_data['id']
    
    # Create PDFDocumentModel
    pdf_doc = PDFDocumentModel(
        document_uuid=doc_uuid,
        file_name=doc_data['original_file_name'],
        original_file_name=doc_data['original_file_name'],
        file_path=file_path,
        file_type='pdf',
        s3_key=s3_key,
        s3_bucket=bucket_name,
        project_uuid=doc_data['project_uuid'],
        status=ProcessingStatus.PROCESSING
    )
    
    logger.info("Created PDFDocumentModel successfully")
    
    # Extract text
    logger.info("Starting OCR extraction...")
    result = extract_text_from_pdf(
        pdf_path=file_path,
        document=pdf_doc,
        db_manager=db_manager,
        source_doc_sql_id=source_doc_id
    )
    
    logger.info(f"OCR Result: {result['status']}")
    if result['status'] == 'success':
        logger.info(f"Text length: {len(result.get('text', ''))}")
        logger.info(f"First 200 chars: {result.get('text', '')[:200]}...")
    else:
        logger.error(f"OCR failed: {result.get('error', 'Unknown error')}")
        
except Exception as e:
    logger.error(f"Test failed: {e}")
    import traceback
    traceback.print_exc()