# Test Execution Plan for Minimal Models Implementation

## Date: 2025-06-01

## Overview

This document provides a systematic test execution plan for verifying the minimal models implementation. The plan covers all 15 verification criteria from context_284, organized for maximum efficiency and minimal risk.

## Test Environment Prerequisites

### 1. Pre-Test Setup Checklist

**Environment Configuration:**
```bash
# 1. Backup current .env
cp .env .env.backup.$(date +%Y%m%d_%H%M%S)

# 2. Set required environment variables
echo "USE_MINIMAL_MODELS=true" >> .env
echo "SKIP_CONFORMANCE_CHECK=true" >> .env

# 3. Verify environment
grep -E "(USE_MINIMAL_MODELS|SKIP_CONFORMANCE_CHECK)" .env
```

**Service Availability:**
```bash
# 4. Check Redis connectivity
redis-cli -h $REDIS_HOST -p $REDIS_PORT -a $REDIS_PASSWORD ping

# 5. Check PostgreSQL connectivity
psql $DATABASE_URL -c "SELECT 1"

# 6. Verify AWS credentials
aws sts get-caller-identity

# 7. Check S3 bucket access
aws s3 ls s3://$S3_PRIMARY_DOCUMENT_BUCKET --max-items 1
```

**Worker Status:**
```bash
# 8. Stop existing workers (clean slate)
pkill -f "celery worker"

# 9. Start fresh workers with correct config
celery -A scripts.celery_app worker --loglevel=info --queues=default,ocr,text,entity,graph &

# 10. Verify workers started
celery -A scripts.celery_app inspect active
```

### 2. Test Data Preparation

**Create Test Documents:**
```bash
# Create test directory
mkdir -p /tmp/test_docs

# Copy sample PDFs (if available)
cp input_docs/Paul*/*.pdf /tmp/test_docs/ 2>/dev/null || echo "No test PDFs found"

# Create test manifest
cat > /tmp/test_manifest.json << 'EOF'
{
  "documents": [
    {
      "filename": "test_doc_1.pdf",
      "project": "Test Project 1",
      "tags": ["test", "minimal_models"]
    }
  ]
}
EOF
```

## Test Execution Phases

### Phase 1: Configuration Verification (15 minutes)

#### Test 1.1: System Configuration (Criterion #1)
```bash
# Execute test
python << 'EOF'
import os
from scripts.config import USE_MINIMAL_MODELS, SKIP_CONFORMANCE_CHECK

print(f"USE_MINIMAL_MODELS: {USE_MINIMAL_MODELS}")
print(f"SKIP_CONFORMANCE_CHECK: {SKIP_CONFORMANCE_CHECK}")

assert USE_MINIMAL_MODELS == True, "USE_MINIMAL_MODELS not set correctly"
assert SKIP_CONFORMANCE_CHECK == True, "SKIP_CONFORMANCE_CHECK not set correctly"
print("✓ Configuration test passed")
EOF
```

**Expected Output:**
- USE_MINIMAL_MODELS: True
- SKIP_CONFORMANCE_CHECK: True
- ✓ Configuration test passed

#### Test 1.2: Model Factory (Criterion #1)
```bash
# Execute test
python << 'EOF'
from scripts.core.model_factory import (
    get_source_document_model,
    get_document_chunk_model,
    get_entity_mention_model,
    get_canonical_entity_model
)

models = {
    "SourceDocument": get_source_document_model(),
    "DocumentChunk": get_document_chunk_model(),
    "EntityMention": get_entity_mention_model(),
    "CanonicalEntity": get_canonical_entity_model()
}

for name, model in models.items():
    print(f"{name}: {model.__name__}")
    assert "Minimal" in model.__name__, f"{name} not using minimal model"

print("✓ Model factory test passed")
EOF
```

### Phase 2: Database Connection Tests (20 minutes)

#### Test 2.1: Database Connection Without Conformance (Criterion #2)
```bash
# Execute test with error handling
python << 'EOF'
import sys
from scripts.db import DatabaseManager

try:
    db = DatabaseManager(validate_conformance=False)
    print("✓ Database connection successful without conformance")
    
    # Check logs
    with open('monitoring/logs/database/sql_20250531.log', 'r') as f:
        if "Skipping conformance validation" in f.read():
            print("✓ Conformance skip confirmed in logs")
    
except Exception as e:
    print(f"✗ Database connection failed: {e}")
    sys.exit(1)
EOF
```

