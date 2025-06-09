"""
Unit tests for entity_service.py - Entity extraction and resolution.
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from typing import List, Dict, Any

from scripts.entity_service import EntityExtractor


@pytest.mark.unit
class TestEntityExtractor:
    """Test the EntityExtractor class."""
    
    def test_init(self, test_db):
        """Test EntityExtractor initialization."""
        extractor = EntityExtractor(test_db)
        
        assert extractor.db_manager == test_db
        assert hasattr(extractor, 'openai_client')
    
    @patch('scripts.entity_service.OpenAI')
    def test_extract_entities_from_text(self, mock_openai, test_db, sample_text):
        """Test entity extraction from text using OpenAI."""
        # Mock OpenAI response
        mock_client = Mock()
        mock_openai.return_value = mock_client
        
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = '''
        [
            {
                "text": "John Doe",
                "type": "PERSON", 
                "start_offset": 50,
                "end_offset": 58,
                "confidence": 0.95
            },
            {
                "text": "Jane Smith",
                "type": "PERSON",
                "start_offset": 70, 
                "end_offset": 80,
                "confidence": 0.92
            }
        ]
        '''
        mock_client.chat.completions.create.return_value = mock_response
        
        extractor = EntityExtractor(test_db)
        entities = extractor.extract_entities_from_text(sample_text)
        
        assert len(entities) == 2
        assert entities[0]['text'] == 'John Doe'
        assert entities[0]['type'] == 'PERSON'
        assert entities[1]['text'] == 'Jane Smith'
        
        # Verify OpenAI was called
        mock_client.chat.completions.create.assert_called_once()
    
    @patch('scripts.entity_service.OpenAI')
    def test_extract_entities_openai_error(self, mock_openai, test_db, sample_text):
        """Test entity extraction with OpenAI error."""
        # Mock OpenAI client that raises exception
        mock_client = Mock()
        mock_openai.return_value = mock_client
        mock_client.chat.completions.create.side_effect = Exception("API Error")
        
        extractor = EntityExtractor(test_db)
        
        # Should handle error gracefully
        entities = extractor.extract_entities_from_text(sample_text)
        
        assert entities == []  # Should return empty list on error
    
    def test_extract_entities_invalid_json(self, test_db, sample_text):
        """Test entity extraction with invalid JSON response."""
        with patch('scripts.entity_service.OpenAI') as mock_openai:
            mock_client = Mock()
            mock_openai.return_value = mock_client
            
            mock_response = Mock()
            mock_response.choices = [Mock()]
            mock_response.choices[0].message.content = "Invalid JSON response"
            mock_client.chat.completions.create.return_value = mock_response
            
            extractor = EntityExtractor(test_db)
            entities = extractor.extract_entities_from_text(sample_text)
            
            assert entities == []  # Should handle invalid JSON gracefully
    
    def test_validate_entity_structure(self, test_db):
        """Test entity structure validation."""
        extractor = EntityExtractor(test_db)
        
        # Valid entity
        valid_entity = {
            'text': 'John Doe',
            'type': 'PERSON',
            'start_offset': 0,
            'end_offset': 8,
            'confidence': 0.95
        }
        assert extractor._validate_entity_structure(valid_entity) is True
        
        # Missing required field
        invalid_entity = {
            'text': 'John Doe',
            'type': 'PERSON'
            # Missing offsets and confidence
        }
        assert extractor._validate_entity_structure(invalid_entity) is False
        
        # Invalid type
        invalid_type = {
            'text': 'John Doe',
            'type': 123,  # Should be string
            'start_offset': 0,
            'end_offset': 8,
            'confidence': 0.95
        }
        assert extractor._validate_entity_structure(invalid_type) is False
    
    def test_normalize_entity_text(self, test_db):
        """Test entity text normalization."""
        extractor = EntityExtractor(test_db)
        
        # Test whitespace normalization
        assert extractor._normalize_entity_text("  John Doe  ") == "John Doe"
        assert extractor._normalize_entity_text("John\nDoe") == "John Doe"
        assert extractor._normalize_entity_text("John\t\tDoe") == "John Doe"
        
        # Test case preservation
        assert extractor._normalize_entity_text("JOHN DOE") == "JOHN DOE"
        assert extractor._normalize_entity_text("john doe") == "john doe"
    
    def test_calculate_entity_confidence(self, test_db):
        """Test entity confidence calculation.""" 
        extractor = EntityExtractor(test_db)
        
        # Test confidence adjustment based on length
        short_entity = {'text': 'AI', 'confidence': 0.95}
        long_entity = {'text': 'John Doe Smith Jr.', 'confidence': 0.95}
        
        short_conf = extractor._calculate_entity_confidence(short_entity)
        long_conf = extractor._calculate_entity_confidence(long_entity)
        
        # Longer entities should get slight confidence boost
        assert long_conf >= short_conf
        
        # Test confidence bounds
        high_entity = {'text': 'Test Entity', 'confidence': 1.5}  # > 1.0
        low_entity = {'text': 'Test Entity', 'confidence': -0.1}  # < 0.0
        
        assert extractor._calculate_entity_confidence(high_entity) <= 1.0
        assert extractor._calculate_entity_confidence(low_entity) >= 0.0


@pytest.mark.unit
class TestEntityResolution:
    """Test entity resolution functionality."""
    
    def test_resolve_entities_simple(self, test_db, test_entity_data):
        """Test simple entity resolution for duplicates."""
        from scripts.entity_service import resolve_entities_simple
        
        # Add duplicate entity with slight variation
        duplicate_entities = test_entity_data + [
            {
                'text': 'John Doe',  # Exact duplicate
                'type': 'PERSON',
                'start_offset': 200,
                'end_offset': 208,
                'confidence': 0.90
            },
            {
                'text': 'john doe',  # Case variation
                'type': 'PERSON', 
                'start_offset': 250,
                'end_offset': 258,
                'confidence': 0.88
            }
        ]
        
        resolved = resolve_entities_simple(duplicate_entities)
        
        # Should resolve duplicates
        assert len(resolved) < len(duplicate_entities)
        
        # Should keep highest confidence version
        john_doe_entities = [e for e in resolved if 'john' in e['text'].lower()]
        assert len(john_doe_entities) == 1
        assert john_doe_entities[0]['confidence'] == 0.95  # Highest confidence
    
    def test_resolve_entities_different_types(self, test_db):
        """Test that entities with same text but different types are not merged."""
        from scripts.entity_service import resolve_entities_simple
        
        entities = [
            {
                'text': 'Apple',
                'type': 'ORG',
                'start_offset': 0,
                'end_offset': 5,
                'confidence': 0.95
            },
            {
                'text': 'Apple',
                'type': 'PRODUCT', 
                'start_offset': 50,
                'end_offset': 55,
                'confidence': 0.90
            }
        ]
        
        resolved = resolve_entities_simple(entities)
        
        # Should keep both as they have different types
        assert len(resolved) == 2
    
    def test_resolve_entities_empty_list(self, test_db):
        """Test entity resolution with empty input."""
        from scripts.entity_service import resolve_entities_simple
        
        resolved = resolve_entities_simple([])
        assert resolved == []
    
    def test_resolve_entities_none_text(self, test_db):
        """Test entity resolution with None text values."""
        from scripts.entity_service import resolve_entities_simple
        
        entities = [
            {
                'text': None,
                'type': 'PERSON',
                'start_offset': 0,
                'end_offset': 5,
                'confidence': 0.95
            },
            {
                'text': 'Valid Entity',
                'type': 'PERSON',
                'start_offset': 10,
                'end_offset': 22,
                'confidence': 0.90
            }
        ]
        
        resolved = resolve_entities_simple(entities)
        
        # Should skip None text entities
        assert len(resolved) == 1
        assert resolved[0]['text'] == 'Valid Entity'


@pytest.mark.unit
class TestEntityValidation:
    """Test entity validation and filtering."""
    
    def test_filter_low_confidence_entities(self, test_db, test_entity_data):
        """Test filtering of low confidence entities."""
        extractor = EntityExtractor(test_db)
        
        # Add low confidence entity
        low_conf_entities = test_entity_data + [
            {
                'text': 'Uncertain Entity',
                'type': 'MISC',
                'start_offset': 300,
                'end_offset': 316,
                'confidence': 0.3  # Below threshold
            }
        ]
        
        filtered = extractor._filter_low_confidence_entities(
            low_conf_entities, threshold=0.5
        )
        
        # Should remove low confidence entity
        assert len(filtered) == len(test_entity_data)
        assert all(e['confidence'] >= 0.5 for e in filtered)
    
    def test_remove_overlapping_entities(self, test_db):
        """Test removal of overlapping entities."""
        extractor = EntityExtractor(test_db)
        
        overlapping_entities = [
            {
                'text': 'John',
                'type': 'PERSON',
                'start_offset': 0,
                'end_offset': 4,
                'confidence': 0.85
            },
            {
                'text': 'John Doe',  # Overlaps with above
                'type': 'PERSON',
                'start_offset': 0,
                'end_offset': 8,
                'confidence': 0.95
            },
            {
                'text': 'Different Entity',
                'type': 'ORG',
                'start_offset': 20,
                'end_offset': 36,
                'confidence': 0.90
            }
        ]
        
        filtered = extractor._remove_overlapping_entities(overlapping_entities)
        
        # Should keep higher confidence overlapping entity
        assert len(filtered) == 2
        person_entities = [e for e in filtered if e['type'] == 'PERSON']
        assert len(person_entities) == 1
        assert person_entities[0]['text'] == 'John Doe'  # Higher confidence
    
    def test_validate_entity_offsets(self, test_db, sample_text):
        """Test entity offset validation against source text."""
        extractor = EntityExtractor(test_db)
        
        valid_entity = {
            'text': 'John Doe',
            'type': 'PERSON',
            'start_offset': sample_text.find('John Doe'),
            'end_offset': sample_text.find('John Doe') + len('John Doe'),
            'confidence': 0.95
        }
        
        invalid_entity = {
            'text': 'Nonexistent',
            'type': 'PERSON', 
            'start_offset': 0,
            'end_offset': 11,
            'confidence': 0.95
        }
        
        assert extractor._validate_entity_offsets(valid_entity, sample_text) is True
        assert extractor._validate_entity_offsets(invalid_entity, sample_text) is False