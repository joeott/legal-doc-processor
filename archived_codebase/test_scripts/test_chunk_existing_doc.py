#!/usr/bin/env python3
"""Test chunking on existing document with OCR text"""

import os
import sys
sys.path.append('/opt/legal-doc-processor')

os.environ['USE_MINIMAL_MODELS'] = 'true'
os.environ['SKIP_CONFORMANCE_CHECK'] = 'true'

from scripts.pdf_tasks import chunk_document_text
from scripts.db import DatabaseManager
from scripts.cache import get_redis_manager
from sqlalchemy import text

# Test with existing document from context_307
test_doc_uuid = '5805f7b5-09ca-4f95-a990-da2dd758fd9e'

print(f"Testing chunking for existing document: {test_doc_uuid}")
print("-" * 80)

# Initialize managers
db = DatabaseManager(validate_conformance=False)
redis_manager = get_redis_manager()

# Clear cache first
cache_key = f"doc:chunks:{test_doc_uuid}"
redis_manager.delete(cache_key)
print("✓ Cache cleared")

# Get document text
session = next(db.get_session())
try:
    # Use raw_extracted_text column
    result = session.execute(
        text("SELECT raw_extracted_text FROM source_documents WHERE document_uuid = :uuid"),
        {"uuid": test_doc_uuid}
    )
    row = result.fetchone()
    
    if not row or not row[0]:
        print("❌ No OCR text found for document")
        sys.exit(1)
    
    ocr_text = row[0]
    print(f"✓ Found OCR text: {len(ocr_text)} characters")
    
    # Delete existing chunks
    session.execute(
        text("DELETE FROM document_chunks WHERE document_uuid = :uuid"),
        {"uuid": test_doc_uuid}
    )
    session.commit()
    print("✓ Cleared existing chunks")
    
finally:
    session.close()

# Now test chunking with the Celery task
print("\nCalling chunk_document_text task...")

# Create a mock Celery task context
class MockCeleryTask:
    def __init__(self):
        self.request = type('obj', (object,), {'id': 'test-task-123'})()

# Prepare the task
task = chunk_document_text
task.db_manager = db
task.request = MockCeleryTask().request

# Test validation bypass
task.validate_conformance = lambda: True
task.conformance_validated = True

try:
    # Call the task with chunking parameters
    result = task(
        document_uuid=test_doc_uuid,
        text=ocr_text,
        chunk_size=1000,
        overlap=200
    )
    
    print(f"✓ Chunking completed!")
    print(f"  Task returned {len(result)} chunks")
    
    # Check database
    session = next(db.get_session())
    try:
        chunk_result = session.execute(
            text("""
                SELECT chunk_index, LENGTH(text) as text_length,
                       char_start_index, char_end_index
                FROM document_chunks 
                WHERE document_uuid = :uuid
                ORDER BY chunk_index
            """),
            {"uuid": test_doc_uuid}
        )
        
        chunks = chunk_result.fetchall()
        print(f"\n✓ Found {len(chunks)} chunks in database:")
        for chunk in chunks:
            print(f"  Chunk {chunk.chunk_index}: {chunk.text_length} chars [{chunk.char_start_index}-{chunk.char_end_index}]")
            
    finally:
        session.close()
    
except Exception as e:
    print(f"❌ Chunking failed: {e}")
    import traceback
    traceback.print_exc()

print("\nTest complete!")