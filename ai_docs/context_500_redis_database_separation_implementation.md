# Context 500: Redis Database Separation Implementation

## Date: January 10, 2025

## Executive Summary

This document details the implementation of Redis database separation to optimize the legal document processing pipeline for batch processing. The implementation follows the architectural recommendations from context_495 and addresses the gaps identified in the current single-database approach.

## Current State Analysis

### Existing Redis Configuration
- **Single Database**: Currently using Redis DB 0 for everything (broker, results, cache, state)
- **Connection**: Redis Cloud endpoint with SSL disabled
- **Max Connections**: 50 concurrent connections
- **Memory Management**: 1GB default with allkeys-lru eviction policy

### Issues with Single Database Approach
1. **Resource Contention**: Celery broker/backend operations compete with application cache
2. **Memory Pressure**: All data types share same memory pool and eviction policy
3. **Monitoring Complexity**: Difficult to track usage patterns by function
4. **Backup/Recovery**: Cannot backup/restore specific data types independently

## Proposed Multi-Database Architecture

### Database Allocation
```python
# Redis Database Assignments
REDIS_DB_BROKER = 0      # Celery task broker (existing)
REDIS_DB_RESULTS = 1     # Celery results backend
REDIS_DB_CACHE = 2       # Application cache (document data)
REDIS_DB_RATE_LIMIT = 3  # Rate limiting and counters
REDIS_DB_BATCH = 4       # Batch processing metadata
REDIS_DB_METRICS = 5     # Performance metrics and monitoring
```

### Benefits of Separation
1. **Performance Isolation**: Each function gets dedicated resources
2. **Targeted Optimization**: Different eviction policies per database
3. **Clear Data Lifecycle**: Separate TTLs and persistence strategies
4. **Scalability**: Can move databases to separate Redis instances later

## Implementation Plan

### Phase 1: Configuration Updates

#### 1.1 Update config.py
```python
# Add database configuration constants
REDIS_DB_BROKER = int(os.getenv("REDIS_DB_BROKER", "0"))
REDIS_DB_RESULTS = int(os.getenv("REDIS_DB_RESULTS", "1"))
REDIS_DB_CACHE = int(os.getenv("REDIS_DB_CACHE", "2"))
REDIS_DB_RATE_LIMIT = int(os.getenv("REDIS_DB_RATE_LIMIT", "3"))
REDIS_DB_BATCH = int(os.getenv("REDIS_DB_BATCH", "4"))
REDIS_DB_METRICS = int(os.getenv("REDIS_DB_METRICS", "5"))

# Create function to build database-specific configs
def get_redis_db_config(db_num: int) -> dict:
    """Get Redis configuration for specific database."""
    config = REDIS_CONFIG.copy()
    config['db'] = db_num
    return config
```

#### 1.2 Update celery_app.py
```python
# Update Celery configuration to use separate databases
app.config_from_object({
    'broker_url': f'redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB_BROKER}',
    'result_backend': f'redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB_RESULTS}',
    # ... rest of config
})
```

### Phase 2: Cache Manager Updates

#### 2.1 Create Multi-Database Redis Manager
```python
class MultiDatabaseRedisManager:
    """Redis manager with support for multiple databases."""
    
    def __init__(self):
        self._pools = {}
        self._initialize_pools()
    
    def _initialize_pools(self):
        """Initialize connection pools for each database."""
        databases = {
            'cache': REDIS_DB_CACHE,
            'batch': REDIS_DB_BATCH,
            'metrics': REDIS_DB_METRICS,
            'rate_limit': REDIS_DB_RATE_LIMIT
        }
        
        for name, db_num in databases.items():
            pool_params = {
                'host': REDIS_HOST,
                'port': REDIS_PORT,
                'db': db_num,
                'password': REDIS_PASSWORD,
                'decode_responses': True,
                'max_connections': REDIS_MAX_CONNECTIONS // len(databases),
                'socket_keepalive': True,
                'socket_keepalive_options': REDIS_SOCKET_KEEPALIVE_OPTIONS,
            }
            self._pools[name] = redis.ConnectionPool(**pool_params)
    
    def get_client(self, database: str = 'cache') -> redis.Redis:
        """Get Redis client for specific database."""
        if database not in self._pools:
            raise ValueError(f"Unknown database: {database}")
        return redis.Redis(connection_pool=self._pools[database])
```

### Phase 3: Migration Strategy

#### 3.1 Data Migration Script
```python
def migrate_redis_data():
    """Migrate existing data from DB 0 to appropriate databases."""
    source_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, 
                               db=0, password=REDIS_PASSWORD)
    
    # Define key patterns and target databases
    migrations = {
        'doc:*': REDIS_DB_CACHE,
        'chunk:*': REDIS_DB_CACHE,
        'entity:*': REDIS_DB_CACHE,
        'batch:*': REDIS_DB_BATCH,
        'metrics:*': REDIS_DB_METRICS,
        'rate:*': REDIS_DB_RATE_LIMIT,
    }
    
    for pattern, target_db in migrations.items():
        target_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT,
                                   db=target_db, password=REDIS_PASSWORD)
        
        # Scan and migrate keys
        for key in source_client.scan_iter(match=pattern, count=100):
            # Get value with TTL
            value = source_client.get(key)
            ttl = source_client.ttl(key)
            
            # Set in target database
            if ttl > 0:
                target_client.setex(key, ttl, value)
            else:
                target_client.set(key, value)
            
            # Delete from source (optional, after verification)
            # source_client.delete(key)
```

