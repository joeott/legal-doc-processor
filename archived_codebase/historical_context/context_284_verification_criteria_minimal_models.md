# Verification Criteria for End-to-End Document Processing with Minimal Models

## Date: 2025-06-01

## Overview

This document defines the verification criteria to confirm successful end-to-end document processing using minimal models and async OCR. These criteria serve as a checklist to validate that the implementation from context_283 is working correctly.

## Prerequisites

Before verification, ensure:
- `USE_MINIMAL_MODELS=true` in `.env`
- `SKIP_CONFORMANCE_CHECK=true` in `.env`
- Redis is running and accessible
- PostgreSQL (RDS) is accessible
- AWS credentials are configured
- Celery workers are running

## Verification Criteria

### 1. System Configuration ✓

**Verify environment configuration:**
```bash
# Check environment variables
grep USE_MINIMAL_MODELS .env  # Should show: USE_MINIMAL_MODELS=true
grep SKIP_CONFORMANCE_CHECK .env  # Should show: SKIP_CONFORMANCE_CHECK=true
```

**Verify model factory returns minimal models:**
```python
from scripts.core.model_factory import get_source_document_model
Model = get_source_document_model()
print(Model.__name__)  # Should print: SourceDocumentMinimal
```

### 2. Database Connection ✓

**Test database connection without conformance errors:**
```python
from scripts.db import DatabaseManager
db = DatabaseManager(validate_conformance=False)
# Should initialize without ConformanceError
```

**Verify no conformance validation occurs:**
- Check logs for: "Skipping conformance validation due to SKIP_CONFORMANCE_CHECK=true"
- No ConformanceError exceptions should be raised

### 3. Document Creation ✓

**Create document with minimal model:**
```python
from scripts.core.model_factory import get_source_document_model
from scripts.db import DatabaseManager
import uuid

SourceDocument = get_source_document_model()
doc = SourceDocument(
    document_uuid=uuid.uuid4(),
    original_file_name="test.pdf",
    s3_bucket="samu-docs-private-upload",
    s3_key="test/test.pdf"
)

db = DatabaseManager(validate_conformance=False)
result = db.create_source_document(doc)
# Should succeed without errors
```

### 4. Async OCR Submission ✓

**Submit document for OCR processing:**
```python
from scripts.pdf_tasks import extract_text_from_document

task = extract_text_from_document.apply_async(
    args=[str(doc_uuid), s3_path]
)
```

**Verify async behavior:**
- Task returns immediately with status 'processing'
- Response includes 'job_id' field
- No blocking on Textract results

### 5. Textract Job Tracking ✓

**Check Textract job fields in database:**
```sql
SELECT 
    document_uuid,
    textract_job_id,
    textract_job_status,
    textract_start_time
FROM source_documents
WHERE textract_job_id IS NOT NULL;
```

**Expected values:**
- `textract_job_id`: Non-null AWS job ID
- `textract_job_status`: 'IN_PROGRESS' or 'SUBMITTED'
- `textract_start_time`: Recent timestamp

### 6. Redis State Management ✓

**Verify document state in Redis:**
```python
from scripts.cache import get_redis_manager, CacheKeys

redis = get_redis_manager()
state_key = CacheKeys.DOC_STATE.format(document_uuid=doc_uuid)
state = redis.get_dict(state_key)
```

**Expected state structure:**
```json
{
    "pipeline": {
        "status": "processing",
        "timestamp": "2025-06-01T...",
        "metadata": {
            "task_id": "...",
            "project_uuid": "..."
        }
    },
    "ocr": {
        "status": "processing",
        "timestamp": "2025-06-01T...",
        "metadata": {
            "job_id": "...",
            "started_at": "..."
        }
    }
}
```

### 7. Polling Task Execution ✓

**Monitor polling task:**
```bash
# Check Celery logs for polling activity
grep "poll_textract_job" celery.log
```

**Expected behavior:**
- Polling task retries every 5 seconds
- No more than 30 retries (2.5 minutes)
- Updates state on each poll

### 8. Pipeline Progression ✓

**Track automatic stage transitions:**

After OCR completes, verify:
1. Chunking starts automatically
2. Entity extraction follows chunking
3. Entity resolution follows extraction
4. Relationship building follows resolution
5. Pipeline finalization completes

**Check state transitions:**
```python
# Monitor state changes over time
import time
for i in range(10):
    state = redis.get_dict(state_key)
    print(f"T+{i*5}s: OCR={state.get('ocr',{}).get('status')}, "
          f"Chunking={state.get('chunking',{}).get('status')}")
    time.sleep(5)
```

