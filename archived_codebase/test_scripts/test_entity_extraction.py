#!/usr/bin/env python3
"""Test entity extraction stage according to context_311 criteria"""

import os
import sys
sys.path.append('/opt/legal-doc-processor')

os.environ['USE_MINIMAL_MODELS'] = 'true'
os.environ['SKIP_CONFORMANCE_CHECK'] = 'true'

from scripts.db import DatabaseManager
from scripts.cache import get_redis_manager, CacheKeys
from scripts.pdf_tasks import extract_entities_from_chunks
from sqlalchemy import text as sql_text
import time

# Test document
doc_uuid = "5805f7b5-09ca-4f95-a990-da2dd758fd9e"

print("Entity Extraction Verification Test")
print("=" * 80)

# Initialize managers
db = DatabaseManager(validate_conformance=False)
redis_manager = get_redis_manager()

# 1. Pre-test setup
print("\n1. PRE-TEST SETUP")
print("-" * 40)

session = next(db.get_session())
try:
    # Clear existing entities
    result = session.execute(
        sql_text("DELETE FROM entity_mentions WHERE document_uuid = :uuid"),
        {"uuid": doc_uuid}
    )
    deleted_count = result.rowcount
    session.commit()
    print(f"✓ Cleared {deleted_count} existing entity mentions")
    
    # Verify chunks exist
    result = session.execute(
        sql_text("SELECT COUNT(*) as count FROM document_chunks WHERE document_uuid = :uuid"),
        {"uuid": doc_uuid}
    )
    chunk_count = result.fetchone().count
    print(f"✓ Found {chunk_count} chunks for document")
    
    if chunk_count == 0:
        print("❌ No chunks found - cannot test entity extraction")
        sys.exit(1)
    
    # Get chunks for entity extraction
    result = session.execute(
        sql_text("""
            SELECT chunk_uuid, chunk_index, text, 
                   char_start_index, char_end_index
            FROM document_chunks 
            WHERE document_uuid = :uuid
            ORDER BY chunk_index
        """),
        {"uuid": doc_uuid}
    )
    
    chunks_data = []
    for row in result:
        chunks_data.append({
            'chunk_uuid': str(row.chunk_uuid),
            'chunk_text': row.text,
            'chunk_index': row.chunk_index,
            'start_char': row.char_start_index or 0,
            'end_char': row.char_end_index or len(row.text)
        })
    
    print(f"✓ Prepared {len(chunks_data)} chunks for entity extraction")
    
finally:
    session.close()

# Clear caches
redis_manager.delete(CacheKeys.DOC_ENTITY_MENTIONS.format(document_uuid=doc_uuid))
redis_manager.delete(CacheKeys.DOC_CANONICAL_ENTITIES.format(document_uuid=doc_uuid))
print("✓ Cleared entity caches")

# 2. Trigger entity extraction
print("\n2. TRIGGER ENTITY EXTRACTION")
print("-" * 40)

print(f"Submitting entity extraction task...")
print(f"  Document UUID: {doc_uuid}")
print(f"  Chunk count: {len(chunks_data)}")

# Check if OpenAI API key is configured
if not os.getenv('OPENAI_API_KEY'):
    print("⚠️  Warning: OPENAI_API_KEY not set in environment")

task = extract_entities_from_chunks.delay(doc_uuid, chunks_data)
print(f"✓ Task submitted: {task.id}")

# 3. Monitor execution
print("\n3. MONITOR EXECUTION")
print("-" * 40)

max_wait = 60  # seconds
start_time = time.time()
check_interval = 2

while time.time() - start_time < max_wait:
    if task.ready():
        break
    
    # Check task state
    state = task.state
    info = task.info
    
    print(f"  Task state: {state}", end="")
    if info and isinstance(info, dict):
        if 'current' in info and 'total' in info:
            print(f" ({info['current']}/{info['total']})")
        else:
            print()
    else:
        print()
    
    time.sleep(check_interval)

print(f"\nTask completed in {time.time() - start_time:.1f} seconds")
print(f"Final state: {task.state}")

if task.failed():
    print(f"❌ Task failed: {task.info}")
    if task.traceback:
        print("\nTraceback:")
        print(task.traceback)
