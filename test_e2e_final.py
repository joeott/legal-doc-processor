#!/usr/bin/env python3
"""
Final End-to-End Pipeline Test with complete error handling
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

def get_comprehensive_status():
    """Get comprehensive pipeline status for the document"""
    print("\n" + "="*80)
    print("📊 COMPREHENSIVE PIPELINE STATUS CHECK")
    print("="*80)
    
    db_manager = DatabaseManager()
    redis_manager = get_redis_manager()
    
    results = {
        'document_info': {},
        'stages': {
            'ocr': {'status': 'not_started', 'details': {}},
            'chunking': {'status': 'not_started', 'details': {}},
            'entity_extraction': {'status': 'not_started', 'details': {}},
            'entity_resolution': {'status': 'not_started', 'details': {}},
            'relationships': {'status': 'not_started', 'details': {}},
            'finalization': {'status': 'not_started', 'details': {}}
        },
        'metrics': {},
        'errors': []
    }
    
    # 1. Document Info
    print("\n📄 DOCUMENT INFORMATION")
    session = next(db_manager.get_session())
    try:
        doc_result = session.execute(
            text("""
                SELECT document_uuid, file_name, file_path, status,
                       ocr_completed_at, processing_completed_at,
                       created_at, updated_at, celery_task_id
                FROM source_documents
                WHERE document_uuid = :uuid
            """),
            {'uuid': TEST_DOCUMENT_UUID}
        ).fetchone()
        
        if doc_result:
            results['document_info'] = {
                'uuid': str(doc_result.document_uuid),
                'file_name': doc_result.file_name,
                'status': doc_result.status,
                'created_at': str(doc_result.created_at),
                'ocr_completed_at': str(doc_result.ocr_completed_at) if doc_result.ocr_completed_at else None,
                'processing_completed_at': str(doc_result.processing_completed_at) if doc_result.processing_completed_at else None
            }
            
            print(f"✅ Document found: {doc_result.file_name}")
            print(f"   Status: {doc_result.status}")
            print(f"   Created: {doc_result.created_at}")
            
    finally:
        session.close()
    
    # 2. Redis Pipeline State
    print("\n🔄 PIPELINE STATE (Redis)")
    state_key = CacheKeys.DOC_STATE.format(document_uuid=TEST_DOCUMENT_UUID)
    pipeline_state = redis_manager.get_dict(state_key) or {}
    
    for stage_name in ['ocr', 'chunking', 'entity_extraction', 'entity_resolution', 'relationships', 'pipeline']:
        if stage_name in pipeline_state:
            stage_info = pipeline_state[stage_name]
            if isinstance(stage_info, dict):
                status = stage_info.get('status', 'unknown')
                print(f"   {stage_name}: {status}")
                
                # Map pipeline state to our results
                if stage_name == 'pipeline' and status == 'completed':
                    results['stages']['finalization']['status'] = 'completed'
                elif stage_name != 'pipeline':
                    results['stages'][stage_name]['status'] = status
    
    # 3. Stage 1: OCR
    print("\n🔍 STAGE 1: OCR EXTRACTION")
    session = next(db_manager.get_session())
    try:
        ocr_result = session.execute(
            text("""
                SELECT raw_extracted_text, ocr_completed_at, ocr_provider,
                       LENGTH(raw_extracted_text) as text_length,
                       celery_task_id, textract_job_id
                FROM source_documents 
                WHERE document_uuid = :uuid
            """),
            {'uuid': TEST_DOCUMENT_UUID}
        ).fetchone()
        
        if ocr_result and ocr_result.raw_extracted_text:
            results['stages']['ocr']['status'] = 'completed'
            results['stages']['ocr']['details'] = {
                'text_length': ocr_result.text_length,
                'provider': ocr_result.ocr_provider,
                'completed_at': str(ocr_result.ocr_completed_at) if ocr_result.ocr_completed_at else None,
                'job_id': ocr_result.textract_job_id
            }
            print(f"✅ OCR completed: {ocr_result.text_length} characters")
            print(f"   Provider: {ocr_result.ocr_provider}")
            print(f"   Job ID: {ocr_result.textract_job_id}")
        else:
            print("❌ No OCR text found")
            
    finally:
        session.close()
    
    # 4. Stage 2: Chunking
    print("\n🔍 STAGE 2: TEXT CHUNKING")
    session = next(db_manager.get_session())
    try:
        chunk_result = session.execute(
            text("""
                SELECT COUNT(*) as count,
                       MIN(char_start_index) as min_start,
                       MAX(char_end_index) as max_end,
                       AVG(LENGTH(text)) as avg_chunk_size
                FROM document_chunks 
                WHERE document_uuid = :uuid
            """),
            {'uuid': TEST_DOCUMENT_UUID}
        ).fetchone()
        
        if chunk_result and chunk_result.count > 0:
            results['stages']['chunking']['status'] = 'completed'
            results['stages']['chunking']['details'] = {
                'chunk_count': chunk_result.count,
                'char_range': f"{chunk_result.min_start}-{chunk_result.max_end}",
                'avg_chunk_size': float(chunk_result.avg_chunk_size) if chunk_result.avg_chunk_size else 0
            }
            print(f"✅ Chunks created: {chunk_result.count}")
            print(f"   Character range: {chunk_result.min_start}-{chunk_result.max_end}")
            print(f"   Avg chunk size: {chunk_result.avg_chunk_size:.0f} chars")
        else:
            print("❌ No chunks found")
            
    finally:
        session.close()
    
    # 5. Stage 3: Entity Extraction
    print("\n🔍 STAGE 3: ENTITY EXTRACTION")
    session = next(db_manager.get_session())
    try:
        entity_result = session.execute(
            text("""
                SELECT entity_type, COUNT(*) as count
                FROM entity_mentions 
                WHERE document_uuid = :uuid
                GROUP BY entity_type
                ORDER BY count DESC
            """),
            {'uuid': TEST_DOCUMENT_UUID}
        ).fetchall()
        
        if entity_result:
            total_mentions = sum(r.count for r in entity_result)
            results['stages']['entity_extraction']['status'] = 'completed'
            results['stages']['entity_extraction']['details'] = {
                'total_mentions': total_mentions,
                'by_type': {r.entity_type: r.count for r in entity_result}
            }
            print(f"✅ Entity mentions: {total_mentions}")
            for r in entity_result:
                print(f"   {r.entity_type}: {r.count}")
        else:
            print("❌ No entity mentions found")
            
    finally:
        session.close()
    
    # 6. Stage 4: Entity Resolution
    print("\n🔍 STAGE 4: ENTITY RESOLUTION")
    session = next(db_manager.get_session())
    try:
        resolution_result = session.execute(
            text("""
                SELECT 
                    COUNT(DISTINCT em.canonical_entity_uuid) as canonical_count,
                    COUNT(em.mention_uuid) as resolved_mentions,
                    COUNT(CASE WHEN em.canonical_entity_uuid IS NULL THEN 1 END) as unresolved_mentions
                FROM entity_mentions em
                WHERE em.document_uuid = :uuid
            """),
            {'uuid': TEST_DOCUMENT_UUID}
        ).fetchone()
        
        if resolution_result and resolution_result.canonical_count > 0:
            results['stages']['entity_resolution']['status'] = 'completed'
            results['stages']['entity_resolution']['details'] = {
                'canonical_entities': resolution_result.canonical_count,
                'resolved_mentions': resolution_result.resolved_mentions,
                'unresolved_mentions': resolution_result.unresolved_mentions
            }
            print(f"✅ Canonical entities: {resolution_result.canonical_count}")
            print(f"   Resolved mentions: {resolution_result.resolved_mentions}")
            print(f"   Unresolved: {resolution_result.unresolved_mentions}")
            
            # Get top canonical entities
            canonical_details = session.execute(
                text("""
                    SELECT ce.entity_type, ce.canonical_name, COUNT(em.mention_uuid) as mentions
                    FROM canonical_entities ce
                    JOIN entity_mentions em ON em.canonical_entity_uuid = ce.canonical_entity_uuid
                    WHERE em.document_uuid = :uuid
                    GROUP BY ce.canonical_entity_uuid, ce.entity_type, ce.canonical_name
                    ORDER BY mentions DESC
                    LIMIT 5
                """),
                {'uuid': TEST_DOCUMENT_UUID}
            ).fetchall()
            
            if canonical_details:
                print("\n   Top entities:")
                for entity in canonical_details:
                    print(f"   - {entity.entity_type}: {entity.canonical_name} ({entity.mentions} mentions)")
        else:
            print("❌ No resolved entities found")
            
    finally:
        session.close()
    
    # 7. Stage 5: Relationships (check different possible tables)
    print("\n🔍 STAGE 5: RELATIONSHIP BUILDING")
    session = next(db_manager.get_session())
    try:
        # First check if relationship_staging table exists
        table_check = session.execute(
            text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_name = 'relationship_staging'
                )
            """)
        ).scalar()
        
        if table_check:
            # Check for relationships using source_uuid
            rel_result = session.execute(
                text("""
                    SELECT relationship_type, COUNT(*) as count
                    FROM relationship_staging
                    WHERE source_uuid = :uuid OR target_uuid = :uuid
                    GROUP BY relationship_type
                """),
                {'uuid': TEST_DOCUMENT_UUID}
            ).fetchall()
            
            if rel_result:
                total_rels = sum(r.count for r in rel_result)
                results['stages']['relationships']['status'] = 'completed'
                results['stages']['relationships']['details'] = {
                    'total_relationships': total_rels,
                    'by_type': {r.relationship_type: r.count for r in rel_result}
                }
                print(f"✅ Relationships found: {total_rels}")
                for r in rel_result:
                    print(f"   {r.relationship_type}: {r.count}")
            else:
                print("⚠️  No relationships found (table exists but no data)")
        else:
            print("⚠️  relationship_staging table does not exist")
            
    except Exception as e:
        print(f"⚠️  Error checking relationships: {e}")
        results['errors'].append(f"Relationship check error: {str(e)}")
    finally:
        session.close()
    
    # 8. Stage 6: Finalization
    print("\n🔍 STAGE 6: PIPELINE FINALIZATION")
    if results['document_info'].get('processing_completed_at'):
        results['stages']['finalization']['status'] = 'completed'
        results['stages']['finalization']['details'] = {
            'completed_at': results['document_info']['processing_completed_at']
        }
        print(f"✅ Pipeline completed at: {results['document_info']['processing_completed_at']}")
    else:
        print("❌ Pipeline not finalized")
    
    # 9. Calculate metrics
    completed_stages = sum(1 for stage in results['stages'].values() if stage['status'] == 'completed')
    total_stages = len(results['stages'])
    success_rate = (completed_stages / total_stages) * 100
    
    results['metrics'] = {
        'completed_stages': completed_stages,
        'total_stages': total_stages,
        'success_rate': success_rate
    }
    
    # 10. Summary
    print("\n" + "="*80)
    print("📊 PIPELINE SUMMARY")
    print("="*80)
    print(f"\n✅ Success Rate: {success_rate:.1f}% ({completed_stages}/{total_stages} stages)")
    
    print("\n📈 Stage Status:")
    for stage_name, stage_data in results['stages'].items():
        icon = "✅" if stage_data['status'] == 'completed' else "❌"
        print(f"   {icon} {stage_name}: {stage_data['status']}")
    
    # Performance assessment
    print("\n🏁 ASSESSMENT:")
    if success_rate >= 99:
        print("✅ PIPELINE MEETS 99% SUCCESS RATE TARGET!")
    else:
        print(f"❌ Success rate {success_rate:.1f}% is below 99% target")
        
        print("\n🔍 BOTTLENECKS:")
        for stage_name, stage_data in results['stages'].items():
            if stage_data['status'] != 'completed':
                print(f"   - {stage_name}: {stage_data['status']}")
                if stage_name in pipeline_state:
                    error = pipeline_state[stage_name].get('metadata', {}).get('error')
                    if error:
                        print(f"     Error: {error}")
    
    # Save results
    results_file = f"e2e_final_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(results_file, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\n💾 Results saved to: {results_file}")
    
    return results

