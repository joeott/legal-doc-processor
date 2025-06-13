"""
Unified caching module for the PDF processing pipeline.
Combines Redis operations, cache keys, models, and high-level cache management.
"""

import redis
import json
import hashlib
import pickle
import time
import uuid
import logging
import threading
import numpy as np
from typing import Any, Optional, Union, Dict, List, Callable, Tuple, Type
from functools import wraps
from contextlib import contextmanager
from datetime import datetime, timedelta
from enum import Enum

from pydantic import BaseModel, Field, field_validator, ConfigDict, ValidationInfo, ValidationError

# Import configuration
from scripts.config import (
    REDIS_HOST, REDIS_PORT, REDIS_PASSWORD, REDIS_DB,
    REDIS_DB_CACHE, REDIS_DB_BATCH, REDIS_DB_METRICS, REDIS_DB_RATE_LIMIT,
    USE_REDIS_CACHE, REDIS_MAX_CONNECTIONS, REDIS_USERNAME, REDIS_SSL,
    REDIS_SOCKET_KEEPALIVE, REDIS_SOCKET_KEEPALIVE_OPTIONS, REDIS_DECODE_RESPONSES,
    REDIS_CONFIG, REDIS_LOCK_TIMEOUT, REDIS_OCR_CACHE_TTL, REDIS_LLM_CACHE_TTL,
    REDIS_ENTITY_CACHE_TTL, REDIS_STRUCTURED_CACHE_TTL, REDIS_CHUNK_CACHE_TTL,
    get_redis_db_config
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)  # Enable debug for cache operations


# ========== Cache Keys ==========

class CacheKeys:
    """Centralized cache key definitions and templates with Redis Cloud prefix support."""
    
    # Import prefixes from config
    from scripts.config import REDIS_PREFIX_CACHE, REDIS_PREFIX_BATCH, REDIS_PREFIX_METRICS, REDIS_PREFIX_RATE
    
    # Document processing keys (all in cache namespace for Redis Cloud compatibility)
    DOC_STATE = f"{REDIS_PREFIX_CACHE}doc:state:{{document_uuid}}"
    DOC_OCR_RESULT = f"{REDIS_PREFIX_CACHE}doc:ocr:{{document_uuid}}"
    DOC_ENTITIES = f"{REDIS_PREFIX_CACHE}doc:entities:{{document_uuid}}:{{chunk_id}}"
    DOC_STRUCTURED = f"{REDIS_PREFIX_CACHE}doc:structured:{{document_uuid}}:{{chunk_id}}"
    DOC_CHUNKS = f"{REDIS_PREFIX_CACHE}doc:chunks:{{document_uuid}}"
    DOC_PROCESSING_LOCK = f"{REDIS_PREFIX_CACHE}doc:lock:{{document_uuid}}"
    
    # Enhanced Redis optimization keys
    DOC_CHUNKS_LIST = "doc:chunks_list:{document_uuid}"
    DOC_CHUNK_TEXT = "doc:chunk_text:{chunk_uuid}"
    DOC_ALL_EXTRACTED_MENTIONS = "doc:all_mentions:{document_uuid}"
    DOC_ENTITY_MENTIONS = "doc:entity_mentions:{document_uuid}"  # Added for compatibility
    DOC_CANONICAL_ENTITIES = "doc:canonical_entities:{document_uuid}"
    DOC_RESOLVED_MENTIONS = "doc:resolved_mentions:{document_uuid}"
    DOC_CLEANED_TEXT = "doc:cleaned_text:{document_uuid}"
    
    # Vector embedding cache keys
    EMB_CHUNK = "emb:chunk:{chunk_id}:v{version}"
    EMB_DOC_CHUNKS = "emb:doc:{document_uuid}:chunks:v{version}"
    EMB_DOC_MEAN = "emb:doc:{document_uuid}:mean:v{version}"
    EMB_SIMILARITY_CACHE = "emb:sim:{chunk_id1}:{chunk_id2}"
    EMB_ENTITY_VECTOR = "emb:entity:{entity_id}:v{version}"
    
    # Job tracking keys
    TEXTRACT_JOB_STATUS = "job:textract:status:{job_id}"
    TEXTRACT_JOB_RESULT = "job:textract:result:{document_uuid}"
    TEXTRACT_JOB_LOCK = "job:textract:lock:{job_id}"
    
    # Queue management keys
    QUEUE_LOCK = "queue:lock:{queue_id}"
    QUEUE_PROCESSOR = "queue:processor:{processor_id}"
    QUEUE_BATCH_LOCK = "queue:batch:lock:{batch_id}"
    
    # Rate limiting keys
    RATE_LIMIT_OPENAI = "rate:openai:{function_name}"
    RATE_LIMIT_TEXTRACT = "rate:textract:{operation}"
    RATE_LIMIT_MISTRAL = "rate:mistral:{endpoint}"
    RATE_LIMIT_GLOBAL = "rate:global:{service}"
    
    # Idempotency keys
    IDEMPOTENT_OCR = "idempotent:ocr:{document_uuid}"
    IDEMPOTENT_CHUNK = "idempotent:chunk:{document_uuid}"
    IDEMPOTENT_ENTITY = "idempotent:entity:{document_uuid}:{chunk_id}"
    
    # Task status keys (Celery)
    TASK_STATUS = "task:status:{task_id}"
    TASK_RESULT = "task:result:{task_id}"
    TASK_LOCK = "task:lock:{task_id}"
    
    # Cache invalidation sets
    INVALIDATION_DOC = "invalidate:doc:{document_uuid}"
    INVALIDATION_PROJECT = "invalidate:project:{project_id}"
    
    @staticmethod
    def format_key(template: str, **kwargs) -> str:
        """Format a cache key template with provided values."""
        try:
            return template.format(**kwargs)
        except KeyError as e:
            logger.error(f"Missing key parameter for template {template}: {e}")
            raise
    
    @staticmethod
    def get_cache_type_from_key(key: str) -> str:
        """Extract cache type from key for metrics."""
        if key.startswith("doc:ocr:"):
            return "ocr"
        elif key.startswith("doc:entities:"):
            return "entities"
        elif key.startswith("doc:chunks"):
            return "chunks"
        elif key.startswith("doc:structured:"):
            return "structured"
        elif key.startswith("emb:"):
            return "embeddings"
        elif key.startswith("task:"):
            return "task"
        elif key.startswith("rate:"):
            return "rate_limit"
        elif key.startswith("job:"):
            return "job"
        else:
            return "other"


