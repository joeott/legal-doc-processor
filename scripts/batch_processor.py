"""
Batch Processing Framework - Orchestrates document processing in organized batches.

This service handles:
- Batch manifest creation and management
- Batch job submission to Celery queues
- Batch progress monitoring and status tracking
- Batch failure handling and recovery
- Performance optimization and resource management
"""

import json
import uuid
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
import logging

from celery import chain, group
from scripts.cache import get_redis_manager
# Import pdf_tasks functions when needed to avoid import errors
from scripts.logging_config import get_logger
from scripts.db import DatabaseManager
from sqlalchemy import text

logger = get_logger(__name__)


class BatchStatus(Enum):
    """Batch processing status."""
    PENDING = "pending"
    SUBMITTED = "submitted"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PARTIAL_SUCCESS = "partial_success"


class BatchPriority(Enum):
    """Batch processing priority."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


@dataclass
class BatchManifest:
    """Manifest for a processing batch."""
    batch_id: str
    batch_type: str  # small, medium, large
    document_count: int
    total_size_mb: float
    documents: List[Dict[str, Any]]
    priority: str
    estimated_processing_time_minutes: int
    created_at: str
    submitted_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    status: str = BatchStatus.PENDING.value
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


@dataclass
class BatchProgress:
    """Current progress of a batch."""
    batch_id: str
    total_documents: int
    completed_documents: int
    failed_documents: int
    in_progress_documents: int
    pending_documents: int
    current_stage_counts: Dict[str, int]  # stage -> count
    started_at: Optional[str]
    estimated_completion: Optional[str]
    elapsed_minutes: float
    completion_percentage: float
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


@dataclass
class BatchJobId:
    """Identifier for a submitted batch job."""
    batch_id: str
    job_group_id: str
    celery_task_ids: List[str]
    submitted_at: str
    priority: str


@dataclass
class RecoveryPlan:
    """Plan for recovering from batch failures."""
    batch_id: str
    failed_documents: List[str]
    retry_strategy: str  # immediate, delayed, manual
    retry_count: int
    max_retries: int
    recovery_actions: List[str]
    estimated_recovery_time_minutes: int


def create_document_record(session, original_filename: str, s3_bucket: str, s3_key: str, 
                          file_size_mb: float, mime_type: str, project_id: int = 1,
                          project_uuid: str = None) -> str:
    """
    Create a source_documents record and return the UUID.
    
    Args:
        session: Database session
        original_filename: Original filename
        s3_bucket: S3 bucket name
        s3_key: S3 object key
        file_size_mb: File size in MB
        mime_type: MIME type of the document
        project_id: Project ID to associate document with
        project_uuid: Project UUID to associate document with
        
    Returns:
        Document UUID
    """
    # Generate UUID
    document_uuid = str(uuid.uuid4())
    
    try:
        # Create record using direct SQL to avoid model conformance issues
        # Convert file size from MB to bytes
        file_size_bytes = int(file_size_mb * 1024 * 1024)
        
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
            'filename': original_filename,
            'bucket': s3_bucket,
            'key': s3_key,
            'size_bytes': file_size_bytes,
            'file_type': mime_type,
            'project_id': project_id,
            'project_uuid': project_uuid
        })
        session.commit()
        
        logger.info(f"Created database record for document {document_uuid}: {original_filename} (project: {project_uuid})")
        return document_uuid
        
    except Exception as e:
        logger.error(f"Failed to create database record for {original_filename}: {e}")
        session.rollback()
        raise


class BatchProcessor:
    """Service for processing document batches."""
    
    def __init__(self):
        self.redis = get_redis_manager()
        self.db_manager = DatabaseManager(validate_conformance=False)
    
    def _get_project_uuid(self, project_id: int) -> str:
        """Get project UUID for given project ID."""
        for session in self.db_manager.get_session():
            project_uuid = session.execute(text(
                "SELECT project_id FROM projects WHERE id = :id"
            ), {'id': project_id}).scalar()
            
            if project_uuid:
                return str(project_uuid)
            else:
                # This should not happen as project_id has a default value
                logger.error(f"No project found with id {project_id}")
                raise ValueError(f"Project {project_id} not found")
        
    def create_batch_manifest(self, documents: List[Dict[str, Any]], 
                            batch_config: Dict[str, Any]) -> BatchManifest:
        """
        Create a batch manifest from documents and configuration.
        
        Args:
            documents: List of document dictionaries from intake service
            batch_config: Configuration for batch creation
            
        Returns:
            BatchManifest object
        """
        batch_id = f"batch_{uuid.uuid4().hex[:8]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Calculate batch metrics
        total_size_mb = sum(doc.get('file_size_mb', 0) for doc in documents)
        
        # Determine batch type based on size and count
        if len(documents) <= 5 or total_size_mb < 10:
            batch_type = "small"
        elif len(documents) <= 25 or total_size_mb < 100:
            batch_type = "medium" 
        else:
            batch_type = "large"
        
        # Determine priority
        priorities = [doc.get('priority', 'normal') for doc in documents]
        if any(p == 'urgent' for p in priorities):
            batch_priority = 'urgent'
        elif any(p == 'high' for p in priorities):
            batch_priority = 'high'
        elif all(p == 'low' for p in priorities):
            batch_priority = 'low'
        else:
            batch_priority = 'normal'
        
        # Estimate processing time
        estimated_time = self._estimate_batch_processing_time(documents)
        
        manifest = BatchManifest(
            batch_id=batch_id,
            batch_type=batch_type,
            document_count=len(documents),
            total_size_mb=round(total_size_mb, 2),
            documents=documents,
            priority=batch_priority,
            estimated_processing_time_minutes=estimated_time,
            created_at=datetime.now().isoformat()
        )
        
        # Cache the manifest
        self._cache_batch_manifest(manifest)
        
        logger.info(f"Created batch manifest {batch_id}: {len(documents)} documents, {total_size_mb:.1f}MB")
        return manifest
    
    def submit_batch_for_processing(self, batch: BatchManifest, project_id: int = 1, 
                                   project_uuid: str = None) -> BatchJobId:
        """
        Submit a batch for processing via Celery.
        
        Args:
            batch: BatchManifest to process
            project_id: Project ID to associate documents with
            project_uuid: Project UUID to associate documents with
            
        Returns:
            BatchJobId with Celery task information
        """
        logger.info(f"Submitting batch {batch.batch_id} for processing")
        
        # Update batch status
        batch.status = BatchStatus.SUBMITTED.value
        batch.submitted_at = datetime.now().isoformat()
        self._cache_batch_manifest(batch)
        
        # Create Celery task chains for each document
        task_chains = []
        celery_task_ids = []
        
        for doc in batch.documents:
            try:
                # CREATE DATABASE RECORD FIRST
                for session in self.db_manager.get_session():
                    document_uuid = create_document_record(
                        session,
                        original_filename=doc.get('filename'),
                        s3_bucket=doc.get('s3_bucket'),
                        s3_key=doc.get('s3_key'),
                        file_size_mb=doc.get('file_size_mb', 0.0),
                        mime_type=doc.get('mime_type', 'application/pdf'),
                        project_id=project_id,
                        project_uuid=project_uuid
                    )
                    
                # Store the database UUID back in the document dict
                doc['document_uuid'] = document_uuid
                
                # STORE METADATA IN REDIS
                if project_uuid:
                    metadata_key = f"doc:metadata:{document_uuid}"
                    metadata = {
                        'project_uuid': project_uuid,
                        'project_id': project_id,
                        'document_metadata': {
                            'filename': doc.get('filename'),
                            's3_bucket': doc.get('s3_bucket'),
                            's3_key': doc.get('s3_key'),
                            'uploaded_at': datetime.now().isoformat()
                        }
                    }
                    self.redis.set_cached(metadata_key, metadata, ttl=86400)  # 24 hours
                    logger.debug(f"Stored Redis metadata for document {document_uuid}")
                
                # Build S3 URL
                s3_url = doc.get('s3_url') or f"s3://{doc.get('s3_bucket', '')}/{doc.get('s3_key', '')}"
                
                # Create processing chain with EXISTING document UUID using immutable signatures
                from scripts.celery_app import app
                processing_chain = chain(
                    app.signature('scripts.pdf_tasks.extract_text_from_document', args=[document_uuid, s3_url], immutable=True),
                    app.signature('scripts.pdf_tasks.chunk_document_text', args=[document_uuid], immutable=True),
                    app.signature('scripts.pdf_tasks.extract_entities_from_chunks', args=[document_uuid], immutable=True),
                    app.signature('scripts.pdf_tasks.resolve_entities_for_document', args=[document_uuid], immutable=True),
                    app.signature('scripts.pdf_tasks.build_document_relationships', args=[document_uuid], immutable=True)
                )
                
                task_chains.append(processing_chain)
                
            except Exception as e:
                logger.error(f"Failed to create database record for document: {e}")
                # Continue with other documents even if one fails
                continue
        
        # Create job group for parallel execution
        job_group = group(task_chains)
        group_id = f"batch_group_{batch.batch_id}"
        
        # Apply the group with appropriate routing
        queue_name = self._get_queue_for_priority(batch.priority)
        result = job_group.apply_async(queue=queue_name)
        
        # Collect task IDs
        if hasattr(result, 'children') and result.children:
            for child in result.children:
                if hasattr(child, 'id'):
                    celery_task_ids.append(child.id)
        elif hasattr(result, 'id'):
            celery_task_ids.append(result.id)
        
        # Create batch job ID
        batch_job = BatchJobId(
            batch_id=batch.batch_id,
            job_group_id=group_id,
            celery_task_ids=celery_task_ids,
            submitted_at=datetime.now().isoformat(),
            priority=batch.priority
        )
        
        # Cache job information
        self._cache_batch_job(batch_job)
        
        # Initialize batch progress tracking
        self._initialize_batch_progress_tracking(batch)
        
        logger.info(f"Batch {batch.batch_id} submitted with {len(celery_task_ids)} tasks")
        return batch_job
    
    def monitor_batch_progress(self, batch_id: str) -> Optional[BatchProgress]:
        """
        Monitor the progress of a processing batch.
        
        Args:
            batch_id: ID of batch to monitor
            
        Returns:
            BatchProgress object or None if not found
        """
        try:
            # Get batch manifest
            manifest = self._get_cached_batch_manifest(batch_id)
            if not manifest:
                logger.warning(f"Batch manifest not found: {batch_id}")
                return None
            
            # Get current document statuses
            document_statuses = self._get_batch_document_statuses(batch_id)
            
            # Count statuses
            completed = sum(1 for status in document_statuses.values() if status.get('overall_status') == 'completed')
            failed = sum(1 for status in document_statuses.values() if status.get('overall_status') == 'failed')
            in_progress = sum(1 for status in document_statuses.values() if status.get('overall_status') == 'in_progress')
            pending = len(document_statuses) - completed - failed - in_progress
            
            # Count by stage
            stage_counts = {}
            for status in document_statuses.values():
                current_stage = status.get('current_stage', 'unknown')
                stage_counts[current_stage] = stage_counts.get(current_stage, 0) + 1
            
            # Calculate timing
            started_at = manifest.get('started_at')
            elapsed_minutes = 0.0
            estimated_completion = None
            
            if started_at:
                start_time = datetime.fromisoformat(started_at.replace('Z', '+00:00'))
                elapsed_minutes = (datetime.now() - start_time.replace(tzinfo=None)).total_seconds() / 60
                
                # Estimate completion time
                if in_progress + pending > 0 and completed > 0:
                    avg_time_per_doc = elapsed_minutes / completed
                    remaining_time = avg_time_per_doc * (in_progress + pending)
                    estimated_completion = (datetime.now() + timedelta(minutes=remaining_time)).isoformat()
            
            # Calculate completion percentage
            total_docs = manifest.get('document_count', 0)
            completion_percentage = (completed / total_docs * 100) if total_docs > 0 else 0
            
            progress = BatchProgress(
                batch_id=batch_id,
                total_documents=total_docs,
                completed_documents=completed,
                failed_documents=failed,
                in_progress_documents=in_progress,
                pending_documents=pending,
                current_stage_counts=stage_counts,
                started_at=started_at,
                estimated_completion=estimated_completion,
                elapsed_minutes=round(elapsed_minutes, 1),
                completion_percentage=round(completion_percentage, 1)
            )
            
            # Cache progress for performance
            self._cache_batch_progress(progress)
            
            return progress
            
        except Exception as e:
            logger.error(f"Error monitoring batch progress {batch_id}: {e}")
            return None
    
    def handle_batch_failures(self, batch_id: str) -> RecoveryPlan:
        """
        Handle failures in batch processing and create recovery plan.
        
        Args:
            batch_id: ID of batch with failures
            
        Returns:
            RecoveryPlan for batch recovery
        """
        logger.info(f"Handling failures for batch {batch_id}")
        
        # Get failed documents
        document_statuses = self._get_batch_document_statuses(batch_id)
        failed_docs = [
            doc_id for doc_id, status in document_statuses.items()
            if status.get('overall_status') == 'failed'
        ]
        
        # Get retry history
        retry_key = f"batch:retry_count:{batch_id}"
        retry_count = int(self.redis.get_cached(retry_key) or 0)
        max_retries = 3
        
        # Determine retry strategy
        if retry_count >= max_retries:
            retry_strategy = "manual"
        elif len(failed_docs) > len(document_statuses) * 0.5:  # More than 50% failed
            retry_strategy = "delayed"
        else:
            retry_strategy = "immediate"
        
        # Create recovery actions
        recovery_actions = []
        if retry_strategy == "immediate":
            recovery_actions = [
                "Retry failed documents immediately",
                "Monitor for repeated failures",
                "Check worker capacity"
            ]
        elif retry_strategy == "delayed":
            recovery_actions = [
                "Wait 10 minutes before retry",
                "Reduce batch size for retry",
                "Check system resources",
                "Review error patterns"
            ]
        else:  # manual
            recovery_actions = [
                "Manual intervention required",
                "Review error logs",
                "Check document validity",
                "Consider alternative processing approach"
            ]
        
        # Estimate recovery time
        estimated_time = len(failed_docs) * 5  # 5 minutes per document
        if retry_strategy == "delayed":
            estimated_time += 10  # Add delay time
        
        recovery_plan = RecoveryPlan(
            batch_id=batch_id,
            failed_documents=failed_docs,
            retry_strategy=retry_strategy,
            retry_count=retry_count,
            max_retries=max_retries,
            recovery_actions=recovery_actions,
            estimated_recovery_time_minutes=estimated_time
        )
        
        # Execute recovery if appropriate
        if retry_strategy in ["immediate", "delayed"]:
            self._execute_recovery_plan(recovery_plan)
        
        return recovery_plan
    
    def get_batch_summary(self, batch_id: str) -> Optional[Dict[str, Any]]:
        """Get comprehensive summary of batch processing."""
        try:
            manifest = self._get_cached_batch_manifest(batch_id)
            progress = self.monitor_batch_progress(batch_id)
            
            if not manifest or not progress:
                return None
            
            return {
                'batch_info': manifest,
                'current_progress': progress.to_dict(),
                'performance_metrics': self._calculate_batch_performance_metrics(batch_id),
                'quality_indicators': self._get_batch_quality_indicators(batch_id)
            }
            
        except Exception as e:
            logger.error(f"Error getting batch summary {batch_id}: {e}")
            return None
    
    def cancel_batch(self, batch_id: str) -> bool:
        """Cancel a running batch."""
        try:
            # Get batch job info
            job_info = self._get_cached_batch_job(batch_id)
            if not job_info:
                return False
            
            # Revoke Celery tasks
            from celery import current_app
            for task_id in job_info.get('celery_task_ids', []):
                current_app.control.revoke(task_id, terminate=True)
            
            # Update batch status
            manifest = self._get_cached_batch_manifest(batch_id)
            if manifest:
                manifest['status'] = BatchStatus.CANCELLED.value
                manifest['completed_at'] = datetime.now().isoformat()
                self._cache_batch_manifest(manifest)
            
            logger.info(f"Cancelled batch {batch_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error cancelling batch {batch_id}: {e}")
            return False
    
    # Private helper methods
    
    def _estimate_batch_processing_time(self, documents: List[Dict[str, Any]]) -> int:
        """Estimate processing time for a batch."""
        total_time = 0
        
        for doc in documents:
            complexity = doc.get('processing_complexity', 'standard')
            size_mb = doc.get('file_size_mb', 1.0)
            
            if complexity == 'simple':
                base_time = 2
            elif complexity == 'standard':
                base_time = 5
            else:  # complex
                base_time = 12
            
            # Adjust for size
            size_multiplier = max(1.0, size_mb / 5.0)
            total_time += base_time * size_multiplier
        
        return max(10, int(total_time))
    
    def _get_queue_for_priority(self, priority: str) -> str:
        """Get appropriate Celery queue for priority."""
        if priority == 'urgent':
            return 'high_priority'
        elif priority == 'high':
            return 'default'
        else:
            return 'default'
    
    def _cache_batch_manifest(self, manifest: BatchManifest) -> None:
        """Cache batch manifest in Redis."""
        if self.redis.is_available():
            key = f"batch:manifest:{manifest.batch_id}"
            self.redis.set_cached(key, manifest.to_dict(), ttl=86400)  # 24 hours
    
    def _get_cached_batch_manifest(self, batch_id: str) -> Optional[Dict[str, Any]]:
        """Get cached batch manifest."""
        if self.redis.is_available():
            key = f"batch:manifest:{batch_id}"
            return self.redis.get_cached(key)
        return None
    
    def _cache_batch_job(self, job: BatchJobId) -> None:
        """Cache batch job information."""
        if self.redis.is_available():
            key = f"batch:job:{job.batch_id}"
            self.redis.set_cached(key, asdict(job), ttl=86400)
    
    def _get_cached_batch_job(self, batch_id: str) -> Optional[Dict[str, Any]]:
        """Get cached batch job information."""
        if self.redis.is_available():
            key = f"batch:job:{batch_id}"
            return self.redis.get_cached(key)
        return None
    
    def _initialize_batch_progress_tracking(self, batch: BatchManifest) -> None:
        """Initialize progress tracking for a batch."""
        if self.redis.is_available():
            # Set initial status for all documents
            for doc in batch.documents:
                doc_key = f"doc:status:{doc.get('document_uuid', doc.get('filename'))}"
                initial_status = {
                    'batch_id': batch.batch_id,
                    'overall_status': 'pending',
                    'current_stage': 'intake',
                    'started_at': datetime.now().isoformat(),
                    'stages_completed': [],
                    'error_count': 0
                }
                self.redis.set_cached(doc_key, initial_status, ttl=86400)
    
    def _get_batch_document_statuses(self, batch_id: str) -> Dict[str, Dict[str, Any]]:
        """Get status of all documents in a batch."""
        statuses = {}
        
        if not self.redis.is_available():
            return statuses
        
        # Get batch manifest to know which documents to check
        manifest = self._get_cached_batch_manifest(batch_id)
        if not manifest:
            return statuses
        
        # Check status of each document
        for doc in manifest.get('documents', []):
            doc_id = doc.get('document_uuid', doc.get('filename'))
            doc_key = f"doc:status:{doc_id}"
            status = self.redis.get_cached(doc_key)
            if status:
                statuses[doc_id] = status
        
        return statuses
    
    def _cache_batch_progress(self, progress: BatchProgress) -> None:
        """Cache batch progress."""
        if self.redis.is_available():
            key = f"batch:progress:{progress.batch_id}"
            self.redis.set_cached(key, progress.to_dict(), ttl=3600)  # 1 hour
    
    def _execute_recovery_plan(self, plan: RecoveryPlan) -> None:
        """Execute a recovery plan."""
        try:
            # Increment retry count
            retry_key = f"batch:retry_count:{plan.batch_id}"
            self.redis.set_cached(retry_key, plan.retry_count + 1, ttl=86400)
            
            if plan.retry_strategy == "immediate":
                # Retry failed documents immediately
                logger.info(f"Executing immediate retry for batch {plan.batch_id}")
                # Implementation would resubmit failed documents
                
            elif plan.retry_strategy == "delayed":
                # Schedule delayed retry
                logger.info(f"Scheduling delayed retry for batch {plan.batch_id}")
                # Implementation would use Celery's countdown feature
            
        except Exception as e:
            logger.error(f"Error executing recovery plan for batch {plan.batch_id}: {e}")
    
    def _calculate_batch_performance_metrics(self, batch_id: str) -> Dict[str, Any]:
        """Calculate performance metrics for a batch."""
        # Placeholder for performance metrics calculation
        return {
            'average_processing_time_per_document_minutes': 0.0,
            'throughput_documents_per_hour': 0.0,
            'success_rate_percentage': 0.0,
            'error_rate_percentage': 0.0
        }
    
    def _get_batch_quality_indicators(self, batch_id: str) -> Dict[str, Any]:
        """Get quality indicators for a batch."""
        # Placeholder for quality indicators
        return {
            'text_extraction_success_rate': 0.0,
            'entity_extraction_completion_rate': 0.0,
            'processing_consistency_score': 0.0
        }