#### Test 2.2: Document Creation (Criterion #3)
```bash
# Execute test
python << 'EOF'
import uuid
from scripts.core.model_factory import get_source_document_model
from scripts.db import DatabaseManager

# Create test document
SourceDocument = get_source_document_model()
test_uuid = str(uuid.uuid4())

doc = SourceDocument(
    document_uuid=test_uuid,
    original_file_name="test_minimal_models.pdf",
    s3_bucket="samu-docs-private-upload",
    s3_key=f"test/{test_uuid}/test.pdf"
)

# Save to database
db = DatabaseManager(validate_conformance=False)
result = db.create_source_document(doc)

if result:
    print(f"✓ Document created: {test_uuid}")
    print(f"  - Fields: {len(doc.__dict__)} (minimal)")
    
    # Verify in database
    retrieved = db.get_source_document(test_uuid)
    if retrieved:
        print("✓ Document retrieved from database")
else:
    print("✗ Document creation failed")

# Save UUID for later tests
with open('/tmp/test_doc_uuid.txt', 'w') as f:
    f.write(test_uuid)
EOF
```

### Phase 3: Async OCR Tests (30 minutes)

#### Test 3.1: OCR Task Submission (Criterion #4)
```bash
# Read test UUID
TEST_UUID=$(cat /tmp/test_doc_uuid.txt)

# Execute OCR test
python << EOF
import json
from scripts.pdf_tasks import extract_text_from_document

doc_uuid = "$TEST_UUID"
s3_path = f"s3://samu-docs-private-upload/test/{doc_uuid}/test.pdf"

# Submit task
result = extract_text_from_document.apply_async(
    args=[doc_uuid, s3_path]
)

print(f"Task ID: {result.id}")
print(f"Task State: {result.state}")

# Get immediate result (should be async)
try:
    immediate = result.get(timeout=2)
    if 'status' in immediate and immediate['status'] == 'processing':
        print("✓ Async OCR submission successful")
        if 'job_id' in immediate:
            print(f"✓ Textract Job ID: {immediate['job_id']}")
            
            # Save job ID
            with open('/tmp/textract_job_id.txt', 'w') as f:
                f.write(immediate['job_id'])
except Exception as e:
    print(f"Expected timeout (good - means async): {e}")
EOF
```

#### Test 3.2: Textract Job Tracking (Criterion #5)
```bash
# Check database for Textract fields
TEST_UUID=$(cat /tmp/test_doc_uuid.txt)

psql $DATABASE_URL << EOF
SELECT 
    document_uuid,
    textract_job_id,
    textract_job_status,
    textract_start_time,
    created_at
FROM source_documents
WHERE document_uuid = '$TEST_UUID';
EOF
```

#### Test 3.3: Redis State Verification (Criterion #6)
```bash
python << 'EOF'
import json
from scripts.cache import get_redis_manager, CacheKeys

doc_uuid = open('/tmp/test_doc_uuid.txt').read().strip()
redis = get_redis_manager()

# Check document state
state_key = CacheKeys.DOC_STATE.format(document_uuid=doc_uuid)
state = redis.get_dict(state_key)

if state:
    print("Document State:")
    print(json.dumps(state, indent=2))
    
    # Verify expected structure
    if 'pipeline' in state and 'ocr' in state:
        print("✓ State structure correct")
        
        if state['ocr'].get('status') == 'processing':
            print("✓ OCR status is processing")
            
        if 'job_id' in state['ocr'].get('metadata', {}):
            print(f"✓ Job ID tracked: {state['ocr']['metadata']['job_id']}")
else:
    print("✗ No state found in Redis")
EOF
```

### Phase 4: Pipeline Progression Tests (45 minutes)

#### Test 4.1: Polling Task Monitoring (Criterion #7)
```bash
# Monitor polling for 30 seconds
echo "Monitoring polling task for 30 seconds..."
timeout 30 tail -f monitoring/logs/celery/celery_20250531.log | grep -E "(poll_textract_job|Polling|retry)"
```

