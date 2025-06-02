"""
Textract job management for async OCR processing.
"""
import boto3
import logging
from typing import Dict, Any, Optional, Tuple, List
from datetime import datetime
import time

from scripts.config import AWS_DEFAULT_REGION, S3_PRIMARY_DOCUMENT_BUCKET, S3_BUCKET_REGION
from scripts.cache import get_redis_manager, CacheKeys
from scripts.db import DatabaseManager

logger = logging.getLogger(__name__)


class TextractJobManager:
    """Manages async Textract jobs"""
    
    def __init__(self, region_name: str = None):
        # Use S3_BUCKET_REGION for Textract to match the S3 bucket location
        if region_name is None:
            region_name = S3_BUCKET_REGION
        self.textract_client = boto3.client('textract', region_name=region_name)
        self.redis_manager = get_redis_manager()
        logger.info(f"TextractJobManager initialized for region: {region_name}")
        
    def start_textract_job(self, document_uuid: str, file_path: str) -> Optional[str]:
        """
        Start an async Textract job for document.
        
        Args:
            document_uuid: Document identifier
            file_path: S3 URI or local path
            
        Returns:
            job_id if successful, None otherwise
        """
        try:
            # Log environment check
            import os
            logger.info(f"AWS_ACCESS_KEY_ID available: {bool(os.getenv('AWS_ACCESS_KEY_ID'))}")
            logger.info(f"S3_BUCKET_REGION: {os.getenv('S3_BUCKET_REGION')}")
            
            # Parse S3 location
            if not file_path.startswith('s3://'):
                logger.error(f"File path must be S3 URI, got: {file_path}")
                return None
                
            parts = file_path.replace('s3://', '').split('/', 1)
            if len(parts) != 2:
                logger.error(f"Invalid S3 URI: {file_path}")
                return None
                
            bucket_name, s3_key = parts
            
            # Start Textract job
            logger.info(f"Starting Textract job for s3://{bucket_name}/{s3_key}")
            
            response = self.textract_client.start_document_text_detection(
                DocumentLocation={
                    'S3Object': {
                        'Bucket': bucket_name,
                        'Name': s3_key
                    }
                },
                ClientRequestToken=f"doc-{document_uuid}"  # Idempotency token
            )
            
            job_id = response.get('JobId')
            
            if job_id:
                logger.info(f"Started Textract job {job_id} for document {document_uuid}")
                
                # Cache job info
                job_info = {
                    'job_id': job_id,
                    'document_uuid': document_uuid,
                    'bucket': bucket_name,
                    's3_key': s3_key,
                    'started_at': datetime.utcnow().isoformat(),
                    'status': 'IN_PROGRESS'
                }
                
                cache_key = f"textract:job:{job_id}"
                self.redis_manager.store_dict(cache_key, job_info, ttl=3600)  # 1 hour TTL
                
                return job_id
            else:
                logger.error("No JobId in Textract response")
                return None
                
        except Exception as e:
            logger.error(f"Failed to start Textract job: {e}")
            logger.error(f"Exception type: {type(e).__name__}")
            logger.error(f"S3 location was: s3://{bucket_name}/{s3_key}")
            
            # Check if it's a credentials issue
            import botocore.exceptions
            if isinstance(e, botocore.exceptions.NoCredentialsError):
                logger.error("NO AWS CREDENTIALS FOUND!")
            elif isinstance(e, botocore.exceptions.ClientError):
                error_code = e.response.get('Error', {}).get('Code', 'Unknown')
                logger.error(f"AWS Client Error Code: {error_code}")
                
            return None
    
    def check_job_status(self, job_id: str) -> Optional[str]:
        """
        Check status of a Textract job.
        
        Returns:
            Status: 'IN_PROGRESS', 'SUCCEEDED', 'FAILED', 'PARTIAL_SUCCESS'
        """
        try:
            response = self.textract_client.get_document_text_detection(JobId=job_id)
            status = response.get('JobStatus', 'UNKNOWN')
            
            # Update cache
            cache_key = f"textract:job:{job_id}"
            job_info = self.redis_manager.get_dict(cache_key) or {}
            job_info['status'] = status
            job_info['last_checked'] = datetime.utcnow().isoformat()
            
            if status in ['SUCCEEDED', 'FAILED']:
                job_info['completed_at'] = datetime.utcnow().isoformat()
                
            self.redis_manager.store_dict(cache_key, job_info, ttl=3600)
            
            return status
            
        except Exception as e:
            logger.error(f"Failed to check job status: {e}")
            return None
    
    def get_job_results(self, job_id: str) -> Optional[Dict[str, Any]]:
        """
        Get results from completed Textract job.
        
        Returns:
            Dict with 'text' and 'metadata' keys
        """
        try:
            # Get all pages of results
            all_blocks = []
            next_token = None
            page_count = 0
            
            while True:
                if next_token:
                    response = self.textract_client.get_document_text_detection(
                        JobId=job_id,
                        NextToken=next_token
                    )
                else:
                    response = self.textract_client.get_document_text_detection(
                        JobId=job_id
                    )
                
                # Check status
                if response.get('JobStatus') != 'SUCCEEDED':
                    logger.error(f"Job {job_id} not succeeded: {response.get('JobStatus')}")
                    return None
                
                # Collect blocks
                blocks = response.get('Blocks', [])
                all_blocks.extend(blocks)
                
                # Track pages
                doc_metadata = response.get('DocumentMetadata', {})
                page_count = doc_metadata.get('Pages', 1)
                
                # Check for more pages
                next_token = response.get('NextToken')
                if not next_token:
                    break
            
            # Extract text from blocks
            text_lines = []
            word_count = 0
            confidence_scores = []
            
            for block in all_blocks:
                if block['BlockType'] == 'LINE':
                    text_lines.append(block.get('Text', ''))
                    if 'Confidence' in block:
                        confidence_scores.append(block['Confidence'])
                elif block['BlockType'] == 'WORD':
                    word_count += 1
            
            # Combine text
            extracted_text = '\n'.join(text_lines)
            
            # Calculate average confidence
            avg_confidence = sum(confidence_scores) / len(confidence_scores) if confidence_scores else 95.0
            
            # Build metadata
            metadata = {
                'job_id': job_id,
                'page_count': page_count,
                'block_count': len(all_blocks),
                'word_count': word_count,
                'line_count': len(text_lines),
                'avg_confidence': avg_confidence / 100.0,  # Convert to 0-1 scale
                'method': 'AWS Textract (async)'
            }
            
            return {
                'status': 'success',
                'text': extracted_text,
                'metadata': metadata
            }
            
        except Exception as e:
            logger.error(f"Failed to get job results: {e}")
            return None
    
    def update_document_status(self, document_uuid: str, job_id: str, status: str, 
                             error_message: Optional[str] = None):
        """Update document status in database"""
        try:
            logger.info(f"Attempting to update document {document_uuid} with job_id={job_id}, status={status}")
            db_manager = DatabaseManager(validate_conformance=False)
            
            session = next(db_manager.get_session())
            try:
                from sqlalchemy import text
                
                update_query = text("""
                    UPDATE source_documents 
                    SET textract_job_id = :job_id,
                        textract_job_status = :status,
                        error_message = CASE WHEN :error_msg IS NOT NULL THEN :error_msg ELSE error_message END,
                        updated_at = NOW()
                    WHERE document_uuid = :doc_uuid
                """)
                
                result = session.execute(update_query, {
                    'job_id': job_id,
                    'status': status,
                    'error_msg': error_message,
                    'doc_uuid': str(document_uuid)  # Ensure string conversion
                })
                session.commit()
                logger.info(f"Updated {result.rowcount} rows for document {document_uuid}")
            finally:
                session.close()
                
        except Exception as e:
            logger.error(f"Failed to update document status: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
    
    def cache_ocr_results(self, document_uuid: str, text: str, metadata: Dict[str, Any]):
        """Cache OCR results for document"""
        try:
            cache_key = CacheKeys.DOC_OCR_RESULT.format(document_uuid=document_uuid)
            
            result = {
                'status': 'success',
                'text': text,
                'metadata': metadata,
                'cached_at': datetime.utcnow().isoformat()
            }
            
            self.redis_manager.store_dict(cache_key, result, ttl=86400)  # 24 hour cache
            logger.info(f"Cached OCR results for document {document_uuid}")
            
        except Exception as e:
            logger.error(f"Failed to cache OCR results: {e}")


# Singleton instance
_job_manager = None

def get_job_manager() -> TextractJobManager:
    """Get singleton job manager instance"""
    global _job_manager
    if _job_manager is None:
        _job_manager = TextractJobManager()
    return _job_manager