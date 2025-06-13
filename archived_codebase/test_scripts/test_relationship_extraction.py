#!/usr/bin/env python3
"""
Test relationship extraction functionality
"""
import os
import sys
import json
import logging
from datetime import datetime
from typing import List, Dict, Any

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
from scripts.relationship_extraction import (
    extract_relationships_from_document,
    save_relationships_to_database
)

def get_test_document_with_entities():
    """Get a document with canonical entities for testing"""
    db_manager = DatabaseManager()
    session = next(db_manager.get_session())
    
    try:
        from sqlalchemy import text as sql_text
        
        # Find a document with canonical entities
        query = sql_text("""
            SELECT DISTINCT d.document_uuid, d.file_name,
                   COUNT(DISTINCT ce.id) as entity_count,
                   COUNT(DISTINCT dc.id) as chunk_count
            FROM source_documents d
            JOIN canonical_entities ce ON d.document_uuid::text = ce.document_uuid::text
            JOIN document_chunks dc ON d.document_uuid = dc.document_uuid
            WHERE d.status IN ('completed', 'processing')
            GROUP BY d.document_uuid, d.file_name
            HAVING COUNT(DISTINCT ce.id) >= 3  -- At least 3 entities
            ORDER BY entity_count DESC
            LIMIT 1
        """)
        
        result = session.execute(query).fetchone()
        
        if result:
            return str(result.document_uuid), result.file_name, result.entity_count, result.chunk_count
        else:
            logger.warning("No documents with canonical entities found")
            return None, None, 0, 0
            
    finally:
        session.close()

def get_chunks_and_entities(document_uuid: str, db_manager: DatabaseManager):
    """Get chunks and canonical entities for a document"""
    session = next(db_manager.get_session())
    
    try:
        from sqlalchemy import text as sql_text
        
        # Get chunks
        chunks_query = sql_text("""
            SELECT chunk_uuid, chunk_index, text, start_char, end_char
            FROM document_chunks
            WHERE document_uuid = :doc_uuid
            ORDER BY chunk_index
        """)
        
        chunks_results = session.execute(chunks_query, {'doc_uuid': document_uuid}).fetchall()
        
        chunks = []
        for row in chunks_results:
            chunks.append({
                'chunk_uuid': str(row.chunk_uuid),
                'chunk_index': row.chunk_index,
                'text': row.text,
                'start_char': row.start_char,
                'end_char': row.end_char
            })
        
        # Get canonical entities with their aliases
        entities_query = sql_text("""
            SELECT ce.canonical_entity_uuid, ce.canonical_name, ce.entity_type,
                   ce.aliases, ce.mention_count
            FROM canonical_entities ce
            ORDER BY ce.mention_count DESC
        """)
        
        entities_results = session.execute(entities_query).fetchall()
        
        canonical_entities = []
        for row in entities_results:
            # Parse aliases from JSONB
            aliases = []
            if row.aliases:
                try:
                    if isinstance(row.aliases, str):
                        aliases = json.loads(row.aliases)
                    elif isinstance(row.aliases, list):
                        aliases = row.aliases
                    elif hasattr(row.aliases, '__iter__'):
                        aliases = list(row.aliases)
                except:
                    aliases = []
            
            canonical_entities.append({
                'canonical_entity_uuid': str(row.canonical_entity_uuid),
                'canonical_name': row.canonical_name,
                'entity_type': row.entity_type,
                'aliases': aliases,
                'mention_count': row.mention_count
            })
        
        return chunks, canonical_entities
        
    finally:
        session.close()

def check_existing_relationships(document_uuid: str, db_manager: DatabaseManager):
    """Check if document already has relationships"""
    session = next(db_manager.get_session())
    
    try:
        from sqlalchemy import text as sql_text
        
        query = sql_text("""
            SELECT COUNT(*) as rel_count
            FROM relationship_staging
            WHERE document_uuid = :doc_uuid
        """)
        
        result = session.execute(query, {'doc_uuid': document_uuid}).scalar()
        return result or 0
        
    finally:
        session.close()

