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
import tempfile
import shutil

from celery import Task, group, chain
import celery.exceptions
from botocore.exceptions import ClientError, ConnectionError as BotoConnectionError
from scripts.celery_app import app
from scripts.cache import get_redis_manager, CacheKeys, redis_cache
from scripts.db import DatabaseManager
from scripts.entity_service import EntityService
from scripts.graph_service import GraphService
from scripts.ocr_extraction import extract_text_from_pdf
from scripts.chunking_utils import simple_chunk_text
# from scripts.s3_storage import upload_to_s3, generate_s3_key  # Not used currently
from scripts.models import ProcessingStatus, ProcessingResultStatus, EntityMentionMinimal as EntityMentionModel
from scripts.utils.pdf_handler import safe_pdf_operation
from scripts.utils.param_validator import validate_task_params
from scripts.config import OPENAI_API_KEY, S3_PRIMARY_DOCUMENT_BUCKET, get_database_url

logger = logging.getLogger(__name__)

# Circuit breaker implementation
import threading

class DocumentCircuitBreaker:
    """Circuit breaker to prevent cascade failures"""
    
    def __init__(self, failure_threshold=3, reset_timeout=300, memory_threshold_mb=400):
        self.failure_counts = defaultdict(int)
        self.failure_times = defaultdict(float)
        self.blocked_until = defaultdict(float)
        self.threshold = failure_threshold
        self.timeout = reset_timeout
        self.memory_threshold_mb = memory_threshold_mb
        self.lock = threading.Lock()
    
    def check_memory(self):
        """Check system memory usage"""
        try:
            import psutil
            memory = psutil.virtual_memory()
            used_mb = (memory.total - memory.available) / (1024 * 1024)
            total_mb = memory.total / (1024 * 1024)
            percent = memory.percent
            
            if percent > 80:
                logger.warning(f"High memory usage: {used_mb:.0f}/{total_mb:.0f}MB ({percent:.1f}%)")
                return False
            return True
        except:
            return True  # Assume OK if can't check
    
    def can_process(self, document_uuid: str) -> Tuple[bool, str]:
        """Check if document can be processed"""
        with self.lock:
            now = time.time()
            
            # Check memory first
            if not self.check_memory():
                return False, "System memory usage too high"
            
            # Check if blocked
            if self.blocked_until[document_uuid] > now:
                remaining = int(self.blocked_until[document_uuid] - now)
                return False, f"Circuit breaker OPEN: blocked for {remaining}s"
            
            # Check failure count
            if self.failure_counts[document_uuid] >= self.threshold:
                # Reset if timeout passed
                if now - self.failure_times[document_uuid] > self.timeout:
                    self.reset(document_uuid)
                    return True, "Circuit breaker RESET"
                else:
                    # Block it
                    self.blocked_until[document_uuid] = now + self.timeout
                    return False, f"Circuit breaker OPEN: {self.failure_counts[document_uuid]} failures"
            
            return True, "OK"
    
    def record_failure(self, document_uuid: str, error: str):
        """Record a failure"""
        with self.lock:
            self.failure_counts[document_uuid] += 1
            self.failure_times[document_uuid] = time.time()
            logger.warning(f"Circuit breaker: {document_uuid} failure #{self.failure_counts[document_uuid]}: {error}")
    
    def record_success(self, document_uuid: str):
        """Record a success"""
        with self.lock:
            if document_uuid in self.failure_counts:
                logger.info(f"Circuit breaker: {document_uuid} succeeded, resetting")
                self.reset(document_uuid)
    
    def reset(self, document_uuid: str):
        """Reset circuit breaker for document"""
        self.failure_counts.pop(document_uuid, None)
        self.failure_times.pop(document_uuid, None)
        self.blocked_until.pop(document_uuid, None)

# Initialize global circuit breaker
circuit_breaker = DocumentCircuitBreaker()

# Define retryable exceptions
RETRYABLE_EXCEPTIONS = (
    # AWS/Boto3 exceptions
    ClientError,
    BotoConnectionError,
    # Network exceptions
    ConnectionError,
    TimeoutError,
    # Transient errors
    Exception,  # Will be filtered by error message
)

# Non-retryable error messages
NON_RETRYABLE_ERRORS = [
    'DocumentTooLargeException',
    'InvalidPDFException',
    'UnsupportedDocumentException',
    'AccessDenied',
    'NoSuchBucket',
    'NoSuchKey',
]


# Smart retry logic helper
def is_retryable_error(exception):
    """Determine if an error should be retried."""
    error_message = str(exception)
    
    # Check if it's a non-retryable error
    for non_retryable in NON_RETRYABLE_ERRORS:
        if non_retryable in error_message:
            logger.info(f"Non-retryable error detected: {non_retryable}")
            return False
    
    # Check if it's a retryable exception type
    if isinstance(exception, RETRYABLE_EXCEPTIONS):
        # Additional checks for specific error codes
        if isinstance(exception, ClientError):
            error_code = exception.response.get('Error', {}).get('Code', '')
            if error_code in ['ThrottlingException', 'ProvisionedThroughputExceededException', 
                              'ServiceUnavailable', 'RequestTimeout']:
                logger.info(f"Retryable AWS error: {error_code}")
                return True
            elif error_code in NON_RETRYABLE_ERRORS:
                logger.info(f"Non-retryable AWS error: {error_code}")
                return False
        
        # Check for transient network errors
        if 'timeout' in error_message.lower() or 'connection' in error_message.lower():
            logger.info("Retryable network error detected")
            return True
    
    # Default: don't retry unknown errors
    logger.info(f"Unknown error type, not retrying: {type(exception).__name__}")
    return False


def calculate_retry_delay(retry_count):
    """Calculate exponential backoff delay with jitter."""
    import random
    
    # Base delay with exponential backoff
    base_delay = min(60, 5 * (2 ** retry_count))  # 5s, 10s, 20s, 40s, 60s max
    
    # Add jitter to prevent thundering herd
    jitter = random.uniform(0, base_delay * 0.1)  # Up to 10% jitter
    
    return base_delay + jitter


# Task execution decorator for enhanced visibility
def log_task_execution(func):
    """Decorator to log task execution details with timing and context."""
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        task_id = self.request.id if hasattr(self, 'request') else 'manual'
        doc_uuid = kwargs.get('document_uuid', 'unknown')
        task_name = func.__name__
        retry_count = self.request.retries if hasattr(self, 'request') else 0
        
        # Log task start with visual separator
        logger.info("="*60)
        logger.info(f"🚀 TASK START: {task_name}")
        logger.info(f"📄 Document: {doc_uuid}")
        logger.info(f"🔖 Task ID: {task_id}")
        if retry_count > 0:
            logger.info(f"🔄 Retry Attempt: {retry_count}")
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
            if retry_count > 0:
                logger.info(f"✅ Succeeded after {retry_count} retries")
            logger.info(f"🏁 End Time: {datetime.now().isoformat()}")
            logger.info("="*60)
            
            return result
            
        except Exception as e:
            # Calculate elapsed time
            elapsed = time.time() - start_time
            
            # Check if error is retryable
            retryable = is_retryable_error(e)
            
            # Log detailed error information
            logger.error("="*60)
            logger.error(f"❌ TASK FAILED: {task_name}")
            logger.error(f"📄 Document: {doc_uuid}")
            logger.error(f"⏱️  Duration: {elapsed:.2f} seconds")
            logger.error(f"🔴 Error Type: {type(e).__name__}")
            logger.error(f"💬 Error Message: {str(e)}")
            logger.error(f"🔄 Retryable: {'Yes' if retryable else 'No'}")
            if retry_count > 0:
                logger.error(f"🔢 Retry Count: {retry_count}")
            logger.error("📋 Traceback:")
            logger.error(traceback.format_exc())
            logger.error("="*60)
            
            # Handle retry logic
            if retryable and hasattr(self, 'retry') and retry_count < self.max_retries:
                retry_delay = calculate_retry_delay(retry_count)
                logger.info(f"🔄 Scheduling retry in {retry_delay:.1f} seconds")
                raise self.retry(exc=e, countdown=retry_delay)
            
            # Re-raise the exception if not retryable or max retries reached
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


