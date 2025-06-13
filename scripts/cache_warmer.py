"""
Cache warming strategies for batch processing optimization.

This module provides pre-processing cache warming to improve batch performance
by pre-loading frequently accessed data before batch processing begins.
"""

import logging
from typing import Dict, Any, List, Set, Optional
from datetime import datetime, timedelta
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json

from celery import group
from scripts.celery_app import app
from scripts.cache import get_redis_manager, CacheKeys
from scripts.config import REDIS_PREFIX_BATCH
from scripts.db import DatabaseManager
from scripts.models import (
    SourceDocumentMinimal, ProjectMinimal, DocumentChunkMinimal,
    EntityMentionMinimal, CanonicalEntityMinimal
)

logger = logging.getLogger(__name__)


class CacheWarmer:
    """Manages cache warming strategies for batch processing."""
    
    def __init__(self):
        self.redis_manager = get_redis_manager()
        self.db_manager = DatabaseManager(validate_conformance=False)
        self.executor = ThreadPoolExecutor(max_workers=10)
        
    def analyze_batch_access_patterns(self, batch_manifest: Dict[str, Any]) -> Dict[str, Set[str]]:
        """
        Analyze batch to predict data access patterns.
        
        Args:
            batch_manifest: Batch configuration with documents
            
        Returns:
            Dictionary of data types to cache keys
        """
        access_patterns = {
            'projects': set(),
            'documents': set(),
            'chunks': set(),
            'entities': set(),
            'canonical_entities': set()
        }
        
        # Extract project UUIDs
        project_uuid = batch_manifest.get('project_uuid')
        if project_uuid:
            access_patterns['projects'].add(project_uuid)
        
        # Extract document UUIDs and predict chunk access
        for doc in batch_manifest.get('documents', []):
            doc_uuid = doc.get('document_uuid')
            if doc_uuid:
                access_patterns['documents'].add(doc_uuid)
                
                # Predict chunk access (these will be created during processing)
                # We'll warm up any existing chunks
                access_patterns['chunks'].add(doc_uuid)
        
        # For entity-heavy processing, predict entity access patterns
        if batch_manifest.get('options', {}).get('entity_resolution', True):
            # We'll warm up frequently accessed canonical entities
            access_patterns['entities'] = 'frequent'  # Special marker
            access_patterns['canonical_entities'] = 'frequent'
        
        return access_patterns
    
    def warm_project_cache(self, project_uuids: Set[str]):
        """Warm cache with project data."""
        logger.info(f"Warming cache for {len(project_uuids)} projects")
        
        session = next(self.db_manager.get_session())
        try:
            # Fetch projects from database
            projects = session.query(ProjectMinimal).filter(
                ProjectMinimal.project_uuid.in_(list(project_uuids))
            ).all()
            
            # Cache each project
            for project in projects:
                cache_key = f"{CacheKeys.PROJECT}{project.project_uuid}"
                self.redis_manager.store_dict(
                    cache_key,
                    project.to_dict(),
                    ttl=3600  # 1 hour
                )
                
            logger.info(f"Cached {len(projects)} projects")
            
        finally:
            session.close()
    
    def warm_document_cache(self, document_uuids: Set[str]):
        """Warm cache with document metadata."""
        logger.info(f"Warming cache for {len(document_uuids)} documents")
        
        session = next(self.db_manager.get_session())
        try:
            # Fetch documents in batches
            batch_size = 100
            doc_list = list(document_uuids)
            cached_count = 0
            
            for i in range(0, len(doc_list), batch_size):
                batch_uuids = doc_list[i:i + batch_size]
                
                documents = session.query(SourceDocumentMinimal).filter(
                    SourceDocumentMinimal.document_uuid.in_(batch_uuids)
                ).all()
                
                # Cache each document
                for doc in documents:
                    # Cache document metadata
                    doc_cache_key = f"doc:metadata:{doc.document_uuid}"
                    self.redis_manager.store_dict(
                        doc_cache_key,
                        doc.to_dict(),
                        ttl=3600
                    )
                    
                    # Cache processing status
                    status_cache_key = f"doc:state:{doc.document_uuid}"
                    self.redis_manager.store_dict(
                        status_cache_key,
                        {
                            'status': doc.processing_status,
                            'stage': doc.current_stage,
                            'updated_at': datetime.utcnow().isoformat()
                        },
                        ttl=3600
                    )
                    
                    cached_count += 1
            
            logger.info(f"Cached {cached_count} documents")
            
        finally:
            session.close()
    
    def warm_chunk_cache(self, document_uuids: Set[str]):
        """Warm cache with existing chunks."""
        logger.info(f"Warming chunk cache for {len(document_uuids)} documents")
        
        session = next(self.db_manager.get_session())
        try:
            # Fetch chunks for documents
            chunks = session.query(DocumentChunkMinimal).filter(
                DocumentChunkMinimal.document_uuid.in_(list(document_uuids))
            ).all()
            
            # Group chunks by document
            chunks_by_doc = {}
            for chunk in chunks:
                if chunk.document_uuid not in chunks_by_doc:
                    chunks_by_doc[chunk.document_uuid] = []
                chunks_by_doc[chunk.document_uuid].append(chunk)
            
            # Cache chunks by document
            for doc_uuid, doc_chunks in chunks_by_doc.items():
                cache_key = f"{CacheKeys.CHUNKS}{doc_uuid}"
                chunk_data = [chunk.to_dict() for chunk in doc_chunks]
                
                self.redis_manager.get_client().set(
                    cache_key,
                    json.dumps(chunk_data),
                    ex=3600
                )
            
            logger.info(f"Cached {len(chunks)} chunks for {len(chunks_by_doc)} documents")
            
        finally:
            session.close()
    
    def warm_entity_cache(self, strategy: str = 'frequent'):
        """
        Warm cache with entity data.
        
        Args:
            strategy: 'frequent' to cache frequently used entities
        """
        if strategy != 'frequent':
            return
            
        logger.info("Warming cache with frequently accessed entities")
        
        session = next(self.db_manager.get_session())
        try:
            # Get top canonical entities by mention count
            from sqlalchemy import func, desc
            
            # Get top 1000 most mentioned canonical entities
            top_entities = session.query(
                CanonicalEntityMinimal,
                func.count(EntityMentionMinimal.id).label('mention_count')
            ).join(
                EntityMentionMinimal,
                EntityMentionMinimal.canonical_entity_id == CanonicalEntityMinimal.id
            ).group_by(
                CanonicalEntityMinimal.id
            ).order_by(
                desc('mention_count')
            ).limit(1000).all()
            
            # Cache canonical entities
            cached_count = 0
            for entity, count in top_entities:
                cache_key = f"{CacheKeys.CANONICAL_ENTITY}{entity.id}"
                self.redis_manager.store_dict(
                    cache_key,
                    {
                        **entity.to_dict(),
                        'mention_count': count
                    },
                    ttl=7200  # 2 hours for frequently accessed
                )
                cached_count += 1
            
            logger.info(f"Cached {cached_count} frequently accessed entities")
            
            # Also cache entity resolution mappings for common names
            # This helps with entity resolution performance
            common_names = session.query(
                EntityMentionMinimal.entity_name,
                EntityMentionMinimal.canonical_entity_id
            ).join(
                CanonicalEntityMinimal,
                EntityMentionMinimal.canonical_entity_id == CanonicalEntityMinimal.id
            ).filter(
                CanonicalEntityMinimal.id.in_([e[0].id for e in top_entities[:100]])
            ).distinct().all()
            
            # Build resolution cache
            resolution_cache = {}
            for name, canonical_id in common_names:
                if name not in resolution_cache:
                    resolution_cache[name] = []
                resolution_cache[name].append(str(canonical_id))
            
            # Store resolution mappings
            for name, canonical_ids in resolution_cache.items():
                cache_key = f"entity:resolution:{name.lower()}"
                self.redis_manager.get_client().set(
                    cache_key,
                    json.dumps(canonical_ids),
                    ex=7200
                )
            
            logger.info(f"Cached {len(resolution_cache)} entity resolution mappings")
            
        finally:
            session.close()
    
    def estimate_cache_size(self, access_patterns: Dict[str, Any]) -> Dict[str, int]:
        """Estimate memory requirements for cache warming."""
        estimates = {
            'projects': 0,
            'documents': 0,
            'chunks': 0,
            'entities': 0,
            'total_mb': 0
        }
        
        # Rough estimates per item (in bytes)
        SIZES = {
            'project': 1024,  # 1KB per project
            'document': 2048,  # 2KB per document
            'chunk': 512,     # 512B per chunk
            'entity': 256     # 256B per entity
        }
        
        # Calculate estimates
        if isinstance(access_patterns.get('projects'), set):
            estimates['projects'] = len(access_patterns['projects']) * SIZES['project']
            
        if isinstance(access_patterns.get('documents'), set):
            estimates['documents'] = len(access_patterns['documents']) * SIZES['document']
            
        if isinstance(access_patterns.get('chunks'), set):
            # Assume ~20 chunks per document on average
            estimates['chunks'] = len(access_patterns['chunks']) * 20 * SIZES['chunk']
            
        if access_patterns.get('entities') == 'frequent':
            # Top 1000 entities
            estimates['entities'] = 1000 * SIZES['entity']
        
        # Total in MB
        total_bytes = sum(v for k, v in estimates.items() if k != 'total_mb')
        estimates['total_mb'] = total_bytes / (1024 * 1024)
        
        return estimates


