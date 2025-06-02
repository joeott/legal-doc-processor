#!/usr/bin/env python3
"""Test chunking directly without Celery to verify the fix works"""

import os
import sys
sys.path.append('/opt/legal-doc-processor')

os.environ['USE_MINIMAL_MODELS'] = 'true'
os.environ['SKIP_CONFORMANCE_CHECK'] = 'true'

from scripts.db import DatabaseManager
from scripts.core.model_factory import get_chunk_model
from scripts.chunking_utils import simple_chunk_text
from scripts.rds_utils import insert_record
from sqlalchemy import text as sql_text
import uuid
from datetime import datetime
import time

# Test document
doc_uuid = "5805f7b5-09ca-4f95-a990-da2dd758fd9e"

print("Direct chunking test (no Celery)")
print("-" * 80)

# Get database and clear chunks
db = DatabaseManager(validate_conformance=False)
ChunkModel = get_chunk_model()

session = next(db.get_session())
try:
    # Clear existing chunks
    session.execute(
        sql_text("DELETE FROM document_chunks WHERE document_uuid = :uuid"),
        {"uuid": doc_uuid}
    )
    session.commit()
    print("✓ Cleared existing chunks")
    
    # Get document text
    result = session.execute(
        sql_text("SELECT raw_extracted_text FROM source_documents WHERE document_uuid = :uuid"),
        {"uuid": doc_uuid}
    )
    row = result.fetchone()
    text_content = row[0] if row else None
    
finally:
    session.close()

if not text_content:
    print("❌ No text found")
    sys.exit(1)

print(f"✓ Found text: {len(text_content)} characters")

# Generate chunks
chunks_data = simple_chunk_text(text_content, 1000, 200)
print(f"\n✓ Generated {len(chunks_data)} chunks")

# Create chunk models
chunk_models = []
for idx, chunk_data in enumerate(chunks_data):
    chunk_model = ChunkModel(
        chunk_uuid=uuid.uuid4(),
        document_uuid=doc_uuid,
        chunk_index=idx,
        text=chunk_data['text'],
        start_char=chunk_data.get('char_start_index', 0),
        end_char=chunk_data.get('char_end_index', len(chunk_data['text'])),
        created_at=datetime.utcnow()
    )
    chunk_models.append(chunk_model)

print(f"✓ Created {len(chunk_models)} chunk models")

# Test batch insertion
print("\n" + "="*60)
print("TESTING BATCH INSERTION")
print("="*60)

stored_chunks = []
failed_chunks = []

session = next(db.get_session())
try:
    # Execute batch insert
    insert_query = sql_text("""
        INSERT INTO document_chunks 
        (chunk_uuid, document_uuid, chunk_index, text, 
         char_start_index, char_end_index, created_at)
        VALUES 
        (:chunk_uuid, :document_uuid, :chunk_index, :text,
         :char_start_index, :char_end_index, :created_at)
        RETURNING id, chunk_uuid
    """)
    
    for i, chunk_model in enumerate(chunk_models):
        try:
            chunk_data = {
                'chunk_uuid': str(chunk_model.chunk_uuid),
                'document_uuid': str(chunk_model.document_uuid),
                'chunk_index': chunk_model.chunk_index,
                'text': chunk_model.text,
                'char_start_index': int(chunk_model.start_char),
                'char_end_index': int(chunk_model.end_char),
                'created_at': chunk_model.created_at
            }
            
            print(f"\nInserting chunk {i}:")
            print(f"  UUID: {chunk_data['chunk_uuid']}")
            print(f"  Range: [{chunk_data['char_start_index']}-{chunk_data['char_end_index']}]")
            print(f"  Text length: {len(chunk_data['text'])}")
            
            result = session.execute(insert_query, chunk_data)
            session.commit()
            
            row = result.fetchone()
            if row:
                stored_chunks.append(chunk_model)
                print(f"  ✓ Stored with ID: {row[0]}")
            else:
                print(f"  ❌ No result returned")
                failed_chunks.append((i, chunk_model, "No result"))
                
        except Exception as e:
            session.rollback()
            print(f"  ❌ Error: {type(e).__name__}: {e}")
            failed_chunks.append((i, chunk_model, str(e)))
            
finally:
    session.close()

print(f"\n" + "="*60)
print(f"RESULTS: {len(stored_chunks)}/{len(chunk_models)} chunks stored")
print("="*60)

# Verify in database
session = next(db.get_session())
try:
    result = session.execute(
        sql_text("""
            SELECT chunk_index, LENGTH(text) as text_length,
                   char_start_index, char_end_index
            FROM document_chunks 
            WHERE document_uuid = :uuid
            ORDER BY chunk_index
        """),
        {"uuid": doc_uuid}
    )
    
    chunks = result.fetchall()
    print(f"\nDatabase verification: {len(chunks)} chunks found")
    for chunk in chunks:
        print(f"  Chunk {chunk.chunk_index}: {chunk.text_length} chars [{chunk.char_start_index}-{chunk.char_end_index}]")
        
finally:
    session.close()

print("\nTest complete!")