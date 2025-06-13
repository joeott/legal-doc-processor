"""
PDF-Only OCR Tasks for Celery-based Document Processing Pipeline
Simplified to only handle PDF documents.
"""
from celery import Task
from scripts.celery_app import app
from scripts.ocr_extraction import extract_text_from_pdf
from scripts.database import SupabaseManager
from scripts.cache import get_redis_manager, CacheKeys
from scripts.celery_tasks.task_utils import update_document_state
from scripts.core.pdf_models import PDFDocumentModel, ProcessingStatus

import logging
import os
from datetime import datetime
from typing import Optional, Dict, Any
from pathlib import Path

logger = logging.getLogger(__name__)


def resolve_file_path(file_path: str) -> tuple[bool, Optional[str]]:
    """
    Resolve file path for PDF files.
    
    Args:
        file_path: The file path to resolve
        
    Returns:
        Tuple of (success, resolved_path)
    """
    # If it's already an S3 or HTTP URL, return as-is
    if file_path.startswith(('s3://', 'http://', 'https://')):
        return True, file_path
    
    # Check if it's a local file
    if os.path.exists(file_path):
        # Verify it's a PDF
        if not file_path.lower().endswith('.pdf'):
            logger.error(f"Not a PDF file: {file_path}")
            return False, None
        return True, file_path
    
    # Try relative to project root
    project_root = Path(__file__).parent.parent.parent
    full_path = project_root / file_path
    if full_path.exists() and str(full_path).lower().endswith('.pdf'):
        return True, str(full_path)
    
    logger.error(f"PDF file not found: {file_path}")
    return False, None


@app.task(bind=True, name='ocr.process_pdf', max_retries=3)
class ProcessPDFTask(Task):
    """Simplified PDF-only OCR task."""
    
    def run(self, document_id: int, file_path: str, document_uuid: str) -> Dict[str, Any]:
        """
        Process a PDF document through OCR.
        
        Args:
            document_id: Database ID of the document
            file_path: Path to the PDF file (local or S3)
            document_uuid: UUID of the document
            
        Returns:
            Dict with processing results
        """
        logger.info(f"Starting PDF OCR task for document {document_uuid}")
        
        db_manager = SupabaseManager()
        redis_manager = get_redis_manager()
        
        try:
            # Resolve file path
            success, resolved_path = resolve_file_path(file_path)
            if not success:
                raise ValueError(f"Could not resolve PDF path: {file_path}")
            
            # Validate it's a PDF
            if not resolved_path.lower().endswith('.pdf') and not resolved_path.startswith('s3://'):
                raise ValueError(f"Only PDF files are supported, got: {resolved_path}")
            
            # Load or create document model
            doc_data = db_manager.get_document_by_id(document_id)
            if not doc_data:
                raise ValueError(f"Document {document_id} not found in database")
            
            # Create PDF document model
            doc = PDFDocumentModel(
                document_uuid=document_uuid,
                original_filename=doc_data.get('original_file_name', 'unknown.pdf'),
                file_size_bytes=doc_data.get('file_size', 0),
                file_hash=doc_data.get('md5_hash', '0' * 64),
                s3_key=doc_data.get('s3_key', ''),
                processing_status=ProcessingStatus.OCR_PROCESSING
            )
            
            # Update state
            update_document_state(
                self.request.id,
                db_manager,
                redis_manager,
                document_id,
                'ocr_processing',
                {'started_at': datetime.utcnow().isoformat()}
            )
            
            # Extract text
            result = extract_text_from_pdf(
                resolved_path,
                doc,
                db_manager,
                document_id
            )
            
            # Cache result
            cache_key = CacheKeys.ocr_result(document_uuid)
            redis_manager.set_cached(cache_key, result, ttl=86400)  # 24 hours
            
            # Update database
            db_manager.update_document_ocr_result(
                document_id,
                result['text'],
                result['metadata']
            )
            
            # Update state to completed
            update_document_state(
                self.request.id,
                db_manager,
                redis_manager,
                document_id,
                'text_extraction',
                {
                    'completed_at': datetime.utcnow().isoformat(),
                    'page_count': result.get('page_count', 0),
                    'confidence': result.get('confidence', 0)
                }
            )
            
            logger.info(f"✅ PDF OCR completed for document {document_uuid}")
            
            return {
                'status': 'success',
                'document_id': document_id,
                'document_uuid': document_uuid,
                'text_length': len(result.get('text', '')),
                'page_count': result.get('page_count', 0),
                'confidence': result.get('confidence', 0)
            }
            
        except Exception as e:
            logger.error(f"PDF OCR task failed: {str(e)}", exc_info=True)
            
            # Update state to failed
            update_document_state(
                self.request.id,
                db_manager,
                redis_manager,
                document_id,
                'ocr_failed',
                {
                    'error': str(e),
                    'failed_at': datetime.utcnow().isoformat()
                }
            )
            
            # Re-raise for Celery retry
            raise self.retry(exc=e, countdown=60 * (self.request.retries + 1))


# Register task
process_pdf_task = ProcessPDFTask()


# Helper function for backwards compatibility
def submit_pdf_for_ocr(document_id: int, file_path: str, document_uuid: str) -> str:
    """
    Submit a PDF document for OCR processing.
    
    Args:
        document_id: Database ID
        file_path: Path to PDF
        document_uuid: Document UUID
        
    Returns:
        Celery task ID
    """
    if not file_path.lower().endswith('.pdf'):
        raise ValueError(f"Only PDF files are supported, got: {file_path}")
    
    task = process_pdf_task.delay(document_id, file_path, document_uuid)
    logger.info(f"Submitted PDF OCR task {task.id} for document {document_uuid}")
    
    return task.id