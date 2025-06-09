"""
Pytest configuration and fixtures for legal document processor tests.
"""
import pytest
import os
import tempfile
from unittest.mock import Mock, patch
from typing import Generator, Optional

# Set test environment variables
os.environ['SKIP_CONFORMANCE_CHECK'] = 'true'
os.environ['USE_MINIMAL_MODELS'] = 'true'

@pytest.fixture(scope="session")
def test_db():
    """Test database connection with conformance validation disabled."""
    from scripts.db import DatabaseManager
    return DatabaseManager(validate_conformance=False)

@pytest.fixture(scope="session") 
def test_redis():
    """Test Redis connection."""
    from scripts.cache import get_redis_manager
    return get_redis_manager()

@pytest.fixture
def sample_document_uuid():
    """Standard test document UUID."""
    return "test-doc-12345678-1234-1234-1234-123456789abc"

@pytest.fixture
def sample_project_uuid():
    """Standard test project UUID.""" 
    return "test-proj-12345678-1234-1234-1234-123456789abc"

@pytest.fixture
def sample_text():
    """Sample extracted text for testing."""
    return """
    This is a sample legal document for testing purposes.
    
    PARTIES
    Party A: John Doe
    Party B: Jane Smith
    
    TERMS
    The agreement shall commence on January 1, 2024.
    Payment terms are Net 30 days.
    
    SIGNATURES
    John Doe: _________________
    Jane Smith: _______________
    """

@pytest.fixture
def mock_s3_client():
    """Mock S3 client for testing."""
    with patch('boto3.client') as mock_client:
        mock_s3 = Mock()
        mock_client.return_value = mock_s3
        
        # Mock common S3 operations
        mock_s3.head_object.return_value = {
            'ContentLength': 1000000,
            'ContentType': 'application/pdf'
        }
        mock_s3.download_file.return_value = None
        mock_s3.put_object.return_value = {'ETag': '"test-etag"'}
        
        yield mock_s3

@pytest.fixture
def mock_textract_client():
    """Mock Textract client for testing."""
    with patch('boto3.client') as mock_client:
        mock_textract = Mock()
        mock_client.return_value = mock_textract
        
        # Mock detect_document_text response
        mock_textract.detect_document_text.return_value = {
            'Blocks': [
                {
                    'BlockType': 'PAGE',
                    'Id': 'page-1',
                    'Confidence': 99.0
                },
                {
                    'BlockType': 'LINE',
                    'Id': 'line-1', 
                    'Text': 'Sample document text',
                    'Confidence': 95.0
                }
            ]
        }
        
        # Mock async job operations
        mock_textract.start_document_text_detection.return_value = {
            'JobId': 'test-job-12345'
        }
        
        mock_textract.get_document_text_detection.return_value = {
            'JobStatus': 'SUCCEEDED',
            'Blocks': [
                {
                    'BlockType': 'LINE',
                    'Text': 'Sample document text',
                    'Confidence': 95.0
                }
            ]
        }
        
        yield mock_textract

@pytest.fixture
def temp_pdf_file():
    """Create a temporary PDF file for testing."""
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
        # Write minimal PDF content
        tmp.write(b'%PDF-1.4\n%Test PDF\nendobj\n%%EOF')
        tmp.flush()
        yield tmp.name
    
    # Cleanup
    try:
        os.unlink(tmp.name)
    except:
        pass

@pytest.fixture
def mock_celery_task():
    """Mock Celery task for testing."""
    mock_task = Mock()
    mock_task.request.id = 'test-task-12345'
    mock_task.request.retries = 0
    mock_task.max_retries = 3
    return mock_task

@pytest.fixture
def test_entity_data():
    """Sample entity data for testing."""
    return [
        {
            'text': 'John Doe',
            'type': 'PERSON',
            'start_offset': 50,
            'end_offset': 58,
            'confidence': 0.95
        },
        {
            'text': 'Jane Smith', 
            'type': 'PERSON',
            'start_offset': 70,
            'end_offset': 80,
            'confidence': 0.92
        },
        {
            'text': 'January 1, 2024',
            'type': 'DATE',
            'start_offset': 120,
            'end_offset': 135,
            'confidence': 0.98
        }
    ]

@pytest.fixture(autouse=True)
def clean_test_environment():
    """Ensure clean test environment for each test."""
    # Setup
    original_env = dict(os.environ)
    
    # Ensure test configuration
    os.environ.update({
        'SKIP_CONFORMANCE_CHECK': 'true',
        'USE_MINIMAL_MODELS': 'true',
        'ENABLE_SCANNED_PDF_DETECTION': 'false',  # Disable for most tests
    })
    
    yield
    
    # Cleanup - restore original environment
    os.environ.clear()
    os.environ.update(original_env)

# Test markers
pytest_plugins = []

def pytest_configure(config):
    """Configure custom pytest markers."""
    config.addinivalue_line(
        "markers", "unit: Unit tests for isolated components"
    )
    config.addinivalue_line(
        "markers", "integration: Integration tests for component interactions"  
    )
    config.addinivalue_line(
        "markers", "e2e: End-to-end tests for full pipeline"
    )
    config.addinivalue_line(
        "markers", "slow: Slow running tests"
    )
    config.addinivalue_line(
        "markers", "requires_aws: Tests requiring AWS credentials"
    )
    config.addinivalue_line(
        "markers", "requires_redis: Tests requiring Redis connection"
    )
    config.addinivalue_line(
        "markers", "requires_db: Tests requiring database connection"
    )