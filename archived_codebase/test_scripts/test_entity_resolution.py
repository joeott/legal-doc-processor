#!/usr/bin/env python3
"""
Test entity resolution functionality
"""
import os
import sys
import json
import uuid
import logging
from datetime import datetime

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import after path setup
from scripts.db import DatabaseManager
from scripts.entity_resolution_fixes import (
    resolve_entities_simple, 
    save_canonical_entities_to_db,
    update_entity_mentions_with_canonical
)

def get_test_document():
    """Get a document with entity mentions for testing"""
    db_manager = DatabaseManager()
    session = next(db_manager.get_session())
    
    try:
        # Find a document with entity mentions
        from sqlalchemy import text as sql_text
        query = sql_text("""
            SELECT DISTINCT d.document_uuid, d.file_name,
                   COUNT(DISTINCT em.id) as mention_count
            FROM source_documents d
            JOIN entity_mentions em ON d.document_uuid = em.document_uuid
            WHERE em.canonical_entity_uuid IS NULL
            GROUP BY d.document_uuid, d.file_name
            ORDER BY mention_count DESC
            LIMIT 1
        """)
        
        result = session.execute(query).fetchone()
        
        if result:
            return str(result.document_uuid), result.file_name, result.mention_count
        else:
            logger.warning("No documents with unresolved entity mentions found")
            return None, None, 0
            
    finally:
        session.close()

def get_entity_mentions(document_uuid: str, db_manager: DatabaseManager):
    """Get all entity mentions for a document"""
    session = next(db_manager.get_session())
    
    try:
        from sqlalchemy import text as sql_text
        query = sql_text("""
            SELECT mention_uuid, entity_text, entity_type, 
                   confidence_score, chunk_uuid
            FROM entity_mentions
            WHERE document_uuid = :doc_uuid
            AND canonical_entity_uuid IS NULL
            ORDER BY entity_type, entity_text
        """)
        
        results = session.execute(query, {'doc_uuid': document_uuid}).fetchall()
        
        mentions = []
        for row in results:
            # Handle UUID fields properly
            mention_uuid = row.mention_uuid if isinstance(row.mention_uuid, uuid.UUID) else uuid.UUID(str(row.mention_uuid))
            chunk_uuid = None
            if row.chunk_uuid:
                chunk_uuid = row.chunk_uuid if isinstance(row.chunk_uuid, uuid.UUID) else uuid.UUID(str(row.chunk_uuid))
            
            mentions.append({
                'mention_uuid': mention_uuid,
                'entity_text': row.entity_text,
                'entity_type': row.entity_type,
                'confidence_score': row.confidence_score,
                'chunk_uuid': chunk_uuid
            })
        
        return mentions
        
    finally:
        session.close()

def check_resolution_results(document_uuid: str, db_manager: DatabaseManager):
    """Check the results after resolution"""
    session = next(db_manager.get_session())
    
    try:
        from sqlalchemy import text as sql_text
        
        # Check canonical entities
        canon_query = sql_text("""
            SELECT ce.canonical_entity_uuid, ce.canonical_name, ce.entity_type,
                   COUNT(DISTINCT em.id) as mention_count
            FROM canonical_entities ce
            LEFT JOIN entity_mentions em ON ce.canonical_entity_uuid = em.canonical_entity_uuid
            GROUP BY ce.canonical_entity_uuid, ce.canonical_name, ce.entity_type
            ORDER BY mention_count DESC
        """)
        
        canonical_entities = session.execute(canon_query).fetchall()
        
        # Check updated mentions
        updated_query = sql_text("""
            SELECT COUNT(*) as resolved_count
            FROM entity_mentions
            WHERE document_uuid = :doc_uuid
            AND canonical_entity_uuid IS NOT NULL
        """)
        
        resolved_count = session.execute(updated_query, {'doc_uuid': document_uuid}).scalar()
        
        # Check unresolved mentions
        unresolved_query = sql_text("""
            SELECT entity_text, entity_type
            FROM entity_mentions
            WHERE document_uuid = :doc_uuid
            AND canonical_entity_uuid IS NULL
        """)
        
        unresolved = session.execute(unresolved_query, {'doc_uuid': document_uuid}).fetchall()
        
        return canonical_entities, resolved_count, unresolved
        
    finally:
        session.close()