# ========== Simple DB Fallback Functions for Redis Acceleration ==========

def get_ocr_text_from_db(document_uuid: str) -> Optional[str]:
    """Simple DB query for OCR text."""
    from scripts.db import DatabaseManager
    from scripts.models import SourceDocumentMinimal
    
    db = DatabaseManager()
    session = next(db.get_session())
    try:
        doc = session.query(SourceDocumentMinimal).filter_by(
            document_uuid=document_uuid
        ).first()
        return doc.raw_extracted_text if doc else None
    finally:
        session.close()

def get_chunks_from_db(document_uuid: str) -> List[Dict]:
    """Simple DB query for chunks."""
    from scripts.db import DatabaseManager
    from scripts.models import DocumentChunkMinimal
    
    db = DatabaseManager()
    session = next(db.get_session())
    try:
        chunks = session.query(DocumentChunkMinimal).filter_by(
            document_uuid=document_uuid
        ).order_by(DocumentChunkMinimal.chunk_index).all()
        return [chunk.dict() for chunk in chunks]
    finally:
        session.close()

def get_entities_from_db(document_uuid: str) -> List[Dict]:
    """Simple DB query for entities."""
    from scripts.db import DatabaseManager
    from scripts.models import EntityMentionMinimal
    
    db = DatabaseManager()
    session = next(db.get_session())
    try:
        entities = session.query(EntityMentionMinimal).filter_by(
            document_uuid=document_uuid
        ).all()
        return [entity.dict() for entity in entities]
    finally:
        session.close()


# Large file handling functions
def check_file_size(file_path: str) -> float:
    """Check file size in MB."""
    if file_path.startswith('s3://'):
        # For S3 files, use boto3 to check size
        import boto3
        from urllib.parse import urlparse
        
        parsed = urlparse(file_path)
        bucket = parsed.netloc
        key = parsed.path.lstrip('/')
        
        s3_client = boto3.client('s3')
        try:
            response = s3_client.head_object(Bucket=bucket, Key=key)
            size_bytes = response['ContentLength']
            return size_bytes / (1024 * 1024)  # Convert to MB
        except Exception as e:
            logger.error(f"Error checking S3 file size: {e}")
            return 0
    else:
        # Local file
        if os.path.exists(file_path):
            size_bytes = os.path.getsize(file_path)
            return size_bytes / (1024 * 1024)  # Convert to MB
        return 0


def retry_with_backoff(func, max_attempts=3, *args, **kwargs):
    """Execute a function with retry logic and exponential backoff."""
    last_exception = None
    
    for attempt in range(max_attempts):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_exception = e
            if is_retryable_error(e) and attempt < max_attempts - 1:
                delay = calculate_retry_delay(attempt)
                logger.warning(f"Attempt {attempt + 1} failed: {str(e)}. Retrying in {delay:.1f}s...")
                time.sleep(delay)
            else:
                break
    
    # If we get here, all attempts failed
    raise last_exception


def split_large_pdf(file_path: str, document_uuid: str, max_size_mb: int = 400) -> List[Dict[str, Any]]:
    """
    Split a large PDF into smaller parts for processing.
    
    Args:
        file_path: Path to the PDF file (local or S3)
        document_uuid: UUID of the document
        max_size_mb: Maximum size per part in MB
        
    Returns:
        List of dictionaries containing part information
    """
    import fitz  # PyMuPDF
    import boto3
    from io import BytesIO
    
    logger.info(f"Splitting large PDF {file_path} into parts (max size: {max_size_mb}MB)")
    
    parts = []
    temp_dir = None
    
    try:
        # Create temporary directory for parts
        temp_dir = tempfile.mkdtemp(prefix=f"pdf_split_{document_uuid}_")
        
        # Load PDF with retry logic for S3 downloads
        if file_path.startswith('s3://'):
            # Download from S3 with retry
            from urllib.parse import urlparse
            parsed = urlparse(file_path)
            bucket = parsed.netloc
            key = parsed.path.lstrip('/')
            
            def download_from_s3():
                s3_client = boto3.client('s3')
                response = s3_client.get_object(Bucket=bucket, Key=key)
                return response['Body'].read()
            
            pdf_bytes = retry_with_backoff(download_from_s3, max_attempts=3)
            
            # Open PDF from bytes
            pdf_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        else:
            # Open local file
            pdf_doc = fitz.open(file_path)
        
        total_pages = pdf_doc.page_count
        logger.info(f"PDF has {total_pages} pages")
        
        # Calculate pages per part based on file size
        file_size_mb = check_file_size(file_path)
        pages_per_part = max(1, int(total_pages * max_size_mb / file_size_mb))
        
        # Split PDF into parts
        part_num = 1
        page_start = 0
        
        while page_start < total_pages:
            page_end = min(page_start + pages_per_part, total_pages)
            
            # Create new PDF with subset of pages
            part_doc = fitz.open()
            for page_num in range(page_start, page_end):
                part_doc.insert_pdf(pdf_doc, from_page=page_num, to_page=page_num)
            
            # Save part to temporary file
            part_filename = f"{document_uuid}_part_{part_num:03d}.pdf"
            part_path = os.path.join(temp_dir, part_filename)
            part_doc.save(part_path)
            part_doc.close()
            
            # Upload part to S3 with retry
            s3_key = f"documents/{document_uuid}/parts/{part_filename}"
            
            def upload_to_s3():
                s3_client = boto3.client('s3')
                with open(part_path, 'rb') as f:
                    s3_client.upload_fileobj(f, S3_PRIMARY_DOCUMENT_BUCKET, s3_key)
            
            retry_with_backoff(upload_to_s3, max_attempts=3)
            
            parts.append({
                'part_number': part_num,
                'filename': part_filename,
                's3_bucket': S3_PRIMARY_DOCUMENT_BUCKET,
                's3_key': s3_key,
                's3_uri': f"s3://{S3_PRIMARY_DOCUMENT_BUCKET}/{s3_key}",
                'start_page': page_start + 1,  # 1-indexed for display
                'end_page': page_end,
                'page_count': page_end - page_start,
                'local_path': part_path
            })
            
            logger.info(f"Created part {part_num}: pages {page_start + 1}-{page_end}")
            
            page_start = page_end
            part_num += 1
        
        pdf_doc.close()
        
        logger.info(f"Successfully split PDF into {len(parts)} parts")
        return parts
        
    except Exception as e:
        logger.error(f"Error splitting PDF: {e}")
        raise
    finally:
        # Clean up temporary directory
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)


