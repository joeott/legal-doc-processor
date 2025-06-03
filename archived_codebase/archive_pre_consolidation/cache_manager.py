"""
Unified cache management for the document pipeline.
Provides high-level cache operations and monitoring.
"""
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
import json

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import Pydantic models for type-safe caching
from scripts.core.cache_models import (
    BaseCacheModel, CacheMetadataModel, CacheStatus,
    CachedProjectModel, CachedDocumentModel, CachedChunkListModel,
    CachedEntityResolutionModel, CachedOCRResultModel, CachedProcessingStatusModel,
    CachedEmbeddingModel, CachedSearchResultModel, CachedBatchStatusModel
)
from pydantic import ValidationError

logger = logging.getLogger(__name__)


class CacheManager:
    """
    High-level cache management with Pydantic model support and automatic invalidation.
    """
    
    def __init__(self, redis_manager=None):
        if redis_manager is None:
            # Import here to avoid circular import
            from scripts.redis_utils import RedisManager
            self.redis = RedisManager()
        else:
            self.redis = redis_manager
        
    @property
    def is_available(self) -> bool:
        """Check if cache is available."""
        return self.redis.is_available()
    
    def clear_document_cache(self, document_uuid: str) -> int:
        """Clear all cached data for a document."""
        if not self.is_available:
            logger.warning("Cache not available")
            return 0
            
        # Import here to avoid circular import
        from scripts.cache_keys import CacheKeys
            
        cleared = 0
        patterns = [
            CacheKeys.DOC_OCR_RESULT,
            CacheKeys.DOC_CHUNKS_LIST,
            CacheKeys.DOC_ENTITY_MENTIONS,
            CacheKeys.DOC_RESOLVED_MENTIONS,
            CacheKeys.DOC_CANONICAL_ENTITIES
        ]
        
        for pattern in patterns:
            # Handle versioned keys
            for version in range(1, 10):  # Check up to version 9
                key = CacheKeys.format_key(pattern, version=version, document_uuid=document_uuid)
                if self.redis.client.delete(key):
                    cleared += 1
                    
            # Handle non-versioned keys
            key = CacheKeys.format_key(pattern, document_uuid=document_uuid)
            if self.redis.client.delete(key):
                cleared += 1
                
        logger.info(f"Cleared {cleared} cache keys for document {document_uuid}")
        return cleared
    
    def clear_project_cache(self, project_id: int) -> int:
        """Clear all cached data for a project."""
        if not self.is_available:
            logger.warning("Cache not available")
            return 0
            
        # Import here to avoid circular import
        from scripts.cache_keys import CacheKeys
            
        cleared = 0
        
        # Clear project info
        key = CacheKeys.format_key(CacheKeys.PROJECT_INFO, project_id=project_id)
        if self.redis.client.delete(key):
            cleared += 1
            
        # Clear entity cache
        key = CacheKeys.format_key(CacheKeys.PROJECT_ENTITIES, project_id=project_id)
        if self.redis.client.delete(key):
            cleared += 1
            
        logger.info(f"Cleared {cleared} cache keys for project {project_id}")
        return cleared
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        if not self.is_available:
            return {'error': 'Cache not available'}
            
        try:
            info = self.redis.client.info()
            
            # Get memory stats
            memory_stats = {
                'used_memory': info.get('used_memory_human', 'N/A'),
                'used_memory_peak': info.get('used_memory_peak_human', 'N/A'),
                'memory_fragmentation_ratio': info.get('mem_fragmentation_ratio', 0)
            }
            
            # Get hit/miss stats
            keyspace_hits = info.get('keyspace_hits', 0)
            keyspace_misses = info.get('keyspace_misses', 0)
            total_ops = keyspace_hits + keyspace_misses
            
            hit_stats = {
                'hits': keyspace_hits,
                'misses': keyspace_misses,
                'hit_rate': (keyspace_hits / total_ops * 100) if total_ops > 0 else 0
            }
            
            # Count keys by pattern
            key_counts = self._count_keys_by_pattern()
            
            return {
                'memory': memory_stats,
                'performance': hit_stats,
                'key_counts': key_counts,
                'total_keys': sum(key_counts.values()),
                'connected_clients': info.get('connected_clients', 0),
                'uptime_days': info.get('uptime_in_days', 0)
            }
            
        except Exception as e:
            logger.error(f"Error getting cache stats: {e}")
            return {'error': str(e)}
    
    def _count_keys_by_pattern(self) -> Dict[str, int]:
        """Count cache keys by pattern type."""
        patterns = {
            'ocr_results': 'ocr:*',
            'chunks': 'chunks:*',
            'entities': 'entity_mentions:*',
            'resolved': 'resolved_mentions:*',
            'canonical': 'canonical:*',
            'projects': 'project:*',
            'embeddings': 'embedding:*'
        }
        
        counts = {}
        for name, pattern in patterns.items():
            try:
                # Use SCAN to avoid blocking
                keys = list(self.redis.client.scan_iter(
                    match=pattern, count=100
                ))
                counts[name] = len(keys)
            except Exception as e:
                logger.warning(f"Error counting {name} keys: {e}")
                counts[name] = 0
                
        return counts
    
    def warm_cache_for_document(self, document_uuid: str) -> Dict[str, bool]:
        """Pre-load cache for a document."""
        results = {}
        
        if not self.is_available:
            logger.warning("Cache not available")
            return results
            
        # Import here to avoid circular import
        from scripts.cache_keys import CacheKeys
            
        try:
            from supabase_utils import SupabaseManager
            db = SupabaseManager()
            
            # Get document
            doc_response = db.client.table('source_documents').select(
                'id', 'raw_extracted_text', 'processing_version'
            ).eq('document_uuid', document_uuid).execute()
            
            if not doc_response.data:
                logger.warning(f"Document {document_uuid} not found")
                return results
                
            doc = doc_response.data[0]
            version = doc.get('processing_version', 1)
            
            # Cache OCR result
            if doc.get('raw_extracted_text'):
                ocr_key = CacheKeys.format_key(
                    CacheKeys.DOC_OCR_RESULT,
                    version=version,
                    document_uuid=document_uuid
                )
                self.redis.set_cached(ocr_key, {
                    'raw_text': doc['raw_extracted_text'],
                    'cached_at': datetime.now().isoformat()
                }, ttl=86400)
                results['ocr'] = True
                
            # Get and cache chunks
            neo4j_response = db.client.table('neo4j_documents').select(
                'id'
            ).eq('document_uuid', document_uuid).execute()
            
            if neo4j_response.data:
                neo4j_id = neo4j_response.data[0]['id']
                
                chunks_response = db.client.table('neo4j_chunks').select(
                    'chunkId', 'chunkIndex'
                ).eq('document_id', neo4j_id).execute()
                
                if chunks_response.data:
                    chunk_ids = [c['chunkId'] for c in chunks_response.data]
                    chunks_key = CacheKeys.format_key(
                        CacheKeys.DOC_CHUNKS_LIST,
                        document_uuid=document_uuid
                    )
                    self.redis.set_cached(chunks_key, chunk_ids, ttl=86400)
                    results['chunks'] = True
                    
            return results
            
        except Exception as e:
            logger.error(f"Error warming cache: {e}")
            return results
    
    def invalidate_stale_cache(self, hours: int = 24) -> int:
        """Remove cache entries older than specified hours."""
        if not self.is_available:
            logger.warning("Cache not available")
            return 0
            
        # This would require storing timestamps with cache entries
        # For now, just log the intent
        logger.info(f"Would invalidate cache entries older than {hours} hours")
        return 0
    
    def export_cache_keys(self, pattern: str = '*') -> List[str]:
        """Export list of cache keys matching pattern."""
        if not self.is_available:
            return []
            
        try:
            keys = list(self.redis.client.scan_iter(
                match=pattern, count=100
            ))
            return sorted(keys)
        except Exception as e:
            logger.error(f"Error exporting cache keys: {e}")
            return []
    
    # Type-safe cache operations
    def get_cached_document(self, document_uuid: str) -> Optional[CachedDocumentModel]:
        """Get cached document with type safety."""
        from scripts.cache_keys import CacheKeys
        key = CacheKeys.document(document_uuid)
        return self.redis.get_cached_model(key, CachedDocumentModel)
    
    def set_cached_document(self, document_uuid: str, document_data: Dict[str, Any], 
                          ttl: int = 3600) -> bool:
        """Set cached document with automatic metadata."""
        from scripts.cache_keys import CacheKeys
        try:
            cached_doc = CachedDocumentModel.create_with_metadata(
                document_uuid=document_uuid,
                title=document_data.get('title', ''),
                document_type=document_data.get('document_type', ''),
                file_path=document_data.get('file_path', ''),
                file_size=document_data.get('file_size', 0),
                created_at=document_data.get('created_at'),
                updated_at=document_data.get('updated_at'),
                ttl_seconds=ttl
            )
            
            key = CacheKeys.document(document_uuid)
            invalidation_tags = [f"doc:{document_uuid}", "documents"]
            
            return self.redis.set_cached_with_auto_invalidation(
                key, cached_doc, ttl, invalidation_tags
            )
        except Exception as e:
            logger.error(f"Failed to cache document {document_uuid}: {e}")
            return False
    
    def get_cached_project(self, project_id: str) -> Optional[CachedProjectModel]:
        """Get cached project with type safety."""
        from scripts.cache_keys import CacheKeys
        key = CacheKeys.project(project_id)
        return self.redis.get_cached_model(key, CachedProjectModel)
    
    def set_cached_project(self, project_id: str, project_data: Dict[str, Any], 
                         ttl: int = 7200) -> bool:
        """Set cached project with automatic metadata."""
        from scripts.cache_keys import CacheKeys
        try:
            cached_project = CachedProjectModel.create_with_metadata(
                project_id=project_id,
                name=project_data.get('name', ''),
                description=project_data.get('description', ''),
                document_count=project_data.get('document_count', 0),
                created_at=project_data.get('created_at'),
                updated_at=project_data.get('updated_at'),
                ttl_seconds=ttl
            )
            
            key = CacheKeys.project(project_id)
            invalidation_tags = [f"proj:{project_id}", "projects"]
            
            return self.redis.set_cached_with_auto_invalidation(
                key, cached_project, ttl, invalidation_tags
            )
        except Exception as e:
            logger.error(f"Failed to cache project {project_id}: {e}")
            return False
    
    def get_cached_chunks(self, document_uuid: str) -> Optional[CachedChunkListModel]:
        """Get cached document chunks with type safety."""
        from scripts.cache_keys import CacheKeys
        key = CacheKeys.document_chunks(document_uuid)
        return self.redis.get_cached_model(key, CachedChunkListModel)
    
    def set_cached_chunks(self, document_uuid: str, chunks_data: List[Dict[str, Any]], 
                        ttl: int = 3600) -> bool:
        """Set cached chunks with automatic metadata."""
        from scripts.cache_keys import CacheKeys
        try:
            cached_chunks = CachedChunkListModel.create_with_metadata(
                document_uuid=document_uuid,
                chunks=chunks_data,
                total_chunks=len(chunks_data),
                ttl_seconds=ttl
            )
            
            key = CacheKeys.document_chunks(document_uuid)
            invalidation_tags = [f"doc:{document_uuid}", f"chunks:{document_uuid}"]
            
            return self.redis.set_cached_with_auto_invalidation(
                key, cached_chunks, ttl, invalidation_tags
            )
        except Exception as e:
            logger.error(f"Failed to cache chunks for document {document_uuid}: {e}")
            return False
    
    def get_cached_entity_resolution(self, document_uuid: str) -> Optional[CachedEntityResolutionModel]:
        """Get cached entity resolution results with type safety."""
        from scripts.cache_keys import CacheKeys
        key = CacheKeys.entity_resolution(document_uuid)
        return self.redis.get_cached_model(key, CachedEntityResolutionModel)
    
    def set_cached_entity_resolution(self, document_uuid: str, entities_data: Dict[str, Any], 
                                   ttl: int = 7200) -> bool:
        """Set cached entity resolution with automatic metadata."""
        from scripts.cache_keys import CacheKeys
        try:
            cached_entities = CachedEntityResolutionModel.create_with_metadata(
                document_uuid=document_uuid,
                entities=entities_data.get('entities', []),
                relationships=entities_data.get('relationships', []),
                confidence_scores=entities_data.get('confidence_scores', {}),
                extraction_method=entities_data.get('extraction_method', ''),
                ttl_seconds=ttl
            )
            
            key = CacheKeys.entity_resolution(document_uuid)
            invalidation_tags = [f"doc:{document_uuid}", f"entities:{document_uuid}"]
            
            return self.redis.set_cached_with_auto_invalidation(
                key, cached_entities, ttl, invalidation_tags
            )
        except Exception as e:
            logger.error(f"Failed to cache entity resolution for document {document_uuid}: {e}")
            return False
    
    def get_cached_embeddings(self, chunk_id: str) -> Optional[CachedEmbeddingModel]:
        """Get cached embeddings with type safety."""
        from scripts.cache_keys import CacheKeys
        key = CacheKeys.embeddings(chunk_id)
        return self.redis.get_cached_model(key, CachedEmbeddingModel)
    
    def set_cached_embeddings(self, chunk_id: str, embeddings_data: Dict[str, Any], 
                            ttl: int = 86400) -> bool:
        """Set cached embeddings with automatic metadata."""
        from scripts.cache_keys import CacheKeys
        try:
            cached_embeddings = CachedEmbeddingModel.create_with_metadata(
                chunk_id=chunk_id,
                embedding_vector=embeddings_data.get('embedding_vector', []),
                model_name=embeddings_data.get('model_name', ''),
                model_version=embeddings_data.get('model_version', ''),
                vector_dimension=embeddings_data.get('vector_dimension', 0),
                ttl_seconds=ttl
            )
            
            key = CacheKeys.embeddings(chunk_id)
            invalidation_tags = [f"chunk:{chunk_id}", "embeddings"]
            
            return self.redis.set_cached_with_auto_invalidation(
                key, cached_embeddings, ttl, invalidation_tags
            )
        except Exception as e:
            logger.error(f"Failed to cache embeddings for chunk {chunk_id}: {e}")
            return False
    
    # Batch operations with type safety
    def batch_get_documents(self, document_uuids: List[str]) -> Dict[str, Optional[CachedDocumentModel]]:
        """Get multiple cached documents in a single operation."""
        from scripts.cache_keys import CacheKeys
        keys_and_classes = [
            (CacheKeys.document(doc_uuid), CachedDocumentModel) 
            for doc_uuid in document_uuids
        ]
        results = self.redis.batch_get_cached_models(keys_and_classes)
        
        # Map back to document UUIDs
        return {
            doc_uuid: results.get(CacheKeys.document(doc_uuid))
            for doc_uuid in document_uuids
        }
    
    def batch_set_documents(self, documents_data: Dict[str, Dict[str, Any]], 
                          ttl: int = 3600) -> bool:
        """Set multiple cached documents in a single operation."""
        from scripts.cache_keys import CacheKeys
        try:
            models_and_keys = []
            for doc_uuid, doc_data in documents_data.items():
                cached_doc = CachedDocumentModel.create_with_metadata(
                    document_uuid=doc_uuid,
                    title=doc_data.get('title', ''),
                    document_type=doc_data.get('document_type', ''),
                    file_path=doc_data.get('file_path', ''),
                    file_size=doc_data.get('file_size', 0),
                    created_at=doc_data.get('created_at'),
                    updated_at=doc_data.get('updated_at'),
                    ttl_seconds=ttl
                )
                key = CacheKeys.document(doc_uuid)
                models_and_keys.append((key, cached_doc))
            
            return self.redis.batch_set_cached_models(models_and_keys, ttl)
        except Exception as e:
            logger.error(f"Failed to batch set documents: {e}")
            return False
    
    # Enhanced cache invalidation
    def invalidate_document_cache(self, document_uuid: str) -> int:
        """Invalidate all cache entries for a specific document."""
        tags = [f"doc:{document_uuid}", f"chunks:{document_uuid}", f"entities:{document_uuid}"]
        return self.redis.invalidate_by_tag_sets(tags)
    
    def invalidate_project_cache(self, project_id: str) -> int:
        """Invalidate all cache entries for a specific project."""
        tags = [f"proj:{project_id}"]
        return self.redis.invalidate_by_tag_sets(tags)
    
    def invalidate_embeddings_cache(self, model_name: str = None) -> int:
        """Invalidate embeddings cache, optionally for specific model."""
        if model_name:
            tags = [f"embeddings:{model_name}"]
        else:
            tags = ["embeddings"]
        return self.redis.invalidate_by_tag_sets(tags)
    
    def get_cache_health_status(self) -> Dict[str, Any]:
        """Get comprehensive cache health status with Pydantic model validation."""
        try:
            stats = self.get_cache_stats()
            
            # Test cache operations with sample models
            test_results = {}
            
            # Test document cache
            try:
                test_doc = CachedDocumentModel.create_with_metadata(
                    document_uuid="test-doc-uuid",
                    title="Test Document",
                    document_type="test",
                    file_path="/test/path",
                    file_size=1024,
                    ttl_seconds=60
                )
                test_key = "test:document:health"
                set_success = self.redis.set_cached_model(test_key, test_doc, 60)
                get_result = self.redis.get_cached_model(test_key, CachedDocumentModel)
                self.redis.delete(test_key)
                
                test_results['document_cache'] = {
                    'set_success': set_success,
                    'get_success': get_result is not None,
                    'validation_success': get_result.is_valid() if get_result else False
                }
            except Exception as e:
                test_results['document_cache'] = {'error': str(e)}
            
            # Test project cache
            try:
                test_project = CachedProjectModel.create_with_metadata(
                    project_id="test-project-id",
                    name="Test Project",
                    description="Test Description",
                    document_count=5,
                    ttl_seconds=60
                )
                test_key = "test:project:health"
                set_success = self.redis.set_cached_model(test_key, test_project, 60)
                get_result = self.redis.get_cached_model(test_key, CachedProjectModel)
                self.redis.delete(test_key)
                
                test_results['project_cache'] = {
                    'set_success': set_success,
                    'get_success': get_result is not None,
                    'validation_success': get_result.is_valid() if get_result else False
                }
            except Exception as e:
                test_results['project_cache'] = {'error': str(e)}
            
            return {
                'redis_available': self.redis.is_available(),
                'cache_stats': stats,
                'model_validation_tests': test_results,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error getting cache health status: {e}")
            return {
                'redis_available': False,
                'error': str(e),
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
    
    def validate_cache_integrity(self) -> Dict[str, Any]:
        """Validate integrity of cached Pydantic models."""
        validation_results = {
            'total_keys_scanned': 0,
            'valid_models': 0,
            'invalid_models': 0,
            'corrupted_entries': 0,
            'expired_entries': 0,
            'validation_errors': []
        }
        
        try:
            if not self.redis.is_available():
                return {'error': 'Redis not available'}
            
            client = self.redis.get_client()
            
            # Scan all cache keys
            for key in client.scan_iter(match="*"):
                validation_results['total_keys_scanned'] += 1
                
                try:
                    value = client.get(key)
                    if not value:
                        continue
                    
                    # Try to parse as JSON
                    try:
                        data = json.loads(value)
                    except json.JSONDecodeError:
                        validation_results['corrupted_entries'] += 1
                        validation_results['validation_errors'].append({
                            'key': key,
                            'error': 'Invalid JSON'
                        })
                        continue
                    
                    # Check if it has cache metadata structure
                    if 'metadata' in data:
                        try:
                            # Validate metadata
                            metadata = CacheMetadataModel(**data['metadata'])
                            if not metadata.is_valid():
                                validation_results['expired_entries'] += 1
                                # Clean up expired entry
                                client.delete(key)
                            else:
                                validation_results['valid_models'] += 1
                        except ValidationError as e:
                            validation_results['invalid_models'] += 1
                            validation_results['validation_errors'].append({
                                'key': key,
                                'error': f'Metadata validation failed: {e}'
                            })
                    
                except Exception as e:
                    validation_results['validation_errors'].append({
                        'key': key,
                        'error': str(e)
                    })
            
            return validation_results
            
        except Exception as e:
            logger.error(f"Error validating cache integrity: {e}")
            return {'error': str(e)}
    