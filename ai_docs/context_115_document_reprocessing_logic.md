# Context 115: Document Reprocessing Logic Strategy

## Executive Summary

This document outlines a comprehensive strategy for implementing robust document reprocessing logic in the Celery-based pipeline. The strategy addresses duplicate key constraints, partial processing recovery, and provides a production-ready approach to handle various reprocessing scenarios while maintaining data integrity and system reliability.

## Core Principles

1. **Idempotency**: Every operation should produce the same result regardless of how many times it's executed
2. **Atomicity**: Processing stages should either complete fully or leave no partial state
3. **Resumability**: Failed processing should be resumable from the last successful checkpoint
4. **Auditability**: All processing attempts and state changes should be tracked
5. **Efficiency**: Avoid unnecessary recomputation of already-processed data

## Reprocessing Strategy Overview

### Three-Tier Approach

1. **Incremental Resume** (Default): Continue from last successful stage
2. **Stage Restart**: Re-run specific stage(s) while preserving others
3. **Full Reprocess**: Complete cleanup and fresh processing

## Detailed Implementation Plan

### 1. Database Schema Enhancements

Add processing metadata to track reprocessing:

```sql
-- Add to source_documents table
ALTER TABLE source_documents ADD COLUMN IF NOT EXISTS processing_version INTEGER DEFAULT 1;
ALTER TABLE source_documents ADD COLUMN IF NOT EXISTS last_successful_stage TEXT;
ALTER TABLE source_documents ADD COLUMN IF NOT EXISTS processing_attempts INTEGER DEFAULT 0;
ALTER TABLE source_documents ADD COLUMN IF NOT EXISTS force_reprocess BOOLEAN DEFAULT FALSE;

-- Create processing history table
CREATE TABLE IF NOT EXISTS document_processing_history (
    id SERIAL PRIMARY KEY,
    document_uuid UUID NOT NULL REFERENCES source_documents(document_uuid),
    processing_version INTEGER NOT NULL,
    stage TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TIMESTAMP WITH TIME ZONE NOT NULL,
    completed_at TIMESTAMP WITH TIME ZONE,
    error_message TEXT,
    error_details JSONB,
    celery_task_id TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Index for efficient queries
CREATE INDEX idx_processing_history_doc_version ON document_processing_history(document_uuid, processing_version);
```

### 2. Enhanced State Management

```python
# scripts/celery_tasks/processing_state.py
from enum import Enum
from typing import Optional, Dict, Any
import json
from datetime import datetime

class ProcessingStage(Enum):
    """Ordered processing stages"""
    PENDING = "pending"
    OCR_PROCESSING = "ocr_processing"
    OCR_COMPLETE = "ocr_complete"
    TEXT_PROCESSING = "text_processing"
    TEXT_COMPLETE = "text_complete"
    ENTITY_EXTRACTION = "entity_extraction"
    ENTITY_COMPLETE = "entity_complete"
    ENTITY_RESOLUTION = "entity_resolution"
    RESOLUTION_COMPLETE = "resolution_complete"
    GRAPH_BUILDING = "graph_building"
    COMPLETED = "completed"
    
    @property
    def next_stage(self) -> Optional['ProcessingStage']:
        """Get the next stage in sequence"""
        stages = list(ProcessingStage)
        current_idx = stages.index(self)
        if current_idx < len(stages) - 1:
            return stages[current_idx + 1]
        return None
    
    def can_transition_to(self, target: 'ProcessingStage') -> bool:
        """Check if transition to target stage is valid"""
        # Define allowed transitions
        allowed_transitions = {
            ProcessingStage.PENDING: [ProcessingStage.OCR_PROCESSING],
            ProcessingStage.OCR_PROCESSING: [ProcessingStage.OCR_COMPLETE, ProcessingStage.PENDING],
            ProcessingStage.OCR_COMPLETE: [ProcessingStage.TEXT_PROCESSING],
            # ... etc
        }
        return target in allowed_transitions.get(self, [])

class ProcessingStateManager:
    """Manages document processing state with Redis and database"""
    
    def __init__(self, db_manager, redis_manager):
        self.db = db_manager
        self.redis = redis_manager
        
    def get_processing_checkpoint(self, document_uuid: str) -> Dict[str, Any]:
        """Get the current processing checkpoint for a document"""
        # Check Redis first for active processing
        state_key = f"doc_state:{document_uuid}"
        redis_state = self.redis.hgetall(state_key)
        
        # Get database state
        doc = self.db.client.table('source_documents').select(
            'celery_status', 'last_successful_stage', 'processing_version'
        ).eq('document_uuid', document_uuid).single().execute()
        
        return {
            'current_stage': doc.data.get('celery_status'),
            'last_successful': doc.data.get('last_successful_stage'),
            'version': doc.data.get('processing_version', 1),
            'redis_state': redis_state
        }
    
    def should_skip_stage(self, document_uuid: str, stage: ProcessingStage, 
                         force_reprocess: bool = False) -> bool:
        """Determine if a stage should be skipped"""
        if force_reprocess:
            return False
            
        checkpoint = self.get_processing_checkpoint(document_uuid)
        last_successful = checkpoint.get('last_successful')
        
        if not last_successful:
            return False
            
        # Skip if this stage was already completed successfully
        try:
            last_stage = ProcessingStage(last_successful)
            current_stage_idx = list(ProcessingStage).index(stage)
            last_stage_idx = list(ProcessingStage).index(last_stage)
            return current_stage_idx <= last_stage_idx
        except ValueError:
            return False
```

