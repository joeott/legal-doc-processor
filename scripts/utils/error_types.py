"""Standardized error types for the processing pipeline"""

class ProcessingError(Exception):
    """Base class for all processing errors"""
    retryable = True
    
    def __init__(self, message: str, details: dict = None):
        super().__init__(message)
        self.details = details or {}

class ValidationError(ProcessingError):
    """Validation failed but might succeed on retry"""
    retryable = True
    
class ConfigurationError(ProcessingError):
    """Configuration issue - won't succeed on retry"""
    retryable = False
    
class ResourceError(ProcessingError):
    """Resource temporarily unavailable"""
    retryable = True
    
class DataError(ProcessingError):
    """Data format or content issue"""
    retryable = False

class NetworkError(ProcessingError):
    """Network-related errors"""
    retryable = True

class AuthenticationError(ProcessingError):
    """Authentication/authorization failures"""
    retryable = False

class ThrottlingError(ProcessingError):
    """Rate limiting or throttling"""
    retryable = True

# Specific error subclasses
class S3AccessError(ResourceError):
    """S3 access issues"""
    pass

class TextractError(ResourceError):
    """Textract processing errors"""
    pass

class DatabaseError(ResourceError):
    """Database connection or query errors"""
    pass

class RedisError(ResourceError):
    """Redis connection or operation errors"""
    pass

class PDFProcessingError(DataError):
    """PDF-specific processing errors"""
    pass

class OCRError(ProcessingError):
    """OCR processing errors"""
    # Some OCR errors are retryable (service issues), others not (corrupt file)
    def __init__(self, message: str, retryable: bool = True, details: dict = None):
        super().__init__(message, details)
        self.retryable = retryable