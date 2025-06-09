"""
Status Manager - Multi-layer status tracking for document processing pipeline.

This service provides:
- Real-time document and batch status tracking via Redis
- Processing stage progression monitoring
- Error rate tracking and analysis
- Worker health and performance monitoring
- Live dashboard data aggregation
"""

import json
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
import logging

from scripts.cache import get_redis_manager
from scripts.logging_config import get_logger

logger = get_logger(__name__)


class ProcessingStage(Enum):
    """Document processing stages."""
    INTAKE = "intake"
    OCR = "ocr" 
    CHUNKING = "chunking"
    ENTITY_EXTRACTION = "entity_extraction"
    ENTITY_RESOLUTION = "entity_resolution"
    RELATIONSHIP_BUILDING = "relationship_building"
    COMPLETED = "completed"
    FAILED = "failed"


class DocumentStatus(Enum):
    """Document processing status."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRYING = "retrying"


@dataclass
class ProcessingEvent:
    """Individual processing event for a document."""
    document_uuid: str
    stage: str
    status: str
    timestamp: str
    metadata: Dict[str, Any]
    error_message: Optional[str] = None
    worker_id: Optional[str] = None
    task_id: Optional[str] = None
    elapsed_seconds: float = 0.0


@dataclass
class DocumentStatusInfo:
    """Complete status information for a document."""
    document_uuid: str
    batch_id: Optional[str]
    overall_status: str
    current_stage: str
    stages_completed: List[str]
    started_at: str
    last_updated: str
    error_count: int
    retry_count: int
    estimated_completion: Optional[str]
    processing_metadata: Dict[str, Any]


@dataclass
class BatchStatus:
    """Status information for a processing batch."""
    batch_id: str
    total_documents: int
    completed: int
    in_progress: int
    failed: int
    pending: int
    started_at: Optional[str]
    estimated_completion: Optional[str]
    completion_percentage: float
    stage_distribution: Dict[str, int]


@dataclass
class WorkerStatus:
    """Status information for processing workers."""
    worker_id: str
    status: str  # active, idle, busy, offline
    current_tasks: List[str]
    tasks_completed_today: int
    tasks_failed_today: int
    average_task_time_minutes: float
    last_heartbeat: str
    memory_usage_mb: float
    cpu_usage_percentage: float


@dataclass
class DashboardData:
    """Aggregated data for live monitoring dashboard."""
    timestamp: str
    active_batches: List[BatchStatus]
    worker_statuses: List[WorkerStatus]
    processing_metrics: Dict[str, Any]
    error_summary: Dict[str, Any]
    performance_indicators: Dict[str, Any]


@dataclass
class ErrorMetrics:
    """Error tracking metrics."""
    stage: str
    error_count_last_hour: int
    error_count_last_24h: int
    error_rate_percentage: float
    common_errors: List[Dict[str, Any]]
    trend: str  # increasing, decreasing, stable


class StatusManager:
    """Manager for document and batch processing status."""
    
    def __init__(self):
        self.redis = get_redis_manager()
        
    def track_document_status(self, doc_id: str, stage: str, status: str, 
                            metadata: Dict[str, Any]) -> None:
        """
        Track document status through processing stages.
        
        Args:
            doc_id: Document UUID
            stage: Current processing stage
            status: Current status
            metadata: Additional metadata (task_id, worker_id, etc.)
        """
        if not self.redis.is_available():
            logger.warning("Redis not available for status tracking")
            return
            
        try:
            timestamp = datetime.now().isoformat()
            
            # Get existing status or create new
            status_key = f"doc:status:{doc_id}"
            existing_status = self.redis.get_cached(status_key) or {}
            
            # Update document status
            if status == "completed" and stage not in existing_status.get('stages_completed', []):
                stages_completed = existing_status.get('stages_completed', [])
                stages_completed.append(stage)
            else:
                stages_completed = existing_status.get('stages_completed', [])
            
            # Calculate overall status
            overall_status = self._calculate_overall_status(status, stage, stages_completed)
            
            updated_status = {
                'document_uuid': doc_id,
                'batch_id': existing_status.get('batch_id'),
                'overall_status': overall_status,
                'current_stage': stage,
                'stages_completed': stages_completed,
                'started_at': existing_status.get('started_at', timestamp),
                'last_updated': timestamp,
                'error_count': existing_status.get('error_count', 0),
                'retry_count': existing_status.get('retry_count', 0),
                'processing_metadata': {
                    **existing_status.get('processing_metadata', {}),
                    **metadata
                }
            }
            
            # Add error information if status is failed
            if status == "failed":
                updated_status['error_count'] += 1
                updated_status['last_error'] = {
                    'stage': stage,
                    'timestamp': timestamp,
                    'message': metadata.get('error_message', 'Unknown error')
                }
            
            # Cache updated status
            self.redis.set_cached(status_key, updated_status, ttl=86400)  # 24 hours
            
            # Track stage-specific metrics
            self._track_stage_metrics(stage, status, metadata)
            
            # Update batch progress if document is part of a batch
            if updated_status.get('batch_id'):
                self._update_batch_progress(updated_status['batch_id'])
            
            logger.debug(f"Updated status for {doc_id}: {stage} -> {status}")
            
        except Exception as e:
            logger.error(f"Error tracking document status for {doc_id}: {e}")
    
    def get_document_status(self, doc_id: str) -> Optional[DocumentStatusInfo]:
        """Get current status for a document."""
        if not self.redis.is_available():
            return None
            
        try:
            status_key = f"doc:status:{doc_id}"
            status_data = self.redis.get_cached(status_key)
            
            if not status_data:
                return None
            
            return DocumentStatusInfo(
                document_uuid=status_data['document_uuid'],
                batch_id=status_data.get('batch_id'),
                overall_status=status_data['overall_status'],
                current_stage=status_data['current_stage'],
                stages_completed=status_data['stages_completed'],
                started_at=status_data['started_at'],
                last_updated=status_data['last_updated'],
                error_count=status_data.get('error_count', 0),
                retry_count=status_data.get('retry_count', 0),
                estimated_completion=status_data.get('estimated_completion'),
                processing_metadata=status_data.get('processing_metadata', {})
            )
            
        except Exception as e:
            logger.error(f"Error getting document status for {doc_id}: {e}")
            return None
    
    def get_live_processing_dashboard(self) -> DashboardData:
        """Get real-time dashboard data."""
        try:
            timestamp = datetime.now().isoformat()
            
            # Get active batches
            active_batches = self._get_active_batches()
            
            # Get worker statuses
            worker_statuses = self._get_worker_statuses()
            
            # Calculate processing metrics
            processing_metrics = self._calculate_processing_metrics()
            
            # Get error summary
            error_summary = self._get_error_summary()
            
            # Calculate performance indicators
            performance_indicators = self._calculate_performance_indicators()
            
            return DashboardData(
                timestamp=timestamp,
                active_batches=active_batches,
                worker_statuses=worker_statuses,
                processing_metrics=processing_metrics,
                error_summary=error_summary,
                performance_indicators=performance_indicators
            )
            
        except Exception as e:
            logger.error(f"Error getting dashboard data: {e}")
            return DashboardData(
                timestamp=datetime.now().isoformat(),
                active_batches=[],
                worker_statuses=[],
                processing_metrics={},
                error_summary={},
                performance_indicators={}
            )
    
    def track_batch_progress(self, batch_id: str) -> Optional[BatchStatus]:
        """Track progress of a processing batch."""
        if not self.redis.is_available():
            return None
            
        try:
            # Get batch manifest
            manifest_key = f"batch:manifest:{batch_id}"
            manifest = self.redis.get_cached(manifest_key)
            
            if not manifest:
                return None
            
            total_documents = manifest.get('document_count', 0)
            
            # Count document statuses
            completed = 0
            in_progress = 0
            failed = 0
            pending = 0
            stage_distribution = {}
            
            # Get document statuses for this batch
            documents = manifest.get('documents', [])
            for doc in documents:
                doc_id = doc.get('document_uuid', doc.get('filename'))
                status_key = f"doc:status:{doc_id}"
                doc_status = self.redis.get_cached(status_key)
                
                if doc_status:
                    overall_status = doc_status.get('overall_status', 'pending')
                    current_stage = doc_status.get('current_stage', 'unknown')
                    
                    # Count by overall status
                    if overall_status == 'completed':
                        completed += 1
                    elif overall_status == 'failed':
                        failed += 1
                    elif overall_status == 'in_progress':
                        in_progress += 1
                    else:
                        pending += 1
                    
                    # Count by stage
                    stage_distribution[current_stage] = stage_distribution.get(current_stage, 0) + 1
                else:
                    pending += 1
                    stage_distribution['unknown'] = stage_distribution.get('unknown', 0) + 1
            
            # Calculate completion percentage
            completion_percentage = (completed / total_documents * 100) if total_documents > 0 else 0
            
            # Estimate completion time
            estimated_completion = None
            started_at = manifest.get('started_at')
            if started_at and completed > 0 and (in_progress + pending) > 0:
                start_time = datetime.fromisoformat(started_at.replace('Z', '+00:00'))
                elapsed_minutes = (datetime.now() - start_time.replace(tzinfo=None)).total_seconds() / 60
                avg_time_per_doc = elapsed_minutes / completed
                remaining_time = avg_time_per_doc * (in_progress + pending)
                estimated_completion = (datetime.now() + timedelta(minutes=remaining_time)).isoformat()
            
            batch_status = BatchStatus(
                batch_id=batch_id,
                total_documents=total_documents,
                completed=completed,
                in_progress=in_progress,
                failed=failed,
                pending=pending,
                started_at=started_at,
                estimated_completion=estimated_completion,
                completion_percentage=round(completion_percentage, 1),
                stage_distribution=stage_distribution
            )
            
            # Cache batch status
            status_key = f"batch:status:{batch_id}"
            self.redis.set_cached(status_key, asdict(batch_status), ttl=300)  # 5 minutes
            
            return batch_status
            
        except Exception as e:
            logger.error(f"Error tracking batch progress for {batch_id}: {e}")
            return None
    
    def get_worker_health_status(self) -> List[WorkerStatus]:
        """Get health status of all workers."""
        if not self.redis.is_available():
            return []
            
        try:
            worker_statuses = []
            
            # Get list of active workers
            workers_key = "workers:active"
            worker_ids = self.redis.get_cached(workers_key) or []
            
            for worker_id in worker_ids:
                worker_key = f"worker:status:{worker_id}"
                worker_data = self.redis.get_cached(worker_key)
                
                if worker_data:
                    worker_status = WorkerStatus(
                        worker_id=worker_data['worker_id'],
                        status=worker_data.get('status', 'unknown'),
                        current_tasks=worker_data.get('current_tasks', []),
                        tasks_completed_today=worker_data.get('tasks_completed_today', 0),
                        tasks_failed_today=worker_data.get('tasks_failed_today', 0),
                        average_task_time_minutes=worker_data.get('average_task_time_minutes', 0.0),
                        last_heartbeat=worker_data.get('last_heartbeat', ''),
                        memory_usage_mb=worker_data.get('memory_usage_mb', 0.0),
                        cpu_usage_percentage=worker_data.get('cpu_usage_percentage', 0.0)
                    )
                    worker_statuses.append(worker_status)
            
            return worker_statuses
            
        except Exception as e:
            logger.error(f"Error getting worker health status: {e}")
            return []
    
    def track_error_rates_by_stage(self) -> Dict[str, ErrorMetrics]:
        """Track error rates for each processing stage."""
        if not self.redis.is_available():
            return {}
            
        try:
            error_metrics = {}
            
            for stage in ProcessingStage:
                stage_name = stage.value
                
                # Get error counts
                error_key_1h = f"errors:stage:{stage_name}:1h"
                error_key_24h = f"errors:stage:{stage_name}:24h"
                
                errors_1h = len(self.redis.get_cached(error_key_1h) or [])
                errors_24h = len(self.redis.get_cached(error_key_24h) or [])
                
                # Calculate error rate
                total_processed_key = f"metrics:stage:{stage_name}:processed:24h"
                total_processed = self.redis.get_cached(total_processed_key) or 0
                
                error_rate = (errors_24h / total_processed * 100) if total_processed > 0 else 0
                
                # Determine trend
                error_key_prev_24h = f"errors:stage:{stage_name}:prev_24h"
                errors_prev_24h = len(self.redis.get_cached(error_key_prev_24h) or [])
                
                if errors_24h > errors_prev_24h * 1.1:
                    trend = "increasing"
                elif errors_24h < errors_prev_24h * 0.9:
                    trend = "decreasing"
                else:
                    trend = "stable"
                
                # Get common errors
                common_errors_key = f"errors:stage:{stage_name}:common"
                common_errors = self.redis.get_cached(common_errors_key) or []
                
                error_metrics[stage_name] = ErrorMetrics(
                    stage=stage_name,
                    error_count_last_hour=errors_1h,
                    error_count_last_24h=errors_24h,
                    error_rate_percentage=round(error_rate, 2),
                    common_errors=common_errors[:5],  # Top 5 common errors
                    trend=trend
                )
            
            return error_metrics
            
        except Exception as e:
            logger.error(f"Error tracking error rates: {e}")
            return {}
    
    def register_processing_event(self, event: ProcessingEvent) -> None:
        """Register a processing event for analytics."""
        if not self.redis.is_available():
            return
            
        try:
            # Store event in time-series data
            event_key = f"events:{event.stage}:{datetime.now().strftime('%Y%m%d%H')}"
            events = self.redis.get_cached(event_key) or []
            events.append(asdict(event))
            
            # Keep only last 1000 events per hour per stage
            if len(events) > 1000:
                events = events[-1000:]
            
            self.redis.set_cached(event_key, events, ttl=3600)  # 1 hour
            
            # Update stage metrics
            if event.status == "failed":
                self._record_stage_error(event.stage, event.error_message)
            
            self._record_stage_processing(event.stage)
            
        except Exception as e:
            logger.error(f"Error registering processing event: {e}")
    
    # Private helper methods
    
    def _calculate_overall_status(self, current_status: str, current_stage: str, 
                                stages_completed: List[str]) -> str:
        """Calculate overall document status."""
        if current_status == "failed":
            return DocumentStatus.FAILED.value
        elif current_status == "cancelled":
            return DocumentStatus.CANCELLED.value
        elif current_status == "retrying":
            return DocumentStatus.RETRYING.value
        elif current_stage == ProcessingStage.COMPLETED.value:
            return DocumentStatus.COMPLETED.value
        elif len(stages_completed) > 0 or current_status == "in_progress":
            return DocumentStatus.IN_PROGRESS.value
        else:
            return DocumentStatus.PENDING.value
    
    def _track_stage_metrics(self, stage: str, status: str, metadata: Dict[str, Any]) -> None:
        """Track metrics for a processing stage."""
        if not self.redis.is_available():
            return
            
        try:
            # Track processing counts
            date_key = datetime.now().strftime('%Y%m%d')
            processed_key = f"metrics:stage:{stage}:processed:{date_key}"
            current_count = self.redis.get_cached(processed_key) or 0
            self.redis.set_cached(processed_key, current_count + 1, ttl=86400)
            
            # Track timing if available
            if 'elapsed_seconds' in metadata:
                timing_key = f"metrics:stage:{stage}:timing:{date_key}"
                timings = self.redis.get_cached(timing_key) or []
                timings.append(metadata['elapsed_seconds'])
                
                # Keep only last 1000 timings
                if len(timings) > 1000:
                    timings = timings[-1000:]
                
                self.redis.set_cached(timing_key, timings, ttl=86400)
            
        except Exception as e:
            logger.error(f"Error tracking stage metrics: {e}")
    
    def _update_batch_progress(self, batch_id: str) -> None:
        """Update cached batch progress."""
        try:
            # Trigger batch progress calculation
            self.track_batch_progress(batch_id)
        except Exception as e:
            logger.error(f"Error updating batch progress for {batch_id}: {e}")
    
    def _get_active_batches(self) -> List[BatchStatus]:
        """Get list of active batches."""
        if not self.redis.is_available():
            return []
            
        try:
            # This would scan for active batch keys
            # For now, return empty list as placeholder
            return []
        except Exception as e:
            logger.error(f"Error getting active batches: {e}")
            return []
    
    def _get_worker_statuses(self) -> List[WorkerStatus]:
        """Get current worker statuses."""
        return self.get_worker_health_status()
    
    def _calculate_processing_metrics(self) -> Dict[str, Any]:
        """Calculate overall processing metrics."""
        if not self.redis.is_available():
            return {}
            
        try:
            today = datetime.now().strftime('%Y%m%d')
            metrics = {}
            
            # Calculate throughput for each stage
            for stage in ProcessingStage:
                stage_name = stage.value
                processed_key = f"metrics:stage:{stage_name}:processed:{today}"
                processed_count = self.redis.get_cached(processed_key) or 0
                metrics[f"{stage_name}_processed_today"] = processed_count
            
            return metrics
            
        except Exception as e:
            logger.error(f"Error calculating processing metrics: {e}")
            return {}
    
    def _get_error_summary(self) -> Dict[str, Any]:
        """Get summary of recent errors."""
        try:
            error_rates = self.track_error_rates_by_stage()
            
            total_errors_24h = sum(metrics.error_count_last_24h for metrics in error_rates.values())
            total_errors_1h = sum(metrics.error_count_last_hour for metrics in error_rates.values())
            
            return {
                'total_errors_last_hour': total_errors_1h,
                'total_errors_last_24h': total_errors_24h,
                'stages_with_errors': len([s for s, m in error_rates.items() if m.error_count_last_24h > 0]),
                'highest_error_rate_stage': max(error_rates.keys(), key=lambda x: error_rates[x].error_rate_percentage) if error_rates else None
            }
            
        except Exception as e:
            logger.error(f"Error getting error summary: {e}")
            return {}
    
    def _calculate_performance_indicators(self) -> Dict[str, Any]:
        """Calculate performance indicators."""
        # Placeholder for performance calculations
        return {
            'average_processing_time_minutes': 0.0,
            'throughput_documents_per_hour': 0.0,
            'system_utilization_percentage': 0.0,
            'success_rate_percentage': 0.0
        }
    
    def _record_stage_error(self, stage: str, error_message: Optional[str]) -> None:
        """Record an error for a specific stage."""
        if not self.redis.is_available():
            return
            
        try:
            # Add to error lists
            error_key_1h = f"errors:stage:{stage}:1h"
            error_key_24h = f"errors:stage:{stage}:24h"
            
            error_record = {
                'timestamp': datetime.now().isoformat(),
                'message': error_message or 'Unknown error'
            }
            
            # Add to 1h list
            errors_1h = self.redis.get_cached(error_key_1h) or []
            errors_1h.append(error_record)
            
            # Keep only errors from last hour
            cutoff_time = datetime.now() - timedelta(hours=1)
            errors_1h = [e for e in errors_1h if datetime.fromisoformat(e['timestamp']) > cutoff_time]
            
            self.redis.set_cached(error_key_1h, errors_1h, ttl=3600)
            
            # Add to 24h list
            errors_24h = self.redis.get_cached(error_key_24h) or []
            errors_24h.append(error_record)
            
            # Keep only errors from last 24 hours
            cutoff_time = datetime.now() - timedelta(hours=24)
            errors_24h = [e for e in errors_24h if datetime.fromisoformat(e['timestamp']) > cutoff_time]
            
            self.redis.set_cached(error_key_24h, errors_24h, ttl=86400)
            
        except Exception as e:
            logger.error(f"Error recording stage error: {e}")
    
    def _record_stage_processing(self, stage: str) -> None:
        """Record that a document was processed in a stage."""
        if not self.redis.is_available():
            return
            
        try:
            # Update 24h processed count
            today = datetime.now().strftime('%Y%m%d')
            processed_key = f"metrics:stage:{stage}:processed:24h"
            current_count = self.redis.get_cached(processed_key) or 0
            self.redis.set_cached(processed_key, current_count + 1, ttl=86400)
            
        except Exception as e:
            logger.error(f"Error recording stage processing: {e}")