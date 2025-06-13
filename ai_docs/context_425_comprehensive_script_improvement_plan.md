# Context 425: Comprehensive Script Improvement Plan

## Executive Summary

This plan addresses the remaining issues from Context 424 and provides a pragmatic approach to improve script robustness while maintaining simplicity. The focus is on removing barriers to successful document processing rather than adding complex validation layers.

## Date: June 5, 2025

## Core Philosophy

**Simplicity First**: Every improvement should reduce failure points, not add complexity. Validation should guide successful processing, not become a barrier.

## Priority 1: Resolve PyMuPDF Issue

### Problem Analysis
The error `libmupdf.so.26.1: failed to map segment from shared object` indicates a shared library loading issue, likely due to:
- Missing system dependencies
- Library version mismatch
- Memory/resource constraints in Celery worker

### Solution Strategy

#### Option A: Fix PyMuPDF (Preferred)
```python
# In scripts/pdf_tasks.py - Add fallback for PDF operations
def safe_pdf_operation(file_path: str, operation: str = "check") -> Optional[Any]:
    """Safely perform PDF operations with multiple fallbacks"""
    
    # Try PyMuPDF first
    try:
        import fitz
        return fitz.open(file_path)
    except Exception as e:
        logger.warning(f"PyMuPDF failed: {e}, trying alternatives")
    
    # Fallback to PyPDF2 for basic operations
    try:
        import PyPDF2
        with open(file_path, 'rb') as f:
            return PyPDF2.PdfReader(f)
    except Exception as e:
        logger.warning(f"PyPDF2 failed: {e}")
    
    # Final fallback - just check file exists and size
    if operation == "check":
        return {"exists": os.path.exists(file_path), 
                "size": os.path.getsize(file_path) if os.path.exists(file_path) else 0}
    
    return None
```

#### Option B: Bypass PDF Pre-processing
```python
# For S3 files, skip local PDF operations entirely
if file_path.startswith('s3://'):
    # Let Textract handle everything
    logger.info("S3 file detected, skipping local PDF operations")
    return {"method": "textract_direct", "preprocessing": "skipped"}
```

### Implementation Steps
1. Add `PyPDF2` to requirements.txt as fallback
2. Implement `safe_pdf_operation` wrapper
3. Update all PyMuPDF usage to use the wrapper
4. Add environment variable `SKIP_PDF_PREPROCESSING=true` for production

## Priority 2: Flexible Pre-processing Validation

### Current Issues
- Validation is too strict (all-or-nothing)
- Non-critical failures block processing
- Redis metadata requirements are artificial

### Solution: Tiered Validation System

```python
# scripts/validation/flexible_validator.py
from enum import Enum
from typing import Dict, List, Tuple

class ValidationLevel(Enum):
    CRITICAL = "critical"     # Must pass or processing fails
    IMPORTANT = "important"   # Log warning but continue
    OPTIONAL = "optional"     # Nice to have, ignore failures

class FlexibleValidator:
    """Validation that helps rather than hinders"""
    
    VALIDATION_RULES = {
        "database_record": ValidationLevel.CRITICAL,
        "s3_access": ValidationLevel.CRITICAL,
        "project_association": ValidationLevel.IMPORTANT,
        "redis_metadata": ValidationLevel.OPTIONAL,
        "file_size": ValidationLevel.IMPORTANT,
        "system_resources": ValidationLevel.OPTIONAL,
        "textract_availability": ValidationLevel.IMPORTANT
    }
    
    def validate_document(self, document_uuid: str, file_path: str) -> Tuple[bool, Dict]:
        """Validate with appropriate flexibility"""
        results = {}
        critical_passed = True
        
        for check_name, level in self.VALIDATION_RULES.items():
            try:
                passed, message = self._run_check(check_name, document_uuid, file_path)
                results[check_name] = {"passed": passed, "message": message, "level": level.value}
                
                if not passed and level == ValidationLevel.CRITICAL:
                    critical_passed = False
                    logger.error(f"❌ CRITICAL validation failed: {check_name}")
                elif not passed and level == ValidationLevel.IMPORTANT:
                    logger.warning(f"⚠️  Important validation failed: {check_name}")
                elif not passed:
                    logger.info(f"ℹ️  Optional validation failed: {check_name}")
                    
            except Exception as e:
                logger.warning(f"Validation check {check_name} error: {e}")
                if level == ValidationLevel.CRITICAL:
                    critical_passed = False
        
        return critical_passed, results
```