def main():
    """Test entity resolution"""
    print("\n" + "="*60)
    print("Entity Resolution Test")
    print("="*60)
    
    # Initialize database
    db_manager = DatabaseManager()
    
    # Step 1: Find a test document
    print("\n1. Finding test document...")
    document_uuid, file_name, mention_count = get_test_document()
    
    if not document_uuid:
        print("❌ No suitable test document found")
        print("\nPlease run entity extraction first to create entity mentions")
        return
    
    print(f"✅ Found document: {file_name}")
    print(f"   Document UUID: {document_uuid}")
    print(f"   Unresolved mentions: {mention_count}")
    
    # Step 2: Get entity mentions
    print("\n2. Loading entity mentions...")
    mentions = get_entity_mentions(document_uuid, db_manager)
    print(f"✅ Loaded {len(mentions)} entity mentions")
    
    # Show sample mentions
    print("\n   Sample mentions:")
    by_type = {}
    for m in mentions:
        entity_type = m['entity_type']
        if entity_type not in by_type:
            by_type[entity_type] = []
        by_type[entity_type].append(m['entity_text'])
    
    for entity_type, texts in by_type.items():
        unique_texts = list(set(texts))[:5]  # Show first 5 unique
        print(f"   - {entity_type}: {', '.join(unique_texts)}")
        if len(set(texts)) > 5:
            print(f"     ... and {len(set(texts)) - 5} more unique {entity_type} entities")
    
    # Step 3: Perform entity resolution
    print("\n3. Performing entity resolution...")
    try:
        resolution_result = resolve_entities_simple(
            entity_mentions=mentions,
            document_uuid=document_uuid,
            threshold=0.8
        )
        
        print(f"✅ Resolution complete:")
        print(f"   - Total mentions: {resolution_result['total_mentions']}")
        print(f"   - Canonical entities: {resolution_result['total_canonical']}")
        print(f"   - Deduplication rate: {resolution_result['deduplication_rate']:.2%}")
        
    except Exception as e:
        print(f"❌ Resolution failed: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Step 4: Save canonical entities
    print("\n4. Saving canonical entities to database...")
    try:
        saved_count = save_canonical_entities_to_db(
            canonical_entities=resolution_result['canonical_entities'],
            document_uuid=document_uuid,
            db_manager=db_manager
        )
        print(f"✅ Saved {saved_count} canonical entities")
        
    except Exception as e:
        print(f"❌ Failed to save canonical entities: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Step 5: Update entity mentions
    print("\n5. Updating entity mentions with canonical UUIDs...")
    try:
        updated_count = update_entity_mentions_with_canonical(
            mention_to_canonical=resolution_result['mention_to_canonical'],
            document_uuid=document_uuid,
            db_manager=db_manager
        )
        print(f"✅ Updated {updated_count} entity mentions")
        
    except Exception as e:
        print(f"❌ Failed to update entity mentions: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Step 6: Verify results
    print("\n6. Verifying resolution results...")
    canonical_entities, resolved_count, unresolved = check_resolution_results(document_uuid, db_manager)
    
    print(f"\n✅ Resolution Summary:")
    print(f"   - Canonical entities created: {len(canonical_entities)}")
    print(f"   - Entity mentions resolved: {resolved_count}")
    print(f"   - Unresolved mentions: {len(unresolved)}")
    
    if canonical_entities:
        print("\n   Top canonical entities:")
        for i, entity in enumerate(canonical_entities[:10]):
            print(f"   {i+1}. '{entity.canonical_name}' ({entity.entity_type}) - {entity.mention_count} mentions")
    
    if unresolved:
        print(f"\n   ⚠️  {len(unresolved)} mentions remain unresolved")
        if len(unresolved) <= 5:
            for mention in unresolved:
                print(f"      - '{mention.entity_text}' ({mention.entity_type})")
    
    # Step 7: Update document status
    print("\n7. Updating document status...")
    session = next(db_manager.get_session())
    try:
        from sqlalchemy import text as sql_text
        update_query = sql_text("""
            UPDATE source_documents
            SET updated_at = NOW()
            WHERE document_uuid = :doc_uuid
        """)
        session.execute(update_query, {'doc_uuid': document_uuid})
        session.commit()
        print("✅ Document status updated")
    except Exception as e:
        session.rollback()
        print(f"⚠️  Failed to update document status: {e}")
    finally:
        session.close()
    
    print("\n" + "="*60)
    print("Entity Resolution Test Complete!")
    print("="*60)

if __name__ == "__main__":
    main()