"""
Text Processing Tasks for Celery-based Document Processing Pipeline
"""
from celery import Task
from scripts.celery_app import app
from scripts.text_processing import (
    clean_extracted_text, categorize_document_text,
    process_document_with_semantic_chunking
)
from scripts.database import SupabaseManager
from scripts.cache import get_redis_manager, CacheKeys
from scripts.config import USE_STRUCTURED_EXTRACTION, REDIS_CHUNK_CACHE_TTL
from scripts.celery_tasks.idempotent_ops import IdempotentDatabaseOps
from scripts.celery_tasks.processing_state import ProcessingStateManager
from scripts.celery_tasks.task_utils import update_document_state, check_stage_completed
import logging
import json
from datetime import datetime
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class TextTask(Task):
    """Base class for text processing tasks with database connection management"""
    _db_manager = None
    _idempotent_ops = None
    _state_manager = None
    
    @property
    def db_manager(self):
        if self._db_manager is None:
            self._db_manager = SupabaseManager()
        return self._db_manager
    
    @property
    def idempotent_ops(self):
        if self._idempotent_ops is None:
            self._idempotent_ops = IdempotentDatabaseOps(self.db_manager)
        return self._idempotent_ops
    
    @property
    def state_manager(self):
        if self._state_manager is None:
            redis_mgr = get_redis_manager()
            self._state_manager = ProcessingStateManager(self.db_manager, redis_mgr)
        return self._state_manager
    
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Called when the task fails."""
        document_uuid = kwargs.get('document_uuid', 'unknown')
        logger.error(f"Task {task_id} failed for document {document_uuid}: {exc}")
        update_document_state(document_uuid, "text_processing", "failed", {"error": str(exc), "task_id": task_id})


@app.task(bind=True, base=TextTask, max_retries=3, default_retry_delay=60, queue='text')
def create_document_node(self, document_uuid: str, source_doc_sql_id: int, 
                        project_sql_id: int, file_name: str = None, 
                        detected_file_type: str = None, raw_text: str = None, 
                        ocr_meta_json: Optional[str] = None) -> Dict[str, Any]:
    """
    Create Neo4j document node and prepare for chunking.
    
    Args:
        document_uuid: UUID of the source document
        source_doc_sql_id: SQL ID of the source document
        project_sql_id: SQL ID of the project
        file_name: Name of the file (optional - will fetch from cache if not provided)
        detected_file_type: File type/extension (optional - will fetch from cache if not provided)
        raw_text: Extracted text from OCR (optional - will fetch from cache if not provided)
        ocr_meta_json: JSON string of OCR metadata (optional - will fetch from cache if not provided)
    
    Returns:
        Dict containing processing results
    """
    logger.info(f"[DOC_NODE_TASK:{self.request.id}] Creating Neo4j document node for {document_uuid}")
    
    # Check if stage is already completed
    processing_version = None
    if source_doc_sql_id:
        version_response = self.db_manager.client.table('source_documents').select(
            'processing_version'
        ).eq('id', source_doc_sql_id).execute()
        processing_version = version_response.data[0]['processing_version'] if version_response.data else 1
    
    is_completed, cached_results = check_stage_completed(document_uuid, "doc_node_creation", processing_version)
    if is_completed and cached_results:
        logger.info(f"[DOC_NODE_TASK:{self.request.id}] Stage already completed, using cached results")
        
        # Update database status from cache hit
        from scripts.celery_tasks.task_utils import update_status_on_cache_hit
        update_status_on_cache_hit(document_uuid, 'text', self.db_manager)
        
        # Get neo4j document info
        neo4j_doc_response = self.db_manager.client.table('neo4j_documents').select(
            'id, documentId'
        ).eq('source_document_fk_id', source_doc_sql_id).execute()
        
        if neo4j_doc_response.data:
            neo4j_doc_sql_id = neo4j_doc_response.data[0]['id']
            neo4j_doc_uuid = neo4j_doc_response.data[0]['documentId']
            
            # Chain to next task directly
            process_chunking.delay(
                document_uuid=document_uuid,
                neo4j_doc_sql_id=neo4j_doc_sql_id,
                neo4j_doc_uuid=neo4j_doc_uuid,
                source_doc_sql_id=source_doc_sql_id
            )
        
        return {
            "status": "skipped_completed",
            "cached": True,
            "neo4j_doc_uuid": cached_results.get('neo4j_doc_uuid'),
            "category": cached_results.get('category')
        }
    
    update_document_state(document_uuid, "doc_node_creation", "started", {"task_id": self.request.id})
    
    # Update Celery status in source_documents
    self.db_manager.client.table('source_documents').update({
        'celery_status': 'text_processing',
        'last_modified_at': datetime.now().isoformat()
    }).eq('id', source_doc_sql_id).execute()
    
    try:
        # Try to fetch OCR result from Redis if not provided
        if raw_text is None or file_name is None or detected_file_type is None:
            redis_mgr = get_redis_manager()
            if redis_mgr and redis_mgr.is_available():
                # Get processing version
                version_response = self.db_manager.client.table('source_documents').select(
                    'processing_version'
                ).eq('id', source_doc_sql_id).execute()
                
                processing_version = None
                if version_response.data and len(version_response.data) > 0:
                    processing_version = version_response.data[0].get('processing_version')
                
                # Check cache
                ocr_cache_key = CacheKeys.format_key(
                    CacheKeys.DOC_OCR_RESULT, 
                    version=processing_version,
                    document_uuid=document_uuid
                )
                cached_ocr = redis_mgr.get_cached(ocr_cache_key)
                
                if cached_ocr:
                    logger.info(f"[DOC_NODE_TASK:{self.request.id}] Retrieved OCR data from Redis cache")
                    raw_text = raw_text or cached_ocr.get('raw_text')
                    file_name = file_name or cached_ocr.get('file_name')
                    detected_file_type = detected_file_type or cached_ocr.get('detected_file_type')
                    if ocr_meta_json is None and cached_ocr.get('ocr_meta'):
                        ocr_meta_json = json.dumps(cached_ocr.get('ocr_meta'))
        
        # If still missing data, fetch from database
        if raw_text is None or file_name is None or detected_file_type is None:
            doc_response = self.db_manager.client.table('source_documents').select(
                'raw_extracted_text, original_file_name, detected_file_type, ocr_metadata_json'
            ).eq('id', source_doc_sql_id).execute()
            
            if doc_response.data and len(doc_response.data) > 0:
                doc_data = doc_response.data[0]
                raw_text = raw_text or doc_data.get('raw_extracted_text')
                file_name = file_name or doc_data.get('original_file_name')
                detected_file_type = detected_file_type or doc_data.get('detected_file_type')
                ocr_meta_json = ocr_meta_json or doc_data.get('ocr_metadata_json')
        
        if not raw_text:
            raise ValueError("No text content available for document")
        
        # Parse OCR metadata if provided
        ocr_meta = json.loads(ocr_meta_json) if ocr_meta_json else None
        
        # Get project UUID
        project_info = self.db_manager.get_project_by_sql_id_or_global_project_id(project_sql_id, None)
        if not project_info:
            raise ValueError(f"Could not find project UUID for project_sql_id {project_sql_id}")
        
        project_uuid = project_info['project_uuid'] if isinstance(project_info, dict) else project_info
        
        # Create neo4j_documents entry using idempotent operation
        neo4j_doc_sql_id, neo4j_doc_uuid = self.idempotent_ops.upsert_neo4j_document(
            source_doc_uuid=document_uuid,
            source_doc_id=source_doc_sql_id,
            project_id=project_sql_id,
            project_uuid=project_uuid,
            file_name=file_name
        )
        
        if not neo4j_doc_sql_id:
            raise RuntimeError(f"Failed to create neo4j_documents entry for {file_name}")
        
        # Clean the text
        cleaned_text = clean_extracted_text(raw_text)
        
        # Categorize the document
        doc_category = categorize_document_text(cleaned_text, ocr_meta)
        
        # Update neo4j_documents with details
        self.db_manager.update_neo4j_document_details(
            neo4j_doc_sql_id,
            category=doc_category,
            file_type=detected_file_type,
            cleaned_text=cleaned_text,
            status="pending_chunking"
        )
        
        # Update source document status
        self.db_manager.update_processing_status('source_documents', source_doc_sql_id, 'neo4j_node_created')
        
        # Cache cleaned text and category
        redis_mgr = get_redis_manager()
        if redis_mgr and redis_mgr.is_available():
            # Get processing version
            version_response = self.db_manager.client.table('source_documents').select(
                'processing_version'
            ).eq('id', source_doc_sql_id).execute()
            
            processing_version = None
            if version_response.data and len(version_response.data) > 0:
                processing_version = version_response.data[0].get('processing_version')
            
            # Cache cleaned text
            cleaned_text_key = CacheKeys.format_key(
                CacheKeys.DOC_CLEANED_TEXT,
                version=processing_version,
                document_uuid=document_uuid
            )
            redis_mgr.set_cached(cleaned_text_key, {
                'cleaned_text': cleaned_text,
                'category': doc_category,
                'neo4j_doc_uuid': neo4j_doc_uuid,
                'neo4j_doc_sql_id': neo4j_doc_sql_id
            }, ttl=3 * 24 * 3600)  # 3 days
            logger.info(f"[DOC_NODE_TASK:{self.request.id}] Cached cleaned text and category in Redis")
        
        # Update state
        update_document_state(document_uuid, "doc_node_creation", "completed", {
            "neo4j_doc_uuid": neo4j_doc_uuid,
            "category": doc_category
        })
        
        # Chain to chunking task (pass only document_uuid)
        process_chunking.delay(
            document_uuid=document_uuid,
            neo4j_doc_sql_id=neo4j_doc_sql_id,
            neo4j_doc_uuid=neo4j_doc_uuid,
            source_doc_sql_id=source_doc_sql_id
        )
        
        return {
            "status": "success",
            "neo4j_doc_sql_id": neo4j_doc_sql_id,
            "neo4j_doc_uuid": neo4j_doc_uuid,
            "category": doc_category
        }
        
    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {str(exc)}"
        logger.exception(f"[DOC_NODE_TASK:{self.request.id}] Error: {exc}")
        
        # Save error to database
        try:
            self.db_manager.client.table('source_documents').update({
                'error_message': error_msg[:500],  # Truncate long errors
                'celery_status': 'text_failed',
                'last_modified_at': datetime.now().isoformat()
            }).eq('id', source_doc_sql_id).execute()
        except Exception as db_exc:
            logger.error(f"Failed to save error to database: {db_exc}")
        
        # Update state for monitoring
        update_document_state(document_uuid, "doc_node_creation", "failed", {
            "error": error_msg,
            "task_id": self.request.id
        })
        
        countdown = int(self.default_retry_delay * (2 ** self.request.retries))
        raise self.retry(exc=exc, countdown=min(countdown, 600))


@app.task(bind=True, base=TextTask, max_retries=3, default_retry_delay=60, queue='text')
def process_chunking(self, document_uuid: str, neo4j_doc_sql_id: int,
                    neo4j_doc_uuid: str, cleaned_text: str = None, 
                    ocr_meta_json: Optional[str] = None, 
                    doc_category: str = None,
                    source_doc_sql_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Perform semantic chunking on document text.
    
    Args:
        document_uuid: UUID of the source document
        neo4j_doc_sql_id: SQL ID of the neo4j_documents entry
        neo4j_doc_uuid: UUID of the neo4j_documents entry
        cleaned_text: Cleaned text to chunk
        ocr_meta_json: JSON string of OCR metadata
        doc_category: Document category
    
    Returns:
        Dict containing chunking results
    """
    logger.info(f"[CHUNKING_TASK:{self.request.id}] Chunking document {neo4j_doc_uuid}")
    
    # Check if stage is already completed
    processing_version = None
    if source_doc_sql_id:
        version_response = self.db_manager.client.table('source_documents').select(
            'processing_version'
        ).eq('document_uuid', document_uuid).execute()
        processing_version = version_response.data[0]['processing_version'] if version_response.data else 1
    
    is_completed, cached_results = check_stage_completed(document_uuid, "chunking", processing_version)
    if is_completed and cached_results:
        logger.info(f"[CHUNKING_TASK:{self.request.id}] Stage already completed, using cached results")
        
        # Update database status from cache hit
        from scripts.celery_tasks.task_utils import update_status_on_cache_hit
        update_status_on_cache_hit(document_uuid, 'text', self.db_manager)
        
        # Get chunk data for NER
        chunks_response = self.db_manager.client.table('neo4j_chunks').select(
            'id, chunkId, chunkIndex'
        ).eq('document_id', neo4j_doc_sql_id).execute()
        
        if chunks_response.data:
            chunk_data = [{
                "sql_id": chunk['id'],
                "chunk_uuid": chunk['chunkId'],
                "chunk_index": chunk['chunkIndex']
            } for chunk in chunks_response.data]
            
            # Chain to NER task
            from scripts.celery_tasks.entity_tasks import extract_entities
            extract_entities.delay(
                document_uuid=document_uuid,
                source_doc_sql_id=source_doc_sql_id,
                neo4j_doc_sql_id=neo4j_doc_sql_id,
                neo4j_doc_uuid=neo4j_doc_uuid,
                chunk_data=chunk_data
            )
        
        return {
            "status": "skipped_completed",
            "cached": True,
            "chunk_count": len(cached_results) if isinstance(cached_results, list) else 0
        }
    
    update_document_state(document_uuid, "chunking", "started", {"task_id": self.request.id})
    
    try:
        # Fetch cleaned text from Redis if not provided
        if not cleaned_text:
            redis_mgr = get_redis_manager()
            if redis_mgr and redis_mgr.is_available():
                # Use processing version from above
                if 'processing_version' not in locals():
                    version_response = self.db_manager.client.table('source_documents').select(
                        'processing_version'
                    ).eq('document_uuid', document_uuid).execute()
                    
                    processing_version = version_response.data[0]['processing_version'] if version_response.data else 1
                
                # Check cache for cleaned text
                cleaned_text_key = CacheKeys.format_key(
                    CacheKeys.DOC_CLEANED_TEXT,
                    version=processing_version,
                    document_uuid=document_uuid
                )
                cached_data = redis_mgr.get_cached(cleaned_text_key)
                
                if cached_data:
                    cleaned_text = cached_data.get('cleaned_text')
                    if not doc_category:
                        doc_category = cached_data.get('category')
                    logger.info(f"[CHUNKING_TASK:{self.request.id}] Retrieved cleaned text from Redis cache")
                else:
                    logger.warning(f"[CHUNKING_TASK:{self.request.id}] No cached cleaned text found")
        
        # If still no cleaned text, fetch from database
        if not cleaned_text:
            doc_response = self.db_manager.client.table('neo4j_documents').select(
                'cleaned_text_for_chunking', 'category'
            ).eq('id', neo4j_doc_sql_id).execute()
            
            if doc_response.data:
                cleaned_text = doc_response.data[0]['cleaned_text_for_chunking']
                if not doc_category:
                    doc_category = doc_response.data[0]['category']
                logger.info(f"[CHUNKING_TASK:{self.request.id}] Retrieved cleaned text from database")
            else:
                raise ValueError(f"No cleaned text available for document {document_uuid}")
        
        # Parse OCR metadata
        ocr_meta = None
        if ocr_meta_json:
            logger.debug(f"ocr_meta_json value: {repr(ocr_meta_json)}")
            if isinstance(ocr_meta_json, str) and ocr_meta_json.strip():
                ocr_meta = json.loads(ocr_meta_json)
        
        # Process document with semantic chunking
        processed_chunks_list, document_structured_data = process_document_with_semantic_chunking(
            self.db_manager,
            neo4j_doc_sql_id,
            neo4j_doc_uuid,
            cleaned_text,
            ocr_meta,
            doc_category,
            use_structured_extraction=USE_STRUCTURED_EXTRACTION
        )
        
        # Update document with structured data if available
        if document_structured_data and USE_STRUCTURED_EXTRACTION:
            # Convert Pydantic model to dict for JSON serialization
            structured_data_dict = document_structured_data.model_dump() if hasattr(document_structured_data, 'model_dump') else document_structured_data.dict()
            self.db_manager.update_neo4j_document_details(
                neo4j_doc_sql_id,
                metadata_json=structured_data_dict
            )
        
        # Update document status
        self.db_manager.update_neo4j_document_status(neo4j_doc_sql_id, "pending_ner")
        
        # Extract chunks from the result model
        chunks_list = processed_chunks_list.chunks if hasattr(processed_chunks_list, 'chunks') else []
        
        # Update state
        update_document_state(document_uuid, "chunking", "completed", {
            "chunk_count": len(chunks_list),
            "has_structured_data": bool(document_structured_data)
        })
        
        # Prepare chunk data for NER task
        chunk_data = [{
            "sql_id": chunk.sql_id if hasattr(chunk, 'sql_id') else chunk.get('sql_id'),
            "chunk_uuid": chunk.chunk_uuid if hasattr(chunk, 'chunk_uuid') else chunk.get('chunk_uuid'),
            "chunk_index": chunk.chunk_index if hasattr(chunk, 'chunk_index') else chunk.get('chunkIndex')
        } for chunk in chunks_list]
        
        # Cache the chunk list in Redis for efficient retrieval by subsequent stages
        redis_mgr = get_redis_manager()
        if redis_mgr and redis_mgr.is_available():
            try:
                # Get processing version
                version_response = self.db_manager.client.table('source_documents').select(
                    'processing_version'
                ).eq('document_uuid', document_uuid).execute()
                
                processing_version = version_response.data[0]['processing_version'] if version_response.data else 1
                
                # Cache the list of chunk UUIDs with version
                chunks_list_key = CacheKeys.format_key(
                    CacheKeys.DOC_CHUNKS_LIST, 
                    version=processing_version,
                    document_uuid=document_uuid
                )
                chunk_uuids = [chunk['chunk_uuid'] for chunk in chunk_data]
                redis_mgr.set_cached(chunks_list_key, chunk_uuids, ttl=REDIS_CHUNK_CACHE_TTL)
                
                # Cache individual chunk texts for entity extraction
                for i, chunk in enumerate(chunks_list):
                    chunk_text = chunk.text if hasattr(chunk, 'text') else chunk.get('text', '')
                    if chunk_text:  # Only cache if text is available
                        chunk_uuid = chunk_data[i]['chunk_uuid']
                        chunk_text_key = CacheKeys.format_key(
                            CacheKeys.DOC_CHUNK_TEXT, 
                            chunk_uuid=chunk_uuid
                        )
                        redis_mgr.set_cached(chunk_text_key, chunk_text, ttl=REDIS_CHUNK_CACHE_TTL)
                
                logger.info(f"[CHUNKING_TASK:{self.request.id}] Cached {len(chunk_uuids)} chunks in Redis with version {processing_version}")
            except Exception as e:
                logger.warning(f"[CHUNKING_TASK:{self.request.id}] Failed to cache chunks in Redis: {e}")
        
        # Chain to embedding generation, which will then chain to NER
        # Prepare chunks data for embedding task
        chunks_for_embedding = []
        for i, chunk in enumerate(chunks_list):
            chunk_text = chunk.text if hasattr(chunk, 'text') else chunk.get('text', '')
            chunks_for_embedding.append({
                'chunkId': chunk_data[i]['chunk_uuid'],
                'chunkText': chunk_text,
                'chunkIndex': chunk_data[i]['chunk_index']
            })
        
        from scripts.celery_tasks.embedding_tasks import generate_chunk_embeddings
        generate_chunk_embeddings.delay(
            document_uuid=document_uuid,
            source_doc_sql_id=source_doc_sql_id,
            chunks=chunks_for_embedding,
            processing_version=processing_version if 'processing_version' in locals() else 1
        )
        
        # Note: The embedding task will chain to entity extraction after completion
        
        return {
            "status": "success",
            "chunk_count": len(chunks_list),
            "chunks": chunk_data,
            "has_structured_data": bool(document_structured_data)
        }
        
    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {str(exc)}"
        logger.exception(f"[CHUNKING_TASK:{self.request.id}] Error: {exc}")
        
        # Save error to database (need source_doc_sql_id)
        try:
            if source_doc_sql_id:
                self.db_manager.client.table('source_documents').update({
                    'error_message': error_msg[:500],  # Truncate long errors
                    'celery_status': 'text_failed',
                    'last_modified_at': datetime.now().isoformat()
                }).eq('id', source_doc_sql_id).execute()
        except Exception as db_exc:
            logger.error(f"Failed to save error to database: {db_exc}")
        
        # Update state for monitoring
        update_document_state(document_uuid, "chunking", "failed", {
            "error": error_msg,
            "task_id": self.request.id
        })
        
        # Update document status
        self.db_manager.update_neo4j_document_status(neo4j_doc_sql_id, "error_chunking")
        
        countdown = int(self.default_retry_delay * (2 ** self.request.retries))
        raise self.retry(exc=exc, countdown=min(countdown, 600))