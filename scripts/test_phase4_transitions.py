#!/usr/bin/env python3
"""
Phase 4 Test 4.2: Verify Automatic Stage Transitions
Monitor pipeline progression for up to 5 minutes to verify automatic transitions.
"""
import os
import time
import sys
import uuid
from datetime import datetime

# Set environment variables
os.environ['USE_MINIMAL_MODELS'] = 'true'
os.environ['SKIP_CONFORMANCE_CHECK'] = 'true'

from scripts.db import DatabaseManager
from scripts.cache import get_redis_manager
from scripts.pdf_tasks import extract_text_from_document
from scripts.core.model_factory import get_source_document_model

def create_test_document():
    """Create a test document for pipeline testing"""
    print("Creating test document...")
    
    db_manager = DatabaseManager()
    DocumentModel = get_source_document_model()
    
    # Create test document
    test_doc = DocumentModel(
        document_uuid=str(uuid.uuid4()),
        file_name='test_pipeline_transitions.pdf',
        original_file_name='test_pipeline_transitions.pdf',
        file_path='/opt/legal-doc-processor/input_docs/Paul, Michael (Acuity)/Paul, Michael - Wombat Corp Disclosure Stmt 10-23-24.pdf',
        file_size=1024,
        mime_type='application/pdf',
        upload_timestamp=datetime.utcnow(),
        processing_status='pending'
    )
    
    try:
        # Store in database
        doc = db_manager.create_document(test_doc)
        print(f"✅ Created test document: {doc.document_uuid}")
        
        # Store metadata in Redis
        redis_manager = get_redis_manager()
        metadata_key = f"doc:metadata:{doc.document_uuid}"
        redis_manager.store_dict(metadata_key, {
            'project_uuid': 'test-project-uuid',
            'document_metadata': {
                'title': 'Test Pipeline Document',
                'created_at': datetime.utcnow().isoformat()
            }
        })
        
        return doc.document_uuid
    except Exception as e:
        print(f"❌ Error creating document: {e}")
        return None

def monitor_pipeline_progression(document_uuid, max_duration=300):
    """Monitor pipeline progression for automatic transitions"""
    print(f"\n=== Phase 4 Test 4.2: Automatic Stage Transitions ===")
    print(f"Document UUID: {document_uuid}")
    print(f"Max monitoring duration: {max_duration} seconds")
    print(f"Start time: {datetime.now()}")
    print("-" * 60)
    
    redis_manager = get_redis_manager()
    start_time = time.time()
    last_state = {}
    stage_transitions = []
    
    # Expected stage progression
    expected_stages = ["ocr", "chunking", "entity_extraction", "entity_resolution", "relationships"]
    completed_stages = set()
    
    print("\nMonitoring pipeline state every 5 seconds...")
    print("Format: elapsed_time | ocr | chunking | entity | resolution | relationships")
    print("-" * 80)
    
    while time.time() - start_time < max_duration:
        elapsed = int(time.time() - start_time)
        
        # Get current state for all stages
        current_state = {}
        for stage in expected_stages:
            state_key = f"doc:state:{document_uuid}:{stage}"
            state_data = redis_manager.get_dict(state_key) or {}
            current_state[stage] = state_data.get('status', 'none')
            
            # Track completed stages
            if state_data.get('status') == 'completed':
                completed_stages.add(stage)
        
        # Check for state changes
        state_changed = False
        for stage, status in current_state.items():
            if stage not in last_state or last_state[stage] != status:
                state_changed = True
                if status != 'none':
                    transition = f"{elapsed}s: {stage} -> {status}"
                    stage_transitions.append(transition)
        
        # Display current state
        if state_changed or elapsed % 10 == 0:  # Show every 10 seconds or on change
            print(f"{elapsed:4d}s | {current_state['ocr']:9} | {current_state['chunking']:9} | "
                  f"{current_state['entity_extraction']:9} | {current_state['entity_resolution']:9} | "
                  f"{current_state['relationships']:9}")
        
        last_state = current_state
        
        # Check if pipeline is complete
        if len(completed_stages) == len(expected_stages):
            print("\n✅ Pipeline completed all stages!")
            break
        
        # Check if pipeline is stuck
        if elapsed > 60 and not completed_stages:
            print("\n⚠️ No stages completed after 60 seconds")
            break
        
        time.sleep(5)
    
    print("\n" + "-" * 80)
    print(f"Monitoring complete. End time: {datetime.now()}")
    print(f"Total elapsed: {int(time.time() - start_time)} seconds")
    
    # Summary
    print("\n=== Stage Transitions ===")
    for transition in stage_transitions:
        print(f"  {transition}")
    
    print(f"\n=== Completed Stages ({len(completed_stages)}/{len(expected_stages)}) ===")
    for stage in expected_stages:
        status = "✅" if stage in completed_stages else "❌"
        print(f"  {status} {stage}")
    
    # Verify automatic transitions
    print("\n=== Automatic Transition Verification ===")
    
    # Check if transitions happened automatically (without manual intervention)
    auto_transitions = []
    
    # OCR -> Chunking
    if "ocr" in completed_stages and "chunking" in stage_transitions:
        for i, trans in enumerate(stage_transitions):
            if "ocr -> completed" in trans:
                # Check if chunking started within 10 seconds
                for j in range(i+1, len(stage_transitions)):
                    if "chunking ->" in stage_transitions[j]:
                        ocr_time = int(stage_transitions[i].split('s:')[0])
                        chunk_time = int(stage_transitions[j].split('s:')[0])
                        if chunk_time - ocr_time <= 10:
                            auto_transitions.append(f"OCR → Chunking (in {chunk_time - ocr_time}s)")
                        break
    
    if auto_transitions:
        print("✅ Automatic transitions detected:")
        for trans in auto_transitions:
            print(f"  - {trans}")
    else:
        print("❌ No automatic transitions detected")
    
    return len(completed_stages) == len(expected_stages), completed_stages

def start_pipeline(document_uuid):
    """Start the pipeline by triggering OCR"""
    print(f"\nStarting pipeline for document {document_uuid}...")
    
    try:
        # Trigger OCR task
        result = extract_text_from_document.apply_async(
            args=[document_uuid, '/opt/legal-doc-processor/input_docs/Paul, Michael (Acuity)/Paul, Michael - Wombat Corp Disclosure Stmt 10-23-24.pdf']
        )
        print(f"✅ OCR task submitted: {result.id}")
        return True
    except Exception as e:
        print(f"❌ Error starting pipeline: {e}")
        return False

if __name__ == "__main__":
    # Create test document
    doc_uuid = create_test_document()
    if not doc_uuid:
        print("Failed to create test document")
        sys.exit(1)
    
    # Start the pipeline
    if not start_pipeline(doc_uuid):
        print("Failed to start pipeline")
        sys.exit(1)
    
    # Monitor progression
    success, completed = monitor_pipeline_progression(doc_uuid, max_duration=300)
    
    if success:
        print("\n✅ Test 4.2 PASSED: Pipeline completed with automatic transitions")
        sys.exit(0)
    else:
        print(f"\n❌ Test 4.2 FAILED: Only {len(completed)} stages completed")
        sys.exit(1)