# ========== Cache Models ==========

class CacheStatus(str, Enum):
    """Cache entry status"""
    VALID = "valid"
    EXPIRED = "expired"
    STALE = "stale"
    INVALID = "invalid"


class CacheMetadataModel(BaseModel):
    """Metadata for cached entries"""
    cache_key: str = Field(..., description="Redis cache key")
    cached_at: datetime = Field(default_factory=datetime.now)
    expires_at: Optional[datetime] = Field(None)
    ttl_seconds: Optional[int] = Field(None)
    version: str = Field("1.0", description="Cache schema version")
    source: str = Field(..., description="Source system/process")
    tags: List[str] = Field(default_factory=list, description="Cache tags for invalidation")
    hit_count: int = Field(0, description="Number of cache hits")
    last_accessed: datetime = Field(default_factory=datetime.now)
    
    model_config = ConfigDict(
        json_encoders={
            datetime: lambda v: v.isoformat(),
            uuid.UUID: lambda v: str(v)
        }
    )
    
    @field_validator('expires_at', mode='after')
    @classmethod
    def set_expiration(cls, v, info: ValidationInfo):
        """Set expiration time based on TTL"""
        if v is None and 'ttl_seconds' in info.data and info.data['ttl_seconds']:
            cached_at = info.data.get('cached_at', datetime.now())
            return cached_at + timedelta(seconds=info.data['ttl_seconds'])
        return v
    
    @property
    def is_expired(self) -> bool:
        """Check if cache entry is expired"""
        if self.expires_at is None:
            return False
        return datetime.now() > self.expires_at
    
    @property
    def status(self) -> CacheStatus:
        """Get current cache status"""
        if self.is_expired:
            return CacheStatus.EXPIRED
        return CacheStatus.VALID
    
    def update_access(self):
        """Update last accessed time and hit count"""
        self.last_accessed = datetime.now()
        self.hit_count += 1


class BaseCacheModel(BaseModel):
    """Base model for all cacheable data with metadata"""
    metadata: CacheMetadataModel = Field(..., description="Cache metadata")
    
    model_config = ConfigDict(
        json_encoders={
            datetime: lambda v: v.isoformat(),
            uuid.UUID: lambda v: str(v)
        }
    )
    
    def is_valid(self) -> bool:
        """Check if cache entry is valid"""
        return self.metadata.status == CacheStatus.VALID
    
    def refresh_ttl(self, ttl_seconds: int):
        """Refresh TTL for this cache entry"""
        self.metadata.expires_at = datetime.now() + timedelta(seconds=ttl_seconds)


# ========== Cache Metrics ==========

class CacheMetrics:
    """Track cache performance metrics."""
    
    def __init__(self, redis_manager):
        self.redis = redis_manager
        self.metrics_key = "cache:metrics"
        self.window_size = 3600  # 1 hour window
        
    def record_hit(self, cache_type: str):
        """Record a cache hit."""
        timestamp = int(time.time())
        key = f"{self.metrics_key}:hits:{cache_type}:{timestamp // 60}"
        try:
            client = self.redis.get_client()
            client.incr(key)
            client.expire(key, self.window_size)
        except Exception as e:
            logger.debug(f"Failed to record cache hit: {e}")
    
    def record_miss(self, cache_type: str):
        """Record a cache miss."""
        timestamp = int(time.time())
        key = f"{self.metrics_key}:misses:{cache_type}:{timestamp // 60}"
        try:
            client = self.redis.get_client()
            client.incr(key)
            client.expire(key, self.window_size)
        except Exception as e:
            logger.debug(f"Failed to record cache miss: {e}")
    
    def record_set(self, cache_type: str):
        """Record a cache set operation."""
        timestamp = int(time.time())
        key = f"{self.metrics_key}:sets:{cache_type}:{timestamp // 60}"
        try:
            client = self.redis.get_client()
            client.incr(key)
            client.expire(key, self.window_size)
        except Exception as e:
            logger.debug(f"Failed to record cache set: {e}")
    
    def get_metrics(self, cache_type: Optional[str] = None) -> Dict[str, Any]:
        """Get cache metrics for the last hour."""
        try:
            client = self.redis.get_client()
            current_minute = int(time.time()) // 60
            
            metrics = {
                "hits": 0,
                "misses": 0,
                "sets": 0,
                "hit_rate": 0.0
            }
            
            # Aggregate metrics for the last hour
            for i in range(60):
                minute = current_minute - i
                
                if cache_type:
                    hits_key = f"{self.metrics_key}:hits:{cache_type}:{minute}"
                    misses_key = f"{self.metrics_key}:misses:{cache_type}:{minute}"
                    sets_key = f"{self.metrics_key}:sets:{cache_type}:{minute}"
                    
                    metrics["hits"] += int(client.get(hits_key) or 0)
                    metrics["misses"] += int(client.get(misses_key) or 0)
                    metrics["sets"] += int(client.get(sets_key) or 0)
            
            # Calculate hit rate
            total_requests = metrics["hits"] + metrics["misses"]
            if total_requests > 0:
                metrics["hit_rate"] = metrics["hits"] / total_requests
            
            return metrics
            
        except Exception as e:
            logger.error(f"Failed to get cache metrics: {e}")
            return {"error": str(e)}


# ========== Redis Manager ==========

