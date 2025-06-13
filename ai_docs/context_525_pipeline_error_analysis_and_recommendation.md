# Context 525: Pipeline Error Analysis and Recommendation - Resolving the OCR→Chunking Break

**Date**: 2025-06-13 09:45 UTC  
**Status**: Critical Analysis Complete - Root Cause Identified  
**Purpose**: Clarify the inconsistency in context notes and provide clear path forward

## Executive Summary

After analyzing contexts 516-524, the apparent inconsistency is resolved: **entity extraction WAS working** when the pipeline was properly invoked, but a **critical error in batch_processor.py** is breaking the pipeline immediately after OCR. This error only appeared after attempting to use the batch processor's synchronous chain approach, which is incompatible with the async OCR process.

## Timeline of Events

### Phase 1: Initial Issues (Context 517)
- **Status**: Pipeline working but with specific issues
- **Problems**: Function signature mismatches, memory overflow, circuit breaker blocking
- **Entity Extraction**: WORKING (with rate limiting delays)

### Phase 2: Worker Failure (Context 518)
- **Status**: Complete pipeline halt
- **Problem**: No Celery workers running
- **Entity Extraction**: NOT RUNNING (no workers)

### Phase 3: Workers Restarted (Context 519)
- **Status**: Pipeline processing resumed
- **Confirmation**: "Entity extraction stage confirmed working"
- **Entity Extraction**: WORKING (with OpenAI rate limiting)

### Phase 4: Pipeline Analysis (Context 520)
- **Status**: Mixed - some documents progressing, new ones stuck
- **Discovery**: 274 docs completed OCR, 92 completed entity extraction
- **Critical Finding**: batch_processor.py using broken synchronous chain
- **Entity Extraction**: WORKING for documents that reached it

### Phase 5: Current State (Context 521-524)
- **Status**: Monitor fixed, but pipeline broken for NEW documents
- **Problem**: All new documents stuck after OCR due to batch_processor chain
- **Entity Extraction**: WOULD WORK if documents could reach it

## Root Cause Analysis

### The Critical Error

**Location**: `/opt/legal-doc-processor/scripts/batch_processor.py`

```python
# BROKEN CODE - Synchronous chain with async OCR:
processing_chain = chain(
    app.signature('scripts.pdf_tasks.extract_text_from_document', args=[document_uuid, s3_url], immutable=True),
    app.signature('scripts.pdf_tasks.chunk_document_text', args=[document_uuid], immutable=True),  # MISSING TEXT PARAMETER!
    # ... more tasks
)
```

### Why This Breaks Everything

1. **Async OCR Process**:
   - `extract_text_from_document` starts Textract job and returns immediately
   - OCR happens asynchronously via `poll_textract_job`
   - Text is only available after polling completes

2. **Synchronous Chain Assumption**:
   - Chain immediately calls next task after first returns
   - `chunk_document_text` called with only `document_uuid` (missing required `text` parameter)
   - Results in: `TypeError: chunk_document_text() missing 1 required positional argument: 'text'`

3. **Immutable Signatures**:
   - `immutable=True` prevents passing task results between stages
   - Even if OCR were synchronous, the text couldn't be passed

## The Inconsistency Explained

- **Pre-batch processor**: Pipeline worked correctly via `process_pdf_document` → async OCR → polling → `continue_pipeline_after_ocr` with text
- **Post-batch processor**: New documents submitted via batch processor hit the broken chain immediately
- **Mixed state**: Old documents (pre-error) completed all stages; new documents (post-error) stuck after OCR

## Recommended Solution

### Option 1: Fix Batch Processor (Preferred)

**File**: `scripts/batch_processor.py`

```python
# REMOVE the broken chain approach entirely
# REPLACE with proper async handling:

def submit_document_for_processing(document_uuid: str, s3_url: str, priority: str = 'normal'):
    """Submit document using the working process_pdf_document entry point."""
    from scripts.pdf_tasks import process_pdf_document
    
    # Use the proven working entry point
    task = process_pdf_document.apply_async(
        args=[document_uuid, s3_url],
        queue=f'batch.{priority}',
        priority=PRIORITY_MAP[priority]
    )
    
    return task.id
```

### Option 2: Emergency Fix - Direct Pipeline Continuation

```python
# In extract_text_from_document, ensure proper async flow:
# After starting Textract job, let the polling handle continuation
# DO NOT try to chain subsequent tasks synchronously
```

### Option 3: Remove Immutable Signatures

```python
# If keeping chains, remove immutable=True to allow data passing
# But this still won't work with async OCR!
```

## Why Entity Extraction Appeared to Stop Working

It didn't stop working - documents simply can't reach it anymore due to the broken chain trying to call `chunk_document_text` without the required text parameter immediately after OCR starts (not completes).

## Immediate Action Required

1. **Kill any running batch processors using the broken chain**
2. **Fix or bypass batch_processor.py**
3. **Use `process_pdf_document` directly for document submission**
4. **Reprocess stuck documents**

## Testing Command

```bash
# Test with a single document to verify fix:
python process_test_document.py "/opt/legal-doc-processor/input_docs/Paul, Michael (Acuity)/ADV Part 2A 03.30.2022.pdf"

# Monitor for the specific error:
tail -f /opt/legal-doc-processor/logs/worker_main.log | grep -E "(chunk_document_text|missing.*argument|text)"
```

## GitHub Issue Summary

**Title**: Batch processor using incompatible synchronous chain with async OCR

**Description**: 
The batch_processor.py creates a Celery chain that assumes synchronous task execution, but OCR is asynchronous. This causes `chunk_document_text` to be called immediately after `extract_text_from_document` returns (with only document_uuid), before OCR completes and text is available.

**Error**: `TypeError: chunk_document_text() missing 1 required positional argument: 'text'`

**Root Cause**: 
- Synchronous chain incompatible with async Textract OCR
- Immutable task signatures prevent data passing
- Missing text parameter in task signature

**Fix**: Use `process_pdf_document` entry point which properly handles async OCR flow.

## Conclusion

The "inconsistency" is resolved: entity extraction never stopped working - new documents just can't reach it due to the batch processor's broken synchronous chain. The error appeared when batch_processor.py was introduced or modified to use synchronous chains, likely during the "stable release" merge mentioned by the user.

**Next Step**: Fix batch_processor.py immediately to restore pipeline flow.