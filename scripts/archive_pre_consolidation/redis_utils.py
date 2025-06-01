# redis_utils.py
"""Redis utility module for managing connections and operations with Redis Cloud."""

import redis
import json
import hashlib
import pickle
import time
from typing import Any, Optional, Union, Dict, List, Callable, Tuple
from functools import wraps
from contextlib import contextmanager
import logging
from datetime import datetime, timedelta
import threading

# Import config settings
from scripts.config import (
    REDIS_HOST, REDIS_PORT, REDIS_PASSWORD, REDIS_DB,
    USE_REDIS_CACHE, REDIS_MAX_CONNECTIONS, REDIS_USERNAME, REDIS_SSL,
    REDIS_SOCKET_KEEPALIVE, REDIS_SOCKET_KEEPALIVE_OPTIONS, REDIS_DECODE_RESPONSES,
    REDIS_CONFIG, REDIS_LOCK_TIMEOUT, REDIS_OCR_CACHE_TTL, REDIS_LLM_CACHE_TTL,
    REDIS_ENTITY_CACHE_TTL, REDIS_STRUCTURED_CACHE_TTL, REDIS_CHUNK_CACHE_TTL
)
from scripts.cache_keys import CacheKeys

# Import Pydantic models for type-safe caching
from scripts.core.cache_models import (
    BaseCacheModel, CacheMetadataModel, CacheStatus,
    CachedProjectModel, CachedDocumentModel, CachedChunkListModel,
    CachedEntityResolutionModel, CachedOCRResultModel, CachedProcessingStatusModel,
    CachedEmbeddingModel, CachedSearchResultModel, CachedBatchStatusModel
)
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)


