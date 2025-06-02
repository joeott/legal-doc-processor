#!/usr/bin/env python3
"""
Phase 4: Pipeline Progression Tests
Tests automatic stage transitions and polling behavior
"""
import time
import json
import sys
from datetime import datetime
from scripts.cache import get_redis_manager, CacheKeys
from scripts.pdf_tasks import extract_text_from_document

def monitor_pipeline_progression(document_uuid: str, duration: int = 300):
    """Monitor pipeline progression for a document"""
    redis = get_redis_manager()
    state_key = CacheKeys.DOC_STATE.format(document_uuid=document_uuid)
    
    print(f"\n=== PHASE 4: PIPELINE PROGRESSION TEST ===")
    print(f"Document UUID: {document_uuid}")
    print(f"Monitoring for {duration} seconds...")
    print(f"Start time: {datetime.now()}")
    print("\nTime | Pipeline | OCR       | Chunking  | Entity    | Relations")
    print("-" * 70)
    
    stages_seen = set()
    transitions = []
    start_time = time.time()
    
    # Submit OCR task to start pipeline
    print("\nSubmitting OCR task to start pipeline...")
    s3_path = f"s3://samu-docs-private-upload/documents/{document_uuid}.pdf"
    task = extract_text_from_document.apply_async(args=[document_uuid, s3_path])
    print(f"Task submitted: {task.id}")
    
    last_state = {}
    while time.time() - start_time < duration:
        elapsed = int(time.time() - start_time)
        
        # Get current state
        state = redis.get_dict(state_key)
        if not state:
            print(f"{elapsed:3d}s | No state in Redis yet...")
            time.sleep(5)
            continue
        
        # Extract stage statuses
        pipeline = state.get('pipeline', {}).get('status', 'none')
        ocr = state.get('ocr', {}).get('status', 'none')
        chunking = state.get('chunking', {}).get('status', 'none')
        entity = state.get('entity_extraction', {}).get('status', 'none')
        relations = state.get('relationships', {}).get('status', 'none')
        
        # Print current state
        print(f"{elapsed:3d}s | {pipeline:8} | {ocr:9} | {chunking:9} | {entity:9} | {relations:9}")
        
        # Track stage transitions
        for stage_name, status in [
            ('ocr', ocr), 
            ('chunking', chunking), 
            ('entity_extraction', entity), 
            ('relationships', relations)
        ]:
            # Check for new completion
            if status == 'completed' and stage_name not in stages_seen:
                stages_seen.add(stage_name)
                transition_time = elapsed
                transitions.append({
                    'stage': stage_name,
                    'status': 'completed',
                    'time': transition_time
                })
                print(f"\n✅ {stage_name} completed at {transition_time}s")
                
            # Check for status changes
            old_status = last_state.get(stage_name, {}).get('status', 'none')
            if status != old_status and status != 'none':
                print(f"\n📋 {stage_name}: {old_status} → {status}")
        
        # Update last state
        last_state = {
            'pipeline': pipeline,
            'ocr': {'status': ocr},
            'chunking': {'status': chunking},
            'entity_extraction': {'status': entity},
            'relationships': {'status': relations}
        }
        
        # Check for pipeline completion
        if pipeline == 'completed':
            print(f"\n✅ Pipeline completed successfully at {elapsed}s!")
            break
            
        # Check for pipeline failure
        if pipeline == 'failed':
            error = state.get('pipeline', {}).get('metadata', {}).get('error', 'Unknown')
            print(f"\n❌ Pipeline failed at {elapsed}s: {error}")
            break
        
        time.sleep(5)
    
    # Final summary
    print(f"\n=== SUMMARY ===")
    print(f"Total monitoring time: {int(time.time() - start_time)}s")
    print(f"Stages completed: {len(stages_seen)}")
    print(f"Completed stages: {', '.join(sorted(stages_seen))}")
    
    if transitions:
        print(f"\nTransition timeline:")
        for t in transitions:
            print(f"  - {t['stage']}: completed at {t['time']}s")
    
    # Check for automatic transitions
    print(f"\n=== VERIFICATION ===")
    if len(transitions) > 1:
        print("✅ Automatic stage transitions detected")
        for i in range(1, len(transitions)):
            prev = transitions[i-1]
            curr = transitions[i]
            gap = curr['time'] - prev['time']
            print(f"  - {prev['stage']} → {curr['stage']}: {gap}s gap")
    else:
        print("❌ No automatic transitions detected")
    
    return stages_seen, transitions

def test_polling_behavior():
    """Test that polling tasks are running"""
    print("\n=== POLLING TASK TEST ===")
    print("Checking for poll_textract_job tasks in logs...")
    
    # Check Celery logs for polling activity
    import subprocess
    try:
        result = subprocess.run(
            ["grep", "-E", "poll_textract_job|Polling|retry", "/opt/legal-doc-processor/celery_worker.log"],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.stdout:
            print("✅ Polling activity found in logs:")
            lines = result.stdout.strip().split('\n')[-5:]  # Last 5 matches
            for line in lines:
                print(f"  {line}")
        else:
            print("⚠️  No polling activity found in logs")
            
    except Exception as e:
        print(f"❌ Error checking logs: {e}")

if __name__ == "__main__":
    # Test with a real document
    test_doc_uuid = "4dcc5583-b2cc-4d68-bdd0-6e227a98cf8b"
    
    # First test polling behavior
    test_polling_behavior()
    
    # Then monitor pipeline progression
    stages, transitions = monitor_pipeline_progression(test_doc_uuid, duration=60)
    
    # Exit with appropriate code
    if len(stages) >= 2:  # At least OCR and one other stage
        print("\n✅ Phase 4 tests PASSED")
        sys.exit(0)
    else:
        print("\n❌ Phase 4 tests FAILED - insufficient progression")
        sys.exit(1)