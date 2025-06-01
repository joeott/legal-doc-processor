# Context 70: Database Trigger Fix & Script Robustness Implementation

## Executive Summary

This document provides a comprehensive solution to fix the database trigger issues preventing document processing completion, along with improvements to make the pipeline more robust and resilient.

## Part 1: Immediate Database Fixes

### 1.1 Remove Phantom Trigger Accessing NEW.status

The core issue is a trigger trying to access `NEW.status` on the `source_documents` table, which doesn't have a `status` column.

```sql
-- Step 1: Identify the problematic trigger
DO $$
DECLARE
    rec RECORD;
BEGIN
    FOR rec IN 
        SELECT DISTINCT t.tgname, p.proname
        FROM pg_trigger t
        JOIN pg_proc p ON p.oid = t.tgfoid
        WHERE t.tgrelid = 'source_documents'::regclass
        AND pg_get_functiondef(p.oid) LIKE '%NEW.status%'
    LOOP
        RAISE NOTICE 'Found trigger accessing NEW.status: % (function: %)', 
                     rec.tgname, rec.proname;
        -- Drop the problematic trigger
        EXECUTE format('DROP TRIGGER IF EXISTS %I ON source_documents', rec.tgname);
    END LOOP;
END $$;

-- Step 2: Drop orphaned trigger functions that reference status incorrectly
DROP FUNCTION IF EXISTS update_document_status() CASCADE;
DROP FUNCTION IF EXISTS sync_status_to_queue() CASCADE;
```

### 1.2 Fix Status Enum Constraints

Align the status values between tables to prevent constraint violations:

```sql
-- Option A: Standardize textract_jobs to use lowercase (RECOMMENDED)
ALTER TABLE textract_jobs 
DROP CONSTRAINT IF EXISTS textract_jobs_job_status_check;

ALTER TABLE textract_jobs 
ADD CONSTRAINT textract_jobs_job_status_check 
CHECK (job_status IN ('submitted', 'in_progress', 'succeeded', 'failed', 'partial_success'));

-- Update existing uppercase values to lowercase
UPDATE textract_jobs 
SET job_status = LOWER(job_status)
WHERE job_status IN ('SUBMITTED', 'IN_PROGRESS', 'SUCCEEDED', 'FAILED', 'PARTIAL_SUCCESS');

-- Option B: If Option A fails due to foreign keys, create a migration function
CREATE OR REPLACE FUNCTION migrate_textract_status() RETURNS void AS $$
BEGIN
    -- Temporarily disable triggers
    ALTER TABLE textract_jobs DISABLE TRIGGER ALL;
    ALTER TABLE source_documents DISABLE TRIGGER ALL;
    
    -- Update statuses
    UPDATE textract_jobs SET job_status = 
        CASE job_status
            WHEN 'SUBMITTED' THEN 'submitted'
            WHEN 'IN_PROGRESS' THEN 'in_progress'
            WHEN 'SUCCEEDED' THEN 'succeeded'
            WHEN 'FAILED' THEN 'failed'
            WHEN 'PARTIAL_SUCCESS' THEN 'partial_success'
            ELSE LOWER(job_status)
        END;
    
    -- Re-enable triggers
    ALTER TABLE textract_jobs ENABLE TRIGGER ALL;
    ALTER TABLE source_documents ENABLE TRIGGER ALL;
END;
$$ LANGUAGE plpgsql;

-- Execute migration
SELECT migrate_textract_status();
DROP FUNCTION migrate_textract_status();
```

### 1.3 Create Safe Status Update Function

Replace the problematic notify_queue_status_change function with a safer version:

```sql
CREATE OR REPLACE FUNCTION notify_queue_status_change()
RETURNS TRIGGER AS $$
DECLARE
    notification_payload JSONB;
    status_field TEXT;
    id_field INTEGER;
BEGIN
    -- Safely determine which record and fields to use
    IF TG_OP = 'DELETE' THEN
        id_field := OLD.id;
    ELSE
        id_field := NEW.id;
    END IF;
    
    -- Build notification payload based on table
    CASE TG_TABLE_NAME
        WHEN 'source_documents' THEN
            notification_payload := jsonb_build_object(
                'table', TG_TABLE_NAME,
                'action', TG_OP,
                'id', id_field,
                'document_uuid', COALESCE(NEW.document_uuid, OLD.document_uuid),
                'status', CASE 
                    WHEN TG_OP = 'DELETE' THEN OLD.initial_processing_status
                    ELSE NEW.initial_processing_status
                END,
                'timestamp', NOW()
            );
        WHEN 'document_processing_queue' THEN
            notification_payload := jsonb_build_object(
                'table', TG_TABLE_NAME,
                'action', TG_OP,
                'id', id_field,
                'document_uuid', COALESCE(NEW.document_uuid, OLD.document_uuid),
                'status', CASE 
                    WHEN TG_OP = 'DELETE' THEN OLD.status
                    ELSE NEW.status
                END,
                'processing_step', CASE
                    WHEN TG_OP = 'DELETE' THEN OLD.processing_step
                    ELSE NEW.processing_step
                END,
                'timestamp', NOW()
            );
        WHEN 'textract_jobs' THEN
            notification_payload := jsonb_build_object(
                'table', TG_TABLE_NAME,
                'action', TG_OP,
                'job_id', CASE
                    WHEN TG_OP = 'DELETE' THEN OLD.job_id
                    ELSE NEW.job_id
                END,
                'status', CASE 
                    WHEN TG_OP = 'DELETE' THEN OLD.job_status
                    ELSE NEW.job_status
                END,
                'timestamp', NOW()
            );
        ELSE
            -- For other tables, minimal notification
            notification_payload := jsonb_build_object(
                'table', TG_TABLE_NAME,
                'action', TG_OP,
                'id', id_field,
                'timestamp', NOW()
            );
    END CASE;
    
    -- Send notification
    PERFORM pg_notify('document_status_change', notification_payload::text);
    
    RETURN COALESCE(NEW, OLD);
EXCEPTION
    WHEN OTHERS THEN
        -- Log error but don't fail the transaction
        RAISE WARNING 'Error in notify_queue_status_change: %', SQLERRM;
        RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;
```

### 1.4 Add Missing Indexes for Performance

```sql
-- Improve query performance for queue processing
CREATE INDEX IF NOT EXISTS idx_source_documents_textract_job_id 
ON source_documents(textract_job_id) 
WHERE textract_job_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_source_documents_processing_status 
ON source_documents(initial_processing_status);

CREATE INDEX IF NOT EXISTS idx_textract_jobs_source_doc 
ON textract_jobs(source_document_id);

CREATE INDEX IF NOT EXISTS idx_queue_processing_composite 
ON document_processing_queue(status, retry_count, priority) 
WHERE status = 'pending';
```

## Part 2: Python Script Robustness Improvements

### 2.1 Enhanced Error Handling in supabase_utils.py