### Phase 4: Application Updates

#### 4.1 Update cache.py Methods
```python
class RedisManager:
    def __init__(self):
        # Initialize with multi-database support
        self._cache_pool = self._create_pool(REDIS_DB_CACHE)
        self._batch_pool = self._create_pool(REDIS_DB_BATCH)
        self._metrics_pool = self._create_pool(REDIS_DB_METRICS)
        
    def get_cache_client(self) -> redis.Redis:
        """Get client for cache database."""
        return redis.Redis(connection_pool=self._cache_pool)
    
    def get_batch_client(self) -> redis.Redis:
        """Get client for batch database."""
        return redis.Redis(connection_pool=self._batch_pool)
```

#### 4.2 Update Batch Processing
```python
# In batch_processor.py
def get_batch_redis_client():
    """Get Redis client for batch processing database."""
    redis_manager = get_redis_manager()
    return redis_manager.get_batch_client()

def track_batch_progress(batch_id: str, progress_data: dict):
    """Track batch progress in dedicated database."""
    client = get_batch_redis_client()
    key = f"batch:progress:{batch_id}"
    client.hset(key, mapping=progress_data)
```

### Phase 5: Monitoring Updates

#### 5.1 Update Monitor to Show Database Stats
```python
def get_redis_database_stats():
    """Get statistics for each Redis database."""
    stats = {}
    databases = {
        'broker': REDIS_DB_BROKER,
        'results': REDIS_DB_RESULTS,
        'cache': REDIS_DB_CACHE,
        'batch': REDIS_DB_BATCH,
        'metrics': REDIS_DB_METRICS
    }
    
    for name, db_num in databases.items():
        client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT,
                           db=db_num, password=REDIS_PASSWORD)
        info = client.info('keyspace')
        db_key = f'db{db_num}'
        
        if db_key in info:
            stats[name] = {
                'keys': info[db_key]['keys'],
                'expires': info[db_key]['expires'],
                'avg_ttl': info[db_key].get('avg_ttl', 0)
            }
        else:
            stats[name] = {'keys': 0, 'expires': 0, 'avg_ttl': 0}
    
    return stats
```

## Testing Strategy

### 1. Unit Tests
```python
def test_multi_database_isolation():
    """Test that data is isolated between databases."""
    cache_client = get_redis_manager().get_cache_client()
    batch_client = get_redis_manager().get_batch_client()
    
    # Set in cache database
    cache_client.set('test_key', 'cache_value')
    
    # Verify not accessible from batch database
    assert batch_client.get('test_key') is None
    
    # Cleanup
    cache_client.delete('test_key')
```

### 2. Integration Tests
- Test Celery broker/backend separation
- Verify cache operations use correct database
- Ensure batch tracking uses dedicated database

### 3. Performance Tests
- Measure latency improvement with separation
- Test concurrent operations across databases
- Verify memory usage patterns

## Rollback Plan

If issues arise:
1. Update configuration to point all databases back to DB 0
2. No data migration needed (data remains accessible)
3. Monitor for any connection pool issues
4. Document any performance degradation

## Success Metrics

1. **Performance**:
   - 20% reduction in cache operation latency
   - 30% improvement in batch processing throughput
   - Reduced memory pressure on broker database

2. **Operational**:
   - Clear separation of concerns
   - Independent monitoring per function
   - Simplified debugging and troubleshooting

3. **Scalability**:
   - Ability to scale databases independently
   - Support for 1000+ document batches
   - Linear performance scaling with Redis resources

## Implementation Timeline

1. **Hour 1**: Configuration updates and testing
2. **Hour 2**: Cache manager modifications
3. **Hour 3**: Data migration and verification
4. **Hour 4**: Application updates and testing
5. **Hour 5**: Monitoring integration
6. **Hour 6**: Performance validation

## Risk Assessment

### Low Risk
- Configuration changes are reversible
- No data loss risk (migration is additive)
- Existing functionality preserved

### Medium Risk
- Connection pool exhaustion if not properly managed
- Temporary performance impact during migration

### Mitigation
- Implement gradual rollout
- Monitor connection pool usage
- Have rollback plan ready

## Next Steps

1. Implement configuration changes
2. Update cache manager for multi-database support
3. Create migration script
4. Test in development environment
5. Deploy to production with monitoring
6. Document operational procedures

This implementation provides a robust foundation for batch processing optimization while maintaining system stability and performance.