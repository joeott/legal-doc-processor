#!/usr/bin/env python3
"""Test the new standalone resolution task"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scripts.celery_app import app
from scripts.resolution_task import resolve_entities_standalone
from scripts.db import DatabaseManager
from scripts.cache import get_redis_manager, CacheKeys
from sqlalchemy import text
import time

# Document with entities
doc_uuid = '5805f7b5-09ca-4f95-a990-da2dd758fd9e'

# Clear any existing canonical entities
db_manager = DatabaseManager()
session = next(db_manager.get_session())

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
session.close()
print("Cleared existing data")

# Test 1: Resolution with entities already in database
print("\n=== Test 1: Resolution with entities in database ===")
print("Triggering resolution task (entities should load from database)...")
task = resolve_entities_standalone.delay(doc_uuid)
print(f"Task ID: {task.id}")

# Wait for completion
try:
    result = task.get(timeout=30)
    print(f"✅ Task completed successfully!")
    print(f"  Status: {result.get('status')}")
    print(f"  Canonical entities: {result.get('total_resolved', 0)}")
    print(f"  Deduplication rate: {result.get('deduplication_rate', 0)}")
except Exception as e:
    print(f"❌ Task failed: {e}")
    import traceback
    traceback.print_exc()

# Check results in database
time.sleep(2)
session = next(db_manager.get_session())
count_result = session.execute(
    text("""
        SELECT COUNT(DISTINCT ce.canonical_entity_uuid) 
        FROM canonical_entities ce
        JOIN entity_mentions em ON em.canonical_entity_uuid = ce.canonical_entity_uuid
        WHERE em.document_uuid = :uuid
    """),
    {'uuid': doc_uuid}
)
canonical_count = count_result.scalar()
print(f"\n✅ Canonical entities in database: {canonical_count}")

# Check specific entities
entity_result = session.execute(
    text("""
        SELECT ce.canonical_name, ce.entity_type, COUNT(em.mention_uuid) as mention_count
        FROM canonical_entities ce
        JOIN entity_mentions em ON em.canonical_entity_uuid = ce.canonical_entity_uuid
        WHERE em.document_uuid = :uuid
        GROUP BY ce.canonical_entity_uuid, ce.canonical_name, ce.entity_type
        ORDER BY mention_count DESC, ce.canonical_name
    """),
    {'uuid': doc_uuid}
)

print("\nCanonical entities created:")
for row in entity_result:
    print(f"  {row.entity_type}: {row.canonical_name} ({row.mention_count} mentions)")

# Check pipeline state
redis_manager = get_redis_manager()
state_key = CacheKeys.DOC_STATE.format(document_uuid=doc_uuid)
doc_state = redis_manager.get_dict(state_key) or {}

print("\nPipeline state:")
for stage, info in doc_state.items():
    if isinstance(info, dict) and 'status' in info:
        print(f"  {stage}: {info['status']}")

session.close()