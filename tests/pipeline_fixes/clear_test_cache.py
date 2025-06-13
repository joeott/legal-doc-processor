#!/usr/bin/env python3
"""Clear test document cache"""

from scripts.cache import get_redis_manager, CacheKeys

document_uuid = "ad63957e-8a09-4cf3-a423-ac1f4e784fc3"

redis_manager = get_redis_manager()
cache_client = redis_manager.get_cache_client()

# Clear chunks cache
chunks_key = CacheKeys.DOC_CHUNKS.format(document_uuid=document_uuid)
if cache_client.delete(chunks_key):
    print(f"Cleared chunks cache for {document_uuid}")
else:
    print(f"No chunks cache found for {document_uuid}")

# Clear entity cache
entity_key = f"cache:doc:entity_mentions:{document_uuid}"
if cache_client.delete(entity_key):
    print(f"Cleared entity cache for {document_uuid}")
    
# Clear canonical entities cache
canonical_key = f"doc:canonical_entities:{document_uuid}"
if cache_client.delete(canonical_key):
    print(f"Cleared canonical entities cache for {document_uuid}")