### 3. Idempotent Database Operations

```python
# scripts/celery_tasks/idempotent_ops.py
from typing import Tuple, Optional
import logging

logger = logging.getLogger(__name__)

class IdempotentDatabaseOps:
    """Database operations that handle duplicates gracefully"""
    
    def __init__(self, db_manager):
        self.db = db_manager
        
    def upsert_neo4j_document(self, source_doc_uuid: str, 
                             source_doc_id: int,
                             project_id: int,
                             project_uuid: str,
                             file_name: str) -> Tuple[int, str]:
        """Create or update neo4j_document entry"""
        try:
            # Check if document already exists
            existing = self.db.client.table('neo4j_documents').select(
                'id', 'documentId'
            ).eq('documentId', source_doc_uuid).maybe_single().execute()
            
            if existing.data:
                # Update existing document
                doc_id = existing.data['id']
                doc_uuid = existing.data['documentId']
                
                self.db.client.table('neo4j_documents').update({
                    'updatedAt': datetime.now().isoformat(),
                    'processingStatus': 'reprocessing'
                }).eq('id', doc_id).execute()
                
                logger.info(f"Updated existing neo4j_document {doc_id}")
                return doc_id, doc_uuid
            else:
                # Create new document
                return self.db.create_neo4j_document_entry(
                    source_doc_fk_id=source_doc_id,
                    source_doc_uuid=source_doc_uuid,
                    project_fk_id=project_id,
                    project_uuid=project_uuid,
                    file_name=file_name
                )
        except Exception as e:
            logger.error(f"Error in upsert_neo4j_document: {e}")
            raise
    
    def upsert_chunk(self, document_id: int, document_uuid: str,
                    chunk_index: int, chunk_text: str, 
                    chunk_metadata: dict) -> Tuple[int, str]:
        """Create or update chunk entry"""
        try:
            # Check for existing chunk
            existing = self.db.client.table('neo4j_chunks').select(
                'id', 'chunkId'
            ).eq('document_id', document_id).eq('chunkIndex', chunk_index).maybe_single().execute()
            
            if existing.data:
                # Update existing chunk
                chunk_id = existing.data['id']
                chunk_uuid = existing.data['chunkId']
                
                self.db.client.table('neo4j_chunks').update({
                    'text': chunk_text,
                    'metadata_json': json.dumps(chunk_metadata),
                    'updatedAt': datetime.now().isoformat()
                }).eq('id', chunk_id).execute()
                
                logger.info(f"Updated existing chunk {chunk_id} (index {chunk_index})")
                return chunk_id, chunk_uuid
            else:
                # Create new chunk
                return self.db.create_chunk_entry(
                    neo4j_doc_sql_id=document_id,
                    document_uuid=document_uuid,
                    chunk_text=chunk_text,
                    chunk_index=chunk_index,
                    metadata_json=chunk_metadata
                )
        except Exception as e:
            logger.error(f"Error in upsert_chunk: {e}")
            raise
```

