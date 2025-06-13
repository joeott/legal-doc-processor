#!/usr/bin/env python3
"""Fix chunks cache with correct field names"""

from scripts.cache import get_redis_manager, CacheKeys
from scripts.db import DatabaseManager
from sqlalchemy import text

document_uuid = "ad63957e-8a09-4cf3-a423-ac1f4e784fc3"

# Get redis manager
redis_manager = get_redis_manager()

# Get chunks from database
db_manager = DatabaseManager(validate_conformance=False)
with next(db_manager.get_session()) as session:
    chunks_result = session.execute(text("""
        SELECT chunk_uuid, document_uuid, chunk_index, text, 
               char_start_index, char_end_index, metadata
        FROM document_chunks
        WHERE document_uuid = :doc_uuid
        ORDER BY chunk_index
    """), {'doc_uuid': document_uuid})
    
    # Create chunks in the format expected by chunking stage cache
    serialized_chunks = []
    for row in chunks_result:
        serialized_chunks.append({
            'chunk_uuid': str(row.chunk_uuid),
            'text': row.text,  # Use text to match database field
            'chunk_index': row.chunk_index,
            'start_char': row.char_start_index,  # Use start_char, not start_char_index
            'end_char': row.char_end_index       # Use end_char, not end_char_index
        })
    
    print(f"Retrieved {len(serialized_chunks)} chunks from database")
    
    # Cache the chunks with proper TTL
    chunks_key = CacheKeys.DOC_CHUNKS.format(document_uuid=document_uuid)
    redis_manager.set_with_ttl(chunks_key, serialized_chunks, ttl=86400)  # 24 hours
    print(f"Cached chunks to Redis key: {chunks_key}")
    
    # Verify cache
    cached_chunks = redis_manager.get_cached(chunks_key)
    print(f"Verified {len(cached_chunks) if cached_chunks else 0} chunks in cache")
    if cached_chunks and len(cached_chunks) > 0:
        print(f"First chunk keys: {list(cached_chunks[0].keys())}")
    
    # Now trigger entity resolution again
    from scripts.pdf_tasks import resolve_document_entities
    
    # Get entity mentions
    mentions_result = session.execute(text("""
        SELECT em.*, c.text as chunk_text
        FROM entity_mentions em
        JOIN document_chunks c ON em.chunk_uuid = c.chunk_uuid
        WHERE em.document_uuid = :doc_id
    """), {'doc_id': document_uuid})
    
    entity_mentions = []
    for row in mentions_result:
        entity_mentions.append({
            'mention_uuid': str(row.mention_uuid),
            'chunk_uuid': str(row.chunk_uuid),
            'document_uuid': str(row.document_uuid),
            'entity_text': row.entity_text,
            'entity_type': row.entity_type,
            'start_char': row.start_char,
            'end_char': row.end_char,
            'confidence_score': row.confidence_score,
            'extraction_method': row.extraction_method,
            'chunk_text': row.chunk_text
        })
    
    print(f"\nFound {len(entity_mentions)} entity mentions")
    
    # Clear canonical entities cache to force re-processing
    canon_key = f"doc:canonical_entities:{document_uuid}"
    redis_manager.get_cache_client().delete(canon_key)
    
    # Trigger entity resolution
    print("\nTriggering entity resolution...")
    task = resolve_document_entities.apply_async(
        args=[document_uuid, entity_mentions]
    )
    
    print(f"Task ID: {task.id}")
    print("Entity resolution task submitted. Check worker logs for relationship building.")