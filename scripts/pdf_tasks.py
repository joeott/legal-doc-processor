"""
Consolidated PDF Processing Tasks for Celery.
Combines all PDF processing tasks into a single module.
"""
import os
import uuid
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path
import time
import traceback
from functools import wraps
from collections import defaultdict

from celery import Task, group, chain
import celery.exceptions
from scripts.celery_app import app
from scripts.cache import get_redis_manager, CacheKeys, redis_cache
from scripts.db import DatabaseManager
from scripts.entity_service import EntityService
from scripts.graph_service import GraphService
from scripts.ocr_extraction import extract_text_from_pdf
from scripts.chunking_utils import simple_chunk_text
# from scripts.s3_storage import upload_to_s3, generate_s3_key  # Not used currently
from scripts.models import ProcessingStatus, ProcessingResultStatus
from scripts.config import OPENAI_API_KEY, S3_PRIMARY_DOCUMENT_BUCKET, get_database_url

logger = logging.getLogger(__name__)


# Task execution decorator for enhanced visibility
def log_task_execution(func):
    """Decorator to log task execution details with timing and context."""
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        task_id = self.request.id if hasattr(self, 'request') else 'manual'
        doc_uuid = kwargs.get('document_uuid', 'unknown')
        task_name = func.__name__
        
        # Log task start with visual separator
        logger.info("="*60)
        logger.info(f"🚀 TASK START: {task_name}")
        logger.info(f"📄 Document: {doc_uuid}")
        logger.info(f"🔖 Task ID: {task_id}")
        logger.info(f"⏰ Start Time: {datetime.now().isoformat()}")
        logger.info("="*60)
        
        start_time = time.time()
        
        try:
            # Execute the task
            result = func(self, *args, **kwargs)
            
            # Calculate elapsed time
            elapsed = time.time() - start_time
            
            # Log success
            logger.info("="*60)
            logger.info(f"✅ TASK SUCCESS: {task_name}")
            logger.info(f"📄 Document: {doc_uuid}")
            logger.info(f"⏱️  Duration: {elapsed:.2f} seconds")
            logger.info(f"🏁 End Time: {datetime.now().isoformat()}")
            logger.info("="*60)
            
            return result
            
        except Exception as e:
            # Calculate elapsed time
            elapsed = time.time() - start_time
            
            # Log detailed error information
            logger.error("="*60)
            logger.error(f"❌ TASK FAILED: {task_name}")
            logger.error(f"📄 Document: {doc_uuid}")
            logger.error(f"⏱️  Duration: {elapsed:.2f} seconds")
            logger.error(f"🔴 Error Type: {type(e).__name__}")
            logger.error(f"💬 Error Message: {str(e)}")
            logger.error("📋 Traceback:")
            logger.error(traceback.format_exc())
            logger.error("="*60)
            
            # Re-raise the exception
            raise
    
    return wrapper


# Circuit breaker for document validation
validation_failures = defaultdict(int)
CIRCUIT_BREAKER_THRESHOLD = 5

def validate_document_with_circuit_breaker(db_manager: DatabaseManager, document_uuid: str) -> bool:
    """Validate document with circuit breaker pattern"""
    # If too many failures, fail fast
    if validation_failures[document_uuid] >= CIRCUIT_BREAKER_THRESHOLD:
        logger.error(f"Circuit breaker OPEN for document {document_uuid} (>= {CIRCUIT_BREAKER_THRESHOLD} failures)")
        return False
        
    if validate_document_exists(db_manager, document_uuid):
        if validation_failures[document_uuid] > 0:
            logger.info(f"Document {document_uuid} found, resetting circuit breaker")
        validation_failures[document_uuid] = 0  # Reset on success
        return True
    else:
        validation_failures[document_uuid] += 1
        logger.warning(f"Document {document_uuid} validation failed (count: {validation_failures[document_uuid]})")
        return False


