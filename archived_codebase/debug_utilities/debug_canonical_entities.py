#!/usr/bin/env python3
"""Debug canonical entity saving issue"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scripts.db import DatabaseManager
from scripts.entity_resolution_fixes import save_canonical_entities_to_db
from sqlalchemy import text
import uuid
from datetime import datetime

# Initialize database
db_manager = DatabaseManager()
session = next(db_manager.get_session())

# Check if we have entity mentions
doc_uuid = '5805f7b5-09ca-4f95-a990-da2dd758fd9e'
result = session.execute(
    text("SELECT COUNT(*) FROM entity_mentions WHERE document_uuid = :uuid"),
    {'uuid': doc_uuid}
)
mention_count = result.scalar()
print(f"Entity mentions for document: {mention_count}")

# Check canonical entities table structure
result = session.execute(
    text("""
        SELECT column_name, data_type 
        FROM information_schema.columns 
        WHERE table_name = 'canonical_entities'
        ORDER BY ordinal_position
    """)
)
print("\nCanonical entities table structure:")
for row in result:
    print(f"  {row.column_name}: {row.data_type}")

# Try to create and save a test canonical entity
test_entity = {
    'canonical_entity_uuid': uuid.uuid4(),
    'canonical_name': 'Test Entity',
    'entity_type': 'ORG',
    'mention_count': 1,
    'confidence_score': 0.95,
    'resolution_method': 'test',
    'aliases': ['Test', 'Test Ent'],
    'metadata': {'test': True},
    'created_at': datetime.utcnow()
}

print(f"\nTrying to save test entity: {test_entity['canonical_name']}")
try:
    saved = save_canonical_entities_to_db([test_entity], doc_uuid, db_manager)
    print(f"Saved {saved} entities")
    
    # Check if it was saved
    result = session.execute(
        text("SELECT canonical_name FROM canonical_entities WHERE canonical_entity_uuid = :uuid"),
        {'uuid': str(test_entity['canonical_entity_uuid'])}
    )
    row = result.fetchone()
    if row:
        print(f"✓ Successfully saved and retrieved: {row.canonical_name}")
    else:
        print("✗ Entity was not found after saving")
        
except Exception as e:
    print(f"Error saving: {e}")
    import traceback
    traceback.print_exc()

session.close()