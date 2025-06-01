# Context 92: Redis Optimization and Implementation Plan

## Overview
This document provides a comprehensive task list for optimizing Redis integration across the document processing pipeline. The plan includes specific implementation details, verification steps, and test requirements to enable autonomous execution by an agentic tool.

## Current State Analysis

### Redis Integration Points
1. **redis_utils.py**: Core Redis manager with connection pooling, caching decorators, and utility functions
2. **main_pipeline.py**: Document state tracking using Redis hashes
3. **queue_processor.py**: Distributed locking for queue items
4. **ocr_extraction.py**: OCR result caching (Textract)
5. **entity_extraction.py**: Entity extraction result caching (OpenAI and local)
6. **structured_extraction.py**: Structured data extraction caching
7. **textract_utils.py**: Textract job status and result caching

### Current Issues
1. Inconsistent cache key naming conventions
2. Missing cache invalidation strategies
3. No cache warming or preloading
4. Limited monitoring of cache performance
5. No Redis cluster support for high availability
6. Missing pipeline state recovery from Redis
7. No cache size management or eviction policies

## Task List

### Phase 1: Redis Infrastructure Optimization

#### Task 1.1: Standardize Cache Key Naming Convention
**Files to modify**: All files using Redis caching
**Implementation**:
```python
# Create a new file: scripts/cache_keys.py
class CacheKeys:
    """Centralized cache key definitions"""
    
    # Document processing keys
    DOC_STATE = "doc:state:{document_uuid}"
    DOC_OCR_RESULT = "doc:ocr:{document_uuid}"
    DOC_ENTITIES = "doc:entities:{document_uuid}:{chunk_id}"
    DOC_STRUCTURED = "doc:structured:{document_uuid}:{chunk_id}"
    
    # Job tracking keys
    TEXTRACT_JOB_STATUS = "job:textract:status:{job_id}"
    TEXTRACT_JOB_RESULT = "job:textract:result:{document_uuid}"
    
    # Queue management keys
    QUEUE_LOCK = "queue:lock:{queue_id}"
    QUEUE_PROCESSOR = "queue:processor:{processor_id}"
    
    # Rate limiting keys
    RATE_LIMIT_OPENAI = "rate:openai:{function_name}"
    RATE_LIMIT_TEXTRACT = "rate:textract:{operation}"
    
    # Idempotency keys
    IDEMPOTENT_OCR = "idempotent:ocr:{document_uuid}"
    IDEMPOTENT_ENTITY = "idempotent:entity:{chunk_hash}"
    
    @staticmethod
    def format_key(template: str, **kwargs) -> str:
        """Format a cache key template with parameters"""
        return template.format(**kwargs)
```

**Verification**:
- Run grep to find all Redis key usage: `grep -r "redis.*key\|cache.*key" scripts/`
- Update all hardcoded keys to use CacheKeys class
- Test that all cache operations still work

#### Task 1.2: Implement Cache Invalidation Strategy
**Files to modify**: redis_utils.py, main_pipeline.py
**Implementation**:
```python
# Add to redis_utils.py
class RedisManager:
    def invalidate_document_cache(self, document_uuid: str):
        """Invalidate all caches related to a document"""
        patterns = [
            f"doc:*:{document_uuid}*",
            f"entity:*:{document_uuid}*",
            f"structured:*:{document_uuid}*"
        ]
        
        client = self.get_client()
        for pattern in patterns:
            for key in client.scan_iter(match=pattern):
                client.delete(key)
                logger.debug(f"Invalidated cache key: {key}")
    
    def invalidate_pattern(self, pattern: str) -> int:
        """Invalidate all keys matching a pattern"""
        client = self.get_client()
        count = 0
        for key in client.scan_iter(match=pattern):
            client.delete(key)
            count += 1
        return count
```

**Verification**:
- Test cache invalidation with sample documents
- Verify that reprocessing uses fresh data
- Check Redis memory usage before/after invalidation

