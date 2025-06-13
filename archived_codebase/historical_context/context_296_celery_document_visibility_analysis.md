# Celery Document Visibility Analysis

## Issue Summary

Test scripts create documents that are visible when accessed directly within the same script, but Celery workers cannot find these documents when processing tasks. This appears to be a database transaction isolation issue, not related to Textract's asynchronous processing.

## Root Cause Analysis

### 1. Transaction Isolation Problem

The core issue is that test scripts and Celery workers use separate database connections with different transaction contexts:

**Test Script Flow:**
```python
# Test script creates document
db = DatabaseManager()
doc = db.create_source_document(model)  # Creates in transaction A
# Document visible within same script
retrieved = db.get_source_document(uuid)  # Same transaction A - FOUND

# Submit to Celery
process_pdf_document.delay(document_uuid)
```

**Celery Worker Flow:**
```python
# In pdf_tasks.py
class PDFTask(Task):
    def db_manager(self):
        # Creates NEW database connection (transaction B)
        self._db_manager = DatabaseManager()
        
# In task execution
document = self.db_manager.get_source_document(uuid)  # Transaction B - NOT FOUND
```

### 2. Session Management Architecture

From `scripts/db.py` and `scripts/rds_utils.py`:

- Each `DatabaseManager` instance creates its own database sessions
- `DBSessionLocal = sessionmaker(bind=db_engine)` creates isolated sessions
- `select_records()` creates a new session for each query:
  ```python
  def select_records(...):
      db = DBSessionLocal()  # New session each time
      try:
          # Query execution
      finally:
          db.close()
  ```

### 3. The Missing Commit

The test scripts create documents but may not commit the transaction before submitting to Celery:

```python
# In create_source_document
def create(self, table, model):
    data = self.serialize_for_db(model)
    result = insert_record(table, data)  # May not auto-commit
    return result
```

Without an explicit commit, the document exists only in the test script's transaction and is invisible to other connections.

## Why This Isn't Related to Textract Async

While Textract does use asynchronous processing:
1. The document visibility issue occurs BEFORE Textract is even called
2. The worker can't find the document in the database, so it never reaches the OCR step
3. Textract's async nature (submit job → poll for completion) is a separate concern

## Solutions

### 1. Immediate Fix - Explicit Commits

Ensure test scripts commit after creating documents:

```python
# In test scripts
db_manager = DatabaseManager()
doc = db_manager.create_source_document(model)

# Force commit
from scripts.config import DBSessionLocal
session = DBSessionLocal()
session.commit()
session.close()

# Now submit to Celery
process_pdf_document.delay(document_uuid)
```

### 2. Better Fix - Transaction Management

Modify `DatabaseManager` to handle commits properly:

```python
class DatabaseManager:
    def create_source_document(self, document, auto_commit=True):
        result = self.pydantic_db.create("source_documents", document)
        if auto_commit:
            # Ensure transaction is committed
            self.commit_transaction()
        return result
    
    def commit_transaction(self):
        """Force commit of any pending transactions"""
        # Implementation needed
```

### 3. Best Fix - Context Managers

Use context managers for transaction boundaries:

```python
with db_manager.transaction() as tx:
    doc = tx.create_source_document(model)
    # Auto-commits on context exit
    
# Document now visible to Celery
process_pdf_document.delay(document_uuid)
```

## Connection Pooling Considerations

The system uses SQLAlchemy connection pooling:
```python
DB_POOL_CONFIG = {
    'pool_size': 5,
    'max_overflow': 10,
    'pool_timeout': 30,
    'pool_recycle': 3600,
    'pool_pre_ping': True
}
```

This means:
- Connections are reused, but sessions are isolated
- Each worker gets its own connection from the pool
- Transaction isolation is maintained between connections

## Testing Recommendations

1. **Add explicit commits** in test scripts after document creation
2. **Verify visibility** before submitting to Celery:
   ```python
   # Create document
   doc = db.create_source_document(model)
   
   # Verify with new connection
   db2 = DatabaseManager()
   verified = db2.get_source_document(uuid)
   assert verified is not None, "Document not visible to other connections"
   
   # Then submit to Celery
   ```

3. **Use transaction logging** to debug:
   ```python
   import logging
   logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)
   ```

## Conclusion

The document visibility issue is caused by transaction isolation between test scripts and Celery workers, not by Textract's asynchronous processing. The solution is to ensure proper transaction commits before submitting work to Celery.