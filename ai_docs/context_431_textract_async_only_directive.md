# Context 431: Textract Async-Only Processing Directive

## Date: June 5, 2025

## Critical Production Requirement

**ALL documents must be submitted to AWS Textract using asynchronous PDF processing ONLY.** This is a fundamental architectural decision based on:

1. **Performance**: Async processing is faster for production volumes
2. **Cost**: Textract is significantly cheaper than vision LLMs
3. **Reliability**: Async processing handles larger documents better
4. **Document Nature**: Production documents are text-based PDFs, NOT scanned images

## Current Problems Identified

### 1. Incorrect Scanned PDF Detection
The system incorrectly assumes PDFs are "scanned" when:
- `detect_document_text` returns `UnsupportedDocumentException`
- Any error occurs during initial detection
- The `_is_scanned_pdf` method defaults to `True` on error

### 2. Failed PDF-to-Image Conversion
When a PDF is (incorrectly) identified as scanned:
- System attempts to convert PDF to images using PyMuPDF
- PyMuPDF fails with library loading errors
- Entire OCR process fails before reaching Textract

### 3. Inappropriate Fallback Behavior
Current fallback chain:
1. Try Textract async → 
2. On "scanned" detection → Try image conversion → 
3. On failure → Try Tesseract → 
4. Complete failure

This is wrong because our documents should ONLY use step 1.

## Required Changes

### 1. Environment Configuration
```bash
# MANDATORY settings for production
export ENABLE_SCANNED_PDF_DETECTION=false
export SKIP_TESSERACT_FALLBACK=true
export TEXTRACT_FORCE_ASYNC=true
export DISABLE_PDF_TO_IMAGE_CONVERSION=true
```

### 2. Code Modifications Needed

#### A. textract_utils.py
```python
# In start_document_text_detection_v2:
# REMOVE or bypass:
- is_scanned = self._is_scanned_pdf(s3_bucket, s3_key)
- if is_scanned: ... (entire block)

# ENSURE:
- Always use textractor.start_document_text_detection()
- Never call _convert_pdf_to_images_s3()
- Never process as "scanned PDF"
```

#### B. pdf_tasks.py (extract_text_from_document)
```python
# REMOVE or disable:
- Tesseract fallback logic
- Local file processing paths
- Any "scanned PDF" handling

# ENSURE:
- S3 documents go directly to Textract async
- No image conversion attempts
- Clear error messages if Textract fails
```

#### C. Error Handling
```python
# When Textract returns UnsupportedDocumentException:
- DO NOT assume it's a scanned PDF
- DO NOT attempt image conversion
- LOG the error and fail fast
- Return clear error: "Document format not supported by Textract"
```

### 3. Validation Points

Before submitting to Textract, validate:
1. ✅ Document is in S3 (required for async)
2. ✅ Document has .pdf extension
3. ✅ File size is within Textract limits (500MB)
4. ❌ Do NOT check if PDF is "scanned"
5. ❌ Do NOT prepare for image conversion

## Implementation Strategy

### Phase 1: Immediate Fixes
1. Set `ENABLE_SCANNED_PDF_DETECTION=false` in environment
2. Add early return in `_is_scanned_pdf` to always return `False`
3. Comment out scanned PDF processing blocks

### Phase 2: Clean Implementation
1. Create `textract_async_only.py` wrapper that:
   - Only accepts S3 URLs
   - Only uses async processing
   - No fallbacks, no conversions
   
2. Modify `extract_text_from_document` to use new wrapper

3. Remove dependencies:
   - PyMuPDF (fitz)
   - pdf2image
   - Tesseract-related code

### Phase 3: Testing Protocol

#### Test Setup
```bash
# Environment
export ENABLE_SCANNED_PDF_DETECTION=false
export SKIP_PDF_PREPROCESSING=true
export FORCE_PROCESSING=true
export TEXTRACT_FORCE_ASYNC=true

# Start fresh workers
celery -A scripts.celery_app worker --loglevel=info
```

#### Test Execution
1. Submit single document
2. Verify Textract job starts immediately
3. Confirm NO image conversion attempts
4. Monitor async job completion
5. Validate text extraction results

#### Success Criteria
- ✅ All PDFs submitted via async Textract
- ✅ No PyMuPDF errors
- ✅ No "scanned PDF" detection logs
- ✅ No Tesseract fallback attempts
- ✅ Clear Textract job IDs in logs
- ✅ Successful text extraction

## Monitoring Requirements

### Log Patterns to Watch For

#### Good (Expected)
```
INFO: Starting Textract job using Textractor for s3://...
INFO: Textract job started via Textractor. JobId: xxx
INFO: Textract job xxx completed successfully
```

#### Bad (Must Not Appear)
```
WARNING: Error detecting if PDF is scanned
INFO: Detected scanned PDF, processing synchronously
INFO: Converting PDF to images
ERROR: Error converting PDF to images
WARNING: Textract failed for xxx, trying Tesseract
```

## Performance Expectations

With async-only Textract:
- **Submission Time**: < 2 seconds per document
- **Processing Time**: 10-60 seconds depending on size
- **Success Rate**: > 95% for standard PDFs
- **Parallel Capacity**: 100+ concurrent jobs

## Cost Implications

Textract async pricing (as of 2025):
- First 1M pages: $1.50 per 1000 pages
- Text extraction only (no forms/tables)
- Significantly cheaper than:
  - Tesseract (compute costs)
  - Vision LLMs ($10+ per 1000 pages)
  - Image conversion + processing

## Next Steps for Production Testing

1. **Immediate Actions**
   ```bash
   # Set environment
   export ENABLE_SCANNED_PDF_DETECTION=false
   
   # Restart workers
   ps aux | grep celery | awk '{print $2}' | xargs kill -9
   celery -A scripts.celery_app worker --loglevel=info &
   
   # Run single document test
   python3 batch_performance_test.py
   ```

2. **Code Quick Fix**
   - Add `return False` at start of `_is_scanned_pdf` method
   - Disable Tesseract fallback in `extract_with_fallback`

3. **Verification**
   - Check Celery logs for proper async submission
   - Verify no image conversion attempts
   - Confirm Textract job IDs are created

4. **Full Pipeline Test**
   - Process 1, 3, 10, 20 documents
   - Measure timing for each stage
   - Validate complete pipeline flow

## Conclusion

The system must treat ALL documents as text-based PDFs suitable for Textract async processing. Any deviation from this path (scanned detection, image conversion, Tesseract fallback) is a bug that must be fixed. This approach ensures optimal performance, cost efficiency, and reliability for production document processing.