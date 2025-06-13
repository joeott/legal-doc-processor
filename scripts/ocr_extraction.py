"""
PDF-only OCR extraction module.
Simplified from multi-format to PDF-only processing.
"""
import os
import logging
import time
import hashlib
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple, List

from scripts.config import (
    S3_PRIMARY_DOCUMENT_BUCKET,
    TEXTRACT_USE_ASYNC_FOR_PDF,
    TEXTRACT_CONFIDENCE_THRESHOLD,
    AWS_DEFAULT_REGION
)
from scripts.db import DatabaseManager
from scripts.textract_utils import TextractProcessor
from scripts.s3_storage import S3StorageManager
from scripts.models import ProcessingStatus
# PDFDocumentModel not in consolidated models - will use dict
# Conformance validators not available, using try/except for now

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)  # Enable debug logging for OCR operations


def extract_text_from_pdf(
    pdf_path: str,
    document: Dict[str, Any],
    db_manager: DatabaseManager,
    source_doc_sql_id: int
) -> Dict[str, Any]:
    """
    Extract text from PDF using AWS Textract with full validation.
    
    Args:
        pdf_path: Path to PDF file or S3 URI
        document: Validated PDFDocumentModel
        db_manager: Database manager with conformance validation
        source_doc_sql_id: SQL ID for database updates
        
    Returns:
        Extraction results with text and metadata
        
    Raises:
        ConformanceError: If schema validation fails
        ValueError: If inputs are invalid
        FileNotFoundError: If PDF file not found
    """
    logger.info(f"Starting PDF text extraction for document {document.document_uuid}")
    logger.debug(f"PDF path: {pdf_path}")
    logger.debug(f"Document type: {document.detected_type if hasattr(document, 'detected_type') else 'unknown'}")
    
    try:
        # 1. Validate conformance before processing
        validate_before_operation("OCR text extraction")
        
        # 2. Validate inputs
        if not pdf_path:
            raise ValueError("pdf_path is required")
        
        if not document or not document.document_uuid:
            raise ValueError("Valid document model is required")
        
        if not isinstance(db_manager, DatabaseManager):
            raise ValueError("Valid DatabaseManager instance required")
        
        # 3. Validate document model using Pydantic
        document.model_validate(document.model_dump())
        
        # 4. Ensure database manager has validated conformance
        db_manager.validate_conformance()
        # Transition to OCR processing
        document.transition_to(ProcessingStatus.OCR_PROCESSING)
        
        # Check cache first
        textract_processor = TextractProcessor(db_manager=db_manager)
        cached_result = textract_processor.get_cached_ocr_result(str(document.document_uuid))
        if cached_result:
            text, metadata = cached_result
            logger.info(f"Using cached OCR result for document {document.document_uuid}")
            
            # Update document model
            document.extracted_text = text
            document.ocr_confidence_score = metadata.get('avg_confidence', 0.95)
            document.page_count = metadata.get('page_count', 1)
            document.extracted_metadata = metadata
            
            # Transition to next state
            document.transition_to(ProcessingStatus.TEXT_EXTRACTION)
            
            return {
                'text': text,
                'metadata': metadata,
                'confidence': document.ocr_confidence_score,
                'page_count': document.page_count
            }
        
        # 5. Process with Textract
        result = _process_with_textract(
            pdf_path, 
            document, 
            db_manager, 
            source_doc_sql_id,
            textract_processor
        )
        
        # 6. Validate OCR result before updating model
        if not result or 'text' not in result:
            raise ValueError("Invalid OCR result: missing text")
        
        if not result['text'].strip():
            raise ValueError("OCR result contains no text content")
        
        # 7. Validate confidence score
        confidence = result.get('confidence', 0.0)
        if confidence < TEXTRACT_CONFIDENCE_THRESHOLD:
            logger.warning(f"Low OCR confidence: {confidence} < {TEXTRACT_CONFIDENCE_THRESHOLD}")
        
        # 8. Update document model with validation
        document.extracted_text = result['text']
        document.ocr_confidence_score = confidence
        document.page_count = result.get('page_count', 1)
        document.extracted_metadata = result.get('metadata', {})
        
        # 9. Validate updated model
        document.model_validate(document.model_dump())
        
        # 10. Transition to next state
        document.transition_to(ProcessingStatus.TEXT_EXTRACTION)
        
        # 11. Return validated result
        return {
            'text': document.extracted_text,
            'metadata': document.extracted_metadata,
            'confidence': document.ocr_confidence_score,
            'page_count': document.page_count,
            'validation_passed': True
        }
        
    except ConformanceError as e:
        logger.error(f"OCR extraction failed due to conformance error: {e}")
        document.transition_to(ProcessingStatus.FAILED, f"Conformance validation failed: {str(e)}")
        raise
    except ValueError as e:
        logger.error(f"OCR extraction failed due to validation error: {e}")
        document.transition_to(ProcessingStatus.FAILED, f"Input validation failed: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"OCR extraction failed: {e}")
        document.transition_to(ProcessingStatus.FAILED, str(e))
        raise


def _process_with_textract(
    pdf_path: str,
    document: Dict[str, Any],
    db_manager: DatabaseManager,
    source_doc_sql_id: int,
    textract_processor: TextractProcessor
) -> Dict[str, Any]:
    """
    Process PDF with AWS Textract.
    """
    s3_manager = S3StorageManager()
    s3_bucket_name = S3_PRIMARY_DOCUMENT_BUCKET
    s3_object_key = None
    
    # Handle different input types
    if pdf_path.startswith('s3://'):
        # Already in S3
        parts = pdf_path.replace('s3://', '').split('/', 1)
        if len(parts) == 2:
            s3_bucket_name = parts[0]
            s3_object_key = parts[1]
            logger.info(f"Processing existing S3 object: s3://{s3_bucket_name}/{s3_object_key}")
        else:
            raise ValueError(f"Invalid S3 URI format: {pdf_path}")
    
    elif os.path.exists(pdf_path):
        # Local file - upload to S3
        logger.info(f"Uploading local file to S3: {pdf_path}")
        
        # Validate PDF before upload
        is_valid, validation_error, validation_metadata = validate_pdf_for_processing(pdf_path)
        if not is_valid:
            raise ValueError(f"PDF validation failed: {validation_error}")
        
        # Update document with validation metadata
        document.page_count = validation_metadata.get('page_count')
        document.file_size_bytes = validation_metadata.get('file_size_bytes')
        
        # Upload to S3
        upload_info = s3_manager.upload_document_with_uuid_naming(
            local_file_path=pdf_path,
            document_uuid=str(document.document_uuid),
            original_filename=document.original_file_name
        )
        s3_object_key = upload_info['s3_key']
        s3_bucket_name = upload_info['s3_bucket']
        document.s3_key = s3_object_key
        
        # Update database with S3 location
        db_manager.client.table('source_documents').update({
            's3_key': s3_object_key,
            's3_bucket': s3_bucket_name,
            's3_region': AWS_DEFAULT_REGION
        }).eq('id', source_doc_sql_id).execute()
    
    else:
        raise FileNotFoundError(f"File not found: {pdf_path}")
    
    # Start Textract processing
    start_time = time.time()
    
    if TEXTRACT_USE_ASYNC_FOR_PDF:
        logger.info(f"Using async Textract for s3://{s3_bucket_name}/{s3_object_key}")
        
        # Start async job
        job_id = textract_processor.start_document_text_detection(
            s3_bucket=s3_bucket_name,
            s3_key=s3_object_key,
            source_doc_id=source_doc_sql_id,
            document_uuid_from_db=str(document.document_uuid)
        )
        
        if not job_id:
            raise RuntimeError("Failed to start Textract job")
        
        # Wait for results
        blocks, textract_metadata = textract_processor.get_text_detection_results(
            job_id, 
            source_doc_sql_id
        )
        
        if not blocks:
            raise RuntimeError(f"No text extracted from Textract job {job_id}")
        
        # Process blocks to text
        extracted_text = textract_processor.process_textract_blocks_to_text(
            blocks, 
            textract_metadata
        )
    else:
        raise NotImplementedError("Synchronous PDF processing not supported. Set TEXTRACT_USE_ASYNC_FOR_PDF=true")
    
    processing_time = time.time() - start_time
    
    # Calculate average confidence
    confidence_scores = [
        block.get('Confidence', 100) / 100.0
        for block in blocks
        if block.get('BlockType') in ['WORD', 'LINE']
    ]
    avg_confidence = sum(confidence_scores) / len(confidence_scores) if confidence_scores else 0.95
    
    # Build metadata
    metadata = {
        'processing_time_seconds': processing_time,
        'textract_job_id': job_id if 'job_id' in locals() else None,
        'page_count': textract_metadata.get('Pages', 1),
        'avg_confidence': avg_confidence,
        'confidence_threshold': TEXTRACT_CONFIDENCE_THRESHOLD,
        'blocks_extracted': len(blocks),
        'method': 'AWS Textract'
    }
    
    # Cache the result
    try:
        textract_processor._cache_ocr_result(
            str(document.document_uuid),
            extracted_text,
            metadata
        )
    except Exception as e:
        logger.warning(f"Failed to cache OCR result: {e}")
    
    return {
        'text': extracted_text,
        'metadata': metadata,
        'confidence': avg_confidence,
        'page_count': metadata['page_count']
    }


def validate_pdf_for_processing(file_path: str) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Pre-flight validation for PDF files before processing.
    
    Args:
        file_path: Path to the PDF file to validate
        
    Returns:
        tuple: (is_valid, error_message, metadata)
    """
    metadata = {}
    
    try:
        # Check if file exists
        if not os.path.exists(file_path):
            return False, f"File not found: {file_path}", metadata
        
        # Check extension
        if not file_path.lower().endswith('.pdf'):
            return False, "File is not a PDF", metadata
        
        # Get file size
        file_size = os.path.getsize(file_path)
        metadata['file_size_bytes'] = file_size
        metadata['file_size_mb'] = file_size / (1024 * 1024)
        
        # Check file size limits (100MB max for Textract)
        if file_size > 100 * 1024 * 1024:
            return False, f"File too large: {metadata['file_size_mb']:.2f}MB (max 100MB)", metadata
        
        if file_size == 0:
            return False, "File is empty (0 bytes)", metadata
        
        # Validate PDF format
        with open(file_path, 'rb') as pdf_file:
            # Check PDF header
            header = pdf_file.read(5)
            if header != b'%PDF-':
                return False, "Invalid PDF header - file may be corrupted", metadata
        
        # Get page count using PyMuPDF
        try:
            import fitz  # PyMuPDF
            pdf_doc = fitz.open(file_path)
            page_count = len(pdf_doc)
            metadata['page_count'] = page_count
            
            # Check if encrypted
            if pdf_doc.is_encrypted:
                pdf_doc.close()
                return False, "PDF is encrypted and cannot be processed", metadata
            
            pdf_doc.close()
            
            # Check page limits
            if page_count > 3000:
                return False, f"Too many pages: {page_count} (max 3000)", metadata
            if page_count == 0:
                return False, "PDF has no pages", metadata
                
        except Exception as e:
            return False, f"Could not read PDF structure: {str(e)}", metadata
        
        # Calculate file hash
        try:
            hasher = hashlib.sha256()
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hasher.update(chunk)
            metadata['file_hash'] = hasher.hexdigest()
        except Exception as e:
            logger.warning(f"Could not calculate file hash: {e}")
            metadata['file_hash'] = "0" * 64
        
        # All validations passed
        metadata['validation_status'] = 'passed'
        metadata['is_valid'] = True
        return True, "", metadata
        
    except Exception as e:
        logger.error(f"Error during PDF validation: {e}", exc_info=True)
        return False, f"Validation error: {str(e)}", metadata