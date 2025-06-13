# Context 321: Pipeline Fixes Implemented

## Summary

Fixed two critical issues blocking document processing:

### 1. OCR S3 File Path Issue (✅ Fixed)
**Problem**: OCR task expected S3 URIs but received S3 keys
**Solution**: Added logic in `extract_text_from_document` to convert S3 keys to full URIs

```python
# Convert "documents/uuid.pdf" to "s3://bucket-name/documents/uuid.pdf"
if not file_path.startswith('s3://'):
    if file_path.startswith('documents/') or '/' in file_path:
        from scripts.config import S3_PRIMARY_DOCUMENT_BUCKET
        file_path = f"s3://{S3_PRIMARY_DOCUMENT_BUCKET}/{file_path}"
```

### 2. OCR Cache Return Issue (✅ Fixed)  
**Problem**: When OCR results were cached, the entire dict was passed to chunking instead of just text
**Solution**: Modified cache return to trigger pipeline continuation properly

```python
if cached_result:
    # Continue the pipeline with cached text
    continue_pipeline_after_ocr.apply_async(
        args=[document_uuid, cached_result['text']]
    )
```

## Current Pipeline Status

Testing shows:
- ✅ OCR: Successfully extracts text (3,278 characters)
- ✅ Chunking: Creates 4 chunks successfully
- ✅ Entity Extraction: Extracts 8 entities
- ⚠️ Entity Resolution: Creates canonical entities but doesn't save to DB
- ❌ Relationship Building: Not triggered (no canonical entities found)
- ❌ Pipeline Completion: Never reached

## Remaining Issues

### Canonical Entity Persistence
- Resolution creates 7 canonical entities correctly
- `save_canonical_entities_to_db` function works when tested directly
- But canonical entities aren't being saved during pipeline execution
- This blocks relationship building and completion

### Root Cause Analysis
The issue appears to be in the task execution flow where:
1. Canonical entities are created in memory
2. The save function is called but may be failing silently
3. The pipeline continues without canonical entities
4. Relationship building is skipped due to empty canonical entities

## Next Steps

1. Add better error logging to canonical entity saving
2. Ensure transaction commits properly in Celery context  
3. Fix the pipeline continuation logic to handle missing canonical entities gracefully
4. Consider simplifying the entire flow by removing unnecessary caching layers