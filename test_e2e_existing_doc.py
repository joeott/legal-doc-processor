#!/usr/bin/env python3
"""
End-to-End Pipeline Test using existing document
Based on context_324_e2e_verification_characteristics.md
"""

import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scripts.celery_app import app
from scripts.pdf_tasks import process_pdf_document
from scripts.db import DatabaseManager
from scripts.cache import get_redis_manager, CacheKeys
from sqlalchemy import text
import json

# Use the existing test document
TEST_DOCUMENT_UUID = '5805f7b5-09ca-4f95-a990-da2dd758fd9e'

# Performance tracking
stage_timings = {}
stage_start_times = {}

def log_stage_start(stage: str):
    """Log the start of a stage"""
    stage_start_times[stage] = time.time()
    print(f"\n{'='*60}")
    print(f"🚀 STAGE START: {stage}")
    print(f"⏰ Time: {datetime.now().isoformat()}")
    print(f"{'='*60}")

def log_stage_complete(stage: str, success: bool = True):
    """Log the completion of a stage"""
    elapsed = time.time() - stage_start_times.get(stage, time.time())
    stage_timings[stage] = elapsed
    
    status = "✅ SUCCESS" if success else "❌ FAILED"
    print(f"\n{'='*60}")
    print(f"{status}: {stage}")
    print(f"⏱️  Duration: {elapsed:.2f} seconds")
    print(f"{'='*60}")

def get_document_info():
    """Get info about the test document"""
    db_manager = DatabaseManager()
    session = next(db_manager.get_session())
    
    try:
        result = session.execute(
            text("""
                SELECT document_uuid, file_name, file_path, status, 
                       project_uuid, ocr_completed_at, processing_completed_at
                FROM source_documents
                WHERE document_uuid = :uuid
            """),
            {'uuid': TEST_DOCUMENT_UUID}
        ).fetchone()
        
        if result:
            print(f"📄 Document: {result.document_uuid}")
            print(f"   File: {result.file_name}")
            print(f"   Path: {result.file_path}")
            print(f"   Status: {result.status}")
            print(f"   Project: {result.project_uuid}")
            return result
        else:
            print(f"❌ Document {TEST_DOCUMENT_UUID} not found!")
            return None
            
    finally:
        session.close()

def check_pipeline_state(document_uuid: str):
    """Check current pipeline state from Redis"""
    redis_manager = get_redis_manager()
    state_key = CacheKeys.DOC_STATE.format(document_uuid=document_uuid)
    state = redis_manager.get_dict(state_key) or {}
    return state

