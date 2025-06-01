# Test Suite for Legal Document Processing Pipeline

This directory contains comprehensive tests for validating the document processing pipeline, schema alignment, and Celery worker functionality.

## Test Scripts

### 1. Schema Alignment Test (`test_schema_alignment.py`)
Tests Pydantic model to RDS schema mapping without processing actual documents.

**Usage:**
```bash
python scripts/tests/test_schema_alignment.py
```

**Tests:**
- Document creation and field mapping
- Chunk operations and bulk creation
- Entity model validation
- Status enum transitions
- JSON metadata handling

### 2. Document Processing Test (`test_document_processing.py`)
End-to-end document processing test with synchronous execution (no Celery).

**Usage:**
```bash
python scripts/tests/test_document_processing.py
```

**Tests:**
- PDF creation and S3 upload
- OCR text extraction
- Text chunking
- Entity extraction
- Relationship building
- Schema validation at each stage

### 3. Celery Submission Test (`test_celery_submission.py`)
Submit a test document through the full Celery pipeline.

**Usage:**
```bash
python scripts/tests/test_celery_submission.py
```

**Tests:**
- Celery task submission
- Worker task pickup
- Async processing flow
- Task state monitoring

### 4. Schema Error Detection (`test_schema_errors.py`)
Test error handling and constraint validation.

**Usage:**
```bash
python scripts/tests/test_schema_errors.py
```

**Tests:**
- Invalid status values
- Missing required fields
- Type mismatches
- Constraint violations
- JSON field validation
- Enum validation

### 5. Monitoring Tools

#### Real-time Monitor (`test_monitor.sh`)
Live dashboard showing worker status, queue depths, and processing activity.

**Usage:**
```bash
./scripts/tests/test_monitor.sh
```

**Shows:**
- Worker status
- Queue depths
- Recent errors
- Active tasks
- Database statistics

#### Worker Check (`../check_workers.sh`)
Quick status check for Celery workers.

**Usage:**
```bash
./scripts/check_workers.sh
```

## Test Execution Order

For comprehensive testing, run in this order:

1. **Pre-flight checks:**
   ```bash
   # Verify environment
   python scripts/check_rds_connection.py
   ./scripts/check_workers.sh
   ```

2. **Schema validation:**
   ```bash
   python scripts/tests/test_schema_alignment.py
   python scripts/tests/test_schema_errors.py
   ```

3. **Start workers (if not running):**
   ```bash
   sudo supervisorctl start celery:*
   ```

4. **Process test document:**
   ```bash
   # Synchronous test (no workers needed)
   python scripts/tests/test_document_processing.py
   
   # Async test (requires workers)
   python scripts/tests/test_celery_submission.py
   ```

5. **Monitor processing:**
   ```bash
   # In another terminal
   ./scripts/tests/test_monitor.sh
   ```

## Success Criteria

All tests pass when:
- ✅ Schema alignment: 100% field mapping
- ✅ Document processing: All stages complete
- ✅ Error detection: All invalid cases caught
- ✅ Celery submission: Task completes successfully
- ✅ No errors in worker logs
- ✅ All queues process to empty

## Troubleshooting

### Workers not starting
```bash
# Check supervisor logs
sudo supervisorctl tail -f celery:celery-ocr
sudo journalctl -u supervisor -f
```

### Database connection issues
```bash
# Verify environment
source /opt/legal-doc-processor/venv/bin/activate
python -c "from scripts.config import DATABASE_URL; print(DATABASE_URL)"
```

### Redis connection issues
```bash
# Test Redis
redis-cli -h $REDIS_HOST -p $REDIS_PORT -a $REDIS_PASSWORD ping
```

### Task not processing
```bash
# Check specific queue
celery -A scripts.celery_app inspect active
celery -A scripts.celery_app inspect reserved
```