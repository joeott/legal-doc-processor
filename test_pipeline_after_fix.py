#!/usr/bin/env python3
"""
Test pipeline after relationship building fix
"""

import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scripts.celery_app import app
from scripts.db import DatabaseManager
from scripts.cache import get_redis_manager, CacheKeys
from scripts.pdf_tasks import build_document_relationships
from sqlalchemy import text

# Use our test document
TEST_DOCUMENT_UUID = '5805f7b5-09ca-4f95-a990-da2dd758fd9e'

def trigger_relationship_building():
    """Manually trigger relationship building with the fix"""
    
    print("\n🔧 TRIGGERING RELATIONSHIP BUILDING WITH FIX")
    print("="*60)
    
    db_manager = DatabaseManager()
    redis_manager = get_redis_manager()
    
    session = next(db_manager.get_session())
    try:
        # Get all required data
        print("📊 Loading required data...")
        
        # Get chunks
        chunks_result = session.execute(
            text("""
                SELECT chunk_uuid, text, chunk_index, char_start_index, char_end_index
                FROM document_chunks 
                WHERE document_uuid = :uuid
                ORDER BY chunk_index
            """),
            {'uuid': TEST_DOCUMENT_UUID}
        ).fetchall()
        
        chunks = []
        for chunk in chunks_result:
            chunks.append({
                'chunk_uuid': str(chunk.chunk_uuid),
                'chunk_text': chunk.text,
                'chunk_index': chunk.chunk_index,
                'start_char': chunk.char_start_index,
                'end_char': chunk.char_end_index
            })
        print(f"✅ Loaded {len(chunks)} chunks")
        
        # Get entity mentions
        mentions_result = session.execute(
            text("""
                SELECT em.*, ce.canonical_name
                FROM entity_mentions em
                LEFT JOIN canonical_entities ce ON em.canonical_entity_uuid = ce.canonical_entity_uuid
                WHERE em.document_uuid = :uuid
            """),
            {'uuid': TEST_DOCUMENT_UUID}
        ).fetchall()
        
        entity_mentions = []
        for mention in mentions_result:
            entity_mentions.append({
                'mention_uuid': str(mention.mention_uuid),
                'chunk_uuid': str(mention.chunk_uuid),
                'document_uuid': str(mention.document_uuid),
                'entity_text': mention.entity_text,
                'entity_type': mention.entity_type,
                'start_char': mention.start_char,
                'end_char': mention.end_char,
                'confidence_score': mention.confidence_score,
                'canonical_entity_uuid': str(mention.canonical_entity_uuid) if mention.canonical_entity_uuid else None,
                'canonical_name': mention.canonical_name
            })
        print(f"✅ Loaded {len(entity_mentions)} entity mentions")
        
        # Get canonical entities
        canonical_result = session.execute(
            text("""
                SELECT DISTINCT ce.*
                FROM canonical_entities ce
                JOIN entity_mentions em ON em.canonical_entity_uuid = ce.canonical_entity_uuid
                WHERE em.document_uuid = :uuid
            """),
            {'uuid': TEST_DOCUMENT_UUID}
        ).fetchall()
        
        canonical_entities = []
        for entity in canonical_result:
            canonical_entities.append({
                'canonical_entity_uuid': str(entity.canonical_entity_uuid),
                'entity_type': entity.entity_type,
                'canonical_name': entity.canonical_name,
                'entity_names': [entity.canonical_name]  # Simplified
            })
        print(f"✅ Loaded {len(canonical_entities)} canonical entities")
        
        # Get project UUID
        project_uuid = session.execute(
            text("SELECT project_uuid FROM source_documents WHERE document_uuid = :uuid"),
            {'uuid': TEST_DOCUMENT_UUID}
        ).scalar()
        print(f"✅ Project UUID: {project_uuid}")
        
    finally:
        session.close()
    
    # Build document metadata WITH the fix
    document_metadata = {
        'title': 'Wombat Corp Disclosure Statement',
        'document_uuid': TEST_DOCUMENT_UUID  # THIS IS THE FIX
    }
    
    print(f"\n📋 Document metadata includes UUID: {document_metadata}")
    
    # Trigger relationship building
    print("\n🚀 Triggering relationship building task...")
    task = build_document_relationships.apply_async(
        args=[
            TEST_DOCUMENT_UUID,
            document_metadata,
            str(project_uuid),
            chunks,
            entity_mentions,
            canonical_entities
        ]
    )
    
    print(f"✅ Task submitted: {task.id}")
    
    # Wait for completion
    print("\n⏳ Waiting for task to complete...")
    max_wait = 30
    start_time = time.time()
    
    while time.time() - start_time < max_wait:
        if task.ready():
            if task.successful():
                result = task.result
                print(f"\n✅ Task completed successfully!")
                print(f"   Total relationships: {result.get('total_relationships', 0)}")
                return True
            else:
                print(f"\n❌ Task failed: {task.info}")
                return False
        
        time.sleep(1)
        print(".", end="", flush=True)
    
    print(f"\n⚠️  Task timed out after {max_wait} seconds")
    return False

