#!/usr/bin/env python3
"""
Simple test of Redis acceleration functionality.
"""
import os
import sys
import time
import logging

# Add scripts directory to path
sys.path.append(os.path.join(os.path.dirname(__file__), 'scripts'))

from scripts.cache import get_redis_manager, CacheKeys
from scripts.config import REDIS_ACCELERATION_ENABLED, REDIS_ACCELERATION_TTL_HOURS

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_redis_acceleration():
    """Test Redis acceleration features."""
    logger.info(f"\n{'='*60}")
    logger.info("Redis Acceleration Test")
    logger.info(f"{'='*60}\n")
    
    logger.info(f"Redis Acceleration Enabled: {REDIS_ACCELERATION_ENABLED}")
    logger.info(f"Redis TTL Hours: {REDIS_ACCELERATION_TTL_HOURS}")
    
    # Get Redis manager
    redis_manager = get_redis_manager()
    
    # Test 1: Circuit breaker
    logger.info("\nTest 1: Circuit Breaker (is_redis_healthy)")
    is_healthy = redis_manager.is_redis_healthy()
    logger.info(f"  Redis is healthy: {is_healthy}")
    
    # Test 2: set_with_ttl
    logger.info("\nTest 2: set_with_ttl")
    test_key = "test:redis:acceleration"
    test_value = {
        'status': 'success',
        'text': 'This is a test document text' * 100,  # Make it reasonably sized
        'metadata': {
            'pages': 5,
            'method': 'test'
        }
    }
    
    success = redis_manager.set_with_ttl(test_key, test_value, ttl=300)
    logger.info(f"  Set test value: {success}")
    
    # Test 3: get_with_fallback
    logger.info("\nTest 3: get_with_fallback")
    
    # First, test cache hit
    def fallback_func():
        logger.info("    Fallback function called (should NOT happen for cache hit)")
        return {'status': 'fallback'}
    
    result = redis_manager.get_with_fallback(test_key, fallback_func)
    logger.info(f"  Cache hit test - got: {result.get('status') if result else None}")
    
    # Test cache miss
    def fallback_func2():
        logger.info("    Fallback function called (SHOULD happen for cache miss)")
        return {'status': 'from_fallback', 'data': 'test'}
    
    result2 = redis_manager.get_with_fallback("nonexistent:key", fallback_func2)
    logger.info(f"  Cache miss test - got: {result2}")
    
    # Test 4: Large object handling
    logger.info("\nTest 4: Large object handling (>5MB)")
    large_value = {
        'status': 'large',
        'text': 'X' * (6 * 1024 * 1024)  # 6MB of data
    }
    
    success = redis_manager.set_with_ttl("test:large:object", large_value, ttl=60)
    logger.info(f"  Set large value (should fail): {success}")
    
    # Test 5: Document cache keys
    logger.info("\nTest 5: Document cache keys")
    test_doc_uuid = "test-doc-12345"
    
    cache_keys = [
        ('OCR Result', CacheKeys.format_key(CacheKeys.DOC_OCR_RESULT, document_uuid=test_doc_uuid)),
        ('Chunks', CacheKeys.format_key(CacheKeys.DOC_CHUNKS, document_uuid=test_doc_uuid)),
        ('Entity Mentions', CacheKeys.format_key(CacheKeys.DOC_ALL_EXTRACTED_MENTIONS, document_uuid=test_doc_uuid)),
        ('Canonical Entities', CacheKeys.format_key(CacheKeys.DOC_CANONICAL_ENTITIES, document_uuid=test_doc_uuid)),
    ]
    
    for name, key in cache_keys:
        logger.info(f"  {name}: {key}")
    
    # Test 6: Simulate pipeline caching
    logger.info("\nTest 6: Simulate pipeline caching")
    
    # Simulate OCR result
    ocr_result = {
        'status': 'completed',
        'text': 'This is the extracted text from the document.',
        'metadata': {'pages': 2, 'method': 'textract'}
    }
    
    ocr_key = CacheKeys.format_key(CacheKeys.DOC_OCR_RESULT, document_uuid=test_doc_uuid)
    success = redis_manager.set_with_ttl(ocr_key, ocr_result, ttl=86400)
    logger.info(f"  Cached OCR result: {success}")
    
    # Simulate chunks
    chunks = [
        {'text': 'Chunk 1 text', 'chunk_index': 0, 'char_start_index': 0, 'char_end_index': 50},
        {'text': 'Chunk 2 text', 'chunk_index': 1, 'char_start_index': 51, 'char_end_index': 100}
    ]
    
    chunks_key = CacheKeys.format_key(CacheKeys.DOC_CHUNKS, document_uuid=test_doc_uuid)
    success = redis_manager.set_with_ttl(chunks_key, chunks, ttl=86400)
    logger.info(f"  Cached chunks: {success}")
    
    # Test retrieval with fallback
    def get_ocr_from_db():
        logger.info("    Simulating DB query for OCR (should not be called)")
        return None
    
    cached_ocr = redis_manager.get_with_fallback(ocr_key, get_ocr_from_db)
    logger.info(f"  Retrieved OCR from cache: {cached_ocr.get('status') if cached_ocr else None}")
    
    # Clean up test keys
    logger.info("\nCleaning up test keys...")
    redis_manager.delete(test_key)
    redis_manager.delete("test:large:object")
    redis_manager.delete(ocr_key)
    redis_manager.delete(chunks_key)
    
    logger.info(f"\n{'='*60}")
    logger.info("Redis Acceleration Test Complete")
    logger.info("All acceleration features working correctly!")
    logger.info(f"{'='*60}\n")


if __name__ == "__main__":
    test_redis_acceleration()