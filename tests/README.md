# Legal Document Processor - Test Suite

## Overview

This directory contains the organized test suite for the legal document processing system. The tests are structured to provide comprehensive coverage while maintaining clear separation of concerns.

## Test Structure

```
tests/
├── conftest.py              # Pytest configuration and fixtures
├── unit/                    # Unit tests (isolated components)
├── integration/             # Integration tests (component interactions)
├── e2e/                     # End-to-end tests (full pipeline)
├── fixtures/                # Test data and sample documents
└── utils/                   # Test utilities and helpers
```

## Test Categories

### Unit Tests (`tests/unit/`)
- **Purpose**: Test individual components in isolation
- **Scope**: Single class or function testing
- **Dependencies**: Mocked external services
- **Speed**: Fast (< 1 second per test)

**Current Tests**:
- `test_textract_utils.py` - OCR and document processing utilities
- `test_entity_service.py` - Entity extraction and resolution
- `test_chunking_utils.py` - Text segmentation (TODO)
- `test_cache.py` - Redis caching operations (TODO)
- `test_db.py` - Database operations (existing)

### Integration Tests (`tests/integration/`)
- **Purpose**: Test component interactions
- **Scope**: Multiple components working together
- **Dependencies**: May use real database/Redis, mock AWS
- **Speed**: Medium (1-10 seconds per test)

**Current Tests**:
- `test_ocr_pipeline.py` - OCR processing with database integration
- `test_entity_pipeline.py` - Entity extraction with database (TODO)
- `test_celery_tasks.py` - Task queue integration (TODO)

### End-to-End Tests (`tests/e2e/`)
- **Purpose**: Test complete workflows
- **Scope**: Full pipeline scenarios
- **Dependencies**: May require AWS credentials for some tests
- **Speed**: Slow (10+ seconds per test)

**Current Tests**:
- `test_scanned_pdf.py` - Complete scanned PDF processing pipeline
- `test_document_processing.py` - Full document pipeline (TODO)
- `test_production_simulation.py` - Production scenarios (TODO)

## Running Tests

### Prerequisites

1. **Environment Setup**:
   ```bash
   source load_env.sh  # Load environment variables
   ```

2. **Dependencies**:
   ```bash
   pip install pytest pytest-mock pytest-cov
   ```

### Basic Execution

```bash
# Run all tests
pytest

# Run specific category
pytest tests/unit/           # Unit tests only
pytest tests/integration/    # Integration tests only
pytest tests/e2e/           # E2E tests only

# Run specific test file
pytest tests/unit/test_textract_utils.py

# Run specific test
pytest tests/unit/test_textract_utils.py::TestTextractProcessor::test_init
```

### Advanced Options

```bash
# Verbose output
pytest -v

# Stop on first failure
pytest -x

# Run with coverage
pytest --cov=scripts --cov-report=html

# Run only fast tests (skip slow ones)
pytest -m "not slow"

# Run tests requiring specific services
pytest -m "requires_aws"     # AWS credentials needed
pytest -m "requires_redis"   # Redis connection needed
pytest -m "requires_db"      # Database connection needed
```

### Test Markers

Tests are marked with categories for selective execution:

- `@pytest.mark.unit` - Unit tests
- `@pytest.mark.integration` - Integration tests  
- `@pytest.mark.e2e` - End-to-end tests
- `@pytest.mark.slow` - Slow running tests
- `@pytest.mark.requires_aws` - Requires AWS credentials
- `@pytest.mark.requires_redis` - Requires Redis connection
- `@pytest.mark.requires_db` - Requires database connection

## Test Configuration

### Environment Variables

Tests automatically set these environment variables:
- `SKIP_CONFORMANCE_CHECK=true` - Disable schema conformance for testing
- `USE_MINIMAL_MODELS=true` - Use minimal models to reduce complexity
- `ENABLE_SCANNED_PDF_DETECTION=false` - Disable for most tests (enabled for specific tests)

### Fixtures

Common fixtures available in all tests:

