# Context 182: Pipeline Error Analysis and Root Causes

## Summary
After cleaning all processing data and tracing a single document through the pipeline, we've identified the root causes of the 95% failure rate.

## Key Findings

### 1. S3 Bucket Configuration Issue (FIXED)
- **Problem**: Documents had S3 keys but `s3_bucket` field was NULL
- **Impact**: 714 documents couldn't be accessed
- **Fix Applied**: Updated all documents with `S3_PRIMARY_DOCUMENT_BUCKET` value
- **Result**: S3 file access now working

### 2. Celery Queue Mismatch
- **Problem**: Tasks submitted to 'ocr_processing' queue, but workers listen to 'ocr'
- **Impact**: Tasks remain in PENDING state forever
- **Fix**: Submit tasks to correct queue names matching worker configuration

### 3. File Type Detection Mismatch (CRITICAL)
- **Problem**: OCR task expects file extensions (.pdf, .docx) but receives MIME types (application/pdf)
- **Error**: `ValueError: Unsupported file type: application/pdf`
- **Location**: `scripts/celery_tasks/ocr_tasks.py` - file type validation
- **Impact**: All documents fail at OCR stage

### 4. Processing Status Tracking
- **Success Path**: pending → pending_ocr → ocr_processing → text_processing → completed
- **Current State**: Documents reach ocr_processing then fail with file type error

## Error Trace Details

Document: `5699e75d-1a44-45ae-b1bf-48dc8ba6de84` (IMG_0792.pdf)
```
1. Document found in Supabase ✓
2. S3 file verified (2.4MB PDF) ✓
3. Celery task submitted ✓
4. Task picked up by worker ✓
5. OCR processing started ✓
6. Failed with: ValueError: Unsupported file type: application/pdf ✗
```

## Root Cause Analysis

### File Type Handling Inconsistency
The system stores file types in multiple formats:
- Database: MIME types (application/pdf, image/jpeg, etc.)
- OCR Task: Expects extensions (.pdf, .jpg, etc.)
- Validation: Doesn't handle MIME type → extension conversion

### Data Sample
```
Documents by File Type (from database):
- application/pdf: 370 documents
- application/msword: 6 documents
- application/vnd.openxmlformats...: 27 documents
- image/jpeg: 247 documents
- image/png: 58 documents
```

## Immediate Fixes Required

### 1. Fix File Type Detection in OCR Task
```python
# In process_ocr function, convert MIME type to extension
mime_to_ext = {
    'application/pdf': '.pdf',
    'application/msword': '.doc',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx',
    'image/jpeg': '.jpg',
    'image/png': '.png',
    # etc.
}
```

### 2. Update Import Process
- Store both MIME type and file extension
- Use consistent format across pipeline
- Add validation at import time

### 3. Fix Queue Names
- Ensure all task submissions use correct queue names
- Update any hardcoded 'ocr_processing' to 'ocr'

## Verification Steps

After fixes:
1. Reset test document status
2. Resubmit to pipeline
3. Monitor each stage completion
4. Verify chunks, entities, and relationships created

## Next Steps

1. **Immediate**: Fix file type validation in OCR task
2. **Short-term**: Update import process for consistency
3. **Long-term**: Add comprehensive error recovery

## Success Metrics
- Current: 4.6% success (36/776 documents)
- After file type fix: Expected 50%+ success
- After all fixes: Target 90%+ success

The good news is that the infrastructure is working correctly - documents are flowing through the pipeline, workers are processing tasks, and S3 storage is accessible. The failures are due to data format mismatches that can be fixed quickly.