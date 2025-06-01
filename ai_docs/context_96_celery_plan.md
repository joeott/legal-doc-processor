# Context 96: Comprehensive Celery Integration Implementation Plan

## Executive Summary

This plan outlines a systematic approach to refactor the existing NLP document processing pipeline from a monolithic `main_pipeline.py` and custom Redis Streams implementation to a robust, distributed task queue system using Celery with Redis as the message broker and result backend. The implementation will be executed in phases to ensure minimal disruption and maximum testing coverage.

## Architecture Overview

### Current State
- Monolithic pipeline: `main_pipeline.py` orchestrates all stages sequentially
- Custom Redis Streams implementation for queue management
- Manual retry logic and error handling
- Basic monitoring through `live_monitor.py`

### Target State
- Distributed Celery tasks for each pipeline stage
- Redis as Celery broker (using Lists) and result backend
- Built-in retry mechanisms with exponential backoff
- Flower dashboard for comprehensive monitoring
- Preserved existing Redis functionality (caching, locking, rate limiting)

## Implementation Phases

### Phase 1: Foundation Setup (Day 1)
1. **Celery Infrastructure**
   - Install required packages
   - Create Celery application configuration
   - Set up task discovery and module structure
   - Configure Redis connection parameters

2. **Project Structure**
   ```
   scripts/
   ├── celery_app.py          # Celery application instance
   ├── celery_tasks/          # Task modules directory
   │   ├── __init__.py
   │   ├── ocr_tasks.py       # OCR processing tasks
   │   ├── text_tasks.py      # Text processing & chunking
   │   ├── entity_tasks.py    # NER & resolution tasks
   │   └── graph_tasks.py     # Relationship building tasks
   └── celery_config.py       # Celery-specific configuration
   ```

### Phase 2: Task Definition (Day 2-3)
1. **Core Task Implementation**
   - Convert each pipeline stage to a Celery task
   - Implement proper error handling and retry logic
   - Add comprehensive logging and state tracking
   - Ensure JSON serialization for all task parameters

2. **Task Chain Design**
   - OCR Task → Document Node Creation → Chunking → NER → Resolution → Relationships
   - Each task calls the next upon successful completion
   - Failed tasks trigger retry with exponential backoff

### Phase 3: Queue Processor Integration (Day 4)
1. **Modify `queue_processor.py`**
   - Replace Redis Stream production with Celery task enqueueing
   - Maintain existing Supabase queue claiming logic
   - Update status tracking to reflect Celery task states

2. **State Management**
   - Integrate `update_document_state` with Celery task lifecycle
   - Store Celery task IDs in document processing history
   - Maintain backward compatibility with existing monitoring

### Phase 4: Testing & Validation (Day 5-6)
1. **Unit Tests**
   - Test each Celery task in isolation
   - Mock external dependencies (Supabase, AWS, OpenAI)
   - Verify retry logic and error handling

2. **Integration Tests**
   - End-to-end document processing through Celery
   - Test task chain execution
   - Verify state persistence and recovery

3. **Performance Tests**
   - Load testing with multiple workers
   - Measure throughput improvements
   - Validate resource utilization

### Phase 5: Monitoring & Operations (Day 7)
1. **Flower Setup**
   - Configure Flower dashboard
   - Set up authentication and access controls
   - Create monitoring views for different task types

2. **Operational Procedures**
   - Document worker management commands
   - Create deployment scripts
   - Establish backup and recovery procedures

## Detailed Implementation Guide

### Step 1: Install Dependencies
```bash
pip install celery[redis] flower celery-types
```

