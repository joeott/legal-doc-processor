#!/usr/bin/env python3
"""
Fixed monitoring script for async processing with correct column names
"""

import os
import sys
sys.path.insert(0, '/opt/legal-doc-processor')

import time
import json
from datetime import datetime
from sqlalchemy import text

os.environ['FORCE_PROCESSING'] = 'true'
os.environ['SKIP_PDF_PREPROCESSING'] = 'true'

from scripts.db import DatabaseManager
from scripts.cache import get_redis_manager

def monitor_document(doc_uuid):
    db = DatabaseManager(validate_conformance=False)
    redis = get_redis_manager()
    
    monitoring_data = {
        'document_uuid': doc_uuid,
        'start_time': datetime.now().isoformat(),
        'stages': []
    }
    
    def log_stage(stage, details):
        entry = {
            'timestamp': datetime.now().isoformat(),
            'stage': stage,
            'details': details
        }
        monitoring_data['stages'].append(entry)
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] {stage}")
        for k, v in details.items():
            if v is not None:
                print(f"  {k}: {v}")
    
    print(f"Monitoring async processing for: {doc_uuid}")
    print("="*70)
    
    for i in range(40):  # Monitor for up to 10 minutes (40 * 15 seconds)
        session = next(db.get_session())
        
        # Check document status
        doc_result = session.execute(text("""
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
        """), {'doc_uuid': doc_uuid})
        
        doc = doc_result.fetchone()
        if doc:
            log_stage("Document Status", {
                'status': doc.status,
                'celery_status': doc.celery_status,
                'has_text': doc.has_text,
                'textract_job_id': doc.textract_job_id[:30] + '...' if doc.textract_job_id else None,
                'textract_status': doc.textract_job_status,
                'error': doc.error_message[:100] if doc.error_message else None
            })
        
        # Check processing tasks (using correct column names)
        tasks_result = session.execute(text("""
            SELECT 
                task_type,
                status,
                celery_task_id,
                error_message,
                created_at,
                completed_at
            FROM processing_tasks
            WHERE document_id = :doc_uuid
            ORDER BY created_at DESC
            LIMIT 5
        """), {'doc_uuid': doc_uuid})
        
        tasks = list(tasks_result)
        if tasks:
            log_stage("Processing Tasks", {
                'total_tasks': len(tasks),
                'latest': f"{tasks[0].task_type} - {tasks[0].status}" if tasks else None,
                'task_id': tasks[0].celery_task_id[:30] + '...' if tasks and tasks[0].celery_task_id else None
            })
            
            # Show task errors
            for task in tasks:
                if task.error_message:
                    print(f"    ERROR in {task.task_type}: {task.error_message[:80]}")
        
        # Check Textract jobs
        textract_result = session.execute(text("""
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
        """), {'doc_uuid': doc_uuid})
        
        textract = textract_result.fetchone()
        if textract:
            log_stage("Textract Job", {
                'job_id': textract.job_id[:30] + '...',
                'status': textract.status,
                'page_count': textract.page_count,
                'has_result': textract.has_result,
                'error': textract.error_message[:80] if textract.error_message else None
            })
        
        # Check chunks
        chunks_result = session.execute(text("""
            SELECT 
                COUNT(*) as count,
                SUM(LENGTH(text)) as total_chars,
                MIN(chunk_index) as min_idx,
                MAX(chunk_index) as max_idx
            FROM document_chunks
            WHERE document_uuid = :doc_uuid
        """), {'doc_uuid': doc_uuid})
        
        chunks = chunks_result.fetchone()
        if chunks and chunks.count > 0:
            log_stage("Document Chunks", {
                'count': chunks.count,
                'total_chars': chunks.total_chars,
                'chunk_range': f"{chunks.min_idx}-{chunks.max_idx}"
            })
        
        # Check entities
        entities_result = session.execute(text("""
            SELECT 
                COUNT(*) as total,
                COUNT(DISTINCT entity_type) as types,
                COUNT(DISTINCT canonical_entity_uuid) as canonical,
                STRING_AGG(DISTINCT entity_type, ', ' ORDER BY entity_type) as type_list
            FROM entity_mentions
            WHERE document_uuid = :doc_uuid
        """), {'doc_uuid': doc_uuid})
        
        entities = entities_result.fetchone()
        if entities and entities.total > 0:
            log_stage("Entity Mentions", {
                'total': entities.total,
                'types': entities.types,
                'canonical': entities.canonical,
                'type_list': entities.type_list[:100] if entities.type_list else None
            })
        
        # Check relationships
        rel_result = session.execute(text("""
            SELECT 
                COUNT(*) as count,
                COUNT(DISTINCT relationship_type) as types
            FROM relationship_staging rs
            JOIN document_chunks dc ON rs.source_chunk_uuid = dc.chunk_uuid
            WHERE dc.document_uuid = :doc_uuid
        """), {'doc_uuid': doc_uuid})
        
        rels = rel_result.fetchone()
        if rels and rels.count > 0:
            log_stage("Relationships", {
                'count': rels.count,
                'types': rels.types
            })
        
        # Check Redis state using proper method
        try:
            state_key = f"doc:state:{doc_uuid}"
            # Use Redis command directly
            state_data = redis.redis_client.get(state_key)
            if state_data:
                state = json.loads(state_data)
                log_stage("Redis State", {
                    'stage': state.get('stage'),
                    'status': state.get('status'),
                    'error': state.get('error')[:100] if state.get('error') else None
                })
        except Exception as e:
            print(f"  Redis check error: {e}")
        
        session.close()
        
        # Check completion
        if doc and doc.celery_status in ['completed', 'failed', 'error']:
            if chunks and chunks.count > 0:
                print("\n✅ Processing appears complete!")
            else:
                print("\n❌ Processing stopped")
            break
        
        print(f"\nWaiting 15 seconds... (check {i+1}/40)")
        time.sleep(15)
    
    monitoring_data['end_time'] = datetime.now().isoformat()
    
    # Save monitoring data
    output_file = f"async_monitor_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_file, 'w') as f:
        json.dump(monitoring_data, f, indent=2)
    
    print(f"\nMonitoring data saved to: {output_file}")
    return monitoring_data

if __name__ == "__main__":
    doc_uuid = "eaca69ea-1b5f-48f4-b7a1-6ac73521e0e5"
    monitor_document(doc_uuid)