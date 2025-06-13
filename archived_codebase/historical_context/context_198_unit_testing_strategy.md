# Context 198: Comprehensive Unit Testing Strategy for Consolidated Codebase

**Date**: 2025-01-29
**Status**: Strategy Document
**Focus**: Unit testing strategy for consolidated 5-module architecture

## 1. Executive Summary

The codebase has been consolidated from ~120 scripts to 25, with 5 core modules requiring comprehensive test coverage. This strategy outlines a prioritized approach to achieving 80%+ test coverage while ensuring critical paths are thoroughly tested.

### Core Modules to Test
1. **cache.py** - Redis operations, caching logic, TTL management
2. **database.py** - Supabase CRUD operations, Pydantic model handling
3. **entity_service.py** - Entity extraction and resolution
4. **graph_service.py** - Relationship building for Neo4j
5. **pdf_tasks.py** - All Celery task definitions and orchestration

## 2. Current Test Coverage Analysis

### Existing Test Structure
```
tests/
├── unit/               # 24 test files (many outdated)
├── integration/        # 5 test files (partial coverage)
├── e2e/               # 2 test files (minimal)
├── fixtures/          # Good mock data foundation
└── mocks/            # Basic mocking utilities
```

### Coverage Gaps Identified
1. **No tests for new consolidated modules** (cache.py, database.py, etc.)
2. **Outdated tests** referencing old module names (redis_utils, supabase_utils)
3. **Limited mocking** for external services (Redis Cloud, Supabase, OpenAI)
4. **Missing async/Celery task testing**
5. **No performance/load testing**
6. **Inadequate error handling coverage**

## 3. Test Categories and Priorities

### Priority 1: Critical Path Testing
Focus on the core document processing pipeline:
```
Document Upload → OCR → Chunking → Entity Extraction → 
Entity Resolution → Relationship Building → Graph Storage
```

### Priority 2: Module-Level Unit Tests
Each core module gets comprehensive unit test coverage:

#### cache.py Testing Requirements
- Redis connection handling
- Cache key generation
- TTL management
- Lock mechanisms
- Decorator functionality
- Error recovery
- Connection pooling

#### database.py Testing Requirements
- Supabase client initialization
- CRUD operations for each model
- Pydantic validation
- Transaction handling
- Error states
- Migration utilities
- Batch operations

#### entity_service.py Testing Requirements
- OpenAI API interactions
- Entity extraction logic
- Entity resolution algorithms
- Confidence scoring
- Batch processing
- Error handling

#### graph_service.py Testing Requirements
- Relationship extraction
- Graph node creation
- Edge building logic
- Neo4j integration
- Data transformation

#### pdf_tasks.py Testing Requirements
- Celery task execution
- Task chaining
- Error propagation
- Retry logic
- State management
- Result caching

### Priority 3: Integration Tests
- Cache + Database interactions
- Entity extraction → Resolution flow
- Complete pipeline execution
- External service integration

### Priority 4: End-to-End Tests
- Full document processing
- Multiple document types
- Error scenarios
- Performance benchmarks

## 4. Test Structure Design

### Proposed Directory Structure
```
tests/
├── unit/
│   ├── test_cache.py
│   ├── test_database.py
│   ├── test_entity_service.py
│   ├── test_graph_service.py
│   └── test_pdf_tasks.py
├── integration/
│   ├── test_cache_database_integration.py
│   ├── test_entity_pipeline.py
│   ├── test_document_flow.py
│   └── test_celery_chains.py
├── e2e/
│   ├── test_complete_pipeline.py
│   ├── test_error_recovery.py
│   └── test_performance.py
├── fixtures/
│   ├── documents/
│   ├── mock_responses/
│   └── test_data.py
├── mocks/
│   ├── external_services.py
│   ├── celery_mocks.py
│   └── model_factories.py
└── conftest.py
```

## 5. Mock Strategy for External Dependencies

### Redis Mocking
```python
@pytest.fixture
def mock_redis_client():
    """Mock Redis client with in-memory storage"""
    return MockRedis()

@pytest.fixture
def mock_cache_manager(mock_redis_client):
    """Mock the entire cache module"""
    with patch('scripts.cache.RedisManager._get_client', return_value=mock_redis_client):
        yield CacheManager()
```

