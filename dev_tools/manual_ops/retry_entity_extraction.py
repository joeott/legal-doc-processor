#!/usr/bin/env python3
"""Retry entity extraction to trigger resolution with fixed code"""

import os
import sys
import logging

# Add the parent directory to the Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.pdf_tasks import extract_entities_from_chunks
from scripts.cache import get_redis_manager

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def main():
    document_uuid = "4909739b-8f12-40cd-8403-04b8b1a79281"
    
    logger.info(f"Clearing entity resolution state and retrying entity extraction for {document_uuid}")
    
    # Clear the failed entity resolution state
    rm = get_redis_manager()
    doc_state = rm.get_cached(f'doc:state:{document_uuid}')
    if doc_state and 'entity_resolution' in doc_state:
        doc_state['entity_resolution']['status'] = 'pending'
        rm.set_cached(f'doc:state:{document_uuid}', doc_state, ttl=86400)
        logger.info("Cleared entity resolution failed state")
    
    # Trigger entity extraction which will then trigger resolution
    result = extract_entities_from_chunks.delay(document_uuid)
    
    logger.info(f"Entity extraction task submitted: {result.id}")
    logger.info(f"Waiting for result...")
    
    # Wait for completion (max 60 seconds)
    try:
        task_result = result.get(timeout=60)
        logger.info(f"Task completed successfully!")
        logger.info(f"Result: Extracted {len(task_result.get('entity_mentions', []))} entities")
    except Exception as e:
        logger.error(f"Task failed: {e}")
        logger.error(f"Task state: {result.state}")
        if hasattr(result, 'info'):
            logger.error(f"Task info: {result.info}")

if __name__ == "__main__":
    main()