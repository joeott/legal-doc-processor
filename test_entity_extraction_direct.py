#!/usr/bin/env python3
"""Test entity extraction directly without Celery"""

import os
import sys
sys.path.append('/opt/legal-doc-processor')

os.environ['USE_MINIMAL_MODELS'] = 'true'
os.environ['SKIP_CONFORMANCE_CHECK'] = 'true'

from scripts.db import DatabaseManager
from scripts.entity_service import EntityService
from scripts.config import OPENAI_API_KEY
from sqlalchemy import text as sql_text
import json

# Test document
doc_uuid = "5805f7b5-09ca-4f95-a990-da2dd758fd9e"

print("Direct Entity Extraction Test (No Celery)")
print("=" * 80)

# Initialize services
db = DatabaseManager(validate_conformance=False)
entity_service = EntityService(db, OPENAI_API_KEY)

print(f"✓ Initialized EntityService")
print(f"✓ OpenAI API Key: {'Set' if OPENAI_API_KEY else 'NOT SET'}")

# Get first chunk for testing
session = next(db.get_session())
try:
    result = session.execute(
        sql_text("""
            SELECT chunk_uuid, text, chunk_index
            FROM document_chunks 
            WHERE document_uuid = :uuid
            ORDER BY chunk_index
            LIMIT 1
        """),
        {"uuid": doc_uuid}
    )
    
    chunk = result.fetchone()
    if not chunk:
        print("❌ No chunks found")
        sys.exit(1)
    
    chunk_uuid = chunk.chunk_uuid  # Keep as UUID, don't convert to string
    chunk_text = chunk.text[:500]  # Use first 500 chars for faster testing
    
    print(f"\nTest chunk:")
    print(f"  UUID: {chunk_uuid}")
    print(f"  Index: {chunk.chunk_index}")
    print(f"  Text length: {len(chunk_text)} chars")
    print(f"  Preview: {chunk_text[:100]}...")
    
finally:
    session.close()

# Test entity extraction
print("\n" + "-"*60)
print("Testing entity extraction...")
print("-"*60)

try:
    # Call entity extraction
    result = entity_service.extract_entities_from_chunk(
        chunk_text=chunk_text,
        chunk_uuid=chunk_uuid,
        document_uuid=doc_uuid,
        use_openai=True  # Force OpenAI usage
    )
    
    print(f"\n✅ Entity extraction completed!")
    print(f"  Status: {result.status}")
    print(f"  Entity mentions: {len(result.entity_mentions)}")
    print(f"  Canonical entities: {len(result.canonical_entities)}")
    
    if result.entity_mentions:
        print("\nFirst 5 entities:")
        for i, mention in enumerate(result.entity_mentions[:5]):
            print(f"  {i+1}. '{mention.entity_text}' ({mention.entity_type}) conf={mention.confidence_score:.2f}")
    
    # Test database persistence
    print("\n" + "-"*60)
    print("Testing database persistence...")
    print("-"*60)
    
    # Save entities to database
    session = next(db.get_session())
    try:
        # Clear existing entities for this chunk
        session.execute(
            sql_text("DELETE FROM entity_mentions WHERE chunk_uuid = :uuid"),
            {"uuid": chunk_uuid}
        )
        session.commit()
        
        # Insert new entities
        for mention in result.entity_mentions:
            insert_query = sql_text("""
                INSERT INTO entity_mentions 
                (mention_uuid, chunk_uuid, document_uuid, entity_text, 
                 entity_type, start_char, end_char, confidence_score, created_at)
                VALUES 
                (:mention_uuid, :chunk_uuid, :document_uuid, :entity_text,
                 :entity_type, :start_char, :end_char, :confidence_score, NOW())
            """)
            
            session.execute(insert_query, {
                'mention_uuid': str(mention.mention_uuid),
                'chunk_uuid': str(mention.chunk_uuid),
                'document_uuid': str(mention.document_uuid),
                'entity_text': mention.entity_text,
                'entity_type': mention.entity_type,
                'start_char': mention.start_char,
                'end_char': mention.end_char,
                'confidence_score': mention.confidence_score
            })
        
        session.commit()
        print(f"✓ Saved {len(result.entity_mentions)} entities to database")
        
        # Verify they were saved
        count_result = session.execute(
            sql_text("SELECT COUNT(*) as count FROM entity_mentions WHERE chunk_uuid = :uuid"),
            {"uuid": chunk_uuid}
        )
        count = count_result.fetchone().count
        print(f"✓ Verified {count} entities in database")
        
    finally:
        session.close()
    
except Exception as e:
    print(f"\n❌ Entity extraction failed: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()

print("\nTest complete!")