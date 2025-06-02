#!/usr/bin/env python3
"""Debug script to check chunking issue in the database"""

import sys
sys.path.append('/opt/legal-doc-processor')

from scripts.db import DatabaseManager
from scripts.core.model_factory import get_chunk_model
from sqlalchemy import text
import uuid
from datetime import datetime

# Test document UUID from context_307
test_doc_uuid = '5805f7b5-09ca-4f95-a990-da2dd758fd9e'

print(f"Checking chunks for document: {test_doc_uuid}")
print("-" * 80)

# Get database manager
db = DatabaseManager(validate_conformance=False)

# Check chunks directly in database
session = next(db.get_session())
try:
    # Query chunks
    query = text("""
        SELECT chunk_uuid, chunk_index, 
               LENGTH(text) as text_length,
               start_char, end_char,
               created_at
        FROM document_chunks 
        WHERE document_uuid = :uuid
        ORDER BY chunk_index
    """)
    
    result = session.execute(query, {"uuid": test_doc_uuid})
    chunks = result.fetchall()
    
    print(f"\nFound {len(chunks)} chunks in database:")
    for chunk in chunks:
        print(f"\nChunk {chunk.chunk_index}:")
        print(f"  - UUID: {chunk.chunk_uuid}")
        print(f"  - Text length: {chunk.text_length}")
        print(f"  - Character range: {chunk.start_char} - {chunk.end_char}")
        print(f"  - Created at: {chunk.created_at}")
    
    # Also check the source document's text length
    doc_query = text("""
        SELECT LENGTH(text) as text_length,
               processing_status,
               updated_at
        FROM source_documents
        WHERE document_uuid = :uuid
    """)
    
    doc_result = session.execute(doc_query, {"uuid": test_doc_uuid})
    doc = doc_result.fetchone()
    
    if doc:
        print(f"\nSource document info:")
        print(f"  - Text length: {doc.text_length}")
        print(f"  - Processing status: {doc.processing_status}")
        print(f"  - Last updated: {doc.updated_at}")
    
    # Check if we're using the create_chunks method correctly
    print("\n" + "-" * 80)
    print("Testing chunk creation logic...")
    
    # Get chunk model
    ChunkModel = get_chunk_model()
    
    # Create test chunks
    test_chunks = []
    test_text = "a" * 3278  # Simulate document text
    
    # Simulate what should happen
    from scripts.chunking_utils import simple_chunk_text
    chunks_data = simple_chunk_text(test_text, 1000, 200)
    print(f"\nSimple chunk text returned {len(chunks_data)} chunks")
    
    # Try to create chunk models like in pdf_tasks.py
    for idx, chunk_data in enumerate(chunks_data):
        chunk_text = chunk_data['text']
        print(f"  - Chunk {idx}: {len(chunk_text)} characters")
        
finally:
    session.close()

print("\nDone.")