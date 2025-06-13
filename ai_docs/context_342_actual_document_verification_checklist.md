# Context 342: Actual Document Verification Checklist

## Document Processing Verification Checklist

This checklist validates the complete document processing pipeline using actual legal documents from our sample data.

## Test Documents Selected

### Primary Test Document
- **File**: `Paul, Michael - Wombat Corp Disclosure Stmt 10-23-24.pdf`
- **Size**: 102KB
- **Type**: Legal disclosure statement
- **Path**: `/opt/legal-doc-processor/input_docs/Paul, Michael (Acuity)/Paul, Michael - Wombat Corp Disclosure Stmt 10-23-24.pdf`

### Secondary Test Documents (for batch testing)
1. `Paul, Michael - Plaintiff Acuity Disclosure Stmt 9-20-24.pdf` (125KB)
2. `Paul, Michael - Lora Prop Disclosure Stmt 10-21-24.pdf` (149KB)
3. `Paul, Michael - Wombat Answer and Counterclaim 1-2-25.pdf` (121KB)

## Pre-Test Verification

### ✅ Environment Setup
- [ ] Redis is running and accessible
- [ ] PostgreSQL database is accessible
- [ ] AWS credentials are configured
- [ ] S3 bucket is accessible
- [ ] Celery workers are running
- [ ] All environment variables are set

### ✅ System State
- [ ] No stuck documents in processing
- [ ] Redis cache is clean or warmed up
- [ ] Database has project records
- [ ] Monitoring is active

## Phase 1: Single Document Processing

### 1.1 Document Upload & Initialization
**Success Criteria:**
- [ ] Document uploads to S3 successfully
- [ ] Database record created with correct metadata
- [ ] Initial processing task triggered
- [ ] Document state set to "processing"

**Validation Commands:**
```bash
# Check S3 upload
aws s3 ls s3://${S3_PRIMARY_DOCUMENT_BUCKET}/ | grep "Wombat Corp Disclosure"

# Check database record
python scripts/check_document_status.py <document_uuid>

# Check Redis state
python scripts/check_redis_state.py <document_uuid>
```

### 1.2 OCR Processing (Textract)
**Success Criteria:**
- [ ] Textract job submitted successfully
- [ ] Job ID persisted in database
- [ ] Async polling initiated
- [ ] Raw text extracted (>90% accuracy)
- [ ] OCR results cached in Redis

**Validation:**
- [ ] Check processing_tasks table for Textract job
- [ ] Verify OCR cache key exists
- [ ] Validate extracted text quality

### 1.3 Text Chunking
**Success Criteria:**
- [ ] Document chunked into semantic segments
- [ ] Chunks between 1000-4000 characters
- [ ] Chunk overlap configured (200 chars)
- [ ] All chunks stored in database
- [ ] Chunk list cached in Redis

**Validation:**
- [ ] Count chunks in document_chunks table
- [ ] Verify chunk boundaries are logical
- [ ] Check chunk cache keys

### 1.4 Entity Extraction
**Success Criteria:**
- [ ] Entities extracted from each chunk
- [ ] Entity types identified (PERSON, ORG, DATE, LOCATION)
- [ ] Confidence scores recorded
- [ ] Entity mentions stored in database
- [ ] Results cached per chunk

**Expected Entities (for Wombat disclosure):**
- [ ] Paul, Michael (PERSON)
- [ ] Wombat Corp (ORG)
- [ ] Acuity (ORG)
- [ ] Dates from document

### 1.5 Entity Resolution
**Success Criteria:**
- [ ] Duplicate entities merged
- [ ] Canonical entities created
- [ ] Similarity scores > 0.85 for matches
- [ ] Cross-references maintained
- [ ] Resolution results cached

**Validation:**
- [ ] Count canonical entities vs raw mentions
- [ ] Verify "Paul, Michael" variants resolved
- [ ] Check organization name variations

### 1.6 Relationship Building
**Success Criteria:**
- [ ] Entity co-occurrences identified
- [ ] Relationships staged for graph
- [ ] Relationship types classified
- [ ] Confidence scores assigned
- [ ] Graph data exportable

### 1.7 Pipeline Finalization
**Success Criteria:**
- [ ] Document status = "completed"
- [ ] Processing time < 5 minutes
- [ ] All caches populated
- [ ] No orphaned tasks
- [ ] Completion timestamp recorded

