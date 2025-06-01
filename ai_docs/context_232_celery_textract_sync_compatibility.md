# Context 232: Celery and Textract Synchronous Database Compatibility

## Overview
This document explains how we resolved the async/sync compatibility issues between Celery workers, AWS Textract operations, and our RDS PostgreSQL database connection.

## The Problem
The user correctly identified that:
1. Textract functions and Celery workers are necessarily async
2. Our initial RDS migration incorrectly left async method definitions in the database module
3. SQLAlchemy with psycopg2 uses synchronous operations, not async

## The Solution

### 1. Remove Async Keywords from Database Methods
We systematically removed all `async def` and `await` keywords from `scripts/db.py`:

```bash
# Remove async from method definitions
sed -i '' 's/async def/def/g' db.py

# Remove await from return statements
sed -i '' 's/return await /return /g' db.py

# Remove await from assignments
sed -i '' 's/= await /= /g' db.py
```

### 2. Key Understanding: Celery's Async Nature
Celery workers are asynchronous at the **task scheduling level**, not at the **database operation level**:

- Celery uses an event loop to manage multiple tasks concurrently
- Each task runs in its own context (process/thread)
- Within a task, database operations can be synchronous
- This is the standard pattern for Celery + SQLAlchemy

### 3. Textract Integration
AWS Textract operations work perfectly with synchronous database operations:

```python
# In textract_utils.py
class TextractManager:
    def __init__(self, db_manager: DatabaseManager, region_name: str):
        self.db = db_manager  # Synchronous DatabaseManager
        self.textract = boto3.client('textract', region_name=region_name)
    
    def process_document(self, document_uuid: str):
        # Textract API call (can be async via boto3)
        response = self.textract.analyze_document(...)
        
        # Database update (synchronous)
        self.db.update_document_status(
            document_uuid, 
            ProcessingStatus.COMPLETED
        )
```

### 4. Updated Import Structure
Changed all imports from the old module name:
```python
# Old
from scripts.database import SupabaseManager

# New
from scripts.db import DatabaseManager
```

### 5. Backward Compatibility
Maintained a `SupabaseManager` wrapper class in `db.py` for gradual migration:
```python
class SupabaseManager(DatabaseManager):
    """Legacy compatibility wrapper for existing code."""
    pass
```

## Why This Works

### Celery's Architecture
1. **Task Queue**: Async message passing via Redis/RabbitMQ
2. **Worker Pool**: Multiple processes/threads handling tasks
3. **Task Execution**: Each task runs synchronously within its context
4. **Database Operations**: Synchronous SQLAlchemy operations are standard

### Common Pattern
```python
@celery.task
def process_document(document_uuid: str):
    # This is a Celery task (async at scheduling level)
    db = DatabaseManager()  # Synchronous database manager
    
    # Synchronous database operations within the task
    doc = db.get_source_document(document_uuid)
    
    # Process document...
    
    # Update status synchronously
    db.update_document_status(document_uuid, ProcessingStatus.COMPLETED)
```

## Benefits

1. **Simplicity**: No async/await complexity in database layer
2. **Performance**: SQLAlchemy connection pooling handles concurrency
3. **Reliability**: Synchronous operations are easier to debug
4. **Compatibility**: Works with all existing Celery patterns

## Migration Checklist

- [x] Remove all `async def` from database methods
- [x] Remove all `await` keywords
- [x] Update imports in all affected files
- [x] Maintain backward compatibility with SupabaseManager
- [x] Verify Celery tasks work with synchronous operations
- [x] Ensure Textract integration functions correctly

## Conclusion

The synchronous database approach is the correct pattern for Celery + SQLAlchemy applications. Celery handles concurrency at the task level, while database operations remain synchronous within each task. This provides the best balance of performance, reliability, and maintainability.