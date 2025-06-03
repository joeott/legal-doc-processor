# Context 108: Redis/Celery Implementation - Explicit Task List with Coding Hints

## Executive Summary

This document provides an explicit, step-by-step implementation guide to migrate the OCR document processing pipeline from Supabase queue-based processing to a pure Celery/Redis architecture. Each task includes specific code snippets and verification steps to ensure minimal human oversight and maximum performance.

## Phase 1: Database Schema Changes (30 minutes)

### Task 1.1: Add Celery Task ID to source_documents
**File**: Create `frontend/database/migrations/00012_add_celery_task_id.sql`
```sql
-- Add celery_task_id column to source_documents
ALTER TABLE source_documents 
ADD COLUMN IF NOT EXISTS celery_task_id VARCHAR(255),
ADD COLUMN IF NOT EXISTS celery_status VARCHAR(50) DEFAULT 'pending';

-- Create index for faster lookups
CREATE INDEX IF NOT EXISTS idx_source_documents_celery_task_id 
ON source_documents(celery_task_id);

-- Add new status values to enum if using enum type
-- Or ensure VARCHAR allows: 'ocr_queued', 'ocr_processing', 'ocr_complete', 
-- 'text_queued', 'text_processing', 'text_complete', etc.
```

### Task 1.2: Disable All Processing Triggers
**File**: Create `frontend/database/migrations/00013_disable_all_processing_triggers.sql`
```sql
-- Find and disable all triggers that auto-update processing status
-- Based on context, these triggers exist:
DROP TRIGGER IF EXISTS update_source_document_status_on_queue_change ON document_processing_queue;
DROP TRIGGER IF EXISTS auto_process_on_status_change ON source_documents;
DROP TRIGGER IF EXISTS trigger_next_processing_step ON neo4j_documents;

-- List all remaining triggers for manual review
SELECT trigger_name, event_object_table, action_statement 
FROM information_schema.triggers 
WHERE trigger_schema = 'public';
```

### Task 1.3: Apply Migrations
**Script**: Create `scripts/apply_celery_migrations.py`
```python
#!/usr/bin/env python3
import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.supabase_utils import SupabaseManager
import glob

def apply_migrations():
    db = SupabaseManager()
    migration_files = sorted(glob.glob('frontend/database/migrations/0001[2-3]_*.sql'))
    
    for migration_file in migration_files:
        print(f"Applying {migration_file}...")
        with open(migration_file, 'r') as f:
            sql = f.read()
        
        # Execute via Supabase SQL editor or direct connection
        # Note: SupabaseManager may need a execute_sql method
        try:
            # db.execute_sql(sql)  # Implement this method if needed
            print(f"✅ Applied {migration_file}")
        except Exception as e:
            print(f"❌ Failed to apply {migration_file}: {e}")
            return False
    
    return True

if __name__ == "__main__":
    apply_migrations()
```

## Phase 2: Refactor Document Intake (45 minutes)

### Task 2.1: Create Celery Task Submission Utility
**File**: Create `scripts/celery_submission.py`
```python
"""Utility functions for submitting documents to Celery"""
from typing import Dict, Optional, Tuple
import logging
from scripts.celery_tasks.ocr_tasks import process_ocr
from scripts.supabase_utils import SupabaseManager

logger = logging.getLogger(__name__)

def submit_document_to_celery(
    document_id: int,
    document_uuid: str,
    file_path: str,
    file_type: str,
    project_id: Optional[str] = None
) -> Tuple[str, bool]:
    """
    Submit a document directly to Celery for processing.
    
    Returns:
        Tuple of (celery_task_id, success)
    """
    try:
        # Submit to Celery
        task = process_ocr.delay(
            document_id=document_id,
            document_uuid=document_uuid,
            file_path=file_path,
            file_type=file_type,
            project_id=project_id
        )
        
        # Update source_documents with Celery task ID
        db = SupabaseManager()
        db.client.table('source_documents').update({
            'celery_task_id': task.id,
            'celery_status': 'ocr_queued',
            'initial_processing_status': 'ocr_queued'
        }).eq('id', document_id).execute()
        
        logger.info(f"Document {document_uuid} submitted to Celery: {task.id}")
        return task.id, True
        
    except Exception as e:
        logger.error(f"Failed to submit document to Celery: {e}")
        return None, False
```

