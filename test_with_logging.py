#!/usr/bin/env python3
"""Test entity resolution with enhanced logging"""

import os
import sys
import logging

# Set up logging to see debug messages
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scripts.celery_app import app
from scripts.pdf_tasks import resolve_document_entities
from scripts.db import DatabaseManager
from sqlalchemy import text

# Get the document that has entities
doc_uuid = '5805f7b5-09ca-4f95-a990-da2dd758fd9e'

# Clear existing canonical entities for clean test
db_manager = DatabaseManager()
session = next(db_manager.get_session())

print("Clearing existing canonical entities...")
# First clear the canonical entities
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
# Then clear the references
session.execute(
    text("UPDATE entity_mentions SET canonical_entity_uuid = NULL WHERE document_uuid = :uuid"),
    {'uuid': doc_uuid}
)
session.commit()
print("Cleared existing data")

# Get entity mentions with all required fields
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

print(f"\nFound {len(mentions)} entity mentions to resolve")

# Trigger resolution task
print("\nTriggering entity resolution task...")
task = resolve_document_entities.delay(doc_uuid, mentions)
print(f"Task ID: {task.id}")

# Wait for task to complete
print("\nWaiting for task to complete...")
result = task.get(timeout=30)
print(f"Task result: {result}")

# Check results
session = next(db_manager.get_session())
count_result = session.execute(
    text("SELECT COUNT(*) FROM canonical_entities WHERE created_at > NOW() - INTERVAL '1 minute'")
)
new_count = count_result.scalar()
print(f"\nCanonical entities created in last minute: {new_count}")

# Check specific canonical entities
entity_result = session.execute(
    text("""
        SELECT ce.canonical_name, ce.entity_type, COUNT(em.mention_uuid) as mention_count
        FROM canonical_entities ce
        JOIN entity_mentions em ON em.canonical_entity_uuid = ce.canonical_entity_uuid
        WHERE em.document_uuid = :uuid
        GROUP BY ce.canonical_entity_uuid, ce.canonical_name, ce.entity_type
    """),
    {'uuid': doc_uuid}
)

print("\nCanonical entities linked to document:")
for row in entity_result:
    print(f"  {row.entity_type}: {row.canonical_name} ({row.mention_count} mentions)")

session.close()