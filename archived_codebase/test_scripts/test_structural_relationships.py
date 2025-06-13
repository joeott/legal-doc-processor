#!/usr/bin/env python3
"""
Test structural relationship building (document-chunk-entity hierarchy)
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
from scripts.graph_service import GraphService
from scripts.core.processing_models import ProcessingResultStatus

def get_test_document():
    """Get a document with chunks and entities for testing"""
    db_manager = DatabaseManager()
    session = next(db_manager.get_session())
    
    try:
        from sqlalchemy import text as sql_text
        
        # Find a document with chunks and canonical entities
        # Note: canonical_entities are linked via entity_mentions
        query = sql_text("""
            SELECT DISTINCT d.document_uuid, d.file_name, d.project_uuid,
                   COUNT(DISTINCT dc.id) as chunk_count,
                   COUNT(DISTINCT ce.id) as entity_count,
                   COUNT(DISTINCT em.id) as mention_count
            FROM source_documents d
            JOIN document_chunks dc ON d.document_uuid = dc.document_uuid
            JOIN entity_mentions em ON d.document_uuid = em.document_uuid
            LEFT JOIN canonical_entities ce ON em.canonical_entity_uuid = ce.canonical_entity_uuid
            WHERE d.project_uuid IS NOT NULL
            GROUP BY d.document_uuid, d.file_name, d.project_uuid
            HAVING COUNT(DISTINCT dc.id) > 0 
               AND COUNT(DISTINCT em.id) > 0
            ORDER BY chunk_count DESC
            LIMIT 1
        """)
        
        result = session.execute(query).fetchone()
        
        if result:
            return {
                'document_uuid': str(result.document_uuid),
                'file_name': result.file_name,
                'project_uuid': str(result.project_uuid),
                'chunk_count': result.chunk_count,
                'entity_count': result.entity_count,
                'mention_count': result.mention_count
            }
        else:
            logger.warning("No suitable document found")
            return None
            
    finally:
        session.close()

def prepare_test_data(document_uuid: str, db_manager: DatabaseManager):
    """Prepare data in the format expected by graph service"""
    session = next(db_manager.get_session())
    
    try:
        from sqlalchemy import text as sql_text
        
        # Get document data
        document_data = {
            'documentId': document_uuid  # This is the neo4j_document_uuid
        }
        
        # Get chunks data
        chunks_query = sql_text("""
            SELECT chunk_uuid, chunk_index, text
            FROM document_chunks
            WHERE document_uuid = :doc_uuid
            ORDER BY chunk_index
        """)
        
        chunks_results = session.execute(chunks_query, {'doc_uuid': document_uuid}).fetchall()
        chunks_data = []
        for row in chunks_results:
            chunks_data.append({
                'chunkId': str(row.chunk_uuid),  # chunk_uuid
                'chunkIndex': row.chunk_index,
                'text': row.text[:100] + '...' if row.text else ''  # Truncate for display
            })
        
        # Get entity mentions
        mentions_query = sql_text("""
            SELECT em.mention_uuid, em.chunk_uuid, em.entity_text, 
                   em.entity_type, em.canonical_entity_uuid
            FROM entity_mentions em
            WHERE em.document_uuid = :doc_uuid
        """)
        
        mentions_results = session.execute(mentions_query, {'doc_uuid': document_uuid}).fetchall()
        entity_mentions_data = []
        for row in mentions_results:
            entity_mentions_data.append({
                'entityMentionId': str(row.mention_uuid),  # entity_mention_uuid
                'chunk_uuid': str(row.chunk_uuid) if row.chunk_uuid else None,
                'entity_text': row.entity_text,
                'entity_type': row.entity_type,
                'resolved_canonical_id_neo4j': str(row.canonical_entity_uuid) if row.canonical_entity_uuid else None
            })
        
        # Get canonical entities for this document (via entity mentions)
        canonical_query = sql_text("""
            SELECT DISTINCT ce.canonical_entity_uuid, ce.canonical_name, ce.entity_type
            FROM canonical_entities ce
            JOIN entity_mentions em ON ce.canonical_entity_uuid = em.canonical_entity_uuid
            WHERE em.document_uuid = :doc_uuid
            ORDER BY ce.canonical_name
        """)
        
        canonical_results = session.execute(canonical_query, {'doc_uuid': document_uuid}).fetchall()
        canonical_entities_data = []
        for row in canonical_results:
            canonical_entities_data.append({
                'canonicalEntityId': str(row.canonical_entity_uuid),
                'canonical_name': row.canonical_name,
                'entity_type': row.entity_type
            })
        
        return document_data, chunks_data, entity_mentions_data, canonical_entities_data
        
    finally:
        session.close()

def check_existing_relationships(document_uuid: str, db_manager: DatabaseManager):
    """Check existing structural relationships"""
    # Note: The relationship_staging table is for graph relationships
    # and doesn't track document_uuid directly. 
    # For this test, we'll skip checking existing relationships.
    return {}

def main():
    """Test structural relationship building"""
    print("\n" + "="*60)
    print("Structural Relationship Building Test")
    print("="*60)
    
    # Initialize services
    db_manager = DatabaseManager()
    graph_service = GraphService(db_manager)
    
    # Step 1: Find test document
    print("\n1. Finding test document...")
    doc_info = get_test_document()
    
    if not doc_info:
        print("❌ No suitable test document found")
        print("\nPlease ensure you have documents with:")
        print("  - Chunks created")
        print("  - Entities extracted and resolved")
        print("  - Project assignment")
        return
    
    print(f"✅ Found document: {doc_info['file_name']}")
    print(f"   Document UUID: {doc_info['document_uuid']}")
    print(f"   Project UUID: {doc_info['project_uuid']}")
    print(f"   Chunks: {doc_info['chunk_count']}")
    print(f"   Canonical entities: {doc_info['entity_count']}")
    print(f"   Entity mentions: {doc_info['mention_count']}")
    
    # Step 2: Check existing relationships
    print("\n2. Checking existing relationships...")
    existing = check_existing_relationships(doc_info['document_uuid'], db_manager)
    if existing:
        print(f"⚠️  Found existing relationships:")
        for rel_type, count in existing.items():
            print(f"   - {rel_type}: {count}")
    else:
        print("✅ No existing relationships found")
    
    # Step 3: Prepare test data
    print("\n3. Preparing test data...")
    document_data, chunks_data, entity_mentions_data, canonical_entities_data = prepare_test_data(
        doc_info['document_uuid'], 
        db_manager
    )
    
    print(f"✅ Prepared data:")
    print(f"   - Chunks: {len(chunks_data)}")
    print(f"   - Entity mentions: {len(entity_mentions_data)}")
    print(f"   - Canonical entities: {len(canonical_entities_data)}")
    
    # Step 4: Build structural relationships
    print("\n4. Building structural relationships...")
    try:
        result = graph_service.stage_structural_relationships(
            document_data=document_data,
            project_uuid=doc_info['project_uuid'],
            chunks_data=chunks_data,
            entity_mentions_data=entity_mentions_data,
            canonical_entities_data=canonical_entities_data,
            document_uuid=uuid.UUID(doc_info['document_uuid'])
        )
        
        if result.status == ProcessingResultStatus.SUCCESS:
            print(f"✅ Successfully staged {result.total_relationships} relationships")
            
            # Count by type
            rel_types = {}
            for rel in result.staged_relationships:
                rel_type = rel.relationship_type
                rel_types[rel_type] = rel_types.get(rel_type, 0) + 1
            
            print("\n   Relationship breakdown:")
            for rel_type, count in rel_types.items():
                print(f"   - {rel_type}: {count}")
            
            # Show sample relationships
            print("\n   Sample relationships:")
            for i, rel in enumerate(result.staged_relationships[:10]):
                print(f"   {i+1}. {rel.from_node_label}({rel.from_node_id[:8]}...) "
                      f"-[{rel.relationship_type}]-> "
                      f"{rel.to_node_label}({rel.to_node_id[:8]}...)")
            
            if len(result.staged_relationships) > 10:
                print(f"   ... and {len(result.staged_relationships) - 10} more relationships")
                
        else:
            print(f"❌ Relationship building failed: {result.error_message}")
            
    except Exception as e:
        print(f"❌ Error building relationships: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Step 5: Verify relationships were saved
    print("\n5. Verifying saved relationships...")
    new_relationships = check_existing_relationships(doc_info['document_uuid'], db_manager)
    
    if new_relationships:
        print("✅ Relationships saved to database:")
        for rel_type, count in new_relationships.items():
            print(f"   - {rel_type}: {count}")
    else:
        print("⚠️  No relationships found in database")
    
    print("\n" + "="*60)
    print("Structural Relationship Building Test Complete!")
    print("="*60)

if __name__ == "__main__":
    main()