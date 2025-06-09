# Context 359: OCR API Fix Complete

## Date: 2025-01-06

### Problem Identified
The error "Document 4909739b-8f12-40cd-8403-04b8b1a79281 not found" was misleading. The document actually existed in the database, but the code was trying to access it incorrectly.

### Root Cause
In `scripts/pdf_tasks.py`, the `extract_text_from_document` function was treating the Pydantic model returned by `get_source_document()` as a dictionary:

```python
# WRONG - Dictionary access on Pydantic model
doc['s3_bucket'], doc['s3_key'], doc['id']
```

### Fix Applied
Changed to proper attribute access:

```python
# CORRECT - Attribute access on Pydantic model  
doc.s3_bucket, doc.s3_key, doc.id
```

### Verification
1. Created test script to verify document access
2. Confirmed document exists in database:
   - Document UUID: 4909739b-8f12-40cd-8403-04b8b1a79281
   - ID: 80
   - S3 Bucket: samu-docs-private-upload
   - S3 Key: documents/4909739b-8f12-40cd-8403-04b8b1a79281
   - Status: processing

3. Verified attribute access works correctly with minimal models

### Impact
This fix should resolve the OCR extraction failures caused by incorrect API usage. The document processing pipeline should now be able to proceed past the OCR stage.

### Next Steps
1. Monitor OCR task execution with the fix in place
2. Check for any other similar API mismatches in the codebase
3. Ensure all database model access uses proper attribute notation