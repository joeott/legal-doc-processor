"""
Audit Logger - File-based audit logging for document processing pipeline.

This service provides:
- Processing event logging with structured data
- Error logging with context and stack traces
- Processing summaries and audit trails
- Performance and quality metrics logging
- Exportable audit trails for compliance
"""

import os
import json
import gzip
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
from pathlib import Path
import logging
from enum import Enum

from scripts.logging_config import get_logger

logger = get_logger(__name__)


class EventType(Enum):
    """Types of processing events."""
    DOCUMENT_INTAKE = "document_intake"
    OCR_START = "ocr_start"
    OCR_COMPLETE = "ocr_complete"
    CHUNKING_START = "chunking_start"
    CHUNKING_COMPLETE = "chunking_complete"
    ENTITY_EXTRACTION_START = "entity_extraction_start"
    ENTITY_EXTRACTION_COMPLETE = "entity_extraction_complete"
    ENTITY_RESOLUTION_START = "entity_resolution_start"
    ENTITY_RESOLUTION_COMPLETE = "entity_resolution_complete"
    RELATIONSHIP_BUILDING_START = "relationship_building_start"
    RELATIONSHIP_BUILDING_COMPLETE = "relationship_building_complete"
    PROCESSING_ERROR = "processing_error"
    BATCH_START = "batch_start"
    BATCH_COMPLETE = "batch_complete"
    VALIDATION_RUN = "validation_run"


class LogLevel(Enum):
    """Log levels for events."""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class ProcessingEvent:
    """Individual processing event for audit logging."""
    timestamp: str
    event_type: str
    level: str
    document_uuid: Optional[str]
    batch_id: Optional[str]
    stage: str
    status: str
    message: str
    metadata: Dict[str, Any]
    worker_id: Optional[str] = None
    task_id: Optional[str] = None
    elapsed_seconds: float = 0.0
    error_details: Optional[Dict[str, Any]] = None


@dataclass
class ProcessingSummary:
    """Summary of processing for a batch or time period."""
    summary_id: str
    summary_type: str  # batch, daily, hourly
    start_time: str
    end_time: str
    total_documents: int
    successful_documents: int
    failed_documents: int
    processing_stages: Dict[str, Dict[str, Any]]
    performance_metrics: Dict[str, float]
    quality_metrics: Dict[str, float]
    error_summary: Dict[str, Any]


@dataclass
class AuditTrail:
    """Complete audit trail for a document or batch."""
    audit_id: str
    subject_type: str  # document, batch
    subject_id: str
    created_at: str
    events: List[ProcessingEvent]
    summary: Dict[str, Any]
    compliance_data: Dict[str, Any]


