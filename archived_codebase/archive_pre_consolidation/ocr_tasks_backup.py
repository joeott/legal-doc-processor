"""
OCR Tasks for Celery-based Document Processing Pipeline
"""
from celery import Task
from scripts.celery_app import app
from scripts.ocr_extraction import (
    extract_text_from_pdf_textract,
    extract_text_from_docx_s3_aware,
    extract_text_from_txt, extract_text_from_eml,
    transcribe_audio_whisper, transcribe_audio_openai_whisper,
    detect_file_category  # Add for file type detection
)
from scripts.supabase_utils import SupabaseManager
from scripts.redis_utils import get_redis_manager
from scripts.cache_keys import CacheKeys
from scripts.config import USE_OPENAI_FOR_AUDIO_TRANSCRIPTION
from scripts.celery_tasks.task_utils import update_document_state, check_stage_completed

# Import Pydantic models
from scripts.core.task_models import (
    OCRTaskPayload, OCRTaskResult, 
    ImageProcessingTaskPayload, ImageProcessingTaskResult,
    AudioProcessingTaskPayload, AudioProcessingTaskResult
)
from scripts.core.processing_models import (
    OCRResultModel, OCRPageResult,
    ImageProcessingResultModel, ImageAnalysisResult,
    AudioTranscriptionResultModel, TranscriptionSegment,
    ProcessingResultStatus
)
from scripts.core.cache_models import CachedOCRResultModel

import logging
import json
import uuid
import os
from datetime import datetime
from typing import Optional, Dict, Any, Union, Tuple
from pydantic import ValidationError
from pathlib import Path

logger = logging.getLogger(__name__)


def resolve_file_path(file_path: str) -> Tuple[bool, Optional[str]]:
    """
    Resolve file path, trying various strategies.
    
    Args:
        file_path: The file path to resolve (can be relative or absolute)
        
    Returns:
        Tuple of (success, resolved_path)
    """
    # If it's already an S3 or HTTP URL, return as-is
    if file_path.startswith(('s3://', 'http://', 'https://', 'supabase://')):
        return True, file_path
    
    # Try as absolute path first
    if os.path.isabs(file_path) and os.path.exists(file_path):
        logger.info(f"File found at absolute path: {file_path}")
        return True, file_path
    
    # Get project root (scripts directory's parent)
    scripts_dir = Path(__file__).parent.parent  # scripts/celery_tasks -> scripts
    project_root = scripts_dir.parent  # scripts -> project root
    
    # Try relative to project root
    full_path = project_root / file_path
    if full_path.exists():
        resolved = str(full_path)
        logger.info(f"File found relative to project root: {resolved}")
        return True, resolved
    
    # Try relative to current working directory
    cwd_path = Path.cwd() / file_path
    if cwd_path.exists():
        resolved = str(cwd_path)
        logger.info(f"File found relative to CWD: {resolved}")
        return True, resolved
    
    # Try with common base paths
    for base in ['/app', os.path.expanduser('~')]:
        test_path = Path(base) / file_path
        if test_path.exists():
            resolved = str(test_path)
            logger.info(f"File found at {resolved}")
            return True, resolved
    
    # Log all attempted paths for debugging
    logger.error(f"File not found: {file_path}")
    logger.error(f"Attempted paths:")
    logger.error(f"  - As absolute: {file_path}")
    logger.error(f"  - Project root: {full_path}")
    logger.error(f"  - CWD: {cwd_path}")
    logger.error(f"  - Working directory: {os.getcwd()}")
    logger.error(f"  - Project root: {project_root}")
    
    return False, None


class OCRTask(Task):
    """Base class for OCR tasks with database connection management"""
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
        update_document_state(document_uuid, "ocr", "failed", {"error": str(exc), "task_id": task_id})
    
    def on_retry(self, exc, task_id, args, kwargs, einfo):
        """Called when the task is retried."""
        document_uuid = kwargs.get('document_uuid', 'unknown')
        logger.warning(f"Task {task_id} retrying for document {document_uuid}: {exc}")
        update_document_state(document_uuid, "ocr", "retrying", {"attempt": self.request.retries + 1})


def _get_project_context(db_manager, project_sql_id: int) -> Optional[str]:
    """Get project context for better image analysis."""
    try:
        project_result = db_manager.client.table('projects').select(
            'name', 'description'
        ).eq('id', project_sql_id).execute()
        
        if project_result.data:
            project = project_result.data[0]
            context = f"Legal case: {project.get('name', 'Unknown')}"
            if project.get('description'):
                context += f" - {project['description']}"
            return context
            
    except Exception as e:
        logger.warning(f"Failed to get project context: {e}")
    
    return None


