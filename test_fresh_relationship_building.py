#!/usr/bin/env python3
"""
Test relationship building from fresh state
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scripts.celery_app import app
from scripts.db import DatabaseManager
from scripts.cache import get_redis_manager, CacheKeys
from scripts.pdf_tasks import build_document_relationships, update_document_state
from sqlalchemy import text
import time

TEST_DOCUMENT_UUID = '5805f7b5-09ca-4f95-a990-da2dd758fd9e'

def clear_relationship_state():
    """Clear the failed relationship state"""
    print("🧹 Clearing failed relationship state...")
    update_document_state(TEST_DOCUMENT_UUID, "relationships", "pending", {})
    print("✅ State cleared")

def test_build_relationships():
    """Test building relationships with proper metadata"""
    
    print("\n🔧 TESTING RELATIONSHIP BUILDING")
    print("="*60)
    
    db_manager = DatabaseManager()
    session = next(db_manager.get_session())
    
    try:
        # Get all data
        print("📊 Loading data...")
        
        # Get chunks
        chunks = []
        chunk_result = session.execute(
            text("""
                SELECT chunk_uuid, text as chunk_text, chunk_index
                FROM document_chunks 
                WHERE document_uuid = :uuid
                ORDER BY chunk_index
            """),
            {'uuid': TEST_DOCUMENT_UUID}
        ).fetchall()
        
        for chunk in chunk_result:
            chunks.append({
                'chunk_uuid': str(chunk.chunk_uuid),
                'chunk_text': chunk.chunk_text,
                'chunk_index': chunk.chunk_index
            })
        print(f"✅ Loaded {len(chunks)} chunks")
        
        # Get entity mentions
        entity_mentions = []
        mention_result = session.execute(
            text("""
                SELECT mention_uuid, chunk_uuid, document_uuid,
                       entity_text, entity_type, canonical_entity_uuid
                FROM entity_mentions
                WHERE document_uuid = :uuid
            """),
            {'uuid': TEST_DOCUMENT_UUID}
        ).fetchall()
        
        for mention in mention_result:
            entity_mentions.append({
                'mention_uuid': str(mention.mention_uuid),
                'chunk_uuid': str(mention.chunk_uuid),
                'document_uuid': str(mention.document_uuid),
                'entity_text': mention.entity_text,
                'entity_type': mention.entity_type,
                'canonical_entity_uuid': str(mention.canonical_entity_uuid) if mention.canonical_entity_uuid else None
            })
        print(f"✅ Loaded {len(entity_mentions)} mentions")
        
        # Get canonical entities
        canonical_entities = []
        entity_result = session.execute(
            text("""
                SELECT DISTINCT ce.canonical_entity_uuid, ce.entity_type, 
                       ce.canonical_name
                FROM canonical_entities ce
                JOIN entity_mentions em ON em.canonical_entity_uuid = ce.canonical_entity_uuid
                WHERE em.document_uuid = :uuid
            """),
            {'uuid': TEST_DOCUMENT_UUID}
        ).fetchall()
        
        for entity in entity_result:
            canonical_entities.append({
                'canonical_entity_uuid': str(entity.canonical_entity_uuid),
                'entity_type': entity.entity_type,
                'canonical_name': entity.canonical_name,
                'entity_names': [entity.canonical_name]
            })
        print(f"✅ Loaded {len(canonical_entities)} canonical entities")
        
        # Get project
        project_uuid = session.execute(
            text("SELECT project_uuid FROM source_documents WHERE document_uuid = :uuid"),
            {'uuid': TEST_DOCUMENT_UUID}
        ).scalar()
        print(f"✅ Project UUID: {project_uuid}")
        
    finally:
        session.close()
    
    # Build proper document metadata - THIS IS THE KEY
    document_data = {
        'document_uuid': TEST_DOCUMENT_UUID,  # MUST include this
        'title': 'Wombat Corp Disclosure Statement',
        'file_name': 'Paul, Michael - Wombat Corp Disclosure Stmt 10-23-24.pdf'
    }
    
    print(f"\n📋 Document data properly includes UUID: {document_data['document_uuid']}")
    
    # Call the task directly (synchronous for testing)
    print("\n🚀 Calling build_document_relationships directly...")
    
    try:
        # Create a mock task context
        task = build_document_relationships
        task.request.id = 'test-direct-call'
        
        result = task(
            document_uuid=TEST_DOCUMENT_UUID,
            document_data=document_data,  # Proper document data with UUID
            project_uuid=str(project_uuid),
            chunks=chunks,
            entity_mentions=entity_mentions,
            canonical_entities=canonical_entities
        )
        
        print(f"\n✅ Task completed successfully!")
        print(f"   Total relationships: {result.get('total_relationships', 0)}")
        print(f"   Relationship types: {result.get('relationship_types', 'N/A')}")
        print(f"   Summary: {result.get('summary', 'N/A')}")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Task failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def verify_relationships():
    """Verify relationships were created"""
    db_manager = DatabaseManager()
    session = next(db_manager.get_session())
    
    try:
        # Check with source_entity_uuid (correct schema)
        result = session.execute(
            text("""
                SELECT relationship_type, COUNT(*) as count
                FROM relationship_staging
                WHERE source_entity_uuid IN (
                    SELECT canonical_entity_uuid FROM canonical_entities 
                    WHERE canonical_entity_uuid IN (
                        SELECT canonical_entity_uuid FROM entity_mentions 
                        WHERE document_uuid = :uuid
                    )
                )
                GROUP BY relationship_type
            """),
            {'uuid': TEST_DOCUMENT_UUID}
        ).fetchall()
        
        if result:
            print("\n✅ Relationships in database:")
            total = 0
            for row in result:
                print(f"   - {row.relationship_type}: {row.count}")
                total += row.count
            print(f"   Total: {total}")
            return True
        else:
            print("\n⚠️  No relationships found with source_id")
            
            # Try a more general query
            count = session.execute(
                text("SELECT COUNT(*) FROM relationship_staging")
            ).scalar()
            print(f"   Total relationships in table: {count}")
            
            return False
            
    except Exception as e:
        print(f"\n❌ Error checking relationships: {e}")
        return False
    finally:
        session.close()

def main():
    print("="*80)
    print("🧪 FRESH RELATIONSHIP BUILDING TEST")
    print("="*80)
    
    # Clear state
    clear_relationship_state()
    
    # Test building
    if test_build_relationships():
        # Verify
        print("\n📊 Verifying relationships...")
        if verify_relationships():
            print("\n✅ SUCCESS! Relationship building is working!")
            
            # Check final state
            redis_manager = get_redis_manager()
            state_key = CacheKeys.DOC_STATE.format(document_uuid=TEST_DOCUMENT_UUID)
            state = redis_manager.get_dict(state_key) or {}
            
            print("\n📊 Final pipeline state:")
            for stage in ['ocr', 'chunking', 'entity_extraction', 'entity_resolution', 'relationships', 'pipeline']:
                if stage in state and isinstance(state[stage], dict):
                    print(f"   {stage}: {state[stage].get('status', 'unknown')}")
            
            return 0
    
    return 1

if __name__ == "__main__":
    sys.exit(main())