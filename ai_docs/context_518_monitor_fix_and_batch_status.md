# Context 518: Monitor Application Fix and Batch Processing Status

**Date**: 2025-06-13  
**Issue**: Monitor application errors and stalled batch processing  
**Status**: Critical - No workers running

## Executive Summary

The monitor application has multiple errors due to incomplete migration from Supabase to RDS, and batch processing is completely stalled because no Celery workers are running. All 20 documents from the recent batch remain in "pending" status.

## Critical Findings

### 1. No Celery Workers Running
```bash
# Current worker status check:
ps aux | grep celery
# Result: Only grep process itself, no celery workers

# Celery inspect shows no active workers:
celery -A scripts.celery_app inspect active
# Error: No nodes replied within time constraint
```

### 2. Batch Processing Status

#### Recent Batch Information
- **Expected Campaign ID**: campaign_205692f0_20250612_231117 (not found in Redis)
- **Found Batch IDs** with similar timestamps:
  - ed8153fa-7dee-4d4b-ab3e-d20048042abc
  - 5287ef37-2256-4b15-b724-b8184386e196  
  - eac61c3d-e41d-4c54-b2ea-1e26f3b1ee9b

#### Document Status in Database
```sql
-- All 20 documents are stuck in 'pending' status:
SELECT status, COUNT(*) FROM source_documents 
WHERE created_at > '2025-06-12 22:00:00' 
GROUP BY status;

-- Result:
-- status | count
-- pending | 20
```

#### Sample Pending Documents
- c1dc7178-39f8-4cdf-84f6-bb30e3d7ba25: ADV Part 2A 03.30.2022.pdf
- 8c17c96f-37fa-478b-9f97-dca0b456f83a: Addendum to JPMS MSA.pdf
- 7a695cbc-d3d8-4caa-9dd5-bb693f5d30f8: JPMS Client Agreement Fully Executed.pdf

### 3. Monitor Application Errors

#### Error 1: Redis WRONGTYPE
```
Error reading batch batch:progress:ed8153fa-7dee-4d4b-ab3e-d20048042abc: WRONGTYPE Operation against a key holding the wrong kind of value
```
**Cause**: Batch progress data stored as JSON strings, not Redis hashes
```bash
redis-cli get "batch:progress:ed8153fa-7dee-4d4b-ab3e-d20048042abc"
# Returns: "{\"batch_id\":\"ed8153fa-7dee-4d4b-ab3e-d20048042abc\",\"total_documents\":20,\"completed_documents\":0...}"
```

#### Error 2: Missing Supabase Attribute
```
Error getting pipeline stats: 'UnifiedMonitor' object has no attribute 'supabase'
```
**Cause**: Incomplete migration from Supabase to RDS in monitor.py (line 337)

#### Error 3: SQL Column Error
```
psycopg2.errors.UndefinedColumn: column sd.processing_status does not exist
```
**Cause**: Using old column name; should be `status` not `processing_status`

## Immediate Fix Implementation

### 1. Start Celery Workers (URGENT)
```bash
# Kill any stuck processes
ps aux | grep "[c]elery" | awk '{print $2}' | xargs -r kill -9

# Start main pipeline workers
celery -A scripts.celery_app worker --loglevel=info --queues=default,ocr,text,entity,graph,cleanup &

# Start batch processing workers  
celery -A scripts.celery_app worker -Q batch.high -n batch-high@%h --concurrency=4 &
celery -A scripts.celery_app worker -Q batch.normal -n batch-normal@%h --concurrency=2 &
celery -A scripts.celery_app worker -Q batch.low -n batch-low@%h --concurrency=1 &
```

### 2. Monitor.py Fixes Required

#### Fix 1: Remove Supabase References
```python
# Line 337 - Remove this block entirely:
if hasattr(self, 'supabase'):
    # Supabase logic
```

#### Fix 2: Handle JSON String Batch Data
```python
# In get_batch_processing() method:
def _read_batch_progress(self, key):
    try:
        # Try to get as string first
        data = self.redis_client.get(key)
        if data:
            return json.loads(data)
    except:
        # Fallback to hash
        return self.redis_client.hgetall(key)
```

#### Fix 3: Fix SQL Column Names
```python
# Change all occurrences of:
sd.processing_status → sd.status
```

### 3. Verify Workers Started
```bash
# Check active workers
celery -A scripts.celery_app inspect active

# Monitor OCR queue (should see tasks)
redis-cli -h $REDIS_HOST -p $REDIS_PORT -a $REDIS_PASSWORD llen celery:queue:ocr
```

## Root Cause Analysis

1. **Worker Startup**: No automatic worker startup configured after system restart or deployment
2. **Monitor Migration**: Partial migration from Supabase to RDS left mixed references
3. **Data Format Mismatch**: Batch progress stored as JSON strings but read as Redis hashes

## Recommended Actions

### Immediate (Within 1 Hour)
1. ✅ Start all Celery workers using commands above
2. ✅ Monitor document processing begins
3. ✅ Apply monitor.py fixes to restore monitoring capability

### Short-term (Within 24 Hours)  
1. Configure systemd or supervisor to auto-start workers
2. Complete monitor.py migration to pure RDS
3. Standardize batch progress storage format

### Long-term
1. Add worker health checks and auto-restart
2. Implement worker scaling based on queue depth
3. Add alerting for worker failures

## Verification Steps

After starting workers:
```bash
# 1. Check workers are running
celery -A scripts.celery_app inspect active

# 2. Check OCR tasks are being processed
watch -n 2 'redis-cli -h $REDIS_HOST -p $REDIS_PORT -a $REDIS_PASSWORD llen celery:queue:ocr'

# 3. Monitor document status changes
watch -n 10 'psql -h $DATABASE_HOST -U $DATABASE_USER -d $DATABASE_NAME -c "SELECT status, COUNT(*) FROM source_documents WHERE created_at > '\''2025-06-12 22:00:00'\'' GROUP BY status;"'

# 4. Check for processing errors
tail -f /opt/legal-doc-processor/monitoring/logs/errors_*.log
```

## Expected Outcome

Once workers are started:
- 20 pending documents should immediately begin OCR processing
- Monitor should show active tasks after fixes applied
- Documents should progress through all 6 pipeline stages
- Batch completion expected within 2-4 hours depending on document complexity

## Current System State

- **Database**: Connected and functional (172.31.33.106)
- **Redis**: Connected and functional (redis-19446.c328.us-east-1-3.ec2.redns.redis-cloud.com)
- **S3**: Accessible with documents uploaded
- **Celery Workers**: NOT RUNNING (critical issue)
- **Task Queue**: 20 documents queued and waiting
- **Monitor**: Partially functional with errors

The primary issue is simply that no workers are running to process the queued tasks. Starting the workers should immediately resolve the processing stall.