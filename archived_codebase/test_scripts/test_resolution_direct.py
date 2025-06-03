#!/usr/bin/env python3
"""Test resolution directly without Celery"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scripts.db import DatabaseManager
from scripts.entity_resolution_fixes import (
    resolve_entities_simple,
    save_canonical_entities_to_db,
    update_entity_mentions_with_canonical
)
from sqlalchemy import text

# Initialize database
db_manager = DatabaseManager()
session = next(db_manager.get_session())

doc_uuid = '5805f7b5-09ca-4f95-a990-da2dd758fd9e'

# Clear existing canonical entities
print("Clearing existing canonical entities...")
session.execute(
    text("""
        DELETE FROM canonical_entities 
        WHERE canonical_entity_uuid IN (
            SELECT DISTINCT canonical_entity_uuid 
            FROM entity_mentions 
            WHERE document_uuid = :uuid
            AND canonical_entity_uuid IS NOT NULL
        )
    """),
    {'uuid': doc_uuid}
)
session.execute(
    text("UPDATE entity_mentions SET canonical_entity_uuid = NULL WHERE document_uuid = :uuid"),
    {'uuid': doc_uuid}
)
session.commit()

# Get entity mentions
result = session.execute(
    text("""
        SELECT mention_uuid, chunk_uuid, document_uuid, entity_text, 
               entity_type, start_char, end_char, confidence_score
        FROM entity_mentions 
        WHERE document_uuid = :uuid
    """),
    {'uuid': doc_uuid}
)

mentions = []
for row in result:
    mentions.append({
        'mention_uuid': str(row.mention_uuid),
        'chunk_uuid': str(row.chunk_uuid),
        'document_uuid': str(row.document_uuid),
        'entity_text': row.entity_text,
        'entity_type': row.entity_type,
        'start_char': row.start_char,
        'end_char': row.end_char,
        'confidence_score': row.confidence_score
    })

session.close()

print(f"\nFound {len(mentions)} entity mentions")

# Perform resolution
print("\nPerforming entity resolution...")
resolution_result = resolve_entities_simple(
    entity_mentions=mentions,
    document_uuid=doc_uuid,
    threshold=0.8
)

print(f"Resolution complete: {resolution_result['total_canonical']} canonical entities")

# Save canonical entities
print("\nSaving canonical entities...")
saved_count = save_canonical_entities_to_db(
    canonical_entities=resolution_result['canonical_entities'],
    document_uuid=doc_uuid,
    db_manager=db_manager
)
print(f"Saved {saved_count} canonical entities")

# Update mentions
print("\nUpdating entity mentions...")
updated_count = update_entity_mentions_with_canonical(
    mention_to_canonical=resolution_result['mention_to_canonical'],
    document_uuid=doc_uuid,
    db_manager=db_manager
)
print(f"Updated {updated_count} entity mentions")

# Verify results
session = next(db_manager.get_session())
result = session.execute(
    text("""
        SELECT ce.canonical_name, ce.entity_type, COUNT(em.mention_uuid) as mention_count
        FROM canonical_entities ce
        JOIN entity_mentions em ON em.canonical_entity_uuid = ce.canonical_entity_uuid
        WHERE em.document_uuid = :uuid
        GROUP BY ce.canonical_entity_uuid, ce.canonical_name, ce.entity_type
    """),
    {'uuid': doc_uuid}
)

print("\n✅ Final Results - Canonical entities:")
for row in result:
    print(f"  {row.entity_type}: {row.canonical_name} ({row.mention_count} mentions)")

session.close()