@app.task(bind=True)
def warm_batch_cache(self, batch_manifest: Dict[str, Any]) -> Dict[str, Any]:
    """
    Celery task to warm cache before batch processing.
    
    Args:
        batch_manifest: Batch configuration
        
    Returns:
        Cache warming results
    """
    warmer = CacheWarmer()
    start_time = datetime.utcnow()
    
    try:
        # Analyze access patterns
        access_patterns = warmer.analyze_batch_access_patterns(batch_manifest)
        
        # Estimate cache size
        estimates = warmer.estimate_cache_size(access_patterns)
        logger.info(f"Estimated cache size: {estimates['total_mb']:.2f} MB")
        
        # Check available Redis memory
        redis_info = warmer.redis_manager.get_client().info('memory')
        used_memory_mb = float(redis_info.get('used_memory', 0)) / (1024 * 1024)
        max_memory_mb = float(redis_info.get('maxmemory', 0)) / (1024 * 1024) if redis_info.get('maxmemory', 0) > 0 else float('inf')
        
        if max_memory_mb != float('inf') and (used_memory_mb + estimates['total_mb']) > (max_memory_mb * 0.8):
            logger.warning(f"Cache warming may exceed memory limit. Used: {used_memory_mb:.2f}MB, "
                          f"Estimated: {estimates['total_mb']:.2f}MB, Max: {max_memory_mb:.2f}MB")
        
        # Warm caches in parallel
        results = {
            'warmed': {},
            'errors': []
        }
        
        # Warm project cache
        if access_patterns['projects']:
            try:
                warmer.warm_project_cache(access_patterns['projects'])
                results['warmed']['projects'] = len(access_patterns['projects'])
            except Exception as e:
                logger.error(f"Error warming project cache: {e}")
                results['errors'].append(f"Projects: {str(e)}")
        
        # Warm document cache
        if access_patterns['documents']:
            try:
                warmer.warm_document_cache(access_patterns['documents'])
                results['warmed']['documents'] = len(access_patterns['documents'])
            except Exception as e:
                logger.error(f"Error warming document cache: {e}")
                results['errors'].append(f"Documents: {str(e)}")
        
        # Warm chunk cache (for existing chunks)
        if access_patterns['chunks']:
            try:
                warmer.warm_chunk_cache(access_patterns['chunks'])
                results['warmed']['chunks'] = 'completed'
            except Exception as e:
                logger.error(f"Error warming chunk cache: {e}")
                results['errors'].append(f"Chunks: {str(e)}")
        
        # Warm entity cache
        if access_patterns.get('entities') == 'frequent':
            try:
                warmer.warm_entity_cache('frequent')
                results['warmed']['entities'] = 'frequent'
            except Exception as e:
                logger.error(f"Error warming entity cache: {e}")
                results['errors'].append(f"Entities: {str(e)}")
        
        # Calculate duration
        duration = (datetime.utcnow() - start_time).total_seconds()
        
        return {
            'status': 'completed',
            'duration_seconds': duration,
            'estimates': estimates,
            'warmed': results['warmed'],
            'errors': results['errors'],
            'memory_usage': {
                'before_mb': used_memory_mb,
                'estimated_mb': estimates['total_mb']
            }
        }
        
    except Exception as e:
        logger.error(f"Cache warming failed: {e}")
        return {
            'status': 'failed',
            'error': str(e)
        }


# Integration with batch processing
def warm_cache_before_batch(batch_manifest: Dict[str, Any], wait: bool = True) -> Optional[Dict[str, Any]]:
    """
    Warm cache before starting batch processing.
    
    Args:
        batch_manifest: Batch configuration
        wait: Whether to wait for warming to complete
        
    Returns:
        Warming results if wait=True, else None
    """
    # Submit cache warming task
    task = warm_batch_cache.apply_async(args=[batch_manifest])
    
    if wait:
        # Wait for warming to complete (with timeout)
        try:
            result = task.get(timeout=60)  # 1 minute timeout
            logger.info(f"Cache warming completed: {result}")
            return result
        except Exception as e:
            logger.warning(f"Cache warming timed out or failed: {e}")
            return None
    else:
        logger.info(f"Cache warming started asynchronously: {task.id}")
        return None