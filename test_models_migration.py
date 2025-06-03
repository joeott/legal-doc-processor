#!/usr/bin/env python3
"""
Test the new consolidated models to ensure they work correctly
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scripts.models import (
    ModelFactory, 
    SourceDocumentMinimal,
    DocumentChunkMinimal,
    EntityMentionMinimal,
    CanonicalEntityMinimal,
    RelationshipStagingMinimal,
    ProcessingStatus,
    EntityType
)
import uuid
from datetime import datetime

def test_models():
    """Test all minimal models"""
    
    print("🧪 Testing Consolidated Minimal Models")
    print("="*50)
    
    # Test 1: Document Model
    print("\n1️⃣ Testing SourceDocumentMinimal...")
    doc = ModelFactory.create_document(
        document_uuid=uuid.uuid4(),
        project_uuid=uuid.uuid4(),
        file_name="test.pdf",
        status=ProcessingStatus.PENDING
    )
    print(f"✅ Created document: {doc.document_uuid}")
    print(f"   Status: {doc.status}")
    
    # Test 2: Chunk Model with database column names
    print("\n2️⃣ Testing DocumentChunkMinimal...")
    chunk = ModelFactory.create_chunk(
        chunk_uuid=uuid.uuid4(),
        document_uuid=doc.document_uuid,
        chunk_index=0,
        text="This is test chunk text",
        char_start_index=0,  # Using database column name
        char_end_index=23    # Using database column name
    )
    print(f"✅ Created chunk: {chunk.chunk_uuid}")
    print(f"   Text: {chunk.text}")
    print(f"   Range: {chunk.start_char}-{chunk.end_char}")
    
    # Test 3: Entity Mention Model
    print("\n3️⃣ Testing EntityMentionMinimal...")
    mention = ModelFactory.create_entity_mention(
        mention_uuid=uuid.uuid4(),
        chunk_uuid=chunk.chunk_uuid,
        document_uuid=doc.document_uuid,
        entity_text="Test Entity",
        entity_type=EntityType.ORG,
        start_char=0,
        end_char=11
    )
    print(f"✅ Created entity mention: {mention.entity_text}")
    print(f"   Type: {mention.entity_type}")
    
    # Test 4: Canonical Entity Model
    print("\n4️⃣ Testing CanonicalEntityMinimal...")
    canonical = ModelFactory.create_canonical_entity(
        canonical_entity_uuid=uuid.uuid4(),
        entity_type=EntityType.ORG,
        canonical_name="Test Organization",
        entity_names=["Test Org", "Test Organization", "T.O."]
    )
    print(f"✅ Created canonical entity: {canonical.canonical_name}")
    print(f"   Variations: {canonical.entity_names}")
    
    # Test 5: Relationship Model
    print("\n5️⃣ Testing RelationshipStagingMinimal...")
    rel = ModelFactory.create_relationship(
        relationship_uuid=uuid.uuid4(),
        source_uuid=doc.document_uuid,
        target_uuid=canonical.canonical_entity_uuid,
        relationship_type="MENTIONS",
        document_uuid=doc.document_uuid
    )
    print(f"✅ Created relationship: {rel.relationship_type}")
    print(f"   Source → Target")
    
    # Test 6: Model Serialization
    print("\n6️⃣ Testing Model Serialization...")
    doc_dict = doc.model_dump()
    print(f"✅ Document serialized to dict with {len(doc_dict)} fields")
    
    doc_json = doc.model_dump_json()
    print(f"✅ Document serialized to JSON ({len(doc_json)} chars)")
    
    print("\n✅ All model tests passed!")
    
    # Test 7: Factory Methods
    print("\n7️⃣ Testing Model Factory...")
    assert ModelFactory.get_document_model() == SourceDocumentMinimal
    assert ModelFactory.get_chunk_model() == DocumentChunkMinimal
    assert ModelFactory.get_entity_mention_model() == EntityMentionMinimal
    assert ModelFactory.get_canonical_entity_model() == CanonicalEntityMinimal
    assert ModelFactory.get_relationship_model() == RelationshipStagingMinimal
    print("✅ All factory methods work correctly")
    
    print("\n" + "="*50)
    print("✅ Model migration test complete - all models working!")
    
    return True

if __name__ == "__main__":
    try:
        test_models()
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)