#!/usr/bin/env python3
"""Trigger entity resolution for document with existing entities"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scripts.celery_app import app
from scripts.pdf_tasks import resolve_document_entities
from scripts.db import DatabaseManager
from sqlalchemy import text

# Get entity mentions for the document
db_manager = DatabaseManager()
session = next(db_manager.get_session())

doc_uuid = '5805f7b5-09ca-4f95-a990-da2dd758fd9e'

# Get entity mentions
result = session.execute(
    text("""
        SELECT mention_uuid, entity_text, entity_type, chunk_uuid
        FROM entity_mentions 
        WHERE document_uuid = :uuid
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

session.close()

print(f"Found {len(mentions)} entity mentions")

# Clear any existing canonical entities for clean test
session = next(db_manager.get_session())
session.execute(
    text("""
        DELETE FROM canonical_entities 
        WHERE canonical_entity_uuid IN (
            SELECT DISTINCT canonical_entity_uuid 
            FROM entity_mentions 
            WHERE document_uuid = :uuid
        )
    """),
    {'uuid': doc_uuid}
)
session.execute(
    text("""
        UPDATE entity_mentions 
        SET canonical_entity_uuid = NULL 
        WHERE document_uuid = :uuid
    """),
    {'uuid': doc_uuid}
)
session.commit()
session.close()
print("Cleared existing canonical entities")

# Trigger resolution task
print(f"\nTriggering entity resolution task...")
task = resolve_document_entities.delay(doc_uuid, mentions)
print(f"Task ID: {task.id}")

# Wait a moment and check result
import time
time.sleep(5)

# Check if canonical entities were created
session = next(db_manager.get_session())
result = session.execute(
    text("""
        SELECT COUNT(DISTINCT ce.canonical_entity_uuid) 
        FROM canonical_entities ce
        JOIN entity_mentions em ON em.canonical_entity_uuid = ce.canonical_entity_uuid
        WHERE em.document_uuid = :uuid
    """),
    {'uuid': doc_uuid}
)
count = result.scalar()
print(f"\nCanonical entities created: {count}")

result = session.execute(
    text("""
        SELECT COUNT(*) 
        FROM entity_mentions 
        WHERE document_uuid = :uuid 
        AND canonical_entity_uuid IS NOT NULL
    """),
    {'uuid': doc_uuid}
)
resolved = result.scalar()
print(f"Entity mentions with canonical UUIDs: {resolved}")

session.close()