"""
Shared utilities for Celery tasks.
"""

import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any, Tuple

from cache_keys import CacheKeys
from redis_utils import get_redis_manager

logger = logging.getLogger(__name__)


def update_document_state(document_uuid: str, phase: str, status: str, metadata: Dict[str, Any] = None):
    """Update document processing state in Redis."""
    try:
        redis_mgr = get_redis_manager()
        if redis_mgr and redis_mgr.is_available():
            state_key = CacheKeys.format_key(CacheKeys.DOC_STATE, document_uuid=document_uuid)
            
            # Update specific phase status
            redis_mgr.hset(state_key, f"{phase}_status", status)
            redis_mgr.hset(state_key, f"{phase}_timestamp", datetime.now().isoformat())
            
            if metadata:
                redis_mgr.hset(state_key, f"{phase}_metadata", json.dumps(metadata))
            
            # Set expiration to 7 days
            redis_mgr.get_client().expire(state_key, 7 * 24 * 3600)
            
            logger.debug(f"Updated state for {document_uuid}: {phase}={status}")
    except Exception as e:
        logger.warning(f"Failed to update document state in Redis: {e}")


def check_stage_completed(document_uuid: str, phase: str, processing_version: int = None) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """
    Check if a processing stage is already completed.
    
    Args:
        document_uuid: UUID of the document
        phase: Processing phase to check (e.g., 'ocr', 'doc_node_creation', 'chunking', etc.)
        processing_version: Optional processing version to check against
    
    Returns:
        Tuple of (is_completed, cached_results)
    """
    try:
        redis_mgr = get_redis_manager()
        if not redis_mgr or not redis_mgr.is_available():
            return False, None
        
        # Check state
        state_key = CacheKeys.format_key(CacheKeys.DOC_STATE, document_uuid=document_uuid)
        phase_status = redis_mgr.hget(state_key, f"{phase}_status")
        
        if phase_status != "completed":
            return False, None
        
        # Check if we have cached results for this phase
        cached_results = None
        if phase == "ocr":
            cache_key = CacheKeys.format_key(
                CacheKeys.DOC_OCR_RESULT,
                version=processing_version,
                document_uuid=document_uuid
            ) if processing_version else CacheKeys.format_key(CacheKeys.DOC_OCR_RESULT, document_uuid=document_uuid)
            cached_results = redis_mgr.get_cached(cache_key)
        elif phase == "doc_node_creation":
            cache_key = CacheKeys.format_key(
                CacheKeys.DOC_CLEANED_TEXT,
                version=processing_version,
                document_uuid=document_uuid
            ) if processing_version else CacheKeys.format_key(CacheKeys.DOC_CLEANED_TEXT, document_uuid=document_uuid)
            cached_results = redis_mgr.get_cached(cache_key)
        elif phase == "chunking":
            cache_key = CacheKeys.format_key(
                CacheKeys.DOC_CHUNKS_LIST,
                version=processing_version,
                document_uuid=document_uuid
            ) if processing_version else CacheKeys.format_key(CacheKeys.DOC_CHUNKS_LIST, document_uuid=document_uuid)
            cached_results = redis_mgr.get_cached(cache_key)
        elif phase == "ner":
            cache_key = CacheKeys.format_key(
                CacheKeys.DOC_ALL_EXTRACTED_MENTIONS,
                version=processing_version,
                document_uuid=document_uuid
            ) if processing_version else CacheKeys.format_key(CacheKeys.DOC_ALL_EXTRACTED_MENTIONS, document_uuid=document_uuid)
            cached_results = redis_mgr.get_cached(cache_key)
        elif phase == "resolution":
            cache_key = CacheKeys.format_key(
                CacheKeys.DOC_CANONICAL_ENTITIES,
                version=processing_version,
                document_uuid=document_uuid
            ) if processing_version else CacheKeys.format_key(CacheKeys.DOC_CANONICAL_ENTITIES, document_uuid=document_uuid)
            cached_results = redis_mgr.get_cached(cache_key)
        
        return True, cached_results
    except Exception as e:
        logger.warning(f"Failed to check stage completion: {e}")
        return False, None


