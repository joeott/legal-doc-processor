# Context 503: Production Document Verification Plan

## Date: 2025-06-11

## Objective
Verify complete end-to-end functionality of the document processing pipeline using 10 production documents from the Paul, Michael (Acuity) folder, with comprehensive error capture and stage-by-stage verification.

## Pre-Test Verification Steps

### 1. Environment Verification
- [ ] Confirm all environment variables are loaded
- [ ] Verify Redis connectivity and health
- [ ] Check database connectivity
- [ ] Ensure S3 bucket access
- [ ] Verify Celery workers are running
- [ ] Check available disk space and memory

### 2. Document Selection Criteria
- Select 10 documents from `/opt/legal-doc-processor/input_docs/Paul, Michael (Acuity)/`
- Ensure variety in:
  - File sizes (small, medium, large)
  - Document types (if multiple formats available)
  - Content complexity

### 3. Pre-Test System State Capture
- Record current Redis key count by prefix
- Note any existing errors in logs
- Clear previous test data if necessary
- Document current queue state

## Test Execution Steps

### Step 1: Document Inventory
```bash
# List all available documents
ls -la "/opt/legal-doc-processor/input_docs/Paul, Michael (Acuity)/" | head -20

# Count total documents
find "/opt/legal-doc-processor/input_docs/Paul, Michael (Acuity)/" -type f -name "*.pdf" | wc -l

# Get file sizes
du -h "/opt/legal-doc-processor/input_docs/Paul, Michael (Acuity)/"*.pdf | sort -h | head -10
```

### Step 2: Batch Submission Script
Create a script to submit documents with proper tracking:
```python
#!/usr/bin/env python3
import sys
import os
import time
from pathlib import Path
from uuid import uuid4
import json

sys.path.insert(0, '/opt/legal-doc-processor')

from scripts.batch_tasks import submit_batch
from scripts.s3_storage import S3StorageManager

# Upload documents to S3 first
# Submit batch with tracking
# Monitor progress
```

### Step 3: Pipeline Stage Verification

For each document, verify completion of:

#### 3.1 OCR Stage
- **Success Criteria:**
  - Task status: 'completed' in processing_tasks
  - OCR result cached in Redis (cache:doc:ocr:{uuid})
  - Text length > 0
  - No error_message in task record

- **Error Capture:**
  - Textract API errors
  - S3 access errors
  - Timeout errors
  - Memory errors

#### 3.2 Chunking Stage
- **Success Criteria:**
  - Chunks created in document_chunks table
  - Chunk count > 0
  - Each chunk has valid text content
  - Chunks cached in Redis

- **Error Capture:**
  - Text parsing errors
  - Database write errors
  - Validation errors

#### 3.3 Entity Extraction Stage
- **Success Criteria:**
  - Entity mentions created in entity_mentions table
  - Entity count > 0
  - Confidence scores present
  - Valid entity types

- **Error Capture:**
  - OpenAI API errors
  - Rate limit errors
  - JSON parsing errors
  - Model response errors

#### 3.4 Entity Resolution Stage
- **Success Criteria:**
  - Canonical entities created
  - Resolution mappings established
  - Fuzzy matching completed

- **Error Capture:**
  - Resolution algorithm errors
  - Database constraint errors
  - Memory errors

#### 3.5 Relationship Building Stage
- **Success Criteria:**
  - Relationships created in relationship_staging
  - Valid source/target entities
  - Confidence scores assigned

- **Error Capture:**
  - Graph building errors
  - Invalid entity references
  - Extraction errors

#### 3.6 Finalization Stage
- **Success Criteria:**
  - Pipeline status: 'completed'
  - All metadata updated
  - Final counts recorded

- **Error Capture:**
  - State update errors
  - Incomplete pipeline errors

## Monitoring During Test

### Real-time Monitoring Commands
```bash
# Watch Celery task progress
celery -A scripts.celery_app events

# Monitor Redis keys
watch -n 2 'redis-cli -h $REDIS_HOST -p $REDIS_PORT -a $REDIS_PASSWORD --no-auth-warning dbsize'

# Check error logs
tail -f /opt/legal-doc-processor/monitoring/logs/errors_*.log

# Database activity
psql -h $DATABASE_HOST -U $DATABASE_USER -d $DATABASE_NAME -c "SELECT task_type, status, COUNT(*) FROM processing_tasks WHERE created_at > NOW() - INTERVAL '1 hour' GROUP BY task_type, status ORDER BY task_type;"
```

## Error Documentation Requirements

### For Each Error:
1. **Timestamp** - Exact time of error
2. **Document ID** - UUID and filename
3. **Stage** - Which pipeline stage failed
4. **Error Type** - Exception class
5. **Error Message** - Complete error message
6. **Stack Trace** - Full traceback
7. **Context** - What was being attempted
8. **System State** - Memory, CPU, queue depth

### Error Categories to Track:
- **Infrastructure Errors**
  - Redis connection failures
  - Database connection issues
  - S3 access problems
  - Network timeouts

- **API Errors**
  - Textract failures
  - OpenAI API errors
  - Rate limiting
  - Authentication issues

- **Processing Errors**
  - Memory exhaustion
  - Timeout errors
  - Validation failures
  - Data format issues

- **Logic Errors**
  - Missing data
  - Invalid state transitions
  - Constraint violations
  - Unexpected null values

## Success Metrics

### Overall Pipeline Success
- Target: 90%+ documents complete all stages
- Measure: (completed_documents / total_documents) * 100

### Stage-Specific Success
- OCR: 100% (all documents should extract text)
- Chunking: 100% (all texts should be chunked)
- Entity Extraction: 95%+ (some docs may have no entities)
- Resolution: 90%+ (depends on entity quality)
- Relationships: 85%+ (depends on content)
- Finalization: 100% (all started should finalize)

### Performance Metrics
- Average time per document
- Peak memory usage
- Redis cache hit rate
- Database query performance

## Post-Test Verification

### 1. Data Integrity Checks
```sql
-- Check for orphaned records
SELECT COUNT(*) as orphaned_chunks 
FROM document_chunks dc 
LEFT JOIN source_documents sd ON dc.document_uuid = sd.document_uuid 
WHERE sd.document_uuid IS NULL;

-- Check for incomplete pipelines
SELECT document_uuid, COUNT(DISTINCT task_type) as stages_completed
FROM processing_tasks
WHERE created_at > NOW() - INTERVAL '1 hour'
GROUP BY document_uuid
HAVING COUNT(DISTINCT task_type) < 6;
```

### 2. Redis State Verification
```bash
# Check for leaked keys
redis-cli --scan --pattern "doc:*" | wc -l

# Check cache consistency
python3 -c "
from scripts.cache import get_redis_manager
rm = get_redis_manager()
# Verify cache entries match database
"
```

### 3. Error Summary Generation
- Total errors by stage
- Error frequency by type
- Failed document analysis
- Recommendations for fixes

## Output Format

All test results should be captured in:
1. **Detailed log file**: `production_test_YYYYMMDD_HHMMSS.log`
2. **Error summary**: `production_errors_YYYYMMDD_HHMMSS.json`
3. **Metrics report**: `production_metrics_YYYYMMDD_HHMMSS.csv`
4. **Context document**: `context_504_production_test_results.md`

## Test Execution Checklist

- [ ] Environment verified
- [ ] Documents selected
- [ ] Monitoring started
- [ ] Batch submitted
- [ ] Real-time monitoring active
- [ ] Errors captured verbatim
- [ ] Stage verifications complete
- [ ] Post-test checks done
- [ ] Reports generated
- [ ] Context document created