### Integration
```python
# In pdf_tasks.py
from scripts.validation.flexible_validator import FlexibleValidator

# Replace strict validation with flexible approach
validator = FlexibleValidator()
passed, results = validator.validate_document(document_uuid, file_path)

if not passed:
    logger.error(f"Critical validations failed: {results}")
    # Still continue if FORCE_PROCESSING is set
    if not os.getenv('FORCE_PROCESSING'):
        raise ValueError("Critical validation failed")
else:
    logger.info("✅ Critical validations passed, proceeding with processing")
```

## Priority 3: Lightweight Parameter Validation

### Design Principle
Use Python's built-in features with minimal overhead. No complex validation frameworks.

### Implementation

```python
# scripts/utils/param_validator.py
from typing import Union, Optional
from functools import wraps
import logging

logger = logging.getLogger(__name__)

def validate_task_params(expected_types: dict):
    """Simple decorator for parameter validation and normalization"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Get function signature
            import inspect
            sig = inspect.signature(func)
            bound_args = sig.bind(*args, **kwargs)
            bound_args.apply_defaults()
            
            # Validate and normalize each parameter
            for param_name, expected_type in expected_types.items():
                if param_name in bound_args.arguments:
                    value = bound_args.arguments[param_name]
                    
                    # Handle UUID parameters specially
                    if param_name.endswith('_uuid') and expected_type == str:
                        normalized = normalize_uuid_param(value)
                        bound_args.arguments[param_name] = normalized
                    
                    # Log parameter types for debugging
                    logger.debug(f"Parameter {param_name}: {type(value).__name__} -> {expected_type.__name__}")
            
            return func(*bound_args.args, **bound_args.kwargs)
        return wrapper
    return decorator

def normalize_uuid_param(value: Union[str, dict, object]) -> str:
    """Normalize various UUID input formats to string"""
    if isinstance(value, str):
        return value
    elif isinstance(value, dict) and 'document_uuid' in value:
        return value['document_uuid']
    elif hasattr(value, 'hex'):
        return str(value)
    else:
        return str(value)
```

### Usage Example
```python
# In pdf_tasks.py
from scripts.utils.param_validator import validate_task_params

@app.task(bind=True, base=PDFTask, max_retries=3)
@validate_task_params({'document_uuid': str, 'file_path': str})
def extract_text_from_document(self, document_uuid: str, file_path: str) -> Dict[str, Any]:
    # Parameters are now guaranteed to be correct types
    logger.info(f"Processing document {document_uuid} from {file_path}")
    # ... rest of implementation
```

## Priority 4: Standardized Error Handling

### Error Categories
```python
# scripts/utils/error_types.py
class ProcessingError(Exception):
    """Base class for processing errors"""
    retryable = True
    
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
```

### Unified Error Handler
```python
# scripts/utils/error_handler.py
def handle_task_error(error: Exception, task_name: str, document_uuid: str) -> dict:
    """Unified error handling with appropriate responses"""
    
    error_info = {
        "task": task_name,
        "document_uuid": document_uuid,
        "error_type": type(error).__name__,
        "error_message": str(error),
        "retryable": getattr(error, 'retryable', False)
    }
    
    # Log appropriately
    if isinstance(error, ProcessingError) and not error.retryable:
        logger.error(f"Non-retryable error in {task_name}: {error}")
    else:
        logger.warning(f"Retryable error in {task_name}: {error}")
    
    # Update monitoring
    update_document_state(document_uuid, task_name, "error", error_info)
    
    return error_info
```

## Implementation Roadmap

### Phase 1: Quick Wins (1-2 hours)
1. **Fix PyMuPDF Issue**
   - Add PyPDF2 fallback
   - Implement safe_pdf_operation wrapper
   - Test with problem documents

2. **Flexible Validation**
   - Create flexible_validator.py
   - Update pdf_tasks.py to use it
   - Add FORCE_PROCESSING environment variable