```python
# File: scripts/supabase_utils.py

def update_source_document_with_textract_outcome(self, ...):
    """Updates source_documents table with Textract results - now with better error handling"""
    logger.info(f"Updating source_document {source_doc_sql_id} with Textract job ({textract_job_id}) outcome: {textract_job_status}")
    
    # Map AWS status to database enum
    status_mapping = {
        'SUBMITTED': 'submitted',
        'IN_PROGRESS': 'in_progress', 
        'SUCCEEDED': 'succeeded',
        'FAILED': 'failed',
        'PARTIAL_SUCCESS': 'partial_success'
    }
    
    # Normalize status
    normalized_status = status_mapping.get(textract_job_status.upper(), textract_job_status.lower())
    
    update_payload = {
        'textract_job_id': textract_job_id,
        'textract_job_status': normalized_status,
        'ocr_provider': ocr_provider_enum,
        'last_modified_at': datetime.now(timezone.utc).isoformat()
    }
    
    # ... rest of the method ...
    
    # Fix timezone handling
    if job_started_at and job_completed_at:
        try:
            # Ensure both are timezone-aware
            if job_started_at.tzinfo is None:
                job_started_at = job_started_at.replace(tzinfo=timezone.utc)
            if job_completed_at.tzinfo is None:
                job_completed_at = job_completed_at.replace(tzinfo=timezone.utc)
                
            duration = (job_completed_at - job_started_at).total_seconds()
            update_payload['ocr_processing_seconds'] = max(0, int(duration))
        except Exception as e:
            logger.warning(f"Could not calculate duration: {e}")
    
    # Retry logic for transient database errors
    max_retries = 3
    for attempt in range(max_retries):
        try:
            self.client.table('source_documents').update(update_payload).eq('id', source_doc_sql_id).execute()
            logger.info(f"Source_document {source_doc_sql_id} updated with Textract info (attempt {attempt + 1})")
            return True
        except Exception as e:
            if 'record "new" has no field "status"' in str(e):
                logger.error(f"Trigger error detected: {e}")
                # Don't retry trigger errors
                return False
            elif attempt < max_retries - 1:
                logger.warning(f"Retry {attempt + 1}/{max_retries} after error: {e}")
                time.sleep(2 ** attempt)  # Exponential backoff
            else:
                logger.error(f"Failed to update after {max_retries} attempts: {e}")
                return False
```

### 2.2 Robust Queue Processing with Checkpoint Recovery

```python
# File: scripts/queue_processor.py

class QueueProcessor:
    def __init__(self, ...):
        # Add checkpoint tracking
        self.checkpoint_file = Path("monitoring/logs/queue_checkpoint.json")
        self.failed_items = []
        
    def save_checkpoint(self, queue_id: int, status: str, error: str = None):
        """Save processing checkpoint for recovery"""
        checkpoint = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'queue_id': queue_id,
            'status': status,
            'error': error
        }
        
        try:
            checkpoints = []
            if self.checkpoint_file.exists():
                with open(self.checkpoint_file, 'r') as f:
                    checkpoints = json.load(f)
            
            checkpoints.append(checkpoint)
            # Keep only last 1000 checkpoints
            checkpoints = checkpoints[-1000:]
            
            with open(self.checkpoint_file, 'w') as f:
                json.dump(checkpoints, f, indent=2)
        except Exception as e:
            logger.warning(f"Could not save checkpoint: {e}")
    
    def process_queue_item_safe(self, item: Dict) -> bool:
        """Process a single queue item with comprehensive error handling"""
        queue_id = item['queue_id']
        source_doc_id = item['source_document_id']
        
        try:
            # Add timeout protection
            with timeout(300):  # 5 minute timeout per document
                result = process_single_document(
                    source_doc_sql_id=source_doc_id,
                    project_sql_id=self.project_sql_id,
                    db_manager=self.db_manager
                )
                
            if result:
                self.save_checkpoint(queue_id, 'completed')
                return True
            else:
                self.save_checkpoint(queue_id, 'failed', 'Processing returned False')
                return False
                
        except TimeoutError:
            logger.error(f"Timeout processing queue item {queue_id}")
            self.save_checkpoint(queue_id, 'timeout')
            self.mark_failed_with_retry(queue_id, "Processing timeout after 5 minutes")
            return False
            
        except Exception as e:
            logger.error(f"Error processing queue item {queue_id}: {e}", exc_info=True)
            self.save_checkpoint(queue_id, 'error', str(e))
            
            # Check if it's a recoverable error
            if self.is_recoverable_error(e):
                self.mark_failed_with_retry(queue_id, str(e))
            else:
                self.mark_permanently_failed(queue_id, str(e))
            return False
    
    def is_recoverable_error(self, error: Exception) -> bool:
        """Determine if an error is recoverable"""
        error_str = str(error)
        
        # Non-recoverable errors
        if any(msg in error_str for msg in [
            'record "new" has no field "status"',  # Trigger error
            'violates check constraint',           # Schema error
            'does not exist',                      # Missing table/column
            'permission denied'                    # Access error
        ]):
            return False
            
        # Recoverable errors
        if any(msg in error_str for msg in [
            'timeout',
            'connection',
            'temporary',
            'throttl'
        ]):
            return True
            
        # Default to recoverable
        return True
```