elif task.successful():
    result = task.result
    print(f"✅ Task successful!")
    if isinstance(result, dict):
        print(f"  Entity mentions: {len(result.get('entity_mentions', []))}")
        print(f"  Canonical entities: {len(result.get('canonical_entities', []))}")

# 4. Verify results
print("\n4. VERIFY RESULTS")
print("-" * 40)

session = next(db.get_session())
try:
    # Check entity counts by type
    result = session.execute(
        sql_text("""
            SELECT entity_type, COUNT(*) as count
            FROM entity_mentions 
            WHERE document_uuid = :uuid
            GROUP BY entity_type
            ORDER BY count DESC
        """),
        {"uuid": doc_uuid}
    )
    
    print("\nEntity counts by type:")
    total_entities = 0
    for row in result:
        print(f"  {row.entity_type}: {row.count}")
        total_entities += row.count
    
    print(f"\nTotal entities: {total_entities}")
    
    # Verify entity positions
    result = session.execute(
        sql_text("""
            SELECT em.entity_text, em.entity_type, 
                   em.start_char, em.end_char,
                   em.confidence_score,
                   LENGTH(dc.text) as chunk_length
            FROM entity_mentions em
            JOIN document_chunks dc ON em.chunk_uuid = dc.chunk_uuid
            WHERE em.document_uuid = :uuid
            LIMIT 10
        """),
        {"uuid": doc_uuid}
    )
    
    print("\nSample entities (first 10):")
    for row in result:
        position = f"[{row.start_char or 'NULL'}-{row.end_char or 'NULL'}]"
        print(f"  '{row.entity_text}' ({row.entity_type}) @ {position} conf={row.confidence_score:.2f}")
    
    # Check for data quality issues
    result = session.execute(
        sql_text("""
            SELECT COUNT(*) as null_positions
            FROM entity_mentions
            WHERE document_uuid = :uuid
            AND (start_char IS NULL OR end_char IS NULL)
        """),
        {"uuid": doc_uuid}
    )
    null_count = result.fetchone().null_positions
    
    if null_count > 0:
        print(f"\n⚠️  Warning: {null_count} entities have NULL positions")
    
    # Check average confidence
    result = session.execute(
        sql_text("""
            SELECT AVG(confidence_score) as avg_confidence
            FROM entity_mentions
            WHERE document_uuid = :uuid
        """),
        {"uuid": doc_uuid}
    )
    avg_conf = result.fetchone().avg_confidence
    
    if avg_conf:
        print(f"\nAverage confidence score: {avg_conf:.3f}")
    
finally:
    session.close()

# 5. Check caching
print("\n5. PERFORMANCE METRICS")
print("-" * 40)

mentions_cached = redis_manager.exists(CacheKeys.DOC_ENTITY_MENTIONS.format(document_uuid=doc_uuid))
entities_cached = redis_manager.exists(CacheKeys.DOC_CANONICAL_ENTITIES.format(document_uuid=doc_uuid))

print(f"Entity mentions cached: {'✓' if mentions_cached else '❌'}")
print(f"Canonical entities cached: {'✓' if entities_cached else '❌'}")

# 6. Success criteria check
print("\n6. SUCCESS CRITERIA CHECK")
print("-" * 40)

criteria = {
    "Task completed": task.state == 'SUCCESS',
    "Entities extracted": total_entities > 0,
    "Multiple entity types": len(set(row.entity_type for row in session.execute(sql_text("SELECT DISTINCT entity_type FROM entity_mentions WHERE document_uuid = :uuid"), {"uuid": doc_uuid}))) > 1,
    "Reasonable entity count": 10 <= total_entities <= 100,
    "Good confidence scores": avg_conf > 0.7 if avg_conf else False,
    "Position data present": null_count == 0,
    "Results cached": mentions_cached and entities_cached
}

for criterion, passed in criteria.items():
    print(f"  {criterion}: {'✅' if passed else '❌'}")

all_passed = all(criteria.values())
print(f"\nOverall: {'✅ PASSED' if all_passed else '❌ FAILED'}")

print("\nTest complete!")