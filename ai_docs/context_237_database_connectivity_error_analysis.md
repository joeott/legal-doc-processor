# Context 237: Database Connectivity Error Analysis and Solutions

## Executive Summary

We are experiencing critical database connectivity issues that prevent our production scripts from accessing the RDS PostgreSQL instance. The primary failure modes include SSH tunnel instability, authentication errors, and connection timeouts. This document analyzes the precise nature of these errors, their impact on production scripts, and proposes solutions with particular emphasis on leveraging Redis as an intermediary layer.

## 1. Precise Nature of Database Connectivity Errors

### 1.1 Primary Error Patterns

#### SSH Tunnel Failure Pattern
```python
# From scripts/db.py - get_engine()
def get_engine():
    """Get or create the SQLAlchemy engine with connection pooling."""
    global _engine
    if _engine is None:
        database_url = os.getenv('DATABASE_URL')
        # When using localhost:5433, SSH tunnel dies during operation
        # Error: psycopg2.OperationalError: server closed the connection unexpectedly
```

#### Direct Connection Timeout
```python
# When DATABASE_URL points directly to RDS endpoint
# Error: timeout expired (psycopg2.OperationalError)
# This occurs because RDS is not publicly accessible
```

#### Authentication Failure Through Tunnel
```python
# When tunnel is active but authentication fails
# Error: FATAL: password authentication failed for user "ottlaw_admin"
# Despite credentials being correct when used directly via psql
```

### 1.2 Root Cause Analysis

The errors stem from a fundamental architectural mismatch:

1. **Network Architecture**: RDS is configured for private subnet access only
2. **SSH Tunnel Instability**: The SSH tunnel through the bastion host is fragile and dies under load
3. **Connection Pool Conflicts**: SQLAlchemy's connection pooling doesn't play well with SSH tunnels
4. **Async Operation Issues**: Celery workers create concurrent connections that overwhelm the tunnel

## 2. Impact on Production Scripts

### 2.1 PDF Processing Pipeline Impact

```python
# From scripts/pdf_tasks.py
@celery_app.task(bind=True, name='pdf_tasks.process_pdf_document')
def process_pdf_document(self, document_data: Dict[str, Any]) -> Dict[str, Any]:
    try:
        # This fails at database initialization
        session = Session()  # <-- Connection timeout here
        
        # Cannot create or update document records
        pdf_doc = PDFDocument(
            document_uuid=document_data.get('document_uuid'),
            filename=document_data.get('filename'),
            status='processing'
        )
        session.add(pdf_doc)  # <-- Never reaches this point
        session.commit()
```

### 2.2 Entity Service Impact

```python
# From scripts/entity_service.py
class EntityService:
    def __init__(self):
        self.engine = get_engine()  # <-- Fails here
        self.Session = sessionmaker(bind=self.engine)
    
    def extract_entities(self, document_uuid: str, chunks: List[ProcessedChunk]) -> Dict[str, Any]:
        # Cannot store extracted entities
        with self.Session() as session:
            # All database operations fail
            for entity_data in entities:
                entity = Entity(
                    entity_uuid=str(uuid.uuid4()),
                    document_uuid=document_uuid,
                    # ... entity data
                )
                session.add(entity)  # <-- Connection lost
```

### 2.3 Cache Service Impact

```python
# From scripts/cache.py
class CacheService:
    def get_with_fallback(self, key: str, fallback_fn: Callable, ttl: int = 3600):
        # Try cache first
        cached = self.get(key)
        if cached:
            return cached
        
        # Fallback to database - THIS FAILS
        try:
            result = fallback_fn()  # <-- Database query fails here
            self.set(key, result, ttl)
            return result
        except Exception as e:
            logger.error(f"Fallback function failed: {e}")
            return None
```

### 2.4 Celery Worker Impact

```python
# From scripts/celery_app.py
# Workers cannot:
# 1. Update task status in database
# 2. Store processing results
# 3. Retrieve document metadata
# 4. Create relationships between entities
```

## 3. Proposed Solutions

### 3.1 Solution 1: Redis as Primary Data Store with Async Database Sync

**Architecture Overview:**
```
Scripts → Redis (Primary) → Background Sync → RDS (Persistent)
```

**Implementation:**