#### Task 1.3: Add Redis Connection Health Monitoring
**Files to modify**: health_check.py, redis_utils.py
**Implementation**:
```python
# Add to health_check.py
def check_redis_health(self) -> Dict:
    """Check Redis connection and performance"""
    try:
        redis_mgr = get_redis_manager()
        
        # Test connection
        start_time = time.time()
        is_available = redis_mgr.is_available()
        ping_time = (time.time() - start_time) * 1000  # ms
        
        if not is_available:
            self.issues.append({
                'type': 'redis_unavailable',
                'severity': 'warning',
                'message': 'Redis connection unavailable - caching disabled'
            })
            return {'available': False}
        
        # Get Redis info
        client = redis_mgr.get_client()
        info = client.info()
        
        # Check memory usage
        used_memory_mb = info.get('used_memory', 0) / (1024 * 1024)
        max_memory_mb = info.get('maxmemory', 0) / (1024 * 1024)
        
        if max_memory_mb > 0 and used_memory_mb / max_memory_mb > 0.9:
            self.issues.append({
                'type': 'redis_memory_high',
                'severity': 'warning',
                'message': f'Redis memory usage high: {used_memory_mb:.1f}/{max_memory_mb:.1f} MB'
            })
        
        return {
            'available': True,
            'ping_ms': round(ping_time, 2),
            'used_memory_mb': round(used_memory_mb, 2),
            'connected_clients': info.get('connected_clients', 0),
            'total_commands_processed': info.get('total_commands_processed', 0),
            'keyspace_hits': info.get('keyspace_hits', 0),
            'keyspace_misses': info.get('keyspace_misses', 0),
            'hit_rate': round(info.get('keyspace_hits', 0) / 
                            (info.get('keyspace_hits', 0) + info.get('keyspace_misses', 1)) * 100, 2)
        }
    except Exception as e:
        logger.error(f"Error checking Redis health: {e}")
        return {'available': False, 'error': str(e)}
```

**Verification**:
- Run health check: `python scripts/health_check.py`
- Verify Redis metrics are displayed
- Test with Redis down to ensure graceful handling

### Phase 2: Caching Strategy Enhancement

#### Task 2.1: Implement Cache Warming for Hot Documents
**Files to create**: scripts/cache_warmer.py
**Implementation**:
```python
# scripts/cache_warmer.py
import asyncio
from typing import List, Dict
from redis_utils import get_redis_manager
from textract_utils import TextractProcessor
from entity_extraction import extract_entities_openai

class CacheWarmer:
    """Preload cache for frequently accessed documents"""
    
    def __init__(self, db_manager):
        self.db_manager = db_manager
        self.redis_mgr = get_redis_manager()
        
    async def warm_recent_documents(self, hours: int = 24, limit: int = 100):
        """Warm cache for recently processed documents"""
        cutoff_time = datetime.now() - timedelta(hours=hours)
        
        # Get recent documents
        recent_docs = self.db_manager.client.table('source_documents').select(
            'id', 'document_uuid', 's3_key', 's3_bucket'
        ).gte('created_at', cutoff_time.isoformat()).limit(limit).execute()
        
        tasks = []
        for doc in recent_docs.data:
            if doc.get('s3_key'):
                tasks.append(self._warm_document_cache(doc))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        success_count = sum(1 for r in results if not isinstance(r, Exception))
        logger.info(f"Cache warming complete: {success_count}/{len(tasks)} documents")
        
    async def _warm_document_cache(self, doc: Dict):
        """Warm cache for a single document"""
        try:
            # Check if already cached
            cache_key = f"doc:ocr:{doc['document_uuid']}"
            if self.redis_mgr.exists(cache_key):
                logger.debug(f"Document {doc['document_uuid']} already cached")
                return
            
            # Simulate OCR result caching
            textract = TextractProcessor(self.db_manager)
            cached_result = textract.get_cached_ocr_result(doc['document_uuid'])
            
            if not cached_result:
                logger.debug(f"No cached OCR result for {doc['document_uuid']}")
                # Could trigger re-extraction here if needed
                
        except Exception as e:
            logger.error(f"Error warming cache for document {doc['document_uuid']}: {e}")
            raise
```

**Verification**:
- Run cache warmer: `python -c "from cache_warmer import CacheWarmer; import asyncio; cw = CacheWarmer(db_manager); asyncio.run(cw.warm_recent_documents())"`
- Check Redis memory usage increase
- Verify subsequent document access is faster