def atomic_cache_update(document_uuid: str, phase: str, data: Dict[str, Any], 
                       processing_version: int = None, ttl: int = None) -> bool:
    """
    Atomically update cache for a processing phase with distributed locking.
    
    Args:
        document_uuid: UUID of the document
        phase: Processing phase (e.g., 'ocr', 'chunking', etc.)
        data: Data to cache
        processing_version: Optional processing version
        ttl: Optional TTL in seconds
    
    Returns:
        True if update successful, False otherwise
    """
    try:
        redis_mgr = get_redis_manager()
        if not redis_mgr or not redis_mgr.is_available():
            return False
        
        # Determine cache key based on phase
        cache_key = None
        default_ttl = 3 * 24 * 3600  # 3 days default
        
        if phase == "ocr":
            cache_key = CacheKeys.format_key(
                CacheKeys.DOC_OCR_RESULT,
                version=processing_version,
                document_uuid=document_uuid
            ) if processing_version else CacheKeys.format_key(CacheKeys.DOC_OCR_RESULT, document_uuid=document_uuid)
            default_ttl = 7 * 24 * 3600  # 7 days for OCR
        elif phase == "doc_node_creation":
            cache_key = CacheKeys.format_key(
                CacheKeys.DOC_CLEANED_TEXT,
                version=processing_version,
                document_uuid=document_uuid
            ) if processing_version else CacheKeys.format_key(CacheKeys.DOC_CLEANED_TEXT, document_uuid=document_uuid)
        elif phase == "chunking":
            cache_key = CacheKeys.format_key(
                CacheKeys.DOC_CHUNKS_LIST,
                version=processing_version,
                document_uuid=document_uuid
            ) if processing_version else CacheKeys.format_key(CacheKeys.DOC_CHUNKS_LIST, document_uuid=document_uuid)
            default_ttl = 2 * 24 * 3600  # 2 days for chunks
        elif phase == "ner":
            cache_key = CacheKeys.format_key(
                CacheKeys.DOC_ALL_EXTRACTED_MENTIONS,
                version=processing_version,
                document_uuid=document_uuid
            ) if processing_version else CacheKeys.format_key(CacheKeys.DOC_ALL_EXTRACTED_MENTIONS, document_uuid=document_uuid)
            default_ttl = 2 * 24 * 3600  # 2 days for mentions
        elif phase == "resolution":
            cache_key = CacheKeys.format_key(
                CacheKeys.DOC_CANONICAL_ENTITIES,
                version=processing_version,
                document_uuid=document_uuid
            ) if processing_version else CacheKeys.format_key(CacheKeys.DOC_CANONICAL_ENTITIES, document_uuid=document_uuid)
        
        if not cache_key:
            return False
        
        # Use provided TTL or default
        cache_ttl = ttl if ttl is not None else default_ttl
        
        # Use distributed lock for atomic update
        lock_key = f"lock:cache_update:{document_uuid}:{phase}"
        with redis_mgr.lock(lock_key, timeout=10):
            # Update cache
            redis_mgr.set_cached(cache_key, data, ttl=cache_ttl)
            
            # Update state to indicate completion
            update_document_state(document_uuid, phase, "completed", {"cache_key": cache_key})
            
            logger.debug(f"Atomically cached data for {document_uuid}:{phase} with TTL {cache_ttl}s")
            return True
            
    except Exception as e:
        logger.warning(f"Failed to atomically update cache: {e}")
        return False


def acquire_processing_lock(document_uuid: str, phase: str, timeout: int = 600) -> Optional[Any]:
    """
    Acquire a processing lock for a document phase to prevent concurrent processing.
    
    Args:
        document_uuid: UUID of the document
        phase: Processing phase
        timeout: Lock timeout in seconds (default 10 minutes)
    
    Returns:
        Lock object if acquired, None otherwise
    """
    try:
        redis_mgr = get_redis_manager()
        if not redis_mgr or not redis_mgr.is_available():
            return None
        
        lock_key = f"processing_lock:{document_uuid}:{phase}"
        client = redis_mgr.get_client()
        lock = client.lock(lock_key, timeout=timeout, blocking_timeout=0)
        
        if lock.acquire(blocking=False):
            logger.debug(f"Acquired processing lock for {document_uuid}:{phase}")
            return lock
        else:
            logger.warning(f"Could not acquire processing lock for {document_uuid}:{phase} - another task is processing")
            return None
            
    except Exception as e:
        logger.warning(f"Failed to acquire processing lock: {e}")
        return None


def release_processing_lock(lock: Any):
    """Release a processing lock."""
    if lock:
        try:
            if hasattr(lock, 'owned') and lock.owned():
                lock.release()
                logger.debug("Released processing lock")
        except Exception as e:
            logger.warning(f"Failed to release processing lock: {e}")


def update_status_on_cache_hit(document_uuid: str, stage: str, db_manager) -> None:
    """
    Update database status when serving from cache.
    
    Args:
        document_uuid: UUID of the document
        stage: Processing stage that was cached
        db_manager: SupabaseManager instance
    """
    status_map = {
        'ocr': 'ocr_complete',
        'text': 'text_complete',
        'entity': 'entity_complete',
        'resolution': 'resolution_complete',
        'graph': 'completed'
    }
    
    try:
        # Get current status
        current = db_manager.client.table('source_documents').select(
            'id', 'celery_status'
        ).eq('document_uuid', document_uuid).single().execute()
        
        if current.data:
            new_status = status_map.get(stage)
            if new_status and current.data['celery_status'] != new_status:
                db_manager.client.table('source_documents').update({
                    'celery_status': new_status,
                    'last_modified_at': datetime.now().isoformat()
                }).eq('id', current.data['id']).execute()
                
                logger.info(f"Updated status from cache hit: {document_uuid} -> {new_status}")
                
    except Exception as e:
        logger.warning(f"Failed to update status on cache hit: {e}")