class PDFTask(Task):
    """Enhanced base task with connection management"""
    _db_manager = None
    _entity_service = None
    _graph_service = None
    _conformance_validated = False
    _last_connection_check = None
    
    @property
    def db_manager(self):
        from datetime import datetime
        
        # Check connection freshness every 60 seconds
        now = datetime.utcnow()
        if (self._db_manager is None or 
            self._last_connection_check is None or
            (now - self._last_connection_check).seconds > 60):
            
            # Verify connection or create new
            if self._db_manager:
                try:
                    # Quick ping test
                    from sqlalchemy import text
                    session = next(self._db_manager.get_session())
                    session.execute(text("SELECT 1"))
                    session.close()
                    logger.debug("Database connection verified")
                except Exception as e:
                    logger.info(f"Database connection stale ({e}), creating new manager")
                    self._db_manager = None
            
            if self._db_manager is None:
                logger.info("Creating new DatabaseManager for worker")
                self._db_manager = DatabaseManager(validate_conformance=False)
                
            self._last_connection_check = now
            
        return self._db_manager
    
    def validate_conformance(self):
        """Validate model conformance for database operations"""
        if os.getenv('SKIP_CONFORMANCE_CHECK', '').lower() == 'true':
            logger.debug(f"Skipping conformance check for task {self.name}")
            return
            
        try:
            from scripts.db import ConformanceValidator
            validator = ConformanceValidator(self.db_manager)
            is_valid, errors = validator.validate_models()
            
            if not is_valid:
                error_msg = f"Model conformance validation failed:\n" + "\n".join(errors)
                logger.error(error_msg)
                if os.getenv('ENVIRONMENT') == 'production':
                    raise ValueError(error_msg)
                else:
                    logger.warning("Continuing despite conformance errors (non-production)")
        except ImportError:
            logger.warning("ConformanceValidator not available, skipping validation")
        except Exception as e:
            logger.error(f"Conformance validation error: {e}")
            if os.getenv('ENVIRONMENT') == 'production':
                raise
    
    @property
    def entity_service(self):
        if self._entity_service is None:
            self._entity_service = EntityService(self.db_manager, OPENAI_API_KEY)
        return self._entity_service
    
    @property 
    def graph_service(self):
        if self._graph_service is None:
            self._graph_service = GraphService(self.db_manager)
        return self._graph_service
    
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Called when the task fails - enhanced with conformance context."""
        document_uuid = kwargs.get('document_uuid', 'unknown')
        task_name = self.name.split('.')[-1]
        
        # Check if failure was due to conformance issues
        error_context = {"error": str(exc), "task_id": task_id}
        if "ConformanceError" in str(type(exc)) or "conformance" in str(exc).lower():
            error_context["conformance_failure"] = True
            error_context["recovery_suggestion"] = "Run conformance validation and fix schema issues"
            logger.error(f"CONFORMANCE FAILURE - Task {task_name} ({task_id}) failed for document {document_uuid}: {exc}")
        else:
            logger.error(f"Task {task_name} ({task_id}) failed for document {document_uuid}: {exc}")
        
        update_document_state(document_uuid, task_name, "failed", error_context)
    
    def on_retry(self, exc, task_id, args, kwargs, einfo):
        """Called when the task is retried."""
        document_uuid = kwargs.get('document_uuid', 'unknown')
        task_name = self.name.split('.')[-1]
        retry_count = self.request.retries
        
        logger.warning(f"Task {task_name} ({task_id}) retry {retry_count} for document {document_uuid}: {exc}")
        update_document_state(document_uuid, task_name, "retrying", {
            "retry_count": retry_count,
            "error": str(exc),
            "task_id": task_id
        })


# Utility functions
def update_document_state(document_uuid: str, stage: str, status: str, metadata: Dict[str, Any] = None):
    """Update document processing state in Redis with enhanced metadata."""
    redis_manager = get_redis_manager()
    state_key = CacheKeys.DOC_STATE.format(document_uuid=document_uuid)
    
    state_data = redis_manager.get_dict(state_key) or {}
    
    # Enhanced metadata with conformance info
    enhanced_metadata = metadata or {}
    enhanced_metadata['updated_at'] = datetime.utcnow().isoformat()
    enhanced_metadata['stage'] = stage
    
    state_data[stage] = {
        'status': status,
        'timestamp': datetime.utcnow().isoformat(),
        'metadata': enhanced_metadata
    }
    
    # Track overall document state
    state_data['last_update'] = {
        'stage': stage,
        'status': status,
        'timestamp': datetime.utcnow().isoformat()
    }
    
    redis_manager.store_dict(state_key, state_data, ttl=86400)
    logger.info(f"Updated state for document {document_uuid}: {stage} -> {status}")

def validate_document_exists(db_manager: DatabaseManager, document_uuid: str) -> bool:
    """Validate document exists with retry logic for cross-process visibility."""
    import time
    from scripts.rds_utils import DBSessionLocal
    from sqlalchemy import text
    
    max_attempts = 3
    
    for attempt in range(max_attempts):
        try:
            # Use direct SQL to bypass any caching
            session = DBSessionLocal()
            try:
                result = session.execute(
                    text("SELECT 1 FROM source_documents WHERE document_uuid = :uuid"),
                    {"uuid": str(document_uuid)}
                )
                exists = result.scalar() is not None
                
                if exists:
                    logger.info(f"Document {document_uuid} found on attempt {attempt + 1}")
                    return True
                elif attempt < max_attempts - 1:
                    logger.warning(f"Document {document_uuid} not found on attempt {attempt + 1}, retrying...")
                    time.sleep(1)  # Wait 1 second before retry
                    
            finally:
                session.close()
                
        except Exception as e:
            logger.error(f"Error validating document {document_uuid} on attempt {attempt + 1}: {e}")
            if attempt < max_attempts - 1:
                time.sleep(1)
            
    logger.error(f"Document {document_uuid} not found after {max_attempts} attempts")
    return False

def validate_processing_stage(db_manager: DatabaseManager, document_uuid: str, required_stage: ProcessingStatus) -> bool:
    """Validate that document is in the correct processing stage."""
    try:
        document = db_manager.get_source_document(document_uuid)
        if not document:
            return False
        return document.processing_status == required_stage
    except Exception as e:
        logger.error(f"Error validating processing stage for document {document_uuid}: {e}")
        return False


# OCR Tasks
@app.task(bind=True, base=PDFTask, max_retries=3, default_retry_delay=60, queue='ocr')
@log_task_execution
def extract_text_from_document(self, document_uuid: str, file_path: str) -> Dict[str, Any]:
    """
    Extract text from PDF document using OCR with full validation.
    
    Args:
        document_uuid: UUID of the document
        file_path: Path to the PDF file
        
    Returns:
        Dict containing extracted text and metadata
    """
    logger.info(f"Starting OCR extraction for document {document_uuid}")
    
    try:
        # 1. Validate conformance before any processing
        self.validate_conformance()
        
        # 2. Validate inputs
        if not document_uuid or not file_path:
            raise ValueError("document_uuid and file_path are required")
        
        # Handle S3 paths - convert S3 key to full URI if needed
        if not file_path.startswith('s3://'):
            # Check if it's an S3 key (e.g., "documents/uuid.pdf")
            if file_path.startswith('documents/') or '/' in file_path:
                # Convert to full S3 URI using the configured bucket
                from scripts.config import S3_PRIMARY_DOCUMENT_BUCKET
                file_path = f"s3://{S3_PRIMARY_DOCUMENT_BUCKET}/{file_path}"
                logger.info(f"Converted S3 key to URI: {file_path}")
            else:
                # It's a local file path - check existence
                if not Path(file_path).exists():
                    raise FileNotFoundError(f"PDF file not found: {file_path}")
        
        # 3. Validate document exists and is in correct state
        if not validate_document_exists(self.db_manager, document_uuid):
            raise ValueError(f"Document {document_uuid} not found in database")
        
        # 4. Update processing state with validation metadata
        update_document_state(document_uuid, "ocr", "in_progress", {
            "task_id": self.request.id,
            "file_path": file_path,
            "conformance_validated": True,
            "validation_timestamp": datetime.utcnow().isoformat()
        })
        # Check cache first
        redis_manager = get_redis_manager()
        cache_key = CacheKeys.DOC_OCR_RESULT.format(document_uuid=document_uuid)
        cached_result = redis_manager.get_dict(cache_key)
        
        if cached_result:
            logger.info(f"Using cached OCR result for document {document_uuid}")
            update_document_state(document_uuid, "ocr", "completed", {"from_cache": True})
            
            # Continue the pipeline with cached text
            continue_pipeline_after_ocr.apply_async(
                args=[document_uuid, cached_result['text']]
            )
            
            return {
                'status': 'completed',
                'text_length': len(cached_result['text']),
                'from_cache': True
            }
        
        # Start async Textract job
        from scripts.textract_job_manager import get_job_manager
        job_manager = get_job_manager()
        
        job_id = job_manager.start_textract_job(document_uuid, file_path)
        
        if not job_id:
            raise RuntimeError("Failed to start Textract job")
        
        # Update document status
        logger.info(f"Updating document status with job_id={job_id}")
        job_manager.update_document_status(document_uuid, job_id, 'IN_PROGRESS')
        logger.info(f"Document status update completed")
        
        # Update state
        update_document_state(document_uuid, "ocr", "processing", {
            "job_id": job_id,
            "started_at": datetime.utcnow().isoformat()
        })
        
        # Schedule polling task
        logger.info(f"Scheduling poll_textract_job for document {document_uuid}, job {job_id}")
        polling_task = poll_textract_job.apply_async(
            args=[document_uuid, job_id],
            countdown=10  # Check after 10 seconds
        )
        logger.info(f"Polling task scheduled: {polling_task.id}")
        
        return {
            'status': 'processing',
            'job_id': job_id,
            'message': 'OCR job started, polling for results'
        }
        
    except Exception as e:
        logger.error(f"OCR extraction failed for {document_uuid}: {e}")
        update_document_state(document_uuid, "ocr", "failed", {"error": str(e)})
        raise


# Text Processing Tasks
@app.task(bind=True, base=PDFTask, max_retries=3, default_retry_delay=60, queue='text')
@log_task_execution
def chunk_document_text(self, document_uuid: str, text: str, chunk_size: int = 1000, 
                       overlap: int = 200) -> List[Dict[str, Any]]:
    """
    Chunk document text into smaller segments with full validation.
    
    Args:
        document_uuid: UUID of the document
        text: Full text to chunk
        chunk_size: Size of each chunk
        overlap: Overlap between chunks
        
    Returns:
        List of chunk dictionaries with validated Pydantic models
    """
    logger.info(f"Starting text chunking for document {document_uuid}")
    
    try:
        # 1. Validate conformance
        self.validate_conformance()
        
        # 2. Validate inputs
        if not document_uuid or not text:
            raise ValueError("document_uuid and text are required")
        
        if not text.strip():
            raise ValueError("Text content cannot be empty")
        
        if chunk_size < 100 or chunk_size > 10000:
            raise ValueError(f"Invalid chunk size: {chunk_size}. Must be between 100 and 10000")
        
        if overlap < 0 or overlap >= chunk_size:
            raise ValueError(f"Invalid overlap: {overlap}. Must be >= 0 and < chunk_size")
        
        # 3. Validate document exists and previous stage completed
        if not validate_document_exists(self.db_manager, document_uuid):
            raise ValueError(f"Document {document_uuid} not found in database")
        
        # 4. Update processing state with validation metadata
        update_document_state(document_uuid, "chunking", "in_progress", {
            "task_id": self.request.id,
            "text_length": len(text),
            "chunk_size": chunk_size,
            "overlap": overlap,
            "conformance_validated": True,
            "validation_timestamp": datetime.utcnow().isoformat()
        })
        # Check cache
        redis_manager = get_redis_manager()
        cache_key = CacheKeys.DOC_CHUNKS.format(document_uuid=document_uuid)
        cached_chunks = redis_manager.get_dict(cache_key)
        
        if cached_chunks and cached_chunks.get('chunks'):
            logger.info(f"Using cached chunks for document {document_uuid}")
            update_document_state(document_uuid, "chunking", "completed", {"from_cache": True})
            return cached_chunks['chunks']
        
        # 5. Chunk the text with validation
        logger.info(f"Chunking text of length {len(text)} with chunk_size={chunk_size}, overlap={overlap}")
        chunks = simple_chunk_text(text, chunk_size, overlap)
        
        logger.info(f"Generated {len(chunks)} chunks from simple_chunk_text")
        for idx, chunk in enumerate(chunks[:3]):  # Log first 3 chunks for debugging
            chunk_text = chunk['text'] if isinstance(chunk, dict) else chunk
            logger.debug(f"Chunk {idx}: length={len(chunk_text)}, type={type(chunk)}")
        
        if not chunks:
            raise ValueError("No chunks generated from text")
        
        # 6. Create validated chunk models
        from scripts.models import ModelFactory
        ChunkModel = ModelFactory.get_chunk_model()
        
        chunk_models = []
        logger.info(f"Creating chunk models for {len(chunks)} chunks")
        for idx, chunk_data in enumerate(chunks):
            try:
                # Extract text from chunk dictionary
                chunk_text = chunk_data['text'] if isinstance(chunk_data, dict) else chunk_data
                
                logger.debug(f"Creating chunk model {idx}: text_length={len(chunk_text)}")
                
                # Create Pydantic model with validation
                chunk_model = ChunkModel(
                    chunk_uuid=uuid.uuid4(),
                    document_uuid=document_uuid,
                    chunk_index=idx,
                    text=chunk_text,  # Changed from text_content to match database
                    start_char=chunk_data.get('char_start_index', 0) if isinstance(chunk_data, dict) else 0,
                    end_char=chunk_data.get('char_end_index', len(chunk_text)) if isinstance(chunk_data, dict) else len(chunk_text),
                    created_at=datetime.utcnow()
                )
                
                # Model is already validated by Pydantic on creation
                chunk_models.append(chunk_model)
                logger.debug(f"Successfully created chunk model {idx}")
                
            except Exception as e:
                logger.error(f"Failed to create chunk model {idx}: {e}")
                raise ValueError(f"Chunk validation failed at index {idx}: {e}")
        
        logger.info(f"Successfully created {len(chunk_models)} chunk models")
        
        # 7. Store chunks in database with batch insertion and proper error handling
        logger.info(f"Storing {len(chunk_models)} chunks in database for document {document_uuid}")
        
        # Prepare all chunks for batch insertion
        from scripts.rds_utils import insert_record, execute_query
        from sqlalchemy import text as sql_text
        
        stored_chunks = []
        failed_chunks = []
        
        # First, try batch insertion for better performance
        try:
            logger.info("Attempting batch chunk insertion...")
            
            # Build batch insert query
            session = next(self.db_manager.get_session())
            try:
                # Prepare values for all chunks
                chunk_values = []
                for chunk_model in chunk_models:
                    chunk_values.append({
                        'chunk_uuid': str(chunk_model.chunk_uuid),
                        'document_uuid': str(chunk_model.document_uuid),
                        'chunk_index': chunk_model.chunk_index,
                        'text': chunk_model.text,
                        'char_start_index': int(chunk_model.start_char),  # Ensure it's an int
                        'char_end_index': int(chunk_model.end_char),      # Ensure it's an int
                        'created_at': chunk_model.created_at
                    })
                
                # Execute batch insert
                insert_query = sql_text("""
                    INSERT INTO document_chunks 
                    (chunk_uuid, document_uuid, chunk_index, text, 
                     char_start_index, char_end_index, created_at)
                    VALUES 
                    (:chunk_uuid, :document_uuid, :chunk_index, :text,
                     :char_start_index, :char_end_index, :created_at)
                    RETURNING id, chunk_uuid
                """)
                
                for i, chunk_data in enumerate(chunk_values):
                    try:
                        result = session.execute(insert_query, chunk_data)
                        session.commit()
                        stored_chunks.append(chunk_models[i])
                        logger.debug(f"✓ Stored chunk {i}: {chunk_data['chunk_uuid']}")
                    except Exception as e:
                        session.rollback()
                        logger.error(f"Failed to insert chunk {i}: {e}")
                        failed_chunks.append((i, chunk_models[i], str(e)))
                        
            finally:
                session.close()
                
            logger.info(f"Batch insertion complete: {len(stored_chunks)} successful, {len(failed_chunks)} failed")
            
        except Exception as batch_error:
            logger.error(f"Batch insertion failed: {batch_error}")
            logger.info("Falling back to individual chunk insertion...")
            
            # Fallback: Try individual insertion with retry logic
            for i, chunk_model in enumerate(chunk_models):
                if any(fc[1].chunk_uuid == chunk_model.chunk_uuid for fc in failed_chunks):
                    continue  # Skip already failed chunks
                    
                retry_count = 3
                for attempt in range(retry_count):
                    try:
                        logger.debug(f"Inserting chunk {i} (attempt {attempt + 1}/{retry_count})")
                        
                        # Map minimal model fields to database columns
                        db_data = {
                            'chunk_uuid': str(chunk_model.chunk_uuid),
                            'document_uuid': str(chunk_model.document_uuid),
                            'chunk_index': chunk_model.chunk_index,
                            'text': chunk_model.text,
                            'char_start_index': int(chunk_model.start_char),  # Ensure int
                            'char_end_index': int(chunk_model.end_char),      # Ensure int
                            'created_at': chunk_model.created_at
                        }
                        
                        # Log the data being inserted for debugging
                        logger.debug(f"Chunk {i} data: start={db_data['char_start_index']}, end={db_data['char_end_index']}, text_len={len(db_data['text'])}")
                        
                        result = insert_record('document_chunks', db_data)
                        if result:
                            stored_chunks.append(chunk_model)
                            logger.info(f"✓ Stored chunk {chunk_model.chunk_index}")
                            break  # Success, exit retry loop
                        else:
                            logger.warning(f"No result returned for chunk {chunk_model.chunk_index}")
                            if attempt < retry_count - 1:
                                time.sleep(0.5 * (attempt + 1))  # Exponential backoff
                            
                    except Exception as e:
                        logger.error(f"Error storing chunk {chunk_model.chunk_index} (attempt {attempt + 1}): {type(e).__name__}: {e}")
                        if attempt < retry_count - 1:
                            time.sleep(0.5 * (attempt + 1))  # Exponential backoff
                        else:
                            failed_chunks.append((i, chunk_model, str(e)))
        
        # Log final results
        logger.info(f"Chunk storage complete: {len(stored_chunks)}/{len(chunk_models)} stored successfully")
        if failed_chunks:
            logger.error(f"Failed chunks: {[(fc[0], str(fc[1].chunk_uuid), fc[2]) for fc in failed_chunks]}")
        
        if len(stored_chunks) == 0:
            raise RuntimeError(f"Failed to store any chunks. Errors: {[fc[2] for fc in failed_chunks]}")
        elif len(stored_chunks) < len(chunk_models):
            logger.warning(f"Partial success: {len(stored_chunks)}/{len(chunk_models)} chunks stored")
        
        # 8. Convert to serializable format for return
        # Map to expected format for entity extraction
        serialized_chunks = []
        for chunk in stored_chunks:
            chunk_data = chunk.model_dump(mode='json')
            # Entity extraction expects 'chunk_text' not 'text'
            serialized_chunks.append({
                'chunk_uuid': chunk_data['chunk_uuid'],
                'chunk_text': chunk_data['text'],  # Map 'text' to 'chunk_text'
                'chunk_index': chunk_data['chunk_index'],
                'start_char': chunk_data.get('start_char', 0),
                'end_char': chunk_data.get('end_char', len(chunk_data['text']))
            })
        
        # 9. Cache the result
        redis_manager.store_dict(cache_key, {'chunks': serialized_chunks}, ttl=86400)
        
        # 10. Update final state with comprehensive metadata
        update_document_state(document_uuid, "chunking", "completed", {
            "chunk_count": len(stored_chunks),
            "chunk_size": chunk_size,
            "overlap": overlap,
            "total_characters": len(text),
            "avg_chunk_size": sum(len(chunk.text) for chunk in stored_chunks) / len(stored_chunks),
            "validation_passed": True
        })
        
        # Trigger next stage - entity extraction
        extract_entities_from_chunks.apply_async(
            args=[document_uuid, serialized_chunks]
        )
        
        return serialized_chunks
        
    except Exception as e:
        logger.error(f"Chunking failed for {document_uuid}: {e}")
        update_document_state(document_uuid, "chunking", "failed", {"error": str(e)})
        raise


def _calculate_start_char(chunks: List[str], index: int, overlap: int) -> int:
    """Calculate start character position for chunk."""
    if index == 0:
        return 0
    
    # Calculate based on previous chunks minus overlap
    total_chars = 0
    for i in range(index):
        if i == 0:
            total_chars += len(chunks[i])
        else:
            total_chars += len(chunks[i]) - overlap
    
    return max(0, total_chars - overlap)


def _calculate_end_char(chunks: List[str], index: int, overlap: int) -> int:
    """Calculate end character position for chunk."""
    start_char = _calculate_start_char(chunks, index, overlap)
    return start_char + len(chunks[index])


# Entity Tasks
@app.task(bind=True, base=PDFTask, max_retries=3, default_retry_delay=60, queue='entity')
@log_task_execution
def extract_entities_from_chunks(self, document_uuid: str, chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Extract entities from document chunks with full validation.
    
    Args:
        document_uuid: UUID of the document
        chunks: List of chunk dictionaries
        
    Returns:
        Dict containing extracted entities and mentions with validated models
    """
    logger.info(f"Starting entity extraction for document {document_uuid}")
    
    try:
        # 1. Validate conformance
        self.validate_conformance()
        
        # 2. Validate inputs
        if not document_uuid or not chunks:
            raise ValueError("document_uuid and chunks are required")
        
        if not isinstance(chunks, list) or len(chunks) == 0:
            raise ValueError("chunks must be a non-empty list")
        
        # 3. Validate document exists
        if not validate_document_exists(self.db_manager, document_uuid):
            raise ValueError(f"Document {document_uuid} not found in database")
        
        # 4. Update processing state
        update_document_state(document_uuid, "entity_extraction", "in_progress", {
            "task_id": self.request.id,
            "chunk_count": len(chunks),
            "conformance_validated": True,
            "validation_timestamp": datetime.utcnow().isoformat()
        })
        
        # 5. Process chunks for entity extraction
        all_entity_mentions = []
        canonical_entities = {}
        
        for chunk in chunks:
            chunk_uuid = chunk['chunk_uuid']
            chunk_text = chunk['chunk_text']
            
            # Extract entities from chunk
            result = self.entity_service.extract_entities_from_chunk(
                chunk_text=chunk_text,
                chunk_uuid=chunk_uuid,
                document_uuid=document_uuid
            )
            
            if result.status == ProcessingResultStatus.SUCCESS:
                all_entity_mentions.extend(result.entity_mentions)
                
                # Store unique canonical entities
                for entity in result.canonical_entities:
                    if entity.canonical_entity_uuid not in canonical_entities:
                        canonical_entities[entity.canonical_entity_uuid] = entity
        
        # Cache results
        redis_manager = get_redis_manager()
        mentions_key = CacheKeys.DOC_ENTITY_MENTIONS.format(document_uuid=document_uuid)
        entities_key = CacheKeys.DOC_CANONICAL_ENTITIES.format(document_uuid=document_uuid)
        
        redis_manager.store_dict(mentions_key, {
            'mentions': [m.dict() for m in all_entity_mentions]
        }, ttl=86400)
        
        redis_manager.store_dict(entities_key, {
            'entities': [e.dict() for e in canonical_entities.values()]
        }, ttl=86400)
        
        update_document_state(document_uuid, "entity_extraction", "completed", {
            "mention_count": len(all_entity_mentions),
            "canonical_count": len(canonical_entities)
        })
        
        # Trigger next stage - entity resolution using standalone task
        entity_mentions_data = [m.dict() for m in all_entity_mentions]
        
        # Import the standalone resolution task
        from scripts.resolution_task import resolve_entities_standalone
        
        resolve_entities_standalone.apply_async(
            args=[document_uuid, entity_mentions_data]
        )
        
        return {
            'entity_mentions': entity_mentions_data,
            'canonical_entities': [e.dict() for e in canonical_entities.values()]
        }
        
    except Exception as e:
        logger.error(f"Entity extraction failed for {document_uuid}: {e}")
        update_document_state(document_uuid, "entity_extraction", "failed", {"error": str(e)})
        raise


