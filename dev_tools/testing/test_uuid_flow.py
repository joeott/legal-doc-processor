#!/usr/bin/env python3
"""Test UUID handling through the pipeline"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uuid import uuid4, UUID
from scripts.models import *

def test_uuid_flow():
    """Test UUID handling at each stage"""
    
    # 1. Document creation
    doc_uuid = uuid4()
    doc = SourceDocumentMinimal(
        document_uuid=doc_uuid,
        file_name="test.pdf",
        status="pending"
    )
    assert isinstance(doc.document_uuid, UUID)
    print("✅ Document model UUID handling correct")
    
    # 2. Celery serialization simulation
    doc_uuid_str = str(doc_uuid)
    doc_uuid_restored = UUID(doc_uuid_str)
    assert doc_uuid == doc_uuid_restored
    print("✅ UUID string round-trip successful")
    
    # 3. Chunk creation
    chunk_uuid = uuid4()
    chunk = DocumentChunkMinimal(
        chunk_uuid=chunk_uuid,
        document_uuid=doc_uuid,
        chunk_index=0,
        text="Test chunk",
        char_start_index=0,
        char_end_index=10
    )
    assert isinstance(chunk.chunk_uuid, UUID)
    assert isinstance(chunk.document_uuid, UUID)
    print("✅ Chunk model UUID handling correct")
    
    # 4. Entity mention
    mention = EntityMentionMinimal(
        mention_uuid=uuid4(),
        chunk_uuid=chunk_uuid,
        document_uuid=doc_uuid,
        entity_text="Test Entity",
        entity_type="PERSON",
        start_char=0,
        end_char=11
    )
    assert isinstance(mention.mention_uuid, UUID)
    print("✅ Entity mention UUID handling correct")
    
    # 5. Canonical entity
    canonical = CanonicalEntityMinimal(
        canonical_entity_uuid=uuid4(),
        entity_type="PERSON",
        canonical_name="Test Entity"
    )
    assert isinstance(canonical.canonical_entity_uuid, UUID)
    print("✅ Canonical entity UUID handling correct")
    
    # 6. Relationship
    rel = RelationshipStagingMinimal(
        source_entity_uuid=uuid4(),
        target_entity_uuid=uuid4(),
        relationship_type="RELATED_TO"
    )
    assert isinstance(rel.source_entity_uuid, UUID)
    assert isinstance(rel.target_entity_uuid, UUID)
    print("✅ Relationship UUID handling correct")
    
    print("\n✅ All UUID handling tests passed!")

if __name__ == "__main__":
    test_uuid_flow()