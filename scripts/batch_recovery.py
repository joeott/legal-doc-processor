"""
Advanced batch failure handling and recovery strategies.

This module provides sophisticated error recovery mechanisms for batch processing,
including intelligent retry logic, partial batch recovery, and error categorization.
"""

import logging
from typing import Dict, Any, List, Optional, Set
from datetime import datetime, timedelta
from enum import Enum
import traceback

from celery import group, chord
from scripts.celery_app import app
from scripts.batch_tasks import BatchTask, aggregate_batch_results
from scripts.cache import get_redis_manager, CacheKeys
from scripts.config import REDIS_PREFIX_BATCH
from scripts.pdf_tasks import process_pdf_document

logger = logging.getLogger(__name__)


class ErrorCategory(Enum):
    """Categories of errors for intelligent retry decisions."""
    TRANSIENT = "transient"          # Network issues, temporary unavailability
    RESOURCE = "resource"            # Out of memory, disk space, etc.
    CONFIGURATION = "configuration"  # Missing API keys, bad config
    DATA = "data"                   # Corrupt files, invalid data
    RATE_LIMIT = "rate_limit"       # API rate limits
    PERMANENT = "permanent"         # Unrecoverable errors


class RetryStrategy(Enum):
    """Retry strategies for different error types."""
    IMMEDIATE = "immediate"          # Retry right away
    EXPONENTIAL = "exponential"      # Exponential backoff
    LINEAR = "linear"               # Linear delay increase
    SCHEDULED = "scheduled"         # Retry at specific time
    MANUAL = "manual"              # Requires manual intervention


# Error patterns for categorization
ERROR_PATTERNS = {
    ErrorCategory.TRANSIENT: [
        "ConnectionError", "TimeoutError", "NetworkError",
        "TemporaryUnavailable", "ServiceUnavailable",
        "ConnectionRefusedError", "BrokenPipeError"
    ],
    ErrorCategory.RESOURCE: [
        "MemoryError", "OutOfMemory", "DiskSpace",
        "ResourceExhausted", "TooManyOpenFiles"
    ],
    ErrorCategory.CONFIGURATION: [
        "InvalidCredentials", "MissingAPIKey", "ConfigurationError",
        "AuthenticationError", "PermissionDenied"
    ],
    ErrorCategory.DATA: [
        "CorruptFile", "InvalidFormat", "UnsupportedFormat",
        "DataError", "ValidationError", "PDFError"
    ],
    ErrorCategory.RATE_LIMIT: [
        "RateLimitExceeded", "TooManyRequests", "429",
        "ThrottlingException", "QuotaExceeded"
    ]
}


