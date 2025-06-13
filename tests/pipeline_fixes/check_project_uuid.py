#!/usr/bin/env python3
"""Check if project_uuid is set for document"""

from scripts.cache import get_redis_manager

document_uuid = "ad63957e-8a09-4cf3-a423-ac1f4e784fc3"
redis_manager = get_redis_manager()

# Check metadata
metadata_key = f"doc:metadata:{document_uuid}"
stored_metadata = redis_manager.get_dict(metadata_key) or {}
print(f"Stored metadata: {stored_metadata}")
print(f"Project UUID: {stored_metadata.get('project_uuid')}")

# Check document state
state_key = f"doc:state:{document_uuid}"
doc_state = redis_manager.get_dict(state_key) or {}
print(f"\nDocument state: {doc_state}")
print(f"Project UUID from state: {doc_state.get('project_uuid')}")

# Check canonical entities
canon_key = f"doc:canonical_entities:{document_uuid}"
cached_entities = redis_manager.get_cached(canon_key)
print(f"\nCanonical entities cached: {len(cached_entities) if cached_entities else 0}")

# Check chunks
chunks_key = f"doc:chunks:{document_uuid}"
chunks = redis_manager.get_cached(chunks_key)
print(f"Chunks cached: {len(chunks) if chunks else 0}")