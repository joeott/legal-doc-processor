# Context 344: Production Test Error Analysis

## Summary

Production testing revealed 11 critical issues (52% success rate). This document analyzes each issue and provides solutions.

## Critical Issues Found

### 1. Database Connection ❌
**Error**: `Connection failed: __enter__`
**Cause**: DatabaseManager.get_session() returns a generator, not a context manager
**Impact**: Cannot process any documents without database access
**Solution**: Use next() on the generator or modify the test code

### 2. Redis Read/Write ❌
**Error**: `Read/write test failed`
**Cause**: Redis decode_responses setting causing string/bytes mismatch
**Impact**: Cache operations may fail
**Solution**: Handle both string and bytes responses

### 3. Textract API ❌
**Error**: `'Textract' object has no attribute 'describe_document_text_detection_job'`
**Cause**: Incorrect method name (should be describe_document_analysis)
**Impact**: Cannot verify OCR capability
**Solution**: Use correct Textract API method

### 4. OpenAI API ❌
**Error**: `openai.ChatCompletion no longer supported in openai>=1.0.0`
**Cause**: Using old OpenAI API syntax
**Impact**: Entity extraction will fail
**Solution**: Update to new OpenAI client API

### 5. Celery Tasks (6 errors) ❌
**Error**: All tasks not found in registry
**Cause**: Tasks use @shared_task decorator but aren't registered
**Impact**: No document processing possible
**Solution**: Ensure tasks are properly imported and registered

## Successful Components ✅

1. **Environment Variables**: All critical vars set
2. **S3 Access**: Full read/write permissions
3. **Redis Connection**: Basic connection works
4. **Test Documents**: 9 PDFs found, primary test doc ready
5. **Celery Broker**: Redis broker configured

## Impact on Fairness and Justice

These issues prevent the system from:
1. **Processing legal documents** - No database/worker access
2. **Extracting entities** - OpenAI API incompatible
3. **Performing OCR** - Textract verification failed
4. **Caching results** - Redis operations unreliable

Without these core functions, the system cannot help reduce legal inequality.

## Immediate Actions Required

### Priority 1: Fix Database Access
```python
# Current (broken):
with db.get_session() as session:

# Fixed:
db_gen = db.get_session()
session = next(db_gen)
try:
    # operations
finally:
    session.close()
```

### Priority 2: Update OpenAI Client
```python
# Current (old API):
openai.ChatCompletion.create()

# Fixed (new API):
from openai import OpenAI
client = OpenAI()
response = client.chat.completions.create()
```

### Priority 3: Fix Celery Task Registration
Ensure all tasks are imported in celery_app.py:
```python
from scripts.pdf_tasks import (
    process_pdf_document,
    process_ocr_task,
    chunk_document_task,
    extract_entities_task,
    resolve_entities_task,
    build_relationships_task
)
```

## Next Steps

1. Apply fixes to critical components
2. Re-run production tests
3. Process test document through pipeline
4. Validate results for fairness criteria