class BatchRecoveryManager(BatchTask):
    """Manages batch recovery operations."""
    
    def categorize_error(self, error_message: str, error_type: str = None) -> ErrorCategory:
        """Categorize error to determine retry strategy."""
        error_str = f"{error_type} {error_message}".lower() if error_type else error_message.lower()
        
        for category, patterns in ERROR_PATTERNS.items():
            for pattern in patterns:
                if pattern.lower() in error_str:
                    return category
        
        # Default to permanent if unknown
        return ErrorCategory.PERMANENT
    
    def determine_retry_strategy(self, error_category: ErrorCategory, 
                               retry_count: int) -> tuple[RetryStrategy, int]:
        """
        Determine retry strategy based on error category and retry count.
        
        Returns:
            Tuple of (strategy, delay_seconds)
        """
        if error_category == ErrorCategory.TRANSIENT:
            if retry_count < 3:
                return RetryStrategy.IMMEDIATE, 0
            elif retry_count < 6:
                return RetryStrategy.EXPONENTIAL, 2 ** (retry_count - 2)
            else:
                return RetryStrategy.MANUAL, 0
                
        elif error_category == ErrorCategory.RESOURCE:
            # Wait longer for resource issues
            return RetryStrategy.LINEAR, 60 * (retry_count + 1)  # 1, 2, 3... minutes
            
        elif error_category == ErrorCategory.RATE_LIMIT:
            # Back off significantly for rate limits
            return RetryStrategy.EXPONENTIAL, min(3600, 60 * (2 ** retry_count))  # Max 1 hour
            
        elif error_category == ErrorCategory.DATA:
            # Don't retry data errors automatically
            return RetryStrategy.MANUAL, 0
            
        else:  # CONFIGURATION, PERMANENT
            return RetryStrategy.MANUAL, 0
    
    def get_failed_documents(self, batch_id: str) -> List[Dict[str, Any]]:
        """Get all failed documents from a batch."""
        redis_manager = get_redis_manager()
        failed_docs = []
        
        # Scan for failed document keys
        pattern = f"{REDIS_PREFIX_BATCH}document:{batch_id}:*"
        
        for key in redis_manager.get_client().scan_iter(match=pattern, count=100):
            doc_data = redis_manager.get_dict(key)
            if doc_data and doc_data.get('status') == 'failed':
                # Extract document UUID from key
                doc_uuid = key.split(':')[-1]
                
                # Get error details
                error_key = f"{REDIS_PREFIX_BATCH}error:{batch_id}:{doc_uuid}"
                error_data = redis_manager.get_dict(error_key) or {}
                
                failed_docs.append({
                    'document_uuid': doc_uuid,
                    'error': error_data.get('error_message', 'Unknown error'),
                    'error_type': error_data.get('error_type', 'Unknown'),
                    'stage': error_data.get('stage', 'unknown'),
                    'retry_count': error_data.get('retry_count', 0),
                    'last_attempt': error_data.get('last_attempt')
                })
        
        return failed_docs
    
    def store_error_details(self, batch_id: str, document_uuid: str, 
                          error: Exception, stage: str, retry_count: int):
        """Store detailed error information for analysis."""
        redis_manager = get_redis_manager()
        error_key = f"{REDIS_PREFIX_BATCH}error:{batch_id}:{document_uuid}"
        
        error_data = {
            'error_type': type(error).__name__,
            'error_message': str(error),
            'traceback': traceback.format_exc(),
            'stage': stage,
            'retry_count': retry_count,
            'last_attempt': datetime.utcnow().isoformat(),
            'category': self.categorize_error(str(error), type(error).__name__).value
        }
        
        redis_manager.store_dict(error_key, error_data, ttl=7 * 24 * 3600)  # Keep for 7 days


