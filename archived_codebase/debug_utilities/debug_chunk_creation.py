#!/usr/bin/env python3
"""Debug chunk creation to see what's failing"""

import os
import sys
sys.path.append('/opt/legal-doc-processor')

os.environ['USE_MINIMAL_MODELS'] = 'true'
os.environ['SKIP_CONFORMANCE_CHECK'] = 'true'

from scripts.db import DatabaseManager
from scripts.core.model_factory import get_chunk_model
from scripts.chunking_utils import simple_chunk_text
import uuid
from datetime import datetime

# Test parameters
test_doc_uuid = "5805f7b5-09ca-4f95-a990-da2dd758fd9e"
test_text = "This is a test. " * 250  # 4000 chars

print("Testing chunk creation directly...")
print("-" * 80)

# Get managers
db = DatabaseManager(validate_conformance=False)
ChunkModel = get_chunk_model()

print(f"Using model: {ChunkModel.__name__}")
print(f"Model fields: {list(ChunkModel.model_fields.keys())}")

# Generate chunks
chunks_data = simple_chunk_text(test_text, 1000, 200)
print(f"\nGenerated {len(chunks_data)} chunks")

# Try to create chunk models
chunk_models = []
for idx, chunk_data in enumerate(chunks_data):
    try:
        chunk_model = ChunkModel(
            chunk_uuid=uuid.uuid4(),
            document_uuid=test_doc_uuid,
            chunk_index=idx,
            text=chunk_data['text'],
            start_char=chunk_data['char_start_index'],
            end_char=chunk_data['char_end_index'],
            created_at=datetime.utcnow()
        )
        chunk_models.append(chunk_model)
        print(f"✓ Created chunk model {idx}")
    except Exception as e:
        print(f"❌ Failed to create chunk model {idx}: {e}")

print(f"\nCreated {len(chunk_models)} chunk models")

# Try to save one chunk
if chunk_models:
    print(f"\nTrying to save first chunk to database...")
    try:
        # Debug the serialization
        print("Serializing chunk model...")
        serialized = db.pydantic_db.serialize_for_db(chunk_models[0])
        print(f"Serialized data keys: {list(serialized.keys())}")
        
        # Try raw insert first
        from scripts.rds_utils import insert_record
        print("\nTrying raw insert...")
        
        # Map fields to database columns
        db_data = {
            'chunk_uuid': str(chunk_models[0].chunk_uuid),
            'document_uuid': str(chunk_models[0].document_uuid),
            'chunk_index': chunk_models[0].chunk_index,
            'text': chunk_models[0].text,
            'char_start_index': chunk_models[0].start_char,
            'char_end_index': chunk_models[0].end_char,
            'created_at': chunk_models[0].created_at
        }
        
        result = insert_record('document_chunks', db_data)
        print(f"Insert result: {result}")
        
        if result:
            print(f"✓ Raw insert successful!")
            print(f"  Returned columns: {list(result.keys())}")
        
    except Exception as e:
        print(f"❌ Failed to save chunk: {e}")
        import traceback
        traceback.print_exc()

print("\nDone.")