### 4. Cleanup Task Implementation

```python
# scripts/celery_tasks/cleanup_tasks.py
from celery import Task
from scripts.celery_app import app
import logging

logger = logging.getLogger(__name__)

@app.task(bind=True, base=Task, name='cleanup_document_for_reprocessing')
def cleanup_document_for_reprocessing(self, document_uuid: str, 
                                     stages_to_clean: list = None,
                                     preserve_ocr: bool = True) -> dict:
    """
    Remove derived data for a document to allow reprocessing
    
    Args:
        document_uuid: Document identifier
        stages_to_clean: List of stages to clean (None = all)
        preserve_ocr: Keep OCR results to avoid re-calling Textract
    
    Returns:
        Dictionary with cleanup statistics
    """
    from scripts.supabase_utils import SupabaseManager
    
    db = SupabaseManager()
    stats = {
        'document_uuid': document_uuid,
        'cleaned_stages': [],
        'preserved_stages': [],
        'deleted_records': {}
    }
    
    try:
        # Get document info
        source_doc = db.client.table('source_documents').select(
            'id', 'processing_version'
        ).eq('document_uuid', document_uuid).single().execute()
        
        if not source_doc.data:
            raise ValueError(f"Document {document_uuid} not found")
        
        source_doc_id = source_doc.data['id']
        current_version = source_doc.data.get('processing_version', 1)
        
        # Determine what to clean
        all_stages = ['entities', 'chunks', 'neo4j_doc', 'ocr']
        stages = stages_to_clean or all_stages
        
        # Get neo4j_document if it exists
        neo4j_doc = db.client.table('neo4j_documents').select(
            'id'
        ).eq('documentId', document_uuid).maybe_single().execute()
        
        if neo4j_doc.data:
            neo4j_doc_id = neo4j_doc.data['id']
            
            # 1. Clean entity mentions (deepest dependency)
            if 'entities' in stages:
                # Get all chunks for this document
                chunks = db.client.table('neo4j_chunks').select(
                    'id'
                ).eq('document_id', neo4j_doc_id).execute()
                
                chunk_ids = [c['id'] for c in chunks.data]
                
                if chunk_ids:
                    # Delete all entity mentions for these chunks
                    result = db.client.table('neo4j_entity_mentions').delete().in_(
                        'chunk_fk_id', chunk_ids
                    ).execute()
                    
                    stats['deleted_records']['entity_mentions'] = len(chunk_ids)
                    stats['cleaned_stages'].append('entities')
                    logger.info(f"Deleted entity mentions for {len(chunk_ids)} chunks")
            
            # 2. Clean chunks
            if 'chunks' in stages:
                result = db.client.table('neo4j_chunks').delete().eq(
                    'document_id', neo4j_doc_id
                ).execute()
                
                stats['deleted_records']['chunks'] = len(result.data)
                stats['cleaned_stages'].append('chunks')
                logger.info(f"Deleted {len(result.data)} chunks")
            
            # 3. Clean neo4j_document
            if 'neo4j_doc' in stages:
                result = db.client.table('neo4j_documents').delete().eq(
                    'id', neo4j_doc_id
                ).execute()
                
                stats['deleted_records']['neo4j_document'] = 1
                stats['cleaned_stages'].append('neo4j_doc')
                logger.info(f"Deleted neo4j_document")
        
        # 4. Handle OCR data
        if 'ocr' in stages and not preserve_ocr:
            # Clear OCR-related fields
            db.client.table('source_documents').update({
                'raw_extracted_text': None,
                'ocr_metadata_json': None,
                'textract_job_id': None,
                'textract_job_status': 'not_started',
                'ocr_completed_at': None
            }).eq('id', source_doc_id).execute()
            
            stats['cleaned_stages'].append('ocr')
            logger.info("Cleared OCR data")
        elif preserve_ocr:
            stats['preserved_stages'].append('ocr')
        
        # 5. Update document status and increment version
        update_data = {
            'processing_version': current_version + 1,
            'last_successful_stage': 'ocr_complete' if preserve_ocr else None,
            'celery_status': 'pending',
            'celery_task_id': None,
            'error_message': None,
            'processing_attempts': 0
        }
        
        db.client.table('source_documents').update(
            update_data
        ).eq('id', source_doc_id).execute()
        
        # 6. Clear Redis state
        from scripts.redis_utils import get_redis_manager
        redis_mgr = get_redis_manager()
        if redis_mgr:
            state_key = f"doc_state:{document_uuid}"
            redis_mgr.get_client().delete(state_key)
            logger.info("Cleared Redis state")
        
        # 7. Log processing history
        db.client.table('document_processing_history').insert({
            'document_uuid': document_uuid,
            'processing_version': current_version + 1,
            'stage': 'cleanup',
            'status': 'completed',
            'started_at': datetime.now().isoformat(),
            'completed_at': datetime.now().isoformat(),
            'error_details': {'stats': stats}
        }).execute()
        
        logger.info(f"Cleanup completed for document {document_uuid}")
        return stats
        
    except Exception as e:
        logger.error(f"Error in cleanup_document_for_reprocessing: {e}")
        
        # Log failure in history
        db.client.table('document_processing_history').insert({
            'document_uuid': document_uuid,
            'processing_version': current_version + 1,
            'stage': 'cleanup',
            'status': 'failed',
            'started_at': datetime.now().isoformat(),
            'error_message': str(e)
        }).execute()
        
        raise
```

