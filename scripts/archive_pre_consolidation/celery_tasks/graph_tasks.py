"""
Graph and Relationship Building Tasks for Celery-based Document Processing Pipeline
"""
from celery import Task
from scripts.celery_app import app
from scripts.graph_service import stage_structural_relationships
from scripts.database import SupabaseManager
from scripts.cache import get_redis_manager, CacheKeys
from scripts.celery_tasks.task_utils import update_document_state
import logging
from datetime import datetime
from typing import Dict, Any, List

logger = logging.getLogger(__name__)


class GraphTask(Task):
    """Base class for graph tasks with database connection management"""
    _db_manager = None
    
    @property
    def db_manager(self):
        if self._db_manager is None:
            self._db_manager = SupabaseManager()
        return self._db_manager
    
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Called when the task fails."""
        document_uuid = kwargs.get('document_uuid', 'unknown')
        logger.error(f"Task {task_id} failed for document {document_uuid}: {exc}")
        update_document_state(document_uuid, "relationships", "failed", {"error": str(exc), "task_id": task_id})


@app.task(bind=True, base=GraphTask, max_retries=3, default_retry_delay=60, queue='graph')
def build_relationships(self, document_uuid: str, source_doc_sql_id: int,
                       doc_data: Dict[str, Any], project_uuid: str, 
                       chunks: List[Dict[str, Any]] = None, entity_mentions: List[Dict[str, Any]] = None, 
                       canonical_entities: List[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Build graph relationships for Neo4j export.
    
    Args:
        document_uuid: UUID of the source document
        source_doc_sql_id: SQL ID of the source document
        doc_data: Document data dict containing documentId (neo4j_doc_uuid), sql_id, name, category, file_type
        project_uuid: UUID of the project
        chunks: List of chunk dicts containing chunkId and chunkIndex (optional - will fetch from Redis/DB if not provided)
        entity_mentions: List of entity mention dicts (optional - will fetch from Redis if not provided)
        canonical_entities: List of canonical entity dicts (optional - will fetch from Redis if not provided)
    
    Returns:
        Dict containing relationship building results
    """
    neo4j_doc_uuid = doc_data.get('documentId')
    neo4j_doc_sql_id = doc_data.get('sql_id')
    
    logger.info(f"[RELATIONSHIP_TASK:{self.request.id}] Building relationships for document {neo4j_doc_uuid}")
    
    # Check if stage is already completed
    processing_version = None
    if source_doc_sql_id:
        version_response = self.db_manager.client.table('source_documents').select(
            'processing_version'
        ).eq('id', source_doc_sql_id).execute()
        processing_version = version_response.data[0]['processing_version'] if version_response.data else 1
    
    # For relationships stage, we check if relationships already exist
    rel_count_result = self.db_manager.service_client.table('neo4j_relationships_staging').select(
        'id', count='exact'
    ).eq('fromNodeId', neo4j_doc_uuid).execute()
    
    relationship_count = rel_count_result.count if hasattr(rel_count_result, 'count') else 0
    
    if relationship_count > 0:
        logger.info(f"[RELATIONSHIP_TASK:{self.request.id}] Stage already completed, {relationship_count} relationships exist")
        
        # Update document status to completed
        self.db_manager.update_neo4j_document_status(neo4j_doc_sql_id, "relationships_staged")
        self.db_manager.update_processing_status('source_documents', source_doc_sql_id, 'completed')
        
        # Update Celery status
        self.db_manager.client.table('source_documents').update({
            'celery_status': 'completed',
            'last_modified_at': datetime.now().isoformat()
        }).eq('id', source_doc_sql_id).execute()
        
        update_document_state(document_uuid, "relationships", "completed", {"relationship_count": relationship_count})
        
        return {
            "status": "skipped_completed",
            "cached": True,
            "relationship_count": relationship_count
        }
    
    # Get Redis manager for fetching cached data
    redis_mgr = get_redis_manager()
    
    # Fetch chunks if not provided
    if chunks is None:
        if redis_mgr and redis_mgr.is_available():
            # Try to get chunk list from Redis
            chunks_key = CacheKeys.format_key(CacheKeys.DOC_CHUNKS_LIST, document_uuid=document_uuid)
            chunk_uuids = redis_mgr.get_cached(chunks_key)
            
            if chunk_uuids:
                # Fetch chunk details from database
                chunks_raw = self.db_manager.client.table('neo4j_chunks').select(
                    'chunkId, chunkIndex'
                ).in_('chunkId', chunk_uuids).execute()
                chunks = [{"chunkId": c['chunkId'], "chunkIndex": c['chunkIndex']} for c in chunks_raw.data]
                logger.info(f"[RELATIONSHIP_TASK:{self.request.id}] Retrieved {len(chunks)} chunks using Redis cache")
            else:
                # Fallback to database query
                chunks_raw = self.db_manager.client.table('neo4j_chunks').select(
                    'chunkId, chunkIndex'
                ).eq('document_id', neo4j_doc_sql_id).execute()
                chunks = [{"chunkId": c['chunkId'], "chunkIndex": c['chunkIndex']} for c in chunks_raw.data]
                logger.info(f"[RELATIONSHIP_TASK:{self.request.id}] Retrieved {len(chunks)} chunks from database")
        else:
            # No Redis, fetch from database
            chunks_raw = self.db_manager.client.table('neo4j_chunks').select(
                'chunkId, chunkIndex'
            ).eq('document_id', neo4j_doc_sql_id).execute()
            chunks = [{"chunkId": c['chunkId'], "chunkIndex": c['chunkIndex']} for c in chunks_raw.data]
    
    # Fetch resolved entity mentions if not provided
    if entity_mentions is None:
        if redis_mgr and redis_mgr.is_available():
            # Get processing version
            version_response = self.db_manager.client.table('source_documents').select(
                'processing_version'
            ).eq('document_uuid', document_uuid).execute()
            
            processing_version = version_response.data[0]['processing_version'] if version_response.data else 1
            
            resolved_key = CacheKeys.format_key(
                CacheKeys.DOC_RESOLVED_MENTIONS, 
                version=processing_version,
                document_uuid=document_uuid
            )
            entity_mentions = redis_mgr.get_cached(resolved_key) or []
            if entity_mentions:
                logger.info(f"[RELATIONSHIP_TASK:{self.request.id}] Retrieved {len(entity_mentions)} entity mentions from Redis with version {processing_version}")
        else:
            entity_mentions = []
            logger.warning(f"[RELATIONSHIP_TASK:{self.request.id}] No entity mentions available (Redis not available)")
    
    # Fetch canonical entities if not provided
    if canonical_entities is None:
        if redis_mgr and redis_mgr.is_available():
            # Use same processing version from above
            if 'processing_version' not in locals():
                version_response = self.db_manager.client.table('source_documents').select(
                    'processing_version'
                ).eq('document_uuid', document_uuid).execute()
                
                processing_version = version_response.data[0]['processing_version'] if version_response.data else 1
            
            canonical_key = CacheKeys.format_key(
                CacheKeys.DOC_CANONICAL_ENTITIES, 
                version=processing_version,
                document_uuid=document_uuid
            )
            canonical_entities = redis_mgr.get_cached(canonical_key) or []
            if canonical_entities:
                logger.info(f"[RELATIONSHIP_TASK:{self.request.id}] Retrieved {len(canonical_entities)} canonical entities from Redis with version {processing_version}")
        else:
            canonical_entities = []
            logger.warning(f"[RELATIONSHIP_TASK:{self.request.id}] No canonical entities available (Redis not available)")
    
    logger.info(f"[RELATIONSHIP_TASK:{self.request.id}] Building relationships for document {neo4j_doc_uuid}")
    update_document_state(document_uuid, "relationships", "started", {
        "task_id": self.request.id,
        "chunk_count": len(chunks),
        "entity_count": len(canonical_entities)
    })
    
    # Update Celery status in source_documents
    self.db_manager.client.table('source_documents').update({
        'celery_status': 'graph_building',
        'last_modified_at': datetime.now().isoformat()
    }).eq('id', source_doc_sql_id).execute()
    
    try:
        # Stage all structural relationships
        stage_structural_relationships(
            self.db_manager,
            doc_data,  # Contains documentId (neo4j_doc_uuid)
            project_uuid,
            chunks,
            entity_mentions,
            canonical_entities
        )
        
        # Count relationships created
        rel_count_result = self.db_manager.service_client.table('neo4j_relationships_staging').select(
            'id', count='exact'
        ).eq('fromNodeId', neo4j_doc_uuid).execute()
        
        relationship_count = rel_count_result.count if hasattr(rel_count_result, 'count') else 0
        
        # Update final statuses
        # Update source document status to completed
        source_doc_result = self.db_manager.client.table('source_documents').select(
            'id, raw_extracted_text'
        ).eq('document_uuid', document_uuid).maybe_single().execute()
        
        if source_doc_result.data:
            self.db_manager.update_source_document_text(
                source_doc_result.data['id'],
                source_doc_result.data['raw_extracted_text'],
                status="completed"
            )
            
            # Update Celery status to completed
            self.db_manager.client.table('source_documents').update({
                'celery_status': 'completed',
                'last_modified_at': datetime.now().isoformat()
            }).eq('id', source_doc_sql_id).execute()
        
        # Update neo4j_documents status to complete
        self.db_manager.update_neo4j_document_status(neo4j_doc_sql_id, "complete")
        
        # Update document processing history
        try:
            history_entry = {
                'document_uuid': document_uuid,
                'processing_stage': 'relationship_building',
                'status': 'completed',
                'details': {
                    'relationships_created': relationship_count,
                    'chunks_processed': len(chunks),
                    'entities_linked': len(entity_mentions),
                    'canonical_entities': len(canonical_entities)
                },
                'timestamp': datetime.now().isoformat()
            }
            
            self.db_manager.client.table('document_processing_history').insert(
                history_entry
            ).execute()
        except Exception as hist_err:
            logger.warning(f"Failed to create processing history entry: {hist_err}")
        
        # Update state to completed
        update_document_state(document_uuid, "relationships", "completed", {
            "relationship_count": relationship_count,
            "processing_complete": True
        })
        
        # Update overall document state
        update_document_state(document_uuid, "pipeline", "completed", {
            "completion_time": datetime.now().isoformat(),
            "total_relationships": relationship_count,
            "total_entities": len(canonical_entities),
            "total_chunks": len(chunks)
        })
        
        logger.info(f"[RELATIONSHIP_TASK:{self.request.id}] Successfully completed processing for document {document_uuid}")
        
        return {
            "status": "success",
            "document_uuid": document_uuid,
            "neo4j_doc_uuid": neo4j_doc_uuid,
            "relationship_count": relationship_count,
            "canonical_entities": len(canonical_entities),
            "chunks": len(chunks)
        }
        
    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {str(exc)}"
        logger.exception(f"[RELATIONSHIP_TASK:{self.request.id}] Error: {exc}")
        
        # Save error to database
        try:
            self.db_manager.client.table('source_documents').update({
                'error_message': error_msg[:500],  # Truncate long errors
                'celery_status': 'graph_failed',
                'last_modified_at': datetime.now().isoformat()
            }).eq('id', source_doc_sql_id).execute()
        except Exception as db_exc:
            logger.error(f"Failed to save error to database: {db_exc}")
        
        # Update state for monitoring
        update_document_state(document_uuid, "relationships", "failed", {
            "error": error_msg,
            "task_id": self.request.id
        })
        
        # Update document status to error
        if neo4j_doc_sql_id:
            self.db_manager.update_neo4j_document_status(neo4j_doc_sql_id, "error_relationships")
        
        countdown = int(self.default_retry_delay * (2 ** self.request.retries))
        raise self.retry(exc=exc, countdown=min(countdown, 600))


@app.task(bind=True, base=GraphTask, max_retries=1, queue='graph')
def export_to_neo4j(self, document_uuid: str, neo4j_doc_uuid: str) -> Dict[str, Any]:
    """
    Export staged relationships to Neo4j (future implementation).
    
    This task would handle the actual export of staged relationships
    to a Neo4j database instance.
    
    Args:
        document_uuid: UUID of the source document
        neo4j_doc_uuid: UUID of the neo4j document
    
    Returns:
        Dict containing export results
    """
    logger.info(f"[NEO4J_EXPORT_TASK:{self.request.id}] Exporting document {neo4j_doc_uuid} to Neo4j")
    
    # TODO: Implement Neo4j export logic
    # This would involve:
    # 1. Connecting to Neo4j instance
    # 2. Creating nodes for Project, Document, Chunks, Entities
    # 3. Creating relationships from neo4j_relationship_staging
    # 4. Updating export status in database
    
    logger.warning("Neo4j export not yet implemented")
    
    return {
        "status": "not_implemented",
        "document_uuid": document_uuid,
        "neo4j_doc_uuid": neo4j_doc_uuid
    }