def check_relationships():
    """Check if relationships were created"""
    db_manager = DatabaseManager()
    session = next(db_manager.get_session())
    
    try:
        # First check table columns
        columns_result = session.execute(
            text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'relationship_staging'
            """)
        ).fetchall()
        
        print("\n📊 relationship_staging columns:")
        for col in columns_result:
            print(f"   - {col.column_name}")
        
        # Try different queries based on columns
        if any('source_uuid' in col.column_name for col in columns_result):
            # New schema
            result = session.execute(
                text("""
                    SELECT relationship_type, COUNT(*) as count
                    FROM relationship_staging
                    WHERE source_uuid = :uuid OR target_uuid = :uuid
                    GROUP BY relationship_type
                """),
                {'uuid': TEST_DOCUMENT_UUID}
            ).fetchall()
        else:
            # Try with source_id
            result = session.execute(
                text("""
                    SELECT relationship_type, COUNT(*) as count
                    FROM relationship_staging
                    WHERE source_id = :uuid
                    GROUP BY relationship_type
                """),
                {'uuid': TEST_DOCUMENT_UUID}
            ).fetchall()
        
        if result:
            print("\n✅ Relationships created:")
            total = 0
            for row in result:
                print(f"   - {row.relationship_type}: {row.count}")
                total += row.count
            print(f"   Total: {total}")
            return True
        else:
            print("\n❌ No relationships found")
            return False
            
    except Exception as e:
        print(f"\n❌ Error checking relationships: {e}")
        return False
    finally:
        session.close()

def main():
    print("\n" + "="*80)
    print("🧪 TESTING RELATIONSHIP BUILDING AFTER FIX")
    print("="*80)
    
    # Check current state
    print("\n1️⃣ Checking current pipeline state...")
    redis_manager = get_redis_manager()
    state_key = CacheKeys.DOC_STATE.format(document_uuid=TEST_DOCUMENT_UUID)
    state = redis_manager.get_dict(state_key) or {}
    
    rel_state = state.get('relationships', {})
    print(f"   Current relationships state: {rel_state.get('status', 'unknown')}")
    
    if rel_state.get('status') == 'failed':
        print(f"   Previous error: {rel_state.get('metadata', {}).get('error', 'unknown')}")
    
    # Trigger relationship building
    print("\n2️⃣ Triggering relationship building with fix...")
    if trigger_relationship_building():
        # Check results
        print("\n3️⃣ Verifying relationships in database...")
        if check_relationships():
            print("\n✅ RELATIONSHIP BUILDING FIXED!")
            
            # Check final pipeline state
            state = redis_manager.get_dict(state_key) or {}
            pipeline_state = state.get('pipeline', {})
            print(f"\n📊 Final pipeline state: {pipeline_state.get('status', 'unknown')}")
            
            return 0
    
    print("\n❌ Relationship building still failing")
    return 1

if __name__ == "__main__":
    sys.exit(main())