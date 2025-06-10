#!/usr/bin/env python3
"""
Test Redis acceleration by processing a document and monitoring cache usage.
"""
import os
import sys
import time
import logging
from datetime import datetime
import asyncio

# Add scripts directory to path
sys.path.append(os.path.join(os.path.dirname(__file__), 'scripts'))

from scripts.db import DatabaseManager
from scripts.cache import get_redis_manager, CacheKeys
from scripts.config import REDIS_ACCELERATION_ENABLED
from scripts.celery_app import app
from scripts.pdf_tasks import extract_text_from_document
from scripts.intake_service import create_project, create_document_with_validation
from scripts.s3_storage import S3StorageManager

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def clear_document_cache(document_uuid: str):
    """Clear all Redis cache for a document to test cold cache."""
    redis_manager = get_redis_manager()
    
    patterns = [
        CacheKeys.DOC_OCR_RESULT,
        CacheKeys.DOC_CHUNKS,
        CacheKeys.DOC_ALL_EXTRACTED_MENTIONS,
        CacheKeys.DOC_CANONICAL_ENTITIES,
        CacheKeys.DOC_RELATIONSHIPS,
        CacheKeys.DOC_STATE
    ]
    
    cleared = 0
    for pattern in patterns:
        key = CacheKeys.format_key(pattern, document_uuid=document_uuid)
        if redis_manager.delete(key):
            cleared += 1
            logger.info(f"Cleared cache key: {key}")
            
    logger.info(f"Cleared {cleared} cache keys for document {document_uuid}")
    return cleared

