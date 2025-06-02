#!/usr/bin/env python3
"""
Comprehensive pipeline test that monitors all stages to completion
"""

import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.db import DatabaseManager
from scripts.cache import get_redis_manager
from sqlalchemy import text

def monitor_pipeline_completion(document_uuid: str, timeout: int = 300):
    """Monitor all pipeline stages until completion or timeout"""
    db = DatabaseManager(validate_conformance=False)
    redis = get_redis_manager()
    start_time = time.time()
    
    stages = {
        'ocr': {'status': 'pending', 'details': {}},
        'chunking': {'status': 'pending', 'details': {}},
        'entities': {'status': 'pending', 'details': {}},
        'resolution': {'status': 'pending', 'details': {}},
        'relationships': {'status': 'pending', 'details': {}}
    }
    
    print(f"\nMonitoring pipeline for document: {document_uuid}")
    print(f"Timeout: {timeout} seconds")
    print("=" * 70)
    
    while time.time() - start_time < timeout:
        # Check document status
        session = next(db.get_session())
        
        try:
            # 1. OCR Status
            doc_result = session.execute(
                text("""SELECT textract_job_id, textract_job_status, ocr_completed_at,
                               raw_extracted_text IS NOT NULL as has_text,
                               error_message
                        FROM source_documents WHERE document_uuid = :uuid"""),
                {"uuid": document_uuid}
            ).first()
            
            if doc_result:
                stages['ocr']['details'] = {
                    'job_id': doc_result[0],
                    'status': doc_result[1],
                    'completed': doc_result[2],
                    'has_text': doc_result[3],
                    'error': doc_result[4]
                }
                if doc_result[2]:  # ocr_completed_at
                    stages['ocr']['status'] = 'completed'
                elif doc_result[4]:  # error_message
                    stages['ocr']['status'] = 'failed'
            
            # 2. Chunking Status
            chunk_count = session.execute(
                text("SELECT COUNT(*) FROM document_chunks WHERE document_uuid = :uuid"),
                {"uuid": document_uuid}
            ).scalar()
            
            stages['chunking']['details'] = {'chunk_count': chunk_count}
            if chunk_count > 0:
                stages['chunking']['status'] = 'completed'
            
            # 3. Entity Status
            entity_count = session.execute(
                text("""SELECT COUNT(*) FROM entity_mentions em
                        JOIN document_chunks dc ON em.document_chunk_id = dc.id
                        WHERE dc.document_uuid = :uuid"""),
                {"uuid": document_uuid}
            ).scalar()
            
            stages['entities']['details'] = {'entity_count': entity_count}
            if entity_count > 0:
                stages['entities']['status'] = 'completed'
                
            # 4. Canonical Entities Status
            canonical_count = session.execute(
                text("""SELECT COUNT(DISTINCT em.canonical_entity_id) 
                        FROM entity_mentions em
                        JOIN document_chunks dc ON em.document_chunk_id = dc.id
                        WHERE dc.document_id = :uuid AND em.canonical_entity_id IS NOT NULL"""),
                {"uuid": document_uuid}
            ).scalar()
            
            stages['resolution']['details'] = {'canonical_count': canonical_count}
            if canonical_count > 0:
                stages['resolution']['status'] = 'completed'
                
            # 5. Relationships Status
            relationship_count = session.execute(
                text("""SELECT COUNT(*) FROM relationship_staging rs
                        WHERE rs.source_entity_id IN (
                            SELECT DISTINCT em.canonical_entity_id 
                            FROM entity_mentions em
                            JOIN document_chunks dc ON em.document_chunk_id = dc.id
                            WHERE dc.document_uuid = :uuid
                        )"""),
                {"uuid": document_uuid}
            ).scalar()
            
            stages['relationships']['details'] = {'relationship_count': relationship_count}
            if relationship_count > 0:
                stages['relationships']['status'] = 'completed'
            
            # 6. Check Redis state
            state_key = f"doc:state:{document_uuid}"
            doc_state = redis.get_dict(state_key)
            
            # 7. Check Celery task status
            celery_status = session.execute(
                text("SELECT celery_status FROM source_documents WHERE document_uuid = :uuid"),
                {"uuid": document_uuid}
            ).scalar()
            
        finally:
            session.close()
        
        # Print status
        elapsed = int(time.time() - start_time)
        print(f"\n[{elapsed}s] Pipeline Status (Celery: {celery_status}):")
        for stage, info in stages.items():
            status_icon = '✅' if info['status'] == 'completed' else ('❌' if info['status'] == 'failed' else '⏳')
            print(f"  {status_icon} {stage}: {info['status']} - {info['details']}")
        
        if doc_state:
            print(f"\nRedis State: {doc_state}")
        
        # Check if all completed
        if all(s['status'] == 'completed' for s in stages.values()):
            print("\n🎉 PIPELINE COMPLETED SUCCESSFULLY!")
            return True
            
        # Check if OCR failed
        if stages['ocr']['status'] == 'failed':
            print(f"\n❌ OCR FAILED: {stages['ocr']['details'].get('error', 'Unknown error')}")
            return False
            
        time.sleep(5)
    
    print("\n⏰ TIMEOUT: Pipeline did not complete in time")
    return False


def run_new_document_test():
    """Run a complete test with a new document"""
    from scripts.test_region_fix_complete import test_complete_region_fix
    
    print("=" * 70)
    print("COMPLETE PIPELINE TEST")
    print("=" * 70)
    
    # First run the region fix test to create a document
    try:
        # Capture the document UUID from the test
        import io
        import contextlib
        
        # Redirect stdout to capture UUID
        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            test_complete_region_fix()
        
        output = f.getvalue()
        
        # Extract UUID from output
        import re
        uuid_match = re.search(r'UUID: ([a-f0-9-]{36})', output)
        if uuid_match:
            document_uuid = uuid_match.group(1)
            print(f"\nDocument created: {document_uuid}")
            
            # Now monitor the pipeline
            success = monitor_pipeline_completion(document_uuid, timeout=300)
            
            if success:
                print("\n✅ Full pipeline test PASSED!")
            else:
                print("\n❌ Full pipeline test FAILED!")
                
            return success
        else:
            print("❌ Could not extract document UUID from test output")
            print(output)
            return False
            
    except Exception as e:
        print(f"❌ Test error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    if len(sys.argv) > 1:
        # Monitor existing document
        doc_uuid = sys.argv[1]
        monitor_pipeline_completion(doc_uuid)
    else:
        # Run new test
        run_new_document_test()