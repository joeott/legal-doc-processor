#!/usr/bin/env python3
"""
Simple success monitoring focusing on key milestones
"""

import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.db import DatabaseManager
from scripts.cache import get_redis_manager
from sqlalchemy import text

def monitor_success(document_uuid: str, timeout: int = 300):
    """Monitor document for key success indicators"""
    print("=" * 80)
    print(f"SUCCESS CRITERIA MONITORING")
    print(f"Document: {document_uuid}")
    print("=" * 80)
    
    db = DatabaseManager(validate_conformance=False)
    redis = get_redis_manager()
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        elapsed = int(time.time() - start_time)
        session = next(db.get_session())
        
        try:
            # Check main document status
            result = session.execute(
                text("""
                    SELECT 
                        textract_job_id,
                        textract_job_status,
                        ocr_completed_at,
                        raw_extracted_text IS NOT NULL as has_text,
                        error_message,
                        celery_status,
                        (SELECT COUNT(*) FROM document_chunks WHERE document_uuid = d.document_uuid) as chunks
                    FROM source_documents d
                    WHERE document_uuid = :uuid
                """),
                {"uuid": document_uuid}
            ).first()
            
            if not result:
                print(f"[{elapsed}s] Document not found!")
                return False
                
            job_id = result[0]
            job_status = result[1]
            ocr_completed = result[2]
            has_text = result[3]
            error = result[4]
            celery_status = result[5]
            chunk_count = result[6]
            
            # Display current status
            print(f"\n[{elapsed}s] Status Update:")
            print("-" * 60)
            print(f"Celery Status: {celery_status}")
            print(f"Textract Job ID: {job_id}")
            print(f"Textract Status: {job_status}")
            print(f"OCR Completed: {ocr_completed}")
            print(f"Has Extracted Text: {has_text}")
            print(f"Chunks Created: {chunk_count}")
            
            if error:
                print(f"Error: {error}")
            
            # Check Redis for additional state
            state_key = f"doc:state:{document_uuid}"
            doc_state = redis.get_dict(state_key)
            if doc_state:
                print("\nPipeline States:")
                for stage, info in doc_state.items():
                    if isinstance(info, dict) and 'status' in info:
                        print(f"  {stage}: {info['status']}")
            
            # Success criteria check
            if job_id and job_status == 'SUCCEEDED' and has_text and chunk_count > 0:
                print("\n" + "=" * 80)
                print("🎉 SUCCESS! All key criteria met:")
                print(f"  ✅ Textract job completed: {job_id}")
                print(f"  ✅ Text extracted from document")
                print(f"  ✅ {chunk_count} chunks created")
                print("=" * 80)
                return True
                
        finally:
            session.close()
        
        time.sleep(5)
    
    print(f"\n⏰ Timeout after {timeout} seconds")
    return False

if __name__ == "__main__":
    if len(sys.argv) > 1:
        document_uuid = sys.argv[1]
    else:
        # Get the most recent document
        db = DatabaseManager(validate_conformance=False)
        session = next(db.get_session())
        result = session.execute(
            text("""
                SELECT document_uuid 
                FROM source_documents 
                ORDER BY created_at DESC 
                LIMIT 1
            """)
        ).first()
        session.close()
        
        if result:
            document_uuid = str(result[0])
            print(f"Monitoring most recent document: {document_uuid}")
        else:
            print("No documents found!")
            sys.exit(1)
    
    monitor_success(document_uuid)