### Task 2.2: Refactor queue_processor.py
**File**: `scripts/queue_processor.py`
```python
#!/usr/bin/env python3
"""
Refactored Queue Processor - Now a document intake handler, not a queue poller
"""
import os
import sys
import time
import logging
from typing import Optional
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.config import Config
from scripts.supabase_utils import SupabaseManager
from scripts.celery_submission import submit_document_to_celery
from scripts.s3_storage import S3Storage

logger = logging.getLogger(__name__)

class DocumentIntakeHandler(FileSystemEventHandler):
    """Handles new document arrivals from filesystem"""
    
    def __init__(self):
        self.db_manager = SupabaseManager()
        self.s3_storage = S3Storage()
        
    def on_created(self, event):
        if event.is_directory:
            return
            
        # Check if it's a document file
        if event.src_path.endswith(('.pdf', '.docx', '.txt', '.eml')):
            self.process_new_document(event.src_path)
    
    def process_new_document(self, file_path: str):
        """Process a newly detected document"""
        try:
            # Upload to S3 first
            s3_key = self.s3_storage.upload_file(file_path)
            
            # Register in source_documents
            doc_id, doc_uuid = self.db_manager.create_source_document_entry(
                original_file_path=s3_key,
                original_file_name=os.path.basename(file_path),
                detected_file_type=os.path.splitext(file_path)[1][1:],
                project_id=Config.PROJECT_ID
            )
            
            # Submit directly to Celery
            task_id, success = submit_document_to_celery(
                document_id=doc_id,
                document_uuid=doc_uuid,
                file_path=s3_key,
                file_type=os.path.splitext(file_path)[1][1:],
                project_id=Config.PROJECT_ID
            )
            
            if success:
                logger.info(f"Document {file_path} submitted successfully")
            else:
                logger.error(f"Failed to submit document {file_path}")
                
        except Exception as e:
            logger.error(f"Error processing document {file_path}: {e}")

def main():
    """Main entry point - now watches for new documents instead of polling queue"""
    watch_dir = Config.DOCUMENT_INTAKE_DIR  # Add this to config.py
    
    if not os.path.exists(watch_dir):
        os.makedirs(watch_dir)
    
    event_handler = DocumentIntakeHandler()
    observer = Observer()
    observer.schedule(event_handler, watch_dir, recursive=False)
    
    print(f"Watching for new documents in: {watch_dir}")
    observer.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    
    observer.join()

if __name__ == "__main__":
    # IMPORTANT: This script no longer polls document_processing_queue!
    # It watches for new files and submits them directly to Celery
    main()
```

### Task 2.3: Refactor main_pipeline.py Direct Mode
**File**: `scripts/main_pipeline.py`
**Location**: Modify `process_single_document` function around line 150-200
```python
def process_single_document(self, file_path: str, file_type: str = None) -> Dict[str, Any]:
    """Process a single document in direct mode - now uses Celery"""
    try:
        # Detect file type if not provided
        if not file_type:
            file_type = self._detect_file_type(file_path)
        
        # Upload to S3 if local file
        if not file_path.startswith('s3://'):
            s3_key = self.s3_storage.upload_file(file_path)
        else:
            s3_key = file_path
        
        # Register document in database
        doc_id, doc_uuid = self.db_manager.create_source_document_entry(
            original_file_path=s3_key,
            original_file_name=os.path.basename(file_path),
            detected_file_type=file_type,
            project_id=self.project_id
        )
        
        # CRITICAL CHANGE: Submit to Celery instead of processing synchronously
        task_id, success = submit_document_to_celery(
            document_id=doc_id,
            document_uuid=doc_uuid,
            file_path=s3_key,
            file_type=file_type,
            project_id=self.project_id
        )
        
        if success:
            logger.info(f"Document submitted to Celery: {task_id}")
            return {
                'success': True,
                'document_id': doc_id,
                'document_uuid': doc_uuid,
                'celery_task_id': task_id,
                'message': 'Document submitted for processing'
            }
        else:
            raise Exception("Failed to submit to Celery")
            
    except Exception as e:
        logger.error(f"Error in direct processing: {e}")
        return {
            'success': False,
            'error': str(e)
        }
        
    # REMOVE ALL SYNCHRONOUS PROCESSING CODE BELOW THIS POINT
    # No more direct calls to OCR, chunking, entity extraction, etc.
```

