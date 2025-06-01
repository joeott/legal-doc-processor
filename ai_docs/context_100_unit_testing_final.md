# Phase 1 Comprehensive Unit Testing Guide - Final Version with Celery

## Executive Summary

This guide provides a complete testing strategy for Phase 1 (cloud-only) implementation of the legal document processing pipeline with Celery integration. Phase 1 utilizes AWS Textract for OCR and OpenAI GPT-4 for entity extraction, with Redis caching, Celery for distributed task processing, and Supabase for data persistence.

**Current Status**: 41% coverage achieved, targeting 80%+

## Testing Architecture

### Test Organization
```
tests/
├── unit/                    # Component-specific tests
├── integration/             # Cross-component tests  
├── e2e/                     # End-to-end pipeline tests
├── fixtures/                # Test data and mocks
└── conftest.py             # Shared test configuration
```

## Critical Test Files Created/Updated

### 1. Celery Task Tests
- `test_celery_tasks.py` - Core Celery task testing ✓
- `test_queue_processor.py` - Updated with Celery integration ✓
- `test_redis_utils.py` - Redis caching and task state management ✓
- `test_supabase_utils.py` - Database operations with Celery support ✓

### 2. Infrastructure Tests
- `test_s3_storage.py` - S3 document storage operations ✓
- `test_textract_utils.py` - AWS Textract integration ✓
- `test_ocr_extraction.py` - OCR extraction with multiple backends ✓
- `test_entity_extraction.py` - Entity extraction with OpenAI ✓

### 3. Pipeline Tests
- `test_main_pipeline.py` - Main orchestration logic
- `test_chunking_utils.py` - Document chunking ✓
- `test_text_processing.py` - Text cleaning and processing ✓
- `test_relationship_builder.py` - Graph relationship building ✓

## Coverage Analysis

### Current Coverage by Module

| Module | Coverage | Target | Status |
|--------|----------|--------|--------|
| celery_app.py | 88% | 90% | ✓ |
| celery_tasks/graph_tasks.py | 78% | 85% | Needs work |
| celery_tasks/text_tasks.py | 59% | 85% | Needs work |
| celery_tasks/ocr_tasks.py | 48% | 85% | Needs work |
| celery_tasks/entity_tasks.py | 17% | 85% | Needs work |
| queue_processor.py | 61% | 85% | Needs work |
| redis_utils.py | 60% | 90% | Needs work |
| s3_storage.py | 93% | 90% | ✓ |
| textract_utils.py | 12% | 80% | Needs work |
| ocr_extraction.py | 47% | 80% | Needs work |
| entity_extraction.py | 71% | 85% | Needs work |
| supabase_utils.py | 11% | 85% | Critical |
| main_pipeline.py | 23% | 80% | Critical |
| **TOTAL** | **41%** | **80%** | In Progress |

### Priority Modules for Testing

1. **supabase_utils.py** (11%) - Database operations are critical
2. **main_pipeline.py** (23%) - Core orchestration logic
3. **textract_utils.py** (12%) - OCR processing foundation
4. **celery_tasks/entity_tasks.py** (17%) - Entity extraction pipeline

## Test Execution Strategy

### Phase 1: Foundation Tests (Current)
```bash
# Run existing tests
pytest tests/unit/ -v

# Check coverage
pytest --cov=scripts --cov-report=term-missing tests/unit/
```

### Phase 2: Critical Path Tests
```bash
# Test database operations
pytest tests/unit/test_supabase_utils.py -v

# Test main pipeline
pytest tests/unit/test_main_pipeline.py -v

# Test Celery tasks
pytest tests/unit/test_celery_tasks.py -v
```

### Phase 3: Integration Tests
```bash
# Start Redis
docker run -d -p 6379:6379 redis:alpine

# Start Celery workers
celery -A scripts.celery_app worker --loglevel=info &

# Run integration tests
pytest tests/integration/ -v
```

## Key Test Patterns Implemented

### 1. Celery Task Mocking
```python
@patch('scripts.celery_tasks.ocr_tasks.process_ocr.delay')
def test_celery_task_enqueue(mock_task):
    mock_task.return_value.id = "celery-task-123"
    # Test task enqueueing
```

### 2. Redis Singleton Testing
```python
def test_redis_singleton():
    manager1 = get_redis_manager()
    manager2 = get_redis_manager()
    assert manager1 is manager2
```

### 3. Database Operation Mocking
```python
@pytest.fixture
def mock_db_manager():
    with patch('scripts.supabase_utils.SupabaseManager') as mock:
        instance = mock.return_value
        instance.create_document_entry.return_value = (123, 'uuid-123')
        yield instance
```

### 4. AWS Service Mocking
```python
@patch('boto3.client')
def test_textract_job(mock_boto):
    mock_client = Mock()
    mock_boto.return_value = mock_client
    # Test Textract operations
```

## Next Steps to Reach 80% Coverage

### 1. Complete Supabase Utils Tests
- Test all CRUD operations
- Test transaction handling
- Test error scenarios
- Test connection pooling

### 2. Complete Main Pipeline Tests
- Test stage validation
- Test error recovery
- Test retry mechanisms
- Test status tracking

### 3. Complete Celery Task Tests
- Test task chaining
- Test error propagation
- Test retry logic
- Test result backend

### 4. Add Integration Tests
- Test full document flow
- Test worker failures
- Test Redis failures
- Test database failures

## Test Maintenance Guidelines

### 1. Test Naming Convention
- `test_<module>_<function>_<scenario>`
- Example: `test_ocr_extraction_pdf_success`

### 2. Mock Management
- Use fixtures for reusable mocks
- Mock external dependencies only
- Test actual logic, not mocks

### 3. Coverage Standards
- New code must have 80%+ coverage
- Critical paths need 90%+ coverage
- Integration tests for all workflows

## CI/CD Integration

### GitHub Actions Configuration
```yaml
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    services:
      redis:
        image: redis:7-alpine
        ports: [6379:6379]
    steps:
      - uses: actions/checkout@v3
      - name: Run tests
        run: |
          pytest --cov=scripts --cov-report=xml
      - name: Upload coverage
        uses: codecov/codecov-action@v3
```

## Monitoring Test Health

### 1. Coverage Tracking
```bash
# Generate HTML report
pytest --cov=scripts --cov-report=html

# View report
open htmlcov/index.html
```

### 2. Test Performance
```bash
# Run with timing
pytest --durations=10
```

### 3. Flaky Test Detection
```bash
# Run tests multiple times
pytest --count=3
```

## Summary

The testing framework has been successfully enhanced with Celery support. Current coverage stands at 41% with clear paths to reach the 80% target. Priority should be given to testing database operations (supabase_utils.py) and main pipeline orchestration, as these are critical components with low coverage.

The modular test structure allows for incremental improvements while maintaining test quality and execution speed.