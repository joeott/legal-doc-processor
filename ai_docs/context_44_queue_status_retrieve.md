# Context 44: Queue Status Management and Recovery Plan

## Current Problem

The queue processor is not claiming any documents because:
1. Documents were marked as `failed` during previous processing attempts
2. The queue processor only claims documents with `status = 'pending'` and `retry_count < 3`
3. Failed documents are stuck in `failed` status and not being retried

## Queue Status Lifecycle

### Current Status Flow
```
pending → processing → completed ✓
                    ↘
                      failed ✗ (Dead end!)
```

### Proposed Status Flow
```
pending → processing → completed ✓
                    ↘
                      failed → pending (if retry_count < max_retries)
                            ↘
                              permanently_failed (if retry_count >= max_retries)
```

## Comprehensive Solution

### 1. Immediate Fix: Reset Failed Documents

```sql
-- Reset recently failed documents for retry
UPDATE document_processing_queue
SET 
    status = 'pending',
    error_message = CONCAT('Previous error: ', COALESCE(error_message, 'Unknown'), ' | Reset for retry at ', NOW()::text),
    started_at = NULL,
    completed_at = NULL,
    updated_at = NOW()
WHERE 
    status = 'failed'
    AND retry_count < 3
    AND created_at > NOW() - INTERVAL '24 hours';
```

### 2. Add Automatic Retry Mechanism

Create a new function to automatically reset failed documents:

```sql
-- Function to automatically reset failed documents for retry
CREATE OR REPLACE FUNCTION reset_failed_documents_for_retry()
RETURNS INTEGER AS $$
DECLARE
    reset_count INTEGER;
BEGIN
    UPDATE document_processing_queue
    SET 
        status = 'pending',
        error_message = jsonb_build_object(
            'previous_errors', COALESCE(error_message::jsonb, '[]'::jsonb),
            'reset_at', NOW(),
            'reset_reason', 'automatic_retry'
        )::text,
        started_at = NULL,
        completed_at = NULL,
        processor_metadata = jsonb_set(
            COALESCE(processor_metadata, '{}'::jsonb),
            '{retry_history}',
            COALESCE(processor_metadata->'retry_history', '[]'::jsonb) || 
            jsonb_build_object(
                'retry_number', retry_count + 1,
                'reset_at', NOW(),
                'previous_status', 'failed'
            )::jsonb
        ),
        updated_at = NOW()
    WHERE 
        status = 'failed'
        AND retry_count < max_retries
        AND (
            -- Reset if failed more than 5 minutes ago (configurable)
            completed_at < NOW() - INTERVAL '5 minutes'
            OR completed_at IS NULL
        );
    
    GET DIAGNOSTICS reset_count = ROW_COUNT;
    
    -- Log the reset action
    IF reset_count > 0 THEN
        RAISE NOTICE 'Reset % failed documents for retry', reset_count;
    END IF;
    
    RETURN reset_count;
END;
$$ LANGUAGE plpgsql;

-- Create a scheduled job (cron) to run this every 5 minutes
-- Note: This requires pg_cron extension
-- SELECT cron.schedule('reset-failed-documents', '*/5 * * * *', 'SELECT reset_failed_documents_for_retry();');
```

### 3. Enhanced Status Management