@app.task(bind=True, base=OCRTask, max_retries=3, default_retry_delay=60, queue='ocr')
def process_image(self, document_uuid: str, source_doc_sql_id: int, 
                 file_path: str, file_name: str, project_sql_id: int) -> Dict[str, Any]:
    """
    Process image files using OpenAI o4-mini vision for legal document analysis.
    
    Args:
        document_uuid: UUID of the document
        source_doc_sql_id: SQL ID of the source document
        file_path: S3 path to the image file
        file_name: Original filename
        project_sql_id: SQL ID of the project
    
    Returns:
        ImageProcessingTaskResult with validation and type safety
    """
    logger.info(f"[IMAGE_TASK:{self.request.id}] Processing image {document_uuid} ({file_name})")
    
    # Create task result model
    task_result = ImageProcessingTaskResult(
        task_id=self.request.id,
        document_uuid=uuid.UUID(document_uuid),
        vision_provider="openai_o4_mini"
    )
    
    try:
        # Check if stage is already completed
        processing_version = None
        if source_doc_sql_id:
            version_response = self.db_manager.client.table('source_documents').select(
                'processing_version'
            ).eq('id', source_doc_sql_id).execute()
            processing_version = version_response.data[0]['processing_version'] if version_response.data else 1
        
        is_completed, cached_results = check_stage_completed(document_uuid, "ocr", processing_version)
        if is_completed and cached_results:
            logger.info(f"[IMAGE_TASK:{self.request.id}] Stage already completed, using cached results")
            
            # Update database status from cache hit
            from scripts.celery_tasks.task_utils import update_status_on_cache_hit
            update_status_on_cache_hit(document_uuid, 'ocr', self.db_manager)
            
            # Create result from cached data
            task_result.image_analyzed = True
            task_result.text_extracted = cached_results.get('raw_text', '')
            # Get image type from additional_data if available
            image_type = ''
            if 'additional_data' in cached_results and cached_results['additional_data']:
                image_type = cached_results['additional_data'].get('image_type', '')
            task_result.image_description = image_type
            task_result.text_confidence = cached_results.get('confidence_score', 0.0)
            task_result.result_data = {"cached": True, "ocr_provider": cached_results.get('ocr_provider', 'o4_mini_cached')}
            
            # Chain to next task directly
            from scripts.celery_tasks.text_tasks import create_document_node
            create_document_node.delay(
                document_uuid=document_uuid,
                source_doc_sql_id=source_doc_sql_id,
                project_sql_id=project_sql_id,
                file_name=file_name,
                detected_file_type="image"
            )
            
            return task_result.model_dump()
        
        # Update state and status
        update_document_state(document_uuid, "ocr", "started", {"task_id": self.request.id})
        self.db_manager.update_processing_status('source_documents', source_doc_sql_id, 'image_processing')
        
        # Update Celery status in source_documents
        self.db_manager.client.table('source_documents').update({
            'celery_status': 'image_processing',
            'file_category': 'image',  # Ensure file category is set
            'last_modified_at': datetime.now().isoformat()
        }).eq('id', source_doc_sql_id).execute()
        
        # Image processing not supported - return minimal result
        extracted_text = "[Image processing not available]"
        confidence_score = 0.0
        image_type = "unsupported"
        
        # Update task result model with minimal info
        task_result.image_analyzed = False
        task_result.text_extracted = extracted_text
        task_result.image_description = image_type
        task_result.text_confidence = confidence_score
        task_result.tokens_used = 0
        task_result.api_cost = 0.0
        task_result.result_data = {
            "image_type": image_type,
            "description_length": 0,
            "input_tokens": processing_metadata.input_tokens,
            "output_tokens": processing_metadata.output_tokens
        }
        
        # Update database with image processing results
        self.db_manager.client.table('source_documents').update({
            'raw_extracted_text': extracted_text,
            'celery_status': 'image_completed',
            'initial_processing_status': 'image_completed',
            'image_analysis_confidence': confidence_score,
            'image_type': image_type,
            'o4_mini_tokens_used': processing_metadata.total_tokens,
            'o4_mini_input_tokens': processing_metadata.input_tokens,
            'o4_mini_output_tokens': processing_metadata.output_tokens,
            'image_processing_cost': processing_metadata.estimated_cost,
            'image_description_length': processing_metadata.description_length,
            'last_modified_at': datetime.now().isoformat()
        }).eq('id', source_doc_sql_id).execute()
        
        # Cache the result for future use using Pydantic model
        redis_mgr = get_redis_manager()
        if redis_mgr and redis_mgr.is_available():
            ocr_cache_key = CacheKeys.format_key(
                CacheKeys.DOC_OCR_RESULT,
                version=processing_version,
                document_uuid=document_uuid
            )
            
            # Create OCR result model first
            from scripts.core.processing_models import OCRResultModel, OCRPageResult
            import hashlib
            
            # Create OCR page result
            # Convert confidence to 0-1 scale if needed
            page_confidence = confidence_score
            if page_confidence > 1:
                page_confidence = page_confidence / 100.0
                
            ocr_page = OCRPageResult(
                page_number=1,
                text=extracted_text,
                confidence=page_confidence,
                word_count=len(extracted_text.split()) if extracted_text else 0
            )
            
            # Create OCR result model
            ocr_result = OCRResultModel(
                document_uuid=uuid.UUID(document_uuid),
                provider='o4_mini_vision',
                total_pages=1,
                pages=[ocr_page],
                full_text=extracted_text,
                average_confidence=page_confidence,
                file_type=detected_file_type,
                status=ProcessingResultStatus.SUCCESS,
                processing_time_seconds=processing_metadata.processing_time_seconds if hasattr(processing_metadata, 'processing_time_seconds') else 0,
                metadata={'image_type': image_type}
            )
            
            # Create file hash
            file_hash = hashlib.md5(file_path.encode()).hexdigest()
            
            # Create cached result using factory method
            cached_result = CachedOCRResultModel.create(
                document_uuid=uuid.UUID(document_uuid),
                ocr_result=ocr_result,
                file_hash=file_hash,
                provider='o4_mini_vision',
                ttl_seconds=86400  # 24 hours
            )
            
            redis_mgr.set_cached(ocr_cache_key, cached_result.model_dump(), ttl=86400)  # Cache for 24 hours
            logger.info(f"[IMAGE_TASK:{self.request.id}] Cached image processing result")
        
        # Update completion state
        update_document_state(document_uuid, "ocr", "completed", {
            "source": "o4_mini_vision",
            "text_length": len(extracted_text),
            "confidence_score": confidence_score,
            "image_type": image_type,
            "total_tokens": processing_metadata.total_tokens,
            "processing_cost": processing_metadata.estimated_cost
        })
        
        logger.info(f"[IMAGE_TASK:{self.request.id}] Successfully processed image {file_name}")
        
        # Chain to next task (text processing)
        from scripts.celery_tasks.text_tasks import create_document_node
        create_document_node.delay(
            document_uuid=document_uuid,
            source_doc_sql_id=source_doc_sql_id,
            project_sql_id=project_sql_id,
            file_name=file_name,
            detected_file_type="image"
        )
        
        return task_result.model_dump()
        
    except Exception as e:
        logger.error(f"[IMAGE_TASK:{self.request.id}] Image processing failed: {e}", exc_info=True)
        
        # Update task result with error
        task_result.status = "FAILURE"
        task_result.error_message = str(e)
        task_result.result_data = {"error": str(e)}
        
        # Update state as failed (image processing not supported)
        update_document_state(document_uuid, "ocr", "failed", {
            "error": str(e),
            "image_processing_not_available": True,
            "task_id": self.request.id
        })
        
        # Still chain to next task with fallback text
        from scripts.celery_tasks.text_tasks import create_document_node
        create_document_node.delay(
            document_uuid=document_uuid,
            source_doc_sql_id=source_doc_sql_id,
            project_sql_id=project_sql_id,
            file_name=file_name,
            detected_file_type="image"
        )
        
        # Add fallback data to result from Pydantic model
        task_result.text_extracted = fallback_result.extracted_text
        task_result.result_data["fallback_text"] = fallback_result.extracted_text
        
        return task_result.model_dump()


