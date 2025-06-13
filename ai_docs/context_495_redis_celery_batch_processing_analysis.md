# Context 495: Redis and Celery Architecture Analysis for Batch Processing

## Date: January 10, 2025

## Executive Summary

This document analyzes the current Redis and Celery implementation in the legal document processor against reference patterns, assessing its suitability for batch processing. The analysis reveals that while the current architecture has solid foundations, significant enhancements are needed to support efficient batch processing of hundreds or thousands of documents.

## Reference Patterns Analysis

### 1. Celery Best Practices for Batch Processing

From the reference materials in `/opt/legal-doc-processor/resources/`:

#### Bulk Task Producer Pattern
```python
# From eventlet/bulk_task_producer.py
# Efficient batch task production using producer pools
with producers[connection].acquire(block=True) as producer:
    for batch in chunks(documents, batch_size=100):
        group([process_document.s(doc) for doc in batch]).apply_async(
            producer=producer,
            compression='zlib',
            serializer='json'
        )
```

#### Group and Chord Patterns
```python
# From resultgraph/tasks.py
# Parallel processing with result aggregation
chord(
    (process_document.s(doc) for doc in documents),
    summarize_results.s()
).apply_async()
```

#### Queue Configuration for High Throughput
```python
# Optimal queue configuration for different task profiles
Queue('ocr', routing_key='ocr.#', 
      queue_arguments={'x-max-priority': 10}),
Queue('batch', routing_key='batch.#',
      queue_arguments={'x-message-ttl': 86400000})  # 24 hours
```

### 2. Redis Optimization Patterns

#### Connection Pooling
```python
# Recommended pool configuration
redis_pool = redis.ConnectionPool(
    max_connections=100,
    socket_keepalive=True,
    socket_keepalive_options={
        1: 1,   # TCP_KEEPIDLE
        2: 1,   # TCP_KEEPINTVL
        3: 5,   # TCP_KEEPCNT
    }
)
```

#### Pipeline Operations for Batch Updates
```python
# Atomic batch operations
with redis_client.pipeline() as pipe:
    for doc_id, status in batch_updates:
        pipe.hset(f"doc:{doc_id}", "status", status)
        pipe.zadd("processing_queue", {doc_id: priority})
    pipe.execute()
```

## Current Implementation Analysis

### 1. Celery Configuration

**Current Setup** (`scripts/celery_app.py`):
```python
app = Celery('legal_doc_processor')
app.config_from_object({
    'broker_url': f'redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}',
    'result_backend': f'redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}',
    'task_serializer': 'json',
    'result_serializer': 'json',
    'accept_content': ['json'],
    'timezone': 'UTC',
    'enable_utc': True,
    'task_track_started': True,
    'task_send_sent_event': True,
    'worker_send_task_events': True,
    'task_default_queue': 'default',
    'task_default_exchange': 'default',
    'task_default_routing_key': 'default',
    'task_routes': {
        'scripts.pdf_tasks.extract_text_from_document': {'queue': 'ocr'},
        'scripts.pdf_tasks.chunk_document_text': {'queue': 'text'},
        'scripts.pdf_tasks.extract_entities_from_chunks': {'queue': 'entity'},
        'scripts.pdf_tasks.resolve_document_entities': {'queue': 'entity'},
        'scripts.pdf_tasks.build_document_relationships': {'queue': 'graph'},
        'scripts.pdf_tasks.cleanup_failed_processing': {'queue': 'cleanup'},
    },
    'worker_max_memory_per_child': 512000,  # 512MB
    'task_compression': 'gzip',
    'task_always_eager': False
})
```

**Strengths**:
- Proper queue routing by task type
- Memory limits to prevent worker bloat
- Event tracking enabled for monitoring

**Gaps for Batch Processing**:
- No priority queue configuration
- Missing prefetch multiplier optimization
- No batch-specific queue configuration
- Limited error handling configuration

### 2. Redis Implementation

**Current Setup** (`scripts/cache.py`):
```python
class RedisManager:
    def __init__(self):
        pool_params = {
            'host': REDIS_HOST,
            'port': REDIS_PORT,
            'db': REDIS_DB,
            'password': REDIS_PASSWORD,
            'decode_responses': True,
            'max_connections': REDIS_MAX_CONNECTIONS,
            'socket_keepalive': True,
            'socket_keepalive_options': REDIS_SOCKET_KEEPALIVE_OPTIONS,
        }
        self._pool = redis.ConnectionPool(**pool_params)
```