### 9. Error Handling ✓

**Test OCR failure handling:**
- Submit invalid S3 path
- Verify graceful failure
- Check error message in state
- Document marked as 'failed'

**Test retry mechanism:**
- Monitor retry count in logs
- Verify exponential backoff
- Check max retry limit

### 10. Concurrent Processing ✓

**Submit multiple documents:**
```bash
python scripts/tests/test_load_async.py --count 5
```

**Verify:**
- All 5 documents start processing
- Workers remain responsive
- No blocking between documents
- System resources stable

### 11. Cache Performance ✓

**Check cache hit rates:**
```python
from scripts.cli.monitor import UnifiedMonitor
monitor = UnifiedMonitor()
redis_stats = monitor.get_redis_stats()
print(f"Hit rate: {redis_stats['hit_rate']}")
```

**Expected:**
- Cache hit rate > 50% after initial processing
- OCR results cached for 24 hours
- Chunk results cached and reused

### 12. Monitor Integration ✓

**Run live monitor:**
```bash
python scripts/cli/monitor.py live
```

**Verify displays:**
- Pending Textract jobs with job IDs
- Document processing status
- Worker availability
- No errors about missing fields

### 13. End-to-End Success ✓

**Complete pipeline verification:**

1. **Submit real PDF document:**
```python
from scripts.pdf_tasks import process_pdf_document

result = process_pdf_document.apply_async(
    args=[doc_uuid, s3_path, project_uuid]
)
```

2. **Wait for completion** (monitor state)

3. **Verify all stages completed:**
```python
final_state = redis.get_dict(state_key)
assert final_state['pipeline']['status'] == 'completed'
assert final_state['ocr']['status'] == 'completed'
assert final_state['chunking']['status'] == 'completed'
assert final_state['entity_extraction']['status'] == 'completed'
assert final_state['relationships']['status'] == 'completed'
```

4. **Check database records:**
```sql
-- Verify chunks created
SELECT COUNT(*) FROM document_chunks WHERE document_uuid = ?;

-- Verify entities extracted
SELECT COUNT(*) FROM entity_mentions WHERE document_uuid = ?;

-- Verify relationships built
SELECT COUNT(*) FROM relationship_staging WHERE source_id = ?;
```

### 14. Performance Metrics ✓

**Measure processing time:**
- OCR submission to job start: < 5 seconds
- Worker availability during OCR: > 95%
- Total pipeline completion: Varies by document size
- Concurrent document throughput: 5+ documents

**Resource usage:**
- Memory per worker: < 1GB
- CPU during processing: < 80%
- Redis memory usage: Stable
- Database connections: Within pool limit

### 15. Logging and Debugging ✓

**Verify comprehensive logging:**
```bash
# Check for key log entries
grep "Using minimal models" logs/
grep "Skipping conformance validation" logs/
grep "Started Textract job" logs/
grep "Pipeline continuation initiated" logs/
```

**Debug information available:**
- Task IDs for each stage
- Textract job IDs
- Error messages with context
- State transitions logged

## Success Criteria Summary

The implementation is considered successful when:

1. ✅ No conformance errors block processing
2. ✅ Documents process end-to-end without manual intervention
3. ✅ OCR runs asynchronously without blocking workers
4. ✅ Each pipeline stage triggers the next automatically
5. ✅ Multiple documents process concurrently
6. ✅ Errors are handled gracefully with proper logging
7. ✅ Monitor shows accurate real-time status
8. ✅ Cache improves performance measurably
9. ✅ System remains stable under load
10. ✅ All data persists correctly to database

## Verification Commands

Quick verification suite:
```bash
# 1. Test minimal models
python scripts/tests/test_minimal_models.py

# 2. Test async OCR
python scripts/tests/test_async_ocr.py

# 3. Test end-to-end
python scripts/tests/test_e2e_minimal.py

# 4. Test concurrent load
python scripts/tests/test_load_async.py --count 5

# 5. Monitor live
python scripts/cli/monitor.py live
```

All tests should pass and monitor should show active processing without errors.

## Troubleshooting

If verification fails:

1. **Check environment variables** - Ensure USE_MINIMAL_MODELS=true
2. **Verify worker logs** - Look for task execution errors
3. **Check Redis state** - Inspect document state keys
4. **Review database** - Check textract_job_id fields
5. **Monitor Textract** - Verify jobs in AWS console
6. **Test connectivity** - Ensure all services accessible

## Next Steps

Once all verification criteria are met:
1. Process larger document batches
2. Monitor performance over time
3. Plan migration to full models
4. Optimize polling intervals
5. Scale worker count as needed