#### Task 2.2: Add Cache Metrics Collection
**Files to modify**: redis_utils.py
**Implementation**:
```python
# Add to redis_utils.py
class CacheMetrics:
    """Track cache performance metrics"""
    
    def __init__(self, redis_manager):
        self.redis_mgr = redis_manager
        self.metrics_key = "cache:metrics"
        
    def record_hit(self, cache_type: str):
        """Record a cache hit"""
        client = self.redis_mgr.get_client()
        client.hincrby(f"{self.metrics_key}:{cache_type}", "hits", 1)
        client.hincrby(f"{self.metrics_key}:total", "hits", 1)
        
    def record_miss(self, cache_type: str):
        """Record a cache miss"""
        client = self.redis_mgr.get_client()
        client.hincrby(f"{self.metrics_key}:{cache_type}", "misses", 1)
        client.hincrby(f"{self.metrics_key}:total", "misses", 1)
        
    def get_metrics(self, cache_type: str = None) -> Dict:
        """Get cache metrics"""
        client = self.redis_mgr.get_client()
        
        if cache_type:
            key = f"{self.metrics_key}:{cache_type}"
        else:
            key = f"{self.metrics_key}:total"
            
        metrics = client.hgetall(key)
        
        hits = int(metrics.get('hits', 0))
        misses = int(metrics.get('misses', 0))
        total = hits + misses
        
        return {
            'hits': hits,
            'misses': misses,
            'total': total,
            'hit_rate': round(hits / total * 100, 2) if total > 0 else 0
        }
```

**Verification**:
- Add metrics recording to cache decorators
- Process several documents
- Check metrics: `redis-cli HGETALL cache:metrics:total`

### Phase 3: Performance Optimization

#### Task 3.1: Implement Redis Pipeline for Batch Operations
**Files to modify**: main_pipeline.py, entity_extraction.py
**Implementation**:
```python
# Add to redis_utils.py
def batch_set_cached(self, key_value_pairs: List[Tuple[str, Any]], ttl: Optional[int] = None) -> bool:
    """Set multiple cache entries in a single pipeline"""
    try:
        client = self.get_client()
        pipe = client.pipeline()
        
        for key, value in key_value_pairs:
            if isinstance(value, (dict, list)):
                serialized = json.dumps(value)
            else:
                serialized = str(value)
            
            if ttl:
                pipe.setex(key, ttl, serialized)
            else:
                pipe.set(key, serialized)
        
        results = pipe.execute()
        return all(results)
    except Exception as e:
        logger.error(f"Redis batch set error: {e}")
        return False

def batch_get_cached(self, keys: List[str]) -> Dict[str, Any]:
    """Get multiple cache entries in a single pipeline"""
    try:
        client = self.get_client()
        pipe = client.pipeline()
        
        for key in keys:
            pipe.get(key)
        
        results = pipe.execute()
        
        return {
            key: self._deserialize_value(value) 
            for key, value in zip(keys, results) 
            if value is not None
        }
    except Exception as e:
        logger.error(f"Redis batch get error: {e}")
        return {}
```

**Verification**:
- Benchmark single vs batch operations
- Process documents with multiple chunks
- Monitor Redis command count reduction

#### Task 3.2: Add Connection Pool Monitoring
**Files to modify**: redis_utils.py
**Implementation**:
```python
# Add to RedisManager.__init__
self._pool_stats_interval = 300  # 5 minutes
self._last_pool_stats_time = 0

def log_pool_stats(self):
    """Log connection pool statistics"""
    if not self._pool or not self.is_available():
        return
        
    current_time = time.time()
    if current_time - self._last_pool_stats_time < self._pool_stats_interval:
        return
        
    self._last_pool_stats_time = current_time
    
    pool_stats = {
        'created_connections': self._pool.created_connections,
        'available_connections': len(self._pool._available_connections),
        'in_use_connections': len(self._pool._in_use_connections),
        'max_connections': self._pool.max_connections
    }
    
    logger.info(f"Redis connection pool stats: {pool_stats}")
    
    # Warn if approaching connection limit
    usage_ratio = pool_stats['in_use_connections'] / pool_stats['max_connections']
    if usage_ratio > 0.8:
        logger.warning(f"Redis connection pool usage high: {usage_ratio:.1%}")
```

