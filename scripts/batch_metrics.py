"""
Batch processing metrics collection and reporting.

This module provides comprehensive metrics collection for batch processing,
including performance metrics, error tracking, and resource utilization.
"""

import logging
import time
import json
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from collections import defaultdict

from scripts.cache import get_redis_manager
from scripts.config import REDIS_PREFIX_METRICS
from scripts.celery_app import app

logger = logging.getLogger(__name__)


class BatchMetricsCollector:
    """Collects and aggregates batch processing metrics."""
    
    def __init__(self):
        self.redis_manager = get_redis_manager()
        self.metrics_ttl = 7 * 24 * 3600  # Keep metrics for 7 days
        
    def record_batch_start(self, batch_id: str, priority: str, document_count: int):
        """Record batch processing start."""
        timestamp = int(time.time())
        metric_key = f"{REDIS_PREFIX_METRICS}batch:start:{timestamp // 60}"
        
        metric_data = {
            'batch_id': batch_id,
            'priority': priority,
            'document_count': document_count,
            'timestamp': timestamp,
            'type': 'batch_start'
        }
        
        # Store in sorted set for time-series queries
        self.redis_manager.get_client().zadd(
            metric_key,
            {json.dumps(metric_data): timestamp}
        )
        self.redis_manager.get_client().expire(metric_key, self.metrics_ttl)
        
        # Update batch-specific metrics
        batch_metric_key = f"{REDIS_PREFIX_METRICS}batch:details:{batch_id}"
        self.redis_manager.store_dict(batch_metric_key, {
            'start_time': timestamp,
            'priority': priority,
            'document_count': document_count,
            'status': 'started'
        }, ttl=self.metrics_ttl)
    
    def record_batch_complete(self, batch_id: str, completed: int, failed: int, 
                            duration_seconds: float):
        """Record batch processing completion."""
        timestamp = int(time.time())
        metric_key = f"{REDIS_PREFIX_METRICS}batch:complete:{timestamp // 60}"
        
        success_rate = (completed / (completed + failed) * 100) if (completed + failed) > 0 else 0
        
        metric_data = {
            'batch_id': batch_id,
            'completed': completed,
            'failed': failed,
            'success_rate': success_rate,
            'duration_seconds': duration_seconds,
            'timestamp': timestamp,
            'type': 'batch_complete'
        }
        
        # Store in sorted set
        self.redis_manager.get_client().zadd(
            metric_key,
            {json.dumps(metric_data): timestamp}
        )
        self.redis_manager.get_client().expire(metric_key, self.metrics_ttl)
        
        # Update batch-specific metrics
        batch_metric_key = f"{REDIS_PREFIX_METRICS}batch:details:{batch_id}"
        batch_data = self.redis_manager.get_dict(batch_metric_key) or {}
        batch_data.update({
            'end_time': timestamp,
            'completed': completed,
            'failed': failed,
            'success_rate': success_rate,
            'duration_seconds': duration_seconds,
            'status': 'completed',
            'throughput_per_minute': (completed + failed) / (duration_seconds / 60) if duration_seconds > 0 else 0
        })
        self.redis_manager.store_dict(batch_metric_key, batch_data, ttl=self.metrics_ttl)
    
    def record_document_metric(self, batch_id: str, document_uuid: str, 
                             stage: str, duration_ms: float, status: str):
        """Record individual document processing metrics within a batch."""
        timestamp = int(time.time())
        metric_key = f"{REDIS_PREFIX_METRICS}document:{stage}:{timestamp // 60}"
        
        metric_data = {
            'batch_id': batch_id,
            'document_uuid': document_uuid,
            'stage': stage,
            'duration_ms': duration_ms,
            'status': status,
            'timestamp': timestamp,
            'type': 'document_stage'
        }
        
        # Store in sorted set
        self.redis_manager.get_client().zadd(
            metric_key,
            {json.dumps(metric_data): timestamp}
        )
        self.redis_manager.get_client().expire(metric_key, self.metrics_ttl)
        
        # Update stage-specific metrics
        self._update_stage_metrics(stage, duration_ms, status)
    
    def record_error(self, batch_id: str, document_uuid: str, stage: str, 
                    error_type: str, error_message: str):
        """Record processing error."""
        timestamp = int(time.time())
        metric_key = f"{REDIS_PREFIX_METRICS}errors:{timestamp // 3600}"  # Hourly buckets
        
        error_data = {
            'batch_id': batch_id,
            'document_uuid': document_uuid,
            'stage': stage,
            'error_type': error_type,
            'error_message': error_message[:500],  # Truncate long messages
            'timestamp': timestamp,
            'type': 'error'
        }
        
        # Store in sorted set
        self.redis_manager.get_client().zadd(
            metric_key,
            {json.dumps(error_data): timestamp}
        )
        self.redis_manager.get_client().expire(metric_key, self.metrics_ttl)
        
        # Increment error counters
        self._increment_error_counter(error_type, stage)
    
    def record_resource_usage(self, worker_id: str, cpu_percent: float, 
                            memory_mb: float, active_tasks: int):
        """Record worker resource usage."""
        timestamp = int(time.time())
        metric_key = f"{REDIS_PREFIX_METRICS}resources:{timestamp // 60}"
        
        resource_data = {
            'worker_id': worker_id,
            'cpu_percent': cpu_percent,
            'memory_mb': memory_mb,
            'active_tasks': active_tasks,
            'timestamp': timestamp,
            'type': 'resource_usage'
        }
        
        # Store in sorted set
        self.redis_manager.get_client().zadd(
            metric_key,
            {json.dumps(resource_data): timestamp}
        )
        self.redis_manager.get_client().expire(metric_key, self.metrics_ttl)
    
    def get_batch_metrics(self, start_time: datetime, end_time: datetime) -> Dict[str, Any]:
        """Get aggregated batch metrics for a time range."""
        start_ts = int(start_time.timestamp())
        end_ts = int(end_time.timestamp())
        
        # Collect metrics from different buckets
        batch_starts = self._collect_metrics('batch:start', start_ts, end_ts)
        batch_completes = self._collect_metrics('batch:complete', start_ts, end_ts)
        
        # Aggregate by priority
        by_priority = defaultdict(lambda: {'count': 0, 'completed': 0, 'failed': 0, 
                                          'total_duration': 0, 'documents': 0})
        
        for metric in batch_starts:
            priority = metric.get('priority', 'normal')
            by_priority[priority]['count'] += 1
            by_priority[priority]['documents'] += metric.get('document_count', 0)
        
        for metric in batch_completes:
            # Find corresponding start to get priority
            batch_id = metric.get('batch_id')
            batch_details = self.redis_manager.get_dict(
                f"{REDIS_PREFIX_METRICS}batch:details:{batch_id}"
            )
            if batch_details:
                priority = batch_details.get('priority', 'normal')
                by_priority[priority]['completed'] += metric.get('completed', 0)
                by_priority[priority]['failed'] += metric.get('failed', 0)
                by_priority[priority]['total_duration'] += metric.get('duration_seconds', 0)
        
        # Calculate aggregates
        total_batches = sum(p['count'] for p in by_priority.values())
        total_documents = sum(p['documents'] for p in by_priority.values())
        total_completed = sum(p['completed'] for p in by_priority.values())
        total_failed = sum(p['failed'] for p in by_priority.values())
        
        return {
            'time_range': {
                'start': start_time.isoformat(),
                'end': end_time.isoformat()
            },
            'summary': {
                'total_batches': total_batches,
                'total_documents': total_documents,
                'total_completed': total_completed,
                'total_failed': total_failed,
                'overall_success_rate': (total_completed / (total_completed + total_failed) * 100) 
                                       if (total_completed + total_failed) > 0 else 0
            },
            'by_priority': dict(by_priority)
        }
    
    def get_stage_metrics(self, start_time: datetime, end_time: datetime) -> Dict[str, Any]:
        """Get processing stage metrics."""
        stage_key = f"{REDIS_PREFIX_METRICS}stage:stats"
        stage_stats = self.redis_manager.get_dict(stage_key) or {}
        
        # Calculate averages
        for stage, stats in stage_stats.items():
            if stats.get('count', 0) > 0:
                stats['avg_duration_ms'] = stats.get('total_duration', 0) / stats['count']
                stats['success_rate'] = (stats.get('success', 0) / stats['count']) * 100
        
        return stage_stats
    
    def get_error_summary(self, hours: int = 24) -> Dict[str, Any]:
        """Get error summary for the last N hours."""
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(hours=hours)
        
        errors = self._collect_metrics('errors', 
                                     int(start_time.timestamp()), 
                                     int(end_time.timestamp()))
        
        # Group by error type and stage
        by_type = defaultdict(int)
        by_stage = defaultdict(int)
        recent_errors = []
        
        for error in errors:
            by_type[error.get('error_type', 'unknown')] += 1
            by_stage[error.get('stage', 'unknown')] += 1
            
            # Keep last 20 errors
            if len(recent_errors) < 20:
                recent_errors.append({
                    'timestamp': datetime.fromtimestamp(error['timestamp']).isoformat(),
                    'batch_id': error.get('batch_id'),
                    'document_uuid': error.get('document_uuid'),
                    'stage': error.get('stage'),
                    'error_type': error.get('error_type'),
                    'message': error.get('error_message')
                })
        
        return {
            'time_range': f'Last {hours} hours',
            'total_errors': len(errors),
            'by_type': dict(by_type),
            'by_stage': dict(by_stage),
            'recent_errors': recent_errors
        }
    
    def get_performance_report(self, batch_id: str) -> Dict[str, Any]:
        """Get detailed performance report for a specific batch."""
        batch_key = f"{REDIS_PREFIX_METRICS}batch:details:{batch_id}"
        batch_data = self.redis_manager.get_dict(batch_key)
        
        if not batch_data:
            return {'error': 'Batch not found'}
        
        # Get document-level metrics
        start_ts = batch_data.get('start_time', 0)
        end_ts = batch_data.get('end_time', int(time.time()))
        
        doc_metrics = self._collect_metrics('document', start_ts, end_ts)
        batch_docs = [m for m in doc_metrics if m.get('batch_id') == batch_id]
        
        # Calculate stage performance
        stage_performance = defaultdict(lambda: {'count': 0, 'total_duration': 0, 
                                               'success': 0, 'failed': 0})
        
        for metric in batch_docs:
            stage = metric.get('stage')
            if stage:
                stage_performance[stage]['count'] += 1
                stage_performance[stage]['total_duration'] += metric.get('duration_ms', 0)
                if metric.get('status') == 'success':
                    stage_performance[stage]['success'] += 1
                else:
                    stage_performance[stage]['failed'] += 1
        
        # Calculate averages
        for stage, perf in stage_performance.items():
            if perf['count'] > 0:
                perf['avg_duration_ms'] = perf['total_duration'] / perf['count']
                perf['success_rate'] = (perf['success'] / perf['count']) * 100
        
        return {
            'batch_id': batch_id,
            'batch_summary': batch_data,
            'stage_performance': dict(stage_performance),
            'document_count': len(set(m.get('document_uuid') for m in batch_docs))
        }
    
    def _collect_metrics(self, metric_type: str, start_ts: int, end_ts: int) -> List[Dict]:
        """Collect metrics from Redis sorted sets."""
        metrics = []
        
        # Calculate minute buckets
        start_minute = start_ts // 60
        end_minute = end_ts // 60
        
        for minute in range(start_minute, end_minute + 1):
            metric_key = f"{REDIS_PREFIX_METRICS}{metric_type}:{minute}"
            
            # Get all metrics in this bucket within time range
            bucket_metrics = self.redis_manager.get_client().zrangebyscore(
                metric_key, start_ts, end_ts
            )
            
            for metric_json in bucket_metrics:
                try:
                    metrics.append(json.loads(metric_json))
                except json.JSONDecodeError:
                    logger.error(f"Invalid metric JSON: {metric_json}")
        
        return metrics
    
    def _update_stage_metrics(self, stage: str, duration_ms: float, status: str):
        """Update aggregated stage metrics."""
        stage_key = f"{REDIS_PREFIX_METRICS}stage:stats"
        
        # Get existing stats
        stats = self.redis_manager.get_dict(stage_key) or {}
        
        if stage not in stats:
            stats[stage] = {
                'count': 0,
                'total_duration': 0,
                'success': 0,
                'failed': 0
            }
        
        stats[stage]['count'] += 1
        stats[stage]['total_duration'] += duration_ms
        
        if status == 'success':
            stats[stage]['success'] += 1
        else:
            stats[stage]['failed'] += 1
        
        self.redis_manager.store_dict(stage_key, stats, ttl=self.metrics_ttl)
    
    def _increment_error_counter(self, error_type: str, stage: str):
        """Increment error counters."""
        counter_key = f"{REDIS_PREFIX_METRICS}error:counters"
        
        # Get existing counters
        counters = self.redis_manager.get_dict(counter_key) or {}
        
        # Increment counters
        type_key = f"type:{error_type}"
        stage_key = f"stage:{stage}"
        
        counters[type_key] = counters.get(type_key, 0) + 1
        counters[stage_key] = counters.get(stage_key, 0) + 1
        counters['total'] = counters.get('total', 0) + 1
        
        self.redis_manager.store_dict(counter_key, counters, ttl=self.metrics_ttl)


