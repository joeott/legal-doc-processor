#!/usr/bin/env python3
"""Test the fixed PDF processing pipeline"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

import logging
from scripts.pdf_tasks_fixed import process_pdf_document_fixed
from scripts.rds_utils import execute_query

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_fixed_pipeline():
    """Test processing with the fixed pipeline"""
    
    # Get a document to process
    docs = execute_query("""
        SELECT document_uuid, original_file_name, s3_key, project_uuid
        FROM source_documents
        WHERE status = 'processing'
        AND celery_status = 'pending'
        LIMIT 1
    """)
    
    if not docs:
        logger.error("No pending documents found")
        return
    
    doc = docs[0]
    document_uuid = doc['document_uuid']
    s3_key = doc['s3_key']
    project_uuid = doc['project_uuid']
    
    # Convert to S3 URI
    import os
    bucket_name = os.getenv('S3_PRIMARY_DOCUMENT_BUCKET', 'legal-doc-processing')
    file_path = f"s3://{bucket_name}/{s3_key}"
    
    logger.info(f"Processing document: {doc['original_file_name']}")
    logger.info(f"Document UUID: {document_uuid}")
    logger.info(f"File path: {file_path}")
    
    # Process the document
    try:
        result = process_pdf_document_fixed(
            document_uuid=document_uuid,
            file_path=file_path,
            project_uuid=project_uuid,
            document_metadata={'fileName': doc['original_file_name']}
        )
        
        logger.info(f"Processing result: {result}")
        
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_fixed_pipeline()