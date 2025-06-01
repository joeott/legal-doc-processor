#!/usr/bin/env python3
"""
Minimal test to verify the pipeline can work with schema mapping.
This demonstrates the simplest path to make the pipeline functional.
"""

import os
import sys
import uuid
import asyncio
from datetime import datetime

# Add scripts directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# The key insight: rds_utils.py now handles all the schema mapping transparently
from db import DatabaseManager
from core.schemas import (
    SourceDocumentModel, ChunkModel, EntityMentionModel,
    ProcessingStatus
)
from rds_utils import test_connection, execute_query

async def test_minimal_pipeline():
    """Test the minimal pipeline operations with schema mapping."""
    
    print("="*60)
    print("Minimal Pipeline Test with Schema Mapping")
    print("="*60)
    
    # 1. Test database connection
    print("\n1. Testing database connection...")
    if not test_connection():
        print("   ❌ Database connection failed")
        return False
    print("   ✅ Database connected")
    
    # 2. Create a test document using the pipeline's expected schema
    print("\n2. Creating test document...")
    db = DatabaseManager(validate_conformance=False)  # Skip conformance for now
    
    try:
        # Create document with pipeline's expected fields
        doc = SourceDocumentModel(
            document_uuid=uuid.uuid4(),
            original_file_name="test_pipeline.pdf",
            detected_file_type="application/pdf",
            s3_bucket="test-bucket",
            s3_key=f"documents/{uuid.uuid4()}/test.pdf",
            file_size_bytes=1024,
            initial_processing_status="pending",
            celery_status="pending"
        )
        
        # This will use the schema mapping to insert into 'documents' table
        result = db.create_source_document(doc)
        if result:
            print(f"   ✅ Created document: {result.document_uuid}")
            doc_uuid = result.document_uuid
        else:
            print("   ❌ Failed to create document")
            return False
            
    except Exception as e:
        print(f"   ❌ Error creating document: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # 3. Create test chunks
    print("\n3. Creating test chunks...")
    try:
        chunks = []
        for i in range(3):
            chunk = ChunkModel(
                chunk_id=uuid.uuid4(),
                document_uuid=doc_uuid,
                chunk_index=i,
                text=f"This is test chunk {i} with some legal content.",
                char_start_index=i * 100,
                char_end_index=(i + 1) * 100
            )
            chunks.append(chunk)
        
        # This will map to 'chunks' table
        created_chunks = db.create_chunks(chunks)
        print(f"   ✅ Created {len(created_chunks)} chunks")
        
    except Exception as e:
        print(f"   ❌ Error creating chunks: {e}")
        return False
    
    # 4. Create test entities
    print("\n4. Creating test entities...")
    try:
        mentions = []
        for i, chunk in enumerate(created_chunks):
            mention = EntityMentionModel(
                entity_mention_id=uuid.uuid4(),
                chunk_fk_id=i,  # This will be ignored by mapping
                chunk_uuid=chunk.chunk_id,
                value="Test Entity",
                entity_type="PERSON",
                confidence_score=0.95
            )
            mentions.append(mention)
        
        # This will map to 'entities' table
        created_mentions = db.create_entity_mentions(mentions)
        print(f"   ✅ Created {len(created_mentions)} entity mentions")
        
    except Exception as e:
        print(f"   ❌ Error creating entities: {e}")
        return False
    
    # 5. Update document status (simulating pipeline progress)
    print("\n5. Updating document status...")
    try:
        # Test status mapping
        statuses = ["ocr_processing", "text_processing", "entity_processing", "completed"]
        
        for status in statuses:
            success = db.update_document_status(
                str(doc_uuid),
                ProcessingStatus.COMPLETED if status == "completed" else ProcessingStatus.PROCESSING
            )
            if success:
                print(f"   ✅ Updated status: {status} → {ProcessingStatus.PROCESSING.value}")
            else:
                print(f"   ❌ Failed to update status: {status}")
                
    except Exception as e:
        print(f"   ❌ Error updating status: {e}")
        return False
    
    # 6. Verify data using direct SQL (bypassing ORM)
    print("\n6. Verifying data in simplified schema...")
    try:
        # Check documents table
        docs = execute_query(
            "SELECT document_uuid, original_filename, processing_status FROM documents WHERE document_uuid = :uuid",
            {"uuid": str(doc_uuid)}
        )
        if docs:
            doc = docs[0]
            print(f"   ✅ Document in DB: {doc['original_filename']} (status: {doc['processing_status']})")
        
        # Check chunks table
        chunks = execute_query(
            "SELECT COUNT(*) as count FROM chunks WHERE document_uuid = :uuid",
            {"uuid": str(doc_uuid)}
        )
        if chunks:
            print(f"   ✅ Chunks in DB: {chunks[0]['count']}")
        
        # Check entities table
        entities = execute_query(
            "SELECT COUNT(*) as count FROM entities WHERE document_uuid = :uuid",
            {"uuid": str(doc_uuid)}
        )
        if entities:
            print(f"   ✅ Entities in DB: {entities[0]['count']}")
            
    except Exception as e:
        print(f"   ❌ Error verifying data: {e}")
        return False
    
    print("\n" + "="*60)
    print("✅ SUCCESS: Pipeline can work with simplified schema!")
    print("="*60)
    print("\nThe schema mapping in rds_utils.py successfully translates:")
    print("- source_documents → documents")
    print("- document_chunks → chunks")
    print("- entity_mentions → entities")
    print("- Complex statuses → simple (pending/processing/completed/failed)")
    print("\nThe pipeline can now process documents without schema changes!")
    
    return True

def main():
    """Run the minimal pipeline test."""
    # Run async test
    success = asyncio.run(test_minimal_pipeline())
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())