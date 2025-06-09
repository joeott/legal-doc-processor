"""
Test utilities and helper functions.
"""
import tempfile
import os
import json
from typing import Dict, Any, List
from unittest.mock import Mock


def create_mock_document(
    document_uuid: str = "test-doc-123",
    project_uuid: str = "test-proj-456", 
    file_name: str = "test.pdf",
    status: str = "pending"
) -> Mock:
    """Create a mock document object for testing."""
    mock_doc = Mock()
    mock_doc.id = 123
    mock_doc.document_uuid = document_uuid
    mock_doc.project_uuid = project_uuid
    mock_doc.original_file_name = file_name
    mock_doc.status = status
    mock_doc.created_at = "2024-01-01T00:00:00Z"
    return mock_doc


def create_mock_textract_response(
    text_lines: List[str],
    confidence: float = 95.0,
    page_count: int = 1
) -> Dict[str, Any]:
    """Create a mock Textract API response."""
    blocks = []
    
    # Add PAGE block
    blocks.append({
        'BlockType': 'PAGE',
        'Id': 'page-1',
        'Confidence': confidence
    })
    
    # Add LINE blocks
    for i, line_text in enumerate(text_lines):
        blocks.append({
            'BlockType': 'LINE',
            'Id': f'line-{i+1}',
            'Text': line_text,
            'Confidence': confidence,
            'Page': 1
        })
        
        # Add WORD blocks for each line
        words = line_text.split()
        for j, word in enumerate(words):
            blocks.append({
                'BlockType': 'WORD',
                'Id': f'word-{i+1}-{j+1}',
                'Text': word,
                'Confidence': confidence,
                'Page': 1
            })
    
    return {
        'Blocks': blocks,
        'DocumentMetadata': {
            'Pages': page_count
        }
    }


def create_test_pdf_file(content: bytes = None) -> str:
    """Create a temporary PDF file for testing."""
    if content is None:
        content = b'%PDF-1.4\n%Test PDF content\nendobj\n%%EOF'
    
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
        tmp.write(content)
        tmp.flush()
        return tmp.name


def cleanup_test_file(file_path: str) -> None:
    """Clean up a test file."""
    try:
        if os.path.exists(file_path):
            os.unlink(file_path)
    except Exception:
        pass  # Ignore cleanup errors


def assert_valid_uuid(uuid_str: str) -> None:
    """Assert that a string is a valid UUID."""
    import uuid
    try:
        uuid.UUID(uuid_str)
    except ValueError:
        raise AssertionError(f"Invalid UUID: {uuid_str}")


def assert_valid_entity(entity: Dict[str, Any]) -> None:
    """Assert that an entity has valid structure."""
    required_fields = ['text', 'type', 'start_offset', 'end_offset', 'confidence']
    
    for field in required_fields:
        assert field in entity, f"Missing required field: {field}"
    
    assert isinstance(entity['text'], str), "Entity text must be string"
    assert isinstance(entity['type'], str), "Entity type must be string"
    assert isinstance(entity['start_offset'], int), "start_offset must be int"
    assert isinstance(entity['end_offset'], int), "end_offset must be int"
    assert isinstance(entity['confidence'], (int, float)), "confidence must be numeric"
    
    assert 0 <= entity['confidence'] <= 1, "confidence must be between 0 and 1"
    assert entity['start_offset'] <= entity['end_offset'], "Invalid offset range"


def create_mock_celery_task(
    task_id: str = "test-task-123",
    retries: int = 0,
    max_retries: int = 3
) -> Mock:
    """Create a mock Celery task for testing."""
    mock_task = Mock()
    mock_task.request.id = task_id
    mock_task.request.retries = retries
    mock_task.max_retries = max_retries
    mock_task.retry = Mock()
    return mock_task


def create_mock_redis_manager(available: bool = True) -> Mock:
    """Create a mock Redis manager for testing."""
    mock_redis = Mock()
    mock_redis.is_available.return_value = available
    
    if available:
        mock_redis.get_cached.return_value = None
        mock_redis.set_cached.return_value = True
        mock_redis.delete.return_value = True
        mock_redis.store_dict.return_value = True
        mock_redis.get_dict.return_value = {}
    else:
        mock_redis.get_cached.side_effect = Exception("Redis not available")
        mock_redis.set_cached.side_effect = Exception("Redis not available")
    
    return mock_redis


def load_test_fixture(filename: str) -> Dict[str, Any]:
    """Load a test fixture from JSON file."""
    fixtures_dir = os.path.join(os.path.dirname(__file__), '..', 'fixtures')
    file_path = os.path.join(fixtures_dir, filename)
    
    try:
        with open(file_path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"Test fixture not found: {filename}")


def compare_entities(entity1: Dict[str, Any], entity2: Dict[str, Any]) -> bool:
    """Compare two entities for similarity (fuzzy matching)."""
    # Normalize text for comparison
    text1 = entity1.get('text', '').lower().strip()
    text2 = entity2.get('text', '').lower().strip()
    
    # Same text and type
    if text1 == text2 and entity1.get('type') == entity2.get('type'):
        return True
    
    # Allow for minor text variations
    if entity1.get('type') == entity2.get('type'):
        # Check if one text is contained in the other (e.g., "John" vs "John Doe")
        if text1 in text2 or text2 in text1:
            return True
    
    return False


def filter_test_warnings():
    """Filter common test warnings."""
    import warnings
    
    # Filter Pydantic warnings
    warnings.filterwarnings("ignore", category=DeprecationWarning, module="pydantic")
    warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")
    
    # Filter SQLAlchemy warnings
    warnings.filterwarnings("ignore", message=".*has no attribute.*")


class MockAWSService:
    """Mock AWS service for testing."""
    
    def __init__(self, service_name: str):
        self.service_name = service_name
        self.call_history = []
    
    def __getattr__(self, name):
        def mock_method(*args, **kwargs):
            self.call_history.append((name, args, kwargs))
            return self._get_mock_response(name, *args, **kwargs)
        return mock_method
    
    def _get_mock_response(self, method_name: str, *args, **kwargs):
        """Get appropriate mock response based on method."""
        if self.service_name == 'textract':
            return self._textract_response(method_name, *args, **kwargs)
        elif self.service_name == 's3':
            return self._s3_response(method_name, *args, **kwargs)
        return {}
    
    def _textract_response(self, method: str, *args, **kwargs):
        """Mock Textract responses."""
        if method == 'detect_document_text':
            return create_mock_textract_response(['Sample text line'])
        elif method == 'start_document_text_detection':
            return {'JobId': 'mock-job-12345'}
        elif method == 'get_document_text_detection':
            return {
                'JobStatus': 'SUCCEEDED',
                'Blocks': create_mock_textract_response(['Sample text'])['Blocks']
            }
        return {}
    
    def _s3_response(self, method: str, *args, **kwargs):
        """Mock S3 responses."""
        if method == 'head_object':
            return {'ContentLength': 1000000, 'ContentType': 'application/pdf'}
        elif method == 'put_object':
            return {'ETag': '"mock-etag"'}
        elif method == 'download_file':
            return None
        return {}