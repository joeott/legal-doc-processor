# Batch Processing Implementation Plan

## Overview
This plan addresses the gaps identified in the Celery/Redis analysis and provides concrete implementation steps for batch processing optimization.

## Phase 1: Core Batch Processing (Week 1)

### 1.1 Batch Task Definition
Create a new file `scripts/batch_tasks.py`:

```python
from celery import group, chord, chain
from scripts.celery_app import app
from scripts.pdf_tasks import PDFTask, extract_text_from_document

@app.task(bind=True, base=PDFTask, queue='default')
def process_document_batch(self, batch_manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Process a batch of documents with optimized parallelism."""
    batch_id = batch_manifest['batch_id']
    documents = batch_manifest['documents']
    
    # Create batch state in Redis
    batch_key = f"batch:state:{batch_id}"
    self.redis_manager.set_cached(batch_key, {
        'status': 'processing',
        'total': len(documents),
        'completed': 0,
        'failed': 0,
        'started_at': datetime.utcnow().isoformat()
    }, ttl=86400)
    
    # Create parallel tasks using Celery group
    parallel_tasks = group(
        process_single_document_optimized.s(doc) 
        for doc in documents
    )
    
    # Use chord for result aggregation
    return chord(parallel_tasks)(aggregate_batch_results.s(batch_id))

@app.task(bind=True, base=PDFTask)
def process_single_document_optimized(self, document: Dict[str, Any]) -> Dict[str, Any]:
    """Optimized single document processing with caching."""
    document_uuid = document['document_uuid']
    
    # Use Redis pipeline for atomic updates
    pipe = self.redis_manager.get_client().pipeline()
    
    # Check multiple caches in one round trip
    cache_keys = [
        CacheKeys.DOC_OCR_RESULT.format(document_uuid=document_uuid),
        CacheKeys.DOC_CHUNKS.format(document_uuid=document_uuid),
        CacheKeys.DOC_ENTITIES.format(document_uuid=document_uuid)
    ]
    
    cached_values = self.redis_manager.mget(cache_keys)
    
    # Process based on what's cached
    if all(cached_values):
        # Everything cached, skip to final stage
        return {'status': 'cached', 'document_uuid': document_uuid}
    
    # Chain remaining tasks
    return chain(
        extract_text_from_document.s(document_uuid, document['file_path']),
        chunk_document_text.s(),
        extract_entities_from_chunks.s()
    ).apply_async()

@app.task
def aggregate_batch_results(results: List[Dict], batch_id: str) -> Dict[str, Any]:
    """Aggregate batch processing results."""
    completed = sum(1 for r in results if r['status'] == 'completed')
    failed = sum(1 for r in results if r['status'] == 'failed')
    
    # Update batch state
    batch_key = f"batch:state:{batch_id}"
    redis_manager = get_redis_manager()
    redis_manager.set_cached(batch_key, {
        'status': 'completed',
        'total': len(results),
        'completed': completed,
        'failed': failed,
        'completed_at': datetime.utcnow().isoformat()
    }, ttl=86400)
    
    return {
        'batch_id': batch_id,
        'total': len(results),
        'completed': completed,
        'failed': failed
    }
```

### 1.2 Redis Pipeline Operations
Enhance `scripts/cache.py`:

```python
def batch_update_document_states(self, updates: List[Tuple[str, str, str, Dict]]) -> bool:
    """Update multiple document states atomically using pipeline."""
    if not self.is_available():
        return False
    
    try:
        pipe = self.get_client().pipeline()
        
        for document_uuid, stage, status, metadata in updates:
            state_key = CacheKeys.DOC_STATE.format(document_uuid=document_uuid)
            state_data = {
                stage: {
                    'status': status,
                    'timestamp': datetime.utcnow().isoformat(),
                    'metadata': metadata
                }
            }
            pipe.hset(state_key, stage, json.dumps(state_data[stage]))
            pipe.expire(state_key, 86400)
        
        pipe.execute()
        return True
    except Exception as e:
        logger.error(f"Batch update failed: {e}")
        return False

def batch_cache_documents(self, documents: List[Dict[str, Any]], ttl: int = 86400) -> bool:
    """Cache multiple documents efficiently."""
    if not self.is_available():
        return False
    
    try:
        pipe = self.get_client().pipeline()
        
        for doc in documents:
            doc_uuid = doc['document_uuid']
            
            # Cache OCR result
            if 'ocr_text' in doc:
                ocr_key = CacheKeys.DOC_OCR_RESULT.format(document_uuid=doc_uuid)
                pipe.setex(ocr_key, ttl, json.dumps({
                    'text': doc['ocr_text'],
                    'metadata': doc.get('ocr_metadata', {})
                }))
            
            # Cache chunks
            if 'chunks' in doc:
                chunks_key = CacheKeys.DOC_CHUNKS.format(document_uuid=doc_uuid)
                pipe.setex(chunks_key, ttl, json.dumps(doc['chunks']))
        
        pipe.execute()
        return True
    except Exception as e:
        logger.error(f"Batch cache failed: {e}")
        return False
```

