#!/usr/bin/env python3
"""
Monitor E2E pipeline progression for recently imported documents.
"""
import os
import sys
import time
from datetime import datetime, timedelta

# Set environment variables
os.environ['USE_MINIMAL_MODELS'] = 'true'
os.environ['SKIP_CONFORMANCE_CHECK'] = 'true'

from scripts.db import DatabaseManager
from scripts.cache import get_redis_manager
from sqlalchemy import text

def get_recent_documents(db_manager, minutes_back=10):
    """Get documents created in the last N minutes"""
    cutoff_time = datetime.utcnow() - timedelta(minutes=minutes_back)
    
    for session in db_manager.get_session():
        result = session.execute(
            text("""
                SELECT document_uuid, file_name, status, celery_status, 
                       textract_job_id, textract_job_status, created_at
                FROM source_documents 
                WHERE created_at > :cutoff
                ORDER BY created_at DESC
            """),
            {"cutoff": cutoff_time}
        )
        docs = []
        for row in result:
            docs.append({
                'document_uuid': str(row[0]),
                'file_name': row[1],
                'status': row[2],
                'celery_status': row[3],
                'textract_job_id': row[4],
                'textract_job_status': row[5],
                'created_at': row[6]
            })
        return docs

def get_pipeline_state(redis_manager, document_uuid):
    """Get complete pipeline state from Redis"""
    stages = ["ocr", "chunking", "entity_extraction", "entity_resolution", "relationships"]
    state = {}
    
    for stage in stages:
        state_key = f"doc:state:{document_uuid}:{stage}"
        stage_data = redis_manager.get_dict(state_key) or {}
        state[stage] = stage_data.get('status', 'none')
    
    return state

def monitor_pipeline(duration_seconds=300):
    """Monitor pipeline for N seconds"""
    print("=== E2E Pipeline Monitoring ===")
    print(f"Monitoring for {duration_seconds} seconds...")
    print(f"Start time: {datetime.now()}")
    
    db_manager = DatabaseManager()
    redis_manager = get_redis_manager()
    
    # Get recent documents
    docs = get_recent_documents(db_manager, minutes_back=10)
    
    if not docs:
        print("❌ No recent documents found!")
        return
    
    print(f"\nFound {len(docs)} recent documents:")
    for doc in docs:
        print(f"  - {doc['file_name'][:50]}... ({doc['document_uuid'][:8]}...)")
    
    print("\n" + "="*100)
    print("Monitoring pipeline states (refreshes every 10 seconds):")
    print("="*100)
    
    start_time = time.time()
    last_states = {}
    
    while time.time() - start_time < duration_seconds:
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Pipeline Status:")
        print("-" * 100)
        print("Document (First 30 chars) | DB Status | OCR | Chunking | Entity Ext | Resolution | Relations")
        print("-" * 100)
        
        all_complete = True
        
        for doc in docs:
            doc_uuid = doc['document_uuid']
            
            # Get latest DB status
            for session in db_manager.get_session():
                result = session.execute(
                    text("SELECT status, textract_job_status FROM source_documents WHERE document_uuid = :uuid"),
                    {"uuid": doc_uuid}
                )
                row = result.first()
                if row:
                    doc['status'] = row[0]
                    doc['textract_job_status'] = row[1]
                break
            
            # Get Redis pipeline state
            pipeline_state = get_pipeline_state(redis_manager, doc_uuid)
            
            # Check for changes
            if doc_uuid in last_states and last_states[doc_uuid] != pipeline_state:
                # State changed - highlight
                print("🔄 ", end="")
            else:
                print("   ", end="")
            
            last_states[doc_uuid] = pipeline_state
            
            # Display status
            file_display = doc['file_name'][:30].ljust(30)
            db_status = (doc['status'] or 'unknown')[:10].ljust(10)
            
            status_symbols = {
                'none': '⬜',
                'pending': '🟨',
                'in_progress': '🔄',
                'completed': '✅',
                'failed': '❌'
            }
            
            ocr = status_symbols.get(pipeline_state['ocr'], '❓')
            chunking = status_symbols.get(pipeline_state['chunking'], '❓')
            entity = status_symbols.get(pipeline_state['entity_extraction'], '❓')
            resolution = status_symbols.get(pipeline_state['entity_resolution'], '❓')
            relations = status_symbols.get(pipeline_state['relationships'], '❓')
            
            print(f"{file_display} | {db_status} | {ocr} | {chunking} | {entity} | {resolution} | {relations}")
            
            # Check if complete
            if pipeline_state.get('relationships') != 'completed':
                all_complete = False
        
        if all_complete:
            print("\n✅ All documents have completed processing!")
            break
        
        # Check for errors
        print("\nTextract Jobs:")
        for doc in docs:
            if doc['textract_job_id']:
                print(f"  {doc['file_name'][:40]}... - Job: {doc['textract_job_id']} - Status: {doc['textract_job_status']}")
        
        time.sleep(10)  # Wait 10 seconds before next check
    
    print(f"\n{'='*100}")
    print(f"Monitoring complete. End time: {datetime.now()}")
    
    # Final summary
    print("\n=== Final Summary ===")
    completed = 0
    failed = 0
    in_progress = 0
    
    for doc in docs:
        pipeline_state = get_pipeline_state(redis_manager, doc['document_uuid'])
        if pipeline_state.get('relationships') == 'completed':
            completed += 1
        elif any(v == 'failed' for v in pipeline_state.values()):
            failed += 1
        else:
            in_progress += 1
    
    print(f"✅ Completed: {completed}")
    print(f"❌ Failed: {failed}")
    print(f"🔄 In Progress: {in_progress}")
    
    return completed == len(docs)

if __name__ == "__main__":
    duration = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    success = monitor_pipeline(duration)
    sys.exit(0 if success else 1)