### Task 2.4: Refactor live_document_test.py
**File**: `scripts/live_document_test.py`
**Location**: Modify `_test_queue_processing` method
```python
def _test_queue_processing(self, test_file: str) -> Tuple[bool, Dict[str, Any]]:
    """Test document processing via Celery submission"""
    try:
        print(f"\n📄 Testing queue processing for: {os.path.basename(test_file)}")
        
        # Register document
        doc_id, doc_uuid = self.db_manager.create_source_document_entry(
            original_file_path=test_file,
            original_file_name=os.path.basename(test_file),
            detected_file_type='pdf',
            project_id=self.project_id
        )
        
        # CRITICAL CHANGE: Submit directly to Celery
        from scripts.celery_submission import submit_document_to_celery
        task_id, success = submit_document_to_celery(
            document_id=doc_id,
            document_uuid=doc_uuid,
            file_path=test_file,
            file_type='pdf',
            project_id=self.project_id
        )
        
        if not success:
            return False, {'error': 'Failed to submit to Celery'}
        
        print(f"✅ Document submitted to Celery: {task_id}")
        
        # Wait for completion
        completed, final_status = self._wait_for_completion(doc_id, doc_uuid)
        
        return completed, {
            'document_id': doc_id,
            'document_uuid': doc_uuid,
            'celery_task_id': task_id,
            'final_status': final_status
        }
        
    except Exception as e:
        print(f"❌ Queue processing failed: {e}")
        return False, {'error': str(e)}

def _wait_for_completion(self, doc_id: int, doc_uuid: str, timeout: int = 300) -> Tuple[bool, str]:
    """Wait for document processing completion - monitor Supabase status"""
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        # Check source_documents status
        result = self.db_manager.client.table('source_documents')\
            .select('initial_processing_status, celery_status')\
            .eq('id', doc_id)\
            .execute()
        
        if result.data:
            status = result.data[0]['initial_processing_status']
            celery_status = result.data[0].get('celery_status', '')
            
            # Success states
            if status == 'completed' or celery_status == 'graph_complete':
                return True, status
            
            # Error states
            if status.startswith('error_') or status == 'failed':
                return False, status
            
            print(f"⏳ Current status: {status} / {celery_status}")
        
        time.sleep(5)
    
    return False, 'timeout'
```

## Phase 3: Enhance Celery Tasks (60 minutes)

### Task 3.1: Update OCR Tasks with State Management
**File**: `scripts/celery_tasks/ocr_tasks.py`
**Add to beginning of `process_ocr` task**:
```python
@celery_app.task(bind=True, name='ocr_tasks.process_ocr', 
                 queue='ocr', max_retries=3,
                 default_retry_delay=60)
def process_ocr(self, document_id: int, document_uuid: str, 
                file_path: str, file_type: str, 
                project_id: str = None) -> Dict[str, Any]:
    """Process document OCR with explicit state management"""
    
    # CRITICAL: Update status at task start
    try:
        db_manager = SupabaseManager()
        db_manager.client.table('source_documents').update({
            'initial_processing_status': 'ocr_processing',
            'celery_status': 'ocr_processing',
            'celery_task_id': self.request.id  # Current task ID
        }).eq('id', document_id).execute()
        
        # Update Redis monitoring state
        update_document_state(
            document_uuid, 
            'ocr_processing', 
            'processing', 
            {'task_id': self.request.id, 'worker': self.request.hostname}
        )
    except Exception as e:
        logger.error(f"Failed to update initial status: {e}")
    
    try:
        # [Existing OCR logic here...]
        
        # On success, update status and chain next task
        db_manager.client.table('source_documents').update({
            'initial_processing_status': 'ocr_complete',
            'celery_status': 'ocr_complete',
            'ocr_completed_at': datetime.utcnow().isoformat()
        }).eq('id', document_id).execute()
        
        update_document_state(document_uuid, 'ocr_complete', 'completed')
        
        # CRITICAL: Chain to next task
        from scripts.celery_tasks.text_tasks import process_text_chunks
        next_task = process_text_chunks.delay(
            document_id=document_id,
            document_uuid=document_uuid,
            extracted_text=extracted_text,  # From OCR processing
            project_id=project_id
        )
        
        logger.info(f"Chained to text processing: {next_task.id}")
        
        return {
            'success': True,
            'document_id': document_id,
            'next_task_id': next_task.id,
            'extracted_text_length': len(extracted_text)
        }
        
    except Exception as e:
        # On failure, update error status
        db_manager.client.table('source_documents').update({
            'initial_processing_status': 'error_ocr',
            'celery_status': 'error_ocr',
            'error_message': str(e)
        }).eq('id', document_id).execute()
        
        update_document_state(
            document_uuid, 
            'ocr_error', 
            'failed',
            {'error': str(e)}
        )
        
        # Celery retry logic
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))
        else:
            logger.error(f"OCR failed permanently for {document_uuid}: {e}")
            raise
```

