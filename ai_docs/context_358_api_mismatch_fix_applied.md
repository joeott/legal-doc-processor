# Context 358: API Mismatch Fix Applied

## Date: 2025-01-06

### Issue Found
In `scripts/pdf_tasks.py`, the `extract_text_from_document` function was trying to access the SourceDocumentModel object as a dictionary:

```python
# WRONG - treating Pydantic model as dictionary
job_id = textract.start_document_text_detection(
    s3_bucket=doc['s3_bucket'],
    s3_key=doc['s3_key'],
    source_doc_id=doc['id'],
    document_uuid_from_db=document_uuid
)
```

### Fix Applied
Changed to proper attribute access:

```python
# CORRECT - using Pydantic model attributes
job_id = textract.start_document_text_detection(
    s3_bucket=doc.s3_bucket,
    s3_key=doc.s3_key,
    source_doc_id=doc.id,
    document_uuid_from_db=document_uuid
)
```

### Root Cause Analysis
This is a classic API mismatch where:
1. `DatabaseManager.get_source_document()` returns a `SourceDocumentModel` (Pydantic model)
2. The calling code was expecting a dictionary
3. This causes AttributeError when trying to use dictionary access on a Pydantic model

### Verification Needed
1. Check if document actually exists in database when the error occurs
2. Ensure proper transaction handling between document creation and OCR task
3. Test the fix with a real document processing flow

### Related Issues
- The error "Document not found" might be misleading - it could be failing at the dictionary access, not the lookup
- Need to verify all other places where database results are used to ensure consistent API usage