## Phase 2: Batch Processing (5 Documents)

### 2.1 Sequential Batch Test
**Documents:** First 5 disclosure statements
**Success Criteria:**
- [ ] All 5 documents complete successfully
- [ ] Processing rate > 2 documents/minute
- [ ] No memory leaks
- [ ] Cache hit rate > 30% after first doc
- [ ] Database connections stable

### 2.2 Concurrent Batch Test
**Configuration:** 3 workers, 5 documents
**Success Criteria:**
- [ ] Concurrent processing without conflicts
- [ ] 3x speedup vs sequential
- [ ] No race conditions
- [ ] Proper task distribution
- [ ] All documents complete

## Phase 3: Data Quality Validation

### 3.1 OCR Accuracy
**Success Criteria:**
- [ ] > 95% word accuracy on typed text
- [ ] > 85% accuracy on handwritten portions
- [ ] Proper paragraph detection
- [ ] Table structure preserved
- [ ] No garbled text blocks

### 3.2 Entity Extraction Quality
**Success Criteria:**
- [ ] > 90% recall on person names
- [ ] > 85% recall on organizations
- [ ] > 80% precision (low false positives)
- [ ] Dates properly formatted
- [ ] Legal terms identified

### 3.3 Chunking Quality
**Success Criteria:**
- [ ] No sentences split mid-word
- [ ] Logical section boundaries
- [ ] Headers preserved with content
- [ ] Lists kept together
- [ ] Signature blocks intact

## Phase 4: Performance Metrics

### 4.1 Processing Speed
**Target Metrics:**
- [ ] OCR: < 30 seconds per page
- [ ] Entity Extraction: < 5 seconds per chunk
- [ ] Entity Resolution: < 10 seconds per document
- [ ] Total Pipeline: < 3 minutes for 5-page document

### 4.2 Resource Usage
**Acceptable Limits:**
- [ ] Memory: < 1GB per worker
- [ ] CPU: < 80% sustained
- [ ] Database connections: < 20 active
- [ ] Redis memory: < 500MB
- [ ] S3 API calls: < 50 per document

## Phase 5: Error Handling

### 5.1 Failure Recovery
**Test Scenarios:**
- [ ] Worker crash during processing
- [ ] Database connection timeout
- [ ] Redis connection lost
- [ ] S3 upload failure
- [ ] Textract API error

**Success Criteria:**
- [ ] Automatic retry initiated
- [ ] No data loss
- [ ] Clear error messages
- [ ] Recovery within 5 minutes
- [ ] Monitoring alerts triggered

## Phase 6: End-to-End Validation

### 6.1 Business Value Metrics
**Key Questions:**
- [ ] Can we find all mentions of "Wombat Corp"?
- [ ] Are all parties correctly identified?
- [ ] Can we trace document relationships?
- [ ] Is the data searchable?
- [ ] Are legal deadlines extractable?

### 6.2 Fitness for Function
**Core Requirements:**
- [ ] Documents fully text-searchable
- [ ] Entities linked across documents
- [ ] Chronology reconstructable
- [ ] Key facts extractable
- [ ] Export-ready for litigation

## Monitoring Commands

```bash
# Live monitoring
python scripts/cli/monitor.py live

# Check specific document
python scripts/check_document_status.py <doc_uuid>

# View processing logs
python scripts/monitor_logs.py --document <doc_uuid>

# Check worker status
celery -A scripts.celery_app inspect active

# Database queries
psql -c "SELECT * FROM source_documents WHERE file_name LIKE '%Wombat%'"
psql -c "SELECT COUNT(*) FROM document_chunks WHERE document_uuid = '<uuid>'"
psql -c "SELECT * FROM canonical_entities WHERE entity_name LIKE '%Paul%'"
```

## Success Summary

**Overall Pipeline Success Criteria:**
- ✅ 100% document completion rate
- ✅ < 5% error rate
- ✅ > 90% entity extraction accuracy
- ✅ < 3 minute processing time per document
- ✅ All data queryable and exportable

**Go/No-Go Decision:**
- If > 95% of criteria met: **GO for production**
- If 85-95% criteria met: **CONDITIONAL GO with monitoring**
- If < 85% criteria met: **NO GO - fix issues first**

## Test Execution Script

Create `scripts/verify_actual_documents.py` to automate this checklist.