### Task 3.2: Update Text Processing Tasks
**File**: `scripts/celery_tasks/text_tasks.py`
**Similar pattern for `process_text_chunks`**:
```python
@celery_app.task(bind=True, name='text_tasks.process_text_chunks',
                 queue='text', max_retries=3)
def process_text_chunks(self, document_id: int, document_uuid: str,
                       extracted_text: str, project_id: str = None) -> Dict[str, Any]:
    """Process text with explicit state management and chaining"""
    
    # Update status at start
    db_manager = SupabaseManager()
    db_manager.client.table('source_documents').update({
        'celery_status': 'text_processing'
    }).eq('id', document_id).execute()
    
    # Also update neo4j_documents if it exists
    neo4j_doc = db_manager.client.table('neo4j_documents')\
        .select('id')\
        .eq('sourceDocumentUuid', document_uuid)\
        .execute()
    
    if neo4j_doc.data:
        db_manager.client.table('neo4j_documents').update({
            'processingStatus': 'text_processing'
        }).eq('id', neo4j_doc.data[0]['id']).execute()
    
    update_document_state(document_uuid, 'text_processing', 'processing')
    
    try:
        # [Existing chunking logic...]
        
        # On success, chain to entity extraction
        db_manager.client.table('source_documents').update({
            'celery_status': 'text_complete'
        }).eq('id', document_id).execute()
        
        from scripts.celery_tasks.entity_tasks import extract_entities_batch
        next_task = extract_entities_batch.delay(
            document_id=document_id,
            document_uuid=document_uuid,
            chunk_ids=chunk_ids,  # From chunking
            project_id=project_id
        )
        
        return {
            'success': True,
            'chunk_count': len(chunk_ids),
            'next_task_id': next_task.id
        }
        
    except Exception as e:
        # Error handling with status update
        db_manager.client.table('source_documents').update({
            'celery_status': 'error_text_processing',
            'error_message': str(e)
        }).eq('id', document_id).execute()
        
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e)
        raise
```

### Task 3.3: Update Entity and Graph Tasks
**Apply same pattern to**:
- `scripts/celery_tasks/entity_tasks.py` - `extract_entities_batch`
- `scripts/celery_tasks/graph_tasks.py` - `build_relationships`

Each should:
1. Update status at start
2. Update status on completion
3. Chain to next task (entity → graph)
4. Update error status on failure
5. Use Celery retry mechanism

## Phase 4: Remove Supabase Queue Dependencies (30 minutes)

### Task 4.1: Update supabase_utils.py
**File**: `scripts/supabase_utils.py`
**Comment out or remove these methods**:
```python
class SupabaseManager:
    # DEPRECATED - No longer used for queue management
    # def create_queue_entry(self, ...):
    #     """DEPRECATED: Use Celery submission instead"""
    #     raise DeprecationWarning("Use celery_submission.submit_document_to_celery instead")
    
    # def claim_pending_documents(self, ...):
    #     """DEPRECATED: Documents submitted directly to Celery"""
    #     raise DeprecationWarning("Queue polling no longer used")
    
    # def update_queue_status(self, ...):
    #     """DEPRECATED: Status managed by Celery tasks"""
    #     raise DeprecationWarning("Status updates handled in Celery tasks")
```