```python
# New: scripts/database/redis_db_sync.py
import redis
import json
from typing import Dict, Any, List
from datetime import datetime
import asyncio
from sqlalchemy.orm import Session

class RedisDatabaseSync:
    """Synchronizes Redis cache with PostgreSQL database."""
    
    def __init__(self):
        self.redis_client = redis.Redis(
            host=os.getenv('REDIS_HOST'),
            port=int(os.getenv('REDIS_PORT')),
            password=os.getenv('REDIS_PASSWORD'),
            decode_responses=True,
            socket_keepalive=True,
            health_check_interval=30
        )
        self.sync_queue = "db:sync:queue"
        self.sync_lock = "db:sync:lock"
        
    def write_to_redis_with_sync(self, table: str, record: Dict[str, Any]):
        """Write to Redis and queue for database sync."""
        # Generate Redis key
        key = f"db:{table}:{record.get('id') or record.get('uuid')}"
        
        # Store in Redis
        self.redis_client.hset(key, mapping={
            k: json.dumps(v) if isinstance(v, (dict, list)) else str(v)
            for k, v in record.items()
        })
        
        # Queue for sync
        sync_record = {
            'table': table,
            'key': key,
            'operation': 'upsert',
            'timestamp': datetime.utcnow().isoformat()
        }
        self.redis_client.lpush(self.sync_queue, json.dumps(sync_record))
        
    async def sync_worker(self):
        """Background worker that syncs Redis to PostgreSQL."""
        while True:
            try:
                # Get lock to prevent multiple sync workers
                if not self.redis_client.set(self.sync_lock, "1", nx=True, ex=60):
                    await asyncio.sleep(5)
                    continue
                
                # Process sync queue
                batch = []
                for _ in range(100):  # Process in batches
                    item = self.redis_client.rpop(self.sync_queue)
                    if not item:
                        break
                    batch.append(json.loads(item))
                
                if batch:
                    await self._sync_batch_to_db(batch)
                    
            except Exception as e:
                logger.error(f"Sync worker error: {e}")
            finally:
                self.redis_client.delete(self.sync_lock)
                await asyncio.sleep(1)
```

**Modified PDF Tasks Integration:**

```python
# Modified scripts/pdf_tasks.py
@celery_app.task(bind=True, name='pdf_tasks.process_pdf_document')
def process_pdf_document(self, document_data: Dict[str, Any]) -> Dict[str, Any]:
    redis_sync = RedisDatabaseSync()
    
    try:
        # Write to Redis instead of database
        pdf_doc = {
            'document_uuid': document_data.get('document_uuid'),
            'filename': document_data.get('filename'),
            'status': 'processing',
            'created_at': datetime.utcnow().isoformat()
        }
        
        # Store in Redis with sync queue
        redis_sync.write_to_redis_with_sync('source_documents', pdf_doc)
        
        # Continue processing...
        # All data operations go through Redis
```

### 3.2 Solution 2: Redis-Based Connection Pool Manager

**Concept:** Use Redis to manage and distribute database connections across workers.

```python
# New: scripts/database/redis_connection_pool.py
class RedisConnectionPoolManager:
    """Manages database connections through Redis coordination."""
    
    def __init__(self):
        self.redis_client = get_redis_client()
        self.pool_key = "db:connection:pool"
        self.max_connections = 10
        
    def acquire_connection(self, worker_id: str, timeout: int = 30):
        """Acquire a connection slot from the pool."""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            # Try to acquire a slot
            current_count = self.redis_client.hlen(self.pool_key)
            
            if current_count < self.max_connections:
                # Reserve a slot
                self.redis_client.hset(
                    self.pool_key, 
                    worker_id, 
                    json.dumps({
                        'acquired_at': datetime.utcnow().isoformat(),
                        'pid': os.getpid()
                    })
                )
                return True
                
            time.sleep(0.5)
        
        return False
        
    def release_connection(self, worker_id: str):
        """Release a connection back to the pool."""
        self.redis_client.hdel(self.pool_key, worker_id)
```

### 3.3 Solution 3: Redis-Cached Database Proxy

**Architecture:** Create a caching proxy layer that intercepts all database operations.

