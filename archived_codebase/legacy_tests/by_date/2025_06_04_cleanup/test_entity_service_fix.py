#!/usr/bin/env python3
"""Test the entity service fix for the missing import functions."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Mock the config module to avoid environment errors
import unittest.mock as mock
with mock.patch.dict(os.environ, {
    'OPENAI_API_KEY': 'test-key',
    'DATABASE_URL': 'postgresql://test',
    'DATABASE_URL_DIRECT': 'postgresql://test',
    'REDIS_HOST': 'localhost',
    'REDIS_PORT': '6379',
    'REDIS_PASSWORD': 'test',
    'AWS_ACCESS_KEY_ID': 'test',
    'AWS_SECRET_ACCESS_KEY': 'test',
    'AWS_DEFAULT_REGION': 'us-east-1',
    'S3_PRIMARY_DOCUMENT_BUCKET': 'test-bucket',
    'DEPLOYMENT_STAGE': '1'
}):
    from scripts.entity_service import EntityService

def test_methods_exist():
    """Test that the methods exist and are callable."""
    # Create a mock db_manager
    from scripts.db import DatabaseManager
    
    # Mock the DatabaseManager methods
    with mock.patch.object(DatabaseManager, '__init__', return_value=None):
        with mock.patch.object(DatabaseManager, 'validate_conformance', return_value=None):
            db_manager = DatabaseManager()
            service = EntityService(db_manager)
    
    # Check methods exist
    assert hasattr(service, '_create_openai_prompt_for_limited_entities')
    assert hasattr(service, '_filter_and_fix_entities')
    
    # Test prompt creation
    prompt = service._create_openai_prompt_for_limited_entities()
    assert isinstance(prompt, str)
    assert 'PERSON' in prompt
    assert 'ORG' in prompt
    assert 'LOCATION' in prompt
    assert 'DATE' in prompt
    
    # Test entity filtering
    test_entities = [
        {'text': 'John Doe', 'type': 'PERSON'},
        {'text': 'Acme Corp', 'type': 'ORG'},
        {'text': 'New York', 'type': 'LOCATION'},
        {'text': 'January 1, 2024', 'type': 'DATE'},
        {'text': '$1000', 'type': 'MONEY'},  # Should be filtered out
        {'text': '12 USC 1234', 'type': 'STATUTE'},  # Should be filtered out
    ]
    
    filtered = service._filter_and_fix_entities(test_entities)
    
    # Should only have 4 entities (MONEY and STATUTE filtered out)
    assert len(filtered) == 4
    
    # Check filtered types
    allowed_types = {'PERSON', 'ORG', 'LOCATION', 'DATE'}
    for entity in filtered:
        assert entity['type'] in allowed_types
    
    print("✓ All tests passed!")
    print(f"✓ Prompt method exists and returns valid prompt")
    print(f"✓ Filter method exists and correctly filters entities")
    print(f"✓ Filtered {len(test_entities)} entities to {len(filtered)} allowed entities")

if __name__ == '__main__':
    test_methods_exist()