@app.task(bind=True, base=OCRTask, max_retries=3, default_retry_delay=60, queue='ocr')
def process_ocr(self, document_uuid: str, source_doc_sql_id: int, file_path: str, 
                file_name: str, detected_file_type: str, project_sql_id: int) -> Dict[str, Any]:
    """
    Process document OCR based on file type.
    
    Args:
        document_uuid: UUID of the document
        source_doc_sql_id: SQL ID of the source document
        file_path: Path to the file (local or S3 URI)
        file_name: Name of the file
        detected_file_type: Detected file extension (.pdf, .docx, etc.)
        project_sql_id: SQL ID of the project
    
    Returns:
        OCRTaskResult with validation and type safety
    """
    logger.info(f"[OCR_TASK:{self.request.id}] Processing document {document_uuid} ({file_name})")
    logger.info(f"[OCR_TASK:{self.request.id}] Original file path: {file_path}")
    
    # Create task result model
    task_result = OCRTaskResult(
        task_id=self.request.id,
        document_uuid=uuid.UUID(document_uuid),
        ocr_provider="textract"  # Default, will be updated based on file type
    )
    
    try:
        # Resolve file path for local files
        if not file_path.startswith(('s3://', 'http://', 'https://', 'supabase://')):
            path_found, resolved_path = resolve_file_path(file_path)
            if path_found and resolved_path:
                logger.info(f"[OCR_TASK:{self.request.id}] Resolved file path: {resolved_path}")
                file_path = resolved_path
            else:
                error_msg = f"File not found: {file_path}"
                logger.error(f"[OCR_TASK:{self.request.id}] {error_msg}")
                
                # Update database with detailed error
                error_metadata = [{
                    "status": "error",
                    "stage": "file_validation",
                    "error_message": error_msg,
                    "original_path": file_path,
                    "working_directory": os.getcwd(),
                    "task_id": self.request.id,
                    "timestamp": datetime.now().isoformat()
                }]
                
                self.db_manager.client.table('source_documents').update({
                    'textract_job_id': 'N/A_PATH_NOT_FOUND',
                    'textract_job_status': 'failed',
                    'ocr_metadata_json': error_metadata,
                    'error_message': error_msg,
                    'celery_status': 'ocr_failed',
                    'last_modified_at': datetime.now().isoformat()
                }).eq('id', source_doc_sql_id).execute()
                
                raise FileNotFoundError(error_msg)
        # Check if stage is already completed
        processing_version = None
        if source_doc_sql_id:
            version_response = self.db_manager.client.table('source_documents').select(
                'processing_version'
            ).eq('id', source_doc_sql_id).execute()
            processing_version = version_response.data[0]['processing_version'] if version_response.data else 1
        
        is_completed, cached_results = check_stage_completed(document_uuid, "ocr", processing_version)
        if is_completed and cached_results:
            logger.info(f"[OCR_TASK:{self.request.id}] Stage already completed, using cached results")
            
            # Update database status from cache hit
            from scripts.celery_tasks.task_utils import update_status_on_cache_hit
            update_status_on_cache_hit(document_uuid, 'ocr', self.db_manager)
            
            # Create result from cached data
            task_result.extracted_text = cached_results.get('raw_text', '')
            task_result.ocr_provider = cached_results.get('ocr_provider', 'cached')
            task_result.result_data = {"cached": True}
            
            # Chain to next task directly
            from scripts.celery_tasks.text_tasks import create_document_node
            create_document_node.delay(
                document_uuid=document_uuid,
                source_doc_sql_id=source_doc_sql_id,
                project_sql_id=project_sql_id,
                file_name=file_name,
                detected_file_type=detected_file_type
            )
            
            return task_result.model_dump()
        
        # ROUTING LOGIC: Detect file category and route appropriately
        file_category = detect_file_category(file_name)
        
        if file_category == 'image':
            logger.info(f"[OCR_TASK:{self.request.id}] Detected image file, routing to image processing")
            
            # Update file category in database
            self.db_manager.client.table('source_documents').update({
                'file_category': 'image',
                'celery_status': 'image_queued',
                'last_modified_at': datetime.now().isoformat()
            }).eq('id', source_doc_sql_id).execute()
            
            # Delegate to image processing task
            result = process_image.delay(
                document_uuid=document_uuid,
                source_doc_sql_id=source_doc_sql_id,
                file_path=file_path,
                file_name=file_name,
                project_sql_id=project_sql_id
            )
            
            # Update task result for routing
            task_result.ocr_provider = "routed_to_image"
            task_result.result_data = {
                "routed_to": "image_processing",
                "task_id": result.id,
                "file_category": "image"
            }
            
            return task_result.model_dump()
        
        elif file_category == 'video':
            logger.info(f"[OCR_TASK:{self.request.id}] Detected video file - reserved for future deployment")
            
            # Update file category and create note
            video_note = f"Video file '{file_name}' detected. Video processing is reserved for future deployment. File skipped."
            
            self.db_manager.client.table('source_documents').update({
                'file_category': 'video',
                'celery_status': 'skipped_video',
                'extracted_text': video_note,
                'last_modified_at': datetime.now().isoformat()
            }).eq('id', source_doc_sql_id).execute()
            
            # Mark as completed state for pipeline continuation
            update_document_state(document_uuid, "ocr", "completed", {
                "source": "video_skipped",
                "note": video_note,
                "file_category": "video"
            })
            
            # Update task result
            task_result.ocr_provider = "video_skipped"
            task_result.extracted_text = video_note
            task_result.result_data = {
                "skipped": True,
                "reason": "video_processing_reserved",
                "file_category": "video"
            }
            
            return task_result.model_dump()
        
        # For non-image files, continue with existing OCR processing
        logger.info(f"[OCR_TASK:{self.request.id}] Processing {file_category} file with traditional OCR")
        
        # Update file category in database
        self.db_manager.client.table('source_documents').update({
            'file_category': file_category,
            'last_modified_at': datetime.now().isoformat()
        }).eq('id', source_doc_sql_id).execute()
        
        # Update state
        update_document_state(document_uuid, "ocr", "started", {"task_id": self.request.id})
        self.db_manager.update_processing_status('source_documents', source_doc_sql_id, 'ocr_processing')
        
        # Update Celery status in source_documents
        self.db_manager.client.table('source_documents').update({
            'celery_status': 'ocr_processing',
            'last_modified_at': datetime.now().isoformat()
        }).eq('id', source_doc_sql_id).execute()
        
        # Check cache first
        redis_mgr = get_redis_manager()
        cached_result = None
        
        if redis_mgr and redis_mgr.is_available():
            # Get processing version from database
            version_response = self.db_manager.client.table('source_documents').select(
                'processing_version'
            ).eq('id', source_doc_sql_id).execute()
            
            processing_version = None
            if version_response.data and len(version_response.data) > 0:
                processing_version = version_response.data[0].get('processing_version')
            
            # Check cache with version
            ocr_cache_key = CacheKeys.format_key(
                CacheKeys.DOC_OCR_RESULT, 
                version=processing_version,
                document_uuid=document_uuid
            )
            cached_result = redis_mgr.get_cached(ocr_cache_key)
            
            if cached_result:
                logger.info(f"[OCR_TASK:{self.request.id}] Retrieved OCR result from cache")
                raw_text = cached_result.get('raw_text')
                ocr_meta = cached_result.get('ocr_meta')
                ocr_provider = cached_result.get('ocr_provider', 'cached')
                
                # Update database with cached result
                self.db_manager.update_source_document_text(
                    source_doc_sql_id, raw_text,
                    ocr_meta_json=json.dumps(ocr_meta) if ocr_meta else None,
                    status="ocr_complete"
                )
                
                # Update state and proceed to next task
                update_document_state(document_uuid, "ocr", "completed", {
                    "source": "cache",
                    "text_length": len(raw_text) if raw_text else 0
                })
                
                # Update task result
                task_result.extracted_text = raw_text or ""
                task_result.ocr_provider = ocr_provider
                task_result.result_data = {"cached": True, "text_length": len(raw_text) if raw_text else 0}
                
                # Chain to next task
                from scripts.celery_tasks.text_tasks import create_document_node
                create_document_node.delay(
                    document_uuid=document_uuid,
                    source_doc_sql_id=source_doc_sql_id,
                    project_sql_id=project_sql_id
                )
                
                return task_result.model_dump()
        
        raw_text = None
        ocr_meta = None
        ocr_provider = None
        
        # Convert MIME type to extension if needed
        mime_to_extension = {
            'application/pdf': '.pdf',
            'application/msword': '.doc',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx',
            'text/plain': '.txt',
            'message/rfc822': '.eml',
            'application/vnd.ms-outlook': '.msg',
            'image/jpeg': '.jpg',
            'image/png': '.png',
            'image/tiff': '.tiff',
            'image/heic': '.heic',
            'audio/wav': '.wav',
            'audio/mpeg': '.mp3',
            'audio/mp4': '.m4a',
            'audio/ogg': '.ogg',
            'video/quicktime': '.mov',
            'video/mp4': '.mp4'
        }
        
        # Check if detected_file_type is a MIME type
        if '/' in detected_file_type:
            # It's a MIME type, convert to extension
            file_extension = mime_to_extension.get(detected_file_type.lower())
            if file_extension:
                logger.info(f"[OCR_TASK:{self.request.id}] Converted MIME type {detected_file_type} to extension {file_extension}")
                detected_file_type = file_extension
            else:
                # Try to extract extension from filename
                if file_name and '.' in file_name:
                    file_extension = os.path.splitext(file_name)[1].lower()
                    logger.info(f"[OCR_TASK:{self.request.id}] Extracted extension {file_extension} from filename")
                    detected_file_type = file_extension
                else:
                    logger.warning(f"[OCR_TASK:{self.request.id}] Unknown MIME type: {detected_file_type}")
        
        # Route based on file type
        if detected_file_type.lower() == '.pdf':
            ocr_provider = 'textract'
            task_result.ocr_provider = ocr_provider
            
            # Update status to indicate Textract is starting
            self.db_manager.client.table('source_documents').update({
                'ocr_provider': ocr_provider,
                'textract_job_status': 'submitted',
                'last_modified_at': datetime.now().isoformat()
            }).eq('id', source_doc_sql_id).execute()
            
            # Extract text using Textract
            raw_text, ocr_meta = extract_text_from_pdf_textract(
                db_manager=self.db_manager,
                source_doc_sql_id=source_doc_sql_id,
                pdf_path_or_s3_uri=file_path,
                document_uuid_from_db=document_uuid
            )
            
        elif detected_file_type.lower() in ['.docx', '.doc']:
            ocr_provider = 'docx_parser'
            task_result.ocr_provider = ocr_provider
            
            # Use S3-aware extraction
            from scripts.s3_storage import S3StorageManager
            raw_text, ocr_meta = extract_text_from_docx_s3_aware(
                file_path_or_s3_uri=file_path,
                s3_manager=S3StorageManager() if file_path.startswith('s3://') else None
            )
            # Check for extraction errors
            if raw_text is None and ocr_meta and isinstance(ocr_meta, list) and len(ocr_meta) > 0:
                if ocr_meta[0].get('status') == 'error':
                    error_msg = ocr_meta[0].get('error_message', 'Unknown DOCX extraction error')
                    logger.error(f"DOCX extraction error: {error_msg}")
                    raise RuntimeError(f"DOCX extraction failed: {error_msg}")
            
        elif detected_file_type.lower() in ['.txt', '.text']:
            ocr_provider = 'text_parser'
            task_result.ocr_provider = ocr_provider
            raw_text = extract_text_from_txt(file_path)  # file_path already resolved
            ocr_meta = [{"method": "text_parser"}]
            
        elif detected_file_type.lower() in ['.eml', '.msg']:
            ocr_provider = 'email_parser'
            task_result.ocr_provider = ocr_provider
            raw_text = extract_text_from_eml(file_path)  # file_path already resolved
            ocr_meta = [{"method": "email_parser"}]
            
        elif detected_file_type.lower() in ['.wav', '.mp3', '.m4a', '.ogg']:
            # Choose transcription method based on configuration
            if USE_OPENAI_FOR_AUDIO_TRANSCRIPTION:
                ocr_provider = 'openai_whisper'
                task_result.ocr_provider = ocr_provider
                raw_text = transcribe_audio_openai_whisper(file_path)
                ocr_meta = [{"method": "openai_whisper"}]
            else:
                ocr_provider = 'local_whisper'
                task_result.ocr_provider = ocr_provider
                raw_text = transcribe_audio_whisper(file_path)
                ocr_meta = [{"method": "local_whisper"}]
                
        else:
            raise ValueError(f"Unsupported file type: {detected_file_type}")
        
        # Check if we got text
        if raw_text:
            # Update task result
            task_result.extracted_text = raw_text
            task_result.total_pages = len(ocr_meta) if ocr_meta else 1
            task_result.pages_processed = task_result.total_pages
            task_result.result_data = {
                "text_length": len(raw_text),
                "provider": ocr_provider,
                "file_type": detected_file_type
            }
            
            # Update database with extracted text
            self.db_manager.update_source_document_text(
                source_doc_sql_id, raw_text,
                ocr_meta_json=json.dumps(ocr_meta) if ocr_meta else None,
                status="ocr_complete"
            )
            
            # Update provider and completion time
            if ocr_provider:
                self.db_manager.client.table('source_documents').update({
                    'ocr_provider': ocr_provider,
                    'ocr_completed_at': datetime.now().isoformat()
                }).eq('id', source_doc_sql_id).execute()
            
            # Cache the OCR result using Pydantic model
            if redis_mgr and redis_mgr.is_available():
                # Get processing version
                version_response = self.db_manager.client.table('source_documents').select(
                    'processing_version'
                ).eq('id', source_doc_sql_id).execute()
                
                processing_version = None
                if version_response.data and len(version_response.data) > 0:
                    processing_version = version_response.data[0].get('processing_version')
                
                # Cache with version using Pydantic model
                ocr_cache_key = CacheKeys.format_key(
                    CacheKeys.DOC_OCR_RESULT, 
                    version=processing_version,
                    document_uuid=document_uuid
                )
                
                # Create OCR result model first
                from scripts.core.processing_models import OCRResultModel, OCRPageResult
                import hashlib
                
                # Create OCR page results from metadata
                pages = []
                if ocr_meta and isinstance(ocr_meta, list):
                    for i, meta in enumerate(ocr_meta):
                        page_num = meta.get('page_number', i + 1) if isinstance(meta, dict) else i + 1
                        # For single page docs, use full text
                        page_text = raw_text if len(ocr_meta) == 1 else ""
                        confidence = meta.get('confidence_threshold', 0.0) if isinstance(meta, dict) else 0.0
                        # Convert confidence to 0-1 scale if needed
                        if confidence > 1:
                            confidence = confidence / 100.0
                        
                        pages.append(OCRPageResult(
                            page_number=page_num,
                            text=page_text,
                            confidence=confidence,
                            word_count=len(page_text.split()) if page_text else 0
                        ))
                else:
                    # Default single page
                    pages.append(OCRPageResult(
                        page_number=1,
                        text=raw_text,
                        confidence=0.0,
                        word_count=len(raw_text.split()) if raw_text else 0
                    ))
                
                # Create OCR result model
                ocr_result = OCRResultModel(
                    document_uuid=uuid.UUID(document_uuid),
                    provider=ocr_provider,
                    total_pages=len(pages),
                    pages=pages,
                    full_text=raw_text,
                    average_confidence=sum(p.confidence for p in pages) / len(pages) if pages else 0.0,
                    file_type=detected_file_type,
                    status=ProcessingResultStatus.SUCCESS,
                    metadata=ocr_meta[0] if ocr_meta and isinstance(ocr_meta[0], dict) else {}
                )
                
                # Create file hash
                file_hash = hashlib.md5(file_path.encode()).hexdigest()
                
                # Create cached result using factory method
                cached_result = CachedOCRResultModel.create(
                    document_uuid=uuid.UUID(document_uuid),
                    ocr_result=ocr_result,
                    file_hash=file_hash,
                    provider=ocr_provider,
                    ttl_seconds=7 * 24 * 3600  # 7 days
                )
                
                redis_mgr.set_cached(ocr_cache_key, cached_result.model_dump(), ttl=7 * 24 * 3600)  # 7 days
                logger.info(f"[OCR_TASK:{self.request.id}] Cached OCR result in Redis")
            
            # Update state to completed
            update_document_state(document_uuid, "ocr", "completed", {
                "text_length": len(raw_text),
                "provider": ocr_provider
            })
            
            # Update Celery status in source_documents
            self.db_manager.client.table('source_documents').update({
                'celery_status': 'ocr_complete',
                'last_modified_at': datetime.now().isoformat()
            }).eq('id', source_doc_sql_id).execute()
            
            # Chain to next task - create document node (pass only document_uuid)
            from scripts.celery_tasks.text_tasks import create_document_node
            create_document_node.delay(
                document_uuid=document_uuid,
                source_doc_sql_id=source_doc_sql_id,
                project_sql_id=project_sql_id
            )
            
            return task_result.model_dump()
        else:
            raise RuntimeError(f"OCR failed to extract text from {file_name}")
            
    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {str(exc)}"
        logger.exception(f"[OCR_TASK:{self.request.id}] Error processing {document_uuid}: {exc}")
        
        # Update task result with error
        task_result.status = "FAILURE"
        task_result.error_message = error_msg
        task_result.result_data = {"error": error_msg}
        
        # Save error to database
        try:
            self.db_manager.client.table('source_documents').update({
                'error_message': error_msg[:500],  # Truncate long errors
                'celery_status': 'ocr_failed',
                'last_modified_at': datetime.now().isoformat()
            }).eq('id', source_doc_sql_id).execute()
        except Exception as db_exc:
            logger.error(f"Failed to save error to database: {db_exc}")
        
        # Update state for monitoring
        update_document_state(document_uuid, "ocr", "failed", {
            "error": error_msg,
            "task_id": self.request.id
        })
        
        # Retry with exponential backoff
        countdown = int(self.default_retry_delay * (2 ** self.request.retries))
        raise self.retry(exc=exc, countdown=min(countdown, 600))  # Max 10 minutes


