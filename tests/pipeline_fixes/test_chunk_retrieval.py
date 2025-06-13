#!/usr/bin/env python3
"""Test chunk retrieval in the exact same way as resolve_document_entities"""

from scripts.cache import get_redis_manager, CacheKeys

document_uuid = "ad63957e-8a09-4cf3-a423-ac1f4e784fc3"

# Get redis manager
redis_manager = get_redis_manager()

print("Testing chunk retrieval as done in resolve_document_entities:")
print("-" * 60)

# Exactly as in the function
chunks_key = CacheKeys.DOC_CHUNKS.format(document_uuid=document_uuid)
print(f"Chunks key: {chunks_key}")

chunks = redis_manager.get_cached(chunks_key) or []
print(f"Result of get_cached: {type(chunks)}, length: {len(chunks)}")

if chunks:
    print(f"First chunk keys: {list(chunks[0].keys())}")
    print(f"First chunk text field: {chunks[0].get('text', 'NOT FOUND')[:50]}...")
else:
    print("No chunks found!")
    
# Try different cache key format
alt_key = f"doc:chunks:{document_uuid}"
alt_chunks = redis_manager.get_cached(alt_key) or []
print(f"\nAlternative key {alt_key}: {len(alt_chunks)} chunks")

# Check raw Redis
import redis
import json
client = redis_manager.get_cache_client()
raw = client.get(chunks_key)
if raw:
    data = json.loads(raw)
    print(f"\nRaw Redis data type: {type(data)}, length: {len(data) if isinstance(data, list) else 'N/A'}")
else:
    print("\nNo raw data in Redis!")
    
# Check all keys
all_keys = client.keys(f"*chunks*{document_uuid}*")
print(f"\nAll chunk-related keys: {all_keys}")