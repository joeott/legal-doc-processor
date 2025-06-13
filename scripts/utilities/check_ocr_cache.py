#!/usr/bin/env python3
"""Check OCR cache for specific document."""

import sys
import json
from scripts.cache import get_redis_manager, CacheKeys

def check_ocr_cache(document_uuid):
    """Check if OCR result is cached for document."""
    redis_manager = get_redis_manager()
    
    if not redis_manager.is_available():
        print("❌ Redis is not available!")
        return False
    
    # Check OCR cache
    ocr_cache_key = CacheKeys.format_key(CacheKeys.DOC_OCR_RESULT, document_uuid=document_uuid)
    print(f"Checking OCR cache key: {ocr_cache_key}")
    
    ocr_data = redis_manager.get_dict(ocr_cache_key)
    if ocr_data:
        print(f"✅ Found OCR cache data:")
        print(json.dumps(ocr_data, indent=2))
        return True
    else:
        print(f"❌ No OCR cache found for document {document_uuid}")
    
    # Check if key exists at all
    client = redis_manager.get_client()
    if client.exists(ocr_cache_key):
        print(f"ℹ️  Key exists but couldn't decode value")
        raw = client.get(ocr_cache_key)
        print(f"Raw value type: {type(raw)}, length: {len(raw) if raw else 0}")
    
    # Check document state
    state_key = CacheKeys.format_key(CacheKeys.DOC_STATE, document_uuid=document_uuid)
    state_data = redis_manager.get_dict(state_key)
    if state_data:
        print(f"\n📊 Document state:")
        print(json.dumps(state_data, indent=2))
    
    # Check all keys for this document
    pattern = f"doc:*:{document_uuid}"
    print(f"\n🔍 All cache keys for document:")
    for key in client.scan_iter(match=pattern, count=100):
        print(f"  - {key}")
    
    return False

if __name__ == "__main__":
    # The document UUID from the test
    doc_uuid = "ced7a402-5271-4ece-9313-4ee6c7be1f16"
    if len(sys.argv) > 1:
        doc_uuid = sys.argv[1]
    
    check_ocr_cache(doc_uuid)