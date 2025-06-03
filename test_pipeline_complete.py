#!/usr/bin/env python3
"""Test complete pipeline by triggering the next stages"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scripts.celery_app import app
from scripts.pdf_tasks import build_document_relationships, finalize_document_pipeline
from scripts.db import DatabaseManager
from scripts.cache import get_redis_manager, CacheKeys
from sqlalchemy import text

# Document that now has canonical entities
doc_uuid = '5805f7b5-09ca-4f95-a990-da2dd758fd9e'

# Get required data
db_manager = DatabaseManager()
redis_manager = get_redis_manager()
session = next(db_manager.get_session())

# Get project UUID
metadata_key = f"doc:metadata:{doc_uuid}"
stored_metadata = redis_manager.get_dict(metadata_key) or {}
project_uuid = stored_metadata.get('project_uuid', 'e0c57112-c755-4798-bc1f-4ecc3f0eec78')

# Get document metadata
doc_result = session.execute(
    text("SELECT file_name, status FROM source_documents WHERE document_uuid = :uuid"),
    {'uuid': doc_uuid}
)
doc_row = doc_result.fetchone()
document_metadata = {
    'file_name': doc_row.file_name,
    'document_uuid': doc_uuid
}

# Get chunks
chunks_key = CacheKeys.DOC_CHUNKS.format(document_uuid=doc_uuid)
chunks_data = redis_manager.get_dict(chunks_key)
if not chunks_data:
    # Get from database
    chunk_result = session.execute(
        text("""
            SELECT chunk_uuid, text as chunk_text, chunk_index, 
                   char_start_index as start_char, char_end_index as end_char
            FROM document_chunks
            WHERE document_uuid = :uuid
            ORDER BY chunk_index
        """),
        {'uuid': doc_uuid}
    )
    chunks = []
    for row in chunk_result:
        chunks.append({
            'chunk_uuid': str(row.chunk_uuid),
            'chunk_text': row.chunk_text,
            'chunk_index': row.chunk_index,
            'start_char': row.start_char,
            'end_char': row.end_char
        })
else:
    chunks = chunks_data.get('chunks', [])

# Get entity mentions
mentions_result = session.execute(
    text("""
        SELECT mention_uuid, chunk_uuid, entity_text, entity_type, 
               start_char, end_char, canonical_entity_uuid
        FROM entity_mentions
        WHERE document_uuid = :uuid
    """),
    {'uuid': doc_uuid}
)
entity_mentions = []
for row in mentions_result:
    entity_mentions.append({
        'mention_uuid': str(row.mention_uuid),
        'chunk_uuid': str(row.chunk_uuid),
        'entity_text': row.entity_text,
        'entity_type': row.entity_type,
        'start_char': row.start_char,
        'end_char': row.end_char,
        'canonical_entity_uuid': str(row.canonical_entity_uuid) if row.canonical_entity_uuid else None
    })

# Get canonical entities
canonical_result = session.execute(
    text("""
        SELECT DISTINCT ce.*
        FROM canonical_entities ce
        JOIN entity_mentions em ON em.canonical_entity_uuid = ce.canonical_entity_uuid
        WHERE em.document_uuid = :uuid
    """),
    {'uuid': doc_uuid}
)
canonical_entities = []
for row in canonical_result:
    canonical_entities.append({
        'canonical_entity_uuid': str(row.canonical_entity_uuid),
        'canonical_name': row.canonical_name,
        'entity_type': row.entity_type,
        'mention_count': row.mention_count,
        'confidence_score': row.confidence_score
    })

session.close()

print(f"Document: {document_metadata['file_name']}")
print(f"Project UUID: {project_uuid}")
print(f"Chunks: {len(chunks)}")
print(f"Entity mentions: {len(entity_mentions)}")
print(f"Canonical entities: {len(canonical_entities)}")

# Trigger relationship building
print("\nTriggering relationship building...")
task = build_document_relationships.delay(
    doc_uuid,
    document_metadata,
    project_uuid,
    chunks,
    entity_mentions,
    canonical_entities
)
print(f"Task ID: {task.id}")

# Wait for completion
try:
    result = task.get(timeout=30)
    print(f"✅ Relationship building complete: {result}")
    
    # Check if finalization was triggered
    import time
    time.sleep(2)
    
    # Check final status
    session = next(db_manager.get_session())
    status_result = session.execute(
        text("SELECT status, processing_completed_at FROM source_documents WHERE document_uuid = :uuid"),
        {'uuid': doc_uuid}
    )
    status_row = status_result.fetchone()
    print(f"\nFinal document status: {status_row.status}")
    print(f"Processing completed: {'Yes' if status_row.processing_completed_at else 'No'}")
    session.close()
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()