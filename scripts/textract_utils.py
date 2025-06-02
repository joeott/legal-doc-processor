# textract_utils.py
import boto3
import logging
import time
import uuid
import hashlib
from datetime import datetime
from typing import List, Dict, Optional, Tuple, Any
from collections import defaultdict
from botocore.exceptions import ClientError

from scripts.db import DatabaseManager
from scripts.config import (
    AWS_DEFAULT_REGION, S3_BUCKET_REGION, TEXTRACT_ASYNC_MAX_POLLING_TIME_SECONDS, TEXTRACT_ASYNC_POLLING_INTERVAL_SECONDS,
    TEXTRACT_ASYNC_INITIAL_DELAY_SECONDS, TEXTRACT_SNS_TOPIC_ARN, TEXTRACT_SNS_ROLE_ARN,
    TEXTRACT_OUTPUT_S3_BUCKET, TEXTRACT_OUTPUT_S3_PREFIX, TEXTRACT_KMS_KEY_ID,
    TEXTRACT_CONFIDENCE_THRESHOLD, TEXTRACT_MAX_RESULTS_PER_PAGE, TEXTRACT_FEATURE_TYPES,
    REDIS_OCR_CACHE_TTL
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
        """Initialize TextractProcessor with database manager."""
        # Use S3_BUCKET_REGION for Textract to match the S3 bucket location
        if region_name is None:
            region_name = S3_BUCKET_REGION
        self.client = boto3.client('textract', region_name=region_name)
        self.db_manager = db_manager
        logger.info(f"TextractProcessor initialized for region: {region_name} with DBManager.")

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

    def get_text_detection_results(self, job_id: str, source_doc_id: int) -> Tuple[Optional[List[Dict[str, Any]]], Optional[Dict[str, Any]]]:
        """Poll for Textract job results and update database."""
        logger.info(f"Polling for Textract job results. JobId: {job_id}, SourceDocId: {source_doc_id}")
        start_time = time.time()
        job_entry = self.db_manager.get_textract_job_by_job_id(job_id)
        initial_db_start_time = datetime.fromisoformat(job_entry.get('started_at')) if job_entry and job_entry.get('started_at') else datetime.now()

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