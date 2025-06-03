#!/usr/bin/env python3
"""
Simple OCR monitoring focused on the current blocker
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

def create_and_monitor_document():
    """Create a new document and monitor OCR processing"""
    print("=" * 70)
    print("OCR PROCESSING TEST")
    print("=" * 70)
    
    # First create a new document
    print("\n1. Creating new document...")
    os.system("python3 scripts/test_region_fix_complete.py")
    
    # Get the latest document
    db = DatabaseManager(validate_conformance=False)
    session = next(db.get_session())
    
    latest = session.execute(
        text("""SELECT document_uuid, file_name, s3_key, s3_bucket, created_at
                FROM source_documents 
                ORDER BY created_at DESC 
                LIMIT 1""")
    ).first()
    
    if not latest:
        print("❌ No documents found!")
        return
        
    doc_uuid = str(latest[0])
    print(f"\n2. Monitoring document: {doc_uuid}")
    print(f"   File: {latest[1]}")
    print(f"   S3: s3://{latest[3]}/{latest[2]}")
    
    # Monitor for 60 seconds
    print("\n3. Monitoring OCR status...")
    for i in range(60):
        result = session.execute(
            text("""SELECT celery_status, textract_job_id, textract_job_status, 
                           error_message, ocr_completed_at
                    FROM source_documents 
                    WHERE document_uuid = :uuid"""),
            {"uuid": doc_uuid}
        ).first()
        
        if result:
            celery_status = result[0]
            job_id = result[1]
            job_status = result[2]
            error = result[3]
            completed = result[4]
            
            print(f"\n   [{i}s] Status:")
            print(f"   - Celery: {celery_status}")
            print(f"   - Textract Job ID: {job_id}")
            print(f"   - Textract Status: {job_status}")
            
            if error:
                print(f"   - ❌ ERROR: {error}")
                
                # Try to get more details from Redis
                redis = get_redis_manager()
                state_key = f"doc:state:{doc_uuid}"
                doc_state = redis.get_dict(state_key)
                if doc_state:
                    print(f"   - Redis State: {doc_state}")
                break
                
            if completed:
                print(f"   - ✅ OCR COMPLETED at {completed}")
                break
                
            if job_id and not job_status:
                # Check Textract job directly
                try:
                    import boto3
                    textract = boto3.client('textract', region_name='us-east-2')
                    job_result = textract.get_document_text_detection(JobId=job_id)
                    actual_status = job_result.get('JobStatus')
                    print(f"   - Textract API Status: {actual_status}")
                except Exception as e:
                    print(f"   - Could not check Textract API: {e}")
                    
        time.sleep(1)
        
    session.close()
    
    # Final check
    print("\n4. Final Status:")
    session = next(db.get_session())
    final = session.execute(
        text("""SELECT celery_status, error_message, 
                       raw_extracted_text IS NOT NULL as has_text,
                       (SELECT COUNT(*) FROM document_chunks WHERE document_uuid = :uuid) as chunks
                FROM source_documents 
                WHERE document_uuid = :uuid"""),
        {"uuid": doc_uuid}
    ).first()
    
    if final:
        print(f"   - Final Celery Status: {final[0]}")
        print(f"   - Has Extracted Text: {final[2]}")
        print(f"   - Chunks Created: {final[3]}")
        if final[1]:
            print(f"   - Final Error: {final[1]}")
            
    session.close()
    
    return doc_uuid


if __name__ == "__main__":
    create_and_monitor_document()