**Current Usage Patterns**:
- Single Redis database (DB 0) for everything
- Cache keys: document state, OCR results, chunks, entities
- TTL strategies: 3600s (1hr) to 86400s (24hr)
- Circuit breaker pattern for resilience

**Gaps for Batch Processing**:
- No Redis pipeline usage for batch operations
- Missing batch get/set operations
- No Redis Streams for event processing
- Single database mixing cache and task data

### 3. Task Implementation Analysis

**Current Pattern** (`scripts/pdf_tasks.py`):
```python
@app.task(name='extract_text_from_document', bind=True, base=DocumentTaskBase)
def extract_text_from_document(self, document_uuid: str, **kwargs):
    # Process single document
    # Submit next task individually
    chunk_document_text.apply_async(
        args=[document_uuid],
        queue='text',
        task_id=f"{document_uuid}-chunk"
    )
```

**Issues for Batch Processing**:
- Sequential task chaining per document
- No batch coordination mechanisms
- Limited parallel processing capabilities
- No batch progress tracking

## Architecture Suitability Assessment

### Current Architecture Limitations for Batch Processing

1. **Sequential Processing Model**
   - Each document processed independently
   - No batch coordination or aggregation
   - Limited parallelization within batches

2. **Resource Inefficiency**
   - API calls not batched (OpenAI, Textract)
   - Database operations per document, not batched
   - Cache operations not optimized for bulk

3. **Monitoring Gaps**
   - No batch-level progress tracking
   - Limited visibility into batch performance
   - Missing batch error recovery

4. **Scaling Constraints**
   - Worker memory limits too restrictive for batches
   - No dynamic worker scaling based on batch size
   - Queue configuration not optimized for high throughput

## Redis Database Separation Proposal

### Recommended Multi-Database Architecture

```python
# Redis Database Allocation
REDIS_DB_BROKER = 0      # Celery task broker
REDIS_DB_RESULTS = 1     # Celery results backend
REDIS_DB_CACHE = 2       # Application cache (document data)
REDIS_DB_RATE_LIMIT = 3  # Rate limiting and counters
REDIS_DB_BATCH = 4       # Batch processing metadata

# Configuration Update
CELERY_CONFIG = {
    'broker_url': f'redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB_BROKER}',
    'result_backend': f'redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB_RESULTS}',
}

# Cache Manager Update
class CacheManager:
    def __init__(self):
        self.cache_pool = redis.ConnectionPool(db=REDIS_DB_CACHE, ...)
        self.batch_pool = redis.ConnectionPool(db=REDIS_DB_BATCH, ...)
```

### Benefits of Separation

1. **Performance Isolation**
   - Cache operations don't interfere with task delivery
   - Batch metadata separate from document cache
   - Independent memory management per database

2. **Operational Benefits**
   - Clear data lifecycle management
   - Independent backup/restore strategies
   - Easier debugging and monitoring

3. **Scaling Flexibility**
   - Can move databases to separate Redis instances
   - Different eviction policies per database
   - Independent persistence configuration

## Batch Processing Implementation Requirements

### 1. Batch Task Definitions

```python
@app.task(name='process_document_batch', bind=True)
def process_document_batch(self, document_batch: List[str], batch_id: str):
    """Process a batch of documents in parallel."""
    
    # Track batch progress in Redis
    batch_key = f"batch:{batch_id}"
    redis_batch = get_redis_connection(REDIS_DB_BATCH)
    
    # Create parallel processing group
    job = group([
        process_single_document.s(doc_uuid) 
        for doc_uuid in document_batch
    ])
    
    # Execute with batch tracking
    result = job.apply_async(
        link=update_batch_progress.s(batch_id),
        link_error=handle_batch_error.s(batch_id)
    )
    
    # Store batch metadata
    batch_data = {
        'total': len(document_batch),
        'completed': 0,
        'failed': 0,
        'start_time': datetime.now().isoformat()
    }
    redis_batch.hset(batch_key, mapping=batch_data)
    redis_batch.expire(batch_key, 86400)  # 24 hours
    
    return {'batch_id': batch_id, 'group_id': result.id}
```