### 5. Enhanced Celery Task Base Class

```python
# scripts/celery_tasks/base_task.py
from celery import Task
from typing import Optional
import logging

logger = logging.getLogger(__name__)

class ReprocessingAwareTask(Task):
    """Base task class with reprocessing support"""
    
    def __init__(self):
        super().__init__()
        self.state_manager = None
        self.idempotent_ops = None
    
    def before_start(self, task_id, args, kwargs):
        """Initialize task resources"""
        from scripts.supabase_utils import SupabaseManager
        from scripts.redis_utils import get_redis_manager
        
        db = SupabaseManager()
        redis = get_redis_manager()
        
        self.state_manager = ProcessingStateManager(db, redis)
        self.idempotent_ops = IdempotentDatabaseOps(db)
        
        # Log task start
        document_uuid = kwargs.get('document_uuid') or args[1] if len(args) > 1 else None
        if document_uuid:
            db.client.table('document_processing_history').insert({
                'document_uuid': document_uuid,
                'processing_version': self.get_processing_version(document_uuid),
                'stage': self.name,
                'status': 'started',
                'started_at': datetime.now().isoformat(),
                'celery_task_id': task_id
            }).execute()
    
    def on_success(self, retval, task_id, args, kwargs):
        """Record successful completion"""
        document_uuid = kwargs.get('document_uuid') or args[1] if len(args) > 1 else None
        if document_uuid:
            # Update last successful stage
            db = SupabaseManager()
            db.client.table('source_documents').update({
                'last_successful_stage': self.get_stage_name()
            }).eq('document_uuid', document_uuid).execute()
    
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Record failure with detailed context"""
        document_uuid = kwargs.get('document_uuid') or args[1] if len(args) > 1 else None
        if document_uuid:
            db = SupabaseManager()
            db.client.table('document_processing_history').insert({
                'document_uuid': document_uuid,
                'processing_version': self.get_processing_version(document_uuid),
                'stage': self.name,
                'status': 'failed',
                'completed_at': datetime.now().isoformat(),
                'error_message': str(exc),
                'error_details': {'traceback': str(einfo)}
            }).execute()
```

### 6. Modified Task Implementations