### Step 2: Create Celery Application (`scripts/celery_app.py`)
```python
from celery import Celery
import os
from scripts.config import REDIS_HOST, REDIS_PORT, REDIS_DB, REDIS_PASSWORD

# Construct Redis URL from existing config
redis_url = f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}" if REDIS_PASSWORD else f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"

# Create Celery app
app = Celery(
    'nlp_pipeline',
    broker=redis_url,
    backend=redis_url,
    include=['scripts.celery_tasks.ocr_tasks',
             'scripts.celery_tasks.text_tasks',
             'scripts.celery_tasks.entity_tasks',
             'scripts.celery_tasks.graph_tasks']
)

# Configure Celery
app.conf.update(
    task_serializer='json',
    result_serializer='json',
    accept_content=['json'],
    timezone='UTC',
    enable_utc=True,
    worker_prefetch_multiplier=1,  # Important for long-running tasks
    task_acks_late=True,
    result_expires=3600 * 24 * 7,  # 7 days
    task_track_started=True,
    task_send_sent_event=True,
    worker_send_task_events=True,
    task_soft_time_limit=3600,  # 1 hour soft limit
    task_time_limit=3900,  # 1 hour 5 min hard limit
    task_default_retry_delay=60,
    task_max_retry_delay=3600,
    task_retry_backoff=True,
    task_retry_backoff_max=600,
    task_retry_jitter=True,
)

if __name__ == '__main__':
    app.start()
```

### Step 3: Create Task Modules

#### OCR Tasks (`scripts/celery_tasks/ocr_tasks.py`)
```python
from celery import Task
from scripts.celery_app import app
from scripts.ocr_extraction import extract_text_from_pdf_textract, extract_text_from_docx
from scripts.supabase_utils import SupabaseManager
from scripts.redis_utils import update_document_state
import logging
import json
from datetime import datetime

logger = logging.getLogger(__name__)

class OCRTask(Task):
    """Base class for OCR tasks with database connection management"""
    _db_manager = None
    
    @property
    def db_manager(self):
        if self._db_manager is None:
            self._db_manager = SupabaseManager()
        return self._db_manager

@app.task(bind=True, base=OCRTask, max_retries=3, default_retry_delay=60)
def process_ocr(self, document_uuid: str, source_doc_sql_id: int, file_path: str, 
                file_name: str, detected_file_type: str, project_sql_id: int):
    """Process document OCR based on file type"""
    logger.info(f"[OCR_TASK:{self.request.id}] Processing document {document_uuid}")
    
    # Update state
    update_document_state(document_uuid, "ocr", "started", {"task_id": self.request.id})
    self.db_manager.update_processing_status('source_documents', source_doc_sql_id, 'ocr_processing')
    
    try:
        raw_text = None
        ocr_meta = None
        ocr_provider = None
        
        if detected_file_type == '.pdf':
            ocr_provider = 'textract'
            self.db_manager.client.table('source_documents').update({
                'ocr_provider': ocr_provider,
                'textract_job_status': 'initiating',
                'last_modified_at': datetime.now().isoformat()
            }).eq('id', source_doc_sql_id).execute()
            
            raw_text, ocr_meta = extract_text_from_pdf_textract(
                db_manager=self.db_manager,
                source_doc_sql_id=source_doc_sql_id,
                pdf_path_or_s3_uri=file_path,
                document_uuid_from_db=document_uuid
            )
        elif detected_file_type == '.docx':
            ocr_provider = 'docx_parser'
            raw_text = extract_text_from_docx(file_path)
            ocr_meta = [{"method": "docx_parser"}]
        # Add other file types...
        else:
            raise ValueError(f"Unsupported file type: {detected_file_type}")
        
        if raw_text:
            # Update database
            self.db_manager.update_source_document_text(
                source_doc_sql_id, raw_text,
                ocr_meta_json=json.dumps(ocr_meta) if ocr_meta else None,
                status="ocr_complete"
            )
            
            if ocr_provider:
                self.db_manager.client.table('source_documents').update({
                    'ocr_provider': ocr_provider,
                    'ocr_completed_at': datetime.now().isoformat()
                }).eq('id', source_doc_sql_id).execute()
            
            update_document_state(document_uuid, "ocr", "completed")
            
            # Chain to next task
            from scripts.celery_tasks.text_tasks import create_document_node
            create_document_node.delay(
                document_uuid=document_uuid,
                source_doc_sql_id=source_doc_sql_id,
                project_sql_id=project_sql_id,
                file_name=file_name,
                detected_file_type=detected_file_type,
                raw_text=raw_text,
                ocr_meta_json=json.dumps(ocr_meta) if ocr_meta else None
            )
            
            return {"status": "success", "document_uuid": document_uuid, "text_length": len(raw_text)}
        else:
            raise RuntimeError("OCR failed to extract text")
            
    except Exception as exc:
        logger.error(f"[OCR_TASK:{self.request.id}] Error: {exc}", exc_info=True)
        update_document_state(document_uuid, "ocr", "failed", {"error": str(exc)})
        self.db_manager.update_processing_status('source_documents', source_doc_sql_id, 'ocr_failed')
        
        # Retry with exponential backoff
        countdown = int(self.default_retry_delay * (2 ** self.request.retries))
        raise self.retry(exc=exc, countdown=min(countdown, 600))  # Max 10 minutes
```