### 2. Optimized Queue Configuration

```python
# Enhanced Celery configuration for batch processing
CELERY_BATCH_CONFIG = {
    # Existing config plus:
    'task_routes': {
        'batch.process_document_batch': {'queue': 'batch', 'priority': 5},
        'batch.aggregate_results': {'queue': 'batch', 'priority': 3},
        # OCR tasks with lower priority for batch
        'scripts.pdf_tasks.extract_text_from_document': {
            'queue': 'ocr',
            'priority': lambda uuid: 1 if is_batch(uuid) else 9
        },
    },
    
    # Optimize for batch throughput
    'worker_prefetch_multiplier': 1,  # For OCR workers
    'task_acks_late': True,
    'task_reject_on_worker_lost': True,
    
    # Batch-specific settings
    'task_batch_size': 100,  # Process in chunks
    'task_time_limit': 3600,  # 1 hour for batch tasks
    'task_soft_time_limit': 3000,  # 50 minutes soft limit
}
```

### 3. Redis Pipeline Operations

```python
def update_batch_documents_status(batch_updates: List[Tuple[str, str]]):
    """Efficiently update multiple document statuses."""
    redis_cache = get_redis_connection(REDIS_DB_CACHE)
    
    with redis_cache.pipeline() as pipe:
        for doc_uuid, status in batch_updates:
            # Update document state
            state_key = CacheKeys.format_key(CacheKeys.DOC_STATE, document_uuid=doc_uuid)
            pipe.hset(state_key, "status", status)
            pipe.hset(state_key, "updated_at", datetime.now().isoformat())
            
            # Update sorted set for batch tracking
            pipe.zadd(f"batch:processing", {doc_uuid: time.time()})
            
        # Execute all updates atomically
        pipe.execute()
```

### 4. Batch Progress Monitoring

```python
def get_batch_progress(batch_id: str) -> Dict[str, Any]:
    """Get real-time batch processing progress."""
    redis_batch = get_redis_connection(REDIS_DB_BATCH)
    
    # Use Lua script for atomic read
    lua_script = """
    local batch_key = KEYS[1]
    local docs_key = KEYS[2]
    
    local batch_data = redis.call('hgetall', batch_key)
    local processing = redis.call('zcard', docs_key)
    
    return {batch_data, processing}
    """
    
    result = redis_batch.eval(lua_script, 2, 
                              f"batch:{batch_id}", 
                              f"batch:{batch_id}:docs")
    return parse_batch_progress(result)
```

## Recommendations

### Immediate Actions (Week 1)

1. **Implement Redis Database Separation**
   - Separate broker, results, cache, and batch databases
   - Update connection managers for each database
   - Migrate existing data to appropriate databases

2. **Create Batch Task Infrastructure**
   - Implement batch processing tasks using Celery groups
   - Add batch progress tracking in Redis
   - Create batch monitoring endpoints

### Short Term (Weeks 2-3)

3. **Optimize Queue Configuration**
   - Implement priority queues for SLA management
   - Configure worker pools for different task types
   - Add prefetch optimization based on task profile

4. **Implement Pipeline Operations**
   - Convert bulk operations to Redis pipelines
   - Add batch get/set operations for cache
   - Implement atomic batch status updates

### Medium Term (Week 4+)

5. **Advanced Batch Features**
   - Implement partial batch recovery
   - Add batch result aggregation with chords
   - Create batch performance analytics

6. **Monitoring and Observability**
   - Real-time batch progress dashboard
   - Performance metrics per batch
   - Automated alerting for batch failures

## Expected Outcomes

With these improvements, the system will support:

1. **Batch Processing Capacity**
   - Handle 1000+ documents per batch
   - Process multiple batches concurrently
   - Linear scaling with worker count

2. **Performance Improvements**
   - 50% reduction in per-document overhead
   - 3x improvement in throughput for large batches
   - Reduced API costs through batching

3. **Operational Benefits**
   - Real-time batch progress visibility
   - Graceful partial batch recovery
   - Predictable processing times

## Conclusion

While the current architecture provides a solid foundation, significant enhancements are needed to support efficient batch processing. The proposed Redis database separation and Celery optimization strategies will enable the system to handle large-scale document processing while maintaining reliability and performance. The phased implementation approach allows for incremental improvements without disrupting existing functionality.