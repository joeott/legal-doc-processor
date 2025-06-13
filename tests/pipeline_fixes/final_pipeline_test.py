#!/usr/bin/env python3
"""Final test of complete pipeline execution"""

from scripts.cache import get_redis_manager
from scripts.pdf_tasks import resolve_document_entities
from scripts.db import DatabaseManager
from sqlalchemy import text
import time
import json

document_uuid = "ad63957e-8a09-4cf3-a423-ac1f4e784fc3"

print("=" * 80)
print("FINAL PIPELINE TEST - STAGES 5-6 ACTIVATION")
print("=" * 80)

# Clear canonical entities to force fresh processing
redis_manager = get_redis_manager()
canon_key = f"doc:canonical_entities:{document_uuid}"
redis_manager.get_cache_client().delete(canon_key)
print(f"✓ Cleared canonical entities cache")

# Ensure chunks are properly cached
chunks_key = f"cache:doc:chunks:{document_uuid}"
chunks = redis_manager.get_cached(chunks_key)
print(f"✓ Chunks in cache: {len(chunks) if chunks else 0}")

# Get metadata
metadata_key = f"doc:metadata:{document_uuid}"
metadata = redis_manager.get_dict(metadata_key) or {}
print(f"✓ Project UUID: {metadata.get('project_uuid')}")

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
    
    print(f"✓ Entity mentions: {len(entity_mentions)}")
    
    # Trigger entity resolution
    print("\n" + "-" * 40)
    print("Triggering entity resolution...")
    task = resolve_document_entities.apply_async(
        args=[document_uuid, entity_mentions]
    )
    
    print(f"Task ID: {task.id}")
    
    # Wait for task completion
    for i in range(30):
        if task.ready():
            print(f"\nTask status: {task.status}")
            if task.successful():
                result = task.result
                print(f"✓ Canonical entities: {result.get('canonical_count', 0)}")
            else:
                print(f"✗ Error: {task.info}")
            break
        time.sleep(2)
        print(".", end="", flush=True)
    
    # Wait for relationship building
    print("\n\nWaiting for relationship building...")
    time.sleep(15)
    
    # Check pipeline stages
    print("\n" + "-" * 40)
    print("PIPELINE STAGE STATUS:")
    
    stages_result = session.execute(text("""
        SELECT task_type, status, created_at, error_message
        FROM processing_tasks
        WHERE document_id = :doc_id
        AND created_at > NOW() - INTERVAL '5 minutes'
        ORDER BY created_at DESC
    """), {'doc_id': document_uuid})
    
    stages = {}
    for row in stages_result:
        if row.task_type not in stages:
            stages[row.task_type] = {
                'status': row.status,
                'created_at': row.created_at,
                'error': row.error_message
            }
    
    # Check all 6 stages
    expected_stages = [
        'ocr', 'chunking', 'entity_extraction', 
        'entity_resolution', 'relationship_building', 'finalization'
    ]
    
    for stage in expected_stages:
        if stage in stages:
            status = stages[stage]['status']
            symbol = "✓" if status == "completed" else "✗"
            print(f"{symbol} Stage {expected_stages.index(stage)+1}: {stage:20} - {status}")
            if stages[stage]['error']:
                print(f"  Error: {stages[stage]['error'][:100]}")
        else:
            print(f"✗ Stage {expected_stages.index(stage)+1}: {stage:20} - NOT EXECUTED")
    
    # Final verdict
    print("\n" + "=" * 80)
    if 'relationship_building' in stages:
        print("✅ SUCCESS: Pipeline stages 5-6 are now executing!")
    else:
        print("❌ FAILED: Pipeline still blocked at stage 4")
        print("\nDEBUG: Checking worker logs...")
        import subprocess
        result = subprocess.run(
            ["tail", "-n", "30", "/opt/legal-doc-processor/logs/worker_main.log"],
            capture_output=True,
            text=True
        )
        for line in result.stdout.split('\n'):
            if any(word in line.lower() for word in ['relationship', 'chunks=', 'error', 'exception']):
                print(f"  {line}")