### Supabase Mocking
```python
@pytest.fixture
def mock_supabase_client():
    """Mock Supabase client with response builders"""
    client = MagicMock()
    client.table.return_value = TableMockBuilder()
    return client
```

### OpenAI Mocking
```python
@pytest.fixture
def mock_openai_responses():
    """Predefined OpenAI API responses"""
    return {
        'entity_extraction': create_entity_response(),
        'structured_extraction': create_structured_response(),
        'embeddings': create_embedding_response()
    }
```

### AWS/S3 Mocking
```python
@pytest.fixture
def mock_s3_client():
    """Mock S3 operations"""
    with patch('boto3.client') as mock:
        yield create_s3_mock()
```

### Celery Mocking
```python
@pytest.fixture
def mock_celery_app():
    """Mock Celery app for synchronous testing"""
    app = MagicMock()
    app.task = lambda **kwargs: lambda f: MockTask(f)
    return app
```

## 6. Testing Tools and Frameworks

### Core Testing Stack
- **pytest** - Primary test framework
- **pytest-asyncio** - Async function testing
- **pytest-cov** - Coverage reporting
- **pytest-mock** - Enhanced mocking utilities
- **pytest-xdist** - Parallel test execution

### Mocking Libraries
- **unittest.mock** - Standard mocking
- **fakeredis** - In-memory Redis for testing
- **moto** - AWS service mocking
- **responses** - HTTP request mocking

### Additional Tools
- **factory_boy** - Test data generation
- **hypothesis** - Property-based testing
- **pytest-benchmark** - Performance testing
- **tox** - Test environment management

## 7. Implementation Roadmap

### Phase 1: Foundation (Week 1)
1. Update conftest.py with new fixtures
2. Create mock builders for all external services
3. Establish test data factories
4. Set up coverage reporting

### Phase 2: Unit Tests (Week 2-3)
1. **Day 1-2**: test_cache.py
   - Connection management
   - Key operations
   - Decorators
   - Error handling

2. **Day 3-4**: test_database.py
   - CRUD operations
   - Model validation
   - Transaction handling
   - Migration utilities

3. **Day 5-6**: test_entity_service.py
   - Extraction logic
   - Resolution algorithms
   - API mocking
   - Batch processing

4. **Day 7-8**: test_graph_service.py
   - Relationship building
   - Graph operations
   - Data transformation

5. **Day 9-10**: test_pdf_tasks.py
   - Task execution
   - Chaining logic
   - Error handling
   - State management

### Phase 3: Integration Tests (Week 4)
1. Cache-Database integration
2. Entity pipeline flow
3. Document processing chains
4. Error propagation

### Phase 4: E2E Tests (Week 5)
1. Complete pipeline tests
2. Performance benchmarks
3. Error recovery scenarios
4. Load testing

## 8. Test Implementation Examples

### Example: Testing Cache Module
```python
# test_cache.py
import pytest
from unittest.mock import patch, MagicMock
from scripts.cache import CacheManager, CacheKeys, redis_cache

class TestCacheManager:
    @pytest.fixture
    def cache_manager(self, mock_redis_client):
        with patch('scripts.cache.redis.Redis', return_value=mock_redis_client):
            return CacheManager()
    
    def test_set_and_get(self, cache_manager):
        """Test basic cache operations"""
        cache_manager.set('test_key', 'test_value', ttl=60)
        assert cache_manager.get('test_key') == 'test_value'
    
    def test_cache_decorator(self, cache_manager):
        """Test redis_cache decorator"""
        call_count = 0
        
        @redis_cache(ttl=60)
        def expensive_function(x):
            nonlocal call_count
            call_count += 1
            return x * 2
        
        # First call should execute function
        result1 = expensive_function(5)
        assert result1 == 10
        assert call_count == 1
        
        # Second call should use cache
        result2 = expensive_function(5)
        assert result2 == 10
        assert call_count == 1  # No additional calls
```

