# Integration Tests

This directory contains integration tests that verify multi-component interactions.

## Test Files

- `test_cache_debug.py` - Redis cache debugging tests
- `test_document_processing.py` - Full document processing integration tests  
- `test_fixes_simple.py` - Simple fix verification tests
- `test_fixes_verification.py` - Comprehensive fix verification
- `test_production_e2e.py` - Production end-to-end tests
- `test_redis_acceleration.py` - Redis acceleration performance tests
- `test_redis_multi_db.py` - Redis multi-database tests
- `test_redis_simple.py` - Basic Redis connectivity tests
- `verify_fixes.py` - Fix verification utility

## Running Tests

```bash
# Run all integration tests
pytest tests/integration/

# Run specific test
pytest tests/integration/test_production_e2e.py
```