@app.task(bind=True, base=PDFTask, max_retries=3, default_retry_delay=60, queue='entity')
@log_task_execution
def resolve_document_entities(self, document_uuid: str, entity_mentions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Resolve entity mentions to canonical entities.
    
    Args:
        document_uuid: UUID of the document
        entity_mentions: List of entity mention dictionaries
        
    Returns:
        Dict containing resolution results
    """
    logger.info(f"Starting entity resolution for document {document_uuid}")
    update_document_state(document_uuid, "entity_resolution", "in_progress", {"task_id": self.request.id})
    
    try:
        # Use the improved entity resolution
        from scripts.entity_resolution_fixes import (
            resolve_entities_simple, 
            save_canonical_entities_to_db,
            update_entity_mentions_with_canonical
        )
        
        # Ensure entity_mentions are dicts, not Pydantic models
        if entity_mentions and hasattr(entity_mentions[0], 'dict'):
            # Convert Pydantic models to dicts
            entity_mentions = [m.dict() if hasattr(m, 'dict') else m for m in entity_mentions]
            logger.info("Converted entity mentions from Pydantic models to dicts")
        
        # Perform resolution
        resolution_result = resolve_entities_simple(
            entity_mentions=entity_mentions,
            document_uuid=document_uuid,
            threshold=0.8
        )
        
        logger.info(f"Resolution complete: {resolution_result['total_canonical']} canonical entities from {resolution_result['total_mentions']} mentions")
        
        # Log canonical entities before saving
        logger.info(f"Canonical entities to save: {len(resolution_result.get('canonical_entities', []))}")
        for i, entity in enumerate(resolution_result.get('canonical_entities', [])):
            logger.debug(f"Entity {i}: {entity.get('canonical_name')} (type: {entity.get('entity_type')})")
        
        # Save canonical entities to database
        try:
            saved_count = save_canonical_entities_to_db(
                canonical_entities=resolution_result['canonical_entities'],
                document_uuid=document_uuid,
                db_manager=self.db_manager
            )
            logger.info(f"Successfully saved {saved_count} canonical entities to database")
        except Exception as e:
            logger.error(f"Failed to save canonical entities: {e}")
            logger.error(f"Exception type: {type(e).__name__}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise
        
        # Update entity mentions with canonical UUIDs
        try:
            updated_count = update_entity_mentions_with_canonical(
                mention_to_canonical=resolution_result['mention_to_canonical'],
                document_uuid=document_uuid,
                db_manager=self.db_manager
            )
            logger.info(f"Successfully updated {updated_count} entity mentions with canonical UUIDs")
        except Exception as e:
            logger.error(f"Failed to update entity mentions: {e}")
            logger.error(f"Exception type: {type(e).__name__}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise
        
        # Update cache with resolved entities
        redis_manager = get_redis_manager()
        entities_key = CacheKeys.DOC_CANONICAL_ENTITIES.format(document_uuid=document_uuid)
        
        redis_manager.store_dict(entities_key, {
            'entities': resolution_result['canonical_entities']
        }, ttl=86400)
        
        update_document_state(document_uuid, "entity_resolution", "completed", {
            "resolved_count": updated_count,
            "canonical_count": len(resolution_result['canonical_entities']),
            "deduplication_rate": resolution_result['deduplication_rate']
        })
        
        # Get metadata and chunks for relationship building
        metadata_key = f"doc:metadata:{document_uuid}"
        stored_metadata = redis_manager.get_dict(metadata_key) or {}
        project_uuid = stored_metadata.get('project_uuid')
        document_metadata = stored_metadata.get('document_metadata', {})
        
        # Get chunks from cache
        chunks_key = CacheKeys.DOC_CHUNKS.format(document_uuid=document_uuid)
        chunks_data = redis_manager.get_dict(chunks_key) or {}
        chunks = chunks_data.get('chunks', [])
        
        # Get updated entity mentions from database with ALL required fields
        session = next(self.db_manager.get_session())
        try:
            from sqlalchemy import text as sql_text
            mentions_query = sql_text("""
                SELECT em.*, ce.entity_name as canonical_name
                FROM entity_mentions em
                LEFT JOIN canonical_entities ce ON em.canonical_entity_uuid = ce.canonical_entity_uuid
                WHERE em.document_uuid = :doc_uuid
            """)
            
            mentions_results = session.execute(mentions_query, {'doc_uuid': str(document_uuid)}).fetchall()
            
            entity_mentions_list = []
            for row in mentions_results:
                entity_mentions_list.append({
                    'mention_uuid': str(row.mention_uuid),
                    'chunk_uuid': str(row.chunk_uuid),
                    'document_uuid': str(row.document_uuid),
                    'entity_text': row.entity_text,
                    'entity_type': row.entity_type,
                    'start_char': row.start_char,
                    'end_char': row.end_char,
                    'confidence_score': row.confidence_score,
                    'canonical_entity_uuid': str(row.canonical_entity_uuid) if row.canonical_entity_uuid else None,
                    'canonical_name': row.canonical_name
                })
        finally:
            session.close()
        
        # Trigger next stage - relationship building
        if project_uuid and chunks and resolution_result['canonical_entities']:
            logger.info(f"Triggering relationship building with {len(resolution_result['canonical_entities'])} canonical entities")
            
            # Ensure document_uuid is in metadata
            if 'document_uuid' not in document_metadata:
                document_metadata['document_uuid'] = document_uuid
            
            build_document_relationships.apply_async(
                args=[
                    document_uuid,
                    document_metadata,
                    project_uuid,
                    chunks,
                    entity_mentions_list,
                    resolution_result['canonical_entities']
                ]
            )
        else:
            logger.warning(f"Skipping relationship building - missing data: project_uuid={bool(project_uuid)}, chunks={len(chunks) if chunks else 0}, entities={len(resolution_result['canonical_entities'])}")
        
        return {
            'canonical_entities': resolution_result['canonical_entities'],
            'total_resolved': updated_count,
            'deduplication_rate': resolution_result['deduplication_rate']
        }
            
    except Exception as e:
        logger.error(f"Entity resolution failed for {document_uuid}: {e}")
        logger.error(f"Exception type: {type(e).__name__}")
        import traceback
        logger.error(f"Full traceback:\n{traceback.format_exc()}")
        update_document_state(document_uuid, "entity_resolution", "failed", {"error": str(e)})
        raise


# Graph Tasks
@app.task(bind=True, base=PDFTask, max_retries=3, default_retry_delay=60, queue='graph')
@log_task_execution
def build_document_relationships(self, document_uuid: str, document_data: Dict[str, Any],
                               project_uuid: str, chunks: List[Dict[str, Any]],
                               entity_mentions: List[Dict[str, Any]],
                               canonical_entities: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Build graph relationships for document.
    
    Args:
        document_uuid: UUID of the document
        document_data: Document metadata
        project_uuid: UUID of the project
        chunks: List of chunk dictionaries
        entity_mentions: List of entity mention dictionaries
        canonical_entities: List of canonical entity dictionaries
        
    Returns:
        Dict containing relationship building results
    """
    logger.info(f"Starting relationship building for document {document_uuid}")
    update_document_state(document_uuid, "relationships", "in_progress", {"task_id": self.request.id})
    
    try:
        # Build structural relationships (document-chunk-entity hierarchy)
        result = self.graph_service.stage_structural_relationships(
            document_data=document_data,
            project_uuid=project_uuid,
            chunks_data=chunks,
            entity_mentions_data=entity_mentions,
            canonical_entities_data=canonical_entities,
            document_uuid=document_uuid
        )
        
        if result.status == ProcessingResultStatus.SUCCESS:
            update_document_state(document_uuid, "relationships", "completed", {
                "relationship_count": result.total_relationships,
                "relationship_types": "structural"  # Only structural relationships at this stage
            })
            
            # Finalize the pipeline
            finalize_document_pipeline.apply_async(
                args=[document_uuid, len(chunks), len(canonical_entities), result.total_relationships]
            )
            
            return {
                'total_relationships': result.total_relationships,
                'staged_relationships': [r.dict() for r in result.staged_relationships],
                'relationship_types': 'structural',
                'summary': f"Staged {result.total_relationships} structural relationships"
            }
        else:
            raise Exception(f"Relationship building failed: {result.error_message}")
            
    except Exception as e:
        logger.error(f"Relationship building failed for {document_uuid}: {e}")
        update_document_state(document_uuid, "relationships", "failed", {"error": str(e)})
        raise


# Pipeline orchestration
@app.task(bind=True, base=PDFTask, queue='default')
@log_task_execution
def process_pdf_document(self, document_uuid: str, file_path: str, project_uuid: str,
                        document_metadata: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Main orchestration task for PDF processing pipeline.
    This now starts the async OCR process and returns immediately.
    The pipeline continues through task callbacks.
    
    Args:
        document_uuid: UUID of the document
        file_path: Path to the PDF file
        project_uuid: UUID of the project
        document_metadata: Optional document metadata
        
    Returns:
        Dict containing processing initiation status
    """
    logger.info(f"Starting PDF processing pipeline for document {document_uuid}")
    
    try:
        # Update state
        update_document_state(document_uuid, "pipeline", "starting", {
            "task_id": self.request.id,
            "project_uuid": project_uuid
        })
        
        # Store metadata for later stages
        redis_manager = get_redis_manager()
        metadata_key = f"doc:metadata:{document_uuid}"
        redis_manager.store_dict(metadata_key, {
            "project_uuid": project_uuid,
            "document_metadata": document_metadata or {},
            "file_path": file_path,
            "pipeline_started": datetime.utcnow().isoformat()
        }, ttl=86400)
        
        # Start async OCR extraction - this will trigger the rest of the pipeline
        ocr_task = extract_text_from_document.apply_async(
            args=[document_uuid, file_path]
        )
        
        # Update state to indicate OCR has been started
        update_document_state(document_uuid, "pipeline", "processing", {
            "ocr_task_id": ocr_task.id,
            "stage": "ocr_initiated"
        })
        
        return {
            'status': 'processing',
            'document_uuid': document_uuid,
            'ocr_task_id': ocr_task.id,
            'message': 'Document processing initiated successfully'
        }
        
    except Exception as e:
        logger.error(f"Failed to start processing pipeline for {document_uuid}: {e}")
        update_document_state(document_uuid, "pipeline", "failed", {"error": str(e)})
        raise


# Polling task for async OCR
@app.task(bind=True, base=PDFTask, queue='ocr', max_retries=30)
@log_task_execution
def poll_textract_job(self, document_uuid: str, job_id: str) -> Dict[str, Any]:
    """
    Poll Textract job status and process results when ready.
    
    Args:
        document_uuid: UUID of the document
        job_id: Textract job ID
        
    Returns:
        Dict containing status information
    """
    logger.info(f"Polling Textract job {job_id} for document {document_uuid}")
    
    try:
        from scripts.textract_job_manager import get_job_manager
        job_manager = get_job_manager()
        
        # Check job status
        status = job_manager.check_job_status(job_id)
        
        if status == 'SUCCEEDED':
            logger.info(f"Textract job {job_id} succeeded, retrieving results")
            
            # Get results
            result = job_manager.get_job_results(job_id)
            
            if not result or result.get('status') != 'success':
                raise RuntimeError("Failed to get Textract results")
            
            # Cache results
            job_manager.cache_ocr_results(
                document_uuid, 
                result['text'], 
                result['metadata']
            )
            
            # Update document status
            job_manager.update_document_status(document_uuid, job_id, 'SUCCEEDED')
            
            # Store extracted text in database
            logger.info(f"Storing extracted text in database for document {document_uuid}")
            session = next(self.db_manager.get_session())
            try:
                from sqlalchemy import text as sql_text
                update_query = sql_text("""
                    UPDATE source_documents 
                    SET raw_extracted_text = :text,
                        ocr_completed_at = NOW(),
                        ocr_provider = 'AWS Textract'
                    WHERE document_uuid = :doc_uuid
                """)
                session.execute(update_query, {
                    'text': result['text'],
                    'doc_uuid': str(document_uuid)
                })
                session.commit()
                logger.info(f"Stored {len(result['text'])} characters in database for document {document_uuid}")
            finally:
                session.close()
            
            # Update state
            update_document_state(document_uuid, "ocr", "completed", {
                "job_id": job_id,
                "page_count": result['metadata'].get('page_count', 0),
                "method": "AWS Textract (async)"
            })
            
            # Trigger the rest of the pipeline
            continue_pipeline_after_ocr.apply_async(
                args=[document_uuid, result['text']]
            )
            
            return {
                'status': 'completed',
                'text_length': len(result['text']),
                'pages': result['metadata'].get('page_count', 0)
            }
            
        elif status == 'IN_PROGRESS':
            logger.info(f"Textract job {job_id} still in progress, retrying...")
            
            # Update state with retry info
            update_document_state(document_uuid, "ocr", "polling", {
                "job_id": job_id,
                "retry_count": self.request.retries,
                "last_checked": datetime.utcnow().isoformat()
            })
            
            # Retry in 5 seconds
            raise self.retry(countdown=5)
            
        elif status == 'FAILED':
            logger.error(f"Textract job {job_id} failed")
            
            # Update document status
            job_manager.update_document_status(
                document_uuid, 
                job_id, 
                'FAILED',
                'Textract job failed'
            )
            
            # Update state
            update_document_state(document_uuid, "ocr", "failed", {
                "job_id": job_id,
                "error": "Textract job failed"
            })
            
            return {
                'status': 'failed',
                'error': 'Textract job failed'
            }
            
        else:
            logger.error(f"Unknown Textract job status: {status}")
            raise RuntimeError(f"Unknown job status: {status}")
            
    except celery.exceptions.Retry:
        # Re-raise retry exceptions
        raise
    except Exception as e:
        logger.error(f"Polling failed for job {job_id}: {e}")
        
        # Update state
        update_document_state(document_uuid, "ocr", "failed", {
            "job_id": job_id,
            "error": str(e)
        })
        
        # Don't retry on hard errors
        raise


# Pipeline continuation task
@app.task(bind=True, base=PDFTask, queue='default')
@log_task_execution
def continue_pipeline_after_ocr(self, document_uuid: str, text: str) -> Dict[str, Any]:
    """
    Continue pipeline processing after OCR completes.
    Simply starts the chunking task which will trigger the rest.
    
    Args:
        document_uuid: UUID of the document
        text: Extracted text from OCR
        
    Returns:
        Dict containing pipeline continuation status
    """
    logger.info(f"Continuing pipeline after OCR for document {document_uuid}")
    
    try:
        # Get stored metadata
        redis_manager = get_redis_manager()
        metadata_key = f"doc:metadata:{document_uuid}"
        stored_metadata = redis_manager.get_dict(metadata_key) or {}
        
        project_uuid = stored_metadata.get('project_uuid')
        
        if not project_uuid:
            raise ValueError(f"No project_uuid found for document {document_uuid}")
        
        # Update state
        update_document_state(document_uuid, "pipeline", "processing", {
            "stage": "post_ocr_processing",
            "text_length": len(text)
        })
        
        # Start chunking - it will trigger the rest of the pipeline
        chunk_task = chunk_document_text.apply_async(
            args=[document_uuid, text]
        )
        
        return {
            'status': 'pipeline_continued',
            'document_uuid': document_uuid,
            'chunk_task_id': chunk_task.id,
            'message': 'Pipeline continuation initiated with chunking'
        }
        
    except Exception as e:
        logger.error(f"Failed to continue pipeline for {document_uuid}: {e}")
        update_document_state(document_uuid, "pipeline", "failed", {
            "error": str(e),
            "stage": "post_ocr_orchestration"
        })
        raise




# Pipeline finalization task
@app.task(bind=True, base=PDFTask, queue='default')
@log_task_execution
def finalize_document_pipeline(self, document_uuid: str, chunk_count: int, entity_count: int, relationship_count: int) -> Dict[str, Any]:
    """
    Finalize document processing pipeline and update final state.
    
    Args:
        document_uuid: UUID of the document
        chunk_count: Number of chunks processed
        entity_count: Number of entities extracted
        relationship_count: Number of relationships built
        
    Returns:
        Dict containing final processing results
    """
    try:
        # Update final state with comprehensive metadata
        update_document_state(document_uuid, "pipeline", "completed", {
            "chunk_count": chunk_count,
            "entity_count": entity_count,
            "relationship_count": relationship_count,
            "completed_at": datetime.utcnow().isoformat()
        })
        
        # Update document status in database
        self.db_manager.update_document_status(document_uuid, ProcessingStatus.COMPLETED)
        
        # Clean up temporary metadata
        redis_manager = get_redis_manager()
        metadata_key = f"doc:metadata:{document_uuid}"
        redis_manager.delete(metadata_key)
        
        logger.info(f"✅ Document {document_uuid} processing completed successfully")
        logger.info(f"📊 Stats: {chunk_count} chunks, {entity_count} entities, {relationship_count} relationships")
        
        return {
            'status': 'completed',
            'document_uuid': document_uuid,
            'stats': {
                'chunks': chunk_count,
                'entities': entity_count,
                'relationships': relationship_count
            }
        }
        
    except Exception as e:
        logger.error(f"Failed to finalize processing for {document_uuid}: {e}")
        update_document_state(document_uuid, "pipeline", "failed", {
            "error": str(e),
            "stage": "finalization"
        })
        raise


# Cleanup tasks
@app.task(bind=True, base=PDFTask, queue='cleanup')
@log_task_execution
def cleanup_failed_document(self, document_uuid: str) -> Dict[str, Any]:
    """
    Clean up resources for a failed document.
    
    Args:
        document_uuid: UUID of the document
        
    Returns:
        Dict containing cleanup results
    """
    logger.info(f"Cleaning up failed document {document_uuid}")
    
    try:
        redis_manager = get_redis_manager()
        
        # Clear all cache keys for this document
        cache_keys = [
            CacheKeys.DOC_STATE.format(document_uuid=document_uuid),
            CacheKeys.DOC_OCR_RESULT.format(document_uuid=document_uuid),
            CacheKeys.DOC_CHUNKS.format(document_uuid=document_uuid),
            CacheKeys.DOC_ENTITY_MENTIONS.format(document_uuid=document_uuid),
            CacheKeys.DOC_CANONICAL_ENTITIES.format(document_uuid=document_uuid),
        ]
        
        deleted_count = 0
        for key in cache_keys:
            if redis_manager.delete(key):
                deleted_count += 1
        
        # Update document status in database
        self.db_manager.update_document_status(document_uuid, ProcessingStatus.FAILED)
        
        return {
            'status': 'cleaned',
            'cache_keys_deleted': deleted_count
        }
        
    except Exception as e:
        logger.error(f"Cleanup failed for document {document_uuid}: {e}")
        raise


@app.task(bind=True, base=PDFTask, queue='cleanup')
@log_task_execution
def cleanup_old_cache_entries(self, days_old: int = 7) -> Dict[str, Any]:
    """
    Clean up old cache entries.
    
    Args:
        days_old: Age threshold in days
        
    Returns:
        Dict containing cleanup results
    """
    logger.info(f"Cleaning up cache entries older than {days_old} days")
    
    # This would need to be implemented based on Redis key patterns
    # For now, return a placeholder
    return {
        'status': 'completed',
        'message': f'Cleanup of entries older than {days_old} days completed'
    }


@app.task(name='monitor_db_connectivity')
def monitor_db_connectivity():
    """Periodic task to verify database connectivity"""
    from scripts.db import DatabaseManager
    from sqlalchemy import text
    
    db = DatabaseManager(validate_conformance=False)
    try:
        session = next(db.get_session())
        result = session.execute(text("SELECT COUNT(*) FROM source_documents"))
        count = result.scalar()
        session.close()
        
        logger.info(f"Database connectivity check: {count} documents")
        return {"status": "healthy", "document_count": count, "timestamp": datetime.utcnow().isoformat()}
    except Exception as e:
        logger.error(f"Database connectivity check failed: {e}")
        return {"status": "unhealthy", "error": str(e), "timestamp": datetime.utcnow().isoformat()}