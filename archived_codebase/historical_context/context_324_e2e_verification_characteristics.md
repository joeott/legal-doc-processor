# Context 324: End-to-End Pipeline Verification Characteristics

## Verification Objectives

To achieve 99% pipeline success rate, we must verify each stage completes successfully and triggers the next stage properly.

## Stage-by-Stage Verification Criteria

### 1. OCR Extraction (Stage 1)
**Success Criteria:**
- ✅ Accepts S3 keys and converts to S3 URIs
- ✅ Submits async Textract job
- ✅ Polls for completion without blocking
- ✅ Extracts text (>100 characters expected)
- ✅ Caches results in Redis
- ✅ Stores raw text in database
- ✅ Triggers chunking stage

**Verification Points:**
- `source_documents.raw_extracted_text` is populated
- `source_documents.ocr_completed_at` is set
- Redis key `doc:ocr:{uuid}` exists
- Pipeline state shows `ocr: completed`

### 2. Text Chunking (Stage 2)
**Success Criteria:**
- ✅ Receives text string (not dict) from OCR
- ✅ Creates chunks of ~1000 chars with 100 char overlap
- ✅ Preserves word boundaries
- ✅ Stores chunks in `document_chunks` table
- ✅ Triggers entity extraction

**Verification Points:**
- `document_chunks` records created (typically 3-5 for test doc)
- Chunks have proper `char_start_index` and `char_end_index`
- Redis key `doc:chunks:{uuid}` exists
- Pipeline state shows `chunking: completed`

### 3. Entity Extraction (Stage 3)
**Success Criteria:**
- ✅ Processes each chunk
- ✅ Extracts PERSON, ORG, LOCATION, DATE entities only
- ✅ Creates entity mentions (stored in cache initially)
- ✅ Triggers standalone resolution task

**Verification Points:**
- Entity mentions created (typically 5-10 for test doc)
- Limited to allowed entity types
- Redis key `doc:entity_mentions:{uuid}` exists
- Pipeline state shows `entity_extraction: completed`

### 4. Entity Resolution (Stage 4)
**Success Criteria:**
- ✅ Uses standalone task (not PDFTask)
- ✅ Saves entity mentions to database if needed
- ✅ Performs fuzzy matching deduplication
- ✅ Creates canonical entities
- ✅ Updates mentions with canonical UUIDs
- ✅ Triggers relationship building

**Verification Points:**
- `entity_mentions` records in database
- `canonical_entities` records created
- `entity_mentions.canonical_entity_uuid` populated
- Deduplication rate typically 10-20%
- Pipeline state shows `entity_resolution: completed`

### 5. Relationship Building (Stage 5)
**Success Criteria:**
- ✅ Creates structural relationships only
- ✅ Links: Document→Project, Chunk→Document, Mention→Chunk, Mention→Canonical
- ✅ Stores in `relationship_staging` table
- ✅ Triggers pipeline finalization

**Verification Points:**
- `relationship_staging` records created
- At least 4 relationship types present
- Pipeline state shows `relationships: completed`

### 6. Pipeline Finalization (Stage 6)
**Success Criteria:**
- ✅ Updates document status to 'completed'
- ✅ Sets `processing_completed_at` timestamp
- ✅ Records final statistics
- ✅ Cleans up temporary cache data

**Verification Points:**
- `source_documents.status` = 'completed'
- `source_documents.processing_completed_at` is set
- Pipeline state shows `pipeline: completed`

## Key Metrics for 99% Success Rate

### Performance Targets:
- **OCR**: < 60 seconds for typical PDF
- **Chunking**: < 2 seconds
- **Entity Extraction**: < 10 seconds
- **Entity Resolution**: < 5 seconds
- **Relationship Building**: < 3 seconds
- **Total Pipeline**: < 90 seconds

### Error Tolerance:
- Each stage has 3 retry attempts
- Exponential backoff between retries
- Failed documents marked with clear error messages
- No silent failures allowed

## Test Document Characteristics

For verification, use documents with:
- 2,000-5,000 characters of text
- Mix of entity types (people, organizations, dates)
- Some duplicate entity mentions for deduplication testing
- Legal document structure (parties, dates, references)

## Verification Script Requirements

The end-to-end test should:
1. Submit document with clear initial state
2. Monitor each stage transition
3. Verify database and cache state at each stage
4. Report timing for each stage
5. Provide clear pass/fail for each criterion
6. Calculate overall success rate

## Success Indicators

A successful pipeline run shows:
- All 6 stages marked "completed" in order
- No stages marked "failed" or stuck in "processing"
- All expected database records created
- Proper data flow between stages
- Total time under 90 seconds

## Failure Patterns to Watch

Common issues that break the 99% target:
- OCR file path errors (fixed)
- Chunking receives dict instead of string (fixed)
- Entity resolution attribute errors (fixed)
- Missing canonical entities blocking relationships
- Pipeline not continuing after stage completion

## Compact Summary

**Fixed Issues:**
1. S3 path handling in OCR
2. Cache text extraction for chunking
3. Canonical entity persistence via standalone task

**Remaining Risks:**
1. Worker availability/memory
2. Network timeouts to AWS services
3. Database connection pool exhaustion

**Target State:**
- 99% of documents complete all 6 stages
- Clear error reporting for the 1% that fail
- Automatic recovery where possible