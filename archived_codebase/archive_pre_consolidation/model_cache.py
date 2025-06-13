"""
Intelligent Model Cache for Pydantic models with Redis backend.
Provides automatic serialization/deserialization and TTL management.
"""
import json
import hashlib
from typing import Type, TypeVar, Optional, Dict, Any, Union
from datetime import datetime, timedelta
from pydantic import BaseModel

from scripts.redis_utils import RedisManager
from scripts.core.json_serializer import PydanticJSONEncoder

T = TypeVar('T', bound=BaseModel)


class IntelligentModelCache:
    """Cache manager for Pydantic models with automatic serialization."""
    
    def __init__(self, redis_manager: RedisManager, default_ttl: int = 3600):
        """
        Initialize the model cache.
        
        Args:
            redis_manager: Redis connection manager
            default_ttl: Default TTL in seconds (1 hour)
        """
        self.redis_manager = redis_manager
        self.default_ttl = default_ttl
        self._cache_prefix = "model_cache"
    
    def _generate_cache_key(self, model: BaseModel, prefix: Optional[str] = None) -> str:
        """
        Generate a cache key for a model based on its content.
        
        Args:
            model: Pydantic model instance
            prefix: Optional prefix for the cache key
            
        Returns:
            Cache key string
        """
        # Serialize model to ensure consistent key generation
        model_json = json.dumps(
            model.model_dump(mode='json'),
            sort_keys=True,
            cls=PydanticJSONEncoder
        )
        
        # Generate hash of the content
        content_hash = hashlib.md5(model_json.encode()).hexdigest()[:16]
        
        # Build key components
        key_parts = [self._cache_prefix]
        if prefix:
            key_parts.append(prefix)
        key_parts.extend([
            model.__class__.__name__,
            content_hash
        ])
        
        return ":".join(key_parts)
    
    def cache_model(
        self, 
        model: T, 
        ttl: Optional[int] = None,
        prefix: Optional[str] = None,
        custom_key: Optional[str] = None
    ) -> str:
        """
        Cache a Pydantic model.
        
        Args:
            model: Pydantic model instance to cache
            ttl: Time to live in seconds (uses default if not specified)
            prefix: Optional prefix for organization
            custom_key: Use a custom key instead of generating one
            
        Returns:
            The cache key used
        """
        # Generate or use provided key
        cache_key = custom_key or self._generate_cache_key(model, prefix)
        
        # Serialize the model
        model_data = {
            "_model_class": f"{model.__class__.__module__}.{model.__class__.__name__}",
            "_cached_at": datetime.utcnow().isoformat(),
            "_ttl": ttl or self.default_ttl,
            "data": model.model_dump(mode='json')
        }
        
        # Store in Redis - RedisManager handles serialization
        self.redis_manager.set_cached(
            cache_key, 
            model_data,  # Pass dict, not serialized string
            ttl=ttl or self.default_ttl
        )
        
        return cache_key
    
    def get_model(
        self, 
        cache_key: str, 
        model_class: Type[T],
        validate: bool = True
    ) -> Optional[T]:
        """
        Retrieve a cached model.
        
        Args:
            cache_key: The cache key
            model_class: Expected model class for validation
            validate: Whether to validate the model class matches
            
        Returns:
            The model instance or None if not found/invalid
        """
        # Get from Redis
        cached_data = self.redis_manager.get_cached(cache_key)
        if not cached_data:
            return None
        
        try:
            # RedisManager already deserializes
            model_data = cached_data if isinstance(cached_data, dict) else json.loads(cached_data)
            
            # Validate model class if requested
            if validate:
                expected_class = f"{model_class.__module__}.{model_class.__name__}"
                if model_data.get("_model_class") != expected_class:
                    return None
            
            # Reconstruct the model
            return model_class(**model_data["data"])
            
        except (json.JSONDecodeError, KeyError, ValueError):
            return None
    
    def invalidate(self, cache_key: str) -> bool:
        """
        Invalidate a cached model.
        
        Args:
            cache_key: The cache key to invalidate
            
        Returns:
            True if the key was deleted, False otherwise
        """
        return bool(self.redis_manager.get_client().delete(cache_key))
    
    def invalidate_pattern(self, pattern: str) -> int:
        """
        Invalidate all keys matching a pattern.
        
        Args:
            pattern: Redis pattern (e.g., "model_cache:DocumentModel:*")
            
        Returns:
            Number of keys deleted
        """
        client = self.redis_manager.get_client()
        keys = client.keys(pattern)
        if keys:
            return client.delete(*keys)
        return 0
    
    def get_cache_stats(self, model_class: Optional[Type[BaseModel]] = None) -> Dict[str, Any]:
        """
        Get cache statistics.
        
        Args:
            model_class: Optional model class to filter stats
            
        Returns:
            Dictionary with cache statistics
        """
        pattern = f"{self._cache_prefix}:*"
        if model_class:
            pattern = f"{self._cache_prefix}:*:{model_class.__name__}:*"
        
        keys = self.redis_manager.get_client().keys(pattern)
        
        total_size = 0
        oldest_cached = None
        newest_cached = None
        
        for key in keys:
            data = self.redis_manager.get_cached(key)
            if data:
                # Convert to string to get size
                data_str = json.dumps(data) if isinstance(data, dict) else str(data)
                total_size += len(data_str)
                try:
                    model_data = data if isinstance(data, dict) else json.loads(data)
                    cached_at = datetime.fromisoformat(model_data.get("_cached_at", ""))
                    
                    if oldest_cached is None or cached_at < oldest_cached:
                        oldest_cached = cached_at
                    if newest_cached is None or cached_at > newest_cached:
                        newest_cached = cached_at
                except:
                    pass
        
        return {
            "total_entries": len(keys),
            "total_size_bytes": total_size,
            "oldest_cached": oldest_cached.isoformat() if oldest_cached else None,
            "newest_cached": newest_cached.isoformat() if newest_cached else None,
            "pattern": pattern
        }
    
    def batch_cache_models(
        self,
        models: Dict[str, T],
        ttl: Optional[int] = None
    ) -> Dict[str, str]:
        """
        Cache multiple models in a batch operation.
        
        Args:
            models: Dictionary of {identifier: model}
            ttl: Time to live for all models
            
        Returns:
            Dictionary of {identifier: cache_key}
        """
        cache_keys = {}
        pipe = self.redis_manager.get_client().pipeline()
        
        for identifier, model in models.items():
            cache_key = self._generate_cache_key(model)
            
            model_data = {
                "_model_class": f"{model.__class__.__module__}.{model.__class__.__name__}",
                "_cached_at": datetime.utcnow().isoformat(),
                "_ttl": ttl or self.default_ttl,
                "data": model.model_dump(mode='json')
            }
            
            # Serialize for pipeline operation
            serialized = json.dumps(model_data, cls=PydanticJSONEncoder)
            pipe.setex(cache_key, ttl or self.default_ttl, serialized)
            cache_keys[identifier] = cache_key
        
        pipe.execute()
        return cache_keys