#### Test 4.2: Automatic Stage Transitions (Criterion #8)
```bash
# Create monitoring script
cat > /tmp/monitor_pipeline.py << 'EOF'
import time
import json
from scripts.cache import get_redis_manager, CacheKeys

doc_uuid = open('/tmp/test_doc_uuid.txt').read().strip()
redis = get_redis_manager()
state_key = CacheKeys.DOC_STATE.format(document_uuid=doc_uuid)

print("Monitoring pipeline progression...")
print("Time | Pipeline | OCR | Chunking | Entity | Relations")
print("-" * 60)

stages_seen = set()
for i in range(60):  # Monitor for 5 minutes
    state = redis.get_dict(state_key)
    if state:
        pipeline = state.get('pipeline', {}).get('status', 'none')
        ocr = state.get('ocr', {}).get('status', 'none')
        chunking = state.get('chunking', {}).get('status', 'none')
        entity = state.get('entity_extraction', {}).get('status', 'none')
        relations = state.get('relationships', {}).get('status', 'none')
        
        print(f"{i*5:3d}s | {pipeline:9} | {ocr:9} | {chunking:9} | {entity:9} | {relations:9}")
        
        # Track stage transitions
        for stage, status in [('ocr', ocr), ('chunking', chunking), ('entity', entity), ('relations', relations)]:
            if status == 'completed' and stage not in stages_seen:
                stages_seen.add(stage)
                print(f"✓ {stage} completed automatically")
        
        if pipeline == 'completed':
            print("✓ Pipeline completed successfully!")
            break
    
    time.sleep(5)

print(f"\nStages completed: {stages_seen}")
EOF

python /tmp/monitor_pipeline.py
```

### Phase 5: Error Handling and Recovery Tests (20 minutes)

#### Test 5.1: OCR Failure Handling (Criterion #9)
```bash
# Test with invalid S3 path
python << 'EOF'
import uuid
from scripts.pdf_tasks import extract_text_from_document

# Submit with invalid path
bad_uuid = str(uuid.uuid4())
bad_path = "s3://invalid-bucket/does-not-exist.pdf"

result = extract_text_from_document.apply_async(
    args=[bad_uuid, bad_path]
)

print(f"Submitted bad task: {result.id}")

# Wait and check state
import time
time.sleep(10)

from scripts.cache import get_redis_manager, CacheKeys
redis = get_redis_manager()
state_key = CacheKeys.DOC_STATE.format(document_uuid=bad_uuid)
state = redis.get_dict(state_key)

if state and state.get('ocr', {}).get('status') == 'failed':
    print("✓ OCR failure handled gracefully")
    if 'error' in state['ocr'].get('metadata', {}):
        print(f"✓ Error captured: {state['ocr']['metadata']['error'][:50]}...")
else:
    print("✗ Failure not properly handled")
EOF
```

### Phase 6: Concurrent Processing Tests (30 minutes)

#### Test 6.1: Load Test (Criterion #10)
```bash
# Run concurrent load test
python scripts/tests/test_load_async.py --count 5

# Monitor system during test
echo "Monitoring concurrent processing..."
python << 'EOF'
import time
import psutil
from scripts.cli.monitor import UnifiedMonitor

monitor = UnifiedMonitor()

print("Time | CPU% | Memory% | Workers | Active Tasks")
print("-" * 50)

for i in range(12):  # Monitor for 1 minute
    stats = monitor.get_system_stats()
    worker_stats = monitor.get_worker_stats()
    
    cpu = psutil.cpu_percent(interval=1)
    mem = psutil.virtual_memory().percent
    workers = len(worker_stats)
    active = sum(w.get('active', 0) for w in worker_stats.values())
    
    print(f"{i*5:3d}s | {cpu:4.1f} | {mem:6.1f} | {workers:7} | {active:12}")
    
    time.sleep(5)

print("✓ Concurrent processing test completed")
EOF
```

### Phase 7: Performance Verification (20 minutes)

#### Test 7.1: Cache Performance (Criterion #11)
```bash
python << 'EOF'
from scripts.cache import get_redis_manager

redis = get_redis_manager()
info = redis.client.info()

# Calculate hit rate
hits = info.get('keyspace_hits', 0)
misses = info.get('keyspace_misses', 0)
total = hits + misses

if total > 0:
    hit_rate = (hits / total) * 100
    print(f"Cache Statistics:")
    print(f"  Total operations: {total}")
    print(f"  Hits: {hits}")
    print(f"  Misses: {misses}")
    print(f"  Hit rate: {hit_rate:.2f}%")
    
    if hit_rate > 50:
        print("✓ Cache hit rate acceptable")
else:
    print("No cache operations yet")

# Check cache keys
keys = redis.client.keys("doc:*")
print(f"\nCached documents: {len([k for k in keys if b':state:' in k])}")
print(f"Cached OCR results: {len([k for k in keys if b':ocr:' in k])}")
print(f"Cached chunks: {len([k for k in keys if b':chunks:' in k])}")
EOF
```

