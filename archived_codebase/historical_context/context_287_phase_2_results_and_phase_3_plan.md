# Phase 2 Test Results and Phase 3 Testing Plan

## Date: 2025-01-06

## Phase 2 Test Execution Results

### Overview
Phase 2 of the minimal models testing focused on database connection and document creation capabilities. The tests were designed to verify that the system can operate without conformance validation errors when using minimal models.

### Test Results Summary

#### Test 2.1: Database Connection Without Conformance ✅
**Status**: PASSED

- Successfully created DatabaseManager instance with `validate_conformance=False`
- Conformance validation was properly bypassed with warning messages
- No conformance errors encountered
- Appropriate warnings displayed: "CONFORMANCE VALIDATION BYPASSED - FOR TESTING ONLY"

#### Test 2.2: Document Creation with Minimal Models ✅
**Status**: PASSED

```
Creating document with UUID: ddf21870-1eb0-4e70-9ee7-ae9c982b2c5e
Using model: SourceDocumentMinimal
Document model has 18 fields (minimal)
✓ Document created: ddf21870-1eb0-4e70-9ee7-ae9c982b2c5e
  - Database ID: 39
✓ Document retrieved from database
  - Status: pending
```

Key achievements:
- Minimal model (`SourceDocumentMinimal`) used successfully
- Document created in database without validation errors
- Document retrieved successfully using the same minimal model
- Model factory pattern working correctly to select minimal vs full models

### Key Implementation Updates

1. **Model Factory Integration**: Updated `scripts/db.py` to use the model factory pattern:
   ```python
   from scripts.core.model_factory import (
       get_source_document_model,
       get_chunk_model,
       get_entity_mention_model,
       get_canonical_entity_model
   )
   ```

2. **Environment Configuration**: Added minimal model flags to `.env`:
   ```
   USE_MINIMAL_MODELS=true
   SKIP_CONFORMANCE_CHECK=true
   ```

3. **Field Compatibility**: Confirmed minimal models have essential fields only (18 fields vs 40+ in full model)

## Phase 3 Testing Plan - Async OCR Tests

### Objectives
According to context_285, Phase 3 aims to verify:
1. OCR tasks submit without blocking (Criterion #4)
2. Textract job IDs are tracked in the database (Criterion #5)
3. Redis state management handles async operations (Criterion #6)

### Test Plan Details

#### Test 3.1: OCR Task Submission (30 minutes)
**Purpose**: Verify OCR tasks return immediately with async job tracking

**Steps**:
1. Submit document for OCR processing via `extract_text_from_document`
2. Verify task returns immediately (within 2 seconds)
3. Confirm response contains `status: processing` and `job_id`
4. Save Textract job ID for subsequent tests

**Expected Outcome**:
- Task submission completes without timeout
- Immediate return with processing status
- Textract job ID provided

#### Test 3.2: Textract Job Tracking
**Purpose**: Verify Textract job details are persisted in database

**Steps**:
1. Query source_documents table for test document
2. Verify textract_job_id field is populated
3. Check textract_job_status field
4. Confirm textract_start_time is set

**Expected Outcome**:
- Database contains Textract job tracking fields
- Job ID matches submission response
- Status reflects processing state

#### Test 3.3: Redis State Verification
**Purpose**: Confirm Redis tracks document processing state

**Steps**:
1. Check Redis for document state key
2. Verify state structure includes pipeline and OCR sections
3. Confirm OCR status is "processing"
4. Verify job_id is stored in metadata

**Expected Outcome**:
- Redis contains comprehensive state tracking
- State properly serialized with enum values
- Job metadata preserved

### Current Blockers

1. **Celery Worker Startup**: Workers need to be running for async task execution
   - Issue: Missing OPENAI_API_KEY environment variable
   - Solution: Ensure all required environment variables are loaded

2. **Document Lookup**: Initial OCR submission showed "Document not found" error
   - Likely cause: Worker using different database connection or model
   - Solution: Ensure workers use same minimal model configuration

### Next Steps

1. **Environment Setup**:
   ```bash
   # Ensure all environment variables are loaded
   source load_env.sh
   export OPENAI_API_KEY="<key>"
   
   # Start Celery worker with minimal models
   celery -A scripts.celery_app worker --loglevel=info
   ```

2. **Run Phase 3 Tests**:
   - Execute test_phase3_ocr_submission.py
   - Monitor worker logs for async processing
   - Verify database and Redis state updates

3. **Success Criteria**:
   - No blocking on OCR submission
   - Textract jobs tracked properly
   - Redis state management functional
   - Pipeline continues automatically

### Risk Mitigation

If Phase 3 encounters issues:
1. **Worker Issues**: Check worker logs for model loading errors
2. **Async Failures**: Verify textract_job_manager.py implementation
3. **State Issues**: Ensure Redis serialization handles enums properly

Phase 3 is critical for validating the async OCR implementation, which is essential for non-blocking document processing in the production environment.