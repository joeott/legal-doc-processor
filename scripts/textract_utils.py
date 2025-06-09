# textract_utils.py
import boto3
import logging
import time
import uuid
import hashlib
import os
import tempfile
import io
from datetime import datetime
from typing import List, Dict, Optional, Tuple, Any
from collections import defaultdict
from botocore.exceptions import ClientError

# Textractor integration
from textractor import Textractor
from textractor.data.constants import TextractAPI
from textractor.entities.lazy_document import LazyDocument
from textractor.exceptions import (
    InputError,
    IncorrectMethodException,
    MissingDependencyException,
    UnhandledCaseException,
)

from scripts.db import DatabaseManager
from scripts.config import (
    AWS_DEFAULT_REGION, S3_BUCKET_REGION, TEXTRACT_ASYNC_MAX_POLLING_TIME_SECONDS, TEXTRACT_ASYNC_POLLING_INTERVAL_SECONDS,
    TEXTRACT_ASYNC_INITIAL_DELAY_SECONDS, TEXTRACT_SNS_TOPIC_ARN, TEXTRACT_SNS_ROLE_ARN,
    TEXTRACT_OUTPUT_S3_BUCKET, TEXTRACT_OUTPUT_S3_PREFIX, TEXTRACT_KMS_KEY_ID,
    TEXTRACT_CONFIDENCE_THRESHOLD, TEXTRACT_MAX_RESULTS_PER_PAGE, TEXTRACT_FEATURE_TYPES,
    REDIS_OCR_CACHE_TTL, PDF_CONVERSION_DPI, PDF_CONVERSION_FORMAT, 
    ENABLE_SCANNED_PDF_DETECTION, PDF_PAGE_PROCESSING_PARALLEL, SCANNED_PDF_IMAGE_PREFIX
)
from scripts.cache import get_redis_manager, redis_cache

logger = logging.getLogger(__name__)

# CloudWatch logging integration
_cloudwatch_logger = None

def get_cloudwatch_logger():
    """Get CloudWatch logger instance."""
    global _cloudwatch_logger
    if _cloudwatch_logger is None:
        try:
            from scripts.cloudwatch_logger import get_cloudwatch_logger as get_cw_logger
            _cloudwatch_logger = get_cw_logger()
        except Exception as e:
            logger.warning(f"Could not initialize CloudWatch logger: {e}")
    return _cloudwatch_logger


