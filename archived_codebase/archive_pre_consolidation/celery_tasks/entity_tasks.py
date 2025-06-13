"""
Entity Extraction and Resolution Tasks for Celery-based Document Processing Pipeline
"""
from celery import Task
from scripts.celery_app import app
from scripts.entity_service import extract_entities_from_chunk, resolve_document_entities
from scripts.database import SupabaseManager
from scripts.cache import get_redis_manager, CacheKeys
from scripts.celery_tasks.task_utils import update_document_state, check_stage_completed
from scripts.core.processing_models import ProcessingResultStatus
import logging
import json
import numpy as np
from datetime import datetime
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)


class EntityTask(Task):
    """Base class for entity tasks with database connection management"""
    _db_manager = None
    
    @property
    def db_manager(self):
        if self._db_manager is None:
            self._db_manager = SupabaseManager()
        return self._db_manager
    
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Called when the task fails."""
        document_uuid = kwargs.get('document_uuid', 'unknown')
        phase = kwargs.get('phase', 'entity_processing')
        logger.error(f"Task {task_id} failed for document {document_uuid}: {exc}")
        update_document_state(document_uuid, phase, "failed", {"error": str(exc), "task_id": task_id})


@app.task(bind=True, base=EntityTask, max_retries=3, default_retry_delay=60, queue='entity')
def extract_entities(self, document_uuid: str, source_doc_sql_id: int,
                    neo4j_doc_sql_id: int, neo4j_doc_uuid: str, 
                    chunk_data: List[Dict]) -> Dict[str, Any]:
    """
    Extract named entities from document chunks.
    
    Args:
        document_uuid: UUID of the source document
        source_doc_sql_id: SQL ID of the source document
        neo4j_doc_sql_id: SQL ID of the neo4j_documents entry
        neo4j_doc_uuid: UUID of the neo4j_documents entry
        chunk_data: List of chunk information dicts containing sql_id, chunk_uuid, chunk_index
    
    Returns:
        Dict containing extraction results
    """
    logger.info(f"[NER_TASK:{self.request.id}] Extracting entities for document {neo4j_doc_uuid} ({len(chunk_data)} chunks)")
    
    # Check if stage is already completed
    processing_version = None
    if source_doc_sql_id:
        version_response = self.db_manager.client.table('source_documents').select(
            'processing_version'
        ).eq('document_uuid', document_uuid).execute()
        processing_version = version_response.data[0]['processing_version'] if version_response.data else 1
    
    is_completed, cached_results = check_stage_completed(document_uuid, "ner", processing_version)
    if is_completed and cached_results:
        logger.info(f"[NER_TASK:{self.request.id}] Stage already completed, using cached results")
        
        # Chain to resolution task
        resolve_entities.delay(
            document_uuid=document_uuid,
            source_doc_sql_id=source_doc_sql_id,
            neo4j_doc_sql_id=neo4j_doc_sql_id,
            neo4j_doc_uuid=neo4j_doc_uuid
        )
        
        return {
            "status": "skipped_completed",
            "cached": True,
            "mention_count": len(cached_results) if isinstance(cached_results, list) else 0
        }
    
    update_document_state(document_uuid, "ner", "started", {"task_id": self.request.id, "chunk_count": len(chunk_data)})
    
    # Update Celery status in source_documents
    self.db_manager.client.table('source_documents').update({
        'celery_status': 'entity_extraction',
        'last_modified_at': datetime.now().isoformat()
    }).eq('id', source_doc_sql_id).execute()
    
    all_entity_mentions = []
    processed_chunks = 0
    
    try:
        # Get Redis manager for caching
        redis_mgr = get_redis_manager()
        
        for chunk_info in chunk_data:
            chunk_sql_id = chunk_info['sql_id']
            chunk_uuid = chunk_info['chunk_uuid']
            chunk_index = chunk_info['chunk_index']
            
            # Check cache first for this chunk's entity mentions
            mentions_in_chunk = None
            if redis_mgr and redis_mgr.is_available():
                chunk_mentions_key = f"chunk:mentions:{chunk_uuid}"
                try:
                    cached_mentions = redis_mgr.get_cached(chunk_mentions_key)
                    if cached_mentions is not None:
                        mentions_in_chunk = cached_mentions
                        logger.debug(f"Retrieved cached mentions for chunk {chunk_uuid}")
                except Exception as e:
                    logger.warning(f"Failed to retrieve cached mentions: {e}")
            
            # If not cached, process the chunk
            if mentions_in_chunk is None:
                # Try to get chunk text from Redis cache first
                chunk_text = None
                if redis_mgr and redis_mgr.is_available():
                    chunk_text_key = CacheKeys.format_key(CacheKeys.DOC_CHUNK_TEXT, chunk_uuid=chunk_uuid)
                    try:
                        chunk_text = redis_mgr.get_cached(chunk_text_key)
                        if chunk_text:
                            logger.debug(f"[NER_TASK:{self.request.id}] Retrieved chunk text from Redis cache for chunk {chunk_uuid}")
                    except Exception as e:
                        logger.warning(f"[NER_TASK:{self.request.id}] Failed to retrieve chunk text from cache: {e}")
                
                # If not in cache, fetch from database
                if not chunk_text:
                    chunk_record = self.db_manager.client.table('neo4j_chunks').select(
                        'text'
                    ).eq('id', chunk_sql_id).maybe_single().execute()
                    
                    if not chunk_record.data or not chunk_record.data.get('text'):
                        logger.warning(f"[NER_TASK:{self.request.id}] Skipping chunk {chunk_sql_id} - no text found")
                        continue
                    
                    chunk_text = chunk_record.data['text']
                    logger.debug(f"[NER_TASK:{self.request.id}] Retrieved chunk text from database for chunk {chunk_sql_id}")
                
                # Extract entities from chunk
                result = extract_entities_from_chunk(
                    chunk_text, 
                    chunk_id=chunk_index,
                    db_manager=self.db_manager
                )
                
                # Check if extraction was successful
                if result.status == ProcessingResultStatus.SUCCESS:
                    mentions_in_chunk = result.entities
                else:
                    logger.warning(f"[NER_TASK:{self.request.id}] Entity extraction failed for chunk {chunk_index}: {result.error_message}")
                    mentions_in_chunk = []
                
                # Cache the extraction results
                if redis_mgr and redis_mgr.is_available() and mentions_in_chunk:
                    try:
                        chunk_mentions_key = f"chunk:mentions:{chunk_uuid}"
                        redis_mgr.set_cached(chunk_mentions_key, mentions_in_chunk, ttl=2 * 24 * 3600)  # 2 days
                    except Exception as e:
                        logger.warning(f"Failed to cache chunk mentions: {e}")
            
            # Store each entity mention in database
            for mention_attrs in mentions_in_chunk:
                em_sql_id, em_neo4j_uuid = self.db_manager.create_entity_mention_entry(
                    chunk_sql_id=chunk_sql_id,
                    chunk_uuid=chunk_uuid,
                    value=mention_attrs["value"],
                    norm_value=mention_attrs["normalizedValue"],
                    display_value=mention_attrs.get("displayValue"),
                    entity_type_label=mention_attrs["entity_type"],
                    rationale=mention_attrs.get("rationale"),
                    attributes_json_str=json.dumps(mention_attrs.get("attributes_json", {})),
                    phone=mention_attrs.get("phone"),
                    email=mention_attrs.get("email"),
                    start_offset=mention_attrs.get("offsetStart"),
                    end_offset=mention_attrs.get("offsetEnd")
                )
                
                if em_sql_id and em_neo4j_uuid:
                    # Prepare data for resolution
                    mention_data_for_resolution = {
                        **mention_attrs,
                        "entity_mention_id_neo4j": em_neo4j_uuid,
                        "entity_mention_sql_id": em_sql_id,
                        "parent_chunk_id_neo4j": chunk_uuid,
                        "chunk_index_int": chunk_index
                    }
                    all_entity_mentions.append(mention_data_for_resolution)
            
            processed_chunks += 1
            
            # Update progress periodically
            if processed_chunks % 10 == 0:
                update_document_state(document_uuid, "ner", "processing", {
                    "processed_chunks": processed_chunks,
                    "total_chunks": len(chunk_data),
                    "mentions_found": len(all_entity_mentions)
                })
        
        # Update document status
        self.db_manager.update_neo4j_document_status(neo4j_doc_sql_id, "pending_canonicalization")
        
        # Update state
        update_document_state(document_uuid, "ner", "completed", {
            "processed_chunks": processed_chunks,
            "mention_count": len(all_entity_mentions)
        })
        
        # Cache all extracted mentions in Redis with version
        try:
            redis_mgr = get_redis_manager()
            if redis_mgr and redis_mgr.is_available():
                # Get processing version
                version_response = self.db_manager.client.table('source_documents').select(
                    'processing_version'
                ).eq('document_uuid', document_uuid).execute()
                
                processing_version = version_response.data[0]['processing_version'] if version_response.data else 1
                
                mentions_key = CacheKeys.format_key(
                    CacheKeys.DOC_ALL_EXTRACTED_MENTIONS, 
                    version=processing_version,
                    document_uuid=document_uuid
                )
                redis_mgr.set_cached(mentions_key, all_entity_mentions, ttl=2 * 24 * 3600)  # 2 days
                logger.info(f"[NER_TASK:{self.request.id}] Cached {len(all_entity_mentions)} entity mentions in Redis with version {processing_version}")
        except Exception as e:
            logger.warning(f"Failed to cache entity mentions in Redis: {e}")
        
        # If we have mentions, proceed to resolution
        if all_entity_mentions:
            # Fetch full document text for resolution context
            doc_record = self.db_manager.client.table('neo4j_documents').select(
                'cleaned_text_for_chunking'
            ).eq('id', neo4j_doc_sql_id).maybe_single().execute()
            
            full_cleaned_text = doc_record.data.get('cleaned_text_for_chunking', '') if doc_record.data else ''
            
            # Chain to resolution task
            resolve_entities.delay(
                document_uuid=document_uuid,
                source_doc_sql_id=source_doc_sql_id,
                neo4j_doc_sql_id=neo4j_doc_sql_id,
                neo4j_doc_uuid=neo4j_doc_uuid,
                entity_mentions=all_entity_mentions,
                full_document_text=full_cleaned_text
            )
        else:
            # No entities found, skip resolution and go to relationships
            logger.info(f"[NER_TASK:{self.request.id}] No entities found, skipping resolution")
            
            # Still need to trigger relationship building for structural relationships
            from celery_tasks.graph_tasks import build_relationships
            
            # Fetch document data for relationships
            doc_data = self.db_manager.client.table('neo4j_documents').select(
                'name, category, fileType, project_id'
            ).eq('id', neo4j_doc_sql_id).single().execute()
            
            # Get project UUID
            project_info = self.db_manager.get_project_by_sql_id_or_global_project_id(
                doc_data.data['project_id'], None
            )
            project_uuid = project_info['project_uuid'] if isinstance(project_info, dict) else project_info
            
            # Get chunks
            chunks_raw = self.db_manager.client.table('neo4j_chunks').select(
                'chunkId, chunkIndex'
            ).eq('document_id', neo4j_doc_sql_id).execute()
            
            chunks_for_rels = [{"chunkId": c['chunkId'], "chunkIndex": c['chunkIndex']} for c in chunks_raw.data]
            
            build_relationships.delay(
                document_uuid=document_uuid,
                source_doc_sql_id=source_doc_sql_id,
                doc_data={
                    "documentId": neo4j_doc_uuid,
                    "sql_id": neo4j_doc_sql_id,
                    "name": doc_data.data['name'],
                    "category": doc_data.data['category'],
                    "file_type": doc_data.data['fileType']
                },
                project_uuid=project_uuid,
                chunks=chunks_for_rels,
                entity_mentions=[],
                canonical_entities=[]
            )
        
        return {
            "status": "success",
            "processed_chunks": processed_chunks,
            "mention_count": len(all_entity_mentions)
        }
        
    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {str(exc)}"
        logger.exception(f"[NER_TASK:{self.request.id}] Error: {exc}")
        
        # Save error to database
        try:
            self.db_manager.client.table('source_documents').update({
                'error_message': error_msg[:500],  # Truncate long errors
                'celery_status': 'entity_failed',
                'last_modified_at': datetime.now().isoformat()
            }).eq('id', source_doc_sql_id).execute()
        except Exception as db_exc:
            logger.error(f"Failed to save error to database: {db_exc}")
        
        # Update state for monitoring
        update_document_state(document_uuid, "ner", "failed", {
            "error": error_msg,
            "task_id": self.request.id
        })
        
        # Update document status
        self.db_manager.update_neo4j_document_status(neo4j_doc_sql_id, "error_ner")
        
        countdown = int(self.default_retry_delay * (2 ** self.request.retries))
        raise self.retry(exc=exc, countdown=min(countdown, 600))


@app.task(bind=True, base=EntityTask, max_retries=3, default_retry_delay=60, queue='entity')
def resolve_entities(self, document_uuid: str, source_doc_sql_id: int,
                    neo4j_doc_sql_id: int, neo4j_doc_uuid: str, 
                    entity_mentions: List[Dict] = None, full_document_text: str = None) -> Dict[str, Any]:
    """
    Resolve and canonicalize extracted entities.
    
    Args:
        document_uuid: UUID of the source document
        source_doc_sql_id: SQL ID of the source document
        neo4j_doc_sql_id: SQL ID of the neo4j_documents entry
        neo4j_doc_uuid: UUID of the neo4j_documents entry
        entity_mentions: List of entity mention dictionaries (optional - will fetch from Redis if not provided)
        full_document_text: Full document text for context (optional - will fetch from DB if not provided)
    
    Returns:
        Dict containing resolution results
    """
    logger.info(f"[RESOLUTION_TASK:{self.request.id}] Resolving entities for document {neo4j_doc_uuid}")
    
    # Check if stage is already completed
    processing_version = None
    if source_doc_sql_id:
        version_response = self.db_manager.client.table('source_documents').select(
            'processing_version'
        ).eq('document_uuid', document_uuid).execute()
        processing_version = version_response.data[0]['processing_version'] if version_response.data else 1
    
    is_completed, cached_results = check_stage_completed(document_uuid, "resolution", processing_version)
    if is_completed and cached_results:
        logger.info(f"[RESOLUTION_TASK:{self.request.id}] Stage already completed, using cached results")
        
        # Chain to relationship building task
        from celery_tasks.graph_tasks import build_relationships
        
        # Fetch document data for relationships
        doc_data_raw = self.db_manager.client.table('neo4j_documents').select(
            'name, category, fileType, project_id'
        ).eq('id', neo4j_doc_sql_id).maybe_single().execute()
        
        if doc_data_raw.data:
            # Get project UUID
            project_info = self.db_manager.get_project_by_sql_id_or_global_project_id(
                doc_data_raw.data['project_id'], None
            )
            project_uuid = project_info['project_uuid'] if isinstance(project_info, dict) else project_info
            
            # Fetch chunks
            chunks_raw = self.db_manager.client.table('neo4j_chunks').select(
                'chunkId, chunkIndex'
            ).eq('document_id', neo4j_doc_sql_id).execute()
            
            chunks_for_rels = [{"chunkId": c['chunkId'], "chunkIndex": c['chunkIndex']} for c in chunks_raw.data]
            
            build_relationships.delay(
                document_uuid=document_uuid,
                source_doc_sql_id=source_doc_sql_id,
                doc_data={
                    "documentId": neo4j_doc_uuid,
                    "sql_id": neo4j_doc_sql_id,
                    "name": doc_data_raw.data['name'],
                    "category": doc_data_raw.data['category'],
                    "file_type": doc_data_raw.data['fileType']
                },
                project_uuid=project_uuid,
                chunks=chunks_for_rels
            )
        
        return {
            "status": "skipped_completed",
            "cached": True,
            "canonical_count": len(cached_results) if isinstance(cached_results, list) else 0
        }
    
    # Try to fetch entity mentions from Redis if not provided
    if entity_mentions is None:
        redis_mgr = get_redis_manager()
        if redis_mgr and redis_mgr.is_available():
            # Use processing version from above
            if 'processing_version' not in locals():
                version_response = self.db_manager.client.table('source_documents').select(
                    'processing_version'
                ).eq('document_uuid', document_uuid).execute()
                
                processing_version = version_response.data[0]['processing_version'] if version_response.data else 1
            
            mentions_key = CacheKeys.format_key(
                CacheKeys.DOC_ALL_EXTRACTED_MENTIONS, 
                version=processing_version,
                document_uuid=document_uuid
            )
            entity_mentions = redis_mgr.get_cached(mentions_key)
            
            if entity_mentions:
                logger.info(f"[RESOLUTION_TASK:{self.request.id}] Retrieved {len(entity_mentions)} mentions from Redis cache")
            else:
                logger.error(f"[RESOLUTION_TASK:{self.request.id}] No entity mentions found in Redis for {document_uuid}")
                # Could also fetch from database here if needed
                raise ValueError("No entity mentions available for resolution")
        else:
            logger.error(f"[RESOLUTION_TASK:{self.request.id}] Redis not available, cannot fetch entity mentions")
            raise ValueError("Redis not available for fetching entity mentions")
    
    # Fetch full document text if not provided
    if full_document_text is None:
        doc_record = self.db_manager.client.table('neo4j_documents').select(
            'cleaned_text_for_chunking'
        ).eq('id', neo4j_doc_sql_id).maybe_single().execute()
        
        full_document_text = doc_record.data.get('cleaned_text_for_chunking', '') if doc_record.data else ''
        logger.info(f"[RESOLUTION_TASK:{self.request.id}] Fetched document text from database")
    
    logger.info(f"[RESOLUTION_TASK:{self.request.id}] Resolving {len(entity_mentions)} entities for document {neo4j_doc_uuid}")
    update_document_state(document_uuid, "resolution", "started", {
        "task_id": self.request.id,
        "mention_count": len(entity_mentions)
    })
    
    # Update Celery status in source_documents
    self.db_manager.client.table('source_documents').update({
        'celery_status': 'entity_resolution',
        'last_modified_at': datetime.now().isoformat()
    }).eq('id', source_doc_sql_id).execute()
    
    try:
        # Check if embeddings are available for enhanced resolution
        chunk_embeddings = {}
        use_enhanced_resolution = False
        
        try:
            # Get unique chunk IDs from entity mentions
            chunk_ids = list(set(em.get('chunk_uuid') for em in entity_mentions if em.get('chunk_uuid')))
            
            if chunk_ids:
                # Try to get embeddings from database
                try:
                    embeddings_result = self.db_manager.service_client.table('chunk_embeddings').select(
                        'chunk_id, embedding'
                    ).in_('chunk_id', chunk_ids[:100]).execute()  # Limit to 100 for query size
                    
                    if embeddings_result.data:
                        for emb_data in embeddings_result.data:
                            chunk_embeddings[emb_data['chunk_id']] = np.array(emb_data['embedding'])
                        logger.info(f"[RESOLUTION_TASK:{self.request.id}] Found embeddings for {len(chunk_embeddings)}/{len(chunk_ids)} chunks")
                        use_enhanced_resolution = len(chunk_embeddings) > 0
                except Exception as db_error:
                    if 'relation "public.chunk_embeddings" does not exist' in str(db_error):
                        logger.info(f"[RESOLUTION_TASK:{self.request.id}] Embeddings table not found, using standard resolution")
                    else:
                        raise
        except Exception as e:
            logger.warning(f"[RESOLUTION_TASK:{self.request.id}] Error fetching embeddings: {e}")
        
        # Perform entity resolution
        if use_enhanced_resolution:
            from entity_resolution_enhanced import enhanced_entity_resolution
            logger.info(f"[RESOLUTION_TASK:{self.request.id}] Using enhanced resolution with embeddings")
            resolved_canonicals_list, updated_mentions_list = enhanced_entity_resolution(
                entity_mentions, 
                full_document_text,
                chunk_embeddings=chunk_embeddings,
                similarity_threshold=0.75,
                semantic_weight=0.7
            )
        else:
            logger.info(f"[RESOLUTION_TASK:{self.request.id}] Using standard resolution (no embeddings)")
            resolved_canonicals_list, updated_mentions_list = resolve_document_entities(
                entity_mentions, full_document_text
            )
        
        # Map temporary canonical IDs to actual database UUIDs and SQL IDs
        map_temp_canon_id_to_neo4j_uuid = {}
        map_temp_canon_id_to_sql_id = {}
        final_canonical_entities = []
        
        # Create canonical entities in database
        for ce_attrs_temp in resolved_canonicals_list:
            ce_sql_id, ce_neo4j_uuid = self.db_manager.create_canonical_entity_entry(
                neo4j_doc_sql_id=neo4j_doc_sql_id,
                document_uuid=neo4j_doc_uuid,
                canonical_name=ce_attrs_temp["canonicalName"],
                entity_type_label=ce_attrs_temp["entity_type"],
                aliases_json=ce_attrs_temp.get("allKnownAliasesInDoc_json"),
                mention_count=ce_attrs_temp.get("mention_count_in_doc", 1),
                first_seen_idx=ce_attrs_temp.get("firstSeenAtChunkIndex_int", 0)
            )
            
            if ce_sql_id and ce_neo4j_uuid:
                # Map temp ID to real UUID and SQL ID
                map_temp_canon_id_to_neo4j_uuid[ce_attrs_temp["canonicalEntityId_temp"]] = ce_neo4j_uuid
                map_temp_canon_id_to_sql_id[ce_attrs_temp["canonicalEntityId_temp"]] = ce_sql_id
                
                # Add to final list with real UUID
                final_canonical_entities.append({
                    **ce_attrs_temp,
                    "canonicalEntityId": ce_neo4j_uuid,
                    "sql_id": ce_sql_id
                })
        
        # Update entity mentions with resolved canonical IDs
        final_entity_mentions = []
        for em_data_updated in updated_mentions_list:
            temp_canon_id = em_data_updated.get("resolved_canonical_id_temp")
            if temp_canon_id and temp_canon_id in map_temp_canon_id_to_neo4j_uuid:
                em_data_updated['resolved_canonical_id_neo4j'] = map_temp_canon_id_to_neo4j_uuid[temp_canon_id]
                
                # Update the entity mention in the database with SQL ID
                if 'entity_mention_sql_id' in em_data_updated:
                    self.db_manager.client.table('neo4j_entity_mentions').update({
                        'resolved_canonical_id': map_temp_canon_id_to_sql_id[temp_canon_id]
                    }).eq('id', em_data_updated['entity_mention_sql_id']).execute()
                    
            final_entity_mentions.append(em_data_updated)
        
        # Cache canonical entities and resolved mentions in Redis with version
        try:
            redis_mgr = get_redis_manager()
            if redis_mgr and redis_mgr.is_available():
                # Get processing version
                version_response = self.db_manager.client.table('source_documents').select(
                    'processing_version'
                ).eq('document_uuid', document_uuid).execute()
                
                processing_version = version_response.data[0]['processing_version'] if version_response.data else 1
                
                # Cache canonical entities
                canonical_key = CacheKeys.format_key(
                    CacheKeys.DOC_CANONICAL_ENTITIES, 
                    version=processing_version,
                    document_uuid=document_uuid
                )
                redis_mgr.set_cached(canonical_key, final_canonical_entities, ttl=3 * 24 * 3600)  # 3 days
                logger.info(f"[RESOLUTION_TASK:{self.request.id}] Cached {len(final_canonical_entities)} canonical entities in Redis with version {processing_version}")
                
                # Cache resolved mentions
                resolved_key = CacheKeys.format_key(
                    CacheKeys.DOC_RESOLVED_MENTIONS, 
                    version=processing_version,
                    document_uuid=document_uuid
                )
                redis_mgr.set_cached(resolved_key, final_entity_mentions, ttl=2 * 24 * 3600)  # 2 days
                logger.info(f"[RESOLUTION_TASK:{self.request.id}] Cached {len(final_entity_mentions)} resolved mentions in Redis with version {processing_version}")
        except Exception as e:
            logger.warning(f"Failed to cache resolution results in Redis: {e}")
        
        # Update document status
        self.db_manager.update_neo4j_document_status(neo4j_doc_sql_id, "pending_relationships")
        
        # Update state
        update_document_state(document_uuid, "resolution", "completed", {
            "canonical_count": len(final_canonical_entities),
            "resolved_mentions": len(final_entity_mentions)
        })
        
        # Update Celery status to resolution_complete
        self.db_manager.client.table('source_documents').update({
            'celery_status': 'resolution_complete',
            'last_modified_at': datetime.now().isoformat()
        }).eq('id', source_doc_sql_id).execute()
        
        # Chain to relationship building task
        from celery_tasks.graph_tasks import build_relationships
        
        # Fetch document data for relationships
        doc_data_raw = self.db_manager.client.table('neo4j_documents').select(
            'name, category, fileType, project_id'
        ).eq('id', neo4j_doc_sql_id).maybe_single().execute()
        
        # Get project UUID
        project_info = self.db_manager.get_project_by_sql_id_or_global_project_id(
            doc_data_raw.data['project_id'], None
        )
        project_uuid = project_info['project_uuid'] if isinstance(project_info, dict) else project_info
        
        doc_data = {
            "documentId": neo4j_doc_uuid,
            "sql_id": neo4j_doc_sql_id,
            "name": doc_data_raw.data['name'],
            "category": doc_data_raw.data['category'],
            "file_type": doc_data_raw.data['fileType']
        }
        
        # Fetch chunks
        chunks_raw = self.db_manager.client.table('neo4j_chunks').select(
            'chunkId, chunkIndex'
        ).eq('document_id', neo4j_doc_sql_id).execute()
        
        chunks_for_rels = [{"chunkId": c['chunkId'], "chunkIndex": c['chunkIndex']} for c in chunks_raw.data]
        
        # Prepare entity mentions with required fields for relationship building
        mentions_for_rels = []
        for em in final_entity_mentions:
            mentions_for_rels.append({
                "entityMentionId": em.get("entity_mention_id_neo4j"),
                "chunk_uuid": em.get("parent_chunk_id_neo4j"),
                "resolved_canonical_id_neo4j": em.get("resolved_canonical_id_neo4j"),
                "value": em.get("value"),
                "entity_type": em.get("entity_type")
            })
        
        build_relationships.delay(
            document_uuid=document_uuid,
            source_doc_sql_id=source_doc_sql_id,
            doc_data=doc_data,
            project_uuid=project_uuid,
            chunks=chunks_for_rels,
            entity_mentions=mentions_for_rels,
            canonical_entities=final_canonical_entities
        )
        
        return {
            "status": "success",
            "canonical_count": len(final_canonical_entities),
            "resolved_mentions": len(final_entity_mentions)
        }
        
    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {str(exc)}"
        logger.exception(f"[RESOLUTION_TASK:{self.request.id}] Error: {exc}")
        
        # Save error to database
        try:
            self.db_manager.client.table('source_documents').update({
                'error_message': error_msg[:500],  # Truncate long errors
                'celery_status': 'resolution_failed',
                'last_modified_at': datetime.now().isoformat()
            }).eq('id', source_doc_sql_id).execute()
        except Exception as db_exc:
            logger.error(f"Failed to save error to database: {db_exc}")
        
        # Update state for monitoring
        update_document_state(document_uuid, "resolution", "failed", {
            "error": error_msg,
            "task_id": self.request.id
        })
        
        # Update document status
        self.db_manager.update_neo4j_document_status(neo4j_doc_sql_id, "error_resolution")
        
        countdown = int(self.default_retry_delay * (2 ** self.request.retries))
        raise self.retry(exc=exc, countdown=min(countdown, 600))