### Step 4: Modify Queue Processor
```python
# In queue_processor.py, add:
from scripts.celery_tasks.ocr_tasks import process_ocr

# In _process_claimed_documents method, replace Redis Stream production with:
logger.info(f"Enqueueing OCR task for document: {doc_to_process['file_name']}")

# Enqueue Celery task
result = process_ocr.delay(
    document_uuid=str(doc_to_process['source_doc_uuid']),
    source_doc_sql_id=source_doc_sql_id,
    file_path=str(doc_to_process['file_path']),
    file_name=str(doc_to_process['file_name']),
    detected_file_type=str(doc_to_process['detected_file_type']),
    project_sql_id=int(doc_to_process['project_sql_id'])
)

# Store task ID
self.db_manager.client.table('source_documents').update({
    'celery_task_id': result.id,
    'initial_processing_status': 'ocr_queued'
}).eq('id', source_doc_sql_id).execute()
```

### Step 5: Create Worker Management Scripts

#### Start Workers (`scripts/start_celery_workers.sh`)
```bash
#!/bin/bash
# Start Celery workers with different configurations

# OCR worker - fewer processes, longer tasks
celery -A scripts.celery_app worker \
    --loglevel=INFO \
    --concurrency=2 \
    --pool=prefork \
    --queues=ocr \
    --hostname=ocr@%h &

# Text processing worker - more concurrency
celery -A scripts.celery_app worker \
    --loglevel=INFO \
    --concurrency=4 \
    --pool=gevent \
    --queues=text,entity \
    --hostname=text@%h &

# Flower monitoring
celery -A scripts.celery_app flower \
    --port=5555 \
    --broker=$CELERY_REDIS_URL &

echo "Celery workers started. Access Flower at http://localhost:5555"
```

### Step 6: Testing Strategy

#### Unit Test Example (`tests/unit/test_celery_tasks.py`)
```python
import pytest
from unittest.mock import patch, MagicMock
from scripts.celery_tasks.ocr_tasks import process_ocr

@pytest.fixture
def mock_db_manager():
    with patch('scripts.celery_tasks.ocr_tasks.SupabaseManager') as mock:
        db_instance = MagicMock()
        mock.return_value = db_instance
        yield db_instance

def test_process_ocr_pdf_success(mock_db_manager):
    """Test successful PDF OCR processing"""
    with patch('scripts.celery_tasks.ocr_tasks.extract_text_from_pdf_textract') as mock_extract:
        mock_extract.return_value = ("Extracted text", [{"pages": 1}])
        
        # Mock the task
        task = MagicMock()
        task.request.id = "test-task-123"
        task.request.retries = 0
        
        # Call the task
        result = process_ocr.run(
            document_uuid="test-uuid",
            source_doc_sql_id=1,
            file_path="test.pdf",
            file_name="test.pdf",
            detected_file_type=".pdf",
            project_sql_id=1
        )
        
        assert result["status"] == "success"
        assert result["text_length"] == 14
        mock_db_manager.update_source_document_text.assert_called_once()
```