### 1.3 Batch Progress Tracking
Create `scripts/batch_monitor.py`:

```python
class BatchProgressTracker:
    """Track batch processing progress in Redis."""
    
    def __init__(self):
        self.redis = get_redis_manager()
        self.progress_prefix = "batch:progress:"
    
    def init_batch(self, batch_id: str, document_uuids: List[str]) -> None:
        """Initialize batch progress tracking."""
        progress_key = f"{self.progress_prefix}{batch_id}"
        
        # Use Redis hash for efficient updates
        progress_data = {
            'status': 'initialized',
            'total': len(document_uuids),
            'pending': len(document_uuids),
            'processing': 0,
            'completed': 0,
            'failed': 0,
            'started_at': datetime.utcnow().isoformat()
        }
        
        # Store document list in a set
        docs_key = f"{self.progress_prefix}{batch_id}:documents"
        
        pipe = self.redis.get_client().pipeline()
        pipe.hset(progress_key, mapping=progress_data)
        pipe.sadd(docs_key, *document_uuids)
        pipe.expire(progress_key, 86400)
        pipe.expire(docs_key, 86400)
        pipe.execute()
    
    def update_document_status(self, batch_id: str, document_uuid: str, 
                             old_status: str, new_status: str) -> None:
        """Update individual document status within batch."""
        progress_key = f"{self.progress_prefix}{batch_id}"
        
        # Use Lua script for atomic update
        lua_script = """
        local progress_key = KEYS[1]
        local old_status = ARGV[1]
        local new_status = ARGV[2]
        
        -- Decrement old status count
        redis.call('hincrby', progress_key, old_status, -1)
        
        -- Increment new status count
        redis.call('hincrby', progress_key, new_status, 1)
        
        -- Update status if all completed or failed
        local completed = redis.call('hget', progress_key, 'completed')
        local failed = redis.call('hget', progress_key, 'failed')
        local total = redis.call('hget', progress_key, 'total')
        
        if tonumber(completed) + tonumber(failed) == tonumber(total) then
            redis.call('hset', progress_key, 'status', 'completed')
            redis.call('hset', progress_key, 'completed_at', ARGV[3])
        end
        
        return redis.status_reply('OK')
        """
        
        self.redis.get_client().eval(
            lua_script, 1, progress_key, 
            old_status, new_status, datetime.utcnow().isoformat()
        )
    
    def get_batch_progress(self, batch_id: str) -> Dict[str, Any]:
        """Get current batch progress."""
        progress_key = f"{self.progress_prefix}{batch_id}"
        progress_data = self.redis.hgetall(progress_key)
        
        if not progress_data:
            return None
        
        # Calculate completion percentage
        total = int(progress_data.get('total', 0))
        completed = int(progress_data.get('completed', 0))
        failed = int(progress_data.get('failed', 0))
        
        progress_data['completion_percentage'] = (
            ((completed + failed) / total * 100) if total > 0 else 0
        )
        
        return progress_data
```

## Phase 2: Priority Queue Implementation (Week 2)

### 2.1 Update Celery Configuration
Modify `scripts/celery_app.py`:

```python
# Add priority queue configuration
app.conf.update(
    # ... existing config ...
    
    # Priority queue configuration
    task_queue_max_priority=10,
    task_default_priority=5,
    worker_prefetch_multiplier=1,  # Important for priority to work properly
    
    # Define priority queues
    task_routes={
        # Existing routes...
        'scripts.batch_tasks.process_priority_batch': {'queue': 'priority.high'},
        'scripts.batch_tasks.process_normal_batch': {'queue': 'priority.normal'},
        'scripts.batch_tasks.process_low_batch': {'queue': 'priority.low'},
    },
    
    # Queue priorities (lower number = higher priority)
    broker_transport_options={
        'priority_steps': list(range(10)),
        'queue_order_strategy': 'priority',
    }
)
```

