#!/usr/bin/env python3
"""
Comprehensive End-to-End Pipeline Test
Based on context_324_e2e_verification_characteristics.md
"""

import os
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scripts.celery_app import app
from scripts.pdf_tasks import process_pdf_document
from scripts.db import DatabaseManager
from scripts.cache import get_redis_manager, CacheKeys
from scripts.rds_utils import insert_record, execute_query
from sqlalchemy import text
import json

# Test configuration
TEST_PROJECT_UUID = str(uuid.uuid4())
TEST_DOCUMENT_UUID = str(uuid.uuid4())
TEST_PDF_PATH = "input_docs/sample_legal_doc.pdf"

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

def setup_test_environment():
    """Set up test project and document"""
    print("\n🔧 SETTING UP TEST ENVIRONMENT")
    
    db_manager = DatabaseManager()
    session = next(db_manager.get_session())
    
    try:
        # Create test project
        project_data = {
            'project_uuid': TEST_PROJECT_UUID,
            'project_name': f'E2E Test Project {datetime.now().strftime("%Y%m%d_%H%M%S")}',
            'client_matter_id': 'TEST-001',
            'created_at': datetime.utcnow()
        }
        
        result = session.execute(
            text("""
                INSERT INTO projects (project_uuid, project_name, client_matter_id, created_at)
                VALUES (:project_uuid, :project_name, :client_matter_id, :created_at)
                ON CONFLICT (project_uuid) DO NOTHING
                RETURNING project_uuid
            """),
            project_data
        )
        session.commit()
        print(f"✅ Created test project: {TEST_PROJECT_UUID}")
        
        # Create test document
        doc_data = {
            'document_uuid': TEST_DOCUMENT_UUID,
            'project_uuid': TEST_PROJECT_UUID,
            'file_name': 'test_document.pdf',
            'file_path': TEST_PDF_PATH,
            'file_size': 1024,
            'mime_type': 'application/pdf',
            'status': 'pending',
            'created_at': datetime.utcnow()
        }
        
        result = session.execute(
            text("""
                INSERT INTO source_documents 
                (document_uuid, project_uuid, file_name, file_path, file_size, mime_type, status, created_at)
                VALUES 
                (:document_uuid, :project_uuid, :file_name, :file_path, :file_size, :mime_type, :status, :created_at)
                RETURNING document_uuid
            """),
            doc_data
        )
        session.commit()
        print(f"✅ Created test document: {TEST_DOCUMENT_UUID}")
        
    finally:
        session.close()
    
    return TEST_PROJECT_UUID, TEST_DOCUMENT_UUID

def check_pipeline_state(document_uuid: str):
    """Check current pipeline state from Redis"""
    redis_manager = get_redis_manager()
    state_key = CacheKeys.DOC_STATE.format(document_uuid=document_uuid)
    state = redis_manager.get_dict(state_key) or {}
    return state

def verify_ocr_stage(document_uuid: str, max_wait: int = 120):
    """Verify OCR extraction stage"""
    log_stage_start("OCR Extraction")
    
    db_manager = DatabaseManager()
    redis_manager = get_redis_manager()
    
    start_time = time.time()
    while time.time() - start_time < max_wait:
        # Check pipeline state
        state = check_pipeline_state(document_uuid)
        ocr_state = state.get('ocr', {})
        
        if ocr_state.get('status') == 'completed':
            # Verify database
            session = next(db_manager.get_session())
            try:
                result = session.execute(
                    text("""
                        SELECT raw_extracted_text, ocr_completed_at, ocr_provider 
                        FROM source_documents 
                        WHERE document_uuid = :uuid
                    """),
                    {'uuid': document_uuid}
                ).fetchone()
                
                if result and result.raw_extracted_text:
                    # Verify cache
                    cache_key = CacheKeys.DOC_OCR_RESULT.format(document_uuid=document_uuid)
                    cached = redis_manager.get_dict(cache_key)
                    
                    print(f"✅ Text extracted: {len(result.raw_extracted_text)} characters")
                    print(f"✅ OCR completed at: {result.ocr_completed_at}")
                    print(f"✅ OCR provider: {result.ocr_provider}")
                    print(f"✅ Redis cache: {'Present' if cached else 'Missing'}")
                    
                    log_stage_complete("OCR Extraction", True)
                    return True, result.raw_extracted_text
                    
            finally:
                session.close()
        
        elif ocr_state.get('status') == 'failed':
            error = ocr_state.get('metadata', {}).get('error', 'Unknown error')
            print(f"❌ OCR failed: {error}")
            log_stage_complete("OCR Extraction", False)
            return False, None
        
        time.sleep(2)
        print(f"⏳ Waiting for OCR... ({int(time.time() - start_time)}s)", end='\r')
    
    print(f"\n❌ OCR timed out after {max_wait} seconds")
    log_stage_complete("OCR Extraction", False)
    return False, None