```python
# New: scripts/database/cached_db_proxy.py
class CachedDatabaseProxy:
    """Proxy all database operations through Redis cache."""
    
    def __init__(self):
        self.cache = CacheService()
        self.sync_service = RedisDatabaseSync()
        
    def query(self, model_class, filters: Dict[str, Any]):
        """Query with Redis cache fallback."""
        # Generate cache key from query
        cache_key = self._generate_query_key(model_class, filters)
        
        # Try cache first
        cached_result = self.cache.get(cache_key)
        if cached_result:
            return cached_result
            
        # Try Redis data store
        redis_result = self._query_redis_store(model_class, filters)
        if redis_result:
            self.cache.set(cache_key, redis_result, ttl=300)
            return redis_result
            
        # Last resort: try database (may fail)
        try:
            db_result = self._query_database(model_class, filters)
            if db_result:
                # Cache and store in Redis
                self.cache.set(cache_key, db_result, ttl=300)
                self._store_in_redis(model_class, db_result)
            return db_result
        except Exception as e:
            logger.error(f"Database query failed: {e}")
            return None
```

### 3.4 Solution 4: Event-Driven Architecture with Redis Streams

**Concept:** Decouple script operations from direct database access using Redis Streams.

```python
# New: scripts/database/redis_event_stream.py
class RedisEventStream:
    """Event-driven database operations using Redis Streams."""
    
    def __init__(self):
        self.redis_client = get_redis_client()
        self.stream_key = "db:events"
        
    def publish_event(self, event_type: str, data: Dict[str, Any]):
        """Publish a database event to Redis Stream."""
        event = {
            'type': event_type,
            'data': json.dumps(data),
            'timestamp': datetime.utcnow().isoformat(),
            'source': os.getenv('WORKER_NAME', 'unknown')
        }
        
        self.redis_client.xadd(self.stream_key, event)
        
    def consume_events(self, consumer_group: str, consumer_name: str):
        """Consume events and apply to database."""
        while True:
            try:
                # Read from stream
                messages = self.redis_client.xreadgroup(
                    consumer_group,
                    consumer_name,
                    {self.stream_key: '>'},
                    block=1000,
                    count=10
                )
                
                for stream, stream_messages in messages:
                    for message_id, data in stream_messages:
                        self._process_event(data)
                        # Acknowledge message
                        self.redis_client.xack(self.stream_key, consumer_group, message_id)
                        
            except Exception as e:
                logger.error(f"Event consumer error: {e}")
```

## 4. Recommended Implementation Strategy

### Phase 1: Immediate Relief (1-2 days)
1. Implement Redis-based connection pool manager (Solution 3.2)
2. Add retry logic with exponential backoff to all database operations
3. Create health check endpoint that monitors SSH tunnel status

### Phase 2: Redis Data Layer (3-5 days)
1. Implement Redis as primary data store (Solution 3.1)
2. Create background sync workers for eventual consistency
3. Modify scripts to write to Redis first, database second

### Phase 3: Full Decoupling (1 week)
1. Implement event-driven architecture (Solution 3.4)
2. Create Redis Streams for all database operations
3. Deploy dedicated sync workers that handle database writes

### Phase 4: Long-term Solution
1. Consider AWS RDS Proxy for connection pooling
2. Evaluate AWS PrivateLink for direct VPC connectivity
3. Implement circuit breakers for database operations

## 5. Implementation Priority

Based on the analysis, the recommended priority is:

1. **Immediate**: Implement Redis-based write buffering
2. **Short-term**: Deploy Redis connection pool manager
3. **Medium-term**: Full Redis data layer with async sync
4. **Long-term**: Event-driven architecture with Redis Streams

## 6. Code Changes Required

### 6.1 Modify base database operations

```python
# Update scripts/db.py
from scripts.database.redis_db_sync import RedisDatabaseSync
from scripts.database.cached_db_proxy import CachedDatabaseProxy

# Replace direct database access
_cached_proxy = None

def get_cached_db():
    """Get cached database proxy instead of direct connection."""
    global _cached_proxy
    if _cached_proxy is None:
        _cached_proxy = CachedDatabaseProxy()
    return _cached_proxy
```

### 6.2 Update all model operations

```python
# Example: Update scripts/pdf_tasks.py
def save_document(doc_data: Dict[str, Any]):
    # Old way (direct database)
    # session.add(PDFDocument(**doc_data))
    # session.commit()
    
    # New way (through Redis)
    cached_db = get_cached_db()
    cached_db.save('source_documents', doc_data)
```

## Conclusion

The database connectivity issues are severely impacting our production pipeline. The SSH tunnel approach is fundamentally incompatible with our high-concurrency Celery architecture. By leveraging Redis as an intermediary layer, we can:

1. Eliminate direct database dependencies in critical paths
2. Provide resilience against connection failures
3. Improve overall system performance
4. Enable gradual migration to more stable connectivity solutions

The proposed Redis-based solutions offer both immediate relief and a path to long-term architectural improvements.