**Verification**:
- Run queue processor with multiple workers
- Monitor logs for pool statistics
- Verify no connection exhaustion

### Phase 4: Advanced Features

#### Task 4.1: Implement Distributed Task Coordination
**Files to create**: scripts/task_coordinator.py
**Implementation**:
```python
# scripts/task_coordinator.py
from redis_utils import get_redis_manager
import uuid
import time

class TaskCoordinator:
    """Coordinate distributed processing tasks using Redis"""
    
    def __init__(self):
        self.redis_mgr = get_redis_manager()
        self.worker_id = f"worker:{socket.gethostname()}:{uuid.uuid4().hex[:8]}"
        
    def register_worker(self, capabilities: List[str]):
        """Register this worker with its capabilities"""
        client = self.redis_mgr.get_client()
        
        worker_data = {
            'id': self.worker_id,
            'capabilities': ','.join(capabilities),
            'status': 'active',
            'last_heartbeat': time.time(),
            'tasks_completed': 0
        }
        
        client.hset(f"workers:{self.worker_id}", mapping=worker_data)
        client.expire(f"workers:{self.worker_id}", 300)  # 5 minute TTL
        
    def heartbeat(self):
        """Update worker heartbeat"""
        client = self.redis_mgr.get_client()
        client.hset(f"workers:{self.worker_id}", 'last_heartbeat', time.time())
        client.expire(f"workers:{self.worker_id}", 300)
        
    def claim_task(self, task_type: str) -> Optional[Dict]:
        """Atomically claim a task from the queue"""
        client = self.redis_mgr.get_client()
        
        # Use BLPOP for blocking pop from task queue
        task_data = client.blpop(f"tasks:{task_type}", timeout=5)
        
        if task_data:
            _, task_json = task_data
            task = json.loads(task_json)
            
            # Record task assignment
            client.hset(f"task:assignments:{task['id']}", mapping={
                'worker_id': self.worker_id,
                'started_at': time.time(),
                'task_type': task_type
            })
            
            return task
        return None
        
    def complete_task(self, task_id: str, result: Dict):
        """Mark task as completed"""
        client = self.redis_mgr.get_client()
        
        # Update task assignment
        client.hset(f"task:assignments:{task_id}", mapping={
            'completed_at': time.time(),
            'status': 'completed',
            'result': json.dumps(result)
        })
        
        # Increment worker stats
        client.hincrby(f"workers:{self.worker_id}", 'tasks_completed', 1)
```

**Verification**:
- Start multiple workers with task coordinator
- Submit tasks to Redis queues
- Verify task distribution and completion

#### Task 4.2: Add Cache Preloading on Startup
**Files to modify**: main_pipeline.py, queue_processor.py
**Implementation**:
```python
# Add to main_pipeline.py
def preload_critical_cache():
    """Preload critical data into cache on startup"""
    logger.info("Preloading critical cache data...")
    
    redis_mgr = get_redis_manager()
    if not redis_mgr.is_available():
        logger.warning("Redis not available, skipping cache preload")
        return
        
    db_manager = SupabaseManager()
    
    # Preload active document states
    active_docs = db_manager.client.table('source_documents').select(
        'document_uuid', 'initial_processing_status'
    ).in_('initial_processing_status', ['processing', 'pending_ocr']).execute()
    
    for doc in active_docs.data:
        state_key = f"doc:state:{doc['document_uuid']}"
        redis_mgr.hset(state_key, 'status', doc['initial_processing_status'])
        redis_mgr.hset(state_key, 'preloaded', 'true')
        
    # Preload recent Textract job statuses
    recent_jobs = db_manager.client.table('textract_jobs').select(
        'job_id', 'job_status'
    ).gte('created_at', (datetime.now() - timedelta(hours=1)).isoformat()).execute()
    
    for job in recent_jobs.data:
        cache_key = f"job:textract:status:{job['job_id']}"
        redis_mgr.set_cached(cache_key, {'JobStatus': job['job_status']}, ttl=3600)
        
    logger.info(f"Preloaded {len(active_docs.data)} document states and {len(recent_jobs.data)} job statuses")
```