def verify_chunking_stage(document_uuid: str, expected_text_length: int, max_wait: int = 30):
    """Verify text chunking stage"""
    log_stage_start("Text Chunking")
    
    db_manager = DatabaseManager()
    redis_manager = get_redis_manager()
    
    start_time = time.time()
    while time.time() - start_time < max_wait:
        state = check_pipeline_state(document_uuid)
        chunk_state = state.get('chunking', {})
        
        if chunk_state.get('status') == 'completed':
            # Verify database
            session = next(db_manager.get_session())
            try:
                result = session.execute(
                    text("""
                        SELECT COUNT(*) as count, 
                               MIN(char_start_index) as min_start,
                               MAX(char_end_index) as max_end,
                               SUM(LENGTH(text)) as total_chars
                        FROM document_chunks 
                        WHERE document_uuid = :uuid
                    """),
                    {'uuid': document_uuid}
                ).fetchone()
                
                if result and result.count > 0:
                    # Verify cache
                    cache_key = CacheKeys.DOC_CHUNKS.format(document_uuid=document_uuid)
                    cached = redis_manager.get_dict(cache_key)
                    
                    print(f"✅ Chunks created: {result.count}")
                    print(f"✅ Character range: {result.min_start} - {result.max_end}")
                    print(f"✅ Total characters: {result.total_chars}")
                    print(f"✅ Redis cache: {'Present' if cached else 'Missing'}")
                    
                    # Verify word boundaries preserved
                    chunks = session.execute(
                        text("SELECT text FROM document_chunks WHERE document_uuid = :uuid ORDER BY chunk_index LIMIT 2"),
                        {'uuid': document_uuid}
                    ).fetchall()
                    
                    for i, chunk in enumerate(chunks):
                        print(f"📄 Chunk {i} preview: {chunk.text[:50]}...")
                    
                    log_stage_complete("Text Chunking", True)
                    return True, result.count
                    
            finally:
                session.close()
        
        elif chunk_state.get('status') == 'failed':
            error = chunk_state.get('metadata', {}).get('error', 'Unknown error')
            print(f"❌ Chunking failed: {error}")
            log_stage_complete("Text Chunking", False)
            return False, 0
        
        time.sleep(1)
        print(f"⏳ Waiting for chunking... ({int(time.time() - start_time)}s)", end='\r')
    
    print(f"\n❌ Chunking timed out after {max_wait} seconds")
    log_stage_complete("Text Chunking", False)
    return False, 0

def verify_entity_extraction_stage(document_uuid: str, chunk_count: int, max_wait: int = 60):
    """Verify entity extraction stage"""
    log_stage_start("Entity Extraction")
    
    redis_manager = get_redis_manager()
    
    start_time = time.time()
    while time.time() - start_time < max_wait:
        state = check_pipeline_state(document_uuid)
        entity_state = state.get('entity_extraction', {})
        
        if entity_state.get('status') == 'completed':
            # Check cache
            cache_key = CacheKeys.DOC_ENTITY_MENTIONS.format(document_uuid=document_uuid)
            cached = redis_manager.get_dict(cache_key)
            
            if cached and 'mentions' in cached:
                mentions = cached['mentions']
                
                # Analyze entity types
                entity_types = {}
                for mention in mentions:
                    entity_type = mention.get('entity_type', 'UNKNOWN')
                    entity_types[entity_type] = entity_types.get(entity_type, 0) + 1
                
                print(f"✅ Entity mentions extracted: {len(mentions)}")
                print(f"✅ Entity types breakdown:")
                for entity_type, count in entity_types.items():
                    print(f"   - {entity_type}: {count}")
                
                # Verify allowed types only
                allowed_types = {'PERSON', 'ORG', 'LOCATION', 'DATE'}
                invalid_types = set(entity_types.keys()) - allowed_types
                if invalid_types:
                    print(f"⚠️  Warning: Invalid entity types found: {invalid_types}")
                
                log_stage_complete("Entity Extraction", True)
                return True, len(mentions)
            else:
                print("⚠️  No mentions found in cache")
                
        elif entity_state.get('status') == 'failed':
            error = entity_state.get('metadata', {}).get('error', 'Unknown error')
            print(f"❌ Entity extraction failed: {error}")
            log_stage_complete("Entity Extraction", False)
            return False, 0
        
        time.sleep(1)
        print(f"⏳ Waiting for entity extraction... ({int(time.time() - start_time)}s)", end='\r')
    
    print(f"\n❌ Entity extraction timed out after {max_wait} seconds")
    log_stage_complete("Entity Extraction", False)
    return False, 0

