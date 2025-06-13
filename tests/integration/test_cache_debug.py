#!/usr/bin/env python3
"""Debug script to test Redis caching functionality."""

import sys
import json
from datetime import datetime
from scripts.cache import get_redis_manager, CacheKeys

def test_redis_caching():
    """Test Redis caching operations."""
    print("Testing Redis caching functionality...")
    
    # Get Redis manager
    redis_manager = get_redis_manager()
    
    # Check if Redis is available
    if not redis_manager.is_available():
        print("❌ Redis is not available!")
        return False
    
    print("✅ Redis is available")
    
    # Test document UUID
    test_doc_uuid = "test-doc-12345"
    
    # Test 1: Simple key-value set/get
    test_key = "test:simple"
    test_value = "Hello Redis"
    
    if redis_manager.set_cached(test_key, test_value, ttl=60):
        print(f"✅ Set simple value: {test_value}")
    else:
        print("❌ Failed to set simple value")
        return False
    
    retrieved = redis_manager.get_cached(test_key)
    if retrieved == test_value:
        print(f"✅ Retrieved simple value: {retrieved}")
    else:
        print(f"❌ Failed to retrieve simple value. Got: {retrieved}")
        return False
    
    # Test 2: Dictionary storage (like OCR result)
    ocr_cache_key = CacheKeys.format_key(CacheKeys.DOC_OCR_RESULT, document_uuid=test_doc_uuid)
    ocr_data = {
        'text': 'This is test OCR text',
        'length': 21,
        'extracted_at': datetime.now().isoformat(),
        'method': 'test'
    }
    
    print(f"\nTesting OCR cache with key: {ocr_cache_key}")
    
    if redis_manager.store_dict(ocr_cache_key, ocr_data, ttl=300):
        print("✅ Stored OCR data successfully")
    else:
        print("❌ Failed to store OCR data")
        return False
    
    retrieved_ocr = redis_manager.get_dict(ocr_cache_key)
    if retrieved_ocr:
        print(f"✅ Retrieved OCR data: {json.dumps(retrieved_ocr, indent=2)}")
    else:
        print("❌ Failed to retrieve OCR data")
        return False
    
    # Test 3: Check cache keys pattern
    print("\nChecking for existing cache keys...")
    pattern = "doc:*"
    keys = []
    try:
        client = redis_manager.get_client()
        for key in client.scan_iter(match=pattern, count=100):
            keys.append(key)
            if len(keys) >= 10:  # Limit to first 10
                break
    except Exception as e:
        print(f"❌ Error scanning keys: {e}")
        return False
    
    if keys:
        print(f"✅ Found {len(keys)} document cache keys:")
        for key in keys[:5]:
            print(f"  - {key}")
    else:
        print("ℹ️  No document cache keys found")
    
    # Clean up test keys
    redis_manager.delete(test_key)
    redis_manager.delete(ocr_cache_key)
    print("\n✅ Cleaned up test keys")
    
    return True

if __name__ == "__main__":
    success = test_redis_caching()
    sys.exit(0 if success else 1)