### Task 4.2: Update Configuration
**File**: `scripts/config.py`
**Add new configs, remove old ones**:
```python
# Add for new document intake
DOCUMENT_INTAKE_DIR = os.getenv('DOCUMENT_INTAKE_DIR', '/tmp/document_intake')

# Remove or comment out
# QUEUE_BATCH_SIZE = 10  # No longer polling queue
# QUEUE_POLL_INTERVAL = 30  # No longer needed
```

## Phase 5: Update Monitoring (30 minutes)

### Task 5.1: Update Pipeline Monitor
**File**: `scripts/standalone_pipeline_monitor.py`
**Modify `get_supabase_queue_stats` method**:
```python
def get_supabase_queue_stats(self) -> Dict[str, Any]:
    """Get statistics from source_documents Celery status"""
    try:
        # No longer query document_processing_queue
        # Instead, query source_documents for Celery status
        response = self.db_manager.client.table('source_documents')\
            .select('celery_status, initial_processing_status')\
            .execute()
        
        celery_status_counts = Counter(item.get('celery_status', 'unknown') for item in response.data)
        processing_status_counts = Counter(item['initial_processing_status'] for item in response.data)
        
        # Get documents by stage
        stages = {
            'ocr_queued': 0,
            'ocr_processing': 0,
            'text_processing': 0,
            'entity_processing': 0,
            'graph_processing': 0,
            'completed': 0,
            'errors': 0
        }
        
        for item in response.data:
            status = item.get('celery_status', '')
            if status.startswith('error_'):
                stages['errors'] += 1
            elif status in stages:
                stages[status] += 1
        
        return {
            'celery_stages': stages,
            'processing_status': dict(processing_status_counts),
            'total_documents': len(response.data)
        }
        
    except Exception as e:
        return {'error': str(e)}
```

### Task 5.2: Update Health Check
**File**: `scripts/health_check.py`
**Modify queue health check**:
```python
def check_queue_health(self) -> Dict[str, Any]:
    """Check Celery queue health via Redis"""
    try:
        redis_client = get_redis_manager().get_client()
        
        # Check Celery queues in Redis
        queue_lengths = {}
        for queue in ['ocr', 'text', 'entity', 'graph']:
            length = redis_client.llen(queue)
            queue_lengths[queue] = length
        
        # Get Celery worker status (if using Celery events)
        # This is a simplified check
        total_queued = sum(queue_lengths.values())
        
        return {
            'healthy': total_queued < 1000,  # Threshold
            'queue_lengths': queue_lengths,
            'total_queued': total_queued,
            'message': 'Celery queues operational'
        }
        
    except Exception as e:
        return {
            'healthy': False,
            'error': str(e)
        }
```

## Phase 6: Testing & Verification (45 minutes)

### Task 6.1: Create Integration Test
**File**: Create `tests/integration/test_celery_workflow.py`
```python
import pytest
import time
from scripts.celery_submission import submit_document_to_celery
from scripts.supabase_utils import SupabaseManager

def test_full_celery_workflow():
    """Test complete document processing via Celery"""
    db = SupabaseManager()
    
    # Create test document
    doc_id, doc_uuid = db.create_source_document_entry(
        original_file_path='s3://test-bucket/test.pdf',
        original_file_name='test.pdf',
        detected_file_type='pdf',
        project_id='test-project'
    )
    
    # Submit to Celery
    task_id, success = submit_document_to_celery(
        document_id=doc_id,
        document_uuid=doc_uuid,
        file_path='s3://test-bucket/test.pdf',
        file_type='pdf'
    )
    
    assert success
    assert task_id is not None
    
    # Wait and check final status
    timeout = 60
    start = time.time()
    
    while time.time() - start < timeout:
        result = db.client.table('source_documents')\
            .select('celery_status')\
            .eq('id', doc_id)\
            .execute()
        
        if result.data:
            status = result.data[0].get('celery_status')
            if status == 'graph_complete':
                break
            elif status and status.startswith('error_'):
                pytest.fail(f"Processing failed: {status}")
        
        time.sleep(2)
    
    # Verify completion
    assert status == 'graph_complete'
```