def process_document_with_monitoring(file_path: str):
    """Process a document and monitor Redis acceleration."""
    logger.info(f"\n{'='*60}")
    logger.info(f"Redis Acceleration Test - Processing: {os.path.basename(file_path)}")
    logger.info(f"Redis Acceleration Enabled: {REDIS_ACCELERATION_ENABLED}")
    logger.info(f"{'='*60}\n")
    
    # Create project
    db = DatabaseManager()
    project_name = f"REDIS_TEST_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    session = next(db.get_session())
    try:
        project_id, project_uuid = create_project(session, project_name)
        logger.info(f"✅ Created project: {project_name} (ID: {project_id})")
    finally:
        session.close()
    
    # Upload document to S3
    s3_manager = S3StorageManager()
    filename = os.path.basename(file_path)
    
    logger.info(f"\nUploading document to S3...")
    start_time = time.time()
    
    result = s3_manager.upload_document_with_uuid_naming(
        project_id=project_id,
        file_path=file_path,
        original_filename=filename
    )
    
    upload_time = time.time() - start_time
    logger.info(f"✅ S3 upload completed in {upload_time:.2f} seconds")
    logger.info(f"   - Document UUID: {result['document_uuid']}")
    logger.info(f"   - S3 Key: {result['s3_key']}")
    
    document_uuid = result['document_uuid']
    
    # Create database record
    session = next(db.get_session())
    try:
        doc_id = create_document_with_validation(
            session=session,
            document_uuid=document_uuid,
            filename=filename,
            s3_bucket=result['s3_bucket'],
            s3_key=result['s3_key'],
            project_id=project_id
        )
        logger.info(f"✅ Created document record (ID: {doc_id})")
    finally:
        session.close()
    
    # Clear any existing cache for cold start test
    logger.info(f"\nClearing Redis cache for cold start test...")
    clear_document_cache(document_uuid)
    
    # Test 1: Cold cache (first run)
    logger.info(f"\n{'='*40}")
    logger.info("TEST 1: Cold Cache (First Run)")
    logger.info(f"{'='*40}")
    
    redis_manager = get_redis_manager()
    
    # Submit OCR task
    logger.info(f"\nSubmitting OCR task to Celery...")
    s3_url = f"s3://{result['s3_bucket']}/{result['s3_key']}"
    
    cold_start = time.time()
    task = extract_text_from_document.apply_async(
        args=[document_uuid, s3_url]
    )
    logger.info(f"✅ Task submitted: {task.id}")
    
    # Monitor cache population
    logger.info(f"\nMonitoring cache population...")
    cache_populated = {}
    start_monitor = time.time()
    
    while time.time() - start_monitor < 120:  # Monitor for up to 2 minutes
        # Check various cache keys
        ocr_cached = redis_manager.exists(CacheKeys.format_key(CacheKeys.DOC_OCR_RESULT, document_uuid=document_uuid))
        chunks_cached = redis_manager.exists(CacheKeys.format_key(CacheKeys.DOC_CHUNKS, document_uuid=document_uuid))
        entities_cached = redis_manager.exists(CacheKeys.format_key(CacheKeys.DOC_ALL_EXTRACTED_MENTIONS, document_uuid=document_uuid))
        
        # Log new cache entries
        if ocr_cached and 'ocr' not in cache_populated:
            cache_populated['ocr'] = time.time() - cold_start
            logger.info(f"  ✅ OCR result cached at {cache_populated['ocr']:.2f}s")
            
        if chunks_cached and 'chunks' not in cache_populated:
            cache_populated['chunks'] = time.time() - cold_start
            logger.info(f"  ✅ Chunks cached at {cache_populated['chunks']:.2f}s")
            
        if entities_cached and 'entities' not in cache_populated:
            cache_populated['entities'] = time.time() - cold_start
            logger.info(f"  ✅ Entities cached at {cache_populated['entities']:.2f}s")
            
        # Check if task is complete
        if task.ready():
            cold_time = time.time() - cold_start
            logger.info(f"\n✅ Cold cache processing completed in {cold_time:.2f} seconds")
            logger.info(f"   Task result: {task.result}")
            break
            
        time.sleep(2)
    
    # Wait a bit to ensure all caching is complete
    time.sleep(5)
    
    # Test 2: Warm cache (second run)
    logger.info(f"\n{'='*40}")
    logger.info("TEST 2: Warm Cache (Second Run)")
    logger.info(f"{'='*40}")
    
    # Submit the same task again
    logger.info(f"\nSubmitting OCR task again (should use cache)...")
    
    warm_start = time.time()
    task2 = extract_text_from_document.apply_async(
        args=[document_uuid, s3_url]
    )
    logger.info(f"✅ Task submitted: {task2.id}")
    
    # Monitor for faster completion
    while time.time() - warm_start < 30:  # Should be much faster
        if task2.ready():
            warm_time = time.time() - warm_start
            logger.info(f"\n✅ Warm cache processing completed in {warm_time:.2f} seconds")
            logger.info(f"   Task result: {task2.result}")
            break
        time.sleep(0.5)
    
    # Calculate performance improvement
    if 'ocr' in cache_populated and warm_time < cold_time:
        improvement = ((cold_time - warm_time) / cold_time) * 100
        logger.info(f"\n🚀 Performance Improvement: {improvement:.1f}%")
        logger.info(f"   Cold cache: {cold_time:.2f}s")
        logger.info(f"   Warm cache: {warm_time:.2f}s")
        logger.info(f"   Time saved: {cold_time - warm_time:.2f}s")
    
    # Show cache contents
    logger.info(f"\n{'='*40}")
    logger.info("Cache Contents")
    logger.info(f"{'='*40}")
    
    # Check what's in cache
    ocr_result = redis_manager.get_cached(CacheKeys.format_key(CacheKeys.DOC_OCR_RESULT, document_uuid=document_uuid))
    if ocr_result:
        logger.info(f"\nOCR Result (cached):")
        if isinstance(ocr_result, dict):
            logger.info(f"  - Status: {ocr_result.get('status', 'N/A')}")
            logger.info(f"  - Text length: {len(ocr_result.get('text', ''))}")
            logger.info(f"  - Method: {ocr_result.get('method', 'N/A')}")
    
    chunks = redis_manager.get_cached(CacheKeys.format_key(CacheKeys.DOC_CHUNKS, document_uuid=document_uuid))
    if chunks:
        logger.info(f"\nChunks (cached):")
        logger.info(f"  - Number of chunks: {len(chunks) if isinstance(chunks, list) else 'N/A'}")
        if isinstance(chunks, list) and chunks:
            logger.info(f"  - First chunk length: {len(chunks[0].get('text', '')) if isinstance(chunks[0], dict) else 'N/A'}")
    
    entities = redis_manager.get_cached(CacheKeys.format_key(CacheKeys.DOC_ALL_EXTRACTED_MENTIONS, document_uuid=document_uuid))
    if entities:
        logger.info(f"\nEntities (cached):")
        logger.info(f"  - Number of entities: {len(entities) if isinstance(entities, list) else 'N/A'}")
    
    return document_uuid


def main():
    """Main test function."""
    # Use the test document
    test_file = "input_docs/Paul, Michael (Acuity)/Paul, Michael - Lora Prop Disclosure Stmt 10-21-24.pdf"
    
    if not os.path.exists(test_file):
        logger.error(f"Test file not found: {test_file}")
        sys.exit(1)
    
    # Process document with monitoring
    document_uuid = process_document_with_monitoring(test_file)
    
    logger.info(f"\n{'='*60}")
    logger.info("Redis Acceleration Test Complete")
    logger.info(f"Document UUID: {document_uuid}")
    logger.info(f"{'='*60}\n")


if __name__ == "__main__":
    main()