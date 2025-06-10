#!/usr/bin/env python3
"""
Monitor full pipeline processing of a document with detailed output capture.
Tracks all stages, Redis cache usage, and task transitions.
"""
import os
import sys
import time
import json
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

# Add scripts directory to path
sys.path.append(os.path.join(os.path.dirname(__file__), 'scripts'))

from scripts.cache import get_redis_manager, CacheKeys
from scripts.db import DatabaseManager
from scripts.models import (
    SourceDocumentMinimal, DocumentChunkMinimal, 
    EntityMentionMinimal, CanonicalEntityMinimal
)
from scripts.celery_app import app
from scripts.s3_storage import S3StorageManager
from scripts.intake_service import create_document_with_validation
from scripts.pdf_tasks import extract_text_from_document
from scripts.config import REDIS_ACCELERATION_ENABLED

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(name)s] - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class PipelineMonitor:
    def __init__(self):
        self.db = DatabaseManager()
        self.redis_manager = get_redis_manager()
        self.s3_manager = S3StorageManager()
        self.start_time = datetime.now()
        self.events = []
        self.errors = []
        self.cache_stats = {
            'hits': 0,
            'misses': 0,
            'writes': 0
        }
        
    def log_event(self, stage: str, event: str, details: Dict[str, Any] = None):
        """Log a pipeline event."""
        timestamp = datetime.now()
        elapsed = (timestamp - self.start_time).total_seconds()
        
        event_data = {
            'timestamp': timestamp.isoformat(),
            'elapsed_seconds': elapsed,
            'stage': stage,
            'event': event,
            'details': details or {}
        }
        
        self.events.append(event_data)
        logger.info(f"[{elapsed:.2f}s] {stage}: {event}")
        
        if details:
            for key, value in details.items():
                logger.info(f"  - {key}: {value}")
                
    def log_error(self, stage: str, error: str, exception: Exception = None):
        """Log an error."""
        error_data = {
            'timestamp': datetime.now().isoformat(),
            'stage': stage,
            'error': error,
            'exception': str(exception) if exception else None,
            'traceback': None
        }
        
        if exception:
            import traceback
            error_data['traceback'] = traceback.format_exc()
            
        self.errors.append(error_data)
        logger.error(f"ERROR in {stage}: {error}")
        
        if exception:
            logger.error(f"  Exception: {exception}")
            
    def check_redis_cache(self, document_uuid: str) -> Dict[str, bool]:
        """Check all cache keys for a document."""
        cache_keys = {
            'OCR': CacheKeys.DOC_OCR_RESULT,
            'Chunks': CacheKeys.DOC_CHUNKS,
            'Entities': CacheKeys.DOC_ALL_EXTRACTED_MENTIONS,
            'Canonical': CacheKeys.DOC_CANONICAL_ENTITIES,
            'Resolved': CacheKeys.DOC_RESOLVED_MENTIONS,
            'State': CacheKeys.DOC_STATE
        }
        
        results = {}
        for name, key_template in cache_keys.items():
            key = CacheKeys.format_key(key_template, document_uuid=document_uuid)
            exists = self.redis_manager.exists(key)
            results[name] = exists
            
            if exists:
                self.cache_stats['hits'] += 1
            else:
                self.cache_stats['misses'] += 1
                
        return results
        
    def check_database_state(self, document_uuid: str) -> Dict[str, Any]:
        """Check database state for a document."""
        session = next(self.db.get_session())
        try:
            # Get document using raw SQL to avoid model issues
            from sqlalchemy import text
            result = session.execute(text("""
                SELECT status, raw_extracted_text 
                FROM source_documents 
                WHERE document_uuid = :uuid
            """), {'uuid': document_uuid})
            
            row = result.fetchone()
            if not row:
                return {'error': 'Document not found'}
                
            doc_status, raw_text = row[0], row[1]
            
            # Get counts using raw SQL
            chunks_result = session.execute(text("""
                SELECT COUNT(*) FROM document_chunks 
                WHERE document_uuid = :uuid
            """), {'uuid': document_uuid})
            chunks_count = chunks_result.scalar()
            
            entities_result = session.execute(text("""
                SELECT COUNT(*) FROM entity_mentions 
                WHERE document_uuid = :uuid
            """), {'uuid': document_uuid})
            entities_count = entities_result.scalar()
            
            # Count canonical entities that have mentions in this document
            canonical_result = session.execute(text("""
                SELECT COUNT(DISTINCT canonical_entity_uuid) 
                FROM entity_mentions 
                WHERE document_uuid = :uuid AND canonical_entity_uuid IS NOT NULL
            """), {'uuid': document_uuid})
            canonical_count = canonical_result.scalar()
            
            return {
                'status': doc_status,
                'has_ocr_text': bool(raw_text),
                'text_length': len(raw_text) if raw_text else 0,
                'chunks_count': chunks_count,
                'entities_count': entities_count,
                'canonical_count': canonical_count
            }
        finally:
            session.close()
            
    def monitor_task(self, task_id: str, timeout: int = 300) -> Dict[str, Any]:
        """Monitor a Celery task until completion."""
        task = app.AsyncResult(task_id)
        start = time.time()
        last_state = None
        
        while time.time() - start < timeout:
            current_state = task.state
            
            if current_state != last_state:
                self.log_event("Task Monitor", f"Task state changed to: {current_state}", {
                    'task_id': task_id,
                    'state': current_state
                })
                last_state = current_state
                
            if task.ready():
                if task.successful():
                    return {
                        'status': 'success',
                        'result': task.result,
                        'duration': time.time() - start
                    }
                else:
                    return {
                        'status': 'failed',
                        'error': str(task.info),
                        'duration': time.time() - start
                    }
                    
            time.sleep(2)
            
        return {
            'status': 'timeout',
            'duration': timeout
        }
        
    def process_document(self, file_path: str) -> str:
        """Process a document through the full pipeline."""
        filename = os.path.basename(file_path)
        
        self.log_event("Pipeline Start", f"Processing document: {filename}", {
            'file_path': file_path,
            'file_size': os.path.getsize(file_path),
            'redis_acceleration': REDIS_ACCELERATION_ENABLED
        })
        
        try:
            # 1. Create project
            session = next(self.db.get_session())
            try:
                from sqlalchemy import text
                result = session.execute(text("""
                    INSERT INTO projects (name, active)
                    VALUES (:name, true)
                    RETURNING id, project_id
                """), {'name': f'PIPELINE_TEST_{datetime.now().strftime("%Y%m%d_%H%M%S")}'})
                
                row = result.fetchone()
                id_value, project_uuid = row[0], row[1]
                project_id = id_value  # Use the integer ID for the foreign key
                session.commit()
                
                self.log_event("Project Creation", "Project created successfully", {
                    'project_id': project_id,
                    'project_uuid': str(project_uuid)
                })
            except Exception as e:
                session.rollback()
                self.log_error("Project Creation", "Failed to create project", e)
                raise
            finally:
                session.close()
                
            # 2. Upload to S3
            self.log_event("S3 Upload", "Starting S3 upload")
            try:
                # Generate document UUID
                import uuid
                document_uuid = str(uuid.uuid4())
                
                result = self.s3_manager.upload_document_with_uuid_naming(
                    local_file_path=file_path,
                    document_uuid=document_uuid,
                    original_filename=filename
                )
                
                # Get S3 details from result or config
                from scripts.config import S3_PRIMARY_DOCUMENT_BUCKET
                s3_bucket = S3_PRIMARY_DOCUMENT_BUCKET
                s3_key = f"documents/{document_uuid}.pdf"
                
                self.log_event("S3 Upload", "Upload completed", {
                    'document_uuid': document_uuid,
                    's3_bucket': s3_bucket,
                    's3_key': s3_key,
                    'file_size': result.get('file_size', 0)
                })
            except Exception as e:
                self.log_error("S3 Upload", "Failed to upload to S3", e)
                raise
                
            # 3. Create document record
            self.log_event("Database", "Creating document record")
            try:
                result = create_document_with_validation(
                    document_uuid=document_uuid,
                    filename=filename,
                    s3_bucket=s3_bucket,
                    s3_key=s3_key,
                    project_id=project_id
                )
                
                doc_id = result.get('document_id')
                
                self.log_event("Database", "Document record created", {
                    'document_id': doc_id,
                    'document_uuid': document_uuid
                })
            except Exception as e:
                self.log_error("Database", "Failed to create document record", e)
                raise
                
            # 4. Check initial cache state
            initial_cache = self.check_redis_cache(document_uuid)
            self.log_event("Redis Cache", "Initial cache state", initial_cache)
            
            # 5. Submit OCR task
            self.log_event("OCR", "Submitting OCR task to Celery")
            s3_url = f"s3://{s3_bucket}/{s3_key}"
            
            try:
                task = extract_text_from_document.apply_async(
                    args=[document_uuid, s3_url]
                )
                
                self.log_event("OCR", "Task submitted", {
                    'task_id': task.id,
                    'queue': 'ocr'
                })
            except Exception as e:
                self.log_error("OCR", "Failed to submit OCR task", e)
                raise
                
            # 6. Monitor processing stages
            self.log_event("Monitoring", "Starting pipeline monitoring")
            
            # Track cache changes
            last_cache_state = initial_cache.copy()
            processing_complete = False
            stage_times = {}
            
            start_monitor = time.time()
            while time.time() - start_monitor < 300 and not processing_complete:  # 5 minute timeout
                # Check cache state
                current_cache = self.check_redis_cache(document_uuid)
                
                # Map of cache key names to CacheKeys attributes
                cache_key_mapping = {
                    'OCR': CacheKeys.DOC_OCR_RESULT,
                    'Chunks': CacheKeys.DOC_CHUNKS,
                    'Entities': CacheKeys.DOC_ALL_EXTRACTED_MENTIONS,
                    'Canonical': CacheKeys.DOC_CANONICAL_ENTITIES,
                    'Resolved': CacheKeys.DOC_RESOLVED_MENTIONS,
                    'State': CacheKeys.DOC_STATE
                }
                
                # Detect cache changes
                for key, cached in current_cache.items():
                    if cached and not last_cache_state.get(key):
                        stage_time = time.time() - start_monitor
                        stage_times[key] = stage_time
                        self.cache_stats['writes'] += 1
                        
                        self.log_event("Cache Update", f"{key} cached", {
                            'elapsed': f"{stage_time:.2f}s",
                            'cache_key': CacheKeys.format_key(
                                cache_key_mapping[key], 
                                document_uuid=document_uuid
                            )
                        })
                        
                        # Get cached data sample
                        if key == 'OCR':
                            ocr_data = self.redis_manager.get_cached(
                                CacheKeys.format_key(CacheKeys.DOC_OCR_RESULT, document_uuid=document_uuid)
                            )
                            if isinstance(ocr_data, dict):
                                self.log_event("OCR Result", "OCR data cached", {
                                    'status': ocr_data.get('status'),
                                    'text_length': len(ocr_data.get('text', '')),
                                    'method': ocr_data.get('method')
                                })
                                
                last_cache_state = current_cache
                
                # Check database state
                db_state = self.check_database_state(document_uuid)
                
                # Check if processing is complete
                if (db_state.get('status') == 'completed' or 
                    all(current_cache.values())):  # All stages cached
                    processing_complete = True
                    self.log_event("Pipeline Complete", "All stages completed", {
                        'total_time': f"{time.time() - start_monitor:.2f}s",
                        'final_status': db_state.get('status'),
                        'chunks': db_state.get('chunks_count'),
                        'entities': db_state.get('entities_count'),
                        'canonical_entities': db_state.get('canonical_count')
                    })
                    
                time.sleep(2)
                
            # 7. Final state check
            final_cache = self.check_redis_cache(document_uuid)
            final_db = self.check_database_state(document_uuid)
            
            self.log_event("Final State", "Processing complete", {
                'cache_state': final_cache,
                'database_state': final_db,
                'stage_times': stage_times,
                'cache_stats': self.cache_stats
            })
            
            return document_uuid
            
        except Exception as e:
            self.log_error("Pipeline", "Fatal error during processing", e)
            raise
            
    def generate_report(self, document_uuid: str):
        """Generate a detailed report of the processing."""
        report = {
            'summary': {
                'document_uuid': document_uuid,
                'start_time': self.start_time.isoformat(),
                'total_duration': (datetime.now() - self.start_time).total_seconds(),
                'total_events': len(self.events),
                'total_errors': len(self.errors),
                'redis_acceleration': REDIS_ACCELERATION_ENABLED,
                'cache_stats': self.cache_stats
            },
            'events': self.events,
            'errors': self.errors
        }
        
        # Save report
        report_file = f"pipeline_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_file, 'w') as f:
            json.dump(report, f, indent=2)
            
        logger.info(f"\nReport saved to: {report_file}")
        
        # Print summary
        print(f"\n{'='*60}")
        print("PIPELINE PROCESSING SUMMARY")
        print(f"{'='*60}")
        print(f"Document UUID: {document_uuid}")
        print(f"Total Duration: {report['summary']['total_duration']:.2f} seconds")
        print(f"Total Events: {report['summary']['total_events']}")
        print(f"Total Errors: {report['summary']['total_errors']}")
        print(f"\nCache Statistics:")
        print(f"  - Hits: {self.cache_stats['hits']}")
        print(f"  - Misses: {self.cache_stats['misses']}")
        print(f"  - Writes: {self.cache_stats['writes']}")
        
        if self.cache_stats['hits'] + self.cache_stats['misses'] > 0:
            hit_rate = self.cache_stats['hits'] / (self.cache_stats['hits'] + self.cache_stats['misses']) * 100
            print(f"  - Hit Rate: {hit_rate:.1f}%")
            
        print(f"{'='*60}\n")


def main():
    """Main function."""
    # Use the Paul Michael document
    test_file = "input_docs/Paul, Michael (Acuity)/Paul, Michael - Lora Prop Disclosure Stmt 10-21-24.pdf"
    
    if not os.path.exists(test_file):
        logger.error(f"Test file not found: {test_file}")
        sys.exit(1)
        
    # Create monitor
    monitor = PipelineMonitor()
    
    try:
        # Process document
        document_uuid = monitor.process_document(test_file)
        
        # Generate report
        monitor.generate_report(document_uuid)
        
    except Exception as e:
        logger.error(f"Pipeline failed: {e}")
        monitor.generate_report("FAILED")
        sys.exit(1)


if __name__ == "__main__":
    main()