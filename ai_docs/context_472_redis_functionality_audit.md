# Comprehensive Redis Functionality Audit

**Date**: January 6, 2025  
**Scope**: All Redis-related functionality in /opt/legal-doc-processor  
**Purpose**: Document all Redis usage patterns, connections, and operations  

## Executive Summary

The codebase uses Redis extensively for:
1. Pipeline state management
2. Caching OCR results and extracted entities  
3. Task coordination and distributed locking
4. Rate limiting for external APIs
5. Celery broker and backend (for task queuing)
6. Performance metrics tracking

## 1. Redis Infrastructure

### 1.1 Core Redis Module: `scripts/cache.py`

**Primary Manager Class**: `RedisManager` (Singleton pattern)
- **Location**: Lines 288-735
- **Features**:
  - Connection pooling with SSL support
  - Singleton pattern to ensure single connection pool
  - Automatic reconnection handling
  - Support for Redis Cloud authentication
  - Circuit breaker pattern for failed connections

**Key Methods**:
- `get_client()`: Returns Redis client from pool
- `get_cached()`, `set_cached()`: Basic cache operations with JSON/pickle serialization
- `get_cached_model()`, `set_cached_model()`: Pydantic model-aware caching
- `lock()`: Distributed locking context manager
- `scan_keys()`, `delete_pattern()`: Pattern-based operations
- `mget()`, `mset()`: Batch operations
- Hash operations: `hget()`, `hset()`, `hgetall()`
- Set operations: `sadd()`, `smembers()`, `srem()`

### 1.2 Cache Manager: `CacheManager`
- **Location**: Lines 779-911
- **Purpose**: High-level cache management
- **Key Methods**:
  - `clear_document_cache()`: Clear all cache for a document
  - `clear_project_cache()`: Clear project-related cache
  - `get_cache_stats()`: Get Redis performance statistics

### 1.3 Cache Keys Registry: `CacheKeys` class
- **Location**: Lines 38-125
- **Document Processing Keys**:
  - `DOC_STATE`: "doc:state:{document_uuid}"
  - `DOC_OCR_RESULT`: "doc:ocr:{document_uuid}"
  - `DOC_ENTITIES`: "doc:entities:{document_uuid}:{chunk_id}"
  - `DOC_CHUNKS`: "doc:chunks:{document_uuid}"
  - `DOC_CHUNKS_LIST`: "doc:chunks_list:{document_uuid}"
  - `DOC_ENTITY_MENTIONS`: "doc:entity_mentions:{document_uuid}"
  - `DOC_CANONICAL_ENTITIES`: "doc:canonical_entities:{document_uuid}"

## 2. Redis Usage by Component

### 2.1 PDF Processing Tasks (`scripts/pdf_tasks.py`)

**Redis Manager Usage**:
- **Import**: Line 22: `from scripts.cache import get_redis_manager, CacheKeys, redis_cache`
- **State Updates**: 
  - Line 392-393: `update_document_state()` function
  - Updates document processing state with stage, status, and metadata

**Specific Usage Locations**:
- Line 392: `redis_manager = get_redis_manager()`
- Line 679: OCR result caching
- Line 718: Chunk data caching
- Line 939: Entity extraction state
- Line 1138: Entity resolution tracking
- Line 1465: Relationship building status
- Line 1902: Pipeline completion state
- Line 2082: Error state management
- Line 2263: Task retry state
- Line 2330: Circuit breaker state
- Line 2372: Document validation cache

### 2.2 Entity Service (`scripts/entity_service.py`)

**Redis Integration**:
- **Import**: Line 45: `from scripts.cache import redis_cache, get_redis_manager, rate_limit, CacheKeys`
- **Manager Instance**: Line 111: `self.redis_manager = get_redis_manager()`
- **Purpose**: 
  - Cache entity extraction results
  - Rate limiting for OpenAI API calls
  - Store extracted entity mentions