def verify_all_stages():
    """Verify all pipeline stages for the document"""
    print("\n🔍 VERIFYING PIPELINE STAGES")
    
    db_manager = DatabaseManager()
    redis_manager = get_redis_manager()
    
    # Get current pipeline state
    state = check_pipeline_state(TEST_DOCUMENT_UUID)
    
    results = {
        'ocr': False,
        'chunking': False,
        'entity_extraction': False,
        'entity_resolution': False,
        'relationships': False,
        'finalization': False
    }
    
    # Check OCR
    log_stage_start("OCR Verification")
    session = next(db_manager.get_session())
    try:
        ocr_result = session.execute(
            text("""
                SELECT raw_extracted_text, ocr_completed_at, ocr_provider,
                       LENGTH(raw_extracted_text) as text_length
                FROM source_documents 
                WHERE document_uuid = :uuid
            """),
            {'uuid': TEST_DOCUMENT_UUID}
        ).fetchone()
        
        if ocr_result and ocr_result.raw_extracted_text:
            print(f"✅ OCR completed: {ocr_result.text_length} characters")
            print(f"✅ Provider: {ocr_result.ocr_provider}")
            print(f"✅ Completed at: {ocr_result.ocr_completed_at}")
            results['ocr'] = True
            log_stage_complete("OCR Verification", True)
        else:
            print("❌ No OCR text found")
            log_stage_complete("OCR Verification", False)
    finally:
        session.close()
    
    # Check Chunking
    log_stage_start("Chunking Verification")
    session = next(db_manager.get_session())
    try:
        chunk_result = session.execute(
            text("""
                SELECT COUNT(*) as count,
                       MIN(char_start_index) as min_start,
                       MAX(char_end_index) as max_end
                FROM document_chunks 
                WHERE document_uuid = :uuid
            """),
            {'uuid': TEST_DOCUMENT_UUID}
        ).fetchone()
        
        if chunk_result and chunk_result.count > 0:
            print(f"✅ Chunks created: {chunk_result.count}")
            print(f"✅ Character range: {chunk_result.min_start} - {chunk_result.max_end}")
            results['chunking'] = True
            log_stage_complete("Chunking Verification", True)
        else:
            print("❌ No chunks found")
            log_stage_complete("Chunking Verification", False)
    finally:
        session.close()
    
    # Check Entity Extraction
    log_stage_start("Entity Extraction Verification")
    session = next(db_manager.get_session())
    try:
        entity_result = session.execute(
            text("""
                SELECT COUNT(*) as count,
                       COUNT(DISTINCT entity_type) as types
                FROM entity_mentions 
                WHERE document_uuid = :uuid
            """),
            {'uuid': TEST_DOCUMENT_UUID}
        ).fetchone()
        
        if entity_result and entity_result.count > 0:
            print(f"✅ Entity mentions: {entity_result.count}")
            print(f"✅ Entity types: {entity_result.types}")
            results['entity_extraction'] = True
            log_stage_complete("Entity Extraction Verification", True)
        else:
            print("❌ No entity mentions found")
            log_stage_complete("Entity Extraction Verification", False)
    finally:
        session.close()
    
    # Check Entity Resolution
    log_stage_start("Entity Resolution Verification")
    session = next(db_manager.get_session())
    try:
        resolution_result = session.execute(
            text("""
                SELECT COUNT(DISTINCT ce.canonical_entity_uuid) as canonical_count,
                       COUNT(em.mention_uuid) as mention_count
                FROM entity_mentions em
                LEFT JOIN canonical_entities ce ON em.canonical_entity_uuid = ce.canonical_entity_uuid
                WHERE em.document_uuid = :uuid
                AND em.canonical_entity_uuid IS NOT NULL
            """),
            {'uuid': TEST_DOCUMENT_UUID}
        ).fetchone()
        
        if resolution_result and resolution_result.canonical_count > 0:
            print(f"✅ Canonical entities: {resolution_result.canonical_count}")
            print(f"✅ Resolved mentions: {resolution_result.mention_count}")
            results['entity_resolution'] = True
            log_stage_complete("Entity Resolution Verification", True)
        else:
            print("❌ No resolved entities found")
            log_stage_complete("Entity Resolution Verification", False)
    finally:
        session.close()
    
    # Check Relationships
    log_stage_start("Relationship Building Verification")
    session = next(db_manager.get_session())
    try:
        rel_result = session.execute(
            text("""
                SELECT relationship_type, COUNT(*) as count
                FROM relationship_staging
                WHERE document_uuid = :uuid
                GROUP BY relationship_type
            """),
            {'uuid': TEST_DOCUMENT_UUID}
        ).fetchall()
        
        if rel_result:
            total_rels = sum(r.count for r in rel_result)
            print(f"✅ Total relationships: {total_rels}")
            for rel in rel_result:
                print(f"   - {rel.relationship_type}: {rel.count}")
            results['relationships'] = True
            log_stage_complete("Relationship Building Verification", True)
        else:
            print("❌ No relationships found")
            log_stage_complete("Relationship Building Verification", False)
    finally:
        session.close()
    
    # Check Finalization
    log_stage_start("Pipeline Finalization Verification")
    session = next(db_manager.get_session())
    try:
        final_result = session.execute(
            text("""
                SELECT status, processing_completed_at
                FROM source_documents
                WHERE document_uuid = :uuid
            """),
            {'uuid': TEST_DOCUMENT_UUID}
        ).fetchone()
        
        if final_result and final_result.status == 'completed':
            print(f"✅ Document status: {final_result.status}")
            print(f"✅ Completed at: {final_result.processing_completed_at}")
            results['finalization'] = True
            log_stage_complete("Pipeline Finalization Verification", True)
        else:
            print(f"❌ Document status: {final_result.status if final_result else 'unknown'}")
            log_stage_complete("Pipeline Finalization Verification", False)
    finally:
        session.close()
    
    return results