def display_relationships(relationships: List[Dict[str, Any]]):
    """Display extracted relationships"""
    if not relationships:
        print("   No relationships found")
        return
    
    # Group by type
    by_type = {}
    for rel in relationships:
        rel_type = rel['relationship_type']
        if rel_type not in by_type:
            by_type[rel_type] = []
        by_type[rel_type].append(rel)
    
    # Display by type
    for rel_type, rels in by_type.items():
        print(f"\n   {rel_type} ({len(rels)} relationships):")
        
        # Show top 5 by confidence
        sorted_rels = sorted(rels, key=lambda r: r['confidence_score'], reverse=True)
        for i, rel in enumerate(sorted_rels[:5]):
            print(f"   {i+1}. {rel['source_entity_name']} → {rel['target_entity_name']}")
            print(f"      Confidence: {rel['confidence_score']:.2f}")
            print(f"      Context: \"{rel['context'][:100]}...\"")
        
        if len(rels) > 5:
            print(f"      ... and {len(rels) - 5} more {rel_type} relationships")

def main():
    """Test relationship extraction"""
    print("\n" + "="*60)
    print("Relationship Extraction Test")
    print("="*60)
    
    # Initialize database
    db_manager = DatabaseManager()
    
    # Step 1: Find a test document
    print("\n1. Finding test document...")
    document_uuid, file_name, entity_count, chunk_count = get_test_document_with_entities()
    
    if not document_uuid:
        print("❌ No suitable test document found")
        print("\nPlease run entity resolution first to create canonical entities")
        return
    
    print(f"✅ Found document: {file_name}")
    print(f"   Document UUID: {document_uuid}")
    print(f"   Canonical entities: {entity_count}")
    print(f"   Chunks: {chunk_count}")
    
    # Step 2: Check existing relationships
    print("\n2. Checking existing relationships...")
    existing_count = check_existing_relationships(document_uuid, db_manager)
    if existing_count > 0:
        print(f"⚠️  Document already has {existing_count} relationships")
    else:
        print("✅ No existing relationships found")
    
    # Step 3: Load chunks and entities
    print("\n3. Loading document data...")
    chunks, canonical_entities = get_chunks_and_entities(document_uuid, db_manager)
    print(f"✅ Loaded {len(chunks)} chunks and {len(canonical_entities)} canonical entities")
    
    # Display sample entities
    print("\n   Sample canonical entities:")
    for i, entity in enumerate(canonical_entities[:10]):
        aliases_str = f" (aliases: {', '.join(entity['aliases'][:3])})" if entity['aliases'] else ""
        print(f"   {i+1}. {entity['canonical_name']} ({entity['entity_type']}){aliases_str}")
    
    if len(canonical_entities) > 10:
        print(f"   ... and {len(canonical_entities) - 10} more entities")
    
    # Step 4: Extract relationships
    print("\n4. Extracting relationships...")
    try:
        result = extract_relationships_from_document(
            chunks=chunks,
            canonical_entities=canonical_entities,
            document_uuid=document_uuid,
            confidence_threshold=0.7
        )
        
        print(f"✅ Extraction complete:")
        print(f"   - Total relationships: {result['total_relationships']}")
        print(f"   - Chunks with relationships: {result['chunks_with_relationships']}")
        print(f"   - Relationship types: {result['relationship_types']}")
        
        # Display sample relationships
        if result['relationships']:
            print("\n   Extracted relationships:")
            display_relationships(result['relationships'])
        
    except Exception as e:
        print(f"❌ Extraction failed: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Step 5: Save relationships (if any found)
    if result['total_relationships'] > 0:
        print(f"\n5. Saving {result['total_relationships']} relationships to database...")
        try:
            saved_count = save_relationships_to_database(
                relationships=result['relationships'],
                document_uuid=document_uuid,
                db_manager=db_manager
            )
            print(f"✅ Saved {saved_count} relationships")
            
        except Exception as e:
            print(f"❌ Failed to save relationships: {e}")
            import traceback
            traceback.print_exc()
            return
    else:
        print("\n5. No relationships to save")
    
    # Step 6: Update document status
    if result['total_relationships'] > 0:
        print("\n6. Updating document processing status...")
        session = next(db_manager.get_session())
        try:
            from sqlalchemy import text as sql_text
            update_query = sql_text("""
                UPDATE source_documents
                SET processing_completed_at = NOW(),
                    status = 'completed'
                WHERE document_uuid = :doc_uuid
                AND status != 'completed'
            """)
            result = session.execute(update_query, {'doc_uuid': document_uuid})
            session.commit()
            
            if result.rowcount > 0:
                print("✅ Document marked as completed")
            else:
                print("ℹ️  Document already completed")
        except Exception as e:
            session.rollback()
            print(f"⚠️  Failed to update document status: {e}")
        finally:
            session.close()
    
    print("\n" + "="*60)
    print("Relationship Extraction Test Complete!")
    print("="*60)

if __name__ == "__main__":
    main()