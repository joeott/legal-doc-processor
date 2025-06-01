"""Utility functions for submitting documents to Celery"""
from typing import Dict, Optional, Tuple
import logging
from scripts.celery_tasks.ocr_tasks import process_ocr
from scripts.supabase_utils import SupabaseManager
from scripts.ocr_extraction import detect_file_category

logger = logging.getLogger(__name__)

def submit_document_to_celery(
    document_id: int,
    document_uuid: str,
    file_path: str,
    file_type: str,
    file_name: str,
    project_sql_id: int
) -> Tuple[str, bool]:
    """
    Submit a document to appropriate Celery task based on file type.
    
    Detects file category and routes to:
    - Image processing (o4-mini vision) for image files
    - Traditional OCR processing for documents and other files
    
    Args:
        document_id: SQL ID of the source document
        document_uuid: UUID of the document  
        file_path: S3 path to the file
        file_type: File extension/MIME type
        file_name: Original filename
        project_sql_id: SQL ID of the project
    
    Returns:
        Tuple of (celery_task_id, success)
    """
    try:
        # Determine file category
        file_category = detect_file_category(file_name)
        
        # Normalize file type
        normalized_file_type = f".{file_type}" if not file_type.startswith('.') else file_type
        
        # Set appropriate initial status based on file category
        if file_category == 'image':
            initial_status = 'image_queued'
            logger.info(f"Submitting image file {file_name} to vision processing")
        else:
            initial_status = 'ocr_queued'
            logger.info(f"Submitting {file_category} file {file_name} to traditional OCR")
        
        # Submit to Celery (process_ocr will handle routing internally)
        task = process_ocr.delay(
            document_uuid=document_uuid,
            source_doc_sql_id=document_id,
            file_path=file_path,
            file_name=file_name,
            detected_file_type=normalized_file_type,
            project_sql_id=project_sql_id
        )
        
        # Update source_documents with Celery task ID and file category
        db = SupabaseManager()
        db.client.table('source_documents').update({
            'celery_task_id': task.id,
            'celery_status': initial_status,
            'initial_processing_status': initial_status,
            'file_category': file_category  # Store detected category
        }).eq('id', document_id).execute()
        
        logger.info(f"Document {document_uuid} ({file_category}) submitted to Celery: {task.id}")
        return task.id, True
        
    except Exception as e:
        logger.error(f"Failed to submit document to Celery: {e}", exc_info=True)
        return None, False