### 2.2 Priority-based Batch Processing
Add to `scripts/batch_tasks.py`:

```python
@app.task(bind=True, base=PDFTask, queue='priority.high', priority=9)
def process_priority_batch(self, batch_manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Process high-priority batches."""
    batch_manifest['priority'] = 'high'
    return process_document_batch(batch_manifest)

@app.task(bind=True, base=PDFTask, queue='priority.normal', priority=5)
def process_normal_batch(self, batch_manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Process normal-priority batches."""
    batch_manifest['priority'] = 'normal'
    return process_document_batch(batch_manifest)

@app.task(bind=True, base=PDFTask, queue='priority.low', priority=1)
def process_low_batch(self, batch_manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Process low-priority batches."""
    batch_manifest['priority'] = 'low'
    return process_document_batch(batch_manifest)
```

## Phase 3: Advanced Monitoring (Week 3)

### 3.1 Real-time Batch Monitoring
Create `scripts/batch_metrics.py`:

```python
class BatchMetricsCollector:
    """Collect and expose batch processing metrics."""
    
    def __init__(self):
        self.redis = get_redis_manager()
        self.metrics_prefix = "metrics:batch:"
    
    def record_batch_metric(self, metric_type: str, batch_id: str, 
                          value: float, tags: Dict[str, str] = None) -> None:
        """Record a batch metric."""
        timestamp = int(time.time())
        metric_key = f"{self.metrics_prefix}{metric_type}:{timestamp // 60}"
        
        metric_data = {
            'batch_id': batch_id,
            'value': value,
            'timestamp': timestamp,
            'tags': tags or {}
        }
        
        # Use sorted set for time-series data
        self.redis.get_client().zadd(
            metric_key, {json.dumps(metric_data): timestamp}
        )
        
        # Expire after 7 days
        self.redis.get_client().expire(metric_key, 604800)
    
    def get_batch_metrics(self, metric_type: str, 
                         start_time: datetime, 
                         end_time: datetime) -> List[Dict[str, Any]]:
        """Get batch metrics for a time range."""
        metrics = []
        
        # Calculate minute buckets
        start_minute = int(start_time.timestamp()) // 60
        end_minute = int(end_time.timestamp()) // 60
        
        for minute in range(start_minute, end_minute + 1):
            metric_key = f"{self.metrics_prefix}{metric_type}:{minute}"
            
            # Get all metrics in this bucket
            bucket_metrics = self.redis.get_client().zrangebyscore(
                metric_key, 
                start_time.timestamp(), 
                end_time.timestamp()
            )
            
            for metric_json in bucket_metrics:
                metrics.append(json.loads(metric_json))
        
        return metrics
```

### 3.2 Batch Processing Dashboard
Update `scripts/cli/monitor.py`:

```python
def get_batch_stats(self) -> Dict:
    """Get batch processing statistics."""
    if not self.redis_available:
        return {'error': 'Redis not available'}
    
    # Get all active batches
    batch_pattern = "batch:state:*"
    batch_keys = self.redis_client.scan_iter(match=batch_pattern)
    
    active_batches = []
    completed_batches = []
    
    for key in batch_keys:
        batch_data = self.redis_client.hgetall(key)
        if batch_data:
            batch_id = key.split(':')[-1]
            batch_data['batch_id'] = batch_id
            
            if batch_data.get('status') == 'processing':
                active_batches.append(batch_data)
            elif batch_data.get('status') == 'completed':
                completed_batches.append(batch_data)
    
    # Calculate aggregate stats
    total_documents = sum(int(b.get('total', 0)) for b in active_batches)
    completed_documents = sum(int(b.get('completed', 0)) for b in active_batches)
    
    return {
        'active_batches': len(active_batches),
        'completed_batches': len(completed_batches),
        'total_documents_processing': total_documents,
        'documents_completed': completed_documents,
        'completion_rate': (completed_documents / total_documents * 100) if total_documents > 0 else 0,
        'batches': active_batches[:10]  # Show latest 10
    }
```

## Phase 4: Error Recovery & Optimization (Week 4)

### 4.1 Batch Error Recovery
Add to `scripts/batch_tasks.py`:

```python
@app.task(bind=True, base=PDFTask)
def recover_failed_batch(self, batch_id: str, retry_strategy: str = 'selective') -> Dict[str, Any]:
    """Recover failed documents in a batch."""
    batch_key = f"batch:state:{batch_id}"
    batch_state = self.redis_manager.get_dict(batch_key)
    
    if not batch_state:
        return {'error': 'Batch not found'}
    
    # Get failed documents
    failed_docs_key = f"batch:failed:{batch_id}"
    failed_documents = self.redis_manager.smembers(failed_docs_key)
    
    if not failed_documents:
        return {'message': 'No failed documents to recover'}
    
    # Create recovery batch based on strategy
    if retry_strategy == 'selective':
        # Only retry documents that failed due to transient errors
        recovery_docs = []
        for doc_uuid in failed_documents:
            error_key = f"doc:error:{doc_uuid}"
            error_data = self.redis_manager.get_dict(error_key)
            
            if error_data and is_retryable_error(error_data.get('error')):
                recovery_docs.append(doc_uuid)
    else:
        recovery_docs = list(failed_documents)
    
    # Create recovery batch
    recovery_batch = {
        'batch_id': f"{batch_id}_recovery",
        'original_batch_id': batch_id,
        'documents': recovery_docs,
        'retry_strategy': retry_strategy,
        'created_at': datetime.utcnow().isoformat()
    }
    
    # Process recovery batch with higher priority
    return process_priority_batch.apply_async(args=[recovery_batch])
```

### 4.2 Cache Warming Strategy
Create `scripts/cache_warmer.py`:

```python
@app.task(bind=True, base=PDFTask, queue='cleanup')
def warm_batch_cache(self, batch_id: str) -> Dict[str, Any]:
    """Pre-warm cache for upcoming batch processing."""
    batch_manifest = self.redis_manager.get_dict(f"batch:manifest:{batch_id}")
    
    if not batch_manifest:
        return {'error': 'Batch manifest not found'}
    
    documents = batch_manifest.get('documents', [])
    warmed_count = 0
    
    # Use pipeline for efficient warming
    pipe = self.redis_manager.get_client().pipeline()
    
    for doc in documents:
        doc_uuid = doc['document_uuid']
        
        # Check if document already processed
        session = next(self.db_manager.get_session())
        try:
            result = session.execute(text("""
                SELECT raw_extracted_text, processing_status 
                FROM source_documents 
                WHERE document_uuid = :uuid
            """), {'uuid': doc_uuid}).fetchone()
            
            if result and result[0]:  # Has OCR text
                # Warm OCR cache
                ocr_key = CacheKeys.DOC_OCR_RESULT.format(document_uuid=doc_uuid)
                pipe.setex(ocr_key, 86400, json.dumps({
                    'text': result[0],
                    'status': 'completed'
                }))
                warmed_count += 1
        finally:
            session.close()
    
    pipe.execute()
    
    return {
        'batch_id': batch_id,
        'total_documents': len(documents),
        'cache_warmed': warmed_count
    }
```

## Implementation Timeline

### Week 1: Core Batch Processing
- [ ] Implement batch task definitions
- [ ] Add Redis pipeline operations
- [ ] Create batch progress tracking
- [ ] Test with small batches

### Week 2: Priority Queues
- [ ] Configure priority queues in Celery
- [ ] Implement priority-based routing
- [ ] Add priority batch tasks
- [ ] Test priority processing

### Week 3: Monitoring & Metrics
- [ ] Implement metrics collection
- [ ] Update monitoring dashboard
- [ ] Add batch statistics
- [ ] Create performance reports

### Week 4: Optimization & Recovery
- [ ] Implement error recovery
- [ ] Add cache warming
- [ ] Optimize batch sizing
- [ ] Performance testing

## Success Metrics

1. **Performance:**
   - 50% reduction in batch processing time
   - 80% cache hit rate for warmed batches
   - <5% failed document rate

2. **Scalability:**
   - Support for 1000+ document batches
   - Linear scaling with worker count
   - <10s batch initialization time

3. **Reliability:**
   - 95% batch completion rate
   - <5 min recovery time for failures
   - Zero data loss guarantee

## Testing Strategy

1. **Unit Tests:**
   - Test batch task logic
   - Test Redis operations
   - Test error handling

2. **Integration Tests:**
   - Test end-to-end batch flow
   - Test priority processing
   - Test recovery mechanisms

3. **Load Tests:**
   - Test with 100, 500, 1000 document batches
   - Test concurrent batch processing
   - Test worker scaling

4. **Chaos Tests:**
   - Test Redis failures
   - Test worker crashes
   - Test network partitions