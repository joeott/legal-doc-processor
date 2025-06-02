#!/usr/bin/env python3
"""Reset document and test processing"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from scripts.rds_utils import execute_query
from scripts.cache import get_cache_manager
from scripts.pdf_tasks import process_pdf_document
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Document to test
doc_uuid = '0697af52-8bc6-4299-90ec-5d67b7eeb858'
project_uuid = 'f7c1bd87-7c8b-4a5e-a74a-b4b73eafe6d7'
bucket_name = os.getenv('S3_PRIMARY_DOCUMENT_BUCKET', 'samu-docs-private-upload')
s3_key = f'documents/{doc_uuid}.pdf'
file_path = f's3://{bucket_name}/{s3_key}'

# Step 1: Clear cache
logger.info("Clearing cache...")
cache_mgr = get_cache_manager()
cleared = cache_mgr.clear_document_cache(doc_uuid)
logger.info(f"Cleared {cleared} cache entries")

# Step 2: Reset document status
logger.info("Resetting document status...")
# Use raw SQL with execute_query
from sqlalchemy import text
from scripts.config import db_engine
with db_engine.connect() as conn:
    result = conn.execute(text("""
        UPDATE source_documents 
        SET celery_status = 'pending', 
            error_message = NULL,
            status = 'processing',
            ocr_completed_at = NULL,
            processing_completed_at = NULL
        WHERE document_uuid = :doc_id
    """), {"doc_id": doc_uuid})
    conn.commit()
    logger.info(f"Updated {result.rowcount} document(s)")

# Step 3: Process document
logger.info(f"Processing document {doc_uuid}...")
logger.info(f"File path: {file_path}")

try:
    result = process_pdf_document(
        document_uuid=doc_uuid,
        file_path=file_path,
        project_uuid=project_uuid,
        document_metadata={'fileName': 'test_document.pdf'}
    )
    logger.info(f"SUCCESS! Result: {result}")
except Exception as e:
    logger.error(f"FAILED: {e}")
    import traceback
    traceback.print_exc()