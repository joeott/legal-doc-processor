# Context 501: Redis Prefix-Based Separation Implementation

## Date: January 10, 2025

## Executive Summary

Due to Redis Cloud's limitation of supporting only a single database (DB 0), we need to pivot from the multi-database approach to a prefix-based separation strategy. This document details the implementation of logical separation using key prefixes while maintaining the benefits of organized data management.

## Discovery: Redis Cloud Limitation

### Test Results
- Redis Version: 7.4.2
- Mode: standalone
- Available Databases: 1 (only DB 0)
- Error when accessing DB 1+: "DB index is out of range"

This is a common limitation with managed Redis services like Redis Cloud, which often restrict database access to improve performance and simplify management.

## Revised Architecture: Prefix-Based Separation

### Key Prefix Strategy

Instead of using separate databases, we'll use consistent key prefixes to logically separate different data types:

```
broker:*      → Celery broker data
results:*     → Celery task results  
cache:*       → Application cache
batch:*       → Batch processing metadata
metrics:*     → Performance metrics
rate:*        → Rate limiting

Document-specific prefixes (remain in cache namespace):
doc:*         → Document metadata and state
chunk:*       → Document chunks
entity:*      → Entity data
ocr:*         → OCR results
```

### Benefits of Prefix Approach

1. **Compatible with Redis Cloud**: Works with single database limitation
2. **Easy Migration**: No data movement required, just key naming conventions
3. **Flexible Monitoring**: Can still track usage by prefix patterns
4. **Scalable**: Can later migrate to separate instances if needed

## Implementation Changes

### 1. Celery Configuration Update

Since Celery broker and results must share DB 0, we'll use different key prefixes:

```python
# In celery_app.py
app.conf.update(
    # Use prefix for result keys
    result_backend_transport_options={
        'master_name': 'mymaster',
        'result_key_prefix': 'results:',
    },
    # Broker will use default celery prefixes
    task_default_queue='broker:default',
    task_routes={
        'scripts.pdf_tasks.extract_text_from_document': {'queue': 'broker:ocr'},
        'scripts.pdf_tasks.chunk_document_text': {'queue': 'broker:text'},
        # ... etc
    }
)
```

### 2. Cache Key Management

Update CacheKeys class to ensure proper prefixing:

```python
class CacheKeys:
    # Document cache keys (in cache: namespace)
    DOC_STATE = "cache:doc:state:{document_uuid}"
    DOC_OCR_RESULT = "cache:doc:ocr_result:{document_uuid}"
    DOC_CHUNKS = "cache:doc:chunks:{document_uuid}"
    DOC_ALL_EXTRACTED_MENTIONS = "cache:doc:all_extracted_mentions:{document_uuid}"
    DOC_CANONICAL_ENTITIES = "cache:doc:canonical_entities:{document_uuid}"
    DOC_RESOLVED_MENTIONS = "cache:doc:resolved_mentions:{document_uuid}"
    
    # Batch processing keys
    BATCH_PROGRESS = "batch:progress:{batch_id}"
    BATCH_MANIFEST = "batch:manifest:{batch_id}"
    BATCH_STATS = "batch:stats:{batch_id}"
    
    # Metrics keys
    METRIC_PIPELINE = "metrics:pipeline:{metric_type}:{timestamp}"
    METRIC_PERFORMANCE = "metrics:performance:{component}:{timestamp}"
    
    # Rate limiting keys
    RATE_LIMIT = "rate:limit:{resource}:{identifier}"
```

### 3. RedisManager Simplification

Remove multi-database complexity and focus on prefix-based operations:

```python
class RedisManager:
    def __init__(self):
        # Single connection pool for DB 0
        self._pool = self._create_pool()
        
    def get_client(self) -> redis.Redis:
        """Get Redis client (always DB 0)."""
        return redis.Redis(connection_pool=self._pool)
    
    def get_keys_by_prefix(self, prefix: str) -> List[str]:
        """Get all keys with given prefix."""
        return list(self.get_client().scan_iter(match=f"{prefix}*"))
    
    def delete_by_prefix(self, prefix: str) -> int:
        """Delete all keys with given prefix."""
        client = self.get_client()
        keys = self.get_keys_by_prefix(prefix)
        if keys:
            return client.delete(*keys)
        return 0
```

### 4. Monitoring by Prefix

Create monitoring functions that group by prefix:

```python
def get_redis_stats_by_prefix():
    """Get key count and memory usage by prefix."""
    client = get_redis_manager().get_client()
    
    prefixes = ['broker:', 'results:', 'cache:', 'batch:', 'metrics:', 'rate:']
    stats = {}
    
    for prefix in prefixes:
        keys = list(client.scan_iter(match=f"{prefix}*", count=1000))
        
        # Sample memory usage (don't check all keys for performance)
        sample_size = min(100, len(keys))
        sample_keys = random.sample(keys, sample_size) if keys else []
        
        total_memory = 0
        for key in sample_keys:
            try:
                memory = client.memory_usage(key)
                total_memory += memory if memory else 0
            except:
                pass
        
        avg_memory = total_memory / sample_size if sample_size > 0 else 0
        estimated_total = avg_memory * len(keys)
        
        stats[prefix.rstrip(':')] = {
            'count': len(keys),
            'estimated_memory_mb': estimated_total / (1024 * 1024)
        }
    
    return stats
```

## Migration Strategy

Since we're staying in DB 0, migration is simpler:

1. **Update Key Generation**: Ensure all new keys use proper prefixes
2. **Gradual Migration**: Update existing keys as they're accessed
3. **Backward Compatibility**: Support both old and new key formats temporarily

### Migration Helper

```python
def migrate_key_to_prefix(old_key: str) -> str:
    """Convert old key format to new prefixed format."""
    # Document keys
    if old_key.startswith('doc:'):
        return f"cache:{old_key}"
    elif old_key.startswith('chunk:'):
        return f"cache:{old_key}"
    elif old_key.startswith('entity:'):
        return f"cache:{old_key}"
    
    # Batch keys
    elif old_key.startswith('batch:'):
        return old_key  # Already prefixed
    
    # Celery keys
    elif old_key.startswith('celery-task-meta-'):
        return f"results:{old_key}"
    
    # Default to cache namespace
    return f"cache:{old_key}"
```

## Performance Considerations

### Advantages
1. **Single Connection Pool**: Less overhead than multiple pools
2. **No Cross-Database Latency**: All operations in same database
3. **Simpler Configuration**: No database routing logic needed

### Potential Issues
1. **Key Scanning**: SCAN operations will see all keys
   - Mitigation: Always use prefix patterns in SCAN
2. **Memory Limits**: All data shares same memory pool
   - Mitigation: Implement aggressive TTLs and eviction policies
3. **Backup Complexity**: Cannot backup by data type
   - Mitigation: Use prefix-based export scripts

## Implementation Steps

1. **Update CacheKeys class** with proper prefixes
2. **Simplify RedisManager** to remove multi-database logic
3. **Update Celery configuration** for prefix-based queues
4. **Create monitoring utilities** for prefix-based stats
5. **Test prefix isolation** and performance
6. **Deploy with backward compatibility**

## Success Metrics

1. **Logical Separation**: Clear prefix boundaries
2. **Performance**: No degradation from current setup
3. **Monitoring**: Visibility into usage by prefix
4. **Compatibility**: Works with Redis Cloud limitations

## Conclusion

While the multi-database approach would have been ideal, the prefix-based separation provides most of the same benefits while working within Redis Cloud's constraints. This approach maintains logical separation, enables targeted monitoring, and provides a migration path to true database separation if we move to self-hosted Redis in the future.