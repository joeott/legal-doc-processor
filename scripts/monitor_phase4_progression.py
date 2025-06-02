#!/usr/bin/env python3
"""Phase 4: Monitor pipeline progression after manual trigger"""
import time
import json
from datetime import datetime
from scripts.cache import get_redis_manager, CacheKeys

def monitor_progression(doc_uuid: str, duration: int = 120):
    """Monitor pipeline stages for automatic transitions"""
    redis = get_redis_manager()
    state_key = CacheKeys.DOC_STATE.format(document_uuid=doc_uuid)
    
    print(f"\n=== PHASE 4: PIPELINE PROGRESSION MONITORING ===")
    print(f"Document: {doc_uuid}")
    print(f"Duration: {duration}s")
    print(f"Started: {datetime.now()}")
    
    print("\nTime | Pipeline  | OCR       | Chunking  | Entity    | Relations")
    print("-" * 75)
    
    start_time = time.time()
    last_state = {}
    stages_completed = []
    transitions = []
    
    while time.time() - start_time < duration:
        elapsed = int(time.time() - start_time)
        
        # Get current state
        state = redis.get_dict(state_key) or {}
        
        # Extract statuses
        pipeline = state.get('pipeline', {}).get('status', 'none')
        ocr = state.get('ocr', {}).get('status', 'none')
        chunking = state.get('chunking', {}).get('status', 'none')
        entity = state.get('entity_extraction', {}).get('status', 'none')
        relations = state.get('relationships', {}).get('status', 'none')
        
        # Print current state
        print(f"{elapsed:3d}s | {pipeline:9} | {ocr:9} | {chunking:9} | {entity:9} | {relations:9}")
        
        # Track transitions
        for stage, status in [
            ('ocr', ocr),
            ('chunking', chunking),
            ('entity_extraction', entity),
            ('relationships', relations)
        ]:
            old_status = last_state.get(stage, 'none')
            if status != old_status and status != 'none':
                transition = f"{stage}: {old_status} → {status}"
                transitions.append((elapsed, transition))
                print(f"\n🔄 {transition} at {elapsed}s")
                
                if status == 'completed' and stage not in stages_completed:
                    stages_completed.append(stage)
                    print(f"✅ {stage} completed!")
        
        # Update last state
        last_state = {
            'ocr': ocr,
            'chunking': chunking,
            'entity_extraction': entity,
            'relationships': relations
        }
        
        # Check completion
        if pipeline == 'completed':
            print(f"\n✅ PIPELINE COMPLETED at {elapsed}s!")
            break
        elif pipeline == 'failed':
            error = state.get('pipeline', {}).get('metadata', {}).get('error', 'Unknown')
            print(f"\n❌ PIPELINE FAILED at {elapsed}s: {error}")
            break
            
        time.sleep(5)
    
    # Summary
    print(f"\n=== PHASE 4 TEST RESULTS ===")
    print(f"Total time: {int(time.time() - start_time)}s")
    print(f"Stages completed: {len(stages_completed)}")
    
    if stages_completed:
        print(f"\nCompleted stages:")
        for stage in stages_completed:
            print(f"  ✅ {stage}")
    
    if transitions:
        print(f"\nTransition timeline:")
        for t, desc in transitions:
            print(f"  {t:3d}s: {desc}")
    
    # Check for automatic transitions
    print(f"\n=== AUTOMATIC TRANSITION ANALYSIS ===")
    auto_transitions = []
    
    # Check if chunking started after OCR
    ocr_complete_time = next((t for t, d in transitions if 'ocr' in d and 'completed' in d), None)
    chunking_start_time = next((t for t, d in transitions if 'chunking' in d and 'processing' in d), None)
    
    if ocr_complete_time is not None and chunking_start_time is not None:
        gap = chunking_start_time - ocr_complete_time
        if gap < 10:  # Within 10 seconds
            auto_transitions.append(f"OCR → Chunking (gap: {gap}s)")
    
    # Check if entity extraction started after chunking
    chunking_complete_time = next((t for t, d in transitions if 'chunking' in d and 'completed' in d), None)
    entity_start_time = next((t for t, d in transitions if 'entity_extraction' in d and 'processing' in d), None)
    
    if chunking_complete_time is not None and entity_start_time is not None:
        gap = entity_start_time - chunking_complete_time
        if gap < 10:
            auto_transitions.append(f"Chunking → Entity Extraction (gap: {gap}s)")
    
    if auto_transitions:
        print("✅ Automatic transitions detected:")
        for trans in auto_transitions:
            print(f"  - {trans}")
    else:
        print("❌ No automatic transitions detected")
    
    # Final verdict
    print(f"\n=== PHASE 4 VERDICT ===")
    if len(stages_completed) >= 2 and auto_transitions:
        print("✅ PASSED: Pipeline shows automatic progression")
        return True
    elif len(stages_completed) >= 2:
        print("⚠️  PARTIAL: Stages completed but no automatic transitions")
        return True
    else:
        print("❌ FAILED: Insufficient pipeline progression")
        return False

if __name__ == "__main__":
    doc_uuid = "4dcc5583-b2cc-4d68-bdd0-6e227a98cf8b"
    success = monitor_progression(doc_uuid, duration=120)
    exit(0 if success else 1)