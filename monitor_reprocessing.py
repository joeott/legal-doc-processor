#!/usr/bin/env python3
"""Monitor document reprocessing progress in real-time"""

import os
import sys
sys.path.insert(0, '/opt/legal-doc-processor')

import time
from datetime import datetime
from scripts.db import DatabaseManager
from scripts.cache import get_redis_manager
from sqlalchemy import text
import json

def get_document_status(document_uuid: str):
    """Get current status of a document from database and Redis"""
    db = DatabaseManager(validate_conformance=False)
    session = next(db.get_session())
    
    try:
        # Get database status
        query = text("""
            SELECT sd.file_name, sd.status, sd.processing_status, 
                   sd.celery_task_id, sd.textract_job_id,
                   sd.ocr_completed_at, sd.updated_at,
                   COUNT(DISTINCT dc.id) as chunk_count,
                   COUNT(DISTINCT em.id) as entity_count,
                   COUNT(DISTINCT ce.id) as canonical_count,
                   COUNT(DISTINCT rs.id) as relationship_count
            FROM source_documents sd
            LEFT JOIN document_chunks dc ON sd.document_uuid = dc.document_uuid
            LEFT JOIN entity_mentions em ON sd.document_uuid = em.document_uuid
            LEFT JOIN canonical_entities ce ON sd.document_uuid = ce.document_uuid
            LEFT JOIN relationship_staging rs ON sd.document_uuid = rs.document_uuid
            WHERE sd.document_uuid = :doc_uuid
            GROUP BY sd.file_name, sd.status, sd.processing_status, 
                     sd.celery_task_id, sd.textract_job_id,
                     sd.ocr_completed_at, sd.updated_at
        """)
        
        result = session.execute(query, {'doc_uuid': document_uuid}).fetchone()
        
        if not result:
            return None
        
        db_status = {
            'file_name': result.file_name,
            'status': result.status,
            'processing_status': result.processing_status,
            'celery_task_id': result.celery_task_id,
            'textract_job_id': result.textract_job_id,
            'ocr_completed': result.ocr_completed_at is not None,
            'updated_at': result.updated_at,
            'chunk_count': result.chunk_count,
            'entity_count': result.entity_count,
            'canonical_count': result.canonical_count,
            'relationship_count': result.relationship_count
        }
        
    finally:
        session.close()
    
    # Get Redis state
    redis_mgr = get_redis_manager()
    state_key = f"doc:state:{document_uuid}"
    redis_state = redis_mgr.get_dict(state_key) or {}
    
    return {
        'database': db_status,
        'redis': redis_state
    }

def get_active_celery_tasks():
    """Get active Celery tasks from Redis"""
    redis_mgr = get_redis_manager()
    
    # Get active tasks
    active_tasks = []
    
    # Check Celery's active tasks
    from celery import current_app
    inspect = current_app.control.inspect()
    
    active = inspect.active()
    if active:
        for worker, tasks in active.items():
            for task in tasks:
                active_tasks.append({
                    'worker': worker,
                    'task_id': task['id'],
                    'name': task['name'],
                    'args': task.get('args', [])
                })
    
    return active_tasks

def format_status_display(doc_uuid: str, status: dict):
    """Format status for display"""
    db = status['database']
    redis = status['redis']
    
    # Determine current stage
    current_stage = "Unknown"
    if redis:
        last_update = redis.get('last_update', {})
        current_stage = last_update.get('stage', 'Unknown')
        stage_status = last_update.get('status', 'Unknown')
    
    # Build progress indicators
    stages = {
        'ocr': '⚪',
        'chunking': '⚪',
        'entity_extraction': '⚪',
        'entity_resolution': '⚪',
        'relationship_building': '⚪'
    }
    
    # Update indicators based on Redis state
    for stage, data in redis.items():
        if stage in stages and isinstance(data, dict):
            status = data.get('status', '')
            if status == 'completed':
                stages[stage] = '✅'
            elif status == 'in_progress':
                stages[stage] = '🔄'
            elif status == 'failed':
                stages[stage] = '❌'
    
    # Also check database counts
    if db['ocr_completed']:
        stages['ocr'] = '✅'
    if db['chunk_count'] > 0:
        stages['chunking'] = '✅'
    if db['entity_count'] > 0:
        stages['entity_extraction'] = '✅'
    if db['canonical_count'] > 0:
        stages['entity_resolution'] = '✅'
    if db['relationship_count'] > 0:
        stages['relationship_building'] = '✅'
    
    return f"""
📄 {db['file_name']}
   UUID: {doc_uuid}
   DB Status: {db['status']} | Processing: {db['processing_status'] or 'N/A'}
   Current Stage: {current_stage} ({stage_status})
   
   Pipeline Progress:
   {stages['ocr']} OCR
   {stages['chunking']} Chunking (chunks: {db['chunk_count']})
   {stages['entity_extraction']} Entity Extraction (entities: {db['entity_count']})
   {stages['entity_resolution']} Entity Resolution (canonical: {db['canonical_count']})
   {stages['relationship_building']} Relationships (count: {db['relationship_count']})
"""

def main():
    """Main monitoring loop"""
    print("=" * 80)
    print("Document Processing Monitor (After UUID Fix)")
    print("Press Ctrl+C to exit")
    print("=" * 80)
    
    # Get test documents
    db = DatabaseManager(validate_conformance=False)
    session = next(db.get_session())
    
    try:
        query = text("""
            SELECT document_uuid, file_name
            FROM source_documents sd
            JOIN projects p ON sd.project_fk_id = p.id
            WHERE p.name LIKE 'PIPELINE_TEST_%'
            AND sd.created_at::date = CURRENT_DATE
            ORDER BY sd.created_at DESC
            LIMIT 3
        """)
        
        documents = session.execute(query).fetchall()
        doc_uuids = [(str(doc.document_uuid), doc.file_name) for doc in documents]
        
    finally:
        session.close()
    
    if not doc_uuids:
        print("No test documents found!")
        return
    
    print(f"\nMonitoring {len(doc_uuids)} documents...\n")
    
    try:
        while True:
            # Clear screen
            os.system('clear' if os.name == 'posix' else 'cls')
            
            print("=" * 80)
            print(f"Document Processing Monitor - {datetime.now().strftime('%H:%M:%S')}")
            print("=" * 80)
            
            # Show active Celery tasks
            active_tasks = get_active_celery_tasks()
            if active_tasks:
                print("\n🔄 Active Celery Tasks:")
                for task in active_tasks[:5]:  # Show max 5 tasks
                    print(f"   - {task['name'].split('.')[-1]} [{task['task_id'][:8]}...]")
            else:
                print("\n⚪ No active Celery tasks")
            
            print("\n" + "-" * 80)
            
            # Show document statuses
            all_complete = True
            for doc_uuid, file_name in doc_uuids:
                status = get_document_status(doc_uuid)
                if status:
                    print(format_status_display(doc_uuid, status))
                    
                    # Check if complete
                    db_status = status['database']
                    if db_status['status'] != 'completed' or db_status['relationship_count'] == 0:
                        all_complete = False
                else:
                    print(f"\n❓ Document {doc_uuid} not found")
                    all_complete = False
            
            if all_complete:
                print("\n" + "=" * 80)
                print("✅ All documents have completed processing!")
                print("=" * 80)
                break
            
            # Wait before next update
            time.sleep(5)
            
    except KeyboardInterrupt:
        print("\n\nMonitoring stopped by user.")

if __name__ == "__main__":
    main()