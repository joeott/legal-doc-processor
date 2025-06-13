"""
Batch processing tasks with priority support for the legal document pipeline.

This module provides batch processing capabilities with three priority levels:
- High Priority (9): Urgent/time-sensitive batches
- Normal Priority (5): Standard batch processing
- Low Priority (1): Background/non-urgent batches
"""

import logging
from typing import Dict, Any, List
from datetime import datetime
from celery import group, chord, chain
from uuid import uuid4

from scripts.celery_app import app
from scripts.pdf_tasks import PDFTask, process_pdf_document
from scripts.cache import get_redis_manager, CacheKeys
from scripts.config import REDIS_PREFIX_BATCH
from scripts.cache_warmer import warm_cache_before_batch

logger = logging.getLogger(__name__)


class BatchTask(PDFTask):
    """Base class for batch processing tasks."""
    
    def update_batch_progress(self, batch_id: str, update: Dict[str, Any]):
        """Update batch progress in Redis."""
        redis_manager = get_redis_manager()
        progress_key = f"{REDIS_PREFIX_BATCH}progress:{batch_id}"
        
        # Update progress data
        progress_data = redis_manager.get_dict(progress_key) or {}
        progress_data.update(update)
        progress_data['last_updated'] = datetime.utcnow().isoformat()
        
        redis_manager.store_dict(progress_key, progress_data, ttl=86400)  # 24 hours
        
    def track_document_in_batch(self, batch_id: str, document_uuid: str, status: str):
        """Track individual document status within a batch."""
        redis_manager = get_redis_manager()
        doc_key = f"{REDIS_PREFIX_BATCH}document:{batch_id}:{document_uuid}"
        
        doc_data = {
            'status': status,
            'updated_at': datetime.utcnow().isoformat()
        }
        
        redis_manager.store_dict(doc_key, doc_data, ttl=86400)


