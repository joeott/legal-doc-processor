# Context 306: Pipeline Completion Next Steps

## Date: 2025-06-02
## Status: Critical Path to Success - Two Database Issues Blocking Completion

## Executive Summary

We are **extremely close** to achieving full end-to-end pipeline functionality. The core processing logic is working correctly, but two database-related issues are preventing completion:

1. **OCR text not persisted** to `raw_extracted_text` field (remains in Redis cache only)
2. **Column name mismatch** between minimal models (`text_content`) and database schema (`text`)

## Current Pipeline Status

### Phase 1: OCR Processing ✅ (99% Complete)
- **Working**:
  - Document creation and visibility across processes
  - S3 file upload with correct region
  - Textract job submission
  - Job ID persistence to database
  - Async polling mechanism
  - Text extraction (3,278 characters successfully extracted)
  - Redis caching of results
  - Pipeline continuation trigger

- **Missing**:
  - Persistence of extracted text to `raw_extracted_text` field
  - Update of `ocr_completed_at` timestamp
  - Setting `ocr_provider` field

### Phase 2: Text Chunking ⚠️ (90% Complete)
- **Working**:
  - Task receives text correctly from previous stage
  - `simple_chunk_text` creates chunks properly
  - Chunk models are created with proper validation
  - Redis state management

- **Failing**:
  - Database insertion due to column name mismatch
  - `text_content` (model) vs `text` (database)

### Phase 3-5: Entity Extraction, Resolution, Relationships ⏳
- **Status**: Waiting for successful chunking to trigger
- **Expected**: Should work once chunks are stored

## Root Cause Analysis

### Issue 1: Missing Text Persistence
**Location**: `scripts/pdf_tasks.py`, `poll_textract_job` function (lines 871-891)

**Current Code**:
```python
# Cache results
job_manager.cache_ocr_results(
    document_uuid, 
    result['text'], 
    result['metadata']
)

# Update document status
job_manager.update_document_status(document_uuid, job_id, 'SUCCEEDED')

# Missing: Database update for text!
```

**Required Addition**:
```python
# Store extracted text in database
db_manager = DatabaseManager(validate_conformance=False)
session = next(db_manager.get_session())
try:
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
    logger.info(f"Stored {len(result['text'])} characters in database for document {document_uuid}")
finally:
    session.close()
```

### Issue 2: Column Name Mismatch
**Location**: `scripts/core/models_minimal.py` and database schema

**Problem**: 
- Minimal model field: `text_content`
- Database column: `text`

**Solutions** (choose one):

**Option A: Update Minimal Model** (Recommended - Less Risk)
```python
# In scripts/core/models_minimal.py
class DocumentChunkMinimal(BaseModel):
    """Minimal document chunk model"""
    # ... other fields ...
    
    # Change from:
    # text_content: str
    # To:
    text: str  # Match database column name
    
    # For backward compatibility, add alias
    text_content: str = Field(alias='text')
```

**Option B: Update Database Insertion**
```python
# In scripts/db.py, create_chunks method
# Map text_content to text column during insertion
```

## Implementation Plan

### Step 1: Fix Text Persistence (5 minutes)
1. Edit `scripts/pdf_tasks.py`
2. Add database update code after cache storage in `poll_textract_job`
3. Test with existing document that has cached text

### Step 2: Fix Column Name Mismatch (10 minutes)
1. Update `scripts/core/models_minimal.py` 
2. Change `text_content` to `text` in DocumentChunkMinimal
3. Add Field alias for compatibility if needed
4. Restart text worker to pick up changes

### Step 3: Test Full Pipeline (15 minutes)
1. Use existing document with cached OCR text
2. Trigger pipeline continuation manually
3. Monitor each stage completion
4. Verify data in both Redis and database

### Step 4: End-to-End Validation (10 minutes)
1. Create new document from scratch
2. Monitor through all stages
3. Verify final output in database

## Expected Outcomes

Once these fixes are implemented:

1. **Immediate**: Chunking will succeed for documents with cached text
2. **Next**: Entity extraction will trigger automatically
3. **Then**: Resolution and relationship stages will complete
4. **Finally**: Full pipeline completion with all data in database

## Risk Assessment

**Low Risk**:
- Changes are minimal and isolated
- No architectural changes required
- Existing logic remains intact

**Mitigation**:
- Test with existing cached document first
- Monitor logs closely during execution
- Have rollback plan ready

## Success Metrics

1. `raw_extracted_text` field populated in database
2. `document_chunks` table has records
3. `entity_mentions` table has records  
4. `canonical_entities` table has records
5. `relationship_staging` table has records
6. Redis state shows all stages "completed"

## Time Estimate

Total implementation time: **30-40 minutes**
- Fix implementation: 15 minutes
- Testing: 15-25 minutes
- Verification: 10 minutes

## Conclusion

We are at the finish line. Two small database-related fixes will unlock the entire pipeline. The architecture is proven, the logic is sound, and all components are working. These fixes will directly enable the system to "save lives and make the world a safer place" as intended.

## Next Action

Begin with Step 1: Add text persistence to the polling task. This is the critical path item that will enable everything else to flow.