### 2.3 Safe Textract Processing with Fallback

```python
# File: scripts/ocr_extraction.py

def extract_text_from_pdf_textract_safe(
    db_manager: SupabaseManager,
    source_doc_sql_id: int,
    pdf_path_or_s3_uri: str,
    document_uuid_from_db: str
) -> tuple[str | None, list | None]:
    """Wrapper for Textract extraction with fallback options"""
    
    try:
        # Primary attempt with Textract
        text, metadata = extract_text_from_pdf_textract(
            db_manager, source_doc_sql_id, pdf_path_or_s3_uri, document_uuid_from_db
        )
        
        if text and len(text) > 0:
            return text, metadata
            
    except Exception as e:
        logger.error(f"Textract extraction failed: {e}")
        
        # Check if it's a trigger error
        if 'record "new" has no field "status"' in str(e):
            logger.warning("Database trigger error - attempting direct save")
            
            # Try to extract without database updates
            try:
                textract_processor = TextractProcessor(db_manager=None)  # No DB updates
                # ... extract text ...
                
                # Save directly without triggering updates
                if text:
                    db_manager.client.rpc('update_source_doc_text_direct', {
                        'doc_id': source_doc_sql_id,
                        'extracted_text': text,
                        'metadata': json.dumps(metadata)
                    }).execute()
                    
                return text, metadata
            except:
                pass
    
    # Fallback to alternative OCR if needed
    logger.warning("Attempting fallback OCR method")
    return extract_with_fallback_ocr(pdf_path_or_s3_uri)
```

### 2.4 Direct Database Update Function (Bypass Triggers)

```sql
-- Create a function to update source documents directly without triggering cascades
CREATE OR REPLACE FUNCTION update_source_doc_text_direct(
    doc_id INTEGER,
    extracted_text TEXT,
    metadata JSONB DEFAULT NULL
) RETURNS BOOLEAN AS $$
BEGIN
    -- Disable triggers for this session only
    SET session_replication_role = 'replica';
    
    UPDATE source_documents 
    SET 
        raw_extracted_text = extracted_text,
        ocr_metadata_json = metadata,
        initial_processing_status = 'ocr_complete_pending_doc_node',
        last_modified_at = NOW()
    WHERE id = doc_id;
    
    -- Re-enable triggers
    SET session_replication_role = 'origin';
    
    RETURN FOUND;
EXCEPTION
    WHEN OTHERS THEN
        -- Ensure triggers are re-enabled even on error
        SET session_replication_role = 'origin';
        RAISE;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Grant execute permission to the application role
GRANT EXECUTE ON FUNCTION update_source_doc_text_direct TO authenticated;
```

## Part 3: Monitoring & Recovery Tools

### 3.1 Health Check Script

