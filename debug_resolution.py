#!/usr/bin/env python3
"""Debug entity resolution process"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scripts.db import DatabaseManager
from scripts.entity_resolution_fixes import resolve_entities_simple
from sqlalchemy import text
import json

# Initialize database
db_manager = DatabaseManager()
session = next(db_manager.get_session())

# Get entity mentions for the document
doc_uuid = '5805f7b5-09ca-4f95-a990-da2dd758fd9e'
result = session.execute(
    text("""
        SELECT mention_uuid, entity_text, entity_type, chunk_uuid
        FROM entity_mentions 
        WHERE document_uuid = :uuid
        ORDER BY entity_type, entity_text
    """),
    {'uuid': doc_uuid}
)

mentions = []
for row in result:
    mentions.append({
        'mention_uuid': str(row.mention_uuid),
        'entity_text': row.entity_text,
        'entity_type': row.entity_type,
        'chunk_uuid': str(row.chunk_uuid)
    })

print(f"Found {len(mentions)} entity mentions")
for m in mentions:
    print(f"  {m['entity_type']}: {m['entity_text']}")

# Run resolution
print("\nRunning entity resolution...")
resolution_result = resolve_entities_simple(
    entity_mentions=mentions,
    document_uuid=doc_uuid,
    threshold=0.8
)

print(f"\nResolution results:")
print(f"  Total mentions: {resolution_result['total_mentions']}")
print(f"  Canonical entities: {resolution_result['total_canonical']}")
print(f"  Deduplication rate: {resolution_result['deduplication_rate']:.1%}")

print(f"\nCanonical entities created:")
for entity in resolution_result['canonical_entities']:
    print(f"  {entity['entity_type']}: {entity['canonical_name']}")
    print(f"    Aliases: {entity['aliases']}")
    print(f"    Mentions: {entity['mention_count']}")

session.close()