### Step 7: Migration Script
```python
# scripts/migrate_to_celery.py
"""Script to migrate existing pipeline to Celery-based processing"""

import sys
from scripts.supabase_utils import SupabaseManager
from scripts.celery_tasks.ocr_tasks import process_ocr
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def migrate_pending_documents():
    """Migrate pending documents to Celery task queue"""
    db = SupabaseManager()
    
    # Find documents in processing state
    pending = db.client.table('source_documents').select('*').in_(
        'initial_processing_status', 
        ['pending', 'ocr_processing', 'ocr_failed']
    ).execute()
    
    logger.info(f"Found {len(pending.data)} documents to migrate")
    
    for doc in pending.data:
        try:
            # Enqueue in Celery
            result = process_ocr.delay(
                document_uuid=doc['document_uuid'],
                source_doc_sql_id=doc['id'],
                file_path=doc['file_path'],
                file_name=doc['file_name'],
                detected_file_type=doc.get('detected_file_type', '.pdf'),
                project_sql_id=doc['project_id']
            )
            
            # Update with task ID
            db.client.table('source_documents').update({
                'celery_task_id': result.id,
                'initial_processing_status': 'ocr_queued'
            }).eq('id', doc['id']).execute()
            
            logger.info(f"Migrated document {doc['id']} to Celery task {result.id}")
            
        except Exception as e:
            logger.error(f"Failed to migrate document {doc['id']}: {e}")
            
if __name__ == "__main__":
    migrate_pending_documents()
```

### Step 8: Monitoring Configuration

#### Flower Authentication (`scripts/flower_config.py`)
```python
# Basic authentication for Flower
import os

# Set via environment variables
FLOWER_BASIC_AUTH = os.getenv('FLOWER_BASIC_AUTH', 'admin:password')
FLOWER_PORT = int(os.getenv('FLOWER_PORT', 5555))

# Persistent database for Flower
FLOWER_DB = "flower.db"
FLOWER_PERSISTENT = True
FLOWER_MAX_TASKS = 10000

# URL prefix if behind proxy
FLOWER_URL_PREFIX = os.getenv('FLOWER_URL_PREFIX', '')
```

### Step 9: Production Deployment

#### Systemd Service (`/etc/systemd/system/celery-nlp.service`)
```ini
[Unit]
Description=Celery NLP Pipeline Worker
After=network.target redis.service

[Service]
Type=forking
User=nlp-user
Group=nlp-group
EnvironmentFile=/etc/celery/nlp-pipeline.conf
WorkingDirectory=/opt/nlp-pipeline
ExecStart=/bin/sh -c '${CELERY_BIN} -A $CELERY_APP multi start $CELERYD_NODES \
    --pidfile=${CELERYD_PID_FILE} \
    --logfile=${CELERYD_LOG_FILE} \
    --loglevel="${CELERYD_LOG_LEVEL}" $CELERYD_OPTS'
ExecStop=/bin/sh -c '${CELERY_BIN} multi stopwait $CELERYD_NODES \
    --pidfile=${CELERYD_PID_FILE}'
ExecReload=/bin/sh -c '${CELERY_BIN} -A $CELERY_APP multi restart $CELERYD_NODES \
    --pidfile=${CELERYD_PID_FILE} \
    --logfile=${CELERYD_LOG_FILE} \
    --loglevel="${CELERYD_LOG_LEVEL}" $CELERYD_OPTS'
Restart=always

[Install]
WantedBy=multi-user.target
```

### Step 10: Performance Tuning

#### Redis Configuration Updates
```bash
# Add to Redis configuration for Celery optimization
redis-cli CONFIG SET maxmemory-policy allkeys-lru
redis-cli CONFIG SET tcp-keepalive 60
redis-cli CONFIG SET timeout 300

# Celery-specific settings
redis-cli CONFIG SET list-max-ziplist-size -2
redis-cli CONFIG SET list-compress-depth 1
```

## Testing & Verification Checklist

