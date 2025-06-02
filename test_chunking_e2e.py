#!/usr/bin/env python3
"""Test script to verify multi-chunk creation works end-to-end"""

import os
import sys
sys.path.append('/opt/legal-doc-processor')

# Source environment variables
os.system('source /opt/legal-doc-processor/load_env.sh')

from scripts.pdf_tasks import chunk_document_text
from scripts.db import DatabaseManager
from scripts.cache import get_redis_manager
from sqlalchemy import text
import uuid
from datetime import datetime

# Test parameters
test_doc_uuid = str(uuid.uuid4())  # New test document
test_text = "This is a test document. " * 200  # Create ~4800 chars of text

print(f"Testing chunking with document UUID: {test_doc_uuid}")
print(f"Text length: {len(test_text)} characters")
print(f"Expected chunks with size=1000, overlap=200: ~6 chunks")
print("-" * 80)

# Create a test document in the database first
db = DatabaseManager(validate_conformance=False)
session = next(db.get_session())

try:
    # Insert test document
    insert_query = text("""
        INSERT INTO source_documents (
            document_uuid, original_file_name, s3_key, 
            status, text, created_at, updated_at
        ) VALUES (
            :uuid, :filename, :s3_key,
            :status, :text, :created_at, :updated_at
        )
    """)
    
    session.execute(insert_query, {
        'uuid': test_doc_uuid,
        'filename': 'test_chunking.txt',
        's3_key': f'test/{test_doc_uuid}/test_chunking.txt',
        'status': 'ocr_completed',
        'text': test_text,
        'created_at': datetime.utcnow(),
        'updated_at': datetime.utcnow()
    })
    session.commit()
    print("✓ Test document created in database")
    
    # Clear any cached chunks
    redis_manager = get_redis_manager()
    cache_key = f"doc:chunks:{test_doc_uuid}"
    redis_manager.delete(cache_key)
    print("✓ Cache cleared")
    
    # Now test the chunking task
    print("\nCalling chunk_document_text task...")
    
    # Create a mock Celery task
    class MockCeleryTask:
        def __init__(self):
            self.request = type('obj', (object,), {'id': 'test-task-123'})()
    
    task = chunk_document_text
    task.db_manager = db
    task.request = MockCeleryTask().request
    
    # Call the chunking function
    try:
        result = task(
            document_uuid=test_doc_uuid,
            text=test_text,
            chunk_size=1000,
            overlap=200
        )
        print(f"✓ Chunking completed successfully")
        print(f"  Returned {len(result)} chunks")
        
    except Exception as e:
        print(f"✗ Chunking failed: {e}")
        import traceback
        traceback.print_exc()
    
    # Check what's in the database
    print("\nChecking database for chunks...")
    chunk_query = text("""
        SELECT chunk_uuid, chunk_index, 
               LENGTH(text) as text_length,
               char_start_index, char_end_index
        FROM document_chunks 
        WHERE document_uuid = :uuid
        ORDER BY chunk_index
    """)
    
    result = session.execute(chunk_query, {"uuid": test_doc_uuid})
    chunks = result.fetchall()
    
    print(f"\nFound {len(chunks)} chunks in database:")
    for chunk in chunks:
        print(f"  Chunk {chunk.chunk_index}: {chunk.text_length} chars, range [{chunk.char_start_index}:{chunk.char_end_index}]")
    
    # Cleanup
    print("\nCleaning up test data...")
    session.execute(
        text("DELETE FROM document_chunks WHERE document_uuid = :uuid"),
        {"uuid": test_doc_uuid}
    )
    session.execute(
        text("DELETE FROM source_documents WHERE document_uuid = :uuid"),
        {"uuid": test_doc_uuid}
    )
    session.commit()
    print("✓ Test data cleaned up")
    
finally:
    session.close()

print("\nTest complete!")