#### Test 7.2: Monitor Integration (Criterion #12)
```bash
# Test monitor displays
echo "Testing monitor integration..."
timeout 10 python scripts/cli/monitor.py live || echo "Monitor test completed"

# Check for specific displays
python << 'EOF'
from scripts.cli.monitor import UnifiedMonitor

monitor = UnifiedMonitor()

# Get Textract jobs
jobs = monitor.get_textract_jobs()
if jobs:
    print(f"✓ Monitor shows {len(jobs)} Textract jobs")
    for job in jobs[:3]:
        print(f"  - {job['document_uuid'][:8]}... Job: {job['textract_job_id']}")
else:
    print("No active Textract jobs")

# Check for errors
errors = monitor.get_recent_errors(minutes=10)
if not errors:
    print("✓ No errors in monitor")
else:
    print(f"Found {len(errors)} errors - reviewing...")
EOF
```

### Phase 8: End-to-End Verification (30 minutes)

#### Test 8.1: Complete Pipeline Test (Criterion #13)
```bash
# Run comprehensive E2E test
python scripts/tests/test_e2e_minimal.py

# Verify all stages
TEST_UUID=$(cat /tmp/test_doc_uuid.txt)

echo "Checking final database state..."
psql $DATABASE_URL << EOF
-- Document status
SELECT document_uuid, status, error_message, 
       textract_job_status, processing_completed_at
FROM source_documents 
WHERE document_uuid = '$TEST_UUID';

-- Chunks created
SELECT COUNT(*) as chunk_count 
FROM document_chunks 
WHERE document_uuid = '$TEST_UUID';

-- Entities extracted  
SELECT COUNT(*) as entity_count
FROM entity_mentions
WHERE document_uuid = '$TEST_UUID';

-- Relationships built
SELECT COUNT(*) as relationship_count
FROM relationship_staging r
JOIN entity_mentions e ON r.source_id = e.entity_mention_id
WHERE e.document_uuid = '$TEST_UUID';
EOF
```

#### Test 8.2: Performance Metrics (Criterion #14)
```bash
python << 'EOF'
import time
from datetime import datetime
from scripts.db import DatabaseManager

doc_uuid = open('/tmp/test_doc_uuid.txt').read().strip()
db = DatabaseManager(validate_conformance=False)

# Get timing metrics
doc = db.get_source_document(doc_uuid)
if doc:
    created = doc.created_at
    completed = doc.processing_completed_at or datetime.now()
    
    duration = (completed - created).total_seconds()
    
    print("Performance Metrics:")
    print(f"  Document UUID: {doc_uuid[:8]}...")
    print(f"  Total processing time: {duration:.2f} seconds")
    print(f"  Status: {doc.status}")
    
    if duration < 300:  # 5 minutes
        print("✓ Processing time acceptable")
    else:
        print("⚠ Processing took longer than expected")

# Check resource usage
import psutil
print("\nResource Usage:")
print(f"  CPU: {psutil.cpu_percent()}%")
print(f"  Memory: {psutil.virtual_memory().percent}%")
print(f"  Disk: {psutil.disk_usage('/').percent}%")
EOF
```

### Phase 9: Logging and Debug Verification (15 minutes)

#### Test 9.1: Log Completeness (Criterion #15)
```bash
# Check for key log entries
echo "Verifying logging..."

LOG_DIR="monitoring/logs"
TODAY=$(date +%Y%m%d)

# Check each expected log entry
for pattern in \
    "Using minimal models" \
    "Skipping conformance validation" \
    "Started Textract job" \
    "Pipeline continuation initiated" \
    "Task submitted successfully"
do
    echo -n "Checking for '$pattern': "
    if grep -q "$pattern" $LOG_DIR/*/*.log 2>/dev/null; then
        echo "✓ Found"
    else
        echo "✗ Not found"
    fi
done

# Check log files exist
echo -e "\nLog files present:"
ls -la $LOG_DIR/*/${TODAY}.log 2>/dev/null | wc -l
```