@app.task(bind=True, base=OCRTask, max_retries=5, default_retry_delay=300, queue='ocr')
def check_textract_job_status(self, job_id: str, document_uuid: str, source_doc_sql_id: int) -> Dict[str, Any]:
    """
    Check the status of an async Textract job.
    This is called periodically for long-running Textract jobs.
    
    Args:
        job_id: Textract job ID
        document_uuid: UUID of the document
        source_doc_sql_id: SQL ID of the source document
    
    Returns:
        OCRTaskResult with validation and type safety
    """
    logger.info(f"[TEXTRACT_CHECK:{self.request.id}] Checking Textract job {job_id} for document {document_uuid}")
    
    # Create task result model
    task_result = OCRTaskResult(
        task_id=self.request.id,
        document_uuid=uuid.UUID(document_uuid),
        ocr_provider="textract_async",
        textract_job_id=job_id
    )
    
    try:
        from textract_utils import TextractProcessor
        
        textract = TextractProcessor(self.db_manager)
        
        # Check job status
        status = textract.get_job_status(job_id)
        
        if status == 'SUCCEEDED':
            # Job completed successfully - retrieve results
            pages_data = textract.get_job_results(job_id)
            
            if pages_data:
                # Process the results
                full_text = "\n\n".join([page.get('text', '') for page in pages_data])
                
                # Update task result
                task_result.extracted_text = full_text
                task_result.total_pages = len(pages_data)
                task_result.pages_processed = len(pages_data)
                task_result.result_data = {
                    "text_length": len(full_text),
                    "pages_data": pages_data,
                    "textract_job_id": job_id
                }
                
                # Update database
                self.db_manager.update_source_document_text(
                    source_doc_sql_id, full_text,
                    ocr_meta_json=json.dumps(pages_data),
                    status="ocr_complete"
                )
                
                # Update completion time
                self.db_manager.client.table('source_documents').update({
                    'ocr_provider': 'textract',
                    'ocr_completed_at': datetime.now().isoformat(),
                    'textract_job_status': 'completed'
                }).eq('id', source_doc_sql_id).execute()
                
                # Update state
                update_document_state(document_uuid, "ocr", "completed", {
                    "text_length": len(full_text),
                    "provider": "textract_async"
                })
                
                # Chain to next task
                from scripts.celery_tasks.text_tasks import create_document_node
                
                # Fetch additional data needed for next task
                doc_data = self.db_manager.client.table('source_documents').select(
                    'file_name, detected_file_type, project_id'
                ).eq('id', source_doc_sql_id).single().execute()
                
                create_document_node.delay(
                    document_uuid=document_uuid,
                    source_doc_sql_id=source_doc_sql_id,
                    project_sql_id=doc_data.data['project_id'],
                    file_name=doc_data.data['file_name'],
                    detected_file_type=doc_data.data['detected_file_type'],
                    raw_text=full_text,
                    ocr_meta_json=json.dumps(pages_data)
                )
                
                return task_result.model_dump()
                
        elif status == 'FAILED':
            # Job failed
            task_result.status = "FAILURE"
            task_result.error_message = f"Textract job {job_id} failed"
            task_result.result_data = {"textract_status": "FAILED"}
            raise RuntimeError(f"Textract job {job_id} failed")
            
        else:
            # Job still in progress - retry later
            logger.info(f"Textract job {job_id} still in progress (status: {status})")
            
            # Update status in database
            self.db_manager.client.table('source_documents').update({
                'textract_job_status': status.lower()
            }).eq('id', source_doc_sql_id).execute()
            
            # Update task result for retry
            task_result.result_data = {"textract_status": status, "retrying": True}
            
            # Retry after delay
            raise self.retry(countdown=300)  # Retry in 5 minutes
            
    except Exception as exc:
        logger.error(f"[TEXTRACT_CHECK:{self.request.id}] Error checking job {job_id}: {exc}", exc_info=True)
        
        # Update task result with error
        task_result.status = "FAILURE"
        task_result.error_message = str(exc)
        task_result.result_data = {"error": str(exc)}
        
        # Update status
        self.db_manager.client.table('source_documents').update({
            'textract_job_status': 'error'
        }).eq('id', source_doc_sql_id).execute()
        
        # Retry with longer delay
        countdown = min(300 * (2 ** self.request.retries), 3600)  # Max 1 hour
        raise self.retry(exc=exc, countdown=countdown)
    
    # This should never be reached, but add as safety
    return task_result.model_dump()