class RedisManager:
    """Manages Redis connections and provides utility methods."""
    
    _instance = None
    _pool = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(RedisManager, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        """Initialize Redis connection pool."""
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
                # Note: Redis Cloud doesn't always require SSL
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
                
                # Pool monitoring
                self._pool_stats_interval = 300  # 5 minutes
                self._last_pool_stats_time = 0
                
            except Exception as e:
                logger.error(f"Failed to connect to Redis: {e}")
                self._pool = None
                raise
    
    def get_client(self) -> redis.Redis:
        """Get Redis client from connection pool."""
        if not USE_REDIS_CACHE or self._pool is None:
            raise RuntimeError("Redis is not configured or disabled")
        return redis.Redis(connection_pool=self._pool)
    
    def is_available(self) -> bool:
        """Check if Redis is available."""
        if not USE_REDIS_CACHE or self._pool is None:
            return False
        try:
            self.get_client().ping()
            return True
        except:
            return False
    
    # Key generation utilities
    @staticmethod
    def generate_cache_key(prefix: str, *args, **kwargs) -> str:
        """Generate a consistent cache key from arguments."""
        key_parts = [prefix]
        
        # Add positional arguments
        for arg in args:
            if isinstance(arg, (dict, list)):
                key_parts.append(hashlib.md5(json.dumps(arg, sort_keys=True).encode()).hexdigest()[:8])
            else:
                key_parts.append(str(arg))
        
        # Add keyword arguments
        if kwargs:
            sorted_kwargs = sorted(kwargs.items())
            kwargs_str = json.dumps(dict(sorted_kwargs), sort_keys=True)
            key_parts.append(hashlib.md5(kwargs_str.encode()).hexdigest()[:8])
        
        return ':'.join(key_parts)
    
    # Cache operations
    def get_cached(self, key: str) -> Optional[Any]:
        """Get value from cache."""
        try:
            client = self.get_client()
            value = client.get(key)
            if value:
                try:
                    # Try to deserialize as JSON first
                    return json.loads(value)
                except json.JSONDecodeError:
                    # Fall back to raw string
                    return value
        except Exception as e:
            logger.error(f"Redis get error for key {key}: {e}")
            return None
    
    def set_cached(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """Set value in cache with optional TTL."""
        try:
            client = self.get_client()
            
            # Serialize value
            if isinstance(value, (dict, list)):
                serialized = json.dumps(value)
            else:
                serialized = str(value)
            
            if ttl:
                return client.setex(key, ttl, serialized)
            else:
                return client.set(key, serialized)
        except Exception as e:
            logger.error(f"Redis set error for key {key}: {e}")
            return False
    
    def delete(self, key: str) -> bool:
        """Delete key from cache."""
        try:
            client = self.get_client()
            return bool(client.delete(key))
        except Exception as e:
            logger.error(f"Redis delete error for key {key}: {e}")
            return False
    
    def exists(self, key: str) -> bool:
        """Check if key exists in cache."""
        try:
            client = self.get_client()
            return bool(client.exists(key))
        except Exception as e:
            logger.error(f"Redis exists error for key {key}: {e}")
            return False
    
    # Hash operations
    def hset(self, name: str, key: str, value: Any) -> bool:
        """Set hash field."""
        try:
            client = self.get_client()
            if isinstance(value, (dict, list)):
                value = json.dumps(value)
            return bool(client.hset(name, key, value))
        except Exception as e:
            logger.error(f"Redis hset error for {name}:{key}: {e}")
            return False
    
    def hget(self, name: str, key: str) -> Optional[Any]:
        """Get hash field."""
        try:
            client = self.get_client()
            value = client.hget(name, key)
            if value:
                try:
                    return json.loads(value)
                except json.JSONDecodeError:
                    return value
            return None
        except Exception as e:
            logger.error(f"Redis hget error for {name}:{key}: {e}")
            return None
    
    def hgetall(self, name: str) -> Dict[str, Any]:
        """Get all hash fields."""
        try:
            client = self.get_client()
            data = client.hgetall(name)
            result = {}
            for k, v in data.items():
                try:
                    result[k] = json.loads(v)
                except json.JSONDecodeError:
                    result[k] = v
            return result
        except Exception as e:
            logger.error(f"Redis hgetall error for {name}: {e}")
            return {}
    
    # Lock operations
    @contextmanager
    def lock(self, lock_name: str, timeout: int = None, blocking: bool = True):
        """Context manager for distributed locking."""
        if timeout is None:
            timeout = REDIS_LOCK_TIMEOUT
        
        lock = None
        try:
            client = self.get_client()
            lock = client.lock(lock_name, timeout=timeout, blocking_timeout=timeout if blocking else 0)
            
            if lock.acquire(blocking=blocking):
                yield lock
            else:
                raise RuntimeError(f"Could not acquire lock: {lock_name}")
        except Exception as e:
            logger.error(f"Lock error for {lock_name}: {e}")
            raise
        finally:
            if lock and lock.owned():
                try:
                    lock.release()
                except:
                    pass
    
    # Atomic operations
    def setnx(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """Set key if not exists (atomic)."""
        try:
            client = self.get_client()
            if isinstance(value, (dict, list)):
                value = json.dumps(value)
            
            if client.setnx(key, value):
                if ttl:
                    client.expire(key, ttl)
                return True
            return False
        except Exception as e:
            logger.error(f"Redis setnx error for key {key}: {e}")
            return False
    
    # Rate limiting
    def check_rate_limit(self, key: str, limit: int, window: int) -> bool:
        """Check if action is within rate limit."""
        try:
            client = self.get_client()
            pipe = client.pipeline()
            now = time.time()
            
            # Remove old entries
            pipe.zremrangebyscore(key, 0, now - window)
            # Add current request
            pipe.zadd(key, {str(now): now})
            # Count requests in window
            pipe.zcard(key)
            # Set expiry
            pipe.expire(key, window)
            
            results = pipe.execute()
            count = results[2]
            
            return count <= limit
        except Exception as e:
            logger.error(f"Rate limit check error for {key}: {e}")
            return True  # Allow on error
    
    # Pub/Sub operations
    def publish(self, channel: str, message: Any) -> bool:
        """Publish message to channel."""
        try:
            client = self.get_client()
            if isinstance(message, (dict, list)):
                message = json.dumps(message)
            return bool(client.publish(channel, message))
        except Exception as e:
            logger.error(f"Redis publish error to {channel}: {e}")
            return False
    
    def get_pubsub(self) -> redis.client.PubSub:
        """Get pub/sub connection."""
        return self.get_client().pubsub()
    
    # Cache invalidation methods
    def invalidate_document_cache(self, document_uuid: str) -> int:
        """
        Invalidate all caches related to a document.
        
        Args:
            document_uuid: Document UUID to invalidate
            
        Returns:
            Number of keys deleted
        """
        if not self.is_available():
            logger.warning("Redis not available, cannot invalidate cache")
            return 0
            
        try:
            client = self.get_client()
            patterns = CacheKeys.get_all_document_patterns(document_uuid)
            
            deleted_count = 0
            for pattern in patterns:
                if '*' in pattern:
                    # Pattern with wildcard - scan and delete
                    for key in client.scan_iter(match=pattern):
                        client.delete(key)
                        deleted_count += 1
                        logger.debug(f"Invalidated cache key: {key}")
                else:
                    # Exact key - direct delete
                    if client.delete(pattern):
                        deleted_count += 1
                        logger.debug(f"Invalidated cache key: {pattern}")
                        
            logger.info(f"Invalidated {deleted_count} cache keys for document {document_uuid}")
            return deleted_count
            
        except Exception as e:
            logger.error(f"Error invalidating document cache for {document_uuid}: {e}")
            return 0
    
    def invalidate_pattern(self, pattern: str) -> int:
        """
        Invalidate all keys matching a pattern.
        
        Args:
            pattern: Redis key pattern (can include wildcards)
            
        Returns:
            Number of keys deleted
        """
        if not self.is_available():
            return 0
            
        try:
            client = self.get_client()
            count = 0
            
            for key in client.scan_iter(match=pattern, count=100):
                client.delete(key)
                count += 1
                
            logger.info(f"Invalidated {count} keys matching pattern: {pattern}")
            return count
            
        except Exception as e:
            logger.error(f"Error invalidating pattern {pattern}: {e}")
            return 0
    
    # Batch operations
    def batch_set_cached(self, key_value_pairs: List[Tuple[str, Any]], ttl: Optional[int] = None) -> bool:
        """
        Set multiple cache entries in a single pipeline.
        
        Args:
            key_value_pairs: List of (key, value) tuples
            ttl: Optional TTL for all keys
            
        Returns:
            True if all operations successful
        """
        if not self.is_available():
            return False
            
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
            success = all(results)
            
            if success:
                # Update metrics
                for key, _ in key_value_pairs:
                    cache_type = CacheKeys.get_cache_type_from_key(key)
                    self._metrics.record_set(cache_type)
                    
            return success
            
        except Exception as e:
            logger.error(f"Redis batch set error: {e}")
            return False
    
    def batch_get_cached(self, keys: List[str]) -> Dict[str, Any]:
        """
        Get multiple cache entries in a single pipeline.
        
        Args:
            keys: List of cache keys
            
        Returns:
            Dictionary mapping keys to values
        """
        if not self.is_available():
            return {}
            
        try:
            client = self.get_client()
            pipe = client.pipeline()
            
            for key in keys:
                pipe.get(key)
            
            results = pipe.execute()
            
            output = {}
            for key, value in zip(keys, results):
                if value is not None:
                    try:
                        output[key] = json.loads(value)
                        self._metrics.record_hit(CacheKeys.get_cache_type_from_key(key))
                    except json.JSONDecodeError:
                        output[key] = value
                        self._metrics.record_hit(CacheKeys.get_cache_type_from_key(key))
                else:
                    self._metrics.record_miss(CacheKeys.get_cache_type_from_key(key))
                    
            return output
            
        except Exception as e:
            logger.error(f"Redis batch get error: {e}")
            return {}
    
    # Connection pool monitoring
    def log_pool_stats(self):
        """Log connection pool statistics."""
        if not self._pool or not self.is_available():
            return
            
        current_time = time.time()
        if current_time - self._last_pool_stats_time < self._pool_stats_interval:
            return
            
        self._last_pool_stats_time = current_time
        
        try:
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
                
        except Exception as e:
            logger.error(f"Error logging pool stats: {e}")
    
    # Stream operations (for future Redis Streams implementation)
    def produce_to_stream(self, stream_name: str, message_data: Dict[str, Any], max_len: Optional[int] = None) -> Optional[str]:
        """Produce a message to a Redis Stream."""
        if not self.is_available():
            logger.error("Redis not available, cannot produce to stream.")
            return None
            
        try:
            client = self.get_client()
            # Ensure all message_data values are strings, bytes, int, or float for XADD
            cleaned_message_data = {
                k: (json.dumps(v) if isinstance(v, (dict, list)) else str(v))
                for k, v in message_data.items()
            }
            
            msg_id = client.xadd(
                stream_name,
                cleaned_message_data,
                maxlen=max_len if max_len is not None else 10000,
                approximate=True
            )
            logger.debug(f"Produced message {msg_id} to stream {stream_name}")
            return msg_id
            
        except Exception as e:
            logger.error(f"Error producing to stream {stream_name}: {e}")
            return None
    
    def create_consumer_group(self, stream_name: str, group_name: str, create_stream_if_not_exists: bool = True) -> bool:
        """Create a consumer group for a stream. Idempotent."""
        if not self.is_available():
            logger.error("Redis not available, cannot create consumer group.")
            return False
            
        try:
            client = self.get_client()
            client.xgroup_create(
                name=stream_name,
                groupname=group_name,
                id='0',  # Start from the beginning of the stream
                mkstream=create_stream_if_not_exists
            )
            logger.info(f"Consumer group {group_name} created for stream {stream_name}.")
            return True
            
        except redis.exceptions.ResponseError as e:
            if "BUSYGROUP" in str(e):
                logger.debug(f"Consumer group {group_name} already exists for stream {stream_name}.")
                return True
            logger.error(f"Error creating consumer group {group_name} for {stream_name}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error creating consumer group {group_name} for {stream_name}: {e}")
            return False

    # Pydantic-aware cache operations
    def get_cached_model(self, key: str, model_class: type[BaseCacheModel]) -> Optional[BaseCacheModel]:
        """
        Get cached value and deserialize to Pydantic model with validation.
        
        Args:
            key: Cache key
            model_class: Pydantic model class to deserialize to
            
        Returns:
            Validated Pydantic model instance or None
        """
        try:
            client = self.get_client()
            value = client.get(key)
            if value:
                try:
                    # Deserialize JSON and validate with Pydantic
                    data = json.loads(value)
                    model_instance = model_class(**data)
                    
                    # Check if cache entry is still valid
                    if model_instance.is_valid():
                        # Update access tracking
                        model_instance.metadata.update_access()
                        # Re-cache with updated metadata
                        self.set_cached_model(key, model_instance)
                        return model_instance
                    else:
                        # Cache expired, delete it
                        self.delete(key)
                        logger.debug(f"Deleted expired cache entry: {key}")
                        return None
                        
                except (json.JSONDecodeError, ValidationError) as e:
                    logger.warning(f"Failed to deserialize cached model for key {key}: {e}")
                    # Delete corrupted cache entry
                    self.delete(key)
                    return None
        except Exception as e:
            logger.error(f"Redis get_cached_model error for key {key}: {e}")
            return None
    
    def set_cached_model(self, key: str, model: BaseCacheModel, ttl: Optional[int] = None) -> bool:
        """
        Set Pydantic model in cache with automatic serialization and validation.
        
        Args:
            key: Cache key
            model: Pydantic model instance
            ttl: Optional TTL override (uses model metadata TTL if not provided)
            
        Returns:
            True if successful
        """
        try:
            client = self.get_client()
            
            # Use model's TTL if not provided
            if ttl is None and model.metadata.ttl_seconds:
                ttl = model.metadata.ttl_seconds
            
            # Serialize model to JSON
            serialized = model.model_dump_json()
            
            if ttl:
                success = client.setex(key, ttl, serialized)
            else:
                success = client.set(key, serialized)
            
            if success:
                # Record cache set operation
                cache_type = self._extract_cache_type_from_key(key)
                self._metrics.record_set(cache_type)
                logger.debug(f"Cached model {model.__class__.__name__} with key: {key}")
            
            return bool(success)
            
        except Exception as e:
            logger.error(f"Redis set_cached_model error for key {key}: {e}")
            return False
    
    def get_or_create_cached_model(self, key: str, model_class: type[BaseCacheModel], 
                                 factory_func: Callable[[], BaseCacheModel], 
                                 ttl: Optional[int] = None) -> Optional[BaseCacheModel]:
        """
        Get cached model or create it using factory function if not found.
        
        Args:
            key: Cache key
            model_class: Pydantic model class
            factory_func: Function to create model if not cached
            ttl: Optional TTL for new cache entry
            
        Returns:
            Cached or newly created model instance
        """
        # Try to get from cache first
        cached_model = self.get_cached_model(key, model_class)
        if cached_model:
            return cached_model
        
        # Create new model using factory
        try:
            new_model = factory_func()
            if new_model:
                self.set_cached_model(key, new_model, ttl)
                return new_model
        except Exception as e:
            logger.error(f"Failed to create model for key {key}: {e}")
        
        return None
    
    def invalidate_by_tags(self, tags: List[str]) -> int:
        """
        Invalidate cache entries by tags using pattern matching.
        
        Args:
            tags: List of tags to invalidate
            
        Returns:
            Number of keys deleted
        """
        if not self.is_available():
            return 0
        
        deleted_count = 0
        try:
            client = self.get_client()
            
            # Build patterns for each tag
            patterns = []
            for tag in tags:
                patterns.extend([
                    f"*:{tag}:*",
                    f"{tag}:*",
                    f"*:{tag}"
                ])
            
            # Scan and delete matching keys
            for pattern in patterns:
                for key in client.scan_iter(match=pattern):
                    if client.delete(key):
                        deleted_count += 1
                        logger.debug(f"Invalidated cache key by tag: {key}")
            
            logger.info(f"Invalidated {deleted_count} cache keys for tags: {tags}")
            return deleted_count
            
        except Exception as e:
            logger.error(f"Error invalidating cache by tags {tags}: {e}")
            return 0
    
    def batch_get_cached_models(self, keys_and_classes: List[Tuple[str, type[BaseCacheModel]]]) -> Dict[str, Optional[BaseCacheModel]]:
        """
        Get multiple cached models in a single pipeline operation.
        
        Args:
            keys_and_classes: List of (key, model_class) tuples
            
        Returns:
            Dictionary mapping keys to model instances (or None if not found/invalid)
        """
        if not self.is_available():
            return {}
        
        try:
            client = self.get_client()
            pipe = client.pipeline()
            
            # Queue all get operations
            for key, _ in keys_and_classes:
                pipe.get(key)
            
            # Execute pipeline
            results = pipe.execute()
            
            # Process results
            output = {}
            for (key, model_class), value in zip(keys_and_classes, results):
                if value is not None:
                    try:
                        data = json.loads(value)
                        model_instance = model_class(**data)
                        
                        if model_instance.is_valid():
                            output[key] = model_instance
                            self._metrics.record_hit(self._extract_cache_type_from_key(key))
                        else:
                            # Expired, schedule for deletion
                            client.delete(key)
                            output[key] = None
                            self._metrics.record_miss(self._extract_cache_type_from_key(key))
                    except (json.JSONDecodeError, ValidationError) as e:
                        logger.warning(f"Failed to deserialize model for key {key}: {e}")
                        client.delete(key)  # Clean up corrupted entry
                        output[key] = None
                        self._metrics.record_miss(self._extract_cache_type_from_key(key))
                else:
                    output[key] = None
                    self._metrics.record_miss(self._extract_cache_type_from_key(key))
            
            return output
            
        except Exception as e:
            logger.error(f"Redis batch_get_cached_models error: {e}")
            return {}
    
    def batch_set_cached_models(self, models_and_keys: List[Tuple[str, BaseCacheModel]], ttl: Optional[int] = None) -> bool:
        """
        Set multiple cached models in a single pipeline operation.
        
        Args:
            models_and_keys: List of (key, model) tuples
            ttl: Optional TTL for all models (uses individual model TTL if not provided)
            
        Returns:
            True if all operations successful
        """
        if not self.is_available():
            return False
        
        try:
            client = self.get_client()
            pipe = client.pipeline()
            
            # Queue all set operations
            for key, model in models_and_keys:
                model_ttl = ttl or model.metadata.ttl_seconds
                serialized = model.model_dump_json()
                
                if model_ttl:
                    pipe.setex(key, model_ttl, serialized)
                else:
                    pipe.set(key, serialized)
            
            # Execute pipeline
            results = pipe.execute()
            success = all(results)
            
            if success:
                # Record metrics for all successful operations
                for key, _ in models_and_keys:
                    cache_type = self._extract_cache_type_from_key(key)
                    self._metrics.record_set(cache_type)
            
            return success
            
        except Exception as e:
            logger.error(f"Redis batch_set_cached_models error: {e}")
            return False
    
    def _extract_cache_type_from_key(self, key: str) -> str:
        """Extract cache type from cache key for metrics."""
        try:
            # Extract first part of key as cache type
            parts = key.split(':')
            if len(parts) >= 2:
                return parts[0]
            return 'unknown'
        except:
            return 'unknown'
    
    # Enhanced cache operations with automatic invalidation
    def set_cached_with_auto_invalidation(self, key: str, value: Any, ttl: Optional[int] = None, 
                                        invalidation_tags: List[str] = None) -> bool:
        """
        Set cached value with automatic invalidation tags.
        
        Args:
            key: Cache key
            value: Value to cache (Pydantic model or serializable data)
            ttl: Time to live in seconds
            invalidation_tags: Tags for automatic invalidation
            
        Returns:
            True if successful
        """
        try:
            # Set the main cache entry
            if isinstance(value, BaseModel):
                success = self.set_cached_model(key, value, ttl)
            else:
                success = self.set_cached(key, value, ttl)
            
            # Set invalidation tags if provided
            if success and invalidation_tags:
                client = self.get_client()
                tag_ttl = ttl or 86400  # Default 24 hours for tags
                
                for tag in invalidation_tags:
                    tag_key = f"tag:{tag}:keys"
                    client.sadd(tag_key, key)
                    client.expire(tag_key, tag_ttl)
            
            return success
            
        except Exception as e:
            logger.error(f"Error setting cache with auto-invalidation for key {key}: {e}")
            return False
    
    def invalidate_by_tag_sets(self, tags: List[str]) -> int:
        """
        Invalidate cache entries using tag sets for more efficient invalidation.
        
        Args:
            tags: List of tags to invalidate
            
        Returns:
            Number of keys deleted
        """
        if not self.is_available():
            return 0
        
        deleted_count = 0
        try:
            client = self.get_client()
            
            # Get all keys associated with tags
            keys_to_delete = set()
            for tag in tags:
                tag_key = f"tag:{tag}:keys"
                tagged_keys = client.smembers(tag_key)
                keys_to_delete.update(tagged_keys)
                # Also delete the tag set itself
                client.delete(tag_key)
            
            # Delete all tagged keys
            if keys_to_delete:
                deleted_count = client.delete(*keys_to_delete)
                logger.info(f"Invalidated {deleted_count} cache keys for tags: {tags}")
            
            return deleted_count
            
        except Exception as e:
            logger.error(f"Error invalidating cache by tag sets {tags}: {e}")
            return 0


class CacheMetrics:
    """Track cache performance metrics."""
    
    def __init__(self, redis_manager):
        self.redis_mgr = redis_manager
        self.metrics_key = "cache:metrics"
        
    def record_hit(self, cache_type: str):
        """Record a cache hit."""
        try:
            if self.redis_mgr.is_available():
                client = self.redis_mgr.get_client()
                client.hincrby(f"{self.metrics_key}:{cache_type}", "hits", 1)
                client.hincrby(f"{self.metrics_key}:total", "hits", 1)
        except Exception as e:
            logger.debug(f"Error recording cache hit: {e}")
            
    def record_miss(self, cache_type: str):
        """Record a cache miss."""
        try:
            if self.redis_mgr.is_available():
                client = self.redis_mgr.get_client()
                client.hincrby(f"{self.metrics_key}:{cache_type}", "misses", 1)
                client.hincrby(f"{self.metrics_key}:total", "misses", 1)
        except Exception as e:
            logger.debug(f"Error recording cache miss: {e}")
            
    def record_set(self, cache_type: str):
        """Record a cache set operation."""
        try:
            if self.redis_mgr.is_available():
                client = self.redis_mgr.get_client()
                client.hincrby(f"{self.metrics_key}:{cache_type}", "sets", 1)
                client.hincrby(f"{self.metrics_key}:total", "sets", 1)
        except Exception as e:
            logger.debug(f"Error recording cache set: {e}")
            
    def get_metrics(self, cache_type: str = None) -> Dict:
        """Get cache metrics."""
        if not self.redis_mgr.is_available():
            return {'error': 'Redis not available'}
            
        try:
            client = self.redis_mgr.get_client()
            
            if cache_type:
                key = f"{self.metrics_key}:{cache_type}"
            else:
                key = f"{self.metrics_key}:total"
                
            metrics = client.hgetall(key)
            
            hits = int(metrics.get('hits', 0))
            misses = int(metrics.get('misses', 0))
            sets = int(metrics.get('sets', 0))
            total_requests = hits + misses
            
            return {
                'hits': hits,
                'misses': misses,
                'sets': sets,
                'total_requests': total_requests,
                'hit_rate': round(hits / total_requests * 100, 2) if total_requests > 0 else 0
            }
        except Exception as e:
            logger.error(f"Error getting cache metrics: {e}")
            return {'error': str(e)}
    
    def reset_metrics(self, cache_type: str = None):
        """Reset cache metrics."""
        if not self.redis_mgr.is_available():
            return
            
        try:
            client = self.redis_mgr.get_client()
            
            if cache_type:
                client.delete(f"{self.metrics_key}:{cache_type}")
            else:
                # Reset all metrics
                for key in client.scan_iter(match=f"{self.metrics_key}:*"):
                    client.delete(key)
        except Exception as e:
            logger.error(f"Error resetting cache metrics: {e}")


# Decorators
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
                    cache_type = CacheKeys.get_cache_type_from_key(cache_key)
                    redis_mgr._metrics.record_hit(cache_type)
                    return cached_value
                
                # Record cache miss
                cache_type = CacheKeys.get_cache_type_from_key(cache_key)
                redis_mgr._metrics.record_miss(cache_type)
                
                # Execute function
                result = func(*args, **kwargs)
                
                # Cache result
                redis_mgr.set_cached(cache_key, result, ttl)
                redis_mgr._metrics.record_set(cache_type)
                logger.debug(f"Cached result for {cache_key}")
                
                return result
                
            except Exception as e:
                logger.error(f"Redis cache error in {func.__name__}: {e}")
                # Fall back to executing function without cache
                return func(*args, **kwargs)
        
        return wrapper
    return decorator


def with_redis_lock(lock_name_func: Callable, timeout: Optional[int] = None):
    """
    Decorator for executing function with distributed lock.
    
    Args:
        lock_name_func: Function to generate lock name from arguments
        timeout: Lock timeout in seconds
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
                
                lock_name = lock_name_func(*args, **kwargs)
                
                with redis_mgr.lock(lock_name, timeout=timeout):
                    return func(*args, **kwargs)
                    
            except Exception as e:
                logger.error(f"Redis lock error in {func.__name__}: {e}")
                # Fall back to executing function without lock
                return func(*args, **kwargs)
        
        return wrapper
    return decorator


def rate_limit(key: str, limit: int, window: int, wait: bool = True, max_wait: int = 60):
    """
    Decorator for rate limiting function calls.
    
    Args:
        key: Rate limit key prefix
        limit: Maximum number of calls allowed
        window: Time window in seconds
        wait: Whether to wait if rate limit exceeded
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
                
                # Generate rate limit key
                rate_key = f"rate_limit:{key}:{func.__name__}"
                
                # Check rate limit with retries
                start_time = time.time()
                while True:
                    if redis_mgr.check_rate_limit(rate_key, limit, window):
                        # Within rate limit, proceed
                        return func(*args, **kwargs)
                    
                    if not wait:
                        raise RuntimeError(f"Rate limit exceeded for {func.__name__}")
                    
                    # Calculate wait time
                    elapsed = time.time() - start_time
                    if elapsed >= max_wait:
                        raise RuntimeError(f"Rate limit wait timeout for {func.__name__}")
                    
                    # Wait with exponential backoff
                    wait_time = min(2 ** (elapsed / 10), 10)  # Max 10 seconds per wait
                    logger.warning(f"Rate limit exceeded for {func.__name__}, waiting {wait_time:.1f}s...")
                    time.sleep(wait_time)
                    
            except RuntimeError:
                raise
            except Exception as e:
                logger.error(f"Rate limit error in {func.__name__}: {e}")
                # Fall back to executing function without rate limit
                return func(*args, **kwargs)
        
        return wrapper
    return decorator


# Singleton instance
_redis_manager = None

def get_redis_manager() -> RedisManager:
    """Get singleton Redis manager instance."""
    global _redis_manager
    if _redis_manager is None:
        _redis_manager = RedisManager()
    return _redis_manager