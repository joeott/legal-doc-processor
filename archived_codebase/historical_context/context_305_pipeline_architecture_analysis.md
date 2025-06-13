# Context 305: Pipeline Architecture Analysis and Chunking Failure Diagnosis

## Date: 2025-06-02
## Status: Critical Analysis for Pipeline Completion

## Executive Summary

The legal document processing pipeline uses a **cache-first architecture** where Redis serves as the primary data store during active processing, with results persisted to RDS after each stage completes. The current chunking failure is due to the OCR text being cached in Redis but **NOT** being persisted to the `raw_extracted_text` field in RDS.

## Architecture Overview

### Design Pattern: Cache-First Processing

```
Stage 1: OCR
  Textract → Redis Cache → RDS (raw_extracted_text)
                ↓
Stage 2: Chunking  
  Redis (text) → Process → Redis Cache → RDS (document_chunks)
                              ↓
Stage 3: Entity Extraction
  Redis (chunks) → Process → Redis Cache → RDS (entity_mentions)
                                ↓
Stage 4: Resolution
  Redis (entities) → Process → Redis Cache → RDS (canonical_entities)
                                   ↓
Stage 5: Relationships
  Redis (all data) → Process → Redis Cache → RDS (relationship_staging)
```

## Current Implementation Analysis

### Successfully Working Components

1. **OCR Task (`extract_text_from_document`)**
   - ✅ Submits Textract job
   - ✅ Stores job ID in database
   - ✅ Schedules polling task

2. **Polling Task (`poll_textract_job`)**  
   - ✅ Checks Textract job status
   - ✅ Retrieves OCR results
   - ✅ Caches results in Redis (3,278 characters cached)
   - ✅ Updates document status to SUCCEEDED
   - ✅ Triggers `continue_pipeline_after_ocr`
   - ❌ **MISSING**: Does NOT store text in `raw_extracted_text` field

3. **Pipeline Continuation (`continue_pipeline_after_ocr`)**
   - ✅ Receives text parameter
   - ✅ Retrieves project_uuid from Redis
   - ✅ Schedules chunking task
   - ❓ Passes text to chunking task

4. **Chunking Task (`chunk_document_text`)**
   - ✅ Validates inputs
   - ✅ Checks cache for existing chunks
   - ✅ Uses `simple_chunk_text` function
   - ❌ **FAILS**: Unknown reason (need logs)

### Root Cause Analysis

The polling task successfully extracts text and caches it but **does not persist it to the database**:

```python
# In poll_textract_job (line 871-876)
# Cache results
job_manager.cache_ocr_results(
    document_uuid, 
    result['text'], 
    result['metadata']
)

# Update document status  
job_manager.update_document_status(document_uuid, job_id, 'SUCCEEDED')

# MISSING: Should also update raw_extracted_text field!
```

The `update_document_status` only updates:
- textract_job_id
- textract_job_status  
- error_message
- updated_at

But NOT:
- raw_extracted_text
- ocr_completed_at
- ocr_provider

## Context 290 Analysis

Context 290 stated that Phase 4 testing was complete with automatic pipeline progression. However, this testing appears to have verified:
- Task registration and imports
- Presence of `apply_async` calls
- Worker configuration

But NOT:
- Actual end-to-end execution with real data
- Text persistence between stages
- Database field updates

## Diagnostic Plan

### 1. Immediate Fix: Update Polling Task
Add text persistence to `poll_textract_job`:

```python
# After caching results
# Store text in database
from sqlalchemy import text as sql_text
update_query = sql_text("""
    UPDATE source_documents 
    SET raw_extracted_text = :text,
        ocr_completed_at = NOW(),
        ocr_provider = 'AWS Textract'
    WHERE document_uuid = :doc_uuid
""")
session.execute(update_query, {
    'text': result['text'],
    'doc_uuid': str(document_uuid)
})
session.commit()
```

### 2. Investigate Chunking Failure
Check why chunking is failing even though text is passed:
- Check text worker logs for the specific error
- Verify `chunk_document_text` receives text parameter
- Check if conformance validation is blocking
- Verify chunk model creation

### 3. Verify Cache-to-Database Flow
Ensure each stage:
1. Reads from cache/previous stage output
2. Processes data
3. Stores results in cache
4. Persists to database
5. Updates document status fields

## Scripts Utilized in Pipeline

### Core Scripts (Successfully Used)
1. **scripts/pdf_tasks.py** - All task definitions
2. **scripts/textract_job_manager.py** - Textract integration
3. **scripts/cache.py** - Redis caching
4. **scripts/db.py** - Database operations
5. **scripts/celery_app.py** - Task queue configuration
6. **scripts/chunking_utils.py** - Text chunking functions

### Supporting Scripts
1. **scripts/config.py** - Environment configuration
2. **scripts/rds_utils.py** - RDS connection management
3. **scripts/s3_storage.py** - S3 file operations
4. **scripts/core/model_factory.py** - Pydantic model selection
5. **scripts/core/models_minimal.py** - Minimal model definitions

## Proposed Fix Implementation

### Step 1: Fix Text Persistence
Update `poll_textract_job` to store raw text in database.

### Step 2: Debug Chunking
1. Add detailed logging to chunking task
2. Check for conformance validation issues
3. Verify text is being passed correctly

### Step 3: Test Full Pipeline
1. Create new document
2. Monitor each stage completion
3. Verify data in both Redis and RDS

### Step 4: Update Monitoring
Enhance monitoring to show:
- Cache vs database status
- Field-level completion tracking
- Stage transition details

## Success Criteria

1. **OCR Stage**: Text stored in both Redis AND `raw_extracted_text` field
2. **Chunking Stage**: Chunks created and stored in `document_chunks` table
3. **Entity Stage**: Entities extracted and stored
4. **Resolution Stage**: Canonical entities created
5. **Relationship Stage**: Relationships identified
6. **Pipeline Complete**: All data persisted to RDS

## Conclusion

The pipeline architecture is sound but incomplete. The cache-first design improves performance, but the persistence layer is not fully implemented. The immediate fix is to ensure OCR text is stored in the database, not just cached. This will likely resolve the chunking failure and allow the pipeline to complete end-to-end.