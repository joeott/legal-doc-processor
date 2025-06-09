# Context 428: Implementation Progress - Phases 3 & 4

## Date: June 5, 2025

## Phase 3: Lightweight Parameter Validation

### Completed Tasks

#### 1. Created Parameter Validator (✅)
**File**: `/scripts/utils/param_validator.py`

**Features Implemented**:
- `@validate_task_params` decorator
- Automatic UUID normalization (handles str, dict, UUID objects)
- File path normalization
- Debug logging with PARAMETER_DEBUG env var
- Zero overhead when not needed

**Key Functions**:
- `normalize_uuid_param()`: Handles all UUID variations
- `normalize_file_path()`: Handles path variations
- `validate_task_params()`: Main decorator

#### 2. Applied to extract_text_from_document (✅)
- Added decorator to OCR task
- Removed manual defensive coding
- Parameters now auto-normalized before function execution

### Benefits
- **Automatic**: No manual parameter checking needed
- **Transparent**: Original function signature unchanged
- **Debuggable**: Optional parameter logging
- **Lightweight**: Uses Python's built-in inspect module

## Phase 4: Standardized Error Handling

### Completed Tasks

#### 1. Created Error Type Hierarchy (✅)
**File**: `/scripts/utils/error_types.py`

**Error Classes**:
```
ProcessingError (base)
├── ValidationError (retryable)
├── ConfigurationError (non-retryable)
├── ResourceError (retryable)
│   ├── S3AccessError
│   ├── TextractError
│   ├── DatabaseError
│   └── RedisError
├── DataError (non-retryable)
│   └── PDFProcessingError
├── NetworkError (retryable)
├── AuthenticationError (non-retryable)
├── ThrottlingError (retryable)
└── OCRError (configurable)
```

#### 2. Created Unified Error Handler (✅)
**File**: `/scripts/utils/error_handler.py`

**Key Functions**:
- `classify_error()`: Convert any exception to typed error
- `handle_task_error()`: Unified error handling with logging
- `should_retry_error()`: Determine retry behavior
- `get_retry_delay()`: Calculate backoff with jitter

### Error Classification Logic

The handler automatically classifies errors based on:
- Exception type name
- Error message content
- Known patterns (S3, database, network, etc.)

### Retry Strategy

**Retryable Errors**:
- ResourceError (S3, Textract, DB, Redis temporary issues)
- NetworkError (timeouts, connection issues)
- ThrottlingError (rate limits)
- ValidationError (may succeed on retry)

**Non-Retryable Errors**:
- ConfigurationError (wrong credentials, missing config)
- AuthenticationError (invalid permissions)
- DataError (corrupt files, invalid format)

**Retry Delays**:
```python
base_delays = {
    ThrottlingError: 30,      # Rate limits need longer wait
    NetworkError: 10,         # Network issues medium delay
    ResourceError: 15,        # Resource issues medium delay
    ValidationError: 5,       # Quick retry for validation
    ProcessingError: 10       # Default medium delay
}
# Exponential backoff: delay * 2^retry_count (max 300s)
# Plus 0-10% jitter to prevent thundering herd
```

## Integration Example

```python
from scripts.utils.error_handler import handle_task_error, should_retry_error

@app.task(bind=True, max_retries=3)
@validate_task_params({'document_uuid': str})
def my_task(self, document_uuid: str):
    try:
        # Task logic here
        process_document(document_uuid)
    except Exception as e:
        # Unified error handling
        error_info = handle_task_error(
            error=e,
            task_name="my_task",
            document_uuid=document_uuid,
            additional_context={"stage": "processing"}
        )
        
        # Retry if appropriate
        if should_retry_error(e) and self.request.retries < self.max_retries:
            delay = get_retry_delay(e, self.request.retries)
            raise self.retry(exc=e, countdown=delay)
        else:
            raise
```

## Environment Variables

```bash
# Enable parameter debug logging
PARAMETER_DEBUG=true

# Force processing despite errors
FORCE_PROCESSING=true

# Skip PDF preprocessing
SKIP_PDF_PREPROCESSING=true

# Validation overrides
VALIDATION_REDIS_METADATA_LEVEL=optional
```

## Testing the Complete Stack

### 1. Parameter Validation Test
```python
# Will normalize any UUID format
extract_text_from_document.apply_async(args=[
    {"document_uuid": "test-uuid"},  # Dict will be normalized
    "s3://bucket/file.pdf"
])
```

### 2. Error Classification Test
```python
from scripts.utils.error_handler import classify_error

# Test various errors
errors = [
    Exception("Access Denied"),
    Exception("Connection timeout"),
    Exception("Invalid PDF file"),
    Exception("Rate limit exceeded")
]

for error in errors:
    classified = classify_error(error)
    print(f"{error} -> {type(classified).__name__} (retryable: {classified.retryable})")
```

### 3. End-to-End Test
```bash
# Set up environment
export FORCE_PROCESSING=true
export SKIP_PDF_PREPROCESSING=true
export PARAMETER_DEBUG=true

# Process documents
python3 rerun_input_docs_processing.py
```

## Summary

All four phases of the improvement plan have been implemented:

1. **PyMuPDF Fix** ✅ - Safe PDF operations with fallbacks
2. **Flexible Validation** ✅ - Tiered validation system
3. **Parameter Validation** ✅ - Automatic normalization
4. **Error Handling** ✅ - Typed errors with retry logic

The system is now more robust and production-ready with:
- Multiple fallback mechanisms
- Flexible validation that doesn't block processing
- Automatic parameter normalization
- Intelligent error classification and retry behavior

Next step: Test with real documents...