#!/usr/bin/env python3
"""
Process a document through the pipeline with Redis acceleration monitoring.
"""
import os
import sys
import time
import json
import logging
from datetime import datetime

# Add scripts directory to path
sys.path.append(os.path.join(os.path.dirname(__file__), 'scripts'))

from scripts.cache import get_redis_manager, CacheKeys
from scripts.celery_app import app
from scripts.pdf_tasks import extract_text_from_document
from scripts.config import REDIS_ACCELERATION_ENABLED

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def monitor_redis_cache(document_uuid: str, duration: int = 120):
    """Monitor Redis cache during document processing."""
    redis_manager = get_redis_manager()
    
    logger.info(f"\n{'='*60}")
    logger.info(f"Redis Acceleration Monitoring")
    logger.info(f"Document UUID: {document_uuid}")
    logger.info(f"Redis Acceleration Enabled: {REDIS_ACCELERATION_ENABLED}")
    logger.info(f"{'='*60}\n")
    
    # Check Redis health
    if redis_manager.is_redis_healthy():
        logger.info("✅ Redis is healthy and ready")
    else:
        logger.error("❌ Redis is not healthy!")
        return
    
    # Define cache keys to monitor
    cache_keys = {
        'OCR': CacheKeys.format_key(CacheKeys.DOC_OCR_RESULT, document_uuid=document_uuid),
        'Chunks': CacheKeys.format_key(CacheKeys.DOC_CHUNKS, document_uuid=document_uuid),
        'Entities': CacheKeys.format_key(CacheKeys.DOC_ALL_EXTRACTED_MENTIONS, document_uuid=document_uuid),
        'Canonical': CacheKeys.format_key(CacheKeys.DOC_CANONICAL_ENTITIES, document_uuid=document_uuid),
        'Resolved': CacheKeys.format_key(CacheKeys.DOC_RESOLVED_MENTIONS, document_uuid=document_uuid),
        'State': CacheKeys.format_key(CacheKeys.DOC_STATE, document_uuid=document_uuid)
    }
    
    # Initial state check
    logger.info("Initial cache state:")
    initial_state = {}
    for name, key in cache_keys.items():
        exists = redis_manager.exists(key)
        initial_state[name] = exists
        logger.info(f"  {name}: {'✅ CACHED' if exists else '❌ NOT CACHED'}")
    
    # If OCR is already cached, submit task to see acceleration
    if initial_state.get('OCR'):
        logger.info("\n🚀 OCR already cached - expecting fast processing!")
    
    # Submit OCR task
    logger.info(f"\nSubmitting OCR task...")
    s3_url = f"s3://samu-docs-private-upload/documents/{document_uuid}.pdf"
    
    start_time = time.time()
    task = extract_text_from_document.apply_async(
        args=[document_uuid, s3_url]
    )
    logger.info(f"✅ Task submitted: {task.id}")
    
    # Monitor cache changes
    logger.info(f"\nMonitoring cache for {duration} seconds...")
    cache_events = []
    last_state = initial_state.copy()
    
    while time.time() - start_time < duration:
        current_state = {}
        
        for name, key in cache_keys.items():
            exists = redis_manager.exists(key)
            current_state[name] = exists
            
            # Detect changes
            if exists != last_state.get(name, False):
                event_time = time.time() - start_time
                if exists:
                    logger.info(f"\n[{event_time:.2f}s] ✅ {name} CACHED")
                    cache_events.append({
                        'time': event_time,
                        'event': f'{name} cached',
                        'key': key
                    })
                    
                    # Show sample data for new cache entries
                    if name == 'OCR':
                        ocr_data = redis_manager.get_cached(key)
                        if isinstance(ocr_data, dict):
                            logger.info(f"    Status: {ocr_data.get('status')}")
                            logger.info(f"    Text length: {len(ocr_data.get('text', ''))}")
                            logger.info(f"    Method: {ocr_data.get('method')}")
                    elif name == 'Chunks':
                        chunks_data = redis_manager.get_cached(key)
                        if isinstance(chunks_data, list):
                            logger.info(f"    Number of chunks: {len(chunks_data)}")
                    elif name == 'Entities':
                        entities_data = redis_manager.get_cached(key)
                        if isinstance(entities_data, list):
                            logger.info(f"    Number of entities: {len(entities_data)}")
        
        last_state = current_state
        
        # Check task status
        if task.ready():
            total_time = time.time() - start_time
            logger.info(f"\n✅ Task completed in {total_time:.2f} seconds")
            logger.info(f"Task result: {task.result}")
            break
            
        time.sleep(1)
    
    # Summary
    logger.info(f"\n{'='*60}")
    logger.info("Cache Event Summary")
    logger.info(f"{'='*60}")
    
    for event in cache_events:
        logger.info(f"  [{event['time']:.2f}s] {event['event']}")
    
    # Performance analysis
    if initial_state.get('OCR') and task.ready():
        total_time = time.time() - start_time
        logger.info(f"\n🚀 Performance with cached OCR:")
        logger.info(f"   Total processing time: {total_time:.2f}s")
        logger.info(f"   Expected without cache: ~60s")
        logger.info(f"   Time saved: ~{60 - total_time:.2f}s")
        logger.info(f"   Performance improvement: ~{((60 - total_time) / 60 * 100):.1f}%")
    
    # Final cache state
    logger.info(f"\nFinal cache state:")
    for name, key in cache_keys.items():
        exists = redis_manager.exists(key)
        logger.info(f"  {name}: {'✅ CACHED' if exists else '❌ NOT CACHED'}")
    
    logger.info(f"\n{'='*60}\n")


def main():
    """Main function."""
    # Use a known document UUID (from previous tests)
    # You can replace this with a new document UUID
    test_uuids = [
        "eaca69ea-1b5f-48f4-b7a1-6ac73521e0e5",  # From context_460
        "4457a843-7b78-49ce-a51c-09d16c88edc0",  # From context_459
    ]
    
    # Try to find a document that exists
    document_uuid = None
    redis_manager = get_redis_manager()
    
    for uuid in test_uuids:
        # Check if document has been processed before
        ocr_key = CacheKeys.format_key(CacheKeys.DOC_OCR_RESULT, document_uuid=uuid)
        if redis_manager.exists(ocr_key):
            document_uuid = uuid
            logger.info(f"Found cached document: {uuid}")
            break
    
    if not document_uuid:
        # Use the first UUID for new processing
        document_uuid = test_uuids[0]
        logger.info(f"Using document UUID for fresh processing: {document_uuid}")
    
    # Monitor the processing
    monitor_redis_cache(document_uuid, duration=120)


if __name__ == "__main__":
    main()