### 2.3 Textract Utils (`scripts/textract_utils.py`)

**Redis Usage**:
- **Import**: Line 35: `from scripts.cache import get_redis_manager, redis_cache`
- **Job Status Tracking**:
  - Line 444: Store Textract job status
  - Line 461: Retrieve job results
  - Line 882: Cache OCR results
  - Line 896: Check for cached results
  - Line 1204: Update job completion status
  - Line 1220: Store processed text

### 2.4 Celery Configuration (`scripts/celery_app.py`)

**Redis as Broker/Backend**:
- **Import**: Line 11: `get_redis_config_for_stage`
- **Config**: Line 29: `redis_config = get_redis_config_for_stage(DEPLOYMENT_STAGE)`
- **Purpose**: 
  - Message broker for task distribution
  - Result backend for task results
  - Task state persistence

### 2.5 Batch Processor (`scripts/batch_processor.py`)

**Redis Usage**:
- **Import**: Line 21: `from scripts.cache import get_redis_manager`
- **Instance**: Line 174: `self.redis = get_redis_manager()`
- **Purpose**: 
  - Track batch processing state
  - Coordinate parallel document processing
  - Store batch results

### 2.6 Status Manager (`scripts/status_manager.py`)

**Redis Integration**:
- **Import**: Line 19: `from scripts.cache import get_redis_manager`
- **Instance**: Line 132: `self.redis = get_redis_manager()`
- **Purpose**: 
  - Real-time status updates
  - Processing metrics
  - Worker health tracking

## 3. Redis Usage in Services

### 3.1 Document Categorization Service
- **File**: `scripts/services/document_categorization.py`
- **Line 10**: Import `get_redis_manager`
- **Line 67**: `self.redis_manager = get_redis_manager()`
- **Purpose**: Cache document categories and metadata

### 3.2 Project Association Service  
- **File**: `scripts/services/project_association.py`
- **Line 15**: Import `get_redis_manager, CacheKeys`
- **Line 35**: `self.redis = get_redis_manager()`
- **Purpose**: Cache project-document associations

### 3.3 Semantic Naming Service
- **File**: `scripts/services/semantic_naming.py`
- **Line 12**: Import `get_redis_manager`
- **Line 58**: `self.redis_manager = get_redis_manager()`
- **Purpose**: Cache semantic document names

## 4. Redis Usage in Validation

### 4.1 Entity Validator
- **File**: `scripts/validation/entity_validator.py`
- **Line 20**: Import `get_redis_manager`
- **Line 81**: `self.redis = get_redis_manager()`

### 4.2 Flexible Validator
- **File**: `scripts/validation/flexible_validator.py`
- **Line 10**: Import `get_redis_manager`
- **Line 47**: `self.redis = get_redis_manager()`

### 4.3 OCR Validator
- **File**: `scripts/validation/ocr_validator.py`
- **Line 20**: Import `get_redis_manager`
- **Line 84**: `self.redis = get_redis_manager()`

### 4.4 Pipeline Validator
- **File**: `scripts/validation/pipeline_validator.py`
- **Line 19**: Import `get_redis_manager`
- **Line 90**: `self.redis = get_redis_manager()`

### 4.5 Pre-Processor
- **File**: `scripts/validation/pre_processor.py`
- **Line 11**: Import `get_redis_manager`
- **Line 29**: `self.redis = get_redis_manager()`

## 5. Redis Usage in CLI Tools

### 5.1 Import CLI
- **File**: `scripts/cli/import.py`
- **Line 27**: Import `get_redis_manager`
- **Line 39**: `self.cache_manager = get_redis_manager()`
- **Purpose**: Track import progress and state

### 5.2 Monitor CLI
- **File**: `scripts/cli/monitor.py`
- **Line 370**: `get_redis_stats()` method
- **Line 516**: Display Redis statistics
- **Line 893**: Health check includes Redis status
- **Purpose**: Monitor Redis health and performance

