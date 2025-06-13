#!/usr/bin/env python3
"""
Test entity extraction stage of the pipeline
Phase 2 of recovery plan from context_362
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.pdf_tasks import extract_entities_from_chunks
from scripts.db import get_db
from sqlalchemy import text

def test_entity_extraction_stage():
    """Test the entity extraction stage"""
    document_uuid = "4909739b-8f12-40cd-8403-04b8b1a79281"
    
    print("="*60)
    print("ENTITY EXTRACTION STAGE TEST")
    print("="*60)
    print(f"Document UUID: {document_uuid}")
    print(f"Time: {datetime.now()}")
    
    # First verify chunks exist and fetch them
    print("\n1. Checking document chunks...")
    chunks_data = []
    session = next(get_db())
    try:
        # Get chunk count first
        chunk_stats = session.execute(text("""
            SELECT 
                COUNT(*) as chunk_count,
                SUM(LENGTH(text)) as total_chars
            FROM document_chunks
            WHERE document_uuid = :uuid
        """), {"uuid": document_uuid}).fetchone()
        
        if not chunk_stats or chunk_stats.chunk_count == 0:
            print("✗ No chunks found! Run chunking first.")
            return False
            
        print(f"✓ Found {chunk_stats.chunk_count} chunks")
        print(f"  Total characters: {chunk_stats.total_chars}")
        
        # Fetch actual chunks
        chunks = session.execute(text("""
            SELECT 
                chunk_uuid,
                chunk_index,
                text,
                start_char_index,
                end_char_index,
                metadata_json
            FROM document_chunks
            WHERE document_uuid = :uuid
            ORDER BY chunk_index
        """), {"uuid": document_uuid}).fetchall()
        
        # Convert to list of dicts for the task
        for chunk in chunks:
            chunks_data.append({
                'chunk_uuid': str(chunk.chunk_uuid),
                'chunk_index': chunk.chunk_index,
                'chunk_text': chunk.text,
                'start_char': chunk.start_char_index,
                'end_char': chunk.end_char_index,
                'metadata': chunk.metadata_json or {}
            })
        
    finally:
        session.close()
    
    # Check existing entities
    print("\n2. Checking existing entities...")
    session = next(get_db())
    try:
        entity_count = session.execute(text("""
            SELECT COUNT(*) as count
            FROM entity_mentions
            WHERE document_uuid = :uuid
        """), {"uuid": document_uuid}).scalar()
        
        print(f"  Existing entities: {entity_count}")
        
    finally:
        session.close()
    
    # Check OpenAI API key
    print("\n3. Checking OpenAI configuration...")
    import os
    if os.getenv('OPENAI_API_KEY'):
        print("✓ OpenAI API key found")
    else:
        print("✗ OpenAI API key not found!")
        return False
    
    # Trigger entity extraction
    print("\n4. Triggering entity extraction task...")
    print(f"  Passing {len(chunks_data)} chunks to task")
    try:
        result = extract_entities_from_chunks.delay(document_uuid, chunks_data)
        print(f"✓ Task submitted: {result.id}")
        print(f"  Status: {result.status}")
        
        # Wait for completion
        print("\n5. Waiting for task completion...")
        import time
        for i in range(60):  # Wait up to 60 seconds
            if result.ready():
                break
            time.sleep(1)
            if i % 10 == 0:
                print(f"  Waiting... ({i}s)")
        
        if result.successful():
            print(f"✓ Task completed successfully!")
            print(f"  Result: {result.result}")
        elif result.failed():
            print(f"✗ Task failed!")
            print(f"  Error: {result.info}")
            if hasattr(result, 'traceback'):
                print(f"\n  Traceback:\n{result.traceback}")
        else:
            print(f"  Task status: {result.status}")
            
    except Exception as e:
        print(f"✗ Error triggering task: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    
    # Verify entities created
    print("\n6. Verifying entities created...")
    session = next(get_db())
    try:
        entities = session.execute(text("""
            SELECT 
                entity_type,
                COUNT(*) as count,
                COUNT(DISTINCT entity_text) as unique_count
            FROM entity_mentions
            WHERE document_uuid = :uuid
            GROUP BY entity_type
            ORDER BY count DESC
            LIMIT 10
        """), {"uuid": document_uuid}).fetchall()
        
        if entities:
            print(f"✓ Created entities by type:")
            total = 0
            for entity in entities:
                print(f"  {entity.entity_type}: {entity.count} mentions ({entity.unique_count} unique)")
                total += entity.count
            print(f"  Total: {total} entity mentions")
        else:
            print("✗ No entities created!")
            
    finally:
        session.close()
    
    return True

if __name__ == "__main__":
    success = test_entity_extraction_stage()
    print("\n" + "="*60)
    if success:
        print("✓ ENTITY EXTRACTION STAGE TEST COMPLETE")
    else:
        print("✗ ENTITY EXTRACTION STAGE TEST FAILED")
    print("="*60)