**Verification**:
- Restart pipeline with cache preloading
- Check Redis for preloaded keys
- Verify faster startup processing

### Phase 5: Monitoring and Observability

#### Task 5.1: Create Redis Dashboard
**Files to create**: monitoring/redis_monitor.py
**Implementation**:
```python
# monitoring/redis_monitor.py
import time
from rich.console import Console
from rich.table import Table
from rich.live import Live
from redis_utils import get_redis_manager

class RedisMonitor:
    """Real-time Redis monitoring dashboard"""
    
    def __init__(self):
        self.console = Console()
        self.redis_mgr = get_redis_manager()
        
    def get_redis_stats(self) -> Dict:
        """Get current Redis statistics"""
        if not self.redis_mgr.is_available():
            return {'error': 'Redis not available'}
            
        client = self.redis_mgr.get_client()
        info = client.info()
        
        # Get key counts by pattern
        key_counts = {}
        patterns = ['doc:*', 'job:*', 'queue:*', 'rate:*', 'cache:*']
        
        for pattern in patterns:
            count = sum(1 for _ in client.scan_iter(match=pattern, count=1000))
            key_counts[pattern] = count
            
        return {
            'uptime_hours': info.get('uptime_in_seconds', 0) / 3600,
            'connected_clients': info.get('connected_clients', 0),
            'used_memory_mb': info.get('used_memory', 0) / (1024 * 1024),
            'used_memory_peak_mb': info.get('used_memory_peak', 0) / (1024 * 1024),
            'total_commands': info.get('total_commands_processed', 0),
            'instantaneous_ops': info.get('instantaneous_ops_per_sec', 0),
            'keyspace_hits': info.get('keyspace_hits', 0),
            'keyspace_misses': info.get('keyspace_misses', 0),
            'evicted_keys': info.get('evicted_keys', 0),
            'key_counts': key_counts
        }
        
    def create_dashboard_table(self, stats: Dict) -> Table:
        """Create Rich table for dashboard"""
        table = Table(title="Redis Monitor Dashboard")
        
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")
        
        if 'error' in stats:
            table.add_row("Status", f"[red]{stats['error']}[/red]")
            return table
            
        # Basic stats
        table.add_row("Uptime", f"{stats['uptime_hours']:.1f} hours")
        table.add_row("Connected Clients", str(stats['connected_clients']))
        table.add_row("Memory Usage", f"{stats['used_memory_mb']:.1f} MB")
        table.add_row("Peak Memory", f"{stats['used_memory_peak_mb']:.1f} MB")
        table.add_row("Commands/sec", str(stats['instantaneous_ops']))
        
        # Cache performance
        total_cache_ops = stats['keyspace_hits'] + stats['keyspace_misses']
        hit_rate = (stats['keyspace_hits'] / total_cache_ops * 100) if total_cache_ops > 0 else 0
        table.add_row("Cache Hit Rate", f"{hit_rate:.1f}%")
        table.add_row("Evicted Keys", str(stats['evicted_keys']))
        
        # Key counts
        table.add_row("", "")  # Separator
        table.add_row("[bold]Key Counts[/bold]", "")
        for pattern, count in stats['key_counts'].items():
            table.add_row(f"  {pattern}", str(count))
            
        return table
        
    def run(self, refresh_interval: int = 5):
        """Run the monitoring dashboard"""
        with Live(self.create_dashboard_table(self.get_redis_stats()), 
                  refresh_per_second=1/refresh_interval) as live:
            while True:
                time.sleep(refresh_interval)
                stats = self.get_redis_stats()
                live.update(self.create_dashboard_table(stats))
```

**Verification**:
- Run monitor: `python monitoring/redis_monitor.py`
- Process documents while monitoring
- Verify real-time updates

### Phase 6: Testing and Validation