@app.task(bind=True, base=BatchTask, queue='batch.high', priority=9)
def process_batch_high(self, batch_manifest: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process a high-priority batch of documents.
    
    Args:
        batch_manifest: Dictionary containing:
            - batch_id: Unique batch identifier
            - documents: List of document metadata dicts
            - project_uuid: Project UUID for the batch
            - options: Processing options
            
    Returns:
        Dictionary with batch processing results
    """
    batch_id = batch_manifest.get('batch_id', str(uuid4()))
    documents = batch_manifest.get('documents', [])
    project_uuid = batch_manifest.get('project_uuid')
    options = batch_manifest.get('options', {})
    
    logger.info(f"Starting HIGH PRIORITY batch {batch_id} with {len(documents)} documents")
    
    # Initialize batch progress
    self.update_batch_progress(batch_id, {
        'status': 'initializing',
        'priority': 'high',
        'total': len(documents),
        'completed': 0,
        'failed': 0,
        'started_at': datetime.utcnow().isoformat()
    })
    
    # Warm cache if enabled
    if options.get('warm_cache', True) and len(documents) > 5:  # Only warm for batches > 5 docs
        logger.info(f"Warming cache for batch {batch_id}")
        warm_result = warm_cache_before_batch(batch_manifest, wait=True)
        if warm_result and warm_result.get('status') == 'completed':
            logger.info(f"Cache warmed successfully for batch {batch_id}")
        
    # Update status to processing
    self.update_batch_progress(batch_id, {'status': 'processing'})
    
    # Create parallel processing tasks with high priority
    parallel_tasks = []
    failed_docs = []
    
    for doc in documents:
        # Ensure document has required fields
        if not doc.get('document_uuid') or not doc.get('file_path'):
            logger.error(f"Invalid document in batch: {doc}")
            failed_docs.append({
                'document_uuid': doc.get('document_uuid', 'unknown'),
                'error': 'Missing required fields',
                'stage': 'validation'
            })
            continue
        
        doc_uuid = doc['document_uuid']
        
        # Check and potentially reset circuit breaker
        try:
            from scripts.pdf_tasks import circuit_breaker
            cb_state = circuit_breaker.get_state(doc_uuid)
            
            if cb_state['state'] == 'OPEN':
                logger.warning(f"Circuit breaker OPEN for {doc_uuid} - attempting reset")
                circuit_breaker.reset(doc_uuid)
                logger.info(f"Circuit breaker reset for {doc_uuid}")
        except Exception as e:
            logger.warning(f"Could not check circuit breaker for {doc_uuid}: {e}")
        
        try:
            # Create task signature with high priority
            task_sig = process_pdf_document.signature(
                args=[doc_uuid, doc['file_path'], project_uuid],
                kwargs={
                    'document_metadata': doc.get('metadata', {}),
                    **options
                },
                priority=9,  # High priority
                immutable=True
            )
            parallel_tasks.append(task_sig)
            
            # Track document submission
            self.track_document_in_batch(batch_id, doc_uuid, 'submitted')
            
        except Exception as e:
            logger.error(f"Failed to create task for document {doc_uuid}: {str(e)}")
            failed_docs.append({
                'document_uuid': doc_uuid,
                'error': str(e),
                'stage': 'submission'
            })
            
            # Update batch progress with failure
            self.track_document_in_batch(batch_id, doc_uuid, 'failed')
            continue
    
    # Update batch progress with submission stats
    if failed_docs:
        self.update_batch_progress(batch_id, {
            'failed': len(failed_docs),
            'failed_documents': failed_docs
        })
    
    # Use chord to process in parallel and aggregate results
    if parallel_tasks:
        job = chord(parallel_tasks)(
            aggregate_batch_results.s(batch_id, 'high')
        )
        
        return {
            'batch_id': batch_id,
            'status': 'submitted',
            'priority': 'high',
            'document_count': len(parallel_tasks),
            'failed_count': len(failed_docs),
            'chord_id': job.id
        }
    else:
        self.update_batch_progress(batch_id, {
            'status': 'completed',
            'completed_at': datetime.utcnow().isoformat()
        })
        return {
            'batch_id': batch_id,
            'status': 'completed',
            'priority': 'high',
            'document_count': 0
        }


@app.task(bind=True, base=BatchTask, queue='batch.normal', priority=5)
def process_batch_normal(self, batch_manifest: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process a normal-priority batch of documents.
    
    Args:
        batch_manifest: Same structure as process_batch_high
        
    Returns:
        Dictionary with batch processing results
    """
    batch_id = batch_manifest.get('batch_id', str(uuid4()))
    documents = batch_manifest.get('documents', [])
    project_uuid = batch_manifest.get('project_uuid')
    options = batch_manifest.get('options', {})
    
    logger.info(f"Starting NORMAL PRIORITY batch {batch_id} with {len(documents)} documents")
    
    # Initialize batch progress
    self.update_batch_progress(batch_id, {
        'status': 'initializing',
        'priority': 'normal',
        'total': len(documents),
        'completed': 0,
        'failed': 0,
        'started_at': datetime.utcnow().isoformat()
    })
    
    # Warm cache if enabled
    if options.get('warm_cache', True) and len(documents) > 5:  # Only warm for batches > 5 docs
        logger.info(f"Warming cache for batch {batch_id}")
        warm_result = warm_cache_before_batch(batch_manifest, wait=True)
        if warm_result and warm_result.get('status') == 'completed':
            logger.info(f"Cache warmed successfully for batch {batch_id}")
        
    # Update status to processing
    self.update_batch_progress(batch_id, {'status': 'processing'})
    
    # Create parallel processing tasks with normal priority
    parallel_tasks = []
    for doc in documents:
        if not doc.get('document_uuid') or not doc.get('file_path'):
            logger.error(f"Invalid document in batch: {doc}")
            continue
            
        task_sig = process_pdf_document.signature(
            args=[doc['document_uuid'], doc['file_path']],
            kwargs={'project_uuid': project_uuid, **options},
            priority=5,  # Normal priority
            immutable=True
        )
        parallel_tasks.append(task_sig)
    
    # Process with normal priority
    if parallel_tasks:
        job = chord(parallel_tasks)(
            aggregate_batch_results.s(batch_id, 'normal')
        )
        
        return {
            'batch_id': batch_id,
            'status': 'submitted',
            'priority': 'normal',
            'document_count': len(parallel_tasks),
            'chord_id': job.id
        }
    else:
        self.update_batch_progress(batch_id, {
            'status': 'completed',
            'completed_at': datetime.utcnow().isoformat()
        })
        return {
            'batch_id': batch_id,
            'status': 'completed',
            'priority': 'normal',
            'document_count': 0
        }


@app.task(bind=True, base=BatchTask, queue='batch.low', priority=1)
def process_batch_low(self, batch_manifest: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process a low-priority batch of documents.
    
    Args:
        batch_manifest: Same structure as process_batch_high
        
    Returns:
        Dictionary with batch processing results
    """
    batch_id = batch_manifest.get('batch_id', str(uuid4()))
    documents = batch_manifest.get('documents', [])
    project_uuid = batch_manifest.get('project_uuid')
    options = batch_manifest.get('options', {})
    
    logger.info(f"Starting LOW PRIORITY batch {batch_id} with {len(documents)} documents")
    
    # Initialize batch progress
    self.update_batch_progress(batch_id, {
        'status': 'initializing',
        'priority': 'low',
        'total': len(documents),
        'completed': 0,
        'failed': 0,
        'started_at': datetime.utcnow().isoformat()
    })
    
    # Warm cache if enabled (less aggressive for low priority)
    if options.get('warm_cache', True) and len(documents) > 10:  # Only warm for larger low priority batches
        logger.info(f"Warming cache for batch {batch_id}")
        warm_result = warm_cache_before_batch(batch_manifest, wait=False)  # Don't wait for low priority
        
    # Update status to processing
    self.update_batch_progress(batch_id, {'status': 'processing'})
    
    # Create parallel processing tasks with low priority
    parallel_tasks = []
    for doc in documents:
        if not doc.get('document_uuid') or not doc.get('file_path'):
            logger.error(f"Invalid document in batch: {doc}")
            continue
            
        task_sig = process_pdf_document.signature(
            args=[doc['document_uuid'], doc['file_path']],
            kwargs={'project_uuid': project_uuid, **options},
            priority=1,  # Low priority
            immutable=True
        )
        parallel_tasks.append(task_sig)
    
    # Process with low priority
    if parallel_tasks:
        job = chord(parallel_tasks)(
            aggregate_batch_results.s(batch_id, 'low')
        )
        
        return {
            'batch_id': batch_id,
            'status': 'submitted',
            'priority': 'low',
            'document_count': len(parallel_tasks),
            'chord_id': job.id
        }
    else:
        self.update_batch_progress(batch_id, {
            'status': 'completed',
            'completed_at': datetime.utcnow().isoformat()
        })
        return {
            'batch_id': batch_id,
            'status': 'completed',
            'priority': 'low',
            'document_count': 0
        }


@app.task(bind=True, base=BatchTask)
def aggregate_batch_results(self, results: List[Dict], batch_id: str, priority: str) -> Dict[str, Any]:
    """
    Aggregate results from parallel document processing.
    
    Args:
        results: List of results from individual document processing
        batch_id: Batch identifier
        priority: Batch priority level
        
    Returns:
        Aggregated batch results
    """
    completed = 0
    failed = 0
    errors = []
    
    for result in results:
        if isinstance(result, dict):
            if result.get('status') == 'completed':
                completed += 1
            else:
                failed += 1
                if result.get('error'):
                    errors.append({
                        'document_uuid': result.get('document_uuid'),
                        'error': result.get('error')
                    })
        else:
            failed += 1
    
    # Update final batch progress
    self.update_batch_progress(batch_id, {
        'status': 'completed',
        'completed': completed,
        'failed': failed,
        'completed_at': datetime.utcnow().isoformat(),
        'errors': errors[:10]  # Store first 10 errors
    })
    
    # Calculate success rate
    total = completed + failed
    success_rate = (completed / total * 100) if total > 0 else 0
    
    logger.info(f"Batch {batch_id} completed: {completed}/{total} successful ({success_rate:.1f}%)")
    
    return {
        'batch_id': batch_id,
        'priority': priority,
        'total': total,
        'completed': completed,
        'failed': failed,
        'success_rate': success_rate,
        'errors': errors[:10]  # Return first 10 errors
    }


@app.task(bind=True, base=BatchTask)
def get_batch_status(self, batch_id: str) -> Dict[str, Any]:
    """
    Get current status of a batch.
    
    Args:
        batch_id: Batch identifier
        
    Returns:
        Current batch status and progress
    """
    redis_manager = get_redis_manager()
    progress_key = f"{REDIS_PREFIX_BATCH}progress:{batch_id}"
    
    progress_data = redis_manager.get_dict(progress_key)
    
    if not progress_data:
        return {
            'batch_id': batch_id,
            'status': 'not_found',
            'error': 'Batch not found'
        }
    
    # Calculate additional metrics
    total = progress_data.get('total', 0)
    completed = progress_data.get('completed', 0)
    failed = progress_data.get('failed', 0)
    
    if total > 0:
        progress_data['progress_percentage'] = ((completed + failed) / total) * 100
        progress_data['success_rate'] = (completed / total) * 100 if total > 0 else 0
    
    # Estimate time remaining
    if progress_data.get('status') == 'processing' and completed > 0:
        started_at = datetime.fromisoformat(progress_data.get('started_at', datetime.utcnow().isoformat()))
        elapsed = (datetime.utcnow() - started_at).total_seconds()
        rate = completed / elapsed if elapsed > 0 else 0
        remaining = total - completed - failed
        
        if rate > 0:
            eta_seconds = remaining / rate
            progress_data['estimated_time_remaining'] = f"{int(eta_seconds / 60)} minutes"
    
    return progress_data


# Helper function for submitting batches with automatic priority routing
def submit_batch(documents: List[Dict], project_uuid: str, priority: str = 'normal', 
                 options: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Submit a batch of documents for processing with specified priority.
    
    Args:
        documents: List of document dictionaries with 'document_uuid' and 'file_path'
        project_uuid: Project UUID for the batch
        priority: Priority level ('high', 'normal', 'low')
        options: Additional processing options
        
    Returns:
        Batch submission result
    """
    batch_manifest = {
        'batch_id': str(uuid4()),
        'documents': documents,
        'project_uuid': project_uuid,
        'options': options or {}
    }
    
    # Route to appropriate priority task
    if priority == 'high':
        task = process_batch_high
    elif priority == 'low':
        task = process_batch_low
    else:
        task = process_batch_normal
    
    # Submit batch
    result = task.apply_async(args=[batch_manifest])
    
    return {
        'batch_id': batch_manifest['batch_id'],
        'task_id': result.id,
        'priority': priority,
        'document_count': len(documents)
    }


def create_document_records(documents: List[Dict[str, Any]], project_uuid: str, 
                          project_id: int = 1) -> List[Dict[str, Any]]:
    """
    Create database records for documents before batch processing.
    
    Args:
        documents: List of document dicts with at least:
                  - filename: Original filename
                  - s3_bucket: S3 bucket name
                  - s3_key: S3 object key
                  - file_size_mb: File size in MB
                  - mime_type: MIME type
        project_uuid: Project UUID to associate documents with
        project_id: Project ID (default: 1)
        
    Returns:
        List of documents updated with document_uuid
    """
    from scripts.db import DatabaseManager
    from sqlalchemy import text
    
    db_manager = DatabaseManager(validate_conformance=False)
    processed_docs = []
    
    for doc in documents:
        try:
            document_uuid = str(uuid4())
            
            # Create record in database
            for session in db_manager.get_session():
                # Convert file size from MB to bytes
                file_size_bytes = int(doc.get('file_size_mb', 0) * 1024 * 1024)
                
                session.execute(text("""
                    INSERT INTO source_documents (
                        document_uuid, original_file_name, file_name, s3_bucket, s3_key,
                        file_size_bytes, file_type, detected_file_type, status,
                        created_at, updated_at, project_fk_id, project_uuid
                    ) VALUES (
                        :uuid, :filename, :filename, :bucket, :key,
                        :size_bytes, :file_type, :file_type, 'pending',
                        NOW(), NOW(), :project_id, :project_uuid
                    )
                """), {
                    'uuid': document_uuid,
                    'filename': doc.get('filename', doc.get('original_filename', '')),
                    'bucket': doc.get('s3_bucket', ''),
                    'key': doc.get('s3_key', ''),
                    'size_bytes': file_size_bytes,
                    'file_type': doc.get('mime_type', 'application/pdf'),
                    'project_id': project_id,
                    'project_uuid': project_uuid
                })
                session.commit()
            
            # Update document with UUID
            doc['document_uuid'] = document_uuid
            doc['file_path'] = f"s3://{doc.get('s3_bucket', '')}/{doc.get('s3_key', '')}"
            processed_docs.append(doc)
            
            logger.info(f"Created database record for document {document_uuid}: {doc.get('filename')}")
            
        except Exception as e:
            logger.error(f"Failed to create database record for {doc.get('filename')}: {e}")
            # Skip documents that fail
            continue
    
    return processed_docs