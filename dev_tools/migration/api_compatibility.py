#!/usr/bin/env python3
"""
API Compatibility Layer
Bridges old and new APIs to fix integration issues without breaking existing code.
This is a temporary solution while we update all callers.
"""

import os
import logging
from contextlib import contextmanager
from typing import Any, Optional, Union
from uuid import uuid4

logger = logging.getLogger(__name__)

# ========== Database Compatibility ==========

@contextmanager
def get_db_session():
    """
    Wrapper to provide context manager interface for get_db().
    Allows using: with get_db_session() as session:
    """
    from scripts.db import get_db
    
    session = next(get_db())
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ========== Redis Compatibility ==========

class RedisCompatibilityWrapper:
    """Wrapper to provide old Redis API while using new implementation"""
    
    def __init__(self, redis_manager):
        self.manager = redis_manager
        self.client = redis_manager.client if hasattr(redis_manager, 'client') else redis_manager
    
    def set(self, key: str, value: Any, ex: Optional[int] = None) -> bool:
        """Old set method mapping to new set_cached"""
        try:
            if hasattr(self.manager, 'set_cached'):
                return self.manager.set_cached(key, value, ttl=ex)
            else:
                # Direct Redis client
                if ex:
                    return self.client.setex(key, ex, value)
                return self.client.set(key, value)
        except Exception as e:
            logger.error(f"Redis set error: {e}")
            return False
    
    def get(self, key: str) -> Optional[Any]:
        """Old get method mapping to new get_cached"""
        try:
            if hasattr(self.manager, 'get_cached'):
                return self.manager.get_cached(key)
            else:
                # Direct Redis client
                return self.client.get(key)
        except Exception as e:
            logger.error(f"Redis get error: {e}")
            return None
    
    def delete(self, key: str) -> bool:
        """Delete method"""
        try:
            if hasattr(self.manager, 'delete'):
                return self.manager.delete(key)
            else:
                return self.client.delete(key) > 0
        except Exception as e:
            logger.error(f"Redis delete error: {e}")
            return False
    
    def exists(self, key: str) -> bool:
        """Check if key exists"""
        try:
            if hasattr(self.manager, 'exists'):
                return self.manager.exists(key)
            else:
                return self.client.exists(key) > 0
        except Exception as e:
            logger.error(f"Redis exists error: {e}")
            return False
    
    def __getattr__(self, name):
        """Pass through other methods to the manager or client"""
        if hasattr(self.manager, name):
            return getattr(self.manager, name)
        elif hasattr(self.client, name):
            return getattr(self.client, name)
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")


def get_redis_client():
    """
    Get Redis client with old API compatibility.
    Maps to new get_redis_manager() but provides old interface.
    """
    from scripts.cache import get_redis_manager
    manager = get_redis_manager()
    return RedisCompatibilityWrapper(manager)


# ========== S3 Compatibility ==========

class S3CompatibilityWrapper:
    """Wrapper to provide old S3 API while using new implementation"""
    
    def __init__(self, s3_manager):
        self.manager = s3_manager
    
    def upload_document(self, file_path: str, key: str) -> bool:
        """
        Old upload method - extract UUID from key.
        Expected key format: "project_uuid/doc_uuid/filename"
        """
        try:
            # Parse key to extract UUIDs
            parts = key.split('/')
            
            if len(parts) >= 3:
                project_uuid = parts[0]
                doc_uuid = parts[1]
                # filename = parts[2]
            elif len(parts) >= 2:
                project_uuid = "default-project"
                doc_uuid = parts[0]
            else:
                # Fallback - generate UUIDs
                project_uuid = str(uuid4())
                doc_uuid = str(uuid4())
                logger.warning(f"Could not parse key '{key}', using generated UUIDs")
            
            # Call new method
            result = self.manager.upload_document_with_uuid_naming(
                file_path, doc_uuid, project_uuid
            )
            
            # Return boolean for compatibility
            return result is not None
            
        except Exception as e:
            logger.error(f"S3 upload compatibility error: {e}")
            return False
    
    def download_document(self, key: str, local_path: str) -> bool:
        """Old download method"""
        try:
            if hasattr(self.manager, 'download_file'):
                return self.manager.download_file(key, local_path)
            else:
                # Try direct S3 client
                self.manager.s3_client.download_file(
                    self.manager.bucket_name, key, local_path
                )
                return True
        except Exception as e:
            logger.error(f"S3 download error: {e}")
            return False
    
    def __getattr__(self, name):
        """Pass through other methods"""
        return getattr(self.manager, name)


def get_s3_client():
    """
    Get S3 client with old API compatibility.
    """
    from scripts.s3_storage import S3StorageManager
    manager = S3StorageManager()
    return S3CompatibilityWrapper(manager)


# ========== Entity Service Compatibility ==========

class EntityExtractionService:
    """
    Compatibility wrapper for old EntityExtractionService name.
    Maps to new EntityService.
    """
    
    def __init__(self, *args, **kwargs):
        from scripts.entity_service import EntityService
        self.service = EntityService(*args, **kwargs)
    
    def __getattr__(self, name):
        """Pass through all methods to new EntityService"""
        return getattr(self.service, name)


# ========== SQL Compatibility ==========

def wrap_sql_query(query: str) -> Any:
    """
    Wrap raw SQL string with text() for SQLAlchemy 2.0.
    Handles the case where raw strings are passed to execute().
    """
    from sqlalchemy import text
    
    if isinstance(query, str):
        return text(query)
    return query


# ========== Export Compatibility Functions ==========

__all__ = [
    'get_db_session',
    'get_redis_client', 
    'get_s3_client',
    'RedisCompatibilityWrapper',
    'S3CompatibilityWrapper',
    'EntityExtractionService',
    'wrap_sql_query'
]