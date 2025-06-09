# Context 351: Historical Context Review - Solutions to Current Issues

## Executive Summary

After reviewing historical context files around context_292-298, I found that we've encountered and solved these EXACT issues before. The problems we're facing now are well-documented with proven solutions.

## Issue 1: Database Record Not Created (Our Current Blocker)

### Historical Context (from context_296 & 298)
This is the **Celery Document Visibility Issue** - a transaction isolation problem between processes.

### Root Cause
- Test scripts create documents in one database transaction
- Celery workers use separate database connections with different transaction contexts
- Without proper commits, documents exist only in the test script's transaction

### The Missing Piece
From context_296:
```python
# The test scripts create documents but may not commit the transaction before submitting to Celery:
def create(self, table, model):
    data = self.serialize_for_db(model)
    result = insert_record(table, data)  # May not auto-commit
    return result
```

### Proven Solution (from context_298)
```python
# After creating document, ensure visibility:
doc = db_manager.create_source_document(doc_model)

# Force visibility verification
max_retries = 5
document_visible = False
for i in range(max_retries):
    # Create fresh connection for verification
    verify_db = DatabaseManager(validate_conformance=False)
    if verify_db.get_source_document(doc_uuid):
        document_visible = True
        break
    time.sleep(0.5)  # Wait 500ms between retries

if not document_visible:
    raise RuntimeError(f"Document {doc_uuid} not visible after {max_retries} attempts")

# NOW safe to submit to Celery
task = process_pdf_document.delay(doc_uuid, file_path, project_uuid)
```

## Issue 2: Column Name Mismatches

### Historical Context (from context_292)
- `project_id` vs `project_uuid`
- `filename` vs `file_name`
- No `ocr_status` column (use `textract_job_status`)

### Status in History
These were identified and resolved by using the actual schema columns.

## Issue 3: API Method Changes

### Not Found in Historical Context
The API changes we discovered (upload_document → upload_document_with_uuid_naming, redis.set → redis.set_cached) appear to be from the recent consolidation phase and weren't part of the historical issues.

## Issue 4: get_db() Context Manager

### Historical Pattern
The historical code uses direct session management:
```python
from scripts.rds_utils import DBSessionLocal
session = DBSessionLocal()
try:
    # operations
finally:
    session.close()
```

## Key Insights from Historical Context

### 1. The Pipeline WAS Working
From context_292: "Import Success Rate: 100%" - documents were being successfully created and stored.

### 2. The Main Blocker Was Textract Permissions
From context_292: The system successfully handled everything up to OCR, then failed on S3-Textract permissions.

### 3. Transaction Commits Are Critical
From context_296: "Without an explicit commit, the document exists only in the test script's transaction and is invisible to other connections."

### 4. Fresh Connections Matter
From context_298: Creating fresh database connections for verification ensures we're not seeing stale transaction data.

## Immediate Fix for Our Current Issue

Based on the historical solutions, here's what we need to do:

### 1. Fix the process_pdf_document Task
Ensure it properly commits after creating the document:

```python
# In pdf_tasks.py, in process_pdf_document:
# After creating the document
doc_created = self.db_manager.create_source_document(doc_model)

# Force commit
from scripts.rds_utils import DBSessionLocal
session = DBSessionLocal()
session.commit()
session.close()

# Verify visibility with fresh connection
verify_db = DatabaseManager(validate_conformance=False)
if not verify_db.get_source_document(document_uuid):
    raise ValueError(f"Document {document_uuid} not visible after creation")
```

### 2. Update Our Test Script
Add visibility verification before checking results:

```python
# In test_real_document_processing.py
# After submitting task, wait and verify
time.sleep(2)  # Give time for transaction to commit

# Use fresh connection to check
fresh_db = DatabaseManager(validate_conformance=False)
doc = fresh_db.get_source_document(doc_uuid)
if doc:
    print("✓ Document created and visible!")
```

### 3. Fix Column Names
Update all queries to use correct column names:
- `document_uuid` not `uuid`
- `file_name` not `filename`
- `textract_job_status` not `ocr_status`

## Validation from History

From context_292, the system achieved:
- **Import Success Rate**: 100%
- **Core Architecture**: Sound
- **Database Layer**: Working correctly
- **Only Blocker**: AWS Textract permissions

This confirms that once we fix the transaction commit issue, the pipeline should work up to the OCR stage.

## Next Steps

1. Apply the transaction commit fix from context_298
2. Use the visibility verification pattern before Celery submission
3. Update column names to match actual schema
4. Then tackle any remaining issues (likely Textract permissions)

The good news: **These are all solved problems with documented solutions!**