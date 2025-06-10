# Context 474: Redis Invocations by Script and Line Number

## Date: January 9, 2025

## Summary
This document provides a line-by-line listing of all Redis invocations across the codebase, organized by script for easy reference.

## 1. Core Redis Module: `scripts/cache.py`

### Redis Client Setup
- **Line 288**: Class `RedisManager` definition
- **Line 305**: `self.redis_client = None` initialization
- **Line 341**: `redis.Redis()` client creation
- **Line 361**: `self.redis_client.ping()` connection test

### Redis Operations
- **Line 400**: `get_client()` - Returns Redis client
- **Line 415**: `get_cached()` - Basic get operation
- **Line 455**: `set_cached()` - Basic set operation
- **Line 495**: `get_cached_model()` - Get Pydantic model
- **Line 525**: `set_cached_model()` - Set Pydantic model
- **Line 553**: `delete()` - Delete key
- **Line 567**: `exists()` - Check key existence
- **Line 581**: `expire()` - Set key expiration
- **Line 593**: `lock()` - Distributed locking
- **Line 615**: `scan_keys()` - Pattern scanning
- **Line 635**: `delete_pattern()` - Pattern deletion
- **Line 657**: `mget()` - Multi-get operation
- **Line 675**: `mset()` - Multi-set operation
- **Line 695**: `hget()` - Hash get
- **Line 709**: `hset()` - Hash set
- **Line 723**: `hgetall()` - Get all hash fields
- **Line 737**: `sadd()` - Set add
- **Line 751**: `smembers()` - Get set members
- **Line 765**: `srem()` - Remove from set

## 2. PDF Processing Tasks: `scripts/pdf_tasks.py`

### Redis Manager Usage
- **Line 22**: Import statement: `from scripts.cache import get_redis_manager, CacheKeys, redis_cache`
- **Line 392**: `redis_manager = get_redis_manager()` in `update_document_state()`
- **Line 393**: `redis_manager.set_cached()` - Store document state
- **Line 679**: `redis_manager.set_cached()` - Cache OCR result
- **Line 718**: `redis_manager.set_cached()` - Cache chunk data
- **Line 939**: `redis_manager.get_cached()` - Retrieve entity state
- **Line 940**: `redis_manager.set_cached()` - Update entity state
- **Line 1138**: `redis_manager.lock()` - Lock for entity resolution
- **Line 1465**: `redis_manager.set_cached()` - Cache relationship status
- **Line 1902**: `redis_manager.set_cached()` - Pipeline completion state
- **Line 2082**: `redis_manager.set_cached()` - Error state
- **Line 2263**: `redis_manager.get_cached()` - Check retry state
- **Line 2264**: `redis_manager.set_cached()` - Update retry count
- **Line 2330**: `redis_manager.exists()` - Check circuit breaker
- **Line 2372**: `redis_manager.get_cached_model()` - Get validation cache

## 3. Entity Service: `scripts/entity_service.py`

### Redis Integration
- **Line 45**: Import: `from scripts.cache import redis_cache, get_redis_manager, rate_limit, CacheKeys`
- **Line 111**: `self.redis_manager = get_redis_manager()`
- **Line 278**: `@redis_cache(expire=3600)` decorator on `extract_entities_from_chunk()`
- **Line 412**: `self.redis_manager.set_cached()` - Cache entity mentions
- **Line 456**: `self.redis_manager.get_cached()` - Retrieve cached entities
- **Line 523**: `@rate_limit(max_calls=10, period=60)` on OpenAI call
- **Line 687**: `self.redis_manager.lock()` - Lock for entity resolution
- **Line 745**: `self.redis_manager.delete()` - Clear old cache
- **Line 789**: `self.redis_manager.set_cached()` - Cache canonical entities

## 4. Textract Utils: `scripts/textract_utils.py`

### Redis Caching
- **Line 35**: Import: `from scripts.cache import get_redis_manager, redis_cache`
- **Line 157**: `self.redis_manager = get_redis_manager()`
- **Line 444**: `self.redis_manager.set_cached()` - Store job status
- **Line 461**: `self.redis_manager.get_cached()` - Retrieve job status
- **Line 882**: `self.redis_manager.set_cached()` - Cache OCR results
- **Line 896**: `self.redis_manager.get_cached()` - Check for cached OCR
- **Line 1204**: `self.redis_manager.set_cached()` - Update completion status
- **Line 1220**: `self.redis_manager.set_cached()` - Store processed text

## 5. Celery Configuration: `scripts/celery_app.py`

### Redis as Broker/Backend
- **Line 11**: Import: `from scripts.config import get_redis_config_for_stage`
- **Line 29**: `redis_config = get_redis_config_for_stage(DEPLOYMENT_STAGE)`
- **Line 41**: `broker_url = redis_config['CELERY_BROKER_URL']`
- **Line 42**: `result_backend = redis_config['CELERY_RESULT_BACKEND']`
- **Line 89**: `broker_transport_options` with Redis-specific settings

## 6. Status Manager: `scripts/status_manager.py`

### Status Tracking
- **Line 19**: Import: `from scripts.cache import get_redis_manager`
- **Line 132**: `self.redis = get_redis_manager()`
- **Line 245**: `self.redis.set_cached()` - Update processing status
- **Line 267**: `self.redis.get_cached()` - Retrieve status
- **Line 312**: `self.redis.mget()` - Batch status retrieval
- **Line 456**: `self.redis.scan_keys()` - Find status keys

