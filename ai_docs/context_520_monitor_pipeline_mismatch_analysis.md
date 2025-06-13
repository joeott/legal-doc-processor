# Monitor vs Pipeline Mismatch Analysis

## Executive Summary

The monitor code and actual pipeline execution have significant discrepancies that are causing monitoring failures. The primary issue is a broken pipeline flow where tasks are being called with incorrect parameters, and the monitor is querying for data structures that don't match the actual implementation.

## Key Findings

### 1. **Critical Pipeline Flow Break**

**Issue**: The `chunk_document_text` task is being called immediately after `extract_text_from_document` completes, but without the required `text` parameter.

**Root Cause**: Found in `/opt/legal-doc-processor/scripts/batch_processor.py`. The batch processor is creating a Celery chain with incorrect task signatures:

```python
processing_chain = chain(
    app.signature('scripts.pdf_tasks.extract_text_from_document', args=[document_uuid, s3_url], immutable=True),
    app.signature('scripts.pdf_tasks.chunk_document_text', args=[document_uuid], immutable=True),  # MISSING TEXT PARAMETER!
    app.signature('scripts.pdf_tasks.extract_entities_from_chunks', args=[document_uuid], immutable=True),
    app.signature('scripts.pdf_tasks.resolve_entities_for_document', args=[document_uuid], immutable=True),
    app.signature('scripts.pdf_tasks.build_document_relationships', args=[document_uuid], immutable=True)
)
```

The `chunk_document_text` signature only passes `document_uuid`, but the function signature requires `(self, document_uuid: str, text: str, chunk_size: int = 1000, overlap: int = 200)`.

**Expected Flow**:
1. `extract_text_from_document` → starts Textract job → schedules `poll_textract_job`
2. `poll_textract_job` → waits for completion → gets text → calls `continue_pipeline_after_ocr`
3. `continue_pipeline_after_ocr` → calls `chunk_document_text` with actual text

**Actual Flow** (broken):
1. `extract_text_from_document` → starts Textract job
2. Something immediately calls `chunk_document_text` without text parameter
3. Task fails with: `TypeError: chunk_document_text() missing 1 required positional argument: 'text'`

### 2. **Deprecated Module References**

The system is still referencing deprecated modules:
- `scripts.cloudwatch_logger` - Module not found warnings in logs
- `scripts.core.*` imports may still exist in some places

### 3. **Redis Key Pattern Mismatches**

**Monitor expects**:
- Queue keys: `celery.{queue_name}` (e.g., `celery.ocr`, `celery.text`)
- Document state: `doc:state:{document_uuid}`

**Pipeline uses**:
- CacheKeys class with format methods
- Different prefixes for different databases (cache, batch, metrics)
- All using DB 0 (not separated into different Redis databases as planned)

### 4. **Database Schema Mismatches**

**Monitor queries** (from `_determine_processing_stage`):
```sql
-- Checks document_chunks table
SELECT COUNT(*) FROM document_chunks WHERE document_uuid = %s

-- Checks entity_mentions joined with document_chunks
SELECT COUNT(*) FROM entity_mentions em
JOIN document_chunks dc ON em.chunk_uuid = dc.chunk_uuid
WHERE dc.document_uuid = %s

-- Checks entity_relationships
SELECT COUNT(*) FROM entity_relationships er
JOIN entity_mentions em1 ON er.from_entity_id = em1.entity_id
JOIN document_chunks dc ON em1.chunk_uuid = dc.chunk_uuid
WHERE dc.document_uuid = %s
```

**Potential Issues**:
- Uses `entity_relationships` table (not `relationship_staging`)
- Joins assume specific foreign key relationships
- No error handling for missing tables/columns

### 5. **Task Tracking Inconsistencies**

**Processing Task Table**:
- Uses `document_id` (not `document_uuid`)
- Uses `task_type` (not `stage`)
- Monitor doesn't query this table for status

**Worker Logs Show**:
- Task tracking decorator creates records
- Updates status to completed/failed
- But monitor doesn't use this information

### 6. **Incorrect Pipeline Orchestration**

The batch_processor.py is using Celery chains with immutable signatures, which:
- Don't wait for async Textract jobs to complete
- Can't pass task outputs to the next task (immutable=True prevents this)
- Assume synchronous processing when OCR is actually asynchronous
- Use incorrect task signatures (missing required parameters)

### 7. **Enhanced Monitor Issues**

The enhanced monitor (`enhanced_monitor.py`) imports several modules that may not exist:
- `scripts.status_manager`
- `scripts.batch_processor`
- `scripts.validation` (OCRValidator, EntityValidator, PipelineValidator)

## Recommended Fixes

### 1. **Fix Pipeline Flow**
- Fix `batch_processor.py` to not use chains with immutable signatures
- Remove the direct chain from `extract_text_from_document` to `chunk_document_text`
- Let the async flow work: OCR → poll → continue_pipeline → chunk
- Either:
  - Use `process_pdf_document` as the entry point (which properly starts async OCR)
  - Or fix the chain to only include the initial OCR task, not the full pipeline

### 2. **Update Monitor Queries**
- Use `processing_tasks` table for real-time status
- Update table/column names to match actual schema
- Add proper error handling for missing data

### 3. **Standardize Redis Keys**
- Document and enforce consistent key patterns
- Use the CacheKeys class everywhere
- Consider implementing Redis database separation

### 4. **Remove Deprecated References**
- Remove all `scripts.core.*` imports
- Remove `scripts.cloudwatch_logger` references
- Update to use current module structure

### 5. **Add Pipeline Orchestration**
- Implement proper task result handling
- Use Celery's built-in chaining/linking features correctly
- Ensure async tasks complete before next stage

## Impact

These mismatches explain why:
- Documents get stuck after OCR (batch processor chain breaks)
- Monitor shows incorrect pipeline stages (querying wrong tables/fields)
- Tasks fail with missing parameter errors (incorrect task signatures in chains)
- Pipeline doesn't progress despite successful OCR (immutable signatures prevent data flow)

The primary issue is that `batch_processor.py` is trying to chain all tasks together synchronously, but the OCR process is asynchronous and requires polling. The immutable signatures also prevent task results from being passed to the next task.

## Additional Findings

### Task Decorator Issue
The `@track_task_execution` decorator has a parameter mismatch issue. It expects:
```python
def wrapper(self, document_uuid: str, *args, **kwargs):
```

But this consumes positional arguments incorrectly for tasks that have multiple required parameters like `chunk_document_text(self, document_uuid, text, ...)`.

### Working vs Broken Flows
**Working flow** (via `continue_pipeline_after_ocr`):
- OCR completes → poll_textract_job gets text → calls continue_pipeline_after_ocr with (document_uuid, text) → calls chunk_document_text with (document_uuid, text)

**Broken flow** (via batch_processor chain):
- batch_processor creates chain with immutable signatures → extract_text_from_document returns immediately with job_id → chain tries to call chunk_document_text with only document_uuid → fails with missing text parameter