### Example: Testing Database Module
```python
# test_database.py
import pytest
from unittest.mock import patch, MagicMock
from scripts.database import SupabaseManager, create_source_document

class TestSupabaseManager:
    @pytest.fixture
    def db_manager(self, mock_supabase_client):
        with patch('scripts.database.create_client', return_value=mock_supabase_client):
            return SupabaseManager()
    
    def test_create_source_document(self, db_manager):
        """Test document creation with Pydantic validation"""
        doc_data = {
            'filename': 'test.pdf',
            'file_path': '/path/to/test.pdf',
            'file_type': 'pdf',
            'project_id': 'proj-123'
        }
        
        result = db_manager.create_source_document(**doc_data)
        assert result.filename == 'test.pdf'
        assert result.processing_status == ProcessingStatus.PENDING
```

### Example: Testing Entity Service
```python
# test_entity_service.py
import pytest
from unittest.mock import patch, MagicMock
from scripts.entity_service import EntityExtractor, EntityResolver

class TestEntityExtractor:
    @pytest.fixture
    def extractor(self, mock_openai_client):
        with patch('scripts.entity_service.OpenAI', return_value=mock_openai_client):
            return EntityExtractor()
    
    def test_extract_entities(self, extractor, mock_openai_responses):
        """Test entity extraction from text"""
        text = "John Doe signed a contract with ACME Corp."
        
        entities = extractor.extract_entities(text)
        
        assert len(entities) == 2
        assert any(e.entity_value == "John Doe" for e in entities)
        assert any(e.entity_type == "ORGANIZATION" for e in entities)
```

## 9. Coverage Goals and Metrics

### Target Coverage
- **Overall**: 80% line coverage
- **Critical paths**: 95% coverage
- **Error handling**: 90% coverage
- **Edge cases**: 85% coverage

### Coverage by Module
- cache.py: 85%
- database.py: 90%
- entity_service.py: 85%
- graph_service.py: 80%
- pdf_tasks.py: 90%

### Metrics to Track
1. Line coverage
2. Branch coverage
3. Function coverage
4. Test execution time
5. Mock call counts
6. Flaky test rate

## 10. CI/CD Integration

### GitHub Actions Workflow
```yaml
name: Test Suite
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    services:
      redis:
        image: redis:alpine
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    
    steps:
    - uses: actions/checkout@v3
    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.11'
    
    - name: Install dependencies
      run: |
        pip install -r requirements.txt
        pip install -r tests/requirements-test.txt
    
    - name: Run tests with coverage
      run: |
        pytest tests/ --cov=scripts --cov-report=xml --cov-report=html
    
    - name: Upload coverage
      uses: codecov/codecov-action@v3
```

## 11. Best Practices and Guidelines

### Test Writing Guidelines
1. **Arrange-Act-Assert pattern** for all tests
2. **One assertion per test** when possible
3. **Descriptive test names** that explain the scenario
4. **Isolated tests** with no dependencies
5. **Fast tests** - mock external calls
6. **Deterministic tests** - no random values

### Mocking Best Practices
1. Mock at the boundaries (external services)
2. Use real objects when possible
3. Verify mock calls were made
4. Reset mocks between tests
5. Use context managers for patches

### Test Data Management
1. Use factories for complex objects
2. Minimal test data that exercises the path
3. Separate fixtures for different scenarios
4. Avoid hardcoded values
5. Clean up after tests

## 12. Next Steps

### Immediate Actions
1. **Create test_cache.py** with basic Redis operation tests
2. **Update conftest.py** with new module fixtures
3. **Implement mock builders** for external services
4. **Set up coverage reporting** in CI/CD

### Week 1 Goals
- Complete foundation setup
- Write tests for cache.py
- Achieve 50% coverage on cache module
- Document testing patterns

### Month 1 Goals
- Complete all unit tests
- Achieve 80% overall coverage
- Implement integration tests
- Set up automated testing in CI/CD

## Conclusion

This testing strategy provides a clear roadmap to achieve comprehensive test coverage for the consolidated codebase. By focusing on critical paths first and using effective mocking strategies, we can ensure the reliability and maintainability of the PDF processing pipeline while keeping tests fast and deterministic.

The modular structure of the consolidated codebase makes it easier to test each component in isolation, leading to more focused and maintainable tests. With proper implementation of this strategy, we'll have a robust test suite that catches bugs early and enables confident refactoring.