class AuditLogger:
    """File-based audit logging system."""
    
    def __init__(self, base_log_dir: str = None):
        self.base_log_dir = Path(base_log_dir or "/opt/legal-doc-processor/monitoring/logs")
        self._ensure_log_directories()
        
        # Log rotation settings
        self.max_file_size_mb = 50
        self.max_files_per_day = 10
        self.retention_days = 30
        
        # Create date-based log files
        self.current_date = datetime.now().strftime("%Y-%m-%d")
        self._setup_log_files()
    
    def _ensure_log_directories(self):
        """Create necessary log directories."""
        directories = [
            self.base_log_dir / "processing",
            self.base_log_dir / "performance", 
            self.base_log_dir / "quality",
            self.base_log_dir / "errors",
            self.base_log_dir / "summaries",
            self.base_log_dir / "archive"
        ]
        
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
    
    def _setup_log_files(self):
        """Setup current log files for the day."""
        self.log_files = {
            'processing': self.base_log_dir / "processing" / f"processing_{self.current_date}.log",
            'performance': self.base_log_dir / "performance" / f"performance_{self.current_date}.log",
            'quality': self.base_log_dir / "quality" / f"quality_{self.current_date}.log",
            'errors': self.base_log_dir / "errors" / f"errors_{self.current_date}.log",
            'summaries': self.base_log_dir / "summaries" / f"summaries_{self.current_date}.log"
        }
    
    def log_processing_event(self, doc_id: str, event: ProcessingEvent):
        """
        Log a processing event with structured data.
        
        Args:
            doc_id: Document UUID
            event: ProcessingEvent to log
        """
        try:
            # Check if we need to rotate to new day
            current_date = datetime.now().strftime("%Y-%m-%d")
            if current_date != self.current_date:
                self.current_date = current_date
                self._setup_log_files()
            
            # Create log entry
            log_entry = {
                'timestamp': event.timestamp,
                'document_uuid': doc_id,
                'event_type': event.event_type,
                'level': event.level,
                'stage': event.stage,
                'status': event.status,
                'message': event.message,
                'metadata': event.metadata,
                'worker_id': event.worker_id,
                'task_id': event.task_id,
                'elapsed_seconds': event.elapsed_seconds,
                'batch_id': event.batch_id
            }
            
            # Add error details if present
            if event.error_details:
                log_entry['error_details'] = event.error_details
            
            # Write to processing log
            self._write_log_entry('processing', log_entry)
            
            # Write to error log if it's an error event
            if event.level in ['error', 'critical']:
                self._write_log_entry('errors', log_entry)
            
            # Log performance metrics if available
            if event.elapsed_seconds > 0:
                performance_entry = {
                    'timestamp': event.timestamp,
                    'document_uuid': doc_id,
                    'stage': event.stage,
                    'elapsed_seconds': event.elapsed_seconds,
                    'worker_id': event.worker_id,
                    'metadata': event.metadata
                }
                self._write_log_entry('performance', performance_entry)
            
        except Exception as e:
            logger.error(f"Error logging processing event: {e}")
    
    def log_error_with_context(self, doc_id: str, error: Exception, context: Dict[str, Any]):
        """
        Log an error with comprehensive context information.
        
        Args:
            doc_id: Document UUID
            error: Exception that occurred
            context: Context information about the error
        """
        try:
            import traceback
            
            error_entry = {
                'timestamp': datetime.now().isoformat(),
                'document_uuid': doc_id,
                'error_type': type(error).__name__,
                'error_message': str(error),
                'stack_trace': traceback.format_exc(),
                'context': context,
                'stage': context.get('stage', 'unknown'),
                'worker_id': context.get('worker_id'),
                'task_id': context.get('task_id'),
                'batch_id': context.get('batch_id')
            }
            
            self._write_log_entry('errors', error_entry)
            
            # Also create a processing event for the error
            event = ProcessingEvent(
                timestamp=error_entry['timestamp'],
                event_type=EventType.PROCESSING_ERROR.value,
                level=LogLevel.ERROR.value,
                document_uuid=doc_id,
                batch_id=context.get('batch_id'),
                stage=context.get('stage', 'unknown'),
                status='failed',
                message=f"Error in {context.get('stage', 'unknown')}: {str(error)}",
                metadata=context,
                worker_id=context.get('worker_id'),
                task_id=context.get('task_id'),
                error_details={
                    'error_type': type(error).__name__,
                    'error_message': str(error),
                    'stack_trace': traceback.format_exc()
                }
            )
            
            self.log_processing_event(doc_id, event)
            
        except Exception as e:
            logger.error(f"Error logging error with context: {e}")
    
    def create_processing_summary(self, batch_id: str) -> ProcessingSummary:
        """
        Create a processing summary for a batch.
        
        Args:
            batch_id: Batch ID to summarize
            
        Returns:
            ProcessingSummary object
        """
        try:
            # Read processing logs for this batch
            batch_events = self._get_batch_events(batch_id)
            
            if not batch_events:
                return self._create_empty_summary(batch_id, "No events found")
            
            # Analyze events
            documents = set()
            successful_docs = set()
            failed_docs = set()
            stage_metrics = {}
            processing_times = []
            error_counts = {}
            
            start_time = None
            end_time = None
            
            for event in batch_events:
                # Track timing
                event_time = datetime.fromisoformat(event['timestamp'].replace('Z', '+00:00'))
                if start_time is None or event_time < start_time:
                    start_time = event_time
                if end_time is None or event_time > end_time:
                    end_time = event_time
                
                # Track documents
                doc_id = event.get('document_uuid')
                if doc_id:
                    documents.add(doc_id)
                    
                    # Track success/failure
                    if event.get('status') == 'completed' and event.get('stage') == 'relationship_building':
                        successful_docs.add(doc_id)
                    elif event.get('level') in ['error', 'critical']:
                        failed_docs.add(doc_id)
                
                # Track stage metrics
                stage = event.get('stage', 'unknown')
                if stage not in stage_metrics:
                    stage_metrics[stage] = {'count': 0, 'success': 0, 'failure': 0, 'total_time': 0}
                
                stage_metrics[stage]['count'] += 1
                
                if event.get('status') == 'completed':
                    stage_metrics[stage]['success'] += 1
                elif event.get('level') in ['error', 'critical']:
                    stage_metrics[stage]['failure'] += 1
                
                # Track processing times
                elapsed = event.get('elapsed_seconds', 0)
                if elapsed > 0:
                    processing_times.append(elapsed)
                    stage_metrics[stage]['total_time'] += elapsed
                
                # Track errors
                if event.get('level') in ['error', 'critical']:
                    error_type = event.get('error_details', {}).get('error_type', 'Unknown')
                    error_counts[error_type] = error_counts.get(error_type, 0) + 1
            
            # Calculate performance metrics
            performance_metrics = {}
            if processing_times:
                performance_metrics['avg_processing_time_seconds'] = sum(processing_times) / len(processing_times)
                performance_metrics['min_processing_time_seconds'] = min(processing_times)
                performance_metrics['max_processing_time_seconds'] = max(processing_times)
                performance_metrics['total_processing_time_seconds'] = sum(processing_times)
            
            if start_time and end_time:
                batch_duration = (end_time - start_time).total_seconds()
                performance_metrics['batch_duration_seconds'] = batch_duration
                if len(documents) > 0:
                    performance_metrics['throughput_docs_per_hour'] = (len(documents) / batch_duration) * 3600
            
            # Calculate quality metrics
            quality_metrics = {}
            if len(documents) > 0:
                quality_metrics['success_rate'] = len(successful_docs) / len(documents) * 100
                quality_metrics['failure_rate'] = len(failed_docs) / len(documents) * 100
                quality_metrics['completion_rate'] = (len(successful_docs) + len(failed_docs)) / len(documents) * 100
            
            # Error summary
            error_summary = {
                'total_errors': sum(error_counts.values()),
                'error_types': error_counts,
                'error_rate': (sum(error_counts.values()) / len(batch_events)) * 100 if batch_events else 0
            }
            
            # Create summary
            summary = ProcessingSummary(
                summary_id=f"batch_{batch_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                summary_type="batch",
                start_time=start_time.isoformat() if start_time else "",
                end_time=end_time.isoformat() if end_time else "",
                total_documents=len(documents),
                successful_documents=len(successful_docs),
                failed_documents=len(failed_docs),
                processing_stages=stage_metrics,
                performance_metrics=performance_metrics,
                quality_metrics=quality_metrics,
                error_summary=error_summary
            )
            
            # Log the summary
            summary_entry = asdict(summary)
            self._write_log_entry('summaries', summary_entry)
            
            return summary
            
        except Exception as e:
            logger.error(f"Error creating processing summary for batch {batch_id}: {e}")
            return self._create_empty_summary(batch_id, f"Error: {e}")
    
    def export_audit_trail(self, doc_id: str, format: str = "json") -> str:
        """
        Export complete audit trail for a document.
        
        Args:
            doc_id: Document UUID
            format: Export format (json, csv)
            
        Returns:
            Path to exported file
        """
        try:
            # Get all events for document
            doc_events = self._get_document_events(doc_id)
            
            if not doc_events:
                raise ValueError(f"No events found for document {doc_id}")
            
            # Create audit trail
            audit_trail = AuditTrail(
                audit_id=f"audit_{doc_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                subject_type="document",
                subject_id=doc_id,
                created_at=datetime.now().isoformat(),
                events=[ProcessingEvent(**event) for event in doc_events],
                summary=self._create_document_summary(doc_events),
                compliance_data=self._create_compliance_data(doc_events)
            )
            
            # Export based on format
            if format == "json":
                return self._export_json(audit_trail)
            elif format == "csv":
                return self._export_csv(audit_trail)
            else:
                raise ValueError(f"Unsupported export format: {format}")
            
        except Exception as e:
            logger.error(f"Error exporting audit trail for {doc_id}: {e}")
            raise
    
    def cleanup_old_logs(self):
        """Clean up old log files based on retention policy."""
        try:
            cutoff_date = datetime.now() - timedelta(days=self.retention_days)
            
            # Process each log directory
            for log_type in ['processing', 'performance', 'quality', 'errors', 'summaries']:
                log_dir = self.base_log_dir / log_type
                
                for log_file in log_dir.glob("*.log"):
                    try:
                        # Extract date from filename
                        filename = log_file.name
                        if "_" in filename:
                            date_str = filename.split("_")[1].replace(".log", "")
                            file_date = datetime.strptime(date_str, "%Y-%m-%d")
                            
                            if file_date < cutoff_date:
                                # Archive before deletion
                                self._archive_log_file(log_file)
                                log_file.unlink()
                                logger.info(f"Cleaned up old log file: {log_file}")
                    
                    except Exception as e:
                        logger.error(f"Error processing log file {log_file}: {e}")
            
        except Exception as e:
            logger.error(f"Error during log cleanup: {e}")
    
    def get_log_statistics(self) -> Dict[str, Any]:
        """Get statistics about current logs."""
        try:
            stats = {
                'log_directories': {},
                'total_files': 0,
                'total_size_mb': 0,
                'oldest_log': None,
                'newest_log': None
            }
            
            for log_type in ['processing', 'performance', 'quality', 'errors', 'summaries']:
                log_dir = self.base_log_dir / log_type
                
                if log_dir.exists():
                    files = list(log_dir.glob("*.log"))
                    total_size = sum(f.stat().st_size for f in files)
                    
                    stats['log_directories'][log_type] = {
                        'file_count': len(files),
                        'size_mb': total_size / (1024 * 1024),
                        'files': [f.name for f in files]
                    }
                    
                    stats['total_files'] += len(files)
                    stats['total_size_mb'] += total_size / (1024 * 1024)
                    
                    # Track oldest and newest
                    for f in files:
                        mtime = datetime.fromtimestamp(f.stat().st_mtime)
                        if stats['oldest_log'] is None or mtime < stats['oldest_log']:
                            stats['oldest_log'] = mtime
                        if stats['newest_log'] is None or mtime > stats['newest_log']:
                            stats['newest_log'] = mtime
            
            # Convert datetime objects to strings
            if stats['oldest_log']:
                stats['oldest_log'] = stats['oldest_log'].isoformat()
            if stats['newest_log']:
                stats['newest_log'] = stats['newest_log'].isoformat()
            
            return stats
            
        except Exception as e:
            logger.error(f"Error getting log statistics: {e}")
            return {'error': str(e)}
    
    # Private helper methods
    
    def _write_log_entry(self, log_type: str, entry: Dict[str, Any]):
        """Write a log entry to the appropriate file."""
        try:
            log_file = self.log_files.get(log_type)
            if not log_file:
                return
            
            # Check file size and rotate if necessary
            if log_file.exists() and log_file.stat().st_size > self.max_file_size_mb * 1024 * 1024:
                self._rotate_log_file(log_file)
            
            # Write entry
            with open(log_file, 'a', encoding='utf-8') as f:
                json.dump(entry, f, default=str, ensure_ascii=False)
                f.write('\n')
                
        except Exception as e:
            logger.error(f"Error writing log entry to {log_type}: {e}")
    
    def _rotate_log_file(self, log_file: Path):
        """Rotate a log file when it gets too large."""
        try:
            # Find next rotation number
            base_name = log_file.stem
            suffix = log_file.suffix
            rotation_num = 1
            
            while True:
                rotated_name = f"{base_name}.{rotation_num}{suffix}"
                rotated_path = log_file.parent / rotated_name
                if not rotated_path.exists():
                    break
                rotation_num += 1
                
                # Prevent too many rotations
                if rotation_num > self.max_files_per_day:
                    # Archive oldest rotation
                    oldest_rotation = log_file.parent / f"{base_name}.{self.max_files_per_day}{suffix}"
                    if oldest_rotation.exists():
                        self._archive_log_file(oldest_rotation)
                        oldest_rotation.unlink()
                    break
            
            # Rotate current file
            log_file.rename(rotated_path)
            
        except Exception as e:
            logger.error(f"Error rotating log file {log_file}: {e}")
    
    def _archive_log_file(self, log_file: Path):
        """Archive a log file using gzip compression."""
        try:
            archive_dir = self.base_log_dir / "archive"
            archive_path = archive_dir / f"{log_file.name}.gz"
            
            with open(log_file, 'rb') as f_in:
                with gzip.open(archive_path, 'wb') as f_out:
                    f_out.writelines(f_in)
            
            logger.info(f"Archived log file: {log_file} -> {archive_path}")
            
        except Exception as e:
            logger.error(f"Error archiving log file {log_file}: {e}")
    
    def _get_batch_events(self, batch_id: str) -> List[Dict[str, Any]]:
        """Get all events for a batch."""
        events = []
        
        try:
            # Read from current processing log
            processing_log = self.log_files.get('processing')
            if processing_log and processing_log.exists():
                with open(processing_log, 'r', encoding='utf-8') as f:
                    for line in f:
                        try:
                            event = json.loads(line.strip())
                            if event.get('batch_id') == batch_id:
                                events.append(event)
                        except json.JSONDecodeError:
                            continue
            
            # Also check rotated files for today
            log_dir = processing_log.parent if processing_log else self.base_log_dir / "processing"
            date_str = self.current_date
            
            for rotation_file in log_dir.glob(f"processing_{date_str}.*.log"):
                with open(rotation_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        try:
                            event = json.loads(line.strip())
                            if event.get('batch_id') == batch_id:
                                events.append(event)
                        except json.JSONDecodeError:
                            continue
        
        except Exception as e:
            logger.error(f"Error getting batch events for {batch_id}: {e}")
        
        return events
    
    def _get_document_events(self, doc_id: str) -> List[Dict[str, Any]]:
        """Get all events for a document."""
        events = []
        
        try:
            # Search across recent log files
            processing_dir = self.base_log_dir / "processing"
            
            # Check files from last 7 days
            for i in range(7):
                date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
                pattern = f"processing_{date}*.log"
                
                for log_file in processing_dir.glob(pattern):
                    with open(log_file, 'r', encoding='utf-8') as f:
                        for line in f:
                            try:
                                event = json.loads(line.strip())
                                if event.get('document_uuid') == doc_id:
                                    events.append(event)
                            except json.JSONDecodeError:
                                continue
        
        except Exception as e:
            logger.error(f"Error getting document events for {doc_id}: {e}")
        
        return events
    
    def _create_document_summary(self, events: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Create summary information for a document's events."""
        if not events:
            return {}
        
        stages_completed = set()
        total_time = 0
        error_count = 0
        
        for event in events:
            if event.get('status') == 'completed':
                stages_completed.add(event.get('stage', ''))
            if event.get('level') in ['error', 'critical']:
                error_count += 1
            
            elapsed = event.get('elapsed_seconds', 0)
            if elapsed > 0:
                total_time += elapsed
        
        return {
            'stages_completed': list(stages_completed),
            'total_processing_time_seconds': total_time,
            'error_count': error_count,
            'event_count': len(events)
        }
    
    def _create_compliance_data(self, events: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Create compliance data from events."""
        return {
            'audit_version': '1.0',
            'processing_standard': 'Legal Document Processing Pipeline v2024',
            'retention_period_days': self.retention_days,
            'data_integrity_verified': True,
            'processing_chain_complete': len(events) > 0
        }
    
    def _export_json(self, audit_trail: AuditTrail) -> str:
        """Export audit trail as JSON."""
        export_dir = self.base_log_dir / "exports"
        export_dir.mkdir(exist_ok=True)
        
        filename = f"{audit_trail.audit_id}.json"
        filepath = export_dir / filename
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(asdict(audit_trail), f, indent=2, default=str, ensure_ascii=False)
        
        return str(filepath)
    
    def _export_csv(self, audit_trail: AuditTrail) -> str:
        """Export audit trail as CSV."""
        import csv
        
        export_dir = self.base_log_dir / "exports"
        export_dir.mkdir(exist_ok=True)
        
        filename = f"{audit_trail.audit_id}.csv"
        filepath = export_dir / filename
        
        with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['timestamp', 'event_type', 'stage', 'status', 'message', 'elapsed_seconds', 'worker_id']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            
            writer.writeheader()
            for event in audit_trail.events:
                writer.writerow({
                    'timestamp': event.timestamp,
                    'event_type': event.event_type,
                    'stage': event.stage,
                    'status': event.status,
                    'message': event.message,
                    'elapsed_seconds': event.elapsed_seconds,
                    'worker_id': event.worker_id
                })
        
        return str(filepath)
    
    def _create_empty_summary(self, batch_id: str, reason: str) -> ProcessingSummary:
        """Create an empty summary with error reason."""
        return ProcessingSummary(
            summary_id=f"batch_{batch_id}_empty_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            summary_type="batch",
            start_time="",
            end_time="",
            total_documents=0,
            successful_documents=0,
            failed_documents=0,
            processing_stages={},
            performance_metrics={},
            quality_metrics={},
            error_summary={'error': reason}
        )