"""Unified error handling for the processing pipeline"""

import logging
import traceback
from typing import Dict, Any, Optional
from datetime import datetime

from scripts.utils.error_types import (
    ProcessingError, ValidationError, ConfigurationError,
    ResourceError, DataError, NetworkError, AuthenticationError,
    ThrottlingError, S3AccessError, TextractError, DatabaseError,
    RedisError, PDFProcessingError, OCRError
)

logger = logging.getLogger(__name__)

def classify_error(error: Exception) -> ProcessingError:
    """
    Classify generic exceptions into specific error types.
    
    Returns a ProcessingError subclass with appropriate retry behavior.
    """
    error_str = str(error).lower()
    error_type = type(error).__name__
    
    # Already a ProcessingError
    if isinstance(error, ProcessingError):
        return error
    
    # S3 errors
    if 'ClientError' in error_type or 's3' in error_str:
        if 'accessdenied' in error_str or 'forbidden' in error_str:
            return S3AccessError("S3 access denied", {"original_error": str(error)})
        elif 'nosuchbucket' in error_str or 'nosuchkey' in error_str:
            return S3AccessError("S3 object not found", {"original_error": str(error)})
        else:
            return S3AccessError("S3 operation failed", {"original_error": str(error)})
    
    # Database errors
    elif 'psycopg2' in error_type or 'sqlalchemy' in error_type:
        if 'connection' in error_str:
            return DatabaseError("Database connection failed", {"original_error": str(error)})
        else:
            return DatabaseError("Database operation failed", {"original_error": str(error)})
    
    # Redis errors
    elif 'redis' in error_type or 'redis' in error_str:
        return RedisError("Redis operation failed", {"original_error": str(error)})
    
    # Textract errors
    elif 'textract' in error_str:
        if 'throttl' in error_str or 'ratelimit' in error_str:
            return ThrottlingError("Textract rate limit exceeded", {"original_error": str(error)})
        else:
            return TextractError("Textract processing failed", {"original_error": str(error)})
    
    # Network errors
    elif 'timeout' in error_str or 'connection' in error_str:
        return NetworkError("Network operation failed", {"original_error": str(error)})
    
    # Authentication errors
    elif 'unauthorized' in error_str or 'credentials' in error_str:
        return AuthenticationError("Authentication failed", {"original_error": str(error)})
    
    # PDF errors
    elif 'pdf' in error_str or 'mupdf' in error_str:
        return PDFProcessingError("PDF processing failed", {"original_error": str(error)})
    
    # Configuration errors
    elif 'config' in error_str or 'missing' in error_str:
        return ConfigurationError("Configuration error", {"original_error": str(error)})
    
    # Default to retryable ProcessingError
    return ProcessingError(f"Unclassified error: {error_type}", {"original_error": str(error)})

def handle_task_error(
    error: Exception, 
    task_name: str, 
    document_uuid: str,
    additional_context: Dict[str, Any] = None
) -> Dict[str, Any]:
    """
    Unified error handling with appropriate logging and response.
    
    Args:
        error: The exception that occurred
        task_name: Name of the task where error occurred
        document_uuid: Document being processed
        additional_context: Additional context information
        
    Returns:
        Error information dictionary
    """
    # Classify the error
    classified_error = classify_error(error)
    
    # Build error info
    error_info = {
        "task": task_name,
        "document_uuid": document_uuid,
        "error_type": type(classified_error).__name__,
        "error_message": str(error),
        "retryable": classified_error.retryable,
        "timestamp": datetime.utcnow().isoformat(),
        "details": classified_error.details
    }
    
    # Add additional context
    if additional_context:
        error_info["context"] = additional_context
    
    # Add traceback for debugging
    if logger.isEnabledFor(logging.DEBUG):
        error_info["traceback"] = traceback.format_exc()
    
    # Log appropriately based on error type
    if classified_error.retryable:
        logger.warning(
            f"Retryable error in {task_name} for document {document_uuid}: "
            f"{type(classified_error).__name__} - {error}"
        )
    else:
        logger.error(
            f"Non-retryable error in {task_name} for document {document_uuid}: "
            f"{type(classified_error).__name__} - {error}"
        )
    
    # Update monitoring/state if available
    try:
        from scripts.pdf_tasks import update_document_state
        update_document_state(
            document_uuid, 
            task_name.replace('_', ' '), 
            "error", 
            error_info
        )
    except Exception as e:
        logger.debug(f"Could not update document state: {e}")
    
    return error_info

def should_retry_error(error: Exception) -> bool:
    """
    Determine if an error should be retried.
    
    Simple wrapper around error classification.
    """
    classified_error = classify_error(error)
    return classified_error.retryable

def get_retry_delay(error: Exception, retry_count: int) -> int:
    """
    Calculate appropriate retry delay based on error type and retry count.
    
    Args:
        error: The exception that occurred
        retry_count: Number of retries already attempted
        
    Returns:
        Delay in seconds before retry
    """
    classified_error = classify_error(error)
    
    # Base delays by error type
    base_delays = {
        ThrottlingError: 30,      # Longer delay for rate limits
        NetworkError: 10,         # Medium delay for network issues
        ResourceError: 15,        # Medium delay for resource issues
        ValidationError: 5,       # Short delay for validation
        ProcessingError: 10       # Default medium delay
    }
    
    # Get base delay for error type
    base_delay = base_delays.get(type(classified_error), 10)
    
    # Exponential backoff with cap
    delay = min(300, base_delay * (2 ** retry_count))  # Max 5 minutes
    
    # Add jitter to prevent thundering herd
    import random
    jitter = random.uniform(0, delay * 0.1)  # Up to 10% jitter
    
    return int(delay + jitter)