@app.task(bind=True, base=BatchRecoveryManager)
def recover_failed_batch(self, batch_id: str, options: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Recover failed documents in a batch with intelligent retry logic.
    
    Args:
        batch_id: Original batch identifier
        options: Recovery options:
            - max_retries: Maximum retry attempts (default: 3)
            - retry_all: Retry all failed docs regardless of error type (default: False)
            - priority: Priority for recovery batch (default: 'normal')
            
    Returns:
        Recovery batch results
    """
    options = options or {}
    max_retries = options.get('max_retries', 3)
    retry_all = options.get('retry_all', False)
    priority = options.get('priority', 'normal')
    
    logger.info(f"Starting recovery for batch {batch_id}")
    
    # Get batch metadata
    redis_manager = get_redis_manager()
    batch_key = f"{REDIS_PREFIX_BATCH}progress:{batch_id}"
    batch_data = redis_manager.get_dict(batch_key)
    
    if not batch_data:
        return {
            'error': 'Batch not found',
            'batch_id': batch_id
        }
    
    # Get failed documents
    failed_docs = self.get_failed_documents(batch_id)
    
    if not failed_docs:
        return {
            'batch_id': batch_id,
            'message': 'No failed documents to recover'
        }
    
    logger.info(f"Found {len(failed_docs)} failed documents in batch {batch_id}")
    
    # Categorize and filter documents for retry
    documents_to_retry = []
    skipped_documents = []
    
    for doc in failed_docs:
        error_category = self.categorize_error(doc['error'], doc['error_type'])
        retry_count = doc.get('retry_count', 0)
        
        if retry_count >= max_retries and not retry_all:
            skipped_documents.append({
                'document_uuid': doc['document_uuid'],
                'reason': 'max_retries_exceeded',
                'retry_count': retry_count
            })
            continue
        
        strategy, delay = self.determine_retry_strategy(error_category, retry_count)
        
        if strategy == RetryStrategy.MANUAL and not retry_all:
            skipped_documents.append({
                'document_uuid': doc['document_uuid'],
                'reason': 'manual_intervention_required',
                'error_category': error_category.value
            })
            continue
        
        # Add to retry list with delay
        documents_to_retry.append({
            'document_uuid': doc['document_uuid'],
            'delay': delay,
            'retry_count': retry_count + 1,
            'error_category': error_category.value,
            'original_error': doc['error']
        })
    
    if not documents_to_retry:
        return {
            'batch_id': batch_id,
            'message': 'No documents eligible for automatic retry',
            'skipped_count': len(skipped_documents),
            'skipped_documents': skipped_documents
        }
    
    # Create recovery batch
    recovery_batch_id = f"{batch_id}_recovery_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
    
    # Initialize recovery batch progress
    self.update_batch_progress(recovery_batch_id, {
        'status': 'processing',
        'priority': priority,
        'total': len(documents_to_retry),
        'completed': 0,
        'failed': 0,
        'original_batch_id': batch_id,
        'is_recovery': True,
        'started_at': datetime.utcnow().isoformat()
    })
    
    # Group documents by delay for efficient scheduling
    delay_groups = {}
    for doc in documents_to_retry:
        delay = doc['delay']
        if delay not in delay_groups:
            delay_groups[delay] = []
        delay_groups[delay].append(doc)
    
    # Create tasks with appropriate delays
    all_tasks = []
    
    for delay, docs in delay_groups.items():
        for doc in docs:
            # Create recovery task with error tracking
            task_sig = recover_single_document.signature(
                args=[recovery_batch_id, doc['document_uuid'], doc['retry_count']],
                kwargs={
                    'original_error': doc['original_error'],
                    'error_category': doc['error_category']
                },
                countdown=delay,  # Delay execution
                priority=self._get_priority_value(priority)
            )
            all_tasks.append(task_sig)
    
    # Execute recovery with result aggregation
    if all_tasks:
        job = chord(all_tasks)(
            aggregate_recovery_results.s(recovery_batch_id, batch_id)
        )
        
        return {
            'recovery_batch_id': recovery_batch_id,
            'original_batch_id': batch_id,
            'status': 'submitted',
            'documents_to_retry': len(documents_to_retry),
            'skipped_documents': len(skipped_documents),
            'chord_id': job.id
        }
    
    return {
        'error': 'No tasks created for recovery'
    }


@app.task(bind=True, base=BatchRecoveryManager)
def recover_single_document(self, recovery_batch_id: str, document_uuid: str, 
                          retry_count: int, **kwargs) -> Dict[str, Any]:
    """
    Recover a single failed document with enhanced error handling.
    
    Args:
        recovery_batch_id: Recovery batch identifier
        document_uuid: Document to retry
        retry_count: Current retry attempt number
        **kwargs: Additional context (original_error, error_category)
        
    Returns:
        Recovery result for the document
    """
    logger.info(f"Recovering document {document_uuid} (attempt {retry_count})")
    
    try:
        # Track recovery attempt
        self.track_document_in_batch(recovery_batch_id, document_uuid, 'retrying')
        
        # Get document metadata
        redis_manager = get_redis_manager()
        
        # Get file path from database
        session = next(self.db_manager.get_session())
        try:
            from sqlalchemy import text
            result = session.execute(text("""
                SELECT file_name, s3_key, s3_bucket, project_uuid
                FROM source_documents
                WHERE document_uuid = :uuid
            """), {'uuid': document_uuid}).fetchone()
            
            if not result:
                raise ValueError(f"Document {document_uuid} not found in database")
            
            file_path = result[1]  # s3_key
            project_uuid = result[3]
            
        finally:
            session.close()
        
        # Process document with enhanced monitoring
        result = process_pdf_document(document_uuid, file_path, project_uuid=project_uuid)
        
        # Update recovery status
        self.track_document_in_batch(recovery_batch_id, document_uuid, 'completed')
        
        return {
            'document_uuid': document_uuid,
            'status': 'recovered',
            'retry_count': retry_count,
            'result': result
        }
        
    except Exception as e:
        logger.error(f"Recovery failed for document {document_uuid}: {str(e)}")
        
        # Store enhanced error details
        self.store_error_details(recovery_batch_id, document_uuid, e, 
                               'recovery', retry_count)
        
        # Update recovery status
        self.track_document_in_batch(recovery_batch_id, document_uuid, 'failed')
        
        return {
            'document_uuid': document_uuid,
            'status': 'failed',
            'retry_count': retry_count,
            'error': str(e),
            'error_type': type(e).__name__
        }


@app.task(bind=True, base=BatchRecoveryManager)
def aggregate_recovery_results(self, results: List[Dict], recovery_batch_id: str, 
                             original_batch_id: str) -> Dict[str, Any]:
    """Aggregate recovery results and update batch status."""
    recovered = 0
    failed = 0
    
    for result in results:
        if result.get('status') == 'recovered':
            recovered += 1
        else:
            failed += 1
    
    # Update recovery batch status
    self.update_batch_progress(recovery_batch_id, {
        'status': 'completed',
        'completed': recovered,
        'failed': failed,
        'completed_at': datetime.utcnow().isoformat()
    })
    
    # Update original batch with recovery results
    redis_manager = get_redis_manager()
    original_key = f"{REDIS_PREFIX_BATCH}progress:{original_batch_id}"
    original_data = redis_manager.get_dict(original_key) or {}
    
    # Increment completed count by recovered documents
    if original_data:
        original_data['completed'] = original_data.get('completed', 0) + recovered
        original_data['failed'] = original_data.get('failed', 0) - recovered
        original_data['last_recovery'] = datetime.utcnow().isoformat()
        original_data['recovery_batch_id'] = recovery_batch_id
        
        redis_manager.store_dict(original_key, original_data, ttl=7 * 24 * 3600)
    
    logger.info(f"Recovery batch {recovery_batch_id} completed: "
                f"{recovered} recovered, {failed} still failed")
    
    return {
        'recovery_batch_id': recovery_batch_id,
        'original_batch_id': original_batch_id,
        'recovered': recovered,
        'failed': failed,
        'recovery_rate': (recovered / (recovered + failed) * 100) if (recovered + failed) > 0 else 0
    }


@app.task
def analyze_batch_failures(batch_id: str) -> Dict[str, Any]:
    """
    Analyze failure patterns in a batch for insights.
    
    Args:
        batch_id: Batch to analyze
        
    Returns:
        Analysis report with failure patterns and recommendations
    """
    manager = BatchRecoveryManager()
    failed_docs = manager.get_failed_documents(batch_id)
    
    if not failed_docs:
        return {
            'batch_id': batch_id,
            'message': 'No failures found'
        }
    
    # Analyze failure patterns
    by_category = {}
    by_stage = {}
    by_error_type = {}
    
    for doc in failed_docs:
        # By category
        category = manager.categorize_error(doc['error'], doc['error_type'])
        by_category[category.value] = by_category.get(category.value, 0) + 1
        
        # By stage
        stage = doc.get('stage', 'unknown')
        by_stage[stage] = by_stage.get(stage, 0) + 1
        
        # By error type
        error_type = doc.get('error_type', 'Unknown')
        by_error_type[error_type] = by_error_type.get(error_type, 0) + 1
    
    # Generate recommendations
    recommendations = []
    
    if by_category.get(ErrorCategory.TRANSIENT.value, 0) > len(failed_docs) * 0.5:
        recommendations.append("High rate of transient errors - consider automatic retry")
    
    if by_category.get(ErrorCategory.RATE_LIMIT.value, 0) > 0:
        recommendations.append("Rate limit errors detected - consider reducing batch size or adding delays")
    
    if by_category.get(ErrorCategory.RESOURCE.value, 0) > 0:
        recommendations.append("Resource errors detected - check worker memory limits and disk space")
    
    if by_category.get(ErrorCategory.CONFIGURATION.value, 0) > 0:
        recommendations.append("Configuration errors detected - verify API keys and service settings")
    
    return {
        'batch_id': batch_id,
        'total_failures': len(failed_docs),
        'failure_analysis': {
            'by_category': by_category,
            'by_stage': by_stage,
            'by_error_type': dict(sorted(by_error_type.items(), 
                                       key=lambda x: x[1], reverse=True)[:10])  # Top 10
        },
        'recommendations': recommendations,
        'recoverable_count': sum(1 for doc in failed_docs 
                               if manager.categorize_error(doc['error'], doc['error_type']) 
                               in [ErrorCategory.TRANSIENT, ErrorCategory.RATE_LIMIT])
    }


# Helper functions
def _get_priority_value(priority: str) -> int:
    """Convert priority string to numeric value."""
    return {
        'high': 9,
        'normal': 5,
        'low': 1
    }.get(priority, 5)