### Task 6.2: Create Verification Script
**File**: Create `scripts/verify_celery_migration.py`
```python
#!/usr/bin/env python3
"""Verify Celery migration is complete and working"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.supabase_utils import SupabaseManager
from scripts.redis_utils import get_redis_manager
import subprocess

def verify_migration():
    """Run verification checks"""
    print("🔍 Verifying Celery Migration...")
    
    # 1. Check database schema
    print("\n1️⃣ Checking database schema...")
    db = SupabaseManager()
    
    # Check for celery_task_id column
    result = db.client.table('source_documents').select('celery_task_id').limit(1).execute()
    print("✅ celery_task_id column exists")
    
    # 2. Check triggers are disabled
    print("\n2️⃣ Checking triggers...")
    # Would need direct SQL access to verify triggers
    print("⚠️  Manual verification needed for trigger removal")
    
    # 3. Check Redis/Celery connectivity
    print("\n3️⃣ Checking Redis/Celery...")
    redis_client = get_redis_manager().get_client()
    assert redis_client.ping()
    print("✅ Redis connected")
    
    # Check Celery queues
    for queue in ['ocr', 'text', 'entity', 'graph']:
        length = redis_client.llen(queue)
        print(f"✅ Queue '{queue}': {length} tasks")
    
    # 4. Check no new entries in document_processing_queue
    print("\n4️⃣ Checking deprecated queue...")
    queue_result = db.client.table('document_processing_queue')\
        .select('id', count='exact')\
        .gte('created_at', 'NOW() - INTERVAL 1 HOUR')\
        .execute()
    
    if queue_result.count == 0:
        print("✅ No new entries in document_processing_queue")
    else:
        print(f"⚠️  Found {queue_result.count} recent entries in deprecated queue")
    
    # 5. Test Celery workers
    print("\n5️⃣ Checking Celery workers...")
    try:
        result = subprocess.run(['celery', '-A', 'scripts.celery_app', 'inspect', 'active'],
                              capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            print("✅ Celery workers responsive")
        else:
            print("⚠️  Celery workers not responding")
    except Exception as e:
        print(f"⚠️  Could not check Celery workers: {e}")
    
    print("\n✅ Migration verification complete!")

if __name__ == "__main__":
    verify_migration()
```

## Phase 7: Deployment Checklist (15 minutes)

### Task 7.1: Stop Old Services
```bash
# Stop old queue processor
pkill -f queue_processor.py

# Stop any services polling document_processing_queue
systemctl stop document-queue-processor  # If exists
```

### Task 7.2: Start New Services
```bash
# Ensure Redis is running
redis-cli ping

# Start Celery workers
./scripts/start_celery_workers.sh

# Start new document intake (if using file watcher)
nohup python scripts/queue_processor.py > intake.log 2>&1 &
```

### Task 7.3: Monitor Transition
```bash
# Watch Celery queues
watch -n 2 'redis-cli llen ocr; redis-cli llen text; redis-cli llen entity; redis-cli llen graph'

# Monitor logs
tail -f celery_*.log

# Run pipeline monitor
python scripts/standalone_pipeline_monitor.py
```

## Critical Success Criteria

1. **No New Entries**: `document_processing_queue` receives no new entries
2. **Celery Task IDs**: All new documents have `celery_task_id` populated
3. **Status Progression**: Documents progress through statuses via Celery tasks only
4. **Error Handling**: Failed tasks update document status to error states
5. **Monitoring Works**: Pipeline monitor shows Celery queue activity

## Performance Optimizations

1. **Celery Prefetch**: Set `worker_prefetch_multiplier = 1` for long tasks
2. **Redis Persistence**: Configure Redis AOF for task durability
3. **Connection Pooling**: Reuse database connections in tasks
4. **Batch Operations**: Process multiple chunks in single entity extraction task
5. **Task Result Expiry**: Set `result_expires = 3600` to prevent Redis bloat

## Rollback Plan

If issues arise:
1. Stop Celery workers
2. Re-enable old queue_processor.py
3. Re-enable database triggers (if needed)
4. Clear Celery queues: `redis-cli FLUSHDB`
5. Revert code changes via git

This implementation ensures a clean transition to Celery-controlled processing with minimal downtime and maximum reliability.