# Celery task for periodic metrics collection
@app.task
def collect_system_metrics():
    """Collect system-wide metrics (run periodically)."""
    import psutil
    import socket
    
    collector = BatchMetricsCollector()
    
    # Get worker hostname
    hostname = socket.gethostname()
    
    # Collect CPU and memory usage
    cpu_percent = psutil.cpu_percent(interval=1)
    memory = psutil.virtual_memory()
    memory_mb = memory.used / 1024 / 1024
    
    # Get active task count from Celery
    from celery import current_app
    active_tasks = current_app.control.inspect().active()
    task_count = sum(len(tasks) for tasks in active_tasks.values()) if active_tasks else 0
    
    # Record metrics
    collector.record_resource_usage(
        worker_id=hostname,
        cpu_percent=cpu_percent,
        memory_mb=memory_mb,
        active_tasks=task_count
    )
    
    return {
        'hostname': hostname,
        'cpu_percent': cpu_percent,
        'memory_mb': memory_mb,
        'active_tasks': task_count
    }


# Helper functions for easy metric recording
_collector = None

def get_metrics_collector() -> BatchMetricsCollector:
    """Get singleton metrics collector instance."""
    global _collector
    if _collector is None:
        _collector = BatchMetricsCollector()
    return _collector


def record_batch_metric(batch_id: str, metric_type: str, **kwargs):
    """Convenience function to record batch metrics."""
    collector = get_metrics_collector()
    
    if metric_type == 'start':
        collector.record_batch_start(batch_id, kwargs.get('priority', 'normal'), 
                                   kwargs.get('document_count', 0))
    elif metric_type == 'complete':
        collector.record_batch_complete(batch_id, kwargs.get('completed', 0),
                                      kwargs.get('failed', 0), 
                                      kwargs.get('duration_seconds', 0))
    elif metric_type == 'document':
        collector.record_document_metric(batch_id, kwargs.get('document_uuid'),
                                       kwargs.get('stage'), kwargs.get('duration_ms', 0),
                                       kwargs.get('status', 'unknown'))
    elif metric_type == 'error':
        collector.record_error(batch_id, kwargs.get('document_uuid'),
                             kwargs.get('stage'), kwargs.get('error_type'),
                             kwargs.get('error_message', ''))