class TextractProcessor:
    def __init__(self, db_manager: DatabaseManager, region_name: str = None):
        """Initialize TextractProcessor with validated region."""
        
        # Import config to get validated region
        from scripts.config import VALIDATED_REGION, S3_PRIMARY_DOCUMENT_BUCKET
        
        # Use validated region
        if region_name is None:
            region_name = VALIDATED_REGION
            logger.info(f"Using validated region: {region_name}")
        
        # Verify S3 access before initializing
        try:
            s3_test = boto3.client('s3', region_name=region_name)
            s3_test.head_bucket(Bucket=S3_PRIMARY_DOCUMENT_BUCKET)
            logger.info(f"✅ Verified S3 access to {S3_PRIMARY_DOCUMENT_BUCKET} from region {region_name}")
        except Exception as e:
            logger.error(f"❌ Cannot access S3 bucket from region {region_name}: {e}")
            raise
        
        # Initialize clients
        self.client = boto3.client('textract', region_name=region_name)
        self.textractor = Textractor(region_name=region_name)
        self.s3_client = s3_test  # Reuse verified client
        self.db_manager = db_manager
        self.region_name = region_name
        
        logger.info(f"TextractProcessor initialized for region: {region_name}")

    def _is_scanned_pdf(self, s3_bucket: str, s3_key: str) -> bool:
        """
        Detect if a PDF is scanned (image-only) by analyzing its content.
        Returns True if the PDF appears to be scanned/image-only.
        """
        # PRODUCTION DIRECTIVE: Force async processing for all PDFs
        # All documents are text-based, not scanned images
        return False
        
        if not ENABLE_SCANNED_PDF_DETECTION:
            return False
            
        try:
            # Quick check using detect_document_text on the PDF directly
            logger.info(f"Checking if PDF is scanned: s3://{s3_bucket}/{s3_key}")
            
            response = self.client.detect_document_text(
                Document={'S3Object': {'Bucket': s3_bucket, 'Name': s3_key}}
            )
            
            blocks = response.get('Blocks', [])
            
            # Count text-bearing blocks
            text_blocks = [b for b in blocks if b.get('BlockType') in ['LINE', 'WORD']]
            
            # If we have very few or no text blocks, it's likely a scanned PDF
            is_scanned = len(text_blocks) < 5  # Threshold for minimal text
            
            logger.info(f"PDF scan detection: {len(text_blocks)} text blocks found. Is scanned: {is_scanned}")
            return is_scanned
            
        except Exception as e:
            logger.warning(f"Error detecting if PDF is scanned: {e}. Assuming it might be scanned.")
            return True  # Assume scanned on error to trigger conversion

    def _convert_pdf_to_images_s3(self, s3_bucket: str, s3_key: str, document_uuid: str) -> List[Dict[str, str]]:
        """
        Convert a PDF in S3 to images and upload them back to S3.
        Returns a list of dicts with 'key' and 'page_num' for each converted image.
        """
        import tempfile
        from pdf2image import convert_from_path
        import io
        
        logger.info(f"Converting PDF to images: s3://{s3_bucket}/{s3_key}")
        
        converted_images = []
        temp_pdf_path = None
        
        try:
            # Download PDF to temporary file
            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_file:
                self.s3_client.download_file(s3_bucket, s3_key, tmp_file.name)
                temp_pdf_path = tmp_file.name
                logger.info(f"Downloaded PDF to temporary file: {temp_pdf_path}")
            
            # Convert PDF to images
            images = convert_from_path(temp_pdf_path, dpi=PDF_CONVERSION_DPI)
            logger.info(f"Converted PDF to {len(images)} images at {PDF_CONVERSION_DPI} DPI")
            
            # Upload each image to S3
            base_key = s3_key.rsplit('.', 1)[0]  # Remove .pdf extension
            
            for page_num, image in enumerate(images, 1):
                # Convert PIL image to bytes
                img_byte_arr = io.BytesIO()
                image.save(img_byte_arr, format=PDF_CONVERSION_FORMAT)
                img_byte_arr = img_byte_arr.getvalue()
                
                # Create S3 key for the image
                image_key = f"{SCANNED_PDF_IMAGE_PREFIX}{base_key}/page_{page_num:03d}.{PDF_CONVERSION_FORMAT.lower()}"
                
                # Upload to S3
                self.s3_client.put_object(
                    Bucket=s3_bucket,
                    Key=image_key,
                    Body=img_byte_arr,
                    ContentType=f'image/{PDF_CONVERSION_FORMAT.lower()}'
                )
                
                logger.info(f"Uploaded page {page_num} to s3://{s3_bucket}/{image_key}")
                
                converted_images.append({
                    'key': image_key,
                    'page_num': page_num,
                    'bucket': s3_bucket
                })
            
            return converted_images
            
        except Exception as e:
            logger.error(f"Error converting PDF to images: {e}")
            raise
        finally:
            # Clean up temporary file
            if temp_pdf_path and os.path.exists(temp_pdf_path):
                try:
                    os.unlink(temp_pdf_path)
                except:
                    pass

    def _process_scanned_pdf_pages(self, s3_bucket: str, image_keys: List[Dict[str, str]], 
                                   source_doc_id: int, document_uuid: str) -> Tuple[str, Dict[str, Any]]:
        """
        Process converted PDF pages with Textract and combine results.
        Returns combined text and metadata.
        """
        logger.info(f"Processing {len(image_keys)} converted PDF pages with Textract")
        
        all_text_parts = []
        total_confidence = 0.0
        total_words = 0
        total_lines = 0
        
        for image_info in image_keys:
            try:
                page_num = image_info['page_num']
                image_key = image_info['key']
                
                logger.info(f"Processing page {page_num}: {image_key}")
                
                # Use detect_document_text for each image
                response = self.client.detect_document_text(
                    Document={'S3Object': {'Bucket': s3_bucket, 'Name': image_key}}
                )
                
                blocks = response.get('Blocks', [])
                
                # Extract text from blocks
                page_lines = []
                page_confidence_sum = 0.0
                page_confidence_count = 0
                
                for block in blocks:
                    if block.get('BlockType') == 'LINE':
                        text = block.get('Text', '')
                        confidence = block.get('Confidence', 0)
                        
                        if text and confidence >= TEXTRACT_CONFIDENCE_THRESHOLD:
                            page_lines.append(text)
                            page_confidence_sum += confidence
                            page_confidence_count += 1
                    elif block.get('BlockType') == 'WORD':
                        total_words += 1
                
                # Combine page text
                page_text = '\n'.join(page_lines)
                if page_text:
                    all_text_parts.append(f"=== Page {page_num} ===\n{page_text}")
                    total_lines += len(page_lines)
                    
                    if page_confidence_count > 0:
                        page_avg_confidence = page_confidence_sum / page_confidence_count
                        total_confidence += page_avg_confidence
                
                logger.info(f"Page {page_num}: {len(page_lines)} lines, {len(page_text)} characters")
                
            except Exception as e:
                logger.error(f"Error processing page {page_num}: {e}")
                # Continue with other pages
        
        # Combine all pages
        combined_text = '\n\n'.join(all_text_parts)
        avg_confidence = (total_confidence / len(image_keys)) if image_keys else 0.0
        
        metadata = {
            'method': 'textract_scanned_pdf',
            'pages': len(image_keys),
            'confidence': avg_confidence,
            'word_count': total_words,
            'line_count': total_lines,
            'converted_from_pdf': True,
            'dpi': PDF_CONVERSION_DPI
        }
        
        logger.info(f"Scanned PDF processing complete: {len(combined_text)} total characters, {avg_confidence:.2f} avg confidence")
        
        return combined_text, metadata

    def process_scanned_pdf_sync(self, s3_bucket: str, s3_key: str, 
                                 source_doc_id: int, document_uuid: str) -> Dict[str, Any]:
        """
        Process a scanned PDF synchronously by converting to images and extracting text.
        Returns a result dict similar to OCR completion.
        """
        try:
            # Convert PDF to images
            image_keys = self._convert_pdf_to_images_s3(s3_bucket, s3_key, document_uuid)
            
            # Process all pages with Textract
            extracted_text, metadata = self._process_scanned_pdf_pages(
                s3_bucket, image_keys, source_doc_id, document_uuid
            )
            
            # Save to database
            self._save_extracted_text_to_db(source_doc_id, extracted_text, metadata)
            
            # Cache the result
            self._cache_ocr_result(document_uuid, extracted_text, metadata)
            
            return {
                'status': 'completed',
                'text': extracted_text,
                'metadata': metadata,
                'method': 'textract_scanned_pdf_sync'
            }
            
        except Exception as e:
            logger.error(f"Error processing scanned PDF: {e}")
            raise

    def _save_extracted_text_to_db(self, source_doc_id: int, text: str, metadata: Dict[str, Any]):
        """Save extracted text to database."""
        try:
            from sqlalchemy import text as sql_text
            from scripts.rds_utils import DBSessionLocal
            
            session = DBSessionLocal()
            try:
                update_query = sql_text("""
                    UPDATE source_documents 
                    SET raw_extracted_text = :text,
                        ocr_completed_at = :completed_at,
                        ocr_provider = :provider,
                        textract_page_count = :page_count,
                        ocr_confidence_score = :confidence
                    WHERE id = :doc_id
                """)
                
                result = session.execute(update_query, {
                    'text': text,
                    'completed_at': datetime.now(),
                    'provider': 'AWS Textract (Scanned PDF)',
                    'page_count': metadata.get('pages', 1),
                    'confidence': metadata.get('confidence', 0.0),
                    'doc_id': source_doc_id
                })
                
                session.commit()
                logger.info(f"✓ Successfully saved {len(text)} characters to database for document {source_doc_id}")
                
            except Exception as db_error:
                session.rollback()
                logger.error(f"Failed to save extracted text to database: {db_error}")
                raise
            finally:
                session.close()
                
        except Exception as e:
            logger.error(f"Critical error saving text to database: {e}")
            raise

    def start_document_text_detection_v2(self, s3_bucket: str, s3_key: str,
                                        source_doc_id: int, document_uuid_from_db: str,
                                        client_request_token: Optional[str] = None,
                                        job_tag: Optional[str] = None) -> Optional[str]:
        """Start async Textract job using Textractor library for enhanced reliability."""
        try:
            # Check if this is a scanned PDF
            if s3_key.lower().endswith('.pdf') and self._is_scanned_pdf(s3_bucket, s3_key):
                logger.info(f"Detected scanned PDF, processing synchronously: s3://{s3_bucket}/{s3_key}")
                
                # Process synchronously and return None to indicate sync completion
                result = self.process_scanned_pdf_sync(s3_bucket, s3_key, source_doc_id, document_uuid_from_db)
                
                # Return a special job_id to indicate sync processing
                return f"SYNC_COMPLETE_{document_uuid_from_db}"
            
            # Regular async processing for text-based PDFs
            s3_path = f"s3://{s3_bucket}/{s3_key}"
            logger.info(f"Starting Textract job using Textractor for s3://{s3_bucket}/{s3_key}")
            
            # Log to CloudWatch
            cw_logger = get_cloudwatch_logger()
            if cw_logger:
                cw_logger.log_api_call(
                    api_method="start_document_text_detection_v2",
                    request_params={"s3_path": s3_path, "source_doc_id": source_doc_id}
                )
            
            # Use Textractor for async document text detection
            lazy_document = self.textractor.start_document_text_detection(
                file_source=s3_path,
                client_request_token=client_request_token or f"textract-{document_uuid_from_db}",
                job_tag=job_tag or f"legal-doc-{source_doc_id}",
                save_image=False  # We don't need images for text extraction
            )
            
            job_id = lazy_document.job_id
            
            if job_id:
                logger.info(f"Textract job started via Textractor. JobId: {job_id} for s3://{s3_bucket}/{s3_key}")
                
                # Log successful job start to CloudWatch
                if cw_logger:
                    cw_logger.log_textract_event(
                        event_type="job_started",
                        document_uuid=document_uuid_from_db,
                        job_id=job_id,
                        metadata={
                            "s3_bucket": s3_bucket,
                            "s3_key": s3_key,
                            "source_doc_id": source_doc_id,
                            "method": "textractor_v2"
                        }
                    )
                
                # Convert string UUID to UUID object for DB operation
                from uuid import UUID as UUID_TYPE
                doc_uuid_obj = UUID_TYPE(document_uuid_from_db)
                
                # Create entry in textract_jobs table
                self.db_manager.create_textract_job_entry(
                    source_document_id=source_doc_id,
                    document_uuid=doc_uuid_obj,
                    job_id=job_id,
                    s3_input_bucket=s3_bucket,
                    s3_input_key=s3_key,
                    job_type='DetectDocumentText',
                    s3_output_bucket=None,  # Textractor handles output internally
                    s3_output_key=None,
                    client_request_token=client_request_token or f"textract-{document_uuid_from_db}",
                    job_tag=job_tag,
                    sns_topic_arn=None
                )
                
                # Update source_documents table with initial job info
                self.db_manager.update_source_document_with_textract_outcome(
                    source_doc_sql_id=source_doc_id,
                    textract_job_id=job_id,
                    textract_job_status='submitted',
                    job_started_at=datetime.now()
                )
                
                # Store LazyDocument reference for polling
                self._cache_lazy_document(job_id, lazy_document)
                
            return job_id
            
        except InvalidS3ObjectException as e:
            error_msg = f"Invalid S3 object or region mismatch: {str(e)}"
            logger.error(f"Textractor S3 error for s3://{s3_bucket}/{s3_key}: {error_msg}")
            self._handle_textract_error(source_doc_id, document_uuid_from_db, error_msg, "InvalidS3ObjectException")
            raise
            
        except UnsupportedDocumentException as e:
            error_msg = f"Unsupported document format: {str(e)}"
            logger.error(f"Textractor document error for s3://{s3_bucket}/{s3_key}: {error_msg}")
            self._handle_textract_error(source_doc_id, document_uuid_from_db, error_msg, "UnsupportedDocumentException")
            raise
            
        except Exception as e:
            error_msg = f"Textractor error: {str(e)}"
            logger.error(f"Textractor general error for s3://{s3_bucket}/{s3_key}: {error_msg}")
            self._handle_textract_error(source_doc_id, document_uuid_from_db, error_msg, "GeneralException")
            raise

    def _cache_lazy_document(self, job_id: str, lazy_document: LazyDocument, ttl: int = 3600):
        """Cache LazyDocument for later polling."""
        try:
            redis_mgr = get_redis_manager()
            if redis_mgr.is_available():
                cache_key = f"textract:lazy_doc:{job_id}"
                # Store job_id and metadata instead of the object itself
                lazy_doc_data = {
                    'job_id': job_id,
                    'api_type': str(lazy_document.api),
                    'created_at': datetime.now().isoformat()
                }
                redis_mgr.set_cached(cache_key, lazy_doc_data, ttl)
                logger.debug(f"Cached LazyDocument metadata for {job_id}")
        except Exception as e:
            logger.debug(f"Error caching LazyDocument: {e}")

    def _get_cached_lazy_document(self, job_id: str) -> Optional[LazyDocument]:
        """Retrieve LazyDocument from cache or recreate it."""
        try:
            redis_mgr = get_redis_manager()
            if redis_mgr.is_available():
                cache_key = f"textract:lazy_doc:{job_id}"
                cached_data = redis_mgr.get_cached(cache_key)
                if cached_data:
                    # Recreate LazyDocument from cached metadata
                    return LazyDocument(
                        job_id,
                        TextractAPI.DETECT_TEXT,
                        textract_client=self.textractor.textract_client,
                        s3_client=self.textractor.s3_client
                    )
        except Exception as e:
            logger.debug(f"Error retrieving cached LazyDocument: {e}")
        
        # Fallback: create new LazyDocument
        return LazyDocument(
            job_id,
            TextractAPI.DETECT_TEXT,
            textract_client=self.textractor.textract_client,
            s3_client=self.textractor.s3_client
        )

    def _handle_textract_error(self, source_doc_id: int, document_uuid: str, error_msg: str, error_type: str):
        """Handle Textract errors with proper logging and database updates."""
        # Log error to CloudWatch
        cw_logger = get_cloudwatch_logger()
        if cw_logger:
            cw_logger.log_textract_event(
                event_type="job_start_failed",
                document_uuid=document_uuid,
                error=error_msg,
                metadata={"error_type": error_type}
            )
        
        # Update source_documents with failure
        if self.db_manager:
            self.db_manager.update_source_document_with_textract_outcome(
                source_doc_sql_id=source_doc_id,
                textract_job_id="N/A_START_FAILURE",
                textract_job_status='failed'
            )

    def extract_text_from_textract_document(self, document) -> str:
        """Extract text using Textractor's built-in methods with fallbacks."""
        try:
            # Primary text extraction
            text = document.text
            
            # Fallback to lines if text is empty
            if not text.strip():
                text = '\n'.join([line.text for line in document.lines])
            
            # Final fallback to words
            if not text.strip():
                text = ' '.join([word.text for word in document.words])
            
            logger.info(f"Extracted {len(text)} characters from Textract document")
            return text
            
        except Exception as e:
            logger.error(f"Text extraction failed: {e}")
            return ""

    def _extract_text_from_blocks(self, blocks: List[Dict[str, Any]]) -> str:
        """Extract text from Textract blocks."""
        lines = []
        current_page = 1
        
        for block in blocks:
            if block.get('BlockType') == 'LINE':
                # Check if we've moved to a new page
                if block.get('Page', 1) > current_page:
                    lines.append('\n\n')  # Add page break
                    current_page = block.get('Page', 1)
                
                text = block.get('Text', '')
                if text:
                    lines.append(text)
        
        return '\n'.join(lines)
    
    def _calculate_confidence_from_blocks(self, blocks: List[Dict[str, Any]]) -> float:
        """Calculate average confidence from Textract blocks."""
        confidences = []
        
        for block in blocks:
            if block.get('BlockType') in ['WORD', 'LINE'] and 'Confidence' in block:
                confidences.append(block['Confidence'])
        
        if confidences:
            return sum(confidences) / len(confidences)
        return 0.0
    
    def calculate_ocr_confidence(self, document) -> float:
        """Calculate average confidence from Textract results."""
        try:
            confidences = []
            for word in document.words:
                if hasattr(word, 'confidence') and word.confidence:
                    confidences.append(word.confidence)
            
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
            logger.info(f"Calculated OCR confidence: {avg_confidence:.2f} from {len(confidences)} words")
            return avg_confidence
            
        except Exception as e:
            logger.error(f"Confidence calculation failed: {e}")
            return 0.0

    def extract_text_with_fallback(self, file_path: str, document_uuid: str) -> Dict[str, Any]:
        """Try Textract first, fallback to Tesseract on failure."""
        logger.info(f"Starting OCR with fallback for {file_path}")
        
        try:
            # Try Textract first if file is on S3
            if file_path.startswith('s3://'):
                # Parse S3 path
                s3_parts = file_path.replace('s3://', '').split('/', 1)
                if len(s3_parts) == 2:
                    s3_bucket, s3_key = s3_parts
                    
                    # Get document info from database
                    doc = self.db_manager.get_source_document(document_uuid)
                    if doc:
                        job_id = self.start_document_text_detection_v2(
                            s3_bucket=s3_bucket,
                            s3_key=s3_key,
                            source_doc_id=doc.id,
                            document_uuid_from_db=document_uuid
                        )
                        
                        # Check for synchronous completion (scanned PDF)
                        if job_id and job_id.startswith('SYNC_COMPLETE_'):
                            logger.info(f"Scanned PDF processed synchronously: {document_uuid}")
                            
                            # Get the cached result
                            cached_result = self.get_cached_ocr_result(document_uuid)
                            if cached_result:
                                text, metadata = cached_result
                                return {
                                    'status': 'completed',
                                    'text': text,
                                    'metadata': metadata,
                                    'method': 'textract_scanned_pdf_sync'
                                }
                            else:
                                # Fallback if cache miss - should not happen
                                logger.warning("Cache miss for synchronously processed scanned PDF")
                                return {
                                    'status': 'textract_initiated',
                                    'job_id': job_id,
                                    'method': 'textract'
                                }
                        
                        if job_id:
                            logger.info(f"Textract job started successfully: {job_id}")
                            return {
                                'status': 'textract_initiated',
                                'job_id': job_id,
                                'method': 'textract'
                            }
            
            # PRODUCTION DIRECTIVE: Only S3 files are supported
            logger.error(f"Textract requires S3 files. Local file not supported: {file_path}")
            raise RuntimeError(f"Only S3 documents are supported for OCR processing")
            
        except Exception as textract_error:
            # PRODUCTION DIRECTIVE: No fallback to Tesseract
            # All documents must use Textract async processing only
            logger.error(f"Textract failed for {file_path}: {textract_error}")
            raise RuntimeError(f"Textract processing failed: {textract_error}")

    # Add safety constants
    MAX_TESSERACT_FILE_SIZE_MB = 50
    MAX_TESSERACT_PAGE_COUNT = 20

    def check_tesseract_eligibility(self, file_path: str) -> Tuple[bool, str]:
        """Check if file is safe for Tesseract processing"""
        try:
            # Check file size
            if file_path.startswith('s3://'):
                import boto3
                from urllib.parse import urlparse
                parsed = urlparse(file_path)
                s3 = boto3.client('s3', region_name=self.region_name)
                response = s3.head_object(Bucket=parsed.netloc, Key=parsed.path.lstrip('/'))
                size_mb = response['ContentLength'] / (1024 * 1024)
            else:
                size_mb = os.path.getsize(file_path) / (1024 * 1024)
            
            if size_mb > self.MAX_TESSERACT_FILE_SIZE_MB:
                return False, f"File too large for Tesseract: {size_mb:.1f}MB > {self.MAX_TESSERACT_FILE_SIZE_MB}MB"
            
            # Check page count for PDFs
            if file_path.lower().endswith('.pdf'):
                import fitz
                if file_path.startswith('s3://'):
                    # Download to temp file for page count
                    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
                        from urllib.parse import urlparse
                        parsed = urlparse(file_path)
                        s3 = boto3.client('s3', region_name=self.region_name)
                        s3.download_file(parsed.netloc, parsed.path.lstrip('/'), tmp.name)
                        doc = fitz.open(tmp.name)
                        page_count = doc.page_count
                        doc.close()
                        os.unlink(tmp.name)
                else:
                    doc = fitz.open(file_path)
                    page_count = doc.page_count
                    doc.close()
                
                if page_count > self.MAX_TESSERACT_PAGE_COUNT:
                    return False, f"Too many pages for Tesseract: {page_count} > {self.MAX_TESSERACT_PAGE_COUNT}"
            
            return True, "OK"
        except Exception as e:
            return False, f"Error checking file: {str(e)}"

    def extract_with_tesseract(self, file_path: str, document_uuid: str) -> Dict[str, Any]:
        """Extract text using Tesseract OCR as fallback with safety checks."""
        
        # Safety check first
        eligible, reason = self.check_tesseract_eligibility(file_path)
        if not eligible:
            logger.error(f"File not eligible for Tesseract: {reason}")
            raise RuntimeError(f"Tesseract fallback rejected: {reason}")
        
        import pytesseract
        from pdf2image import convert_from_path
        from PIL import Image
        import tempfile
        import os
        
        logger.info(f"Starting Tesseract OCR for {file_path} (passed safety checks)")
        
        try:
            # Handle S3 files by downloading first
            local_file_path = file_path
            temp_file = None
            
            if file_path.startswith('s3://'):
                # Download S3 file to temporary location
                s3_parts = file_path.replace('s3://', '').split('/', 1)
                if len(s3_parts) == 2:
                    s3_bucket, s3_key = s3_parts
                    
                    # Download file
                    import boto3
                    s3_client = boto3.client('s3', region_name=self.region_name)
                    
                    # Create temporary file
                    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(s3_key)[1])
                    s3_client.download_file(s3_bucket, s3_key, temp_file.name)
                    local_file_path = temp_file.name
                    temp_file.close()
                    
                    logger.info(f"Downloaded S3 file to {local_file_path}")
            
            # Extract text based on file type
            if local_file_path.lower().endswith('.pdf'):
                # Convert PDF to images
                logger.info("Converting PDF to images for Tesseract")
                images = convert_from_path(local_file_path, dpi=200)  # Higher DPI for better OCR
                
                text_parts = []
                for i, image in enumerate(images):
                    logger.debug(f"Processing PDF page {i+1}")
                    page_text = pytesseract.image_to_string(image, config='--psm 1 --oem 3')
                    text_parts.append(page_text)
                
                extracted_text = '\n\n'.join(text_parts)
                pages = len(images)
                
            else:
                # Handle image files directly
                logger.info("Processing image file with Tesseract")
                image = Image.open(local_file_path)
                extracted_text = pytesseract.image_to_string(image, config='--psm 1 --oem 3')
                pages = 1
            
            # Clean up temporary file
            if temp_file and os.path.exists(temp_file.name):
                os.unlink(temp_file.name)
            
            # Create metadata
            metadata = {
                'method': 'tesseract',
                'confidence': 0.8,  # Default confidence for Tesseract
                'pages': pages,
                'word_count': len(extracted_text.split()) if extracted_text else 0,
                'line_count': len(extracted_text.splitlines()) if extracted_text else 0
            }
            
            logger.info(f"Tesseract OCR completed: {len(extracted_text)} characters, {pages} pages")
            
            # Cache the result
            self._cache_ocr_result(document_uuid, extracted_text, metadata)
            
            return {
                'status': 'completed',
                'text': extracted_text,
                'metadata': metadata,
                'method': 'tesseract'
            }
            
        except Exception as e:
            logger.error(f"Tesseract OCR failed for {file_path}: {e}")
            
            # Clean up temporary file on error
            if temp_file and os.path.exists(temp_file.name):
                try:
                    os.unlink(temp_file.name)
                except:
                    pass
            
            raise RuntimeError(f"Tesseract OCR failed: {e}")

    def start_document_text_detection(self, s3_bucket: str, s3_key: str,
                                    source_doc_id: int, document_uuid_from_db: str,
                                    client_request_token: Optional[str] = None,
                                    job_tag: Optional[str] = None) -> Optional[str]:
        """Start async Textract job for document text detection."""
        try:
            params = {
                'DocumentLocation': {'S3Object': {'Bucket': s3_bucket, 'Name': s3_key}}
            }
            # Use a deterministic client request token if none provided, based on document_uuid
            params['ClientRequestToken'] = client_request_token or f"textract-{document_uuid_from_db}"
            if job_tag:
                params['JobTag'] = job_tag
            if TEXTRACT_SNS_TOPIC_ARN and TEXTRACT_SNS_ROLE_ARN:
                params['NotificationChannel'] = {'SNSTopicArn': TEXTRACT_SNS_TOPIC_ARN, 'RoleArn': TEXTRACT_SNS_ROLE_ARN}
            if TEXTRACT_OUTPUT_S3_BUCKET and TEXTRACT_OUTPUT_S3_PREFIX:
                params['OutputConfig'] = {'S3Bucket': TEXTRACT_OUTPUT_S3_BUCKET, 'S3Prefix': TEXTRACT_OUTPUT_S3_PREFIX.rstrip('/') + '/'}
            if TEXTRACT_KMS_KEY_ID:
                params['KMSKeyId'] = TEXTRACT_KMS_KEY_ID

            logger.info(f"Starting Textract job for s3://{s3_bucket}/{s3_key} with params: {params}")
            
            # Log to CloudWatch
            cw_logger = get_cloudwatch_logger()
            if cw_logger:
                cw_logger.log_api_call(
                    api_method="start_document_text_detection",
                    request_params=params
                )
            
            response = self.client.start_document_text_detection(**params)
            job_id = response.get('JobId')

            if job_id:
                logger.info(f"Textract job started. JobId: {job_id} for s3://{s3_bucket}/{s3_key}")
                
                # Log successful job start to CloudWatch
                if cw_logger:
                    cw_logger.log_textract_event(
                        event_type="job_started",
                        document_uuid=document_uuid_from_db,
                        job_id=job_id,
                        metadata={
                            "s3_bucket": s3_bucket,
                            "s3_key": s3_key,
                            "source_doc_id": source_doc_id
                        }
                    )
                # Create entry in textract_jobs table
                textract_output_key_val = f"{TEXTRACT_OUTPUT_S3_PREFIX.rstrip('/')}/{job_id}/1" if params.get('OutputConfig') else None

                self.db_manager.create_textract_job_entry(
                    source_document_id=source_doc_id,
                    document_uuid=document_uuid_from_db,
                    job_id=job_id,
                    s3_input_bucket=s3_bucket,
                    s3_input_key=s3_key,
                    job_type='DetectDocumentText',
                    s3_output_bucket=params.get('OutputConfig', {}).get('S3Bucket'),
                    s3_output_key=textract_output_key_val,
                    client_request_token=params['ClientRequestToken'],
                    job_tag=job_tag,
                    sns_topic_arn=params.get('NotificationChannel', {}).get('SNSTopicArn')
                )
                # Update source_documents table with initial job info
                self.db_manager.update_source_document_with_textract_outcome(
                    source_doc_sql_id=source_doc_id,
                    textract_job_id=job_id,
                    textract_job_status='submitted',
                    job_started_at=datetime.now()
                )
            return job_id
        except ClientError as e:
            error_msg = e.response['Error']['Message']
            logger.error(f"Error starting Textract job for s3://{s3_bucket}/{s3_key}: {error_msg}")
            
            # Log error to CloudWatch
            cw_logger = get_cloudwatch_logger()
            if cw_logger:
                cw_logger.log_textract_event(
                    event_type="job_start_failed",
                    document_uuid=document_uuid_from_db,
                    error=error_msg,
                    metadata={
                        "s3_bucket": s3_bucket,
                        "s3_key": s3_key,
                        "error_code": e.response['Error']['Code']
                    }
                )
            
            # Update source_documents with failure
            if self.db_manager:
                self.db_manager.update_source_document_with_textract_outcome(
                    source_doc_sql_id=source_doc_id,
                    textract_job_id="N/A_START_FAILURE",
                    textract_job_status='failed'
                )
            raise

    def _check_job_status_cache(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Check Redis cache for Textract job status."""
        try:
            redis_mgr = get_redis_manager()
            if redis_mgr.is_available():
                cache_key = f"textract:job_status:{job_id}"
                cached_status = redis_mgr.get_cached(cache_key)
                if cached_status:
                    logger.debug(f"Textract job status cache hit for {job_id}")
                    return cached_status
        except Exception as e:
            logger.debug(f"Error checking Textract job cache: {e}")
        return None

    def _cache_job_status(self, job_id: str, status: Dict[str, Any], ttl: int = 60):
        """Cache Textract job status in Redis."""
        try:
            redis_mgr = get_redis_manager()
            if redis_mgr.is_available():
                cache_key = f"textract:job_status:{job_id}"
                redis_mgr.set_cached(cache_key, status, ttl)
                logger.debug(f"Cached Textract job status for {job_id}")
        except Exception as e:
            logger.debug(f"Error caching Textract job status: {e}")

    def get_text_detection_results_v2(self, job_id: str, source_doc_id: int) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        """Check Textract job status using LazyDocument and return results if ready."""
        logger.info(f"Checking Textract job status using LazyDocument. JobId: {job_id}, SourceDocId: {source_doc_id}")
        
        try:
            # Check job status using AWS API directly
            response = self.client.get_document_text_detection(JobId=job_id, MaxResults=1)
            job_status = response.get('JobStatus', 'UNKNOWN')
            
            # Check if job is ready (non-blocking)
            if job_status == 'SUCCEEDED':
                logger.info(f"Textract job {job_id} is ready, retrieving results")
                
                # Get all pages of results
                all_blocks = []
                next_token = None
                
                while True:
                    if next_token:
                        response = self.client.get_document_text_detection(JobId=job_id, NextToken=next_token)
                    else:
                        response = self.client.get_document_text_detection(JobId=job_id)
                    
                    blocks = response.get('Blocks', [])
                    all_blocks.extend(blocks)
                    
                    next_token = response.get('NextToken')
                    if not next_token:
                        break
                
                # Extract text from blocks
                extracted_text = self._extract_text_from_blocks(all_blocks)
                
                # Calculate confidence from blocks
                confidence = self._calculate_confidence_from_blocks(all_blocks)
                
                # Create metadata
                metadata = {
                    'confidence': confidence,
                    'pages': response.get('DocumentMetadata', {}).get('Pages', 1),
                    'word_count': sum(1 for block in all_blocks if block.get('BlockType') == 'WORD'),
                    'line_count': sum(1 for block in all_blocks if block.get('BlockType') == 'LINE'),
                    'method': 'textract_direct'
                }
                
                # Update database
                self.db_manager.update_textract_job_status(
                    job_id, 
                    'SUCCEEDED', 
                    avg_confidence=confidence,
                    pages_processed=metadata['pages']
                )
                
                self.db_manager.update_source_document_with_textract_outcome(
                    source_doc_sql_id=source_doc_id,
                    textract_job_id=job_id,
                    textract_job_status='completed',
                    job_completed_at=datetime.now()
                )
                
                # CRITICAL: Save extracted text to database
                logger.info(f"Saving extracted text to database for document {source_doc_id}")
                try:
                    from sqlalchemy import text as sql_text
                    from scripts.rds_utils import DBSessionLocal
                    
                    session = DBSessionLocal()
                    try:
                        update_query = sql_text("""
                            UPDATE source_documents 
                            SET raw_extracted_text = :text,
                                ocr_completed_at = :completed_at,
                                ocr_provider = :provider,
                                textract_page_count = :page_count,
                                ocr_confidence_score = :confidence
                            WHERE id = :doc_id
                        """)
                        
                        result = session.execute(update_query, {
                            'text': extracted_text,
                            'completed_at': datetime.now(),
                            'provider': 'AWS Textract',
                            'page_count': metadata['pages'],
                            'confidence': confidence,
                            'doc_id': source_doc_id
                        })
                        
                        session.commit()
                        logger.info(f"✓ Successfully saved {len(extracted_text)} characters to database for document {source_doc_id}")
                        
                    except Exception as db_error:
                        session.rollback()
                        logger.error(f"Failed to save extracted text to database: {db_error}")
                        raise
                    finally:
                        session.close()
                        
                except Exception as e:
                    logger.error(f"Critical error saving text to database: {e}")
                    # Don't fail the whole process, but log the error
                
                # Cache the result
                self._cache_ocr_result(f"doc_uuid_from_job_{job_id}", extracted_text, metadata)
                
                logger.info(f"Successfully processed Textract job {job_id}: {len(extracted_text)} chars, {confidence:.2f} confidence")
                return extracted_text, metadata
                
            elif job_status == 'IN_PROGRESS':
                # Job still in progress
                logger.debug(f"Textract job {job_id} still in progress")
                return None, None
            elif job_status == 'FAILED':
                # Job failed
                error_msg = response.get('StatusMessage', 'Unknown error')
                logger.error(f"Textract job {job_id} failed: {error_msg}")
                self.db_manager.update_textract_job_status(job_id, 'FAILED', error_message=error_msg)
                raise Exception(f"Textract job failed: {error_msg}")
            else:
                # Unknown status
                logger.warning(f"Textract job {job_id} has unknown status: {job_status}")
                return None, None
                
        except Exception as e:
            logger.error(f"Error checking Textract job {job_id}: {e}")
            
            # Update database with error
            self.db_manager.update_textract_job_status(job_id, 'FAILED', error_message=str(e))
            self.db_manager.update_source_document_with_textract_outcome(
                source_doc_sql_id=source_doc_id,
                textract_job_id=job_id,
                textract_job_status='failed'
            )
            
            raise

    def get_text_detection_results(self, job_id: str, source_doc_id: int) -> Tuple[Optional[List[Dict[str, Any]]], Optional[Dict[str, Any]]]:
        """Poll for Textract job results and update database."""
        logger.info(f"Polling for Textract job results. JobId: {job_id}, SourceDocId: {source_doc_id}")
        start_time = time.time()
        job_entry = self.db_manager.get_textract_job_by_job_id(job_id)
        # Handle both datetime objects and strings
        started_at = job_entry.get('started_at') if job_entry else None
        if isinstance(started_at, datetime):
            initial_db_start_time = started_at
        elif isinstance(started_at, str):
            initial_db_start_time = datetime.fromisoformat(started_at)
        else:
            initial_db_start_time = datetime.now()

        time.sleep(TEXTRACT_ASYNC_INITIAL_DELAY_SECONDS)

        while True:
            elapsed_time = time.time() - start_time
            if elapsed_time > TEXTRACT_ASYNC_MAX_POLLING_TIME_SECONDS:
                logger.error(f"Textract job {job_id} timed out after {elapsed_time:.2f} seconds.")
                self.db_manager.update_textract_job_status(job_id, 'FAILED', error_message='Polling Timeout')
                self.db_manager.update_source_document_with_textract_outcome(
                    source_doc_sql_id=source_doc_id, 
                    textract_job_id=job_id, 
                    textract_job_status='failed'
                )
                return None, None

            try:
                # Check cache first
                cached_status = self._check_job_status_cache(job_id)
                if cached_status and cached_status.get('JobStatus') in ['SUCCEEDED', 'FAILED', 'PARTIAL_SUCCESS']:
                    response = cached_status
                    job_status_api = response.get('JobStatus')
                    logger.info(f"Using cached Textract job status for {job_id}: {job_status_api}")
                else:
                    response = self.client.get_document_text_detection(JobId=job_id, MaxResults=TEXTRACT_MAX_RESULTS_PER_PAGE)
                    job_status_api = response.get('JobStatus')  # SUCCEEDED, FAILED, IN_PROGRESS, PARTIAL_SUCCESS
                    logger.debug(f"Textract job {job_id} API status: {job_status_api}. Elapsed time: {elapsed_time:.2f}s")
                    
                    # Cache the status for completed jobs
                    if job_status_api in ['SUCCEEDED', 'FAILED', 'PARTIAL_SUCCESS']:
                        self._cache_job_status(job_id, response, ttl=3600)  # Cache for 1 hour
                    else:
                        self._cache_job_status(job_id, {'JobStatus': job_status_api}, ttl=30)  # Cache in-progress for 30 seconds

                # Map API status to DB enum values
                db_job_status = 'in_progress'
                if job_status_api == 'IN_PROGRESS':
                    db_job_status = 'in_progress'
                elif job_status_api == 'SUCCEEDED':
                    db_job_status = 'succeeded'
                elif job_status_api == 'FAILED':
                    db_job_status = 'failed'
                elif job_status_api == 'PARTIAL_SUCCESS':
                    db_job_status = 'partial_success'

                # Update textract_jobs table with current status
                self.db_manager.update_textract_job_status(job_id, db_job_status)
                # Also update source_documents.textract_job_status
                self.db_manager.update_source_document_with_textract_outcome(
                    source_doc_sql_id=source_doc_id, 
                    textract_job_id=job_id, 
                    textract_job_status=db_job_status
                )

                if job_status_api == 'SUCCEEDED' or job_status_api == 'PARTIAL_SUCCESS':
                    all_blocks = response.get('Blocks', [])
                    document_metadata_api = response.get('DocumentMetadata', {})
                    api_warnings = response.get('Warnings')
                    next_token = response.get('NextToken')

                    while next_token:
                        time.sleep(0.5)  # Small delay for paginated calls
                        response = self.client.get_document_text_detection(
                            JobId=job_id, 
                            MaxResults=TEXTRACT_MAX_RESULTS_PER_PAGE, 
                            NextToken=next_token
                        )
                        all_blocks.extend(response.get('Blocks', []))
                        # Aggregate warnings if any from subsequent pages
                        page_warnings = response.get('Warnings')
                        if page_warnings:
                            if api_warnings is None:
                                api_warnings = []
                            api_warnings.extend(page_warnings)
                        next_token = response.get('NextToken')
                    
                    # Calculate average confidence
                    avg_conf = sum(b.get('Confidence', 0) for b in all_blocks if 'Confidence' in b) / len(all_blocks) if all_blocks else None
                    
                    # Final update to textract_jobs and source_documents
                    completion_time = datetime.now()
                    self.db_manager.update_textract_job_status(
                        job_id, db_job_status,
                        page_count=document_metadata_api.get('Pages'),
                        processed_pages=document_metadata_api.get('Pages'),
                        avg_confidence=round(avg_conf, 2) if avg_conf is not None else None,
                        warnings_json=api_warnings,
                        completed_at_override=completion_time
                    )
                    self.db_manager.update_source_document_with_textract_outcome(
                        source_doc_sql_id=source_doc_id, 
                        textract_job_id=job_id, 
                        textract_job_status=db_job_status,
                        ocr_metadata=document_metadata_api,
                        textract_warnings_json=api_warnings,
                        textract_confidence=round(avg_conf, 2) if avg_conf is not None else None,
                        job_completed_at=completion_time,
                        job_started_at=initial_db_start_time
                    )
                    logger.info(f"Textract job {job_id} {job_status_api}. Retrieved {len(all_blocks)} blocks. Pages: {document_metadata_api.get('Pages')}")
                    return all_blocks, document_metadata_api
                
                elif job_status_api == 'FAILED':
                    error_msg_api = response.get('StatusMessage', 'Unknown Textract job failure')
                    api_warnings = response.get('Warnings')
                    logger.error(f"Textract job {job_id} Failed. StatusMessage: {error_msg_api}, Warnings: {api_warnings}")
                    self.db_manager.update_textract_job_status(
                        job_id, 'failed', 
                        error_message=error_msg_api, 
                        warnings_json=api_warnings, 
                        completed_at_override=datetime.now()
                    )
                    self.db_manager.update_source_document_with_textract_outcome(
                        source_doc_sql_id=source_doc_id, 
                        textract_job_id=job_id, 
                        textract_job_status='failed', 
                        job_completed_at=datetime.now(), 
                        job_started_at=initial_db_start_time
                    )
                    return None, None
                
                time.sleep(TEXTRACT_ASYNC_POLLING_INTERVAL_SECONDS)

            except ClientError as e:
                error_message = e.response.get('Error', {}).get('Message', str(e))
                logger.error(f"ClientError while polling job {job_id}: {error_message}")
                # Update DB with polling error
                self.db_manager.update_textract_job_status(
                    job_id, 'failed', 
                    error_message=f"Polling ClientError: {error_message[:200]}"
                )
                self.db_manager.update_source_document_with_textract_outcome(
                    source_doc_sql_id=source_doc_id, 
                    textract_job_id=job_id, 
                    textract_job_status='failed'
                )
                time.sleep(TEXTRACT_ASYNC_POLLING_INTERVAL_SECONDS * 2)
            except Exception as e:
                logger.error(f"Unexpected error while polling job {job_id}: {e}", exc_info=True)
                self.db_manager.update_textract_job_status(
                    job_id, 'failed', 
                    error_message=f"Polling Exception: {str(e)[:200]}"
                )
                self.db_manager.update_source_document_with_textract_outcome(
                    source_doc_sql_id=source_doc_id, 
                    textract_job_id=job_id, 
                    textract_job_status='failed'
                )
                return None, None

    def _cache_ocr_result(self, document_uuid: str, text: str, metadata: Dict[str, Any] = None):
        """Cache OCR result in Redis."""
        try:
            redis_mgr = get_redis_manager()
            if redis_mgr.is_available():
                cache_key = f"textract:result:{document_uuid}"
                cache_data = {
                    'text': text,
                    'metadata': metadata or {},
                    'cached_at': datetime.now().isoformat()
                }
                redis_mgr.set_cached(cache_key, cache_data, REDIS_OCR_CACHE_TTL)
                logger.debug(f"Cached OCR result for document {document_uuid}")
        except Exception as e:
            logger.debug(f"Error caching OCR result: {e}")

    def get_cached_ocr_result(self, document_uuid: str) -> Optional[Tuple[str, Dict[str, Any]]]:
        """Get cached OCR result from Redis."""
        try:
            redis_mgr = get_redis_manager()
            if redis_mgr.is_available():
                cache_key = f"textract:result:{document_uuid}"
                cached_data = redis_mgr.get_cached(cache_key)
                if cached_data and isinstance(cached_data, dict):
                    logger.info(f"OCR result cache hit for document {document_uuid}")
                    return cached_data.get('text', ''), cached_data.get('metadata', {})
        except Exception as e:
            logger.debug(f"Error getting cached OCR result: {e}")
        return None

    def process_textract_blocks_to_text(self, blocks: List[Dict[str, Any]], doc_metadata: Dict[str, Any]) -> str:
        """Process Textract blocks into readable text."""
        if not blocks:
            return ""
        
        page_texts = defaultdict(list)
        line_blocks = [block for block in blocks if block['BlockType'] == 'LINE']
        
        for line in line_blocks:
            page_number = line.get('Page', 1)
            if line.get('Confidence', 0) < TEXTRACT_CONFIDENCE_THRESHOLD:
                logger.debug(f"Skipping LINE block on page {page_number} due to low confidence: {line.get('Confidence')}. Text: '{line.get('Text', '')[:50]}...'")
                continue
            
            geometry = line.get('Geometry', {}).get('BoundingBox', {})
            if not geometry:
                logger.warning(f"LINE block on page {page_number} missing BoundingBox. Text: '{line.get('Text', '')[:50]}...'")
                page_texts[page_number].append({
                    'text': line.get('Text', ''), 
                    'top': float('inf'), 
                    'left': float('inf')
                })
                continue
                
            page_texts[page_number].append({
                'text': line.get('Text', ''), 
                'top': geometry.get('Top', 0), 
                'left': geometry.get('Left', 0)
            })
        
        full_text_parts = []
        num_pages = doc_metadata.get('Pages', 0) if doc_metadata else max(page_texts.keys() or [0])
        
        for page_num in range(1, num_pages + 1):
            if page_num in page_texts:
                sorted_lines_on_page = sorted(page_texts[page_num], key=lambda item: (item['top'], item['left']))
                page_content = "\n".join([item['text'] for item in sorted_lines_on_page])
                full_text_parts.append(page_content)
            else:
                full_text_parts.append(f"[Page {page_num} - No text detected or processed]")
                
        return "\n\n<END_OF_PAGE>\n\n".join(full_text_parts)