```python
# scripts/celery_tasks/text_tasks.py (modified)
@app.task(bind=True, base=ReprocessingAwareTask, name='create_document_node')
def create_document_node(self, source_doc_sql_id: int, source_doc_uuid: str,
                        file_name: str, project_sql_id: int,
                        force_reprocess: bool = False):
    """Create or update neo4j document node with idempotent logic"""
    
    try:
        # Check if we should skip this stage
        if not force_reprocess and self.state_manager.should_skip_stage(
            source_doc_uuid, ProcessingStage.TEXT_PROCESSING
        ):
            logger.info(f"Skipping text processing for {source_doc_uuid} - already completed")
            # Chain to next task
            process_chunking.delay(
                source_doc_sql_id=source_doc_sql_id,
                source_doc_uuid=source_doc_uuid,
                force_reprocess=force_reprocess
            )
            return {'status': 'skipped', 'reason': 'already_processed'}
        
        # Update status
        update_document_state(
            source_doc_uuid, 'text_processing', 
            'text', 'processing'
        )
        
        # Get project UUID
        project_uuid = self.db_manager.get_project_uuid_by_sql_id(project_sql_id)
        
        # Use idempotent operation
        neo4j_doc_sql_id, neo4j_doc_uuid = self.idempotent_ops.upsert_neo4j_document(
            source_doc_uuid=source_doc_uuid,
            source_doc_id=source_doc_sql_id,
            project_id=project_sql_id,
            project_uuid=project_uuid,
            file_name=file_name
        )
        
        # Continue with processing...
```

## Implementation Phases

### Phase 1: Core Infrastructure (1-2 days)
1. Implement database schema changes
2. Create ProcessingStateManager class
3. Add cleanup_document_for_reprocessing task
4. Update error handling in existing tasks

### Phase 2: Idempotent Operations (2-3 days)
1. Implement IdempotentDatabaseOps class
2. Modify all database operations to use upsert logic
3. Add transaction support where needed
4. Test with duplicate data scenarios

### Phase 3: State Management (1-2 days)
1. Implement stage skipping logic
2. Add processing version tracking
3. Create resumable processing flow
4. Add force_reprocess parameter throughout

### Phase 4: Monitoring & Testing (2-3 days)
1. Implement processing history tracking
2. Create monitoring dashboards
3. Build comprehensive test suite
4. Document reprocessing procedures

## Usage Examples

### 1. Retry Failed Document
```python
# Document failed at entity extraction
cleanup_document_for_reprocessing.delay(
    document_uuid="abc-123",
    stages_to_clean=["entities"],  # Only clean failed stage
    preserve_ocr=True  # Don't re-run expensive OCR
)
```

### 2. Force Complete Reprocess
```python
# Changed extraction logic, need fresh processing
cleanup_document_for_reprocessing.delay(
    document_uuid="abc-123",
    stages_to_clean=None,  # Clean everything
    preserve_ocr=False  # Re-run OCR too
).then(
    submit_document_to_celery(
        document_id=123,
        document_uuid="abc-123",
        force_reprocess=True
    )
)
```

### 3. Bulk Reprocessing
```python
# Reprocess all documents with updated models
from scripts.bulk_operations import bulk_reprocess_documents

bulk_reprocess_documents(
    filter_criteria={"processing_version": {"<": 2}},
    preserve_ocr=True,
    batch_size=10,
    delay_between_batches=5  # seconds
)
```

## Benefits of This Approach

1. **Reliability**: Handles all failure scenarios gracefully
2. **Efficiency**: Avoids redundant processing of completed stages  
3. **Flexibility**: Supports various reprocessing scenarios
4. **Auditability**: Complete history of all processing attempts
5. **Scalability**: Works with high-volume production workloads
6. **Maintainability**: Clear separation of concerns and well-documented

## Conclusion

This comprehensive reprocessing strategy transforms the pipeline from a one-shot process to a robust, production-ready system that can handle the complexities of real-world document processing. By implementing these changes, the system will support iterative development, testing, and continuous improvement of processing logic without data loss or manual intervention.