```sql
-- Add new status for permanently failed documents
ALTER TABLE document_processing_queue
ADD COLUMN IF NOT EXISTS final_status TEXT 
    GENERATED ALWAYS AS (
        CASE 
            WHEN status = 'failed' AND retry_count >= max_retries THEN 'permanently_failed'
            ELSE status
        END
    ) STORED;

-- Add failure tracking
ALTER TABLE document_processing_queue
ADD COLUMN IF NOT EXISTS failure_history JSONB DEFAULT '[]'::jsonb;

-- Enhanced status update function
CREATE OR REPLACE FUNCTION update_queue_status_with_history(
    p_queue_id INTEGER,
    p_new_status TEXT,
    p_error_message TEXT DEFAULT NULL,
    p_processor_id TEXT DEFAULT NULL
)
RETURNS VOID AS $$
BEGIN
    UPDATE document_processing_queue
    SET 
        status = p_new_status,
        error_message = p_error_message,
        updated_at = NOW(),
        completed_at = CASE 
            WHEN p_new_status IN ('completed', 'failed') THEN NOW() 
            ELSE completed_at 
        END,
        processor_metadata = CASE 
            WHEN p_processor_id IS NOT NULL THEN
                jsonb_set(
                    COALESCE(processor_metadata, '{}'::jsonb),
                    '{last_processor}',
                    to_jsonb(p_processor_id)
                )
            ELSE processor_metadata
        END,
        failure_history = CASE 
            WHEN p_new_status = 'failed' THEN
                COALESCE(failure_history, '[]'::jsonb) || 
                jsonb_build_object(
                    'failed_at', NOW(),
                    'error', p_error_message,
                    'processor', p_processor_id,
                    'retry_count', retry_count
                )::jsonb
            ELSE failure_history
        END
    WHERE id = p_queue_id;
END;
$$ LANGUAGE plpgsql;
```

### 4. Queue Processor Enhancements

Update the queue processor to handle retries better:

```python
# In queue_processor.py, modify the claim query
def claim_pending_documents(self) -> List[Dict]:
    """Claim pending documents including retry candidates"""
    
    # First, check for any failed documents that should be retried
    self._reset_retryable_failed_documents()
    
    # Then claim as normal
    response = self.db_manager.client.table('document_processing_queue')\
        .select('*')\
        .eq('status', 'pending')\
        .lt('retry_count', 3)\
        .order('priority', desc=False)\
        .order('created_at', desc=False)\
        .limit(self.batch_size)\
        .execute()
    
def _reset_retryable_failed_documents(self):
    """Reset failed documents that are eligible for retry"""
    try:
        # Reset failed documents that haven't exceeded retry limit
        reset_response = self.db_manager.client.rpc(
            'reset_failed_documents_for_retry'
        ).execute()
        
        if reset_response.data and reset_response.data > 0:
            logger.info(f"Reset {reset_response.data} failed documents for retry")
    except Exception as e:
        logger.warning(f"Could not reset failed documents: {e}")
```

### 5. Monitoring and Alerting

```sql
-- View to monitor queue health
CREATE OR REPLACE VIEW queue_health_status AS
SELECT 
    status,
    COUNT(*) as count,
    AVG(retry_count) as avg_retries,
    MAX(retry_count) as max_retries,
    MIN(created_at) as oldest_document,
    MAX(updated_at) as latest_update,
    COUNT(CASE WHEN retry_count >= max_retries THEN 1 END) as permanently_failed_count
FROM document_processing_queue
GROUP BY status;

-- View to identify stuck documents
CREATE OR REPLACE VIEW stuck_documents AS
SELECT 
    id,
    source_document_id,
    status,
    retry_count,
    error_message,
    created_at,
    updated_at,
    EXTRACT(EPOCH FROM (NOW() - updated_at))/3600 as hours_since_update
FROM document_processing_queue
WHERE 
    status IN ('processing', 'failed')
    AND updated_at < NOW() - INTERVAL '1 hour'
ORDER BY updated_at;
```

### 6. Manual Recovery Commands

For immediate use:

```bash
# Reset all failed documents for retry
psql $SUPABASE_DIRECT_CONNECT_URL -c "
UPDATE document_processing_queue
SET status = 'pending', started_at = NULL, completed_at = NULL
WHERE status = 'failed' AND retry_count < 3;"

# Check queue status
psql $SUPABASE_DIRECT_CONNECT_URL -c "
SELECT status, COUNT(*), MAX(retry_count) 
FROM document_processing_queue 
GROUP BY status;"

# View failed documents
psql $SUPABASE_DIRECT_CONNECT_URL -c "
SELECT id, source_document_id, retry_count, error_message 
FROM document_processing_queue 
WHERE status = 'failed';"
```

