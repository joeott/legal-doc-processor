#!/usr/bin/env python3
"""
Monitor pipeline to completion - tracking all success criteria from context_300
"""

import os
import sys
import time
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.db import DatabaseManager
from scripts.cache import get_redis_manager
from sqlalchemy import text

def monitor_document_pipeline(document_uuid: str, timeout: int = 600):
    """Monitor document through all pipeline stages"""
    print("=" * 80)
    print(f"PIPELINE MONITORING - Document: {document_uuid}")
    print("=" * 80)
    
    db = DatabaseManager(validate_conformance=False)
    redis = get_redis_manager()
    start_time = time.time()
    
    success_criteria = {
        'ocr': {'met': False, 'details': {}},
        'chunking': {'met': False, 'details': {}},
        'entities': {'met': False, 'details': {}},
        'resolution': {'met': False, 'details': {}},
        'relationships': {'met': False, 'details': {}}
    }
    
    while time.time() - start_time < timeout:
        elapsed = int(time.time() - start_time)
        session = next(db.get_session())
        
        try:
            # 1. Check OCR Status
            ocr_result = session.execute(
                text("""
                    SELECT textract_job_id, textract_job_status, ocr_completed_at,
                           raw_extracted_text IS NOT NULL as has_text,
                           error_message, celery_status, ocr_provider
                    FROM source_documents 
                    WHERE document_uuid = :uuid
                """),
                {"uuid": document_uuid}
            ).first()
            
            if ocr_result:
                success_criteria['ocr']['details'] = {
                    'job_id': ocr_result[0],
                    'job_status': ocr_result[1],
                    'completed_at': ocr_result[2],
                    'has_text': ocr_result[3],
                    'error': ocr_result[4],
                    'celery_status': ocr_result[5],
                    'provider': ocr_result[6]
                }
                
                # OCR Success: Job ID exists, status is SUCCEEDED, text extracted
                if ocr_result[0] and ocr_result[1] == 'SUCCEEDED' and ocr_result[3]:
                    success_criteria['ocr']['met'] = True
            
            # 2. Check Chunking Status
            chunk_result = session.execute(
                text("""
                    SELECT COUNT(*), AVG(LENGTH(chunk_text))
                    FROM document_chunks 
                    WHERE document_uuid = :uuid
                """),
                {"uuid": document_uuid}
            ).first()
            
            chunk_count = chunk_result[0] if chunk_result else 0
            avg_chunk_size = int(chunk_result[1]) if chunk_result and chunk_result[1] else 0
            
            success_criteria['chunking']['details'] = {
                'count': chunk_count,
                'avg_size': avg_chunk_size
            }
            
            # Chunking Success: > 5 chunks created
            if chunk_count > 5:
                success_criteria['chunking']['met'] = True
            
            # 3. Check Entity Extraction
            entity_result = session.execute(
                text("""
                    SELECT COUNT(*), COUNT(DISTINCT entity_type)
                    FROM entity_mentions em
                    JOIN document_chunks dc ON em.chunk_fk_id = dc.id
                    WHERE dc.document_uuid = :uuid
                """),
                {"uuid": document_uuid}
            ).first()
            
            entity_count = entity_result[0] if entity_result else 0
            entity_types = entity_result[1] if entity_result else 0
            
            success_criteria['entities']['details'] = {
                'count': entity_count,
                'types': entity_types
            }
            
            # Entity Success: > 10 entities extracted
            if entity_count > 10:
                success_criteria['entities']['met'] = True
            
            # 4. Check Entity Resolution
            resolution_result = session.execute(
                text("""
                    SELECT COUNT(DISTINCT em.canonical_fk_id)
                    FROM entity_mentions em
                    JOIN document_chunks dc ON em.chunk_fk_id = dc.id
                    WHERE dc.document_uuid = :uuid
                    AND em.canonical_fk_id IS NOT NULL
                """),
                {"uuid": document_uuid}
            ).first()
            
            canonical_count = resolution_result[0] if resolution_result else 0
            
            success_criteria['resolution']['details'] = {
                'canonical_count': canonical_count
            }
            
            # Resolution Success: Canonical entities created
            if canonical_count > 0:
                success_criteria['resolution']['met'] = True
            
            # 5. Check Relationships
            relationship_result = session.execute(
                text("""
                    SELECT COUNT(*)
                    FROM relationship_staging rs
                    WHERE rs.source_fk_id IN (
                        SELECT DISTINCT em.canonical_fk_id
                        FROM entity_mentions em
                        JOIN document_chunks dc ON em.chunk_fk_id = dc.id
                        WHERE dc.document_uuid = :uuid
                    )
                """),
                {"uuid": document_uuid}
            ).first()
            
            relationship_count = relationship_result[0] if relationship_result else 0
            
            success_criteria['relationships']['details'] = {
                'count': relationship_count
            }
            
            # Relationship Success: Relationships identified
            if relationship_count > 0:
                success_criteria['relationships']['met'] = True
            
            # Check Redis state
            state_key = f"doc:state:{document_uuid}"
            doc_state = redis.get_dict(state_key)
            
        finally:
            session.close()
        
        # Display status
        print(f"\n[{elapsed}s] Pipeline Status Update:")
        print("-" * 60)
        
        for stage, info in success_criteria.items():
            icon = "✅" if info['met'] else "⏳"
            print(f"{icon} {stage.upper()}:")
            for key, value in info['details'].items():
                print(f"   {key}: {value}")
        
        if doc_state:
            print(f"\nRedis State Summary:")
            for key, value in doc_state.items():
                if isinstance(value, dict) and 'status' in value:
                    print(f"   {key}: {value.get('status', 'unknown')}")
        
        # Check if all criteria met
        all_met = all(s['met'] for s in success_criteria.values())
        if all_met:
            print("\n" + "=" * 80)
            print("🎉 ALL SUCCESS CRITERIA MET! PIPELINE COMPLETED SUCCESSFULLY!")
            print("=" * 80)
            
            # Final summary
            print("\nFinal Summary:")
            print(f"  ✅ OCR: Textract job {success_criteria['ocr']['details']['job_id']}")
            print(f"  ✅ Chunking: {success_criteria['chunking']['details']['count']} chunks")
            print(f"  ✅ Entities: {success_criteria['entities']['details']['count']} entities")
            print(f"  ✅ Resolution: {success_criteria['resolution']['details']['canonical_count']} canonical")
            print(f"  ✅ Relationships: {success_criteria['relationships']['details']['count']} relationships")
            
            return True
        
        # Check for errors
        if success_criteria['ocr']['details'].get('error'):
            print(f"\n❌ ERROR: {success_criteria['ocr']['details']['error']}")
            return False
        
        time.sleep(10)  # Check every 10 seconds
    
    print("\n⏰ TIMEOUT: Pipeline did not complete within {timeout} seconds")
    return False


def run_complete_test():
    """Run a complete end-to-end test"""
    print("Creating new test document...")
    
    # Run the test to create a document
    import subprocess
    result = subprocess.run([
        'python3', 'scripts/test_region_fix_complete.py'
    ], capture_output=True, text=True)
    
    # Extract UUID from output
    import re
    uuid_match = re.search(r'UUID: ([a-f0-9-]{36})', result.stdout)
    
    if uuid_match:
        document_uuid = uuid_match.group(1)
        print(f"Document created: {document_uuid}")
        print("\nStarting pipeline monitoring...")
        
        success = monitor_document_pipeline(document_uuid)
        
        if success:
            print("\n✅ END-TO-END TEST PASSED!")
        else:
            print("\n❌ END-TO-END TEST FAILED!")
            
        return success
    else:
        print("❌ Could not create test document")
        print(result.stdout)
        print(result.stderr)
        return False


if __name__ == "__main__":
    if len(sys.argv) > 1:
        # Monitor specific document
        monitor_document_pipeline(sys.argv[1])
    else:
        # Run complete test
        run_complete_test()