def process_pdf_parts(document_uuid: str, parts: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Process multiple PDF parts and combine results.
    
    Args:
        document_uuid: UUID of the document
        parts: List of part information dictionaries
        
    Returns:
        Combined processing results
    """
    from scripts.textract_utils import TextractProcessor
    from scripts.db import DatabaseManager
    
    logger.info(f"Processing {len(parts)} parts for document {document_uuid}")
    
    db_manager = DatabaseManager(validate_conformance=False)
    textract = TextractProcessor(db_manager)
    
    all_job_ids = []
    all_text = []
    total_pages = 0
    
    # Submit all parts to Textract with retry logic
    for part in parts:
        try:
            # Submit to Textract with retry
            def submit_to_textract():
                return textract.extract_text_with_fallback(part['s3_uri'], f"{document_uuid}_part_{part['part_number']}")
            
            result = retry_with_backoff(submit_to_textract, max_attempts=3)
            
            if result['status'] == 'textract_initiated':
                job_id = result['job_id']
                all_job_ids.append({
                    'job_id': job_id,
                    'part_number': part['part_number'],
                    'start_page': part['start_page'],
                    'end_page': part['end_page']
                })
                logger.info(f"Started Textract job {job_id} for part {part['part_number']}")
            else:
                logger.warning(f"Part {part['part_number']} processed immediately (fallback)")
                all_text.append(result.get('text', ''))
                
        except Exception as e:
            logger.error(f"Error processing part {part['part_number']} after retries: {e}")
            # Continue with other parts even if one fails
            continue
    
    # Store job information for polling
    if all_job_ids:
        redis_manager = get_redis_manager()
        jobs_key = f"doc:pdf_parts:{document_uuid}"
        redis_manager.store_dict(jobs_key, {
            'jobs': all_job_ids,
            'total_parts': len(parts),
            'status': 'processing'
        }, ttl=86400)
        
        # Schedule polling for all parts
        poll_pdf_parts.apply_async(
            args=[document_uuid, all_job_ids],
            countdown=10
        )
    
    return {
        'status': 'processing',
        'parts': len(parts),
        'job_ids': [j['job_id'] for j in all_job_ids],
        'message': f'Processing {len(parts)} PDF parts'
    }


@app.task(bind=True, base=PDFTask, queue='ocr', max_retries=30)
def poll_pdf_parts(self, document_uuid: str, job_infos: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Poll multiple Textract jobs for PDF parts and combine results.
    
    Args:
        document_uuid: UUID of the document
        job_infos: List of job information dictionaries
        
    Returns:
        Combined text from all parts
    """
    from scripts.textract_utils import TextractProcessor
    
    logger.info(f"Polling {len(job_infos)} Textract jobs for document {document_uuid}")
    
    textract_processor = TextractProcessor(self.db_manager)
    redis_manager = get_redis_manager()
    
    # Check status of all jobs
    all_completed = True
    combined_text = []
    total_pages = 0
    
    # Get source document ID
    session = next(self.db_manager.get_session())
    try:
        from sqlalchemy import text as sql_text
        query = sql_text("""
            SELECT id FROM source_documents 
            WHERE document_uuid = :doc_uuid
        """)
        result = session.execute(query, {'doc_uuid': str(document_uuid)}).fetchone()
        if not result:
            raise ValueError(f"Document {document_uuid} not found in database")
        source_doc_id = result[0]
    finally:
        session.close()
    
    # Check each job
    for job_info in sorted(job_infos, key=lambda x: x['part_number']):
        job_id = job_info['job_id']
        part_number = job_info['part_number']
        
        try:
            # Get job results
            extracted_text, metadata = textract_processor.get_text_detection_results_v2(job_id, source_doc_id)
            
            if extracted_text:
                logger.info(f"Part {part_number} completed: {len(extracted_text)} characters")
                combined_text.append(extracted_text)
                total_pages += metadata.get('pages', 0) if metadata else 0
            else:
                # Job still processing
                all_completed = False
                logger.info(f"Part {part_number} still processing")
                
        except Exception as e:
            logger.error(f"Error checking job {job_id} for part {part_number}: {e}")
            all_completed = False
    
    if all_completed:
        # All parts completed - combine text
        full_text = '\n\n'.join(combined_text)
        logger.info(f"All parts completed. Combined text length: {len(full_text)} characters")
        
        # Store in database
        session = next(self.db_manager.get_session())
        try:
            from sqlalchemy import text as sql_text
            update_query = sql_text("""
                UPDATE source_documents 
                SET raw_extracted_text = :text,
                    ocr_completed_at = NOW(),
                    ocr_provider = 'AWS Textract (Multi-part)'
                WHERE document_uuid = :doc_uuid
            """)
            session.execute(update_query, {
                'text': full_text,
                'doc_uuid': str(document_uuid)
            })
            session.commit()
            logger.info(f"Stored combined text for document {document_uuid}")
        finally:
            session.close()
        
        # Update state
        update_document_state(document_uuid, "ocr", "completed", {
            'parts_processed': len(job_infos),
            'total_pages': total_pages,
            'method': 'textract_multipart'
        })
        
        # Continue pipeline
        continue_pipeline_after_ocr.apply_async(
            args=[document_uuid, full_text]
        )
        
        # Clean up Redis key
        jobs_key = f"doc:pdf_parts:{document_uuid}"
        redis_manager.delete(jobs_key)
        
        return {
            'status': 'completed',
            'text_length': len(full_text),
            'parts': len(job_infos),
            'pages': total_pages
        }
    else:
        # Not all parts ready - retry
        if self.request.retries >= self.max_retries:
            logger.error(f"PDF parts polling exceeded maximum attempts")
            update_document_state(document_uuid, "ocr", "failed", {
                "error": "Multi-part polling timeout",
                "parts_attempted": len(job_infos)
            })
            raise RuntimeError(f"PDF parts polling timeout")
        
        # Schedule next poll
        retry_delay = min(30, 5 * (self.request.retries + 1))
        logger.info(f"Retrying parts polling in {retry_delay} seconds")
        
        self.retry(countdown=retry_delay)


# OCR Tasks
@app.task(bind=True, base=PDFTask, max_retries=3, default_retry_delay=60, queue='ocr')
@log_task_execution
@validate_task_params({'document_uuid': str, 'file_path': str})
def extract_text_from_document(self, document_uuid: str, file_path: str) -> Dict[str, Any]:
    """
    Extract text from PDF document using OCR with circuit breaker.
    
    Args:
        document_uuid: UUID of the document (as string from Celery)
        file_path: Path to the PDF file
        
    Returns:
        Dict containing extracted text and metadata
    """
    # Convert string UUID to UUID object for internal use
    from uuid import UUID as UUID_TYPE
    # Parameters are now normalized by @validate_task_params decorator
    document_uuid_obj = UUID_TYPE(document_uuid)
    
    # Check circuit breaker first (using string UUID for consistency)
    can_process, reason = circuit_breaker.can_process(document_uuid)
    if not can_process:
        logger.error(f"Circuit breaker prevented processing: {reason}")
        raise RuntimeError(f"Processing blocked: {reason}")
    
    logger.info(f"Starting OCR extraction for document {document_uuid}")
    
    # Redis Acceleration: Check cache first
    from scripts.config import REDIS_ACCELERATION_ENABLED
    if REDIS_ACCELERATION_ENABLED:
        redis_manager = get_redis_manager()
        cache_key = CacheKeys.format_key(CacheKeys.DOC_OCR_RESULT, document_uuid=document_uuid)
        
        if redis_manager.is_redis_healthy():
            cached_result = redis_manager.get_cached(cache_key)
            if cached_result:
                logger.info(f"Redis Acceleration: Using cached OCR result for {document_uuid}")
                # Chain to next stage
                continue_pipeline_after_ocr.apply_async(
                    args=[cached_result, document_uuid],
                    queue='text'
                )
                return cached_result
    
    try:
        # 1. Validate conformance before any processing
        self.validate_conformance()
        
        # 2. Validate inputs
        if not document_uuid or not file_path:
            raise ValueError("document_uuid and file_path are required")
        
        # 2.5. Add pre-processing validation
        try:
            from scripts.validation.flexible_validator import validate_before_processing
            validate_before_processing(document_uuid, file_path)
            logger.info("✅ Pre-processing validation passed")
        except ValueError as e:
            logger.error(f"❌ Pre-processing validation failed: {e}")
            update_document_state(document_uuid, "ocr", "failed", {
                "error": str(e),
                "stage": "pre_validation"
            })
            raise
        
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
        
        # 3.5. Check file size and handle large files
        file_size_mb = check_file_size(file_path)
        logger.info(f"File size for {document_uuid}: {file_size_mb:.2f} MB")
        
        if file_size_mb > 500:
            logger.warning(f"Large file detected ({file_size_mb:.2f} MB > 500 MB), using multi-part processing")
            
            # Update state to indicate large file processing
            update_document_state(document_uuid, "ocr", "processing_large_file", {
                "task_id": self.request.id,
                "file_size_mb": file_size_mb,
                "method": "multi_part_split"
            })
            
            try:
                # Split the PDF into parts
                parts = split_large_pdf(file_path, document_uuid, max_size_mb=400)
                
                # Process parts
                result = process_pdf_parts(document_uuid, parts)
                
                # Return early - polling will handle the rest
                return {
                    'status': 'processing',
                    'method': 'multi_part',
                    'parts': len(parts),
                    'file_size_mb': file_size_mb,
                    'message': f'Large file split into {len(parts)} parts for processing'
                }
                
            except Exception as e:
                logger.error(f"Failed to process large file: {e}")
                update_document_state(document_uuid, "ocr", "failed", {
                    "error": f"Large file processing failed: {str(e)}",
                    "file_size_mb": file_size_mb
                })
                raise
        
        # 4. Update processing state with validation metadata
        update_document_state(document_uuid, "ocr", "in_progress", {
            "task_id": self.request.id,
            "file_path": file_path,
            "file_size_mb": file_size_mb,
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
            
            # Record success for cached result
            circuit_breaker.record_success(document_uuid)
            
            return {
                'status': 'completed',
                'text_length': len(cached_result['text']),
                'from_cache': True
            }
        
        # Try OCR with fallback mechanism
        from scripts.textract_utils import TextractProcessor
        from scripts.db import DatabaseManager
        
        # Initialize processor and database manager
        db_manager = DatabaseManager(validate_conformance=False)
        
        # Debug region configuration
        from scripts.config import S3_BUCKET_REGION, AWS_DEFAULT_REGION
        logger.info(f"PDF Tasks - AWS_DEFAULT_REGION: {AWS_DEFAULT_REGION}, S3_BUCKET_REGION: {S3_BUCKET_REGION}")
        
        textract = TextractProcessor(db_manager)
        
        try:
            # Use fallback mechanism - tries Textract first, then Tesseract
            result = textract.extract_text_with_fallback(file_path, document_uuid)
            
            if result['status'] == 'textract_initiated':
                # Textract job started successfully
                job_id = result['job_id']
                logger.info(f"Started Textract job {job_id} for document {document_uuid}")
                
                # Update state
                update_document_state(document_uuid, "ocr", "processing", {
                    "job_id": job_id,
                    "method": "textract",
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
                    'method': 'textract',
                    'message': 'Textract job started, polling for results'
                }
                
            elif result['status'] == 'completed':
                # OCR completed immediately (Tesseract or scanned PDF sync)
                extracted_text = result['text']
                metadata = result['metadata']
                method = result.get('method', 'tesseract')
                
                logger.info(f"{method} OCR completed immediately: {len(extracted_text)} characters")
                
                # Store extracted text in database
                doc = db_manager.get_source_document(document_uuid)
                if doc:
                    session = next(db_manager.get_session())
                    try:
                        from sqlalchemy import text as sql_text
                        update_query = sql_text("""
                            UPDATE source_documents 
                            SET raw_extracted_text = :text,
                                ocr_completed_at = NOW(),
                                ocr_provider = :provider
                            WHERE document_uuid = :doc_uuid
                        """)
                        session.execute(update_query, {
                            'text': extracted_text,
                            'provider': f"{method}",
                            'doc_uuid': str(document_uuid)
                        })
                        session.commit()
                        logger.info(f"Stored {len(extracted_text)} characters via Tesseract for document {document_uuid}")
                    finally:
                        session.close()
                
                # Redis Acceleration: Cache the result
                if REDIS_ACCELERATION_ENABLED and redis_manager.is_redis_healthy():
                    cache_result = {
                        'status': 'completed',
                        'text': extracted_text,
                        'metadata': metadata,
                        'method': method
                    }
                    redis_manager.set_with_ttl(cache_key, cache_result, ttl=86400)
                    logger.info(f"Redis Acceleration: Cached OCR result for {document_uuid}")
                
                # Update state
                update_document_state(document_uuid, "ocr", "completed", {
                    "method": metadata.get('method', 'tesseract'),
                    "confidence": metadata.get('confidence', 0.8),
                    "pages": metadata.get('pages', 1),
                    "fallback_used": True
                })
                
                # Trigger the rest of the pipeline immediately
                continue_pipeline_after_ocr.apply_async(
                    args=[document_uuid, extracted_text]
                )
                
                # Record success
                circuit_breaker.record_success(document_uuid)
                
                return {
                    'status': 'completed',
                    'text_length': len(extracted_text),
                    'method': 'tesseract',
                    'confidence': metadata.get('confidence', 0.8),
                    'fallback_used': True,
                    'message': 'OCR completed via Tesseract fallback'
                }
            
            else:
                raise RuntimeError(f"Unexpected OCR result status: {result.get('status')}")
                
        except Exception as ocr_error:
            logger.error(f"All OCR methods failed for {document_uuid}: {ocr_error}")
            
            # Update state with failure
            update_document_state(document_uuid, "ocr", "failed", {
                "error": str(ocr_error),
                "textract_attempted": True,
                "tesseract_attempted": True
            })
            
            raise RuntimeError(f"All OCR methods failed: {ocr_error}")
        
    except Exception as e:
        logger.error(f"OCR extraction failed for {document_uuid}: {e}")
        # Record failure
        circuit_breaker.record_failure(document_uuid, str(e))
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
        document_uuid: UUID of the document (as string from Celery)
        text: Full text to chunk
        chunk_size: Size of each chunk
        overlap: Overlap between chunks
        
    Returns:
        List of chunk dictionaries with validated Pydantic models
    """
    # Convert string UUID to UUID object for internal use
    from uuid import UUID as UUID_TYPE
    document_uuid_obj = UUID_TYPE(document_uuid)
    
    logger.info(f"Starting text chunking for document {document_uuid}")
    
    # Redis Acceleration: Check cache first
    from scripts.config import REDIS_ACCELERATION_ENABLED
    redis_manager = get_redis_manager()
    
    if REDIS_ACCELERATION_ENABLED and redis_manager.is_redis_healthy():
        # Try to get chunks from cache
        cache_key = CacheKeys.format_key(CacheKeys.DOC_CHUNKS, document_uuid=document_uuid)
        cached_chunks = redis_manager.get_cached(cache_key)
        if cached_chunks:
            logger.info(f"Redis Acceleration: Using cached chunks for {document_uuid}")
            # Chain to next stage
            extract_entities_from_chunks.apply_async(
                args=[document_uuid, cached_chunks],
                queue='entity'
            )
            return cached_chunks
    
    # If not using text parameter directly, try to get from Redis or DB
    if not text or text == document_uuid:  # Sometimes just UUID is passed
        if REDIS_ACCELERATION_ENABLED:
            # Try Redis first, then DB
            text = redis_manager.get_with_fallback(
                CacheKeys.format_key(CacheKeys.DOC_OCR_RESULT, document_uuid=document_uuid),
                lambda: get_ocr_text_from_db(document_uuid)
            )
            if isinstance(text, dict) and 'text' in text:
                text = text['text']
        else:
            text = get_ocr_text_from_db(document_uuid)
    
    if not text:
        raise ValueError("No text available for chunking")
    
    try:
        # 1. Validate conformance
        self.validate_conformance()
        
        # 2. Validate inputs
        if not document_uuid:
            raise ValueError("document_uuid is required")
        
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
        from scripts.models import DocumentChunkMinimal
        ChunkModel = DocumentChunkMinimal
        
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
                    document_uuid=document_uuid_obj,  # Use UUID object
                    chunk_index=idx,
                    text=chunk_text,  # Changed from text_content to match database
                    char_start_index=chunk_data.get('char_start_index', 0) if isinstance(chunk_data, dict) else 0,
                    char_end_index=chunk_data.get('char_end_index', len(chunk_text)) if isinstance(chunk_data, dict) else len(chunk_text),
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
                        'char_start_index': int(chunk_model.char_start_index),  # Ensure it's an int
                        'char_end_index': int(chunk_model.char_end_index),      # Ensure it's an int
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
                            'char_start_index': int(chunk_model.char_start_index),  # Ensure int
                            'char_end_index': int(chunk_model.char_end_index),      # Ensure int
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
                'start_char': chunk_data.get('char_start_index', 0),
                'end_char': chunk_data.get('char_end_index', len(chunk_data['text']))
            })
        
        # 9. Cache the result
        if REDIS_ACCELERATION_ENABLED and redis_manager.is_redis_healthy():
            cache_key = CacheKeys.format_key(CacheKeys.DOC_CHUNKS, document_uuid=document_uuid)
            redis_manager.set_with_ttl(cache_key, serialized_chunks, ttl=86400)
            logger.info(f"Redis Acceleration: Cached {len(serialized_chunks)} chunks for {document_uuid}")
        
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
        document_uuid: UUID of the document (as string from Celery)
        chunks: List of chunk dictionaries
        
    Returns:
        Dict containing extracted entities and mentions with validated models
    """
    # Convert string UUID to UUID object for internal use
    from uuid import UUID as UUID_TYPE
    document_uuid_obj = UUID_TYPE(document_uuid)
    
    logger.info(f"Starting entity extraction for document {document_uuid}")
    
    # Redis Acceleration: Check cache first
    from scripts.config import REDIS_ACCELERATION_ENABLED
    redis_manager = get_redis_manager()
    
    if REDIS_ACCELERATION_ENABLED and redis_manager.is_redis_healthy():
        cache_key = CacheKeys.format_key(CacheKeys.DOC_ENTITY_MENTIONS, document_uuid=document_uuid)
        cached_entities = redis_manager.get_cached(cache_key)
        if cached_entities:
            logger.info(f"Redis Acceleration: Using cached entities for {document_uuid}")
            # Chain to next stage - resolution
            resolve_entities_simple.apply_async(
                args=[document_uuid],
                queue='entity'
            )
            return {
                'status': 'completed',
                'entity_count': len(cached_entities),
                'from_cache': True
            }
    
    # If chunks not provided or empty, get from Redis or DB
    if not chunks:
        if REDIS_ACCELERATION_ENABLED:
            chunks = redis_manager.get_with_fallback(
                CacheKeys.format_key(CacheKeys.DOC_CHUNKS, document_uuid=document_uuid),
                lambda: get_chunks_from_db(document_uuid)
            )
        else:
            chunks = get_chunks_from_db(document_uuid)
    
    if not chunks:
        raise ValueError("No chunks available for entity extraction")
    
    try:
        # 1. Validate conformance
        self.validate_conformance()
        
        # 2. Validate inputs
        if not document_uuid:
            raise ValueError("document_uuid is required")
        
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
                all_entity_mentions.extend(result.entities)
        
        # Save entity mentions to database
        logger.info(f"Saving {len(all_entity_mentions)} entity mentions to database")
        saved_mentions = []
        if all_entity_mentions:
            try:
                # Convert ExtractedEntity objects to EntityMentionModel objects
                entity_mention_models = []
                for entity in all_entity_mentions:
                    # Extract attributes from the ExtractedEntity object
                    mention_uuid = entity.attributes.get('mention_uuid') if entity.attributes else None
                    chunk_uuid = entity.attributes.get('chunk_uuid') if entity.attributes else None
                    document_uuid_attr = entity.attributes.get('document_uuid') if entity.attributes else document_uuid
                    
                    # Create EntityMentionModel with the correct fields
                    mention_model = EntityMentionModel(
                        mention_uuid=uuid.UUID(mention_uuid) if mention_uuid else uuid.uuid4(),
                        document_uuid=uuid.UUID(document_uuid_attr) if isinstance(document_uuid_attr, str) else document_uuid_attr,
                        chunk_uuid=uuid.UUID(chunk_uuid) if chunk_uuid else uuid.uuid4(),
                        entity_text=entity.text,
                        entity_type=entity.type,
                        confidence_score=entity.confidence,
                        start_char=entity.start_offset,
                        end_char=entity.end_offset,
                        created_at=datetime.utcnow()
                    )
                    entity_mention_models.append(mention_model)
                
                # Save to database
                saved_mentions = self.db_manager.create_entity_mentions(entity_mention_models)
                logger.info(f"Successfully saved {len(saved_mentions)} entity mentions to database")
            except Exception as e:
                logger.error(f"Failed to save entity mentions to database: {e}")
                logger.error(f"Error type: {type(e).__name__}")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")
                # Continue with pipeline even if save fails
        
        # Cache results with Redis Acceleration
        if REDIS_ACCELERATION_ENABLED and redis_manager.is_redis_healthy():
            cache_key = CacheKeys.format_key(CacheKeys.DOC_ENTITY_MENTIONS, document_uuid=document_uuid)
            mentions_data = [m.dict() for m in all_entity_mentions]
            redis_manager.set_with_ttl(cache_key, mentions_data, ttl=86400)
            logger.info(f"Redis Acceleration: Cached {len(mentions_data)} entity mentions for {document_uuid}")
        
        update_document_state(document_uuid, "entity_extraction", "completed", {
            "mention_count": len(all_entity_mentions),
            "canonical_count": 0  # Will be populated during resolution
        })
        
        # Trigger next stage - entity resolution
        entity_mentions_data = [m.dict() for m in all_entity_mentions]
        
        # Use the existing resolve_document_entities task
        resolve_document_entities.apply_async(
            args=[document_uuid, entity_mentions_data]
        )
        
        return {
            'entity_mentions': entity_mentions_data,
            'canonical_entities': []  # Will be populated during resolution
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
    
    # Redis Acceleration: Check cache first
    from scripts.config import REDIS_ACCELERATION_ENABLED
    redis_manager = get_redis_manager()
    
    if REDIS_ACCELERATION_ENABLED and redis_manager.is_redis_healthy():
        cache_key = CacheKeys.format_key(CacheKeys.DOC_CANONICAL_ENTITIES, document_uuid=document_uuid)
        cached_entities = redis_manager.get_cached(cache_key)
        if cached_entities:
            logger.info(f"Redis Acceleration: Using cached canonical entities for {document_uuid}")
            # Chain to next stage - relationship building
            build_document_relationships.apply_async(
                args=[document_uuid],
                queue='graph'
            )
            return {
                'status': 'completed',
                'canonical_count': len(cached_entities),
                'from_cache': True
            }
    
    # If entity mentions not provided, get from Redis or DB
    if not entity_mentions:
        if REDIS_ACCELERATION_ENABLED:
            entity_mentions = redis_manager.get_with_fallback(
                CacheKeys.format_key(CacheKeys.DOC_ENTITY_MENTIONS, document_uuid=document_uuid),
                lambda: get_entities_from_db(document_uuid)
            )
        else:
            entity_mentions = get_entities_from_db(document_uuid)
    
    if not entity_mentions:
        logger.warning("No entity mentions to resolve")
        return {'canonical_entities': []}
    
    update_document_state(document_uuid, "entity_resolution", "in_progress", {"task_id": self.request.id})
    
    try:
        # Inline entity resolution functions (avoiding imports from archived code)
        def create_canonical_entity_for_minimal_model(
            entity_name: str,
            entity_type: str,
            mention_uuids: List[uuid.UUID],
            aliases: List[str],
            confidence: float = 0.9
        ) -> Dict[str, Any]:
            """Create a canonical entity dictionary compatible with minimal models"""
            return {
                'canonical_entity_uuid': uuid.uuid4(),
                'canonical_name': entity_name,  # Changed from entity_name to canonical_name
                'entity_type': entity_type,
                'aliases': aliases,  # Store as JSON
                'mention_count': len(mention_uuids),
                'confidence_score': confidence,
                'resolution_method': 'fuzzy' if confidence < 0.9 else 'llm',
                'created_at': datetime.utcnow(),
                'metadata': {
                    'mention_uuids': [str(u) for u in mention_uuids],
                    'aliases': aliases,
                    'resolution_method': 'fuzzy' if confidence < 0.9 else 'llm'
                }
            }

        def is_person_variation(name1: str, name2: str) -> bool:
            """Check if two person names are variations"""
            parts1 = name1.lower().replace(',', '').split()
            parts2 = name2.lower().replace(',', '').split()
            
            if parts1 and parts2:
                last1 = parts1[0] if ',' in name1 else parts1[-1] if parts1 else ''
                last2 = parts2[0] if ',' in name2 else parts2[-1] if parts2 else ''
                
                if last1 == last2:
                    first1 = parts1[-1] if ',' in name1 else parts1[0] if parts1 else ''
                    first2 = parts2[-1] if ',' in name2 else parts2[0] if parts2 else ''
                    
                    if (first1 and first2 and 
                        (first1[0] == first2[0] or first1 == first2)):
                        return True
            return False

        def is_org_variation(org1: str, org2: str) -> bool:
            """Check if two organization names are variations"""
            abbrevs = {
                'corporation': 'corp',
                'incorporated': 'inc',
                'limited': 'ltd',
                'company': 'co',
                'international': 'intl',
                'association': 'assoc',
            }
            
            norm1 = org1.lower()
            norm2 = org2.lower()
            
            for full, abbrev in abbrevs.items():
                norm1 = norm1.replace(full, abbrev).replace(f'{abbrev}.', abbrev)
                norm2 = norm2.replace(full, abbrev).replace(f'{abbrev}.', abbrev)
            
            import string
            norm1 = ''.join(c for c in norm1 if c not in string.punctuation)
            norm2 = ''.join(c for c in norm2 if c not in string.punctuation)
            
            if norm1 == norm2:
                return True
            
            words1 = norm1.split()
            words2 = norm2.split()
            
            if len(words1) > 1 and len(words2) == 1:
                initials = ''.join(w[0] for w in words1 if w)
                if initials == words2[0]:
                    return True
            elif len(words2) > 1 and len(words1) == 1:
                initials = ''.join(w[0] for w in words2 if w)
                if initials == words1[0]:
                    return True
            
            return False

        def is_entity_variation(text1: str, text2: str, entity_type: str) -> bool:
            """Check if two entity texts are variations of each other"""
            t1_lower = text1.lower().strip()
            t2_lower = text2.lower().strip()
            
            if t1_lower == t2_lower:
                return True
            
            if t1_lower in t2_lower or t2_lower in t1_lower:
                return True
            
            if entity_type == 'PERSON':
                if is_person_variation(text1, text2):
                    return True
            elif entity_type == 'ORG':
                if is_org_variation(text1, text2):
                    return True
            elif entity_type == 'DATE':
                nums1 = ''.join(c for c in text1 if c.isdigit())
                nums2 = ''.join(c for c in text2 if c.isdigit())
                if nums1 and nums1 == nums2:
                    return True
            
            return False

        def resolve_entities_simple(
            entity_mentions: List[Any],
            document_uuid: str,
            threshold: float = 0.8
        ) -> Dict[str, Any]:
            """Simple entity resolution using fuzzy matching"""
            logger.info(f"Resolving {len(entity_mentions)} entity mentions for document {document_uuid}")
            
            # First, normalize the data structure - handle both 'text' and 'entity_text' keys
            normalized_mentions = []
            for mention in entity_mentions:
                # Handle both dict and object access patterns
                if hasattr(mention, 'get'):  # It's a dict
                    text = mention.get('entity_text') or mention.get('text')
                    entity_type = mention.get('entity_type') or mention.get('type')
                    mention_uuid = mention.get('mention_uuid') or mention.get('attributes', {}).get('mention_uuid')
                else:  # It's an object
                    text = getattr(mention, 'entity_text', None) or getattr(mention, 'text', None)
                    entity_type = getattr(mention, 'entity_type', None) or getattr(mention, 'type', None)
                    mention_uuid = getattr(mention, 'mention_uuid', None)
                
                if text and entity_type:  # Only include if we have both text and type
                    normalized_mentions.append({
                        'text': text,
                        'entity_type': entity_type,
                        'mention_uuid': mention_uuid,
                        'original': mention
                    })
                else:
                    logger.warning(f"Skipping entity with missing text or type: {mention}")
            
            logger.info(f"Normalized {len(normalized_mentions)} valid mentions from {len(entity_mentions)} total")
            
            mentions_by_type = defaultdict(list)
            for mention in normalized_mentions:
                mentions_by_type[mention['entity_type']].append(mention)
            
            canonical_entities = []
            mention_to_canonical = {}
            
            for entity_type, mentions in mentions_by_type.items():
                logger.info(f"Processing {len(mentions)} {entity_type} entities")
                
                groups = []
                processed = set()
                
                for i, mention1 in enumerate(mentions):
                    if i in processed:
                        continue
                    
                    text1 = mention1['text']
                    uuid1 = mention1['mention_uuid']
                    
                    # Skip if text is None or empty
                    if not text1:
                        logger.warning(f"Skipping entity {i} with null or empty text")
                        continue
                    
                    group = [(mention1, text1, uuid1)]
                    processed.add(i)
                    
                    for j, mention2 in enumerate(mentions[i+1:], i+1):
                        if j in processed:
                            continue
                        
                        text2 = mention2['text']
                        uuid2 = mention2['mention_uuid']
                        
                        # Skip if text is None or empty
                        if not text2:
                            logger.warning(f"Skipping entity {j} with null or empty text")
                            continue
                        
                        from difflib import SequenceMatcher
                        similarity = SequenceMatcher(None, text1.lower(), text2.lower()).ratio()
                        
                        if (similarity >= threshold or 
                            is_entity_variation(text1, text2, entity_type)):
                            group.append((mention2, text2, uuid2))
                            processed.add(j)
                    
                    groups.append(group)
                
                for group in groups:
                    canonical_name = max(group, key=lambda x: len(x[1]))[1]
                    
                    aliases = list(set(item[1] for item in group))
                    mention_uuids = [item[2] for item in group]
                    
                    mention_uuids = [
                        uuid.UUID(str(u)) if not isinstance(u, uuid.UUID) else u 
                        for u in mention_uuids
                    ]
                    
                    canonical_entity = create_canonical_entity_for_minimal_model(
                        entity_name=canonical_name,
                        entity_type=entity_type,
                        mention_uuids=mention_uuids,
                        aliases=aliases,
                        confidence=0.8 if len(group) > 1 else 1.0
                    )
                    
                    canonical_entities.append(canonical_entity)
                    
                    canonical_uuid = canonical_entity['canonical_entity_uuid']
                    for _, _, mention_uuid in group:
                        mention_to_canonical[str(mention_uuid)] = canonical_uuid
            
            logger.info(f"Created {len(canonical_entities)} canonical entities from {len(normalized_mentions)} valid mentions")
            
            return {
                'canonical_entities': canonical_entities,
                'mention_to_canonical': mention_to_canonical,
                'total_mentions': len(normalized_mentions),
                'total_canonical': len(canonical_entities),
                'deduplication_rate': 1 - (len(canonical_entities) / len(normalized_mentions)) if normalized_mentions else 0
            }

        def save_canonical_entities_to_db(
            canonical_entities: List[Dict[str, Any]], 
            document_uuid: str,
            db_manager: Any
        ) -> int:
            """Save canonical entities to database"""
            logger.info(f"Starting save_canonical_entities_to_db with {len(canonical_entities)} entities")
            
            session = next(db_manager.get_session())
            saved_count = 0
            
            try:
                for i, entity in enumerate(canonical_entities):
                    try:
                        from sqlalchemy import text as sql_text
                        insert_query = sql_text("""
                            INSERT INTO canonical_entities (
                                canonical_entity_uuid, canonical_name, entity_type,
                                mention_count, confidence_score, resolution_method,
                                aliases, metadata, created_at
                            ) VALUES (
                                :canonical_entity_uuid, :canonical_name, :entity_type,
                                :mention_count, :confidence_score, :resolution_method,
                                CAST(:aliases AS jsonb), CAST(:metadata AS jsonb), :created_at
                            )
                            ON CONFLICT (canonical_entity_uuid) DO NOTHING
                        """)
                        
                        import json
                        save_params = {
                            'canonical_entity_uuid': str(entity['canonical_entity_uuid']),
                            'canonical_name': entity['canonical_name'],
                            'entity_type': entity['entity_type'],
                            'mention_count': entity.get('mention_count', 1),
                            'confidence_score': entity.get('confidence_score', 1.0),
                            'resolution_method': entity.get('resolution_method', 'fuzzy'),
                            'aliases': json.dumps(entity.get('aliases', [])),
                            'metadata': json.dumps(entity.get('metadata', {})),
                            'created_at': entity.get('created_at', datetime.utcnow())
                        }
                        
                        result = session.execute(insert_query, save_params)
                        
                        if result.rowcount > 0:
                            saved_count += 1
                            logger.info(f"✓ Saved canonical entity {i+1}: {entity['canonical_name']}")
                            
                    except Exception as e:
                        logger.error(f"Failed to save canonical entity {i+1}: {e}")
                
                session.commit()
                logger.info(f"✓ Successfully committed {saved_count}/{len(canonical_entities)} canonical entities")
                
            except Exception as e:
                session.rollback()
                logger.error(f"Failed to save canonical entities: {e}")
                raise
            finally:
                session.close()
            
            return saved_count

        def update_entity_mentions_with_canonical(
            mention_to_canonical: Dict[str, uuid.UUID],
            document_uuid: str,
            db_manager: Any
        ) -> int:
            """Update entity mentions with their canonical entity UUIDs"""
            from sqlalchemy import text as sql_text
            
            updated_count = 0
            session = next(db_manager.get_session())
            
            try:
                for mention_uuid_str, canonical_uuid in mention_to_canonical.items():
                    try:
                        update_query = sql_text("""
                            UPDATE entity_mentions 
                            SET canonical_entity_uuid = :canonical_uuid
                            WHERE mention_uuid = :mention_uuid
                            AND document_uuid = :document_uuid
                        """)
                        
                        result = session.execute(update_query, {
                            'canonical_uuid': str(canonical_uuid),
                            'mention_uuid': str(mention_uuid_str),
                            'document_uuid': str(document_uuid)
                        })
                        
                        if result.rowcount > 0:
                            updated_count += result.rowcount
                            
                    except Exception as e:
                        logger.error(f"Failed to update mention {mention_uuid_str}: {e}")
                
                session.commit()
                logger.info(f"Updated {updated_count} entity mentions with canonical UUIDs")
                
            except Exception as e:
                session.rollback()
                logger.error(f"Failed to update entity mentions: {e}")
                raise
            finally:
                session.close()
            
            return updated_count
        
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
        
        # Update cache with resolved entities using Redis Acceleration
        if REDIS_ACCELERATION_ENABLED and redis_manager.is_redis_healthy():
            cache_key = CacheKeys.format_key(CacheKeys.DOC_CANONICAL_ENTITIES, document_uuid=document_uuid)
            redis_manager.set_with_ttl(cache_key, resolution_result['canonical_entities'], ttl=86400)
            logger.info(f"Redis Acceleration: Cached {len(resolution_result['canonical_entities'])} canonical entities for {document_uuid}")
        
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
                SELECT em.*, ce.canonical_name as canonical_name
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
    
    # Redis Acceleration: Check cache first
    from scripts.config import REDIS_ACCELERATION_ENABLED
    redis_manager = get_redis_manager()
    
    if REDIS_ACCELERATION_ENABLED and redis_manager.is_redis_healthy():
        cache_key = f"doc:relationships:{document_uuid}"  # Custom key for relationships
        cached_relationships = redis_manager.get_cached(cache_key)
        if cached_relationships:
            logger.info(f"Redis Acceleration: Using cached relationships for {document_uuid}")
            # Chain to finalization
            finalize_document_pipeline.apply_async(
                args=[document_uuid, len(chunks or []), len(canonical_entities or []), len(cached_relationships)]
            )
            return {
                'status': 'completed',
                'relationship_count': len(cached_relationships),
                'from_cache': True
            }
    
    # Get data from Redis/DB if not provided
    if not chunks and REDIS_ACCELERATION_ENABLED:
        chunks = redis_manager.get_with_fallback(
            CacheKeys.format_key(CacheKeys.DOC_CHUNKS, document_uuid=document_uuid),
            lambda: get_chunks_from_db(document_uuid)
        )
    
    if not canonical_entities and REDIS_ACCELERATION_ENABLED:
        canonical_entities = redis_manager.get_with_fallback(
            CacheKeys.format_key(CacheKeys.DOC_CANONICAL_ENTITIES, document_uuid=document_uuid),
            lambda: []  # No DB fallback for canonical entities yet
        )
    
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
            # Cache relationships with Redis Acceleration
            if REDIS_ACCELERATION_ENABLED and redis_manager.is_redis_healthy():
                cache_key = f"doc:relationships:{document_uuid}"
                relationships_data = [r.dict() for r in result.staged_relationships]
                redis_manager.set_with_ttl(cache_key, relationships_data, ttl=86400)
                logger.info(f"Redis Acceleration: Cached {len(relationships_data)} relationships for {document_uuid}")
            
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
        from scripts.textract_utils import TextractProcessor
        from scripts.cache import get_redis_manager
        
        # Get source document ID from database
        session = next(self.db_manager.get_session())
        try:
            from sqlalchemy import text as sql_text
            query = sql_text("""
                SELECT id FROM source_documents 
                WHERE document_uuid = :doc_uuid
            """)
            result = session.execute(query, {'doc_uuid': str(document_uuid)}).fetchone()
            if not result:
                raise ValueError(f"Document {document_uuid} not found in database")
            source_doc_id = result[0]
        finally:
            session.close()
        
        # Initialize TextractProcessor
        textract_processor = TextractProcessor(self.db_manager)
        
        # Get job results using new LazyDocument method
        extracted_text, metadata = textract_processor.get_text_detection_results_v2(job_id, source_doc_id)
        
        # Check if job completed (extracted_text is not None, even if empty)
        if extracted_text is not None:
            logger.info(f"Textract job {job_id} succeeded, got {len(extracted_text)} characters")
            
            # Cache results
            textract_processor._cache_ocr_result(document_uuid, extracted_text, metadata)
            
            # Redis Acceleration: Cache the result
            from scripts.config import REDIS_ACCELERATION_ENABLED
            if REDIS_ACCELERATION_ENABLED:
                redis_manager = get_redis_manager()
                cache_key = CacheKeys.format_key(CacheKeys.DOC_OCR_RESULT, document_uuid=document_uuid)
                
                if redis_manager.is_redis_healthy():
                    cache_result = {
                        'status': 'completed',
                        'text': extracted_text,
                        'metadata': metadata,
                        'method': 'textract'
                    }
                    redis_manager.set_with_ttl(cache_key, cache_result, ttl=86400)
                    logger.info(f"Redis Acceleration: Cached OCR result for {document_uuid}")
            
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
                    'text': extracted_text,
                    'doc_uuid': str(document_uuid)
                })
                session.commit()
                logger.info(f"Stored {len(extracted_text)} characters in database for document {document_uuid}")
            finally:
                session.close()
            
            # Update state
            update_document_state(document_uuid, "ocr", "completed", {
                "job_id": job_id,
                "page_count": metadata.get('pages', 0) if metadata else 0,
                "confidence": metadata.get('confidence', 0.0) if metadata else 0.0,
                "method": "AWS Textract (Textractor v2)"
            })
            
            # Trigger the rest of the pipeline
            continue_pipeline_after_ocr.apply_async(
                args=[document_uuid, extracted_text]
            )
            
            return {
                'status': 'completed',
                'text_length': len(extracted_text),
                'pages': metadata.get('pages', 0) if metadata else 0,
                'confidence': metadata.get('confidence', 0.0) if metadata else 0.0,
                'method': 'textractor_v2'
            }
            
        else:
            # Job still in progress - schedule next poll
            logger.info(f"Textract job {job_id} still in progress, scheduling next poll")
            
            # Check if we've exceeded maximum retries or timeout
            if self.request.retries >= self.max_retries:
                logger.error(f"Textract job {job_id} exceeded maximum polling attempts")
                update_document_state(document_uuid, "ocr", "failed", {
                    "error": "Polling timeout",
                    "job_id": job_id
                })
                raise RuntimeError(f"Textract job {job_id} polling timeout")
            
            # Schedule next poll with exponential backoff
            retry_delay = min(30, 5 * (self.request.retries + 1))  # 5s, 10s, 15s, 20s, 25s, 30s max
            logger.info(f"Retrying Textract polling in {retry_delay} seconds (attempt {self.request.retries + 1})")
            
            self.retry(countdown=retry_delay)
            
            # This return should not be reached due to retry
            return {
                'status': 'polling',
                'retry_attempt': self.request.retries + 1,
                'next_poll_in': retry_delay
            }
            
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
            CacheKeys.format_key(CacheKeys.DOC_STATE, document_uuid=document_uuid),
            CacheKeys.format_key(CacheKeys.DOC_OCR_RESULT, document_uuid=document_uuid),
            CacheKeys.format_key(CacheKeys.DOC_CHUNKS, document_uuid=document_uuid),
            CacheKeys.format_key(CacheKeys.DOC_ENTITY_MENTIONS, document_uuid=document_uuid),
            CacheKeys.format_key(CacheKeys.DOC_CANONICAL_ENTITIES, document_uuid=document_uuid),
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


# Parallel Processing Enhancement
@app.task(bind=True, base=PDFTask, queue='default', max_retries=3)
@log_task_execution
def process_pdf_batch(self, document_paths: List[Dict[str, Any]], max_workers: int = 5) -> Dict[str, Any]:
    """
    Process multiple PDFs concurrently for improved throughput.
    
    Args:
        document_paths: List of dicts with document_uuid, file_path, project_uuid
        max_workers: Maximum number of concurrent workers (default: 5)
        
    Returns:
        Dict containing batch processing results
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import threading
    
    logger.info(f"Starting batch processing of {len(document_paths)} documents with {max_workers} workers")
    
    # Update state for batch
    batch_id = str(uuid.uuid4())
    redis_manager = get_redis_manager()
    batch_key = f"batch:processing:{batch_id}"
    
    redis_manager.store_dict(batch_key, {
        'total_documents': len(document_paths),
        'max_workers': max_workers,
        'started_at': datetime.utcnow().isoformat(),
        'status': 'processing'
    }, ttl=86400)
    
    results = {
        'batch_id': batch_id,
        'total': len(document_paths),
        'successful': 0,
        'failed': 0,
        'results': {}
    }
    
    # Thread-safe counter
    counter_lock = threading.Lock()
    processed_count = 0
    
    def process_single_document_wrapper(doc_info: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        """Wrapper to process a single document and return results."""
        nonlocal processed_count
        
        document_uuid = doc_info['document_uuid']
        file_path = doc_info['file_path']
        project_uuid = doc_info['project_uuid']
        document_metadata = doc_info.get('metadata', {})
        
        try:
            # Start processing using existing task
            result = process_pdf_document.apply_async(
                args=[document_uuid, file_path, project_uuid, document_metadata]
            )
            
            # Wait for initial task to complete (OCR initiation)
            task_result = result.get(timeout=60)
            
            with counter_lock:
                processed_count += 1
                logger.info(f"Batch progress: {processed_count}/{len(document_paths)} documents initiated")
            
            return document_uuid, {
                'status': 'success',
                'task_id': result.id,
                'result': task_result
            }
            
        except Exception as e:
            logger.error(f"Failed to process document {document_uuid}: {e}")
            
            with counter_lock:
                processed_count += 1
            
            return document_uuid, {
                'status': 'failed',
                'error': str(e)
            }
    
    # Process documents in parallel
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all documents
        future_to_doc = {
            executor.submit(process_single_document_wrapper, doc): doc
            for doc in document_paths
        }
        
        # Process completions
        for future in as_completed(future_to_doc):
            doc_info = future_to_doc[future]
            
            try:
                document_uuid, result = future.result()
                results['results'][document_uuid] = result
                
                if result['status'] == 'success':
                    results['successful'] += 1
                else:
                    results['failed'] += 1
                    
                # Update batch progress in Redis
                redis_manager.store_dict(batch_key, {
                    'total_documents': len(document_paths),
                    'processed': processed_count,
                    'successful': results['successful'],
                    'failed': results['failed'],
                    'status': 'processing',
                    'updated_at': datetime.utcnow().isoformat()
                }, ttl=86400)
                
            except Exception as e:
                logger.error(f"Error processing future result: {e}")
                results['failed'] += 1
    
    # Calculate statistics
    end_time = datetime.utcnow()
    start_time = datetime.fromisoformat(redis_manager.get_dict(batch_key)['started_at'])
    duration_seconds = (end_time - start_time).total_seconds()
    
    # Final statistics
    final_stats = {
        'batch_id': batch_id,
        'total_documents': len(document_paths),
        'successful': results['successful'],
        'failed': results['failed'],
        'duration_seconds': duration_seconds,
        'documents_per_hour': (len(document_paths) / duration_seconds) * 3600 if duration_seconds > 0 else 0,
        'average_time_per_doc': duration_seconds / len(document_paths) if document_paths else 0,
        'status': 'completed',
        'completed_at': end_time.isoformat()
    }
    
    # Update final batch status
    redis_manager.store_dict(batch_key, final_stats, ttl=86400)
    
    logger.info(f"Batch processing completed: {results['successful']} successful, {results['failed']} failed")
    logger.info(f"Throughput: {final_stats['documents_per_hour']:.1f} documents/hour")
    
    return {
        **final_stats,
        'results': results['results']
    }


def create_document_batches(documents: List[Dict[str, Any]], batch_size: int = 10) -> List[List[Dict[str, Any]]]:
    """
    Create optimal batches from a list of documents.
    
    Args:
        documents: List of document information
        batch_size: Maximum documents per batch
        
    Returns:
        List of document batches
    """
    batches = []
    for i in range(0, len(documents), batch_size):
        batch = documents[i:i + batch_size]
        batches.append(batch)
    
    logger.info(f"Created {len(batches)} batches from {len(documents)} documents (batch size: {batch_size})")
    return batches


@app.task(bind=True, base=PDFTask, queue='default')
def process_document_manifest(self, manifest: Dict[str, Any], batch_size: int = 10, max_workers: int = 5) -> Dict[str, Any]:
    """
    Process a manifest of documents in optimized batches.
    
    Args:
        manifest: Document manifest with list of documents
        batch_size: Documents per batch
        max_workers: Concurrent workers per batch
        
    Returns:
        Combined results from all batches
    """
    documents = manifest.get('documents', [])
    logger.info(f"Processing manifest with {len(documents)} documents")
    
    # Create batches
    batches = create_document_batches(documents, batch_size)
    
    # Process each batch
    all_results = {
        'manifest_id': manifest.get('id', 'unknown'),
        'total_documents': len(documents),
        'total_batches': len(batches),
        'batch_results': []
    }
    
    for i, batch in enumerate(batches):
        logger.info(f"Processing batch {i+1}/{len(batches)} with {len(batch)} documents")
        
        # Process batch with parallel workers
        batch_result = process_pdf_batch.apply_async(
            args=[batch, max_workers]
        ).get()
        
        all_results['batch_results'].append(batch_result)
    
    # Aggregate statistics
    total_successful = sum(r['successful'] for r in all_results['batch_results'])
    total_failed = sum(r['failed'] for r in all_results['batch_results'])
    
    all_results['summary'] = {
        'total_successful': total_successful,
        'total_failed': total_failed,
        'success_rate': total_successful / len(documents) if documents else 0,
        'batches_completed': len(batches)
    }
    
    logger.info(f"Manifest processing complete: {total_successful}/{len(documents)} successful")
    
    return all_results


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