## 6. Redis Usage in Monitoring

### 6.1 Health Monitor
- **File**: `scripts/monitoring/health_monitor.py`
- **Line 14**: Import `get_redis_manager`
- **Line 23**: `self.redis = get_redis_manager()`
- **Purpose**: System health tracking

### 6.2 Intake Service
- **File**: `scripts/intake_service.py`
- **Line 84-85**: Redis manager for document intake tracking

## 7. Configuration

### 7.1 Environment Variables (.env)
```
REDIS_DATABASE_NAME=preprocessagent
REDIS_PUBLIC_ENDPOINT=redis-12696.c325.us-east-1-4.ec2.redns.redis-cloud.com:12696
REDIS_USERNAME=joe_ott
REDIS_PW="BHMbnJHyf&9!4TT"
```

### 7.2 Config Module (`scripts/config.py`)
- **Function**: `get_redis_config_for_stage()` (Line 365)
- **Redis Config**: Line 391: `REDIS_CONFIG = get_redis_config_for_stage(DEPLOYMENT_STAGE)`

### 7.3 Celery Environment
- **File**: `scripts/celery_environment.conf`
- Lines 18-20: Export Redis environment variables

## 8. Redis Operations Summary

### 8.1 State Management Operations
- **Pattern**: `doc:state:{document_uuid}`
- **Operations**: get_dict(), store_dict()
- **Purpose**: Track document processing pipeline state

### 8.2 Caching Operations
- **OCR Results**: `doc:ocr:{document_uuid}`
- **Chunks**: `doc:chunks:{document_uuid}`, `doc:chunks_list:{document_uuid}`
- **Entities**: `doc:entities:{document_uuid}:{chunk_id}`
- **Operations**: get_cached(), set_cached(), mget(), mset()

### 8.3 Locking Operations
- **Pattern**: `lock:{resource_name}`
- **Operations**: lock() context manager
- **Purpose**: Distributed locking for concurrent operations

### 8.4 Rate Limiting
- **Pattern**: `rate:{service}:{operation}`
- **Decorator**: @rate_limit()
- **Purpose**: Control API request rates

### 8.5 Metrics Tracking
- **Pattern**: `cache:metrics:*`
- **Class**: CacheMetrics
- **Purpose**: Track cache hit/miss rates

## 9. Test Coverage

### 9.1 Files with Redis Tests
- `tests/conftest.py`: Test fixtures
- `tests/test_pdf_tasks.py`: PDF processing tests
- `tests/verification/test_production_verification.py`: Production tests
- `tests/utils/test_helpers.py`: Test utilities
- `tests/integration/test_ocr_pipeline.py`: Integration tests

## 10. Key Findings and Recommendations

### 10.1 Consistent Usage Pattern
- All components use `get_redis_manager()` singleton
- No direct Redis client instantiation found
- Consistent use of CacheKeys for key formatting

### 10.2 Areas of Heavy Usage
1. **PDF Tasks**: Most Redis operations (15+ locations)
2. **Textract Utils**: Job tracking and result caching (6+ locations)
3. **Entity Service**: Rate limiting and result caching
4. **Validation Services**: 5 different validators use Redis

### 10.3 Potential Improvements
1. **Connection Pool Monitoring**: Add metrics for pool usage
2. **Key Expiration**: Some keys may need TTL settings
3. **Error Handling**: Enhanced retry logic for connection failures
4. **Memory Usage**: Monitor Redis memory consumption

### 10.4 Security Considerations
- Credentials stored in environment variables
- SSL/TLS support enabled for Redis Cloud
- No hardcoded credentials found

## Conclusion

The Redis integration is well-structured with a centralized management approach through the `cache.py` module. All components consistently use the singleton RedisManager, ensuring efficient connection pooling. The system makes extensive use of Redis for state management, caching, distributed locking, and task coordination.