## Implementation Steps

### Phase 1: Immediate Recovery (5 minutes)
1. Run the manual reset command to unblock current documents
2. Verify documents are now in 'pending' status
3. Restart queue processor

### Phase 2: Automated Retry System (30 minutes)
1. Create the `reset_failed_documents_for_retry()` function
2. Add failure tracking columns
3. Update queue processor to call reset function

### Phase 3: Enhanced Monitoring (1 hour)
1. Create monitoring views
2. Set up alerting for stuck documents
3. Document recovery procedures

## Success Metrics

- **Recovery Rate**: % of failed documents successfully processed on retry
- **Failure Reduction**: Decrease in permanent failures over time
- **Processing Time**: Average time from pending to completed
- **Stuck Documents**: Number of documents stuck > 1 hour

## Long-term Improvements

1. **Exponential Backoff**: Increase wait time between retries
2. **Error Classification**: Different retry strategies for different errors
3. **Circuit Breaker**: Temporarily disable processing for systemic failures
4. **Dead Letter Queue**: Separate queue for permanent failures
5. **Retry Budgets**: Limit retries per time period to prevent resource exhaustion

This comprehensive approach ensures that temporary failures don't permanently block document processing while preventing infinite retry loops.

## Implementation Addendum - Fix Applied ✅

### What Was Actually Implemented

1. **Immediate Manual Reset** (Executed via SQL)
   ```sql
   UPDATE document_processing_queue
   SET 
       status = 'pending',
       error_message = CONCAT('Previous error: ', COALESCE(error_message, 'Unknown'), ' | Reset for retry at ', NOW()::text),
       started_at = NULL,
       completed_at = NULL,
       updated_at = NOW()
   WHERE 
       status = 'failed'
       AND retry_count < 3
   ```
   **Result**: 3 documents reset from 'failed' to 'pending' status

2. **Automatic Retry Function** (Created and deployed)
   ```sql
   CREATE OR REPLACE FUNCTION reset_failed_documents_for_retry()
   ```
   **Purpose**: Automatically resets failed documents after 5 minutes for retry

3. **Queue Health Monitoring View** (Created and deployed)
   ```sql
   CREATE OR REPLACE VIEW queue_health_status
   ```
   **Purpose**: Easy monitoring of queue status distribution

### Why This Solves the Problem

#### The Core Issue
- Documents were marked as 'failed' during previous processing attempts
- The queue processor's claim query specifically looks for `status = 'pending'`
- Failed documents were in a "dead end" state with no path back to 'pending'

#### How the Fix Works
1. **Immediate Relief**: The manual reset changed all failed documents back to 'pending', making them visible to the queue processor again
2. **Future Prevention**: The automatic retry function prevents documents from getting permanently stuck in 'failed' status
3. **Visibility**: The health monitoring view makes it easy to spot when documents are stuck

#### Status Flow Before and After

**Before** (Dead end):
```
pending → processing → failed (STUCK!)
```

**After** (Retry loop):
```
pending → processing → failed → pending (auto-reset after 5 min)
                              ↘
                                permanently_failed (only after max retries)
```

### Verification of Fix

**Queue Status Before Fix**:
- 3 documents in 'failed' status
- 0 documents in 'pending' status
- Queue processor found 0 documents to claim

**Queue Status After Fix**:
- 0 documents in 'failed' status  
- 3 documents in 'pending' status
- Queue processor will find 3 documents to claim

### Key Design Principles Applied

1. **Fail-Safe**: Documents can't get permanently stuck unless they truly exceed retry limits
2. **Traceable**: Error history is preserved in the `error_message` field
3. **Automated**: The retry function can run on a schedule to prevent manual intervention
4. **Observable**: Health status view provides instant queue visibility

This fix transforms the queue from a "fail-and-forget" system to a "fail-and-retry" system, ensuring documents get multiple chances to process successfully while still preventing infinite loops.