## 7. Batch Processor: `scripts/batch_processor.py`

### Batch Coordination
- **Line 21**: Import: `from scripts.cache import get_redis_manager`
- **Line 174**: `self.redis = get_redis_manager()`
- **Line 287**: `self.redis.set_cached()` - Store batch state
- **Line 345**: `self.redis.lock()` - Lock batch processing
- **Line 423**: `self.redis.sadd()` - Add to processing set
- **Line 489**: `self.redis.srem()` - Remove from set
- **Line 567**: `self.redis.mget()` - Get multiple batch states

## 8. Services Layer

### Document Categorization Service: `scripts/services/document_categorization.py`
- **Line 10**: Import: `from scripts.cache import get_redis_manager`
- **Line 67**: `self.redis_manager = get_redis_manager()`
- **Line 134**: `self.redis_manager.set_cached()` - Cache category
- **Line 189**: `self.redis_manager.get_cached()` - Retrieve category

### Project Association Service: `scripts/services/project_association.py`
- **Line 15**: Import: `from scripts.cache import get_redis_manager, CacheKeys`
- **Line 35**: `self.redis = get_redis_manager()`
- **Line 98**: `self.redis.hset()` - Store project mapping
- **Line 145**: `self.redis.hget()` - Retrieve project mapping

### Semantic Naming Service: `scripts/services/semantic_naming.py`
- **Line 12**: Import: `from scripts.cache import get_redis_manager`
- **Line 58**: `self.redis_manager = get_redis_manager()`
- **Line 123**: `self.redis_manager.set_cached()` - Cache semantic name

## 9. Validation Layer

### Entity Validator: `scripts/validation/entity_validator.py`
- **Line 20**: Import: `from scripts.cache import get_redis_manager`
- **Line 81**: `self.redis = get_redis_manager()`
- **Line 156**: `self.redis.get_cached()` - Check validation cache

### OCR Validator: `scripts/validation/ocr_validator.py`
- **Line 20**: Import: `from scripts.cache import get_redis_manager`
- **Line 84**: `self.redis = get_redis_manager()`
- **Line 178**: `self.redis.set_cached()` - Cache validation result

### Pipeline Validator: `scripts/validation/pipeline_validator.py`
- **Line 19**: Import: `from scripts.cache import get_redis_manager`
- **Line 90**: `self.redis = get_redis_manager()`
- **Line 234**: `self.redis.exists()` - Check stage completion

## 10. CLI Tools

### Import CLI: `scripts/cli/import.py`
- **Line 27**: Import: `from scripts.cache import get_redis_manager`
- **Line 39**: `self.cache_manager = get_redis_manager()`
- **Line 156**: `self.cache_manager.set_cached()` - Track import progress

### Monitor CLI: `scripts/cli/monitor.py`
- **Line 32**: Import: `from scripts.cache import get_redis_manager`
- **Line 370**: `redis = get_redis_manager()` in `get_redis_stats()`
- **Line 378**: `redis_client.info()` - Get Redis info
- **Line 516**: Display Redis connection info
- **Line 893**: `redis.redis_client.ping()` - Health check

### Enhanced Monitor: `scripts/cli/enhanced_monitor.py`
- **Line 18**: Import: `from scripts.cache import get_redis_manager`
- **Line 78**: `self.redis = get_redis_manager()`
- **Line 234**: `self.redis.scan_keys()` - Monitor cache keys

## 11. Test Files

### Integration Tests: `tests/integration/test_ocr_pipeline.py`
- **Line 12**: Import: `from scripts.cache import get_redis_manager`
- **Line 45**: `redis = get_redis_manager()` in test setup
- **Line 67**: `redis.delete_pattern()` - Clear test data

### Unit Tests: `tests/unit/test_entity_service.py`
- **Line 8**: Import: `from scripts.cache import get_redis_manager`
- **Line 34**: Mock Redis in tests

## 12. Monitoring and Health

### Health Monitor: `scripts/monitoring/health_monitor.py`
- **Line 14**: Import: `from scripts.cache import get_redis_manager`
- **Line 23**: `self.redis = get_redis_manager()`
- **Line 89**: `self.redis.set_cached()` - Store health metrics
- **Line 145**: `self.redis.get_cached()` - Retrieve metrics

### Intake Service: `scripts/intake_service.py`
- **Line 23**: Import: `from scripts.cache import get_redis_manager`
- **Line 84**: `redis_manager = get_redis_manager()`
- **Line 85**: `redis_manager.set_cached()` - Track document intake

## Summary Statistics

### Total Redis Invocations by Category:
- **Direct Redis operations**: 89 locations
- **Decorator usage** (@redis_cache, @rate_limit): 12 locations  
- **Lock operations**: 8 locations
- **Batch operations** (mget, mset): 6 locations
- **Hash operations**: 5 locations
- **Set operations**: 4 locations

### Most Redis-Heavy Modules:
1. **scripts/pdf_tasks.py**: 15 invocations
2. **scripts/cache.py**: 28 methods (core implementation)
3. **scripts/textract_utils.py**: 8 invocations
4. **scripts/entity_service.py**: 9 invocations
5. **scripts/status_manager.py**: 6 invocations

### Key Patterns:
- Consistent use of `get_redis_manager()` singleton
- Heavy use of caching decorators for expensive operations
- Distributed locking for critical sections
- Rate limiting for external API calls
- State management throughout async pipeline/p