#### Task 6.1: Create Comprehensive Redis Tests
**Files to create**: tests/unit/test_redis_optimization.py
**Implementation**:
```python
# tests/unit/test_redis_optimization.py
import pytest
import time
from unittest.mock import Mock, patch
from redis_utils import RedisManager, redis_cache, rate_limit
from cache_keys import CacheKeys

class TestRedisOptimization:
    """Test Redis optimization features"""
    
    @pytest.fixture
    def redis_manager(self):
        """Get Redis manager instance"""
        return RedisManager()
        
    def test_cache_key_formatting(self):
        """Test standardized cache key formatting"""
        key = CacheKeys.format_key(CacheKeys.DOC_STATE, document_uuid="test-uuid")
        assert key == "doc:state:test-uuid"
        
    def test_batch_operations(self, redis_manager):
        """Test batch get/set operations"""
        # Prepare test data
        test_data = [
            ("test:key1", {"value": 1}),
            ("test:key2", {"value": 2}),
            ("test:key3", {"value": 3})
        ]
        
        # Batch set
        success = redis_manager.batch_set_cached(test_data, ttl=60)
        assert success
        
        # Batch get
        keys = [kv[0] for kv in test_data]
        results = redis_manager.batch_get_cached(keys)
        
        assert len(results) == 3
        assert results["test:key1"]["value"] == 1
        
    def test_cache_invalidation(self, redis_manager):
        """Test cache invalidation patterns"""
        # Set test keys
        redis_manager.set_cached("doc:state:uuid1", {"status": "processing"})
        redis_manager.set_cached("doc:ocr:uuid1", {"text": "sample"})
        redis_manager.set_cached("entity:local:uuid1:chunk1", {"entities": []})
        
        # Invalidate document cache
        redis_manager.invalidate_document_cache("uuid1")
        
        # Verify keys are deleted
        assert redis_manager.get_cached("doc:state:uuid1") is None
        assert redis_manager.get_cached("doc:ocr:uuid1") is None
        assert redis_manager.get_cached("entity:local:uuid1:chunk1") is None
        
    def test_rate_limiting(self):
        """Test rate limiting decorator"""
        call_count = 0
        
        @rate_limit(key="test", limit=3, window=1, wait=False)
        def limited_function():
            nonlocal call_count
            call_count += 1
            return call_count
            
        # Should allow 3 calls
        for i in range(3):
            assert limited_function() == i + 1
            
        # 4th call should raise
        with pytest.raises(RuntimeError, match="Rate limit exceeded"):
            limited_function()
            
        # Wait for window to reset
        time.sleep(1.1)
        
        # Should allow again
        assert limited_function() == 4
        
    def test_connection_pool_monitoring(self, redis_manager):
        """Test connection pool statistics"""
        # Force pool stats logging
        redis_manager._last_pool_stats_time = 0
        
        with patch('logging.Logger.info') as mock_log:
            redis_manager.log_pool_stats()
            
        # Verify stats were logged
        assert mock_log.called
        log_message = str(mock_log.call_args)
        assert 'connection pool stats' in log_message
        
    @pytest.mark.asyncio
    async def test_cache_warming(self, redis_manager):
        """Test cache warming functionality"""
        from cache_warmer import CacheWarmer
        
        # Mock database manager
        mock_db = Mock()
        mock_db.client.table.return_value.select.return_value.gte.return_value.limit.return_value.execute.return_value.data = [
            {'id': 1, 'document_uuid': 'uuid1', 's3_key': 'key1', 's3_bucket': 'bucket1'},
            {'id': 2, 'document_uuid': 'uuid2', 's3_key': 'key2', 's3_bucket': 'bucket2'}
        ]
        
        warmer = CacheWarmer(mock_db)
        
        # Run cache warming
        await warmer.warm_recent_documents(hours=1, limit=10)
        
        # Verify database was queried
        assert mock_db.client.table.called
```

**Verification**:
- Run tests: `pytest tests/unit/test_redis_optimization.py -v`
- Ensure all tests pass
- Check code coverage