def trigger_missing_stages(results):
    """Trigger any missing pipeline stages"""
    print("\n🔧 TRIGGERING MISSING STAGES")
    
    db_manager = DatabaseManager()
    
    # If OCR is missing, start from the beginning
    if not results['ocr']:
        print("\n🚀 Starting OCR extraction...")
        session = next(db_manager.get_session())
        try:
            # Get document info
            doc_info = session.execute(
                text("SELECT file_path, project_uuid FROM source_documents WHERE document_uuid = :uuid"),
                {'uuid': TEST_DOCUMENT_UUID}
            ).fetchone()
            
            if doc_info:
                # Convert local path to S3 key
                file_path = f"documents/{TEST_DOCUMENT_UUID}.pdf"
                
                from scripts.pdf_tasks import extract_text_from_document
                task = extract_text_from_document.delay(TEST_DOCUMENT_UUID, file_path)
                print(f"✅ OCR task started: {task.id}")
                
                # Wait for OCR to complete
                print("⏳ Waiting for OCR to complete...")
                time.sleep(10)
                
                # Poll for completion
                max_wait = 120
                start_time = time.time()
                while time.time() - start_time < max_wait:
                    state = check_pipeline_state(TEST_DOCUMENT_UUID)
                    ocr_state = state.get('ocr', {}).get('status')
                    
                    if ocr_state == 'completed':
                        print("✅ OCR completed!")
                        break
                    elif ocr_state == 'failed':
                        print("❌ OCR failed!")
                        return False
                    
                    time.sleep(5)
                    print(f"⏳ Still waiting... ({int(time.time() - start_time)}s)", end='\r')
                
        finally:
            session.close()
    
    # Check if chunking needs to be triggered
    elif not results['chunking']:
        print("\n🚀 Starting chunking...")
        session = next(db_manager.get_session())
        try:
            # Get OCR text
            text_result = session.execute(
                text("SELECT raw_extracted_text FROM source_documents WHERE document_uuid = :uuid"),
                {'uuid': TEST_DOCUMENT_UUID}
            ).fetchone()
            
            if text_result and text_result.raw_extracted_text:
                from scripts.pdf_tasks import chunk_document_text
                task = chunk_document_text.delay(TEST_DOCUMENT_UUID, text_result.raw_extracted_text)
                print(f"✅ Chunking task started: {task.id}")
                time.sleep(5)
        finally:
            session.close()
    
    # Continue with other stages if needed...
    
    return True

def run_comprehensive_test():
    """Run the comprehensive end-to-end test"""
    print("\n" + "="*80)
    print("🧪 END-TO-END PIPELINE TEST (EXISTING DOCUMENT)")
    print("📋 Based on context_324_e2e_verification_characteristics.md")
    print("="*80)
    
    # Get document info
    doc_info = get_document_info()
    if not doc_info:
        return
    
    # Initial verification
    print("\n📊 INITIAL STATE CHECK")
    initial_results = verify_all_stages()
    
    # Count completed stages
    completed_stages = sum(1 for v in initial_results.values() if v)
    total_stages = len(initial_results)
    
    print(f"\n📈 Initial Pipeline Status: {completed_stages}/{total_stages} stages completed")
    
    # If not all stages are complete, trigger missing ones
    if completed_stages < total_stages:
        print(f"\n⚠️  {total_stages - completed_stages} stages incomplete")
        
        # Trigger missing stages
        if trigger_missing_stages(initial_results):
            # Wait a bit for processing
            print("\n⏳ Waiting 30 seconds for pipeline to progress...")
            time.sleep(30)
            
            # Re-verify
            print("\n📊 FINAL STATE CHECK")
            final_results = verify_all_stages()
            completed_stages = sum(1 for v in final_results.values() if v)
    else:
        final_results = initial_results
    
    # Calculate total time
    total_time = sum(stage_timings.values())
    
    # Generate summary
    print("\n" + "="*80)
    print("📊 PIPELINE TEST SUMMARY")
    print("="*80)
    
    success_rate = (completed_stages / total_stages) * 100
    print(f"\n✅ Success Rate: {success_rate:.1f}% ({completed_stages}/{total_stages} stages)")
    print(f"⏱️  Total Verification Time: {total_time:.2f} seconds")
    
    print("\n📈 Stage Status:")
    for stage, status in final_results.items():
        icon = "✅" if status else "❌"
        print(f"   {icon} {stage}")
    
    # Check pipeline state details
    state = check_pipeline_state(TEST_DOCUMENT_UUID)
    print("\n📋 Pipeline State Details:")
    for stage, info in state.items():
        if isinstance(info, dict) and 'status' in info:
            print(f"   {stage}: {info['status']}")
            if 'metadata' in info and 'error' in info['metadata']:
                print(f"      Error: {info['metadata']['error']}")
    
    # Overall assessment
    print("\n🏁 FINAL ASSESSMENT:")
    if success_rate >= 99:
        print("✅ PIPELINE MEETS 99% SUCCESS RATE TARGET!")
    else:
        print(f"❌ Success rate {success_rate:.1f}% is below 99% target")
        
        # Identify bottlenecks
        print("\n🔍 IDENTIFIED BOTTLENECKS:")
        for stage, status in final_results.items():
            if not status:
                print(f"   - {stage} stage failed or incomplete")
    
    # Save results
    results_file = f"e2e_test_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(results_file, 'w') as f:
        json.dump({
            'document_uuid': TEST_DOCUMENT_UUID,
            'timestamp': datetime.utcnow().isoformat(),
            'results': final_results,
            'success_rate': success_rate,
            'pipeline_state': state,
            'meets_target': success_rate >= 99
        }, f, indent=2)
    
    print(f"\n💾 Results saved to: {results_file}")
    
    return final_results

if __name__ == "__main__":
    try:
        results = run_comprehensive_test()
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()