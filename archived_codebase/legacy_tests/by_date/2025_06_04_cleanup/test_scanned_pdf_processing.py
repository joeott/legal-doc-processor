#!/usr/bin/env python3
"""Test the new scanned PDF processing functionality."""

import os
import sys
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment
if os.path.exists('.env'):
    from dotenv import load_dotenv
    load_dotenv()

# Test parameters
TEST_DOCUMENT_UUID = "1d9e1752-942c-4505-a1f9-3ee28f52a2a1"
TEST_S3_PATH = "s3://samu-docs-private-upload/documents/1d9e1752-942c-4505-a1f9-3ee28f52a2a1/IMG_0791.pdf"

def test_scanned_pdf_processing():
    """Test the scanned PDF processing pipeline."""
    from scripts.pdf_tasks import extract_text_from_document
    
    logger.info(f"Testing scanned PDF processing for document {TEST_DOCUMENT_UUID}")
    logger.info(f"File path: {TEST_S3_PATH}")
    
    try:
        # Call the OCR extraction task directly
        result = extract_text_from_document(TEST_DOCUMENT_UUID, TEST_S3_PATH)
        
        logger.info(f"OCR Result: {result}")
        
        if result['status'] == 'completed':
            logger.info(f"✓ OCR completed successfully")
            logger.info(f"  Method: {result.get('method', 'unknown')}")
            logger.info(f"  Text length: {result.get('text_length', 0)} characters")
            logger.info(f"  Confidence: {result.get('confidence', 0):.2f}")
        elif result['status'] == 'processing':
            logger.info(f"⏳ OCR initiated, job ID: {result.get('job_id', 'unknown')}")
            logger.info(f"  Method: {result.get('method', 'unknown')}")
        else:
            logger.error(f"❌ Unexpected status: {result['status']}")
            
    except Exception as e:
        logger.error(f"❌ Error during testing: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    print("=== Scanned PDF Processing Test ===")
    test_scanned_pdf_processing()