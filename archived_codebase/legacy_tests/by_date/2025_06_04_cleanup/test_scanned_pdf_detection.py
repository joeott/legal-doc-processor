#!/usr/bin/env python3
"""Test just the scanned PDF detection functionality."""

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
TEST_S3_BUCKET = "samu-docs-private-upload"
TEST_S3_KEY = "documents/1d9e1752-942c-4505-a1f9-3ee28f52a2a1/IMG_0791.pdf"

def test_scanned_pdf_detection():
    """Test the scanned PDF detection logic."""
    from scripts.textract_utils import TextractProcessor
    from scripts.db import DatabaseManager
    
    logger.info(f"Testing scanned PDF detection for s3://{TEST_S3_BUCKET}/{TEST_S3_KEY}")
    
    try:
        # Initialize components
        db_manager = DatabaseManager(validate_conformance=False)
        textract_processor = TextractProcessor(db_manager)
        
        # Test detection
        is_scanned = textract_processor._is_scanned_pdf(TEST_S3_BUCKET, TEST_S3_KEY)
        
        logger.info(f"Detection result: {'SCANNED PDF' if is_scanned else 'TEXT PDF'}")
        
        return is_scanned
        
    except Exception as e:
        logger.error(f"Error during detection: {e}")
        import traceback
        traceback.print_exc()
        return None

if __name__ == "__main__":
    print("=== Scanned PDF Detection Test ===")
    result = test_scanned_pdf_detection()
    
    if result is True:
        print("\n✓ PDF correctly identified as SCANNED (image-based)")
    elif result is False:
        print("\n✓ PDF identified as TEXT-BASED")
    else:
        print("\n❌ Detection failed")