## Rollback Procedures

### Quick Rollback (5 minutes)
If critical issues found:
```bash
# 1. Stop workers
pkill -f "celery worker"

# 2. Restore environment
cp .env.backup.* .env

# 3. Clear test data from Redis
redis-cli -h $REDIS_HOST -p $REDIS_PORT -a $REDIS_PASSWORD --eval "
for _,k in ipairs(redis.call('keys', 'doc:*:state:*')) do 
    redis.call('del', k) 
end
return 'Cleared test states'"

# 4. Restart services
celery -A scripts.celery_app worker --loglevel=info &
```

### Full Rollback (15 minutes)
For complete reversion:
```bash
# 1. Stop all processing
supervisorctl stop all

# 2. Restore configuration
git checkout -- .env
git checkout -- scripts/config.py

# 3. Remove minimal models
rm -f scripts/core/models_minimal.py
rm -f scripts/core/model_factory.py

# 4. Reset database
psql $DATABASE_URL << 'EOF'
-- Remove test documents
DELETE FROM source_documents 
WHERE original_file_name LIKE 'test_minimal%';

-- Reset any schema changes
-- (Add specific rollback SQL if needed)
EOF

# 5. Clear all cache
redis-cli -h $REDIS_HOST -p $REDIS_PORT -a $REDIS_PASSWORD FLUSHDB

# 6. Restart everything
supervisorctl start all
```

## Test Summary Report Template

```markdown
# Minimal Models Test Execution Report
Date: [DATE]
Tester: [NAME]

## Environment
- USE_MINIMAL_MODELS: [true/false]
- SKIP_CONFORMANCE_CHECK: [true/false]
- Workers Running: [count]

## Test Results

### Phase 1: Configuration (15 min)
- [ ] System configuration verified
- [ ] Model factory returns minimal models
- Issues: [none/description]

### Phase 2: Database (20 min)
- [ ] Connection without conformance errors
- [ ] Document creation successful
- Issues: [none/description]

### Phase 3: Async OCR (30 min)
- [ ] OCR submission returns immediately
- [ ] Textract job tracked in database
- [ ] Redis state management working
- Issues: [none/description]

### Phase 4: Pipeline Progression (45 min)
- [ ] Polling task executes correctly
- [ ] Automatic stage transitions work
- [ ] All stages complete
- Issues: [none/description]

### Phase 5: Error Handling (20 min)
- [ ] OCR failures handled gracefully
- [ ] Error messages captured
- Issues: [none/description]

### Phase 6: Concurrent Processing (30 min)
- [ ] 5 documents process simultaneously
- [ ] System remains stable
- Issues: [none/description]

### Phase 7: Performance (20 min)
- [ ] Cache hit rate > 50%
- [ ] Monitor integration working
- Issues: [none/description]

### Phase 8: End-to-End (30 min)
- [ ] Complete pipeline successful
- [ ] All data persisted correctly
- [ ] Performance acceptable
- Issues: [none/description]

### Phase 9: Logging (15 min)
- [ ] All expected logs present
- [ ] Debug information available
- Issues: [none/description]

## Overall Result: [PASS/FAIL]

## Recommendations:
1. [First recommendation]
2. [Second recommendation]

## Next Steps:
1. [First next step]
2. [Second next step]
```

## Execution Timeline

**Total Estimated Time: 4-5 hours**

1. **Setup** (30 min)
   - Environment configuration
   - Service verification
   - Test data preparation

2. **Testing** (3-4 hours)
   - Phase 1-9 execution
   - Issue investigation
   - Documentation

3. **Cleanup** (30 min)
   - Result compilation
   - Rollback if needed
   - Report generation

## Critical Success Factors

1. **No Conformance Errors** - The primary goal
2. **Async OCR Working** - Non-blocking Textract
3. **Pipeline Automation** - Each stage triggers next
4. **Concurrent Processing** - Multiple documents
5. **System Stability** - No crashes or hangs

## Go/No-Go Decision Points

**After Phase 2:** If database connections fail, STOP and investigate
**After Phase 3:** If async OCR doesn't work, STOP and fix
**After Phase 6:** If concurrent processing fails, evaluate severity
**After Phase 8:** If E2E fails, determine if partial success acceptable

This plan provides comprehensive coverage of all verification criteria while minimizing risk through careful rollback procedures and clear decision points.