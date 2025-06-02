# Context 296: Celery-Textract Asynchronous Processing Analysis

## Executive Summary
The core issue is NOT that Textract runs asynchronously, but that Celery worker processes cannot see database records created by the test scripts. This is a database connection/transaction isolation issue, not a Textract async issue.

## Evidence of the Problem

### 1. Test Script Results
From `scripts/test_region_fix_complete.py`:
```
3. Creating database record...
   ✓ Document created in database

4. Verifying document in database...
   ✓ Document found: 320cfd73-ad09-492f-be84-4606ec7979f6
   
7. Monitoring task progress...
   ❌ Task failed!
   Error: Document 320cfd73-ad09-492f-be84-4606ec7979f6 not found in database
```

### 2. Synchronous Test Confirmation
From `scripts/test_ocr_sync.py`:
```
4. Verifying document exists...
   ✓ Document found in database
INFO:scripts.db:Source document lookup result: id=63 document_uuid=UUID('cd52cf50-ebdd-4d1a-8988-5ad578cc7db8')...
```

The document IS found when accessed directly from the same Python process, proving the issue is specific to Celery workers.

## Why This Is NOT a Textract Async Issue

### 1. The Failure Occurs Before Textract
Looking at `scripts/pdf_tasks.py` line 244-245:
```python
if not validate_document_exists(self.db_manager, document_uuid):
    raise ValueError(f"Document {document_uuid} not found in database")
```

The task fails at document validation, BEFORE any Textract API call is made. This proves Textract's async nature is irrelevant to the current failure.

### 2. Database Lookup Happens First
The `extract_text_from_document` task flow:
1. Validate conformance (line 232)
2. Validate inputs (line 235)
3. **Validate document exists in DB (line 244)** ← FAILS HERE
4. Update document state (line 248)
5. Submit to Textract (much later)

### 3. The Real Issue: Database Connection Isolation

#### Evidence from `scripts/db.py`:
```python
def __init__(self, validate_conformance: bool = True):
    # Each Celery task creates a new DatabaseManager instance
    self.pydantic_db = PydanticDatabase(serializer)
```

#### Evidence from `scripts/rds_utils.py`:
```python
def insert_record(table_name: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    db = DBSessionLocal()  # Gets connection from pool
    try:
        # ... execute insert ...
        db.commit()  # Line 252 - commits the transaction
```

## The Actual Problem

### 1. Different Database Connections
- Test script: Creates its own database connection/session
- Celery worker: Has its own database connection pool
- These are SEPARATE connection pools with different sessions

### 2. Transaction Visibility
Even though `insert_record()` commits at line 252, the committed data may not be immediately visible to other connections due to:
- PostgreSQL's MVCC (Multi-Version Concurrency Control)
- Connection pooling serving different physical connections
- Possible differences in transaction isolation levels

### 3. Why Synchronous Processing Would "Work"
Running synchronously would avoid the issue because:
```python
# All operations happen in the same Python process
db_manager = DatabaseManager()
doc = db_manager.create_source_document(doc_model)  # Same connection
result = db_manager.get_source_document(doc_uuid)   # Same connection
# Therefore, the document is always visible
```

## The Solution Path

### 1. Force Fresh Connections in Celery
Modify `scripts/pdf_tasks.py` to ensure fresh database state:
```python
def validate_document_exists(db_manager: DatabaseManager, document_uuid: str) -> bool:
    # Force a new connection/session
    db_manager = DatabaseManager(validate_conformance=False)  # New instance
    document = db_manager.get_source_document(document_uuid)
    return document is not None
```

### 2. Add Connection Pool Refresh
In `scripts/config.py`, add:
```python
DB_POOL_CONFIG = {
    'pool_pre_ping': True,  # Already set
    'pool_recycle': 3600,   # Already set
    'isolation_level': 'READ COMMITTED',  # Ensure consistent isolation
}
```

### 3. Verify Celery Uses Same Database URL
The logs show Celery IS using the correct URL:
```
INFO:scripts.config:EFFECTIVE_DATABASE_URL: postgresql://app_user:LegalDoc2025%5C%21Secure@database1.cuviucyodbeg.us-east-1.rds.amazonaws.com:5432/legal_doc_processing?sslmode=require
```

## Conclusion
The issue is NOT related to Textract's asynchronous processing. The document lookup fails before any OCR processing begins. The root cause is database connection isolation between the test script process and Celery worker processes. The solution is to ensure Celery workers get fresh database connections that can see recently committed data.