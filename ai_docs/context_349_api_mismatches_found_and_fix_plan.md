# Context 349: API Mismatches Found and Fix Plan

## Executive Summary

We've confirmed the API mismatches described in context_347. The system has evolved APIs during consolidation but didn't update all callers. Here's what we found and how to fix it.

## API Mismatches Confirmed

### 1. S3 Storage API
- **Old**: `s3.upload_document(file, key)`
- **New**: `s3.upload_document_with_uuid_naming(local_path, doc_uuid, project_uuid)`
- **Status**: ✗ Old method missing, new method exists

### 2. Redis Cache API
- **Old**: `redis.set(key, value)` and `redis.get(key)`
- **New**: `redis.set_cached(key, value, ttl=300)` and `redis.get_cached(key)`
- **Status**: ✗ Old methods missing, new methods exist

### 3. Database Session API
- **Old**: Used as context manager `with get_db() as session:`
- **New**: Generator function requiring `session = next(get_db())`
- **Status**: ✗ Context manager pattern fails

### 4. Entity Service API
- **Old**: `EntityExtractionService`
- **New**: `EntityService`
- **Status**: ✓ New class exists (import works)

## Git Recovery Status

- **Last Working Commit**: `6e8aa82` - "Pipeline completion breakthrough: 99% success rate achieved"
- **Current Branch**: `backup/pre-recovery-state` (post-consolidation)
- **Recovery Branch**: `recovery/last-working-state` (99% success commit)

## Good News

The core pipeline files (`pdf_tasks.py`, `entity_service.py`, `s3_storage.py`, `cache.py`, `db.py`) were NOT changed during consolidation. This means the pipeline logic is intact - we just need to fix the API calls.

## Fix Strategy

### Option A: Update All Callers (Recommended)
Fix all code that calls the old APIs to use the new APIs. This preserves the consolidation improvements.

### Option B: Add Compatibility Layer
Create wrapper functions that bridge old and new APIs during transition.

### Option C: Selective Restoration
Restore specific files from the working commit only where needed.

## Immediate Fix Implementation

### Step 1: Create Compatibility Wrappers

```python
# scripts/api_compatibility.py
"""Temporary compatibility layer to bridge API changes"""

def get_db_session():
    """Wrapper to provide context manager interface for get_db()"""
    from contextlib import contextmanager
    from scripts.db import get_db
    
    @contextmanager
    def session_context():
        session = next(get_db())
        try:
            yield session
            session.commit()
        except:
            session.rollback()
            raise
        finally:
            session.close()
    
    return session_context()

class RedisCompatibilityWrapper:
    """Wrapper to provide old Redis API"""
    def __init__(self, redis_manager):
        self.manager = redis_manager
    
    def set(self, key, value, ex=None):
        """Old set method mapping to new set_cached"""
        return self.manager.set_cached(key, value, ttl=ex)
    
    def get(self, key):
        """Old get method mapping to new get_cached"""
        return self.manager.get_cached(key)
    
    def __getattr__(self, name):
        """Pass through other methods"""
        return getattr(self.manager, name)

class S3CompatibilityWrapper:
    """Wrapper to provide old S3 API"""
    def __init__(self, s3_manager):
        self.manager = s3_manager
    
    def upload_document(self, file_path, key):
        """Old upload method - extract UUID from key"""
        import os
        from uuid import uuid4
        
        # Parse key format: "project_uuid/doc_uuid/filename"
        parts = key.split('/')
        if len(parts) >= 2:
            project_uuid = parts[0]
            doc_uuid = parts[1]
        else:
            # Fallback
            project_uuid = str(uuid4())
            doc_uuid = str(uuid4())
        
        return self.manager.upload_document_with_uuid_naming(
            file_path, doc_uuid, project_uuid
        )
    
    def __getattr__(self, name):
        """Pass through other methods"""
        return getattr(self.manager, name)
```

### Step 2: Fix Critical Files

The main files that need fixing based on context_347:
1. `scripts/pdf_tasks.py` - Core pipeline orchestration
2. `scripts/ocr_extraction.py` - OCR processing
3. `scripts/entity_service.py` - Entity extraction
4. Any test scripts trying to process documents

### Step 3: Verification Process

1. Fix one API at a time
2. Run real document test after each fix
3. Only proceed when current fix verified
4. Document what's required vs optional

## Next Immediate Actions

1. Create the compatibility layer
2. Test if it resolves the immediate errors
3. Run a real document through the pipeline
4. Fix any remaining issues one by one

## Success Criteria

- One document processes through all 6 stages
- No API mismatch errors
- Real data appears in database tables
- Pipeline completes without manual intervention