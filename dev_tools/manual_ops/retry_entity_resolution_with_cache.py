#!/usr/bin/env python3
"""Retry entity resolution with cached entity mentions"""

import os
import sys
import logging

# Add the parent directory to the Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.pdf_tasks import resolve_document_entities
from scripts.cache import get_redis_manager, CacheKeys

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def main():
    document_uuid = "4909739b-8f12-40cd-8403-04b8b1a79281"
    
    logger.info(f"Retrying entity resolution with cached data for {document_uuid}")
    
    # Get entity mentions from cache
    rm = get_redis_manager()
    mentions_key = CacheKeys.DOC_ENTITY_MENTIONS.format(document_uuid=document_uuid)
    cached_data = rm.get_cached(mentions_key)
    
    if cached_data and 'mentions' in cached_data:
        entity_mentions = cached_data['mentions']
        logger.info(f"Found {len(entity_mentions)} entity mentions in cache")
        
        # Show a sample
        logger.info("Sample mentions:")
        for i, mention in enumerate(entity_mentions[:3]):
            text = mention.get('text', 'N/A')
            entity_type = mention.get('type', 'N/A')
            logger.info(f"  {i+1}. {text} ({entity_type})")
    else:
        logger.error("No entity mentions found in cache!")
        return
    
    # Clear the failed resolution state
    doc_state = rm.get_cached(f'doc:state:{document_uuid}')
    if doc_state and 'entity_resolution' in doc_state:
        doc_state['entity_resolution']['status'] = 'pending'
        rm.set_cached(f'doc:state:{document_uuid}', doc_state, ttl=86400)
        logger.info("Cleared entity resolution failed state")
    
    # Trigger entity resolution
    result = resolve_document_entities.delay(document_uuid, entity_mentions)
    
    logger.info(f"Entity resolution task submitted: {result.id}")
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