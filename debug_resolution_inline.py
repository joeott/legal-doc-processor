#!/usr/bin/env python3
"""Debug resolution inline to find the exact error"""

import os
import sys
import logging

# Set up detailed logging
logging.basicConfig(level=logging.DEBUG)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scripts.db import DatabaseManager
from sqlalchemy import text

# Get entity mentions
db_manager = DatabaseManager()
session = next(db_manager.get_session())

doc_uuid = '5805f7b5-09ca-4f95-a990-da2dd758fd9e'

result = session.execute(
    text("""
        SELECT mention_uuid, entity_text, entity_type, chunk_uuid
        FROM entity_mentions 
        WHERE document_uuid = :uuid
        LIMIT 1
    """),
    {'uuid': doc_uuid}
)

# Get just one mention
row = result.fetchone()
if row:
    mention_dict = {
        'mention_uuid': str(row.mention_uuid),
        'entity_text': row.entity_text,
        'entity_type': row.entity_type,
        'chunk_uuid': str(row.chunk_uuid)
    }
    print(f"Test mention: {mention_dict}")
    
    # Try to create EntityMentionModel from it
    try:
        from scripts.core.models_minimal import EntityMentionMinimal
        print("\nTrying to create EntityMentionMinimal from dict...")
        model = EntityMentionMinimal(**mention_dict)
        print(f"✓ Success! Created model: {model}")
    except Exception as e:
        print(f"✗ Failed to create model: {e}")
        print(f"Exception type: {type(e).__name__}")
        
        # Check what fields the model expects
        print("\nEntityMentionMinimal fields:")
        for field_name, field_info in EntityMentionMinimal.model_fields.items():
            print(f"  {field_name}: {field_info.annotation} (required: {field_info.is_required()})")

session.close()