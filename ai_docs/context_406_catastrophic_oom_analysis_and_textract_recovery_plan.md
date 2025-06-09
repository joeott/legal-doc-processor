# Context 406: Catastrophic OOM Analysis and Textract Recovery Plan

## Issue Summary
The EC2 instance experienced catastrophic Out-of-Memory (OOM) crashes on June 5, 2025, caused by runaway `pdftoppm` processes when Textract failed and the system fell back to local OCR processing.

## OOM Event Timeline
```
[516111.852116] Out of memory: Killed process 435763 (celery) - 1010MB RSS
[516386.338830] Out of memory: Killed process 474278 (celery) - 1112MB RSS  
[516465.878432] Out of memory: Killed process 455513 (node) - 767MB RSS
[516466.527828] Out of memory: Killed process 476341 (pdftoppm) - 1511MB RSS
[518256.745943] Out of memory: Killed process 477137 (pdftoppm) - 1416MB RSS
[518333.392419] Out of memory: Killed process 476147 (celery) - 1084MB RSS
```

## Root Cause Analysis

### Primary Issue: Textract Never Executes
1. **Database Validation Failure**
   - Documents uploaded to S3 successfully
   - But NO database records created for documents
   - `pdf_tasks.py:781` - `validate_document_exists()` returns False
   - Task fails before Textract is even attempted

2. **Missing Prerequisites**
   - No projects exist in database (`projects` table empty)
   - Documents require `project_fk_id` foreign key
   - Pipeline hardcodes `project_fk_id = 1` which doesn't exist
   - Foreign key constraint prevents document insertion

3. **Metadata Gap**
   - Pipeline expects Redis key `doc:metadata:{document_uuid}`
   - This metadata is never created during upload
   - Even if Textract succeeded, pipeline would fail at next stage

### Secondary Issue: Catastrophic Fallback
When validation fails, the system attempts fallback OCR:

1. **Memory-Intensive Process**
   ```python
   # pdf_tasks.py -> textract_utils.py -> extract_with_tesseract()
   images = convert_from_path(local_file_path, dpi=200)  # Uses pdftoppm
   ```

2. **Resource Consumption**
   - Each PDF page → high-res image (200 DPI)
   - Large PDFs (400+ pages) → gigabytes of memory
   - Multiple concurrent failures → memory exhaustion
   - System enters OOM death spiral

### Technical Details

#### 1. Document Creation Failure Path
```
upload_to_s3() → create_document_in_db() → FAILS (no project)
                                        ↓
                            extract_text_from_document() 
                                        ↓
                            validate_document_exists() → False
                                        ↓
                            Task fails → Retry with fallback
                                        ↓
                            extract_with_tesseract() → OOM
```

#### 2. Textract Configuration Issues
- Region mismatch between S3 bucket and Textract service
- `S3_BUCKET_REGION` vs `AWS_DEFAULT_REGION` confusion
- Results in `InvalidS3ObjectException` when regions differ

#### 3. Missing Error Boundaries
- No memory limit checks before fallback
- No circuit breaker for repeated failures
- No graceful degradation for large files

## Immediate Recovery Actions

### 1. Fix Document Creation
```python
# Create default project
INSERT INTO projects (project_uuid, name, created_at) 
VALUES (gen_random_uuid(), 'Default Project', NOW());

# Update pipeline to create documents properly
def create_document_with_project(document_uuid, file_path, project_id=1):
    # Ensure project exists
    # Create document with proper FK reference
    # Create Redis metadata
```

### 2. Disable Memory-Intensive Fallback
```python
# In textract_utils.py
def extract_with_tesseract(self, file_path: str, document_uuid: str):
    # Add memory safety check
    file_size_mb = check_file_size(file_path)
    if file_size_mb > 50:  # 50MB limit for Tesseract
        raise RuntimeError(f"File too large for Tesseract fallback: {file_size_mb}MB")
    
    # Add page limit
    if file_path.lower().endswith('.pdf'):
        pdf_info = get_pdf_info(file_path)
        if pdf_info['pages'] > 20:  # 20 page limit
            raise RuntimeError(f"Too many pages for Tesseract: {pdf_info['pages']}")
```

### 3. Fix Textract Region Configuration
```python
# In textract_utils.py
def __init__(self, db_manager: DatabaseManager, region_name: str = None):
    # Ensure Textract uses same region as S3
    if region_name is None:
        region_name = S3_BUCKET_REGION or AWS_DEFAULT_REGION
    
    # Verify S3 bucket is accessible from this region
    self.verify_s3_access(S3_PRIMARY_DOCUMENT_BUCKET, region_name)
```

