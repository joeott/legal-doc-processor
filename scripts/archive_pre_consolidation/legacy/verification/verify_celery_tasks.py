#!/usr/bin/env python3
"""
Verify Celery Tasks Implementation - Phase 3 Verification
Tests that Celery tasks properly update status in source_documents table
"""
import sys
import os
import time
from pathlib import Path
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.celery_submission import submit_document_to_celery
from scripts.supabase_utils import SupabaseManager

def test_celery_status_updates():
    """Test that Celery tasks update celery_status field properly"""
    print("Testing Celery status updates in source_documents table...")
    
    db = SupabaseManager()
    
    # Create a test document entry
    test_file_path = "/tmp/test_celery_status.txt"
    with open(test_file_path, 'w') as f:
        f.write("This is a test document for verifying Celery status updates.")
    
    # Create source document
    try:
        doc_id, doc_uuid = db.create_document_entry(
            project_id=db.get_global_project_sql_id(),
            file_name="test_celery_status.txt",
            file_path=test_file_path,
            file_type=".txt",
            upload_status="completed",
            metadata={"test": "celery_status_verification"}
        )
        
        print(f"Created test document: ID={doc_id}, UUID={doc_uuid}")
        
        # Submit to Celery
        task_id, success = submit_document_to_celery(
            document_id=doc_id,
            document_uuid=doc_uuid,
            file_path=test_file_path,
            file_type=".txt"
        )
        
        if not success:
            print("ERROR: Failed to submit document to Celery")
            return False
        
        print(f"Submitted to Celery with task_id: {task_id}")
        
        # Monitor status changes
        status_history = []
        last_status = None
        timeout = 120  # 2 minutes timeout
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            # Check current status
            result = db.client.table('source_documents').select(
                'celery_status, celery_task_id, status, last_modified_at'
            ).eq('id', doc_id).single().execute()
            
            current_status = result.data.get('celery_status')
            
            if current_status != last_status:
                status_history.append({
                    'status': current_status,
                    'time': datetime.now().isoformat(),
                    'elapsed': round(time.time() - start_time, 2)
                })
                print(f"Status changed to: {current_status} (after {status_history[-1]['elapsed']}s)")
                last_status = current_status
            
            # Check if completed or failed
            if current_status in ['completed', 'ocr_failed', 'text_failed', 
                                  'entity_failed', 'resolution_failed', 'graph_failed']:
                break
            
            time.sleep(1)
        
        # Print status history
        print("\nStatus transition history:")
        for i, status in enumerate(status_history):
            print(f"  {i+1}. {status['status']} at {status['elapsed']}s")
        
        # Verify expected transitions
        expected_statuses = [
            'pending',
            'processing',
            'ocr_processing',
            'ocr_complete',
            'text_processing',
            'entity_extraction',
            'entity_resolution',
            'graph_building',
            'completed'
        ]
        
        actual_statuses = [s['status'] for s in status_history]
        
        # Check if we have the expected progression
        success = True
        if 'completed' in actual_statuses:
            print("\n✓ Document processing completed successfully")
            # Check key transitions occurred
            for expected in ['ocr_processing', 'text_processing', 'completed']:
                if expected not in actual_statuses:
                    print(f"  ✗ Missing expected status: {expected}")
                    success = False
        else:
            print("\n✗ Document processing did not complete")
            success = False
        
        # Check Redis state tracking
        from scripts.redis_utils import get_redis_manager, CacheKeys
        redis_mgr = get_redis_manager()
        if redis_mgr and redis_mgr.is_available():
            state_key = CacheKeys.format_key(CacheKeys.DOC_STATE, document_uuid=doc_uuid)
            state_data = redis_mgr.hgetall(state_key)
            
            print("\nRedis state tracking:")
            phases = ['ocr', 'doc_node_creation', 'chunking', 'ner', 'resolution', 'relationships', 'pipeline']
            for phase in phases:
                status = state_data.get(f"{phase}_status", "not_found")
                if status != "not_found":
                    print(f"  {phase}: {status}")
        
        # Cleanup
        Path(test_file_path).unlink(missing_ok=True)
        
        return success
        
    except Exception as e:
        print(f"ERROR during test: {e}")
        import traceback
        traceback.print_exc()
        return False


def check_celery_workers():
    """Check if Celery workers are running"""
    from scripts.celery_app import app
    
    print("Checking Celery workers...")
    
    # Get active queues
    i = app.control.inspect()
    active_queues = i.active_queues()
    
    if not active_queues:
        print("✗ No Celery workers found running!")
        print("  Run: ./scripts/start_celery_workers.sh")
        return False
    
    print("✓ Celery workers found:")
    for worker, queues in active_queues.items():
        print(f"  Worker: {worker}")
        for queue in queues:
            print(f"    - Queue: {queue['name']}")
    
    return True


if __name__ == "__main__":
    print("=== Celery Task Status Update Verification ===\n")
    
    # First check workers
    if not check_celery_workers():
        sys.exit(1)
    
    print("\n" + "="*50 + "\n")
    
    # Run the test
    if test_celery_status_updates():
        print("\n✓ All tests passed! Celery tasks are properly updating status.")
        sys.exit(0)
    else:
        print("\n✗ Tests failed. Check the output above for details.")
        sys.exit(1)