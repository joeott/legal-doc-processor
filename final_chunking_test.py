#!/usr/bin/env python3
"""Final chunking test with cleanup"""

import os
import sys
sys.path.append('/opt/legal-doc-processor')

os.environ['USE_MINIMAL_MODELS'] = 'true'
os.environ['SKIP_CONFORMANCE_CHECK'] = 'true'

from scripts.cache import get_redis_manager, CacheKeys
from scripts.pdf_tasks import chunk_document_text
from scripts.db import DatabaseManager
from sqlalchemy import text
import time

# Test document from context_307
doc_uuid = "5805f7b5-09ca-4f95-a990-da2dd758fd9e"

print(f"Final chunking test for document: {doc_uuid}")
print("-" * 80)

# Get database connection
db = DatabaseManager(validate_conformance=False)

# Clean up ALL chunks for this document
print("Cleaning up existing chunks...")
session = next(db.get_session())
try:
    # Delete all chunks
    result = session.execute(
        text("DELETE FROM document_chunks WHERE document_uuid = :uuid"),
        {"uuid": doc_uuid}
    )
    deleted_count = result.rowcount
    session.commit()
    print(f"✓ Deleted {deleted_count} existing chunks")
    
    # Get document text
    result = session.execute(
        text("SELECT raw_extracted_text FROM source_documents WHERE document_uuid = :uuid"),
        {"uuid": doc_uuid}
    )
    row = result.fetchone()
    
    if not row or not row[0]:
        print("❌ No OCR text found")
        sys.exit(1)
    
    text_content = row[0]
    print(f"✓ Found OCR text: {len(text_content)} characters")
    
finally:
    session.close()

# Clear all caches
redis = get_redis_manager()
redis.delete(CacheKeys.DOC_CHUNKS.format(document_uuid=doc_uuid))
redis.delete(f"doc:state:{doc_uuid}:chunking")
print("✓ Cleared all caches")

# Submit chunking task
print("\nSubmitting chunking task...")
print("Parameters: chunk_size=1000, overlap=200")
print("Expected: ~4 chunks for 3278 characters")

task = chunk_document_text.delay(
    doc_uuid, 
    text_content, 
    chunk_size=1000, 
    overlap=200
)

print(f"✓ Task submitted: {task.id}")

# Wait for completion
print("\nWaiting for completion...")
max_wait = 10
for i in range(max_wait):
    if task.ready():
        break
    time.sleep(1)
    print(".", end="", flush=True)

print(f"\n\nTask status: {task.state}")
if task.failed():
    print(f"Error: {task.info}")

# Check final result
print("\nFinal database check:")
session = next(db.get_session())
try:
    result = session.execute(
        text("""
            SELECT chunk_index, 
                   LENGTH(text) as text_length,
                   char_start_index, 
                   char_end_index,
                   chunk_uuid
            FROM document_chunks 
            WHERE document_uuid = :uuid
            ORDER BY chunk_index
        """),
        {"uuid": doc_uuid}
    )
    
    chunks = result.fetchall()
    print(f"\n✓ Found {len(chunks)} chunks in database:")
    
    total_coverage = 0
    for chunk in chunks:
        char_range = f"[{chunk.char_start_index}-{chunk.char_end_index}]" if chunk.char_start_index is not None else "[NULL]"
        print(f"  Chunk {chunk.chunk_index}: {chunk.text_length} chars {char_range} UUID={chunk.chunk_uuid}")
        if chunk.char_start_index is not None and chunk.char_end_index is not None:
            total_coverage += (chunk.char_end_index - chunk.char_start_index)
    
    if len(chunks) > 0:
        print(f"\nCoverage: {total_coverage}/{len(text_content)} characters ({total_coverage/len(text_content)*100:.1f}%)")
        
finally:
    session.close()

print("\nTest complete!")