### Phase 2: Robustness (2-3 hours)
3. **Parameter Validation**
   - Create param_validator.py decorator
   - Apply to all Celery tasks
   - Add debug logging

4. **Error Standardization**
   - Create error types
   - Implement unified handler
   - Update existing error handling

### Phase 3: Testing (1-2 hours)
5. **Integration Tests**
   - Test parameter edge cases
   - Test validation flexibility
   - Test error recovery

## Verification Steps

### 1. PyMuPDF Resolution Test
```bash
# Test PDF operations work
python3 -c "
from scripts.pdf_tasks import safe_pdf_operation
result = safe_pdf_operation('/path/to/test.pdf')
print(f'PDF operation result: {result}')
"
```

### 2. Flexible Validation Test
```bash
# Test with missing Redis metadata
export SKIP_REDIS_VALIDATION=true
python3 test_flexible_validation.py

# Force processing despite validation failures
export FORCE_PROCESSING=true
python3 rerun_input_docs_processing.py
```

### 3. Parameter Validation Test
```python
# test_param_validation.py
from scripts.pdf_tasks import extract_text_from_document

# Test various parameter formats
test_cases = [
    ("string-uuid", "s3://bucket/file.pdf"),
    ({"document_uuid": "dict-uuid"}, "s3://bucket/file.pdf"),
    (UUID("uuid-object"), "s3://bucket/file.pdf")
]

for doc_id, file_path in test_cases:
    result = extract_text_from_document.apply_async(args=[doc_id, file_path])
    print(f"Test case {type(doc_id).__name__}: {result.status}")
```

### 4. Error Handling Test
```python
# Test retryable vs non-retryable errors
from scripts.utils.error_types import ResourceError, ConfigurationError

# Should retry
raise ResourceError("S3 temporarily unavailable")

# Should not retry
raise ConfigurationError("Invalid AWS credentials")
```

### 5. End-to-End Processing Test
```bash
# Run full pipeline with all improvements
cd /opt/legal-doc-processor
source load_env.sh

# Set permissive mode
export FORCE_PROCESSING=true
export SKIP_PDF_PREPROCESSING=true

# Process documents
python3 process_paul_michael_documents.py

# Monitor results
python3 monitor_reprocessing.py
```

## Success Metrics

1. **PyMuPDF errors eliminated** - No library loading failures
2. **Validation pass rate > 95%** - Most documents process without intervention
3. **Parameter errors = 0** - All parameter formats handled gracefully
4. **Processing success rate > 90%** - Documents complete full pipeline
5. **Mean time to recovery < 5 min** - Quick error recovery

## Configuration Management

### Environment Variables
```bash
# Production settings for maximum reliability
FORCE_PROCESSING=true              # Continue despite validation warnings
SKIP_PDF_PREPROCESSING=true        # Let Textract handle PDFs
VALIDATION_LEVEL=flexible          # Use tiered validation
PARAMETER_DEBUG=true               # Log parameter normalization
ERROR_RETRY_MAX=3                  # Retry count for transient errors
CIRCUIT_BREAKER_THRESHOLD=5        # Failures before circuit opens
```

### Monitoring Dashboard
```python
# scripts/monitoring/health_check.py
def check_pipeline_health():
    """Quick health check for production monitoring"""
    checks = {
        "celery_workers": check_celery_workers(),
        "redis_connection": check_redis(),
        "s3_access": check_s3_access(),
        "database_connection": check_database(),
        "recent_errors": get_recent_errors(minutes=5),
        "processing_rate": get_processing_rate()
    }
    
    health_score = sum(1 for check in checks.values() if check.get('healthy', False))
    return {
        "healthy": health_score >= 4,  # At least 4/6 checks passing
        "score": f"{health_score}/6",
        "details": checks
    }
```

## Conclusion

This plan prioritizes practical solutions over theoretical perfection. By focusing on:
1. **Removing barriers** (PyMuPDF issue, strict validation)
2. **Adding resilience** (fallbacks, flexible validation)
3. **Maintaining simplicity** (lightweight decorators, clear errors)

We achieve a robust document processing pipeline that handles real-world variations without unnecessary complexity. The goal is documents processed successfully, not perfect validation scores.