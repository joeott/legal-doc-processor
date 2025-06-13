#!/usr/bin/env python3
"""Debug chunks retrieval issue"""

from scripts.cache import get_redis_manager, CacheKeys

document_uuid = "ad63957e-8a09-4cf3-a423-ac1f4e784fc3"

# Get redis manager
redis_manager = get_redis_manager()

# Test different cache keys
chunks_key = CacheKeys.DOC_CHUNKS.format(document_uuid=document_uuid)
print(f"Chunks key: {chunks_key}")

# Try get_cached
chunks = redis_manager.get_cached(chunks_key)
print(f"get_cached result: {type(chunks)}, length: {len(chunks) if chunks else 0}")
if chunks and len(chunks) > 0:
    print(f"First chunk: {chunks[0]}")

# Try direct Redis get
cache_client = redis_manager.get_cache_client()
raw_data = cache_client.get(chunks_key)
print(f"\nRaw Redis data exists: {raw_data is not None}")
if raw_data:
    import json
    try:
        decoded_data = json.loads(raw_data)
        print(f"Decoded data type: {type(decoded_data)}, length: {len(decoded_data) if decoded_data else 0}")
    except Exception as e:
        print(f"Error decoding: {e}")

# Check if Redis is healthy
print(f"\nRedis healthy: {redis_manager.is_redis_healthy()}")

# Check all keys for this document
pattern = f"*{document_uuid}*"
all_keys = cache_client.keys(pattern)
print(f"\nAll Redis keys for document: {len(all_keys)}")
for key in all_keys:
    print(f"  - {key}")
    
# Try format_key directly
from scripts.cache import CacheKeys as CK
test_key = CK.format_key(CK.DOC_CHUNKS, document_uuid=document_uuid)
print(f"\nDirect format_key result: {test_key}")
print(f"Keys match: {test_key == chunks_key}")