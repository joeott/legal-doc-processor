# Context 297: Scripts Required for Celery-Textract Async Analysis

## Problem Statement
The test scripts create documents in the database that are immediately visible to direct database queries, but Celery workers report "Document not found in database" when attempting to process the same documents. This may be related to:
1. Database transaction isolation between processes
2. Textract's asynchronous processing model
3. Connection pooling and session management
4. Timing issues between document creation and Celery task execution

## Critical Scripts for Analysis

### 1. Database Layer Scripts
- **`scripts/db.py`**
  - Contains `DatabaseManager.get_source_document()` method (line 505-514)
  - Shows how documents are looked up by UUID
  - Manages database sessions and connections

- **`scripts/rds_utils.py`**
  - Contains `select_records()` function used by get_source_document
  - Contains `insert_record()` function (line 223-252) that commits transactions
  - Handles database connection pooling via DBSessionLocal

- **`scripts/config.py`**
  - Defines database connection settings and pool configuration
  - Sets `EFFECTIVE_DATABASE_URL` and `DB_POOL_CONFIG`
  - Controls connection pooling parameters (pool_size=20, max_overflow=40)

### 2. Celery Task Scripts
- **`scripts/pdf_tasks.py`**
  - Contains `extract_text_from_document()` task (line 217)
  - Contains `validate_document_exists()` function (line 191-200)
  - Shows how Celery tasks initialize DatabaseManager instances
  - Implements async OCR pipeline flow

- **`scripts/celery_app.py`**
  - Defines Celery app configuration
  - Sets up task queues and routing
  - May affect how database connections are handled in worker processes

### 3. Test Scripts
- **`scripts/test_region_fix_complete.py`**
  - Creates documents and immediately verifies they exist
  - Shows document IS found when queried directly after creation
  - Submits Celery tasks that fail to find the same document

- **`scripts/test_ocr_sync.py`**
  - Attempted synchronous test that confirmed documents are visible outside Celery
  - Shows the issue is specific to Celery worker processes

- **`scripts/test_celery_db_lookup.py`**
  - Direct test of Celery's ability to query the database
  - Would show if Celery has any database access at all

### 4. Textract Integration Scripts
- **`scripts/textract_utils.py`**
  - Contains async Textract submission logic
  - May show if async processing affects database visibility

- **`scripts/ocr_extraction.py`**
  - Contains OCR extraction logic
  - Shows how documents are processed

### 5. Supporting Scripts
- **`scripts/enhanced_column_mappings.py`**
  - Contains column and table mappings
  - May affect how UUID lookups are performed

- **`scripts/cache.py`**
  - Redis caching layer
  - Could be caching stale or missing data

## Key Areas to Investigate

### 1. Transaction Isolation
- Check if `insert_record()` in `rds_utils.py` properly commits
- Verify if Celery workers use different transaction isolation levels
- Look for any deferred commits or transaction boundaries

### 2. UUID Type Handling
- Verify if document_uuid is passed as string vs UUID object
- Check if PostgreSQL UUID column type causes comparison issues
- Look for any UUID serialization/deserialization mismatches

### 3. Connection Pooling
- Examine if Celery workers get stale connections from the pool
- Check if `pool_pre_ping=True` is properly configured
- Look for connection recycling issues

### 4. Session Management
- Verify how DatabaseManager.get_session() works in Celery context
- Check if sessions are properly closed/refreshed
- Look for any session caching that might show stale data

### 5. Timing Issues
- The 1-second delay added to test script didn't help
- Suggests it's not a simple timing issue
- May be related to how Celery initializes database connections

## Hypothesis
The issue is likely NOT directly related to Textract's async nature, but rather to how Celery worker processes establish and maintain database connections. The fact that documents are visible to direct queries but not to Celery suggests:
1. Celery workers may be using a different database connection configuration
2. There may be transaction isolation between the test process and worker processes
3. Connection pooling may be serving stale connections to workers