### Pre-deployment Tests
- [ ] All unit tests pass for Celery tasks
- [ ] Integration tests confirm end-to-end processing
- [ ] Load tests show improved throughput
- [ ] Flower dashboard accessible and showing tasks
- [ ] Worker auto-restart on failure confirmed
- [ ] Redis memory usage within limits
- [ ] Task retry logic functioning correctly
- [ ] Dead letter queue handling tested

### Deployment Steps
1. **Stop existing pipeline**: `systemctl stop nlp-pipeline`
2. **Deploy Celery code**: `git pull && pip install -r requirements.txt`
3. **Run migrations**: `python scripts/migrate_to_celery.py`
4. **Start Celery workers**: `systemctl start celery-nlp`
5. **Start Flower**: `systemctl start celery-flower`
6. **Monitor initial processing**: Watch Flower dashboard
7. **Verify queue processing**: Check Supabase queue status

### Post-deployment Monitoring
- [ ] Monitor Flower dashboard for task failures
- [ ] Check Redis memory usage trends
- [ ] Verify document processing times
- [ ] Monitor worker CPU and memory usage
- [ ] Check error rates and retry counts
- [ ] Validate end-to-end document flow

## Rollback Plan

If issues arise:
1. **Stop Celery workers**: `systemctl stop celery-nlp`
2. **Revert code**: `git checkout previous-tag`
3. **Restart old pipeline**: `systemctl start nlp-pipeline`
4. **Clear Celery queues**: `celery -A scripts.celery_app purge`
5. **Reset document states**: Run rollback script

## Success Metrics

### Performance Improvements
- **Throughput**: 3-5x increase in documents/hour
- **Reliability**: <1% failure rate with retries
- **Resource Usage**: Better CPU utilization across workers
- **Monitoring**: Real-time visibility into processing

### Operational Benefits
- **Scalability**: Easy to add/remove workers
- **Maintainability**: Clear task separation
- **Debuggability**: Better error tracking and logs
- **Flexibility**: Easy to modify individual stages

## Appendix: Complete Task Definitions

### Text Processing Tasks (`scripts/celery_tasks/text_tasks.py`)
```python
@app.task(bind=True, base=DatabaseTask, max_retries=3)
def create_document_node(self, document_uuid: str, source_doc_sql_id: int, 
                        project_sql_id: int, file_name: str, 
                        detected_file_type: str, raw_text: str, 
                        ocr_meta_json: str):
    """Create Neo4j document node and prepare for chunking"""
    # Implementation details...

@app.task(bind=True, base=DatabaseTask, max_retries=3)
def process_chunking(self, document_uuid: str, neo4j_doc_sql_id: int,
                    neo4j_doc_uuid: str, cleaned_text: str, 
                    ocr_meta_json: str, doc_category: str):
    """Perform semantic chunking on document text"""
    # Implementation details...
```

### Entity Tasks (`scripts/celery_tasks/entity_tasks.py`)
```python
@app.task(bind=True, base=DatabaseTask, max_retries=3)
def extract_entities(self, document_uuid: str, neo4j_doc_sql_id: int,
                    neo4j_doc_uuid: str, chunk_data: list):
    """Extract entities from document chunks"""
    # Implementation details...

@app.task(bind=True, base=DatabaseTask, max_retries=3)
def resolve_entities(self, document_uuid: str, neo4j_doc_sql_id: int,
                    neo4j_doc_uuid: str, entity_mentions: str, 
                    full_text: str):
    """Resolve and canonicalize extracted entities"""
    # Implementation details...
```

### Graph Tasks (`scripts/celery_tasks/graph_tasks.py`)
```python
@app.task(bind=True, base=DatabaseTask, max_retries=3)
def build_relationships(self, document_uuid: str, doc_data: dict,
                       project_uuid: str, chunks: list, 
                       entities: list, canonicals: list):
    """Build graph relationships for Neo4j export"""
    # Implementation details...
```

## Conclusion

This comprehensive plan provides a systematic approach to migrating from a monolithic pipeline to a distributed Celery-based system. The implementation focuses on maintaining existing functionality while adding robustness, scalability, and operational visibility. The phased approach ensures minimal disruption and allows for thorough testing at each stage.