- `test_db` - Database manager with conformance disabled
- `test_redis` - Redis manager for caching tests
- `sample_document_uuid` - Standard test document UUID
- `sample_project_uuid` - Standard test project UUID
- `sample_text` - Sample legal document text
- `mock_s3_client` - Mock S3 client for AWS operations
- `mock_textract_client` - Mock Textract client
- `temp_pdf_file` - Temporary PDF file for testing
- `test_entity_data` - Sample entity extraction data

### Test Data

Test fixtures are stored in `tests/fixtures/`:
- `sample_documents/` - Sample PDF files for testing
- `test_data.json` - Structured test data

## Writing New Tests

### Guidelines

1. **Location**: Place tests in appropriate directory (`unit/`, `integration/`, `e2e/`)
2. **Naming**: Use `test_*.py` naming convention
3. **Markers**: Add appropriate pytest markers
4. **Docstrings**: Include clear test descriptions
5. **Assertions**: Use descriptive assertion messages
6. **Cleanup**: Ensure tests clean up after themselves

### Example Test Structure

```python
"""
Unit tests for new_module.py - Description of module functionality.
"""
import pytest
from unittest.mock import Mock, patch

from scripts.new_module import NewClass


@pytest.mark.unit
class TestNewClass:
    """Test the NewClass functionality."""
    
    def test_basic_functionality(self, test_db):
        """Test basic NewClass functionality."""
        instance = NewClass(test_db)
        result = instance.do_something()
        
        assert result is not None
        assert isinstance(result, dict)
    
    @patch('scripts.new_module.external_service')
    def test_with_mocked_service(self, mock_service, test_db):
        """Test NewClass with mocked external service."""
        mock_service.return_value = {'status': 'success'}
        
        instance = NewClass(test_db)
        result = instance.call_external_service()
        
        assert result['status'] == 'success'
        mock_service.assert_called_once()
```

### Testing Best Practices

1. **Isolation**: Each test should be independent
2. **Mocking**: Mock external services (AWS, OpenAI, etc.)
3. **Coverage**: Aim for high test coverage of critical paths
4. **Performance**: Keep unit tests fast, mark slow tests appropriately
5. **Reliability**: Tests should be deterministic and not flaky
6. **Documentation**: Clear test names and docstrings

## Maintenance

### Adding New Tests

1. **For new functionality**: Add unit tests first, then integration if needed
2. **For bug fixes**: Add regression tests to prevent future issues
3. **For critical workflows**: Add E2E tests for important user journeys

### Updating Tests

1. **When changing APIs**: Update corresponding test mocks
2. **When adding dependencies**: Update test fixtures and requirements
3. **When deprecating features**: Remove or update obsolete tests

### Test Hygiene

- **Review regularly**: Remove obsolete or duplicate tests
- **Maintain fixtures**: Keep test data current and relevant
- **Monitor performance**: Watch for tests becoming too slow
- **Check coverage**: Ensure new code has appropriate test coverage

## Troubleshooting

### Common Issues

1. **Import Errors**: Ensure `PYTHONPATH` includes project root
2. **Database Errors**: Check database connection and permissions
3. **AWS Errors**: Verify AWS credentials for integration tests
4. **Redis Errors**: Ensure Redis is available for caching tests

### Debugging

```bash
# Run with debugging output
pytest -s -v --tb=long

# Run single test with debugging
pytest -s tests/unit/test_module.py::test_function

# Use pdb for interactive debugging
pytest --pdb
```

## Migration from Old Tests

This test suite replaces 107+ scattered test files that were archived during cleanup. If you need functionality from archived tests:

1. **Check existing tests**: New tests may already cover the functionality
2. **Review archive**: Check `archived_codebase/legacy_tests/` for specific logic
3. **Extract carefully**: Copy specific test logic, don't restore wholesale
4. **Maintain organization**: Add to appropriate test category

## Contact

For questions about testing:
- Review this documentation
- Check test examples in each category
- Refer to cleanup documentation in `ai_docs/context_396_*`