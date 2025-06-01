# Redis Refactor Implementation Tasks

## Overview
This document outlines the comprehensive task list for integrating Redis into the Legal Document Processing Pipeline to enhance performance, robustness, and scalability.

## Task List

### High Priority Tasks

#### 1. Redis Configuration & Connection Management (redis-1)
- **Location**: `scripts/config.py`
- **Description**: Set up Redis configuration and connection management
- **Implementation**:
  - Add Redis connection parameters (host, port, db, password)
  - Create stage-aware Redis configuration (local for dev, Elasticache for cloud)
  - Add connection pool settings
  - Include Redis enable/disable flags per deployment stage

#### 2. Redis Utility Module (redis-2)
- **Location**: Create `scripts/redis_utils.py`
- **Description**: Create centralized Redis utility module with connection pooling
- **Implementation**:
  - Connection pool management
  - Helper functions for common operations
  - Error handling and retry logic
  - Serialization/deserialization utilities
  - Cache key generation patterns

#### 3. LLM Response Caching (redis-3)
- **Location**: `scripts/entity_extraction.py`
- **Description**: Implement caching decorator for OpenAI API responses
- **Implementation**:
  - Create cache decorator with TTL support
  - Use key pattern: `llm_cache:{model}:{hash_of_prompt}`
  - Add cache hit/miss metrics
  - Handle JSON serialization of responses

#### 4. OCR Result Caching (redis-4)
- **Location**: `scripts/ocr_extraction.py`, `scripts/textract_utils.py`
- **Description**: Cache OCR results to avoid redundant processing
- **Implementation**:
  - Cache Textract results with key: `textract:{document_uuid}:result`
  - Cache local OCR results with key: `ocr:{document_uuid}:{method}:result`
  - Include file hash/S3 ETag for validity checking
  - Set appropriate TTL based on document type

#### 5. Distributed Queue Locking (redis-5)
- **Location**: `scripts/queue_processor.py`
- **Description**: Implement Redis-based distributed locking for queue items
- **Implementation**:
  - Use Redis SETNX for atomic queue item claiming
  - Create lock key: `lock:queue_item:{queue_id}`
  - Add lock timeout and automatic release
  - Integrate with existing queue claiming logic

### Medium Priority Tasks

#### 6. API Rate Limiting (redis-6)
- **Location**: Create rate limiting wrapper for API calls
- **Description**: Implement sliding window rate limiter
- **Implementation**:
  - Create rate limiter using Redis sorted sets
  - Apply to OpenAI, AWS Textract API calls
  - Configure limits per API endpoint
  - Add backoff logic when limits reached

#### 7. Document Processing State Tracking (redis-7)
- **Location**: `scripts/main_pipeline.py`
- **Description**: Track document processing stages in Redis
- **Implementation**:
  - Use Redis hashes: `doc_state:{document_uuid}`
  - Track stages: ocr_completed, chunking_completed, etc.
  - Enable pipeline resumption from last completed stage
  - Add progress querying functionality

#### 8. Structured Extraction Caching (redis-8)
- **Location**: `scripts/structured_extraction.py`
- **Description**: Cache structured extraction results
- **Implementation**:
  - Cache key: `structured:{chunk_uuid}:data`
  - Cache both chunk-level and document-level extractions
  - Include model version in cache key
  - Handle cache invalidation on model updates

#### 9. Entity Resolution Caching (redis-9)
- **Location**: `scripts/entity_resolution.py`
- **Description**: Cache entity resolution results
- **Implementation**:
  - Cache key: `resolution:{document_uuid}:entities`
  - Store resolved entity clusters
  - Include context hash in key for accuracy
  - Set TTL based on document update frequency

#### 10. Idempotency Keys (redis-10)
- **Location**: `scripts/supabase_utils.py`
- **Description**: Implement idempotency for critical database writes
- **Implementation**:
  - Generate idempotency keys for entity creation
  - Check Redis before write operations
  - Store keys with appropriate TTL
  - Handle duplicate request scenarios

### Lower Priority Tasks

#### 11. Chunk-Level Entity Caching (redis-11)
- **Location**: After entity extraction in pipeline
- **Description**: Cache entity mentions at chunk level
- **Implementation**:
  - Cache key: `chunk:{chunk_uuid}:entities`
  - Enable partial reprocessing
  - Coordinate with document-level caching

#### 12. Textract Job Status Caching (redis-12)
- **Location**: `scripts/textract_utils.py`
- **Description**: Cache Textract job statuses
- **Implementation**:
  - Reduce AWS API polling calls
  - Cache job status updates
  - Implement efficient status checking

#### 13. Redis Integration Testing (redis-13)
- **Location**: `tests/unit/`, `tests/integration/`
- **Description**: Create comprehensive tests
- **Implementation**:
  - Unit tests for cache decorators
  - Integration tests for distributed locking
  - Mock Redis for CI/CD environments
  - Performance benchmarking tests

#### 14. Health Check Updates (redis-14)
- **Location**: `scripts/health_check.py`
- **Description**: Monitor Redis health
- **Implementation**:
  - Add Redis connection checks
  - Monitor cache hit rates
  - Track memory usage
  - Alert on connection failures

#### 15. Documentation (redis-15)
- **Location**: Create `docs/redis_integration.md`
- **Description**: Document Redis patterns
- **Implementation**:
  - Usage guidelines
  - Cache key conventions
  - Troubleshooting guide
  - Performance tuning tips

## Implementation Order

1. **Phase 1**: Infrastructure (Tasks 1-2)
   - Set up configuration and utilities
   - Establish connection patterns

2. **Phase 2**: Core Caching (Tasks 3-4)
   - Implement high-impact caching
   - Measure performance improvements

3. **Phase 3**: Distributed Features (Tasks 5-7)
   - Add locking and state tracking
   - Enable distributed processing

4. **Phase 4**: Extended Caching (Tasks 8-11)
   - Cache remaining expensive operations
   - Optimize cache strategies

5. **Phase 5**: Polish & Documentation (Tasks 12-15)
   - Add monitoring and tests
   - Complete documentation

## Success Metrics

- **Performance**: 50%+ reduction in API calls
- **Reliability**: Zero race conditions in queue processing
- **Scalability**: Support for 10+ concurrent workers
- **Cost**: 30%+ reduction in external API costs
- **Maintainability**: Clear documentation and test coverage

## Notes

- All implementations should be stage-aware (different behavior for Stage 1/2/3)
- Cache keys should include version information for easy invalidation
- Consider Redis persistence settings for production deployments
- Monitor memory usage and implement eviction policies as needed