## Long-Term Solutions

### 1. Robust Textract-Only Processing
```python
def process_document_textract_only(document_uuid: str, s3_uri: str):
    """Use ONLY Textract - no fallback to local OCR"""
    
    # 1. Verify document exists in database first
    if not document_exists_in_db(document_uuid):
        create_document_record(document_uuid)
    
    # 2. Submit to Textract with proper error handling
    try:
        job_id = submit_to_textract(s3_uri, document_uuid)
    except InvalidS3ObjectException:
        # Fix region mismatch
        job_id = submit_to_textract_cross_region(s3_uri, document_uuid)
    
    # 3. No fallback - fail gracefully
    if not job_id:
        mark_document_failed(document_uuid, "Textract submission failed")
        return
    
    # 4. Poll for results
    schedule_textract_polling(document_uuid, job_id)
```

### 2. Pre-Processing Validation
```python
def validate_before_processing(document_uuid: str, file_path: str):
    """Validate all prerequisites before attempting OCR"""
    
    checks = {
        'document_exists': check_document_in_db(document_uuid),
        'project_exists': check_project_exists(),
        'redis_metadata': check_redis_metadata(document_uuid),
        's3_accessible': check_s3_access(file_path),
        'file_size_ok': check_file_size(file_path) < 500,  # MB
    }
    
    failed_checks = [k for k, v in checks.items() if not v]
    if failed_checks:
        raise PrerequisiteError(f"Failed checks: {failed_checks}")
```

### 3. Memory-Safe Architecture
```python
# Celery worker configuration
CELERY_WORKER_MAX_MEMORY_PER_CHILD = 512 * 1024  # 512MB
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_TIME_LIMIT = 300  # 5 minutes

# Task memory limits
@app.task(memory_limit='256MB')
def process_with_memory_limit():
    pass
```

### 4. Circuit Breaker Pattern
```python
class TextractCircuitBreaker:
    def __init__(self, failure_threshold=5, reset_timeout=300):
        self.failures = defaultdict(int)
        self.last_failure = defaultdict(float)
        self.threshold = failure_threshold
        self.timeout = reset_timeout
    
    def can_process(self, document_uuid):
        if self.failures[document_uuid] >= self.threshold:
            if time.time() - self.last_failure[document_uuid] < self.timeout:
                return False
        return True
    
    def record_failure(self, document_uuid):
        self.failures[document_uuid] += 1
        self.last_failure[document_uuid] = time.time()
```

## Implementation Priority

1. **IMMEDIATE (Prevent OOM)**
   - Disable Tesseract fallback for files > 50MB
   - Add memory limits to Celery workers
   - Implement circuit breaker for failed documents

2. **URGENT (Fix Textract)**
   - Create default project in database
   - Fix document creation with proper FK references
   - Ensure Redis metadata creation
   - Fix region configuration

3. **IMPORTANT (Long-term stability)**
   - Implement pre-processing validation
   - Add comprehensive error boundaries
   - Monitor memory usage proactively
   - Set up alerts for OOM conditions

## Verification Steps

1. **Test Document Creation**
   ```bash
   # Verify project exists
   psql -c "SELECT * FROM projects"
   
   # Test document creation
   python -c "from scripts.db import create_document; create_document('test-uuid', 'test.pdf')"
   ```

2. **Test Textract Direct**
   ```bash
   # Test Textract without fallback
   AWS_DEFAULT_REGION=us-east-1 python scripts/test_textract_direct.py
   ```

3. **Monitor Memory Usage**
   ```bash
   # Watch for memory spikes
   watch -n 1 'free -h; ps aux | grep -E "(celery|pdftoppm)" | grep -v grep'
   ```

## Success Criteria

1. Zero OOM events
2. Textract processes 100% of PDFs (no fallback)
3. Memory usage stays below 80% capacity
4. All documents have database records before processing
5. Circuit breaker prevents cascade failures

## Conclusion

The OOM crash was caused by a cascade failure:
1. Documents couldn't be created in database (missing project)
2. Textract was never attempted (validation failed)
3. System fell back to memory-intensive local OCR
4. Multiple concurrent failures exhausted memory

The solution is to fix the prerequisites so Textract can work properly, and add safety mechanisms to prevent memory-intensive fallbacks.