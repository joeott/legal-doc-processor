#!/usr/bin/env python3
"""Trigger chunking for test document with logging enabled"""

import os
import sys
sys.path.append('/opt/legal-doc-processor')

os.environ['USE_MINIMAL_MODELS'] = 'true'
os.environ['SKIP_CONFORMANCE_CHECK'] = 'true'

# Enable DEBUG logging for our modules
import logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger('scripts.pdf_tasks')
logger.setLevel(logging.DEBUG)

from scripts.cache import get_redis_manager, CacheKeys
from scripts.pdf_tasks import chunk_document_text
from scripts.db import DatabaseManager
from sqlalchemy import text

# Test document from context_307
doc_uuid = "5805f7b5-09ca-4f95-a990-da2dd758fd9e"

print(f"Triggering chunking for document: {doc_uuid}")
print("-" * 80)

# Get document text from database
db = DatabaseManager(validate_conformance=False)
session = next(db.get_session())
try:
    result = session.execute(
        text("SELECT raw_extracted_text FROM source_documents WHERE document_uuid = :uuid"),
        {"uuid": doc_uuid}
    )
    row = result.fetchone()
    
    if not row or not row[0]:
        print("❌ No OCR text found for document")
        sys.exit(1)
    
    text_content = row[0]
    print(f"✓ Found OCR text: {len(text_content)} characters")
    
    # Clear existing chunks
    session.execute(
        text("DELETE FROM document_chunks WHERE document_uuid = :uuid"),
        {"uuid": doc_uuid}
    )
    session.commit()
    print("✓ Cleared existing chunks")
    
finally:
    session.close()

# Clear cache
redis = get_redis_manager()
cache_key = CacheKeys.DOC_CHUNKS.format(document_uuid=doc_uuid)
redis.delete(cache_key)
print("✓ Cleared chunk cache")

# Trigger chunking task
print("\nTriggering chunk_document_text task...")
print(f"Parameters: chunk_size=1000, overlap=200")

task = chunk_document_text.delay(
    doc_uuid, 
    text_content, 
    chunk_size=1000, 
    overlap=200
)

print(f"✓ Chunking task submitted: {task.id}")
print("\nWaiting for task to complete...")

# Wait for task completion
import time
max_wait = 30  # seconds
start_time = time.time()

while time.time() - start_time < max_wait:
    if task.ready():
        if task.successful():
            result = task.result
            print(f"\n✓ Task completed successfully!")
            print(f"  Result type: {type(result)}")
            if isinstance(result, list):
                print(f"  Number of chunks returned: {len(result)}")
            break
        else:
            print(f"\n❌ Task failed: {task.info}")
            break
    time.sleep(1)
    print(".", end="", flush=True)

if not task.ready():
    print(f"\n⚠️ Task still running after {max_wait} seconds")

# Check database for chunks
print("\nChecking database for chunks...")
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
        {"uuid": doc_uuid}
    )
    
    chunks = chunk_result.fetchall()
    print(f"\n✓ Found {len(chunks)} chunks in database:")
    for chunk in chunks:
        print(f"  Chunk {chunk.chunk_index}: {chunk.text_length} chars [{chunk.char_start_index}-{chunk.char_end_index}]")
        
finally:
    session.close()

print("\nTest complete!")