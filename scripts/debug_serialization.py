#!/usr/bin/env python3
"""
Debug chunk serialization
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.db import DatabaseManager

# Get a chunk model from db manager
db = DatabaseManager(validate_conformance=False)

# Check how the serialization works
print("Testing serialization...")

# Create a minimal chunk dict to test
test_data = {
    'chunk_uuid': 'test-uuid',
    'document_uuid': 'doc-uuid', 
    'chunk_index': 0,
    'text': 'Test text',
    'start_char': 0,
    'end_char': 100,
    'created_at': '2025-06-02T19:00:00'
}

# Check serialize_for_db
serialized = db.pydantic_db.serialize_for_db(test_data)
print(f"Serialized data: {serialized}")
print(f"Has text field: {'text' in serialized}")
print(f"Has text_content field: {'text_content' in serialized}")