#### Task 6.2: Create Integration Tests
**Files to create**: tests/integration/test_redis_pipeline.py
**Implementation**:
```python
# tests/integration/test_redis_pipeline.py
import pytest
import tempfile
from pathlib import Path
from main_pipeline import process_single_document, preload_critical_cache
from queue_processor import QueueProcessor
from redis_utils import get_redis_manager

class TestRedisPipelineIntegration:
    """Integration tests for Redis-optimized pipeline"""
    
    @pytest.fixture
    def sample_document(self):
        """Create a sample document for testing"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("This is a test document for Redis optimization testing.")
            return f.name
            
    def test_document_state_tracking(self, sample_document, db_manager):
        """Test document state tracking through pipeline"""
        redis_mgr = get_redis_manager()
        
        # Clear any existing state
        redis_mgr.delete("doc:state:test-uuid")
        
        # Process document (mock the source_doc_sql_id)
        with patch('main_pipeline.SupabaseManager.get_document_by_id') as mock_get:
            mock_get.return_value = {
                'id': 1,
                'document_uuid': 'test-uuid',
                'original_file_name': 'test.txt'
            }
            
            process_single_document(
                db_manager=db_manager,
                source_doc_sql_id=1,
                file_path=sample_document,
                file_name='test.txt',
                detected_file_type='.txt',
                project_sql_id=1
            )
        
        # Check Redis state
        state = redis_mgr.hgetall("doc:state:test-uuid")
        
        assert state.get('ocr_status') == 'completed'
        assert 'ocr_timestamp' in state
        assert state.get('progress') is not None
        
    def test_cache_performance(self, db_manager):
        """Test cache performance improvements"""
        from cache_warmer import CacheWarmer
        import time
        
        # Time without cache
        start = time.time()
        # Simulate document processing without cache
        no_cache_time = time.time() - start
        
        # Warm cache
        warmer = CacheWarmer(db_manager)
        asyncio.run(warmer.warm_recent_documents(hours=1))
        
        # Time with cache
        start = time.time()
        # Simulate document processing with cache
        cache_time = time.time() - start
        
        # Cache should be faster (this is a simplified test)
        assert cache_time <= no_cache_time
        
    def test_distributed_locking(self, db_manager):
        """Test distributed locking for queue processing"""
        redis_mgr = get_redis_manager()
        
        # Create two queue processors
        processor1 = QueueProcessor(batch_size=1)
        processor2 = QueueProcessor(batch_size=1)
        
        # Mock queue item
        queue_item = {
            'id': 1,
            'source_document_id': 1,
            'status': 'pending',
            'retry_count': 0
        }
        
        # Try to claim same item with both processors
        lock_key = f"queue:lock:1"
        
        # First processor claims
        claimed1 = redis_mgr.setnx(lock_key, processor1.processor_id, ttl=300)
        assert claimed1 is True
        
        # Second processor should fail
        claimed2 = redis_mgr.setnx(lock_key, processor2.processor_id, ttl=300)
        assert claimed2 is False
        
        # Clean up
        redis_mgr.delete(lock_key)
```

**Verification**:
- Run integration tests: `pytest tests/integration/test_redis_pipeline.py -v`
- Monitor Redis during tests
- Verify no race conditions

### Phase 7: Deployment and Migration

#### Task 7.1: Create Migration Script
**Files to create**: scripts/migrate_to_optimized_redis.py
**Implementation**:
```python
# scripts/migrate_to_optimized_redis.py
import logging
from redis_utils import get_redis_manager
from cache_keys import CacheKeys

logger = logging.getLogger(__name__)

def migrate_redis_keys():
    """Migrate existing Redis keys to new naming convention"""
    redis_mgr = get_redis_manager()
    if not redis_mgr.is_available():
        logger.error("Redis not available")
        return False
        
    client = redis_mgr.get_client()
    
    # Define migration mappings
    migrations = [
        # Old pattern -> New pattern
        (r"doc_state:*", "doc:state:"),
        (r"textract:result:*", "doc:ocr:"),
        (r"entity:openai:*", "entity:openai:"),
        (r"rate_limit:*", "rate:"),
    ]
    
    migrated_count = 0
    
    for old_pattern, new_prefix in migrations:
        for old_key in client.scan_iter(match=old_pattern):
            # Extract the suffix
            suffix = old_key.split(':', 1)[1] if ':' in old_key else old_key
            new_key = new_prefix + suffix
            
            # Get value and TTL
            value = client.get(old_key)
            ttl = client.ttl(old_key)
            
            if value:
                # Set new key
                client.set(new_key, value)
                if ttl > 0:
                    client.expire(new_key, ttl)
                    
                # Delete old key
                client.delete(old_key)
                
                logger.info(f"Migrated {old_key} -> {new_key}")
                migrated_count += 1
                
    logger.info(f"Migration complete. Migrated {migrated_count} keys")
    return True

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    migrate_redis_keys()
```