def trigger_next_stage():
    """Trigger the next incomplete stage in the pipeline"""
    db_manager = DatabaseManager()
    redis_manager = get_redis_manager()
    
    # Get current state
    state_key = CacheKeys.DOC_STATE.format(document_uuid=TEST_DOCUMENT_UUID)
    pipeline_state = redis_manager.get_dict(state_key) or {}
    
    # Check what needs to be done
    session = next(db_manager.get_session())
    try:
        # Check if relationships need to be built
        rel_count = session.execute(
            text("""
                SELECT COUNT(*) 
                FROM relationship_staging
                WHERE source_uuid = :uuid OR target_uuid = :uuid
            """),
            {'uuid': TEST_DOCUMENT_UUID}
        ).scalar()
        
        if rel_count == 0:
            print("\n🚀 Triggering relationship building...")
            
            # Get all required data
            chunks = session.execute(
                text("SELECT chunk_uuid, text, chunk_index FROM document_chunks WHERE document_uuid = :uuid ORDER BY chunk_index"),
                {'uuid': TEST_DOCUMENT_UUID}
            ).fetchall()
            
            entity_mentions = session.execute(
                text("""
                    SELECT em.*, ce.canonical_name
                    FROM entity_mentions em
                    LEFT JOIN canonical_entities ce ON em.canonical_entity_uuid = ce.canonical_entity_uuid
                    WHERE em.document_uuid = :uuid
                """),
                {'uuid': TEST_DOCUMENT_UUID}
            ).fetchall()
            
            canonical_entities = session.execute(
                text("""
                    SELECT DISTINCT ce.*
                    FROM canonical_entities ce
                    JOIN entity_mentions em ON em.canonical_entity_uuid = ce.canonical_entity_uuid
                    WHERE em.document_uuid = :uuid
                """),
                {'uuid': TEST_DOCUMENT_UUID}
            ).fetchall()
            
            if chunks and entity_mentions and canonical_entities:
                # Prepare data
                chunks_data = [{'chunk_uuid': str(c.chunk_uuid), 'chunk_text': c.text, 'chunk_index': c.chunk_index} for c in chunks]
                mentions_data = [dict(row._mapping) for row in entity_mentions]
                entities_data = [dict(row._mapping) for row in canonical_entities]
                
                # Get project UUID
                project_uuid = session.execute(
                    text("SELECT project_uuid FROM source_documents WHERE document_uuid = :uuid"),
                    {'uuid': TEST_DOCUMENT_UUID}
                ).scalar()
                
                # Trigger relationship building
                from scripts.pdf_tasks import build_document_relationships
                task = build_document_relationships.delay(
                    document_uuid=TEST_DOCUMENT_UUID,
                    document_data={'document_uuid': TEST_DOCUMENT_UUID},
                    project_uuid=str(project_uuid),
                    chunks=chunks_data,
                    entity_mentions=mentions_data,
                    canonical_entities=entities_data
                )
                print(f"✅ Relationship building task: {task.id}")
                return True
                
    finally:
        session.close()
    
    return False

if __name__ == "__main__":
    try:
        # Run comprehensive status check
        results = get_comprehensive_status()
        
        # If not at 99%, offer to trigger missing stages
        if results['metrics']['success_rate'] < 99:
            print("\n" + "="*80)
            response = input("Would you like to trigger the missing stages? (y/n): ")
            if response.lower() == 'y':
                if trigger_next_stage():
                    print("\n⏳ Waiting 10 seconds for processing...")
                    time.sleep(10)
                    print("\n🔄 Re-running status check...")
                    results = get_comprehensive_status()
                    
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()