class RedisManager:
    """
    Manages Redis connections and provides utility methods.
    Supports multiple databases for different purposes:
    - cache: Application cache (documents, chunks, entities)
    - batch: Batch processing metadata
    - metrics: Performance metrics
    - rate_limit: Rate limiting
    """
    
    _instance = None
    _pool = None  # Legacy single pool for backward compatibility
    _pools = {}   # New multi-database pools
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(RedisManager, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        """Initialize Redis connection pool."""
        # Initialize circuit breaker attributes
        self._redis_failures = 0
        self._redis_disabled_until = None
        
        if self._pool is None and USE_REDIS_CACHE:
            try:
                # Build connection parameters from REDIS_CONFIG
                pool_params = {
                    'host': REDIS_CONFIG.get('host', REDIS_HOST),
                    'port': REDIS_CONFIG.get('port', REDIS_PORT),
                    'db': REDIS_DB,
                    'password': REDIS_PASSWORD,
                    'decode_responses': REDIS_DECODE_RESPONSES,
                    'max_connections': REDIS_MAX_CONNECTIONS,
                    'socket_keepalive': REDIS_SOCKET_KEEPALIVE,
                    'socket_keepalive_options': REDIS_SOCKET_KEEPALIVE_OPTIONS,
                }
                
                # Add username if provided (Redis Cloud)
                if REDIS_USERNAME:
                    pool_params['username'] = REDIS_USERNAME
                
                # Add SSL parameters if configured
                if REDIS_CONFIG.get('ssl', REDIS_SSL):
                    pool_params['connection_class'] = redis.SSLConnection
                    pool_params['ssl_cert_reqs'] = REDIS_CONFIG.get('ssl_cert_reqs', 'none')
                    pool_params['ssl_check_hostname'] = False
                
                self._pool = redis.ConnectionPool(**pool_params)
                
                # Test connection
                self.get_client().ping()
                logger.info(f"Redis connected successfully to {REDIS_CONFIG.get('host')}:{REDIS_CONFIG.get('port')}")
                
                # Initialize cache metrics
                self._metrics = CacheMetrics(self)
                
                # Initialize multi-database pools
                self._initialize_multi_db_pools()
                
            except Exception as e:
                logger.error(f"Failed to connect to Redis: {e}")
                self._pool = None
                self._metrics = None
    
    def _initialize_multi_db_pools(self):
        """Initialize connection pools for multiple databases."""
        if not USE_REDIS_CACHE:
            return
            
        databases = {
            'cache': REDIS_DB_CACHE,
            'batch': REDIS_DB_BATCH,
            'metrics': REDIS_DB_METRICS,
            'rate_limit': REDIS_DB_RATE_LIMIT
        }
        
        for db_name, db_num in databases.items():
            try:
                # Get database-specific config
                db_config = get_redis_db_config(db_name)
                
                # Build connection parameters
                pool_params = {
                    'host': db_config.get('host', REDIS_HOST),
                    'port': db_config.get('port', REDIS_PORT),
                    'db': db_num,
                    'password': db_config.get('password', REDIS_PASSWORD),
                    'decode_responses': db_config.get('decode_responses', REDIS_DECODE_RESPONSES),
                    'max_connections': REDIS_MAX_CONNECTIONS // len(databases),  # Distribute connections
                    'socket_keepalive': REDIS_SOCKET_KEEPALIVE,
                    'socket_keepalive_options': REDIS_SOCKET_KEEPALIVE_OPTIONS,
                }
                
                # Add username if provided
                username = db_config.get('username', REDIS_USERNAME)
                if username:
                    pool_params['username'] = username
                
                # Add SSL parameters if configured
                if db_config.get('ssl', REDIS_SSL):
                    pool_params['connection_class'] = redis.SSLConnection
                    pool_params['ssl_cert_reqs'] = db_config.get('ssl_cert_reqs', 'none')
                    pool_params['ssl_check_hostname'] = False
                
                # Create pool
                self._pools[db_name] = redis.ConnectionPool(**pool_params)
                
                # Test connection
                test_client = redis.Redis(connection_pool=self._pools[db_name])
                test_client.ping()
                logger.info(f"Redis database '{db_name}' (DB {db_num}) connected successfully")
                
            except Exception as e:
                logger.error(f"Failed to connect to Redis database '{db_name}': {e}")
                self._pools[db_name] = None
    
    def get_client(self, database: str = 'default') -> redis.Redis:
        """
        Get Redis client from connection pool.
        
        Args:
            database: Database name ('default', 'cache', 'batch', 'metrics', 'rate_limit')
            
        Returns:
            Redis client instance
        """
        if not USE_REDIS_CACHE:
            raise RuntimeError("Redis is not configured or disabled")
            
        # Use legacy pool for 'default' or backward compatibility
        if database == 'default' or database not in self._pools:
            if self._pool is None:
                raise RuntimeError("Redis is not configured or disabled")
            return redis.Redis(connection_pool=self._pool)
        
        # Use multi-database pool
        pool = self._pools.get(database)
        if pool is None:
            raise RuntimeError(f"Redis database '{database}' is not configured")
        return redis.Redis(connection_pool=pool)
    
    @property
    def redis_client(self) -> redis.Redis:
        """Property for accessing Redis client (for compatibility)."""
        return self.get_client()
    
    def is_available(self) -> bool:
        """Check if Redis is available and configured."""
        if not USE_REDIS_CACHE or self._pool is None:
            return False
        try:
            self.get_client().ping()
            return True
        except:
            return False
    
    def get_cache_client(self) -> redis.Redis:
        """Get Redis client for cache database (documents, chunks, entities)."""
        return self.get_client('cache')
    
    def get_batch_client(self) -> redis.Redis:
        """Get Redis client for batch processing database."""
        return self.get_client('batch')
    
    def get_metrics_client(self) -> redis.Redis:
        """Get Redis client for metrics database."""
        return self.get_client('metrics')
    
    def get_rate_limit_client(self) -> redis.Redis:
        """Get Redis client for rate limiting database."""
        return self.get_client('rate_limit')
    
    def _get_database_for_key(self, key: str) -> str:
        """
        Determine which database to use based on key pattern.
        
        Args:
            key: Redis key
            
        Returns:
            Database name ('cache', 'batch', 'metrics', 'rate_limit')
        """
        if key.startswith(('batch:', 'batch_')):
            return 'batch'
        elif key.startswith(('metrics:', 'metric_', 'stats:')):
            return 'metrics'
        elif key.startswith(('rate:', 'limit:')):
            return 'rate_limit'
        else:
            # Default to cache database for document data
            return 'cache'
    
    def generate_cache_key(self, prefix: str, *args, **kwargs) -> str:
        """Generate a cache key from prefix and arguments."""
        parts = [prefix]
        
        # Add positional arguments
        for arg in args:
            if isinstance(arg, (str, int, float)):
                parts.append(str(arg))
            elif hasattr(arg, '__dict__'):
                # For objects, use a hash of their attributes
                obj_str = json.dumps(sorted(arg.__dict__.items()), default=str)
                parts.append(hashlib.md5(obj_str.encode()).hexdigest()[:8])
            else:
                parts.append(hashlib.md5(str(arg).encode()).hexdigest()[:8])
        
        # Add keyword arguments
        for key, value in sorted(kwargs.items()):
            parts.append(f"{key}:{value}")
        
        return ":".join(parts)
    
    # ========== Basic Cache Operations ==========
    
    def get_cached(self, key: str) -> Optional[Any]:
        """Get value from cache, handling JSON/pickle serialization."""
        if not self.is_available():
            return None
        
        try:
            # Determine which database to use based on key pattern
            database = self._get_database_for_key(key)
            client = self.get_client(database)
            value = client.get(key)
            
            if value is None:
                return None
            
            # Try to deserialize
            try:
                # First try JSON
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                # Try pickle for complex objects
                try:
                    return pickle.loads(value.encode('latin-1') if isinstance(value, str) else value)
                except:
                    # Return as string if all else fails
                    return value
                    
        except Exception as e:
            logger.error(f"Redis get error for key {key}: {e}")
            return None
    
    def set_cached(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """Set value in cache with optional TTL."""
        if not self.is_available():
            return False
        
        # Don't cache None values
        if value is None:
            return False
        
        try:
            # Determine which database to use based on key pattern
            database = self._get_database_for_key(key)
            client = self.get_client(database)
            
            # Serialize value
            if isinstance(value, BaseModel):
                # Pydantic model - use JSON
                serialized = value.model_dump_json()
            elif isinstance(value, (dict, list, str, int, float, bool)):
                # JSON-serializable types
                serialized = json.dumps(value, default=str)
            else:
                # Complex objects - use pickle
                serialized = pickle.dumps(value)
            
            # Set with optional TTL
            if ttl:
                return client.setex(key, ttl, serialized)
            else:
                return client.set(key, serialized)
                
        except Exception as e:
            logger.error(f"Redis set error for key {key}: {e}")
            return False
    
    def delete(self, key: str) -> bool:
        """Delete a key from cache."""
        if not self.is_available():
            return False
        
        try:
            return bool(self.get_client().delete(key))
        except Exception as e:
            logger.error(f"Redis delete error for key {key}: {e}")
            return False
    
    def exists(self, key: str) -> bool:
        """Check if a key exists in cache."""
        if not self.is_available():
            return False
        
        try:
            return bool(self.get_client().exists(key))
        except Exception as e:
            logger.error(f"Redis exists error for key {key}: {e}")
            return False
    
    # ========== Model-Aware Cache Operations ==========
    
    def get_cached_model(self, key: str, model_class: Type[BaseCacheModel]) -> Optional[BaseCacheModel]:
        """Get a Pydantic model from cache with validation."""
        if not self.is_available():
            return None
        
        try:
            client = self.get_client()
            value = client.get(key)
            
            if value is None:
                return None
            
            # Deserialize and validate model
            try:
                data = json.loads(value)
                model = model_class(**data)
                
                # Check if expired
                if hasattr(model, 'metadata') and model.metadata.is_expired:
                    # Delete expired entry
                    self.delete(key)
                    logger.debug(f"Deleted expired cache entry: {key}")
                    return None
                
                # Update access metrics
                if hasattr(model, 'metadata'):
                    model.metadata.update_access()
                    # Update in cache with new hit count
                    self.set_cached_model(key, model, ttl=model.metadata.ttl_seconds)
                
                return model
                
            except (json.JSONDecodeError, ValidationError) as e:
                logger.warning(f"Failed to deserialize cached model for key {key}: {e}")
                # Delete corrupted cache entry
                self.delete(key)
                return None
                
        except Exception as e:
            logger.error(f"Redis get_cached_model error for key {key}: {e}")
            return None
    
    def set_cached_model(self, key: str, model: BaseCacheModel, ttl: Optional[int] = None) -> bool:
        """Set Pydantic model in cache with automatic serialization."""
        if not self.is_available():
            return False
        
        try:
            client = self.get_client()
            
            # Use model's TTL if not provided
            if ttl is None and hasattr(model, 'metadata') and model.metadata.ttl_seconds:
                ttl = model.metadata.ttl_seconds
            
            # Serialize model to JSON
            serialized = model.model_dump_json()
            
            if ttl:
                success = client.setex(key, ttl, serialized)
            else:
                success = client.set(key, serialized)
            
            # Record metric
            if success and self._metrics:
                cache_type = CacheKeys.get_cache_type_from_key(key)
                self._metrics.record_set(cache_type)
            
            return success
            
        except Exception as e:
            logger.error(f"Redis set_cached_model error for key {key}: {e}")
            return False
    
    # ========== Batch Operations ==========
    
    def mget(self, keys: List[str]) -> List[Optional[Any]]:
        """Get multiple values from cache."""
        if not self.is_available() or not keys:
            return [None] * len(keys)
        
        try:
            client = self.get_client()
            values = client.mget(keys)
            
            results = []
            for value in values:
                if value is None:
                    results.append(None)
                else:
                    # Try to deserialize each value
                    try:
                        results.append(json.loads(value))
                    except:
                        results.append(value)
            
            return results
            
        except Exception as e:
            logger.error(f"Redis mget error: {e}")
            return [None] * len(keys)
    
    def mset(self, mapping: Dict[str, Any], ttl: Optional[int] = None) -> bool:
        """Set multiple values in cache."""
        if not self.is_available() or not mapping:
            return False
        
        try:
            client = self.get_client()
            
            # Serialize all values
            serialized_mapping = {}
            for key, value in mapping.items():
                if isinstance(value, BaseModel):
                    serialized_mapping[key] = value.model_dump_json()
                elif isinstance(value, (dict, list)):
                    serialized_mapping[key] = json.dumps(value, default=str)
                else:
                    serialized_mapping[key] = str(value)
            
            # Use pipeline for atomic operation
            with client.pipeline() as pipe:
                pipe.mset(serialized_mapping)
                
                # Set TTL if provided
                if ttl:
                    for key in serialized_mapping:
                        pipe.expire(key, ttl)
                
                pipe.execute()
            
            return True
            
        except Exception as e:
            logger.error(f"Redis mset error: {e}")
            return False
    
    # ========== Lock Operations ==========
    
    @contextmanager
    def lock(self, name: str, timeout: int = None, blocking: bool = True):
        """Distributed lock context manager."""
        if not self.is_available():
            yield True  # No-op if Redis not available
            return
        
        timeout = timeout or REDIS_LOCK_TIMEOUT
        lock_key = f"lock:{name}"
        
        try:
            client = self.get_client()
            lock = client.lock(lock_key, timeout=timeout, blocking_timeout=10 if blocking else 0)
            
            acquired = lock.acquire(blocking=blocking)
            if not acquired and blocking:
                logger.warning(f"Failed to acquire lock: {name}")
            
            yield acquired
            
        finally:
            try:
                if 'lock' in locals() and hasattr(lock, 'owned') and lock.owned():
                    lock.release()
            except Exception as e:
                logger.error(f"Error releasing lock {name}: {e}")
    
    # ========== Pattern Operations ==========
    
    def scan_keys(self, pattern: str, count: int = 100) -> List[str]:
        """Scan for keys matching a pattern."""
        if not self.is_available():
            return []
        
        try:
            client = self.get_client()
            keys = []
            
            for key in client.scan_iter(match=pattern, count=count):
                keys.append(key)
            
            return keys
            
        except Exception as e:
            logger.error(f"Redis scan error for pattern {pattern}: {e}")
            return []
    
    def delete_pattern(self, pattern: str) -> int:
        """Delete all keys matching a pattern."""
        if not self.is_available():
            return 0
        
        try:
            keys = self.scan_keys(pattern)
            if keys:
                return self.get_client().delete(*keys)
            return 0
            
        except Exception as e:
            logger.error(f"Redis delete_pattern error for {pattern}: {e}")
            return 0
    
    # ========== Hash Operations ==========
    
    def hget(self, name: str, key: str) -> Optional[str]:
        """Get a field from a hash."""
        if not self.is_available():
            return None
        
        try:
            return self.get_client().hget(name, key)
        except Exception as e:
            logger.error(f"Redis hget error for {name}:{key}: {e}")
            return None
    
    def hset(self, name: str, key: str, value: str) -> bool:
        """Set a field in a hash."""
        if not self.is_available():
            return False
        
        try:
            return bool(self.get_client().hset(name, key, value))
        except Exception as e:
            logger.error(f"Redis hset error for {name}:{key}: {e}")
            return False
    
    def hgetall(self, name: str) -> Dict[str, str]:
        """Get all fields from a hash."""
        if not self.is_available():
            return {}
        
        try:
            return self.get_client().hgetall(name) or {}
        except Exception as e:
            logger.error(f"Redis hgetall error for {name}: {e}")
            return {}
    
    # ========== Set Operations ==========
    
    def sadd(self, name: str, *values) -> int:
        """Add members to a set."""
        if not self.is_available() or not values:
            return 0
        
        try:
            return self.get_client().sadd(name, *values)
        except Exception as e:
            logger.error(f"Redis sadd error for {name}: {e}")
            return 0
    
    def smembers(self, name: str) -> set:
        """Get all members of a set."""
        if not self.is_available():
            return set()
        
        try:
            return self.get_client().smembers(name) or set()
        except Exception as e:
            logger.error(f"Redis smembers error for {name}: {e}")
            return set()
    
    def srem(self, name: str, *values) -> int:
        """Remove members from a set."""
        if not self.is_available() or not values:
            return 0
        
        try:
            return self.get_client().srem(name, *values)
        except Exception as e:
            logger.error(f"Redis srem error for {name}: {e}")
            return 0

    # ========== Simplified Redis Acceleration Methods ==========
    # These methods provide simple Redis acceleration with fallback support
    
    def set_with_ttl(self, key: str, value: Any, ttl: int = 3600) -> bool:
        """Set cache with TTL. Skip if too large."""
        try:
            # Simple size check - skip large objects
            data = pickle.dumps(value) if not isinstance(value, str) else value.encode()
            if len(data) > 5 * 1024 * 1024:  # 5MB limit
                logger.warning(f"Skipping cache for {key} - too large ({len(data)} bytes)")
                return False
                
            return self.set_cached(key, value, ttl=ttl)
        except Exception as e:
            logger.error(f"Cache set failed for {key}: {e}")
            return False

    def get_with_fallback(self, key: str, fallback_func: Callable) -> Optional[Any]:
        """Get from cache or fallback to function (usually DB query)."""
        try:
            # Try cache first
            value = self.get_cached(key)
            if value is not None:
                logger.debug(f"Cache hit for {key}")
                return value
        except Exception as e:
            logger.warning(f"Cache error for {key}: {e}")
        
        # Fallback
        logger.debug(f"Cache miss for {key}, using fallback")
        return fallback_func()

    # Simple circuit breaker
    _redis_failures = 0
    _redis_disabled_until = None

    def is_redis_healthy(self) -> bool:
        """Simple circuit breaker - disable Redis for 5 minutes after 5 failures."""
        # Check if circuit breaker is open
        if self._redis_disabled_until and datetime.utcnow() < self._redis_disabled_until:
            return False
        elif self._redis_disabled_until:
            # Reset if time has passed
            self._redis_disabled_until = None
            self._redis_failures = 0
                
        try:
            self.get_client().ping()
            self._redis_failures = 0  # Reset on success
            return True
        except Exception as e:
            self._redis_failures += 1
            if self._redis_failures >= 5:
                self._redis_disabled_until = datetime.utcnow() + timedelta(minutes=5)
                logger.error(f"Redis circuit breaker opened - disabled for 5 minutes. Error: {e}")
            return False

    # ========== Compatibility Methods ==========
    # These methods provide compatibility with code expecting dict-specific methods
    
    def get_dict(self, key: str) -> Optional[Dict[str, Any]]:
        """Get a dictionary from cache. Compatibility wrapper for get_cached."""
        result = self.get_cached(key)
        if result is not None and not isinstance(result, dict):
            logger.warning(f"get_dict called but value at {key} is not a dict: {type(result)}")
            return None
        return result
    
    def store_dict(self, key: str, value: Dict[str, Any], ttl: Optional[int] = None) -> bool:
        """Store a dictionary in cache. Compatibility wrapper for set_cached."""
        if not isinstance(value, dict):
            logger.error(f"store_dict called with non-dict value: {type(value)}")
            return False
        return self.set_cached(key, value, ttl)
    
    def get_cached_chunks(self, key: str) -> Optional[Dict[str, Any]]:
        """Get cached chunks data. Alias for get_dict."""
        return self.get_dict(key)
    
    def cache_chunks(self, key: str, chunks_data: Dict[str, Any], ttl: Optional[int] = None) -> bool:
        """Cache chunks data. Alias for store_dict."""
        return self.store_dict(key, chunks_data, ttl)
    
    def get_cached_ocr_result(self, key: str) -> Optional[Dict[str, Any]]:
        """Get cached OCR result. Alias for get_dict."""
        return self.get_dict(key)
    
    def cache_ocr_result(self, key: str, ocr_data: Dict[str, Any], ttl: Optional[int] = None) -> bool:
        """Cache OCR result. Alias for store_dict."""
        return self.store_dict(key, ocr_data, ttl)
    
    def get_cached_entity_mentions(self, key: str) -> Optional[Dict[str, Any]]:
        """Get cached entity mentions. Alias for get_dict."""
        return self.get_dict(key)
    
    def get_cached_canonical_entities(self, key: str) -> Optional[Dict[str, Any]]:
        """Get cached canonical entities. Alias for get_dict."""
        return self.get_dict(key)
    
    # ========== Enhanced Batch Processing Operations ==========
    # Methods specifically designed for batch processing optimization
    
    def batch_update_document_states(self, updates: List[Tuple[str, str, str, Dict]]) -> bool:
        """
        Update multiple document states atomically using pipeline.
        
        Args:
            updates: List of (document_uuid, stage, status, metadata) tuples
            
        Returns:
            bool: True if all updates succeeded, False otherwise
        """
        if not self.is_available() or not updates:
            return False
        
        try:
            client = self.get_client()
            
            with client.pipeline() as pipe:
                for document_uuid, stage, status, metadata in updates:
                    state_key = CacheKeys.format_key(CacheKeys.DOC_STATE, document_uuid=document_uuid)
                    
                    # Create state data for this stage
                    state_data = {
                        stage: {
                            'status': status,
                            'timestamp': datetime.now().isoformat(),
                            'metadata': metadata
                        }
                    }
                    
                    # Update the hash field for this stage
                    pipe.hset(state_key, stage, json.dumps(state_data[stage]))
                    pipe.expire(state_key, 86400)  # 24 hour TTL
                
                # Execute all updates atomically
                results = pipe.execute()
                
                # Check if all operations succeeded
                success = all(results[i::2] for i in range(0, len(results), 2))  # Every other result (hset operations)
                
                if success:
                    logger.debug(f"Successfully updated {len(updates)} document states")
                else:
                    logger.warning(f"Some document state updates failed")
                
                return success
                
        except Exception as e:
            logger.error(f"Batch document state update failed: {e}")
            return False
    
    def batch_cache_documents(self, documents: List[Dict[str, Any]], ttl: int = 86400) -> bool:
        """
        Cache multiple documents efficiently using pipeline.
        
        Args:
            documents: List of document dictionaries with caching data
            ttl: Time to live in seconds (default: 24 hours)
            
        Returns:
            bool: True if caching succeeded, False otherwise
        """
        if not self.is_available() or not documents:
            return False
        
        try:
            client = self.get_client()
            
            with client.pipeline() as pipe:
                cached_count = 0
                
                for doc in documents:
                    doc_uuid = doc.get('document_uuid')
                    if not doc_uuid:
                        logger.warning("Document missing UUID, skipping cache")
                        continue
                    
                    # Cache OCR result if available
                    if 'ocr_text' in doc:
                        ocr_key = CacheKeys.format_key(CacheKeys.DOC_OCR_RESULT, document_uuid=doc_uuid)
                        ocr_data = {
                            'text': doc['ocr_text'],
                            'length': len(doc['ocr_text']),
                            'extracted_at': datetime.now().isoformat(),
                            'metadata': doc.get('ocr_metadata', {}),
                            'method': doc.get('ocr_method', 'unknown')
                        }
                        pipe.setex(ocr_key, ttl, json.dumps(ocr_data))
                        cached_count += 1
                    
                    # Cache chunks if available
                    if 'chunks' in doc:
                        chunks_key = CacheKeys.format_key(CacheKeys.DOC_CHUNKS, document_uuid=doc_uuid)
                        chunks_data = {
                            'chunks': doc['chunks'],
                            'chunk_count': len(doc['chunks']),
                            'created_at': datetime.now().isoformat()
                        }
                        pipe.setex(chunks_key, ttl, json.dumps(chunks_data))
                        cached_count += 1
                    
                    # Cache entity mentions if available
                    if 'entity_mentions' in doc:
                        mentions_key = CacheKeys.format_key(CacheKeys.DOC_ALL_EXTRACTED_MENTIONS, document_uuid=doc_uuid)
                        mentions_data = {
                            'mentions': doc['entity_mentions'],
                            'mention_count': len(doc['entity_mentions']),
                            'extracted_at': datetime.now().isoformat()
                        }
                        pipe.setex(mentions_key, ttl, json.dumps(mentions_data))
                        cached_count += 1
                    
                    # Cache canonical entities if available
                    if 'canonical_entities' in doc:
                        canonical_key = CacheKeys.format_key(CacheKeys.DOC_CANONICAL_ENTITIES, document_uuid=doc_uuid)
                        canonical_data = {
                            'entities': doc['canonical_entities'],
                            'entity_count': len(doc['canonical_entities']),
                            'resolved_at': datetime.now().isoformat()
                        }
                        pipe.setex(canonical_key, ttl, json.dumps(canonical_data))
                        cached_count += 1
                
                # Execute all cache operations atomically
                results = pipe.execute()
                
                logger.info(f"Batch cached {cached_count} data items for {len(documents)} documents")
                return True
                
        except Exception as e:
            logger.error(f"Batch document caching failed: {e}")
            return False
    
    def batch_get_document_cache(self, document_uuids: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        Efficiently retrieve cached data for multiple documents.
        
        Args:
            document_uuids: List of document UUIDs to retrieve cache for
            
        Returns:
            Dict mapping document_uuid to cached data
        """
        if not self.is_available() or not document_uuids:
            return {}
        
        try:
            client = self.get_client()
            
            # Build all cache keys
            cache_keys = []
            key_map = {}  # Map index to (document_uuid, cache_type)
            
            for doc_uuid in document_uuids:
                # OCR cache
                ocr_key = CacheKeys.format_key(CacheKeys.DOC_OCR_RESULT, document_uuid=doc_uuid)
                cache_keys.append(ocr_key)
                key_map[len(cache_keys) - 1] = (doc_uuid, 'ocr')
                
                # Chunks cache
                chunks_key = CacheKeys.format_key(CacheKeys.DOC_CHUNKS, document_uuid=doc_uuid)
                cache_keys.append(chunks_key)
                key_map[len(cache_keys) - 1] = (doc_uuid, 'chunks')
                
                # Entity mentions cache
                mentions_key = CacheKeys.format_key(CacheKeys.DOC_ALL_EXTRACTED_MENTIONS, document_uuid=doc_uuid)
                cache_keys.append(mentions_key)
                key_map[len(cache_keys) - 1] = (doc_uuid, 'mentions')
                
                # Canonical entities cache
                canonical_key = CacheKeys.format_key(CacheKeys.DOC_CANONICAL_ENTITIES, document_uuid=doc_uuid)
                cache_keys.append(canonical_key)
                key_map[len(cache_keys) - 1] = (doc_uuid, 'canonical')
            
            # Get all values in one round trip
            cached_values = client.mget(cache_keys)
            
            # Organize results by document
            result = {}
            for i, value in enumerate(cached_values):
                doc_uuid, cache_type = key_map[i]
                
                if doc_uuid not in result:
                    result[doc_uuid] = {}
                
                if value is not None:
                    try:
                        result[doc_uuid][cache_type] = json.loads(value)
                    except json.JSONDecodeError:
                        result[doc_uuid][cache_type] = value
                else:
                    result[doc_uuid][cache_type] = None
            
            logger.debug(f"Retrieved cache data for {len(document_uuids)} documents")
            return result
            
        except Exception as e:
            logger.error(f"Batch document cache retrieval failed: {e}")
            return {}
    
    def execute_lua_script(self, script: str, keys: List[str], args: List[str], database: str = 'cache') -> Any:
        """
        Execute a Lua script atomically in Redis.
        
        Args:
            script: Lua script to execute
            keys: Redis keys the script will access
            args: Arguments to pass to the script
            database: Database to execute script in
            
        Returns:
            Script execution result
        """
        if not self.is_available():
            return None
        
        try:
            # Use specified database or determine from first key
            if keys and database == 'cache':
                database = self._get_database_for_key(keys[0])
            client = self.get_client(database)
            return client.eval(script, len(keys), *keys, *args)
        except Exception as e:
            logger.error(f"Lua script execution failed: {e}")
            return None
    
    def atomic_batch_progress_update(self, batch_id: str, document_uuid: str, 
                                   old_status: str, new_status: str) -> bool:
        """
        Atomically update batch progress using Lua script.
        
        Args:
            batch_id: Batch identifier
            document_uuid: Document being updated
            old_status: Previous status
            new_status: New status
            
        Returns:
            bool: True if update succeeded
        """
        if not self.is_available():
            return False
        
        # Lua script for atomic batch progress update
        lua_script = """
        local progress_key = KEYS[1]
        local old_status = ARGV[1]
        local new_status = ARGV[2]
        local timestamp = ARGV[3]
        
        -- Decrement old status count
        redis.call('hincrby', progress_key, old_status, -1)
        
        -- Increment new status count
        redis.call('hincrby', progress_key, new_status, 1)
        
        -- Update timestamp
        redis.call('hset', progress_key, 'last_updated', timestamp)
        
        -- Check if batch is completed
        local completed = tonumber(redis.call('hget', progress_key, 'completed') or 0)
        local failed = tonumber(redis.call('hget', progress_key, 'failed') or 0)
        local total = tonumber(redis.call('hget', progress_key, 'total') or 0)
        
        if completed + failed >= total then
            redis.call('hset', progress_key, 'status', 'completed')
            redis.call('hset', progress_key, 'completed_at', timestamp)
        end
        
        return redis.status_reply('OK')
        """
        
        progress_key = f"batch:progress:{batch_id}"
        timestamp = datetime.now().isoformat()
        
        try:
            result = self.execute_lua_script(
                lua_script, 
                [progress_key], 
                [old_status, new_status, timestamp]
            )
            return result is not None
        except Exception as e:
            logger.error(f"Atomic batch progress update failed for {batch_id}: {e}")
            return False


# ========== Cache Manager ==========

class CacheManager:
    """
    High-level cache management with Pydantic model support and automatic invalidation.
    """
    
    def __init__(self, redis_manager: Optional[RedisManager] = None):
        self.redis = redis_manager or RedisManager()
    
    @property
    def is_available(self) -> bool:
        """Check if cache is available."""
        return self.redis.is_available()
    
    def clear_document_cache(self, document_uuid: str) -> int:
        """Clear all cached data for a document."""
        if not self.is_available:
            logger.warning("Cache not available")
            return 0
        
        cleared = 0
        patterns = [
            CacheKeys.DOC_OCR_RESULT,
            CacheKeys.DOC_CHUNKS,
            CacheKeys.DOC_CHUNKS_LIST,
            CacheKeys.DOC_ALL_EXTRACTED_MENTIONS,
            CacheKeys.DOC_RESOLVED_MENTIONS,
            CacheKeys.DOC_CANONICAL_ENTITIES,
            CacheKeys.DOC_CLEANED_TEXT,
            CacheKeys.DOC_ENTITIES,
            CacheKeys.DOC_STRUCTURED,
            CacheKeys.DOC_STATE
        ]
        
        for pattern in patterns:
            # Skip patterns that require chunk_id for now, handle them separately
            if "{chunk_id}" in pattern:
                # Use pattern matching for chunk-based keys
                chunk_pattern = pattern.replace("{document_uuid}", document_uuid).replace("{chunk_id}", "*")
                cleared += self.redis.delete_pattern(chunk_pattern)
                continue
                
            # Handle versioned keys
            for version in range(1, 10):  # Check up to version 9
                try:
                    key = CacheKeys.format_key(pattern, version=version, document_uuid=document_uuid)
                    if self.redis.delete(key):
                        cleared += 1
                except KeyError:
                    # Pattern doesn't support version parameter
                    pass
            
            # Handle non-versioned keys
            try:
                key = CacheKeys.format_key(pattern, document_uuid=document_uuid)
                if self.redis.delete(key):
                    cleared += 1
            except KeyError:
                # Pattern requires additional parameters
                pass
        
        # Clear embeddings
        pattern = f"emb:doc:{document_uuid}:*"
        cleared += self.redis.delete_pattern(pattern)
        
        logger.info(f"Cleared {cleared} cache keys for document {document_uuid}")
        return cleared
    
    def clear_project_cache(self, project_id: int) -> int:
        """Clear all cached data for a project."""
        if not self.is_available:
            logger.warning("Cache not available")
            return 0
        
        # Clear project-related keys
        pattern = f"project:{project_id}:*"
        cleared = self.redis.delete_pattern(pattern)
        
        logger.info(f"Cleared {cleared} cache keys for project {project_id}")
        return cleared
    
    def invalidate_by_tags(self, tags: List[str]) -> int:
        """Invalidate cache entries by tags."""
        if not self.is_available or not tags:
            return 0
        
        # This would require maintaining a tag index
        # For now, log the intent
        logger.info(f"Tag-based invalidation requested for tags: {tags}")
        return 0
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get comprehensive cache statistics."""
        if not self.is_available:
            return {"status": "unavailable"}
        
        try:
            client = self.redis.get_client()
            info = client.info()
            
            stats = {
                "status": "available",
                "used_memory": info.get("used_memory_human", "unknown"),
                "used_memory_peak": info.get("used_memory_peak_human", "unknown"),
                "connected_clients": info.get("connected_clients", 0),
                "total_connections_received": info.get("total_connections_received", 0),
                "total_commands_processed": info.get("total_commands_processed", 0),
                "instantaneous_ops_per_sec": info.get("instantaneous_ops_per_sec", 0),
                "keyspace_hits": info.get("keyspace_hits", 0),
                "keyspace_misses": info.get("keyspace_misses", 0),
                "evicted_keys": info.get("evicted_keys", 0),
                "expired_keys": info.get("expired_keys", 0)
            }
            
            # Calculate hit rate
            hits = stats["keyspace_hits"]
            misses = stats["keyspace_misses"]
            if hits + misses > 0:
                stats["hit_rate"] = hits / (hits + misses)
            else:
                stats["hit_rate"] = 0.0
            
            # Add custom metrics if available
            if hasattr(self.redis, '_metrics') and self.redis._metrics:
                stats["custom_metrics"] = self.redis._metrics.get_metrics()
            
            return stats
            
        except Exception as e:
            logger.error(f"Failed to get cache stats: {e}")
            return {"status": "error", "error": str(e)}


# ========== Decorators ==========

def redis_cache(prefix: str, ttl: int, key_func: Optional[Callable] = None):
    """
    Decorator for caching function results in Redis.
    
    Args:
        prefix: Cache key prefix
        ttl: Time to live in seconds
        key_func: Optional function to generate cache key from arguments
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not USE_REDIS_CACHE:
                return func(*args, **kwargs)
            
            try:
                redis_mgr = RedisManager()
                if not redis_mgr.is_available():
                    return func(*args, **kwargs)
                
                # Generate cache key
                if key_func:
                    cache_key = key_func(*args, **kwargs)
                else:
                    cache_key = redis_mgr.generate_cache_key(prefix, *args, **kwargs)
                
                # Check cache
                cached_value = redis_mgr.get_cached(cache_key)
                if cached_value is not None:
                    logger.debug(f"Cache hit for {cache_key}")
                    # Record cache hit
                    if hasattr(redis_mgr, '_metrics') and redis_mgr._metrics:
                        cache_type = CacheKeys.get_cache_type_from_key(cache_key)
                        redis_mgr._metrics.record_hit(cache_type)
                    return cached_value
                
                # Record cache miss
                if hasattr(redis_mgr, '_metrics') and redis_mgr._metrics:
                    cache_type = CacheKeys.get_cache_type_from_key(cache_key)
                    redis_mgr._metrics.record_miss(cache_type)
                
                # Execute function
                result = func(*args, **kwargs)
                
                # Cache result
                redis_mgr.set_cached(cache_key, result, ttl)
                logger.debug(f"Cached result for {cache_key}")
                
                return result
                
            except Exception as e:
                logger.error(f"Redis cache decorator error: {e}")
                # Fall back to executing function
                return func(*args, **kwargs)
        
        return wrapper
    return decorator


def rate_limit(key: str, limit: int, window: int, wait: bool = True, max_wait: int = 60):
    """
    Rate limiting decorator using Redis.
    
    Args:
        key: Rate limit key
        limit: Maximum requests allowed
        window: Time window in seconds
        wait: Whether to wait if rate limited
        max_wait: Maximum wait time in seconds
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not USE_REDIS_CACHE:
                return func(*args, **kwargs)
            
            try:
                redis_mgr = RedisManager()
                if not redis_mgr.is_available():
                    return func(*args, **kwargs)
                
                client = redis_mgr.get_client()
                rate_key = f"rate:{key}"
                
                # Use a sliding window rate limiter
                now = time.time()
                window_start = now - window
                
                # Remove old entries
                client.zremrangebyscore(rate_key, 0, window_start)
                
                # Count current requests
                current_count = client.zcard(rate_key)
                
                if current_count < limit:
                    # Add current request
                    client.zadd(rate_key, {str(now): now})
                    client.expire(rate_key, window)
                    return func(*args, **kwargs)
                else:
                    if wait:
                        # Calculate wait time
                        oldest = client.zrange(rate_key, 0, 0, withscores=True)
                        if oldest:
                            wait_time = window - (now - oldest[0][1])
                            wait_time = min(wait_time, max_wait)
                            logger.warning(f"Rate limited on {key}, waiting {wait_time:.2f}s")
                            time.sleep(wait_time)
                            # Retry
                            return wrapper(*args, **kwargs)
                    else:
                        raise Exception(f"Rate limit exceeded for {key}")
                        
            except Exception as e:
                logger.error(f"Rate limit decorator error: {e}")
                # Fall back to executing function
                return func(*args, **kwargs)
        
        return wrapper
    return decorator


# ========== Utility Functions ==========

def get_redis_manager() -> RedisManager:
    """Get singleton Redis manager instance."""
    return RedisManager()


def get_cache_manager() -> CacheManager:
    """Get cache manager instance."""
    return CacheManager()


def clear_all_cache() -> int:
    """Clear all cache entries (use with caution)."""
    manager = get_redis_manager()
    if not manager.is_available():
        return 0
    
    try:
        client = manager.get_client()
        return client.flushdb()
    except Exception as e:
        logger.error(f"Failed to clear all cache: {e}")
        return 0


def warmup_cache(document_uuids: List[str]) -> Dict[str, Any]:
    """
    Warm up cache for specified documents.
    
    Args:
        document_uuids: List of document UUIDs to warm up
        
    Returns:
        Statistics about warmed entries
    """
    stats = {
        "warmed": 0,
        "failed": 0,
        "already_cached": 0
    }
    
    # This would be implemented based on specific warming needs
    logger.info(f"Cache warmup requested for {len(document_uuids)} documents")
    
    return stats


# ========== Export All ==========

__all__ = [
    # Classes
    'CacheKeys',
    'CacheStatus',
    'CacheMetadataModel',
    'BaseCacheModel',
    'CacheMetrics',
    'RedisManager',
    'CacheManager',
    
    # Decorators
    'redis_cache',
    'rate_limit',
    
    # Functions
    'get_redis_manager',
    'get_cache_manager',
    'clear_all_cache',
    'warmup_cache'
]