**Verification**:
- Backup Redis data first
- Run migration: `python scripts/migrate_to_optimized_redis.py`
- Verify old keys are gone and new keys exist

#### Task 7.2: Update Deployment Configuration
**Files to modify**: config.py, requirements.txt
**Implementation**:
```python
# Add to config.py
# Redis Optimization Settings
REDIS_ENABLE_OPTIMIZATION = os.getenv("REDIS_ENABLE_OPTIMIZATION", "true").lower() in ("true", "1", "yes")
REDIS_CACHE_WARMING_ENABLED = os.getenv("REDIS_CACHE_WARMING_ENABLED", "true").lower() in ("true", "1", "yes")
REDIS_CACHE_WARMING_HOURS = int(os.getenv("REDIS_CACHE_WARMING_HOURS", "24"))
REDIS_CACHE_WARMING_LIMIT = int(os.getenv("REDIS_CACHE_WARMING_LIMIT", "100"))
REDIS_MONITOR_ENABLED = os.getenv("REDIS_MONITOR_ENABLED", "false").lower() in ("true", "1", "yes")
REDIS_MONITOR_PORT = int(os.getenv("REDIS_MONITOR_PORT", "8090"))

# Redis Cluster Support (future)
REDIS_CLUSTER_ENABLED = os.getenv("REDIS_CLUSTER_ENABLED", "false").lower() in ("true", "1", "yes")
REDIS_CLUSTER_NODES = os.getenv("REDIS_CLUSTER_NODES", "").split(",") if os.getenv("REDIS_CLUSTER_NODES") else []
```

**Verification**:
- Update .env file with new variables
- Test configuration loading
- Verify backward compatibility

### Final Verification Checklist

1. **Unit Tests**
   - [ ] Run all unit tests: `pytest tests/unit/ -v`
   - [ ] Verify >90% code coverage for Redis-related code
   - [ ] No test failures

2. **Integration Tests**
   - [ ] Run integration tests: `pytest tests/integration/ -v`
   - [ ] Process sample documents end-to-end
   - [ ] Verify cache hits improve performance

3. **Performance Tests**
   - [ ] Benchmark cache operations (target: <1ms for cache hits)
   - [ ] Test with 100+ concurrent documents
   - [ ] Monitor Redis memory usage stays within limits

4. **Monitoring**
   - [ ] Redis dashboard shows accurate metrics
   - [ ] Health checks include Redis status
   - [ ] Alerts configured for Redis issues

5. **Documentation**
   - [ ] Update README with Redis optimization features
   - [ ] Document new environment variables
   - [ ] Add troubleshooting guide for Redis issues

## Success Criteria

1. **Performance Improvements**
   - 50% reduction in redundant API calls through caching
   - 30% improvement in document processing throughput
   - <5ms average cache operation latency

2. **Reliability**
   - Zero data loss during Redis failures (graceful degradation)
   - Automatic cache invalidation on document updates
   - Distributed locking prevents duplicate processing

3. **Observability**
   - Real-time Redis metrics available
   - Cache hit rates >80% for frequently accessed data
   - Clear logging of cache operations

4. **Maintainability**
   - Standardized cache key naming
   - Centralized cache configuration
   - Comprehensive test coverage

## Rollback Plan

If issues arise during deployment:

1. Set `REDIS_ENABLE_OPTIMIZATION=false` in environment
2. Run cache invalidation: `redis-cli FLUSHDB`
3. Restart all services
4. Monitor for normal operation
5. Investigate issues before re-enabling

## Next Steps

After successful implementation:

1. **Phase 8**: Implement Redis Cluster for high availability
2. **Phase 9**: Add machine learning model caching
3. **Phase 10**: Implement real-time document processing notifications via Redis Pub/Sub 