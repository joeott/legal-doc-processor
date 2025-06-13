#!/usr/bin/env python3
"""Test complete pipeline execution with fixes"""

from scripts.cache import get_redis_manager
from scripts.pdf_tasks import resolve_document_entities
from scripts.db import DatabaseManager
from sqlalchemy import text
import time

document_uuid = "ad63957e-8a09-4cf3-a423-ac1f4e784fc3"

# Clear canonical entities to force full processing
redis_manager = get_redis_manager()
canon_key = f"doc:canonical_entities:{document_uuid}"
redis_manager.get_cache_client().delete(canon_key)
print(f"Cleared canonical entities cache for {document_uuid}")

# Get entity mentions and trigger resolution
db_manager = DatabaseManager(validate_conformance=False)
with next(db_manager.get_session()) as session:
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
    
    print(f"Found {len(entity_mentions)} entity mentions")
    
    # Trigger entity resolution
    print("\nTriggering entity resolution...")
    task = resolve_document_entities.apply_async(
        args=[document_uuid, entity_mentions]
    )
    
    print(f"Task ID: {task.id}")
    print("Waiting for completion...")
    
    # Wait for task completion
    for i in range(30):
        if task.ready():
            print(f"\nTask completed with status: {task.status}")
            if task.successful():
                result = task.result
                print(f"Canonical entities created: {result.get('canonical_count', 0)}")
            break
        time.sleep(2)
        print(".", end="", flush=True)
    
    # Wait a bit more for relationship building to trigger
    print("\n\nWaiting for relationship building to trigger...")
    time.sleep(10)
    
    # Check for relationship building task
    print("\nChecking for pipeline stage 5-6 tasks...")
    tasks_result = session.execute(text("""
        SELECT task_type, status, error_message, created_at
        FROM processing_tasks
        WHERE document_id = :doc_id
        AND created_at > NOW() - INTERVAL '2 minutes'
        ORDER BY created_at DESC
    """), {'doc_id': document_uuid})
    
    print("\nRecent processing tasks:")
    print("-" * 80)
    for row in tasks_result:
        print(f"{row.created_at} | {row.task_type:20} | {row.status:10}")
        if row.error_message:
            print(f"  Error: {row.error_message[:100]}")
    
    # Specifically check for relationship_building
    rel_result = session.execute(text("""
        SELECT COUNT(*) as count
        FROM processing_tasks
        WHERE document_id = :doc_id
        AND task_type = 'relationship_building'
        AND created_at > NOW() - INTERVAL '2 minutes'
    """), {'doc_id': document_uuid})
    
    rel_count = rel_result.scalar()
    if rel_count > 0:
        print(f"\n✅ SUCCESS: Relationship building task was triggered!")
    else:
        print(f"\n❌ FAILED: Relationship building was not triggered")
        
        # Check worker logs for the reason
        print("\nChecking recent worker logs...")
        import subprocess
        result = subprocess.run(
            ["tail", "-n", "50", "/opt/legal-doc-processor/logs/worker_main.log"],
            capture_output=True,
            text=True
        )
        
        for line in result.stdout.split('\n'):
            if 'relationship' in line.lower() or 'chunks=' in line:
                print(f"  LOG: {line}")