def verify_entity_resolution_stage(document_uuid: str, mention_count: int, max_wait: int = 30):
    """Verify entity resolution stage"""
    log_stage_start("Entity Resolution")
    
    db_manager = DatabaseManager()
    redis_manager = get_redis_manager()
    
    start_time = time.time()
    while time.time() - start_time < max_wait:
        state = check_pipeline_state(document_uuid)
        resolution_state = state.get('entity_resolution', {})
        
        if resolution_state.get('status') == 'completed':
            # Verify database
            session = next(db_manager.get_session())
            try:
                # Check entity mentions
                mentions_result = session.execute(
                    text("""
                        SELECT COUNT(*) as total,
                               COUNT(DISTINCT canonical_entity_uuid) as canonical_count,
                               COUNT(canonical_entity_uuid) as resolved_count
                        FROM entity_mentions 
                        WHERE document_uuid = :uuid
                    """),
                    {'uuid': document_uuid}
                ).fetchone()
                
                # Check canonical entities
                canonical_result = session.execute(
                    text("""
                        SELECT ce.entity_type, ce.canonical_name, COUNT(em.mention_uuid) as mention_count
                        FROM canonical_entities ce
                        JOIN entity_mentions em ON em.canonical_entity_uuid = ce.canonical_entity_uuid
                        WHERE em.document_uuid = :uuid
                        GROUP BY ce.canonical_entity_uuid, ce.entity_type, ce.canonical_name
                        ORDER BY mention_count DESC
                    """),
                    {'uuid': document_uuid}
                ).fetchall()
                
                if mentions_result and canonical_result:
                    dedup_rate = ((mention_count - len(canonical_result)) / mention_count * 100) if mention_count > 0 else 0
                    
                    print(f"✅ Entity mentions in DB: {mentions_result.total}")
                    print(f"✅ Mentions with canonical UUID: {mentions_result.resolved_count}")
                    print(f"✅ Unique canonical entities: {len(canonical_result)}")
                    print(f"✅ Deduplication rate: {dedup_rate:.1f}%")
                    
                    print("\n📊 Top canonical entities:")
                    for i, entity in enumerate(canonical_result[:5]):
                        print(f"   {i+1}. {entity.entity_type}: {entity.canonical_name} ({entity.mention_count} mentions)")
                    
                    log_stage_complete("Entity Resolution", True)
                    return True, len(canonical_result)
                    
            finally:
                session.close()
        
        elif resolution_state.get('status') == 'failed':
            error = resolution_state.get('metadata', {}).get('error', 'Unknown error')
            print(f"❌ Entity resolution failed: {error}")
            log_stage_complete("Entity Resolution", False)
            return False, 0
        
        time.sleep(1)
        print(f"⏳ Waiting for entity resolution... ({int(time.time() - start_time)}s)", end='\r')
    
    print(f"\n❌ Entity resolution timed out after {max_wait} seconds")
    log_stage_complete("Entity Resolution", False)
    return False, 0

