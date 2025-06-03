#!/usr/bin/env python3
"""Debug the EntityMention issue more directly"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Test creating and using EntityMentionMinimal
from scripts.core.models_minimal import EntityMentionMinimal
import uuid

# Create a test mention
test_data = {
    'mention_uuid': uuid.uuid4(),
    'chunk_uuid': uuid.uuid4(),
    'document_uuid': uuid.uuid4(),
    'entity_text': 'Test Entity',
    'entity_type': 'ORG',
    'start_char': 0,
    'end_char': 10,
    'confidence_score': 0.9
}

print("Creating EntityMentionMinimal...")
mention = EntityMentionMinimal(**test_data)
print(f"✓ Created: {mention}")

# Check if it has a text attribute
print(f"\nChecking attributes:")
print(f"  entity_text: {mention.entity_text}")
print(f"  Has 'text' attribute: {hasattr(mention, 'text')}")

# Try to access .text and see what happens
try:
    print(f"  mention.text: {mention.text}")
except AttributeError as e:
    print(f"  ✗ AttributeError when accessing .text: {e}")

# Check all attributes
print(f"\nAll attributes:")
for attr in dir(mention):
    if not attr.startswith('_'):
        print(f"  {attr}")

# Now test with entity resolution
print("\n\nTesting with entity resolution...")
from scripts.entity_resolution_fixes import resolve_entities_simple

# Create multiple mentions
mentions = []
for i in range(3):
    mention_data = {
        'mention_uuid': uuid.uuid4(),
        'chunk_uuid': uuid.uuid4(), 
        'document_uuid': uuid.uuid4(),
        'entity_text': f'Test Entity {i%2}',  # Will create duplicates
        'entity_type': 'ORG',
        'start_char': i * 20,
        'end_char': i * 20 + 10,
        'confidence_score': 0.9
    }
    mentions.append(mention_data)

print(f"Created {len(mentions)} test mentions")

try:
    result = resolve_entities_simple(mentions, str(uuid.uuid4()))
    print(f"✓ Resolution succeeded: {result['total_canonical']} canonical entities")
except Exception as e:
    print(f"✗ Resolution failed: {e}")
    import traceback
    traceback.print_exc()