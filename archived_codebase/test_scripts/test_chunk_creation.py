#!/usr/bin/env python3
"""
Test chunk model creation
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.core.model_factory import get_chunk_model
import uuid
from datetime import datetime

# Get chunk model
ChunkModel = get_chunk_model()

# Create a test chunk
chunk = ChunkModel(
    chunk_uuid=uuid.uuid4(),
    document_uuid=uuid.uuid4(),
    chunk_index=0,
    text="Test chunk text",
    start_char=0,
    end_char=100,
    created_at=datetime.utcnow()
)

print("Chunk model created successfully")
print(f"Model fields: {chunk.model_fields.keys()}")
print(f"Model dump: {chunk.model_dump()}")
print(f"Has text field: {'text' in chunk.model_dump()}")
print(f"Has text_content field: {'text_content' in chunk.model_dump()}")