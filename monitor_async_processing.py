#!/usr/bin/env python3
"""
Monitor async processing stages for a document with detailed tracking
"""

import os
import sys
sys.path.insert(0, '/opt/legal-doc-processor')

import time
import json
from datetime import datetime
from sqlalchemy import text

# Set up environment
os.environ['FORCE_PROCESSING'] = 'true'
os.environ['SKIP_PDF_PREPROCESSING'] = 'true'
os.environ['VALIDATION_REDIS_METADATA_LEVEL'] = 'optional'

from scripts.db import DatabaseManager
from scripts.cache import get_redis_manager

class AsyncProcessingMonitor:
    def __init__(self, document_uuid):
        self.document_uuid = document_uuid
        self.db = DatabaseManager(validate_conformance=False)
        self.redis = get_redis_manager()
        self.monitoring_data = {
            'document_uuid': document_uuid,
            'start_time': datetime.now().isoformat(),
            'stages': []
        }
        
    def log_stage(self, stage_name, status, details=None):
        """Log a processing stage"""
        entry = {
            'timestamp': datetime.now().isoformat(),
            'stage': stage_name,
            'status': status,
            'details': details or {}
        }
        self.monitoring_data['stages'].append(entry)
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] {stage_name}: {status}")
        if details:
            for key, value in details.items():
                print(f"  {key}: {value}")
    
    def check_document_status(self):
        """Check current document status"""
        session = next(self.db.get_session())
        try:
            result = session.execute(text("""
                SELECT 
                    status,
                    celery_status,
                    error_message,
                    textract_job_id,
                    textract_job_status,
                    raw_extracted_text IS NOT NULL as has_text,
                    updated_at
                FROM source_documents
                WHERE document_uuid = :doc_uuid
            """), {'doc_uuid': self.document_uuid})
            
            return result.fetchone()
        finally:
            session.close()
    
    def check_processing_tasks(self):
        """Check processing tasks"""
        session = next(self.db.get_session())
        try:
            # First check what columns exist
            col_check = session.execute(text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'processing_tasks'
                AND column_name IN ('stage', 'task_type', 'task_name')
            """))
            
            columns = [row.column_name for row in col_check]
            
            # Use appropriate column
            task_column = 'stage' if 'stage' in columns else 'task_type' if 'task_type' in columns else 'task_name'
            
            result = session.execute(text(f"""
                SELECT 
                    {task_column} as task_stage,
                    status,
                    celery_task_id,
                    error_message,
                    created_at,
                    completed_at
                FROM processing_tasks
                WHERE document_uuid = :doc_uuid
                ORDER BY created_at DESC
            """), {'doc_uuid': self.document_uuid})
            
            return list(result)
        finally:
            session.close()
    
    def check_textract_job(self):
        """Check Textract job status"""
        session = next(self.db.get_session())
        try:
            result = session.execute(text("""
                SELECT 
                    job_id,
                    status,
                    page_count,
                    result_text IS NOT NULL as has_result,
                    error_message,
                    created_at,
                    updated_at
                FROM textract_jobs
                WHERE document_uuid = :doc_uuid
                ORDER BY created_at DESC
                LIMIT 1
            """), {'doc_uuid': self.document_uuid})
            
            return result.fetchone()
        finally:
            session.close()
    
    def check_chunks(self):
        """Check document chunks"""
        session = next(self.db.get_session())
        try:
            result = session.execute(text("""
                SELECT 
                    COUNT(*) as count,
                    MIN(chunk_index) as min_index,
                    MAX(chunk_index) as max_index,
                    SUM(LENGTH(text)) as total_chars,
                    AVG(LENGTH(text)) as avg_chars
                FROM document_chunks
                WHERE document_uuid = :doc_uuid
            """), {'doc_uuid': self.document_uuid})
            
            return result.fetchone()
        finally:
            session.close()
    
    def check_entities(self):
        """Check entity mentions"""
        session = next(self.db.get_session())
        try:
            result = session.execute(text("""
                SELECT 
                    COUNT(*) as total_mentions,
                    COUNT(DISTINCT entity_type) as entity_types,
                    COUNT(DISTINCT canonical_entity_uuid) as canonical_count,
                    STRING_AGG(DISTINCT entity_type, ', ') as types_list
                FROM entity_mentions
                WHERE document_uuid = :doc_uuid
            """), {'doc_uuid': self.document_uuid})
            
            return result.fetchone()
        finally:
            session.close()
    
    def check_relationships(self):
        """Check relationships"""
        session = next(self.db.get_session())
        try:
            result = session.execute(text("""
                SELECT 
                    COUNT(*) as count,
                    COUNT(DISTINCT relationship_type) as rel_types,
                    STRING_AGG(DISTINCT relationship_type, ', ') as types_list
                FROM relationship_staging rs
                JOIN document_chunks dc ON rs.source_chunk_uuid = dc.chunk_uuid
                WHERE dc.document_uuid = :doc_uuid
            """), {'doc_uuid': self.document_uuid})
            
            return result.fetchone()
        finally:
            session.close()
    
    def check_redis_state(self):
        """Check Redis pipeline state"""
        try:
            state_key = f"doc:state:{self.document_uuid}"
            state_data = self.redis.get(state_key)
            if state_data:
                return json.loads(state_data)
            return None
        except:
            return None
    
    def monitor_continuously(self, max_duration=600):
        """Monitor processing for up to max_duration seconds"""
        start_time = time.time()
        last_status = None
        iterations = 0
        
        print(f"Starting async monitoring for document: {self.document_uuid}")
        print("="*70)
        
        while time.time() - start_time < max_duration:
            iterations += 1
            print(f"\n--- Check #{iterations} at {datetime.now().strftime('%H:%M:%S')} ---")
            
            # Check document status
            doc_status = self.check_document_status()
            if doc_status:
                status_changed = doc_status.celery_status != last_status
                last_status = doc_status.celery_status
                
                self.log_stage("Document Status", doc_status.celery_status or doc_status.status, {
                    'status': doc_status.status,
                    'celery_status': doc_status.celery_status,
                    'has_text': doc_status.has_text,
                    'textract_status': doc_status.textract_job_status,
                    'error': doc_status.error_message[:100] if doc_status.error_message else None
                })
                
                if status_changed and doc_status.error_message:
                    print(f"\n⚠️  ERROR DETECTED: {doc_status.error_message}")
            
            # Check processing tasks
            tasks = self.check_processing_tasks()
            if tasks:
                self.log_stage("Processing Tasks", f"{len(tasks)} tasks found", {
                    'latest_task': f"{tasks[0].task_stage} - {tasks[0].status}" if tasks else None,
                    'task_count': len(tasks)
                })
                
                # Show recent tasks
                print("\nRecent tasks:")
                for task in tasks[:5]:
                    print(f"  - {task.task_stage}: {task.status}")
                    if task.error_message:
                        print(f"    ERROR: {task.error_message[:80]}")
            
            # Check Textract job
            textract_job = self.check_textract_job()
            if textract_job:
                self.log_stage("Textract Job", textract_job.status, {
                    'job_id': textract_job.job_id[:30] + "...",
                    'page_count': textract_job.page_count,
                    'has_result': textract_job.has_result,
                    'error': textract_job.error_message
                })
            
            # Check chunks
            chunks = self.check_chunks()
            if chunks and chunks.count > 0:
                self.log_stage("Document Chunks", f"{chunks.count} chunks created", {
                    'chunk_count': chunks.count,
                    'total_chars': chunks.total_chars,
                    'avg_chars': int(chunks.avg_chars) if chunks.avg_chars else 0
                })
            
            # Check entities
            entities = self.check_entities()
            if entities and entities.total_mentions > 0:
                self.log_stage("Entity Extraction", f"{entities.total_mentions} entities found", {
                    'total_mentions': entities.total_mentions,
                    'entity_types': entities.entity_types,
                    'canonical_entities': entities.canonical_count,
                    'types': entities.types_list
                })
            
            # Check relationships
            relationships = self.check_relationships()
            if relationships and relationships.count > 0:
                self.log_stage("Relationship Building", f"{relationships.count} relationships found", {
                    'count': relationships.count,
                    'types': relationships.types_list
                })
            
            # Check Redis state
            redis_state = self.check_redis_state()
            if redis_state:
                self.log_stage("Redis Pipeline State", redis_state.get('stage', 'unknown'), {
                    'stage': redis_state.get('stage'),
                    'status': redis_state.get('status'),
                    'error': redis_state.get('error')
                })
            
            # Check if processing is complete or failed
            if doc_status:
                if doc_status.celery_status in ['completed', 'failed', 'error']:
                    if chunks and chunks.count > 0:
                        print("\n✅ Processing appears complete!")
                    else:
                        print("\n❌ Processing stopped without completing chunking")
                    break
            
            # Wait before next check
            print(f"\nWaiting 15 seconds...")
            time.sleep(15)
        
        self.monitoring_data['end_time'] = datetime.now().isoformat()
        self.monitoring_data['iterations'] = iterations
        
        return self.monitoring_data

def main():
    document_uuid = "eaca69ea-1b5f-48f4-b7a1-6ac73521e0e5"
    
    monitor = AsyncProcessingMonitor(document_uuid)
    results = monitor.monitor_continuously(max_duration=600)  # Monitor for up to 10 minutes
    
    # Save results
    output_file = f"async_monitoring_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"\nMonitoring results saved to: {output_file}")

if __name__ == "__main__":
    main()