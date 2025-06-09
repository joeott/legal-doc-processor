#!/usr/bin/env python3
"""Test entity resolution retry after fixing NoneType error"""

import os
import sys
import logging

# Add the parent directory to the Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.pdf_tasks import resolve_document_entities

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def main():
    document_uuid = "4909739b-8f12-40cd-8403-04b8b1a79281"
    
    logger.info(f"Testing entity resolution retry for document {document_uuid}")
    
    # Trigger the resolution task
    result = resolve_document_entities.delay(document_uuid)
    
    logger.info(f"Task submitted: {result.id}")
    logger.info(f"Waiting for result...")
    
    # Wait for completion (max 30 seconds)
    try:
        task_result = result.get(timeout=30)
        logger.info(f"Task completed successfully!")
        logger.info(f"Result: {task_result}")
    except Exception as e:
        logger.error(f"Task failed: {e}")
        logger.error(f"Task state: {result.state}")
        if hasattr(result, 'info'):
            logger.error(f"Task info: {result.info}")

if __name__ == "__main__":
    main()