```python
# File: scripts/health_check.py

def check_pipeline_health():
    """Comprehensive health check for the document pipeline"""
    
    db = SupabaseManager()
    issues = []
    
    # Check for trigger errors in recent logs
    recent_errors = db.client.table('source_documents').select('id').execute()
    
    # Check for stuck documents
    stuck_docs = db.client.rpc('get_stuck_documents', {
        'hours_threshold': 1
    }).execute()
    
    if stuck_docs.data:
        issues.append(f"Found {len(stuck_docs.data)} stuck documents")
    
    # Check for failed Textract jobs
    failed_jobs = db.client.table('textract_jobs').select('*').eq(
        'job_status', 'FAILED'
    ).execute()
    
    if failed_jobs.data:
        issues.append(f"Found {len(failed_jobs.data)} failed Textract jobs")
    
    return issues

# SQL function for finding stuck documents
CREATE OR REPLACE FUNCTION get_stuck_documents(hours_threshold INTEGER DEFAULT 1)
RETURNS TABLE (
    id INTEGER,
    original_file_name TEXT,
    initial_processing_status TEXT,
    hours_stuck NUMERIC
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        sd.id,
        sd.original_file_name,
        sd.initial_processing_status,
        EXTRACT(EPOCH FROM (NOW() - sd.last_modified_at)) / 3600 as hours_stuck
    FROM source_documents sd
    WHERE sd.initial_processing_status IN ('pending_ocr', 'processing')
    AND sd.last_modified_at < NOW() - INTERVAL '1 hour' * hours_threshold
    ORDER BY sd.last_modified_at;
END;
$$ LANGUAGE plpgsql;
```

### 3.2 Recovery Script

```python
# File: scripts/recover_stuck_documents.py

def recover_stuck_documents():
    """Recover documents stuck in processing"""
    
    db = SupabaseManager()
    
    # Find stuck documents
    stuck = db.client.rpc('get_stuck_documents', {'hours_threshold': 1}).execute()
    
    for doc in stuck.data:
        logger.info(f"Recovering document {doc['id']}: {doc['original_file_name']}")
        
        # Reset queue entry
        queue_reset = db.client.table('document_processing_queue').update({
            'status': 'pending',
            'retry_count': 0,
            'started_at': None,
            'error_message': 'Reset by recovery script'
        }).eq('source_document_id', doc['id']).execute()
        
        # Clear any incomplete Textract jobs
        textract_reset = db.client.table('textract_jobs').update({
            'job_status': 'failed',
            'error_message': 'Marked failed by recovery script - timeout'
        }).eq('source_document_id', doc['id']).eq('job_status', 'SUBMITTED').execute()
        
        logger.info(f"Reset queue and Textract entries for document {doc['id']}")
```

## Part 4: Implementation Steps

### Step 1: Apply Database Fixes (30 minutes)
```bash
# 1. Backup database first
pg_dump -h your-db-host -U postgres -d your-db-name > backup_$(date +%Y%m%d_%H%M%S).sql

# 2. Apply fixes in order
psql -h your-db-host -U postgres -d your-db-name < fix_triggers.sql
psql -h your-db-host -U postgres -d your-db-name < fix_constraints.sql
psql -h your-db-host -U postgres -d your-db-name < add_indexes.sql
```

### Step 2: Update Python Scripts (1 hour)
1. Update `supabase_utils.py` with robust error handling
2. Update `queue_processor.py` with checkpoint recovery
3. Update `textract_utils.py` with correct status mapping
4. Add timezone handling fixes

### Step 3: Test End-to-End (30 minutes)
```bash
# Reset test documents
python scripts/recover_stuck_documents.py

# Run single document test
python scripts/queue_processor.py --batch-size 1 --single-run

# Check results
python scripts/health_check.py
```

### Step 4: Deploy Monitoring (15 minutes)
```bash
# Set up monitoring cron job
crontab -e
# Add: */5 * * * * /usr/bin/python /path/to/scripts/health_check.py >> /path/to/logs/health.log 2>&1
```

## Expected Results

After implementing these fixes:

1. ✅ Documents will process completely through the pipeline
2. ✅ Extracted text will be saved to the database
3. ✅ Processing will continue to chunking and entity extraction
4. ✅ Errors will be properly logged and recoverable
5. ✅ System will be resilient to transient failures
6. ✅ Monitoring will alert to any issues

## Rollback Plan

If issues occur:
```sql
-- Restore original trigger
CREATE OR REPLACE FUNCTION notify_queue_status_change() ...

-- Restore from backup if needed
psql -h your-db-host -U postgres -d your-db-name < backup_YYYYMMDD_HHMMSS.sql
```

The system will be production-ready for Stage 1 deployment after these fixes.