def verify_relationship_building_stage(document_uuid: str, max_wait: int = 30):
    """Verify relationship building stage"""
    log_stage_start("Relationship Building")
    
    db_manager = DatabaseManager()
    
    start_time = time.time()
    while time.time() - start_time < max_wait:
        state = check_pipeline_state(document_uuid)
        relationship_state = state.get('relationships', {})
        
        if relationship_state.get('status') == 'completed':
            # Verify database
            session = next(db_manager.get_session())
            try:
                result = session.execute(
                    text("""
                        SELECT relationship_type, COUNT(*) as count
                        FROM relationship_staging
                        WHERE document_uuid = :uuid
                        GROUP BY relationship_type
                        ORDER BY count DESC
                    """),
                    {'uuid': document_uuid}
                ).fetchall()
                
                if result:
                    total_relationships = sum(r.count for r in result)
                    
                    print(f"✅ Total relationships: {total_relationships}")
                    print(f"✅ Relationship types:")
                    for rel in result:
                        print(f"   - {rel.relationship_type}: {rel.count}")
                    
                    # Verify expected relationship types
                    expected_types = {'Document→Project', 'Chunk→Document', 'Mention→Chunk', 'Mention→Canonical'}
                    found_types = {r.relationship_type for r in result}
                    
                    if expected_types.issubset(found_types):
                        print("✅ All expected relationship types present")
                    else:
                        missing = expected_types - found_types
                        print(f"⚠️  Missing relationship types: {missing}")
                    
                    log_stage_complete("Relationship Building", True)
                    return True, total_relationships
                    
            finally:
                session.close()
        
        elif relationship_state.get('status') == 'failed':
            error = relationship_state.get('metadata', {}).get('error', 'Unknown error')
            print(f"❌ Relationship building failed: {error}")
            log_stage_complete("Relationship Building", False)
            return False, 0
        
        time.sleep(1)
        print(f"⏳ Waiting for relationship building... ({int(time.time() - start_time)}s)", end='\r')
    
    print(f"\n❌ Relationship building timed out after {max_wait} seconds")
    log_stage_complete("Relationship Building", False)
    return False, 0

def verify_pipeline_finalization(document_uuid: str, max_wait: int = 30):
    """Verify pipeline finalization"""
    log_stage_start("Pipeline Finalization")
    
    db_manager = DatabaseManager()
    
    start_time = time.time()
    while time.time() - start_time < max_wait:
        state = check_pipeline_state(document_uuid)
        pipeline_state = state.get('pipeline', {})
        
        if pipeline_state.get('status') == 'completed':
            # Verify database
            session = next(db_manager.get_session())
            try:
                result = session.execute(
                    text("""
                        SELECT status, processing_completed_at
                        FROM source_documents
                        WHERE document_uuid = :uuid
                    """),
                    {'uuid': document_uuid}
                ).fetchone()
                
                if result and result.status == 'completed':
                    print(f"✅ Document status: {result.status}")
                    print(f"✅ Processing completed at: {result.processing_completed_at}")
                    
                    # Check final stats
                    stats = pipeline_state.get('metadata', {})
                    print(f"✅ Final statistics:")
                    print(f"   - Chunks: {stats.get('chunk_count', 'N/A')}")
                    print(f"   - Entities: {stats.get('entity_count', 'N/A')}")
                    print(f"   - Relationships: {stats.get('relationship_count', 'N/A')}")
                    
                    log_stage_complete("Pipeline Finalization", True)
                    return True
                    
            finally:
                session.close()
        
        elif pipeline_state.get('status') == 'failed':
            error = pipeline_state.get('metadata', {}).get('error', 'Unknown error')
            print(f"❌ Pipeline finalization failed: {error}")
            log_stage_complete("Pipeline Finalization", False)
            return False
        
        time.sleep(1)
        print(f"⏳ Waiting for pipeline finalization... ({int(time.time() - start_time)}s)", end='\r')
    
    print(f"\n❌ Pipeline finalization timed out after {max_wait} seconds")
    log_stage_complete("Pipeline Finalization", False)
    return False

def run_comprehensive_test():
    """Run the comprehensive end-to-end test"""
    print("\n" + "="*80)
    print("🧪 COMPREHENSIVE END-TO-END PIPELINE TEST")
    print("📋 Based on context_324_e2e_verification_characteristics.md")
    print("="*80)
    
    # Setup
    project_uuid, document_uuid = setup_test_environment()
    
    # Start pipeline
    print(f"\n🚀 INITIATING PIPELINE for document {document_uuid}")
    task = process_pdf_document.delay(
        document_uuid=document_uuid,
        file_path=TEST_PDF_PATH,
        project_uuid=project_uuid,
        document_metadata={
            'title': 'E2E Test Document',
            'test_run': True,
            'timestamp': datetime.utcnow().isoformat()
        }
    )
    print(f"📋 Pipeline task ID: {task.id}")
    
    # Track results
    results = {
        'stages': {},
        'timings': {},
        'success_count': 0,
        'total_stages': 6
    }
    
    # Stage 1: OCR Extraction
    ocr_success, extracted_text = verify_ocr_stage(document_uuid)
    results['stages']['ocr'] = ocr_success
    if ocr_success:
        results['success_count'] += 1
    
    if not ocr_success:
        print("\n❌ Pipeline failed at OCR stage")
        return results
    
    # Stage 2: Text Chunking
    chunk_success, chunk_count = verify_chunking_stage(document_uuid, len(extracted_text))
    results['stages']['chunking'] = chunk_success
    if chunk_success:
        results['success_count'] += 1
    
    if not chunk_success:
        print("\n❌ Pipeline failed at chunking stage")
        return results
    
    # Stage 3: Entity Extraction
    entity_success, mention_count = verify_entity_extraction_stage(document_uuid, chunk_count)
    results['stages']['entity_extraction'] = entity_success
    if entity_success:
        results['success_count'] += 1
    
    if not entity_success:
        print("\n❌ Pipeline failed at entity extraction stage")
        return results
    
    # Stage 4: Entity Resolution
    resolution_success, canonical_count = verify_entity_resolution_stage(document_uuid, mention_count)
    results['stages']['entity_resolution'] = resolution_success
    if resolution_success:
        results['success_count'] += 1
    
    if not resolution_success:
        print("\n❌ Pipeline failed at entity resolution stage")
        return results
    
    # Stage 5: Relationship Building
    relationship_success, relationship_count = verify_relationship_building_stage(document_uuid)
    results['stages']['relationships'] = relationship_success
    if relationship_success:
        results['success_count'] += 1
    
    if not relationship_success:
        print("\n❌ Pipeline failed at relationship building stage")
        return results
    
    # Stage 6: Pipeline Finalization
    finalization_success = verify_pipeline_finalization(document_uuid)
    results['stages']['finalization'] = finalization_success
    if finalization_success:
        results['success_count'] += 1
    
    # Calculate total time
    total_time = sum(stage_timings.values())
    results['timings'] = stage_timings
    results['total_time'] = total_time
    
    # Generate summary
    print("\n" + "="*80)
    print("📊 PIPELINE TEST SUMMARY")
    print("="*80)
    
    success_rate = (results['success_count'] / results['total_stages']) * 100
    print(f"\n✅ Success Rate: {success_rate:.1f}% ({results['success_count']}/{results['total_stages']} stages)")
    print(f"⏱️  Total Time: {total_time:.2f} seconds")
    
    print("\n📈 Stage Performance:")
    for stage, timing in stage_timings.items():
        status = "✅" if results['stages'].get(stage.lower().replace(' ', '_'), False) else "❌"
        print(f"   {status} {stage}: {timing:.2f}s")
    
    # Check against targets
    print("\n🎯 Performance vs Targets:")
    targets = {
        'OCR Extraction': 60,
        'Text Chunking': 2,
        'Entity Extraction': 10,
        'Entity Resolution': 5,
        'Relationship Building': 3,
        'Pipeline Finalization': 5
    }
    
    for stage, target in targets.items():
        actual = stage_timings.get(stage, 0)
        if actual > 0:
            status = "✅" if actual <= target else "⚠️"
            print(f"   {status} {stage}: {actual:.2f}s (target: {target}s)")
    
    # Overall assessment
    print("\n🏁 FINAL ASSESSMENT:")
    if success_rate >= 99 and total_time <= 90:
        print("✅ PIPELINE MEETS 99% SUCCESS RATE TARGET!")
        print("✅ TOTAL TIME UNDER 90 SECOND TARGET!")
    else:
        if success_rate < 99:
            print(f"❌ Success rate {success_rate:.1f}% is below 99% target")
        if total_time > 90:
            print(f"❌ Total time {total_time:.2f}s exceeds 90 second target")
    
    # Save results
    results_file = f"e2e_test_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(results_file, 'w') as f:
        json.dump({
            'document_uuid': document_uuid,
            'project_uuid': project_uuid,
            'timestamp': datetime.utcnow().isoformat(),
            'results': results,
            'success_rate': success_rate,
            'meets_target': success_rate >= 99 and total_time <= 90
        }, f, indent=2)
    
    print(f"\n💾 Results saved to: {results_file}")
    
    return results

if __name__ == "__main__":
    try:
        results = run_comprehensive_test()
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()