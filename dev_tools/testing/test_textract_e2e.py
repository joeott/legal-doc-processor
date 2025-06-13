#!/usr/bin/env python3
"""End-to-end test for Textract processing"""

import os
import sys
import uuid
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.intake_service import create_document_with_validation
from scripts.pdf_tasks import extract_text_from_document
from scripts.cache import get_redis_manager
from scripts.db import DatabaseManager
from scripts.s3_storage import S3StorageManager

def test_textract_e2e():
    """Test complete Textract flow"""
    
    print("🧪 Starting Textract E2E Test")
    
    # 1. Create test document
    doc_uuid = str(uuid.uuid4())
    test_file = "test_single_doc/Paul, Michael - Lora Prop Disclosure Stmt 10-21-24.pdf"
    
    if not Path(test_file).exists():
        print(f"❌ Test file not found: {test_file}")
        return False
    
    print(f"📄 Using test document: {test_file}")
    
    # 2. Upload to S3
    s3_manager = S3StorageManager()
    result = s3_manager.upload_document_with_uuid_naming(
        test_file, 
        doc_uuid,
        Path(test_file).name
    )
    
    if result['success']:
        s3_key = result['s3_key']
        s3_uri = f"s3://{result['bucket']}/{s3_key}"
        print(f"☁️  Uploaded to S3: {s3_uri}")
    else:
        print(f"❌ Failed to upload to S3: {result['error']}")
        return False
    
    # 3. Create document record with metadata
    try:
        result = create_document_with_validation(
            doc_uuid,
            Path(test_file).name,
            s3_uri.split('/')[2],  # bucket
            s3_key
        )
        print(f"✅ Created document record: {result}")
    except Exception as e:
        print(f"❌ Failed to create document: {e}")
        return False
    
    # 4. Submit to OCR pipeline
    try:
        task_result = extract_text_from_document.apply_async(
            args=[doc_uuid, s3_uri]
        )
        print(f"🚀 Submitted OCR task: {task_result.id}")
        
        # 5. Wait for Textract to start
        time.sleep(5)
        
        # Check document state
        redis_mgr = get_redis_manager()
        state_key = f"doc:state:{doc_uuid}"
        state = redis_mgr.get_dict(state_key)
        
        print(f"📊 Document state: {state}")
        
        if state and state.get('ocr', {}).get('status') == 'processing':
            job_id = state['ocr'].get('metadata', {}).get('job_id')
            if job_id:
                print(f"✅ Textract job started: {job_id}")
                
                # 6. Check database for job record
                db = DatabaseManager()
                session = next(db.get_session())
                from sqlalchemy import text
                
                job_check = session.execute(
                    text("SELECT * FROM textract_jobs WHERE job_id = :job_id"),
                    {'job_id': job_id}
                )
                job_record = job_check.fetchone()
                
                if job_record:
                    print(f"✅ Textract job recorded in database")
                    print(f"   Status: {job_record.job_status}")
                    print(f"   S3 Input: s3://{job_record.s3_input_bucket}/{job_record.s3_input_key}")
                else:
                    print(f"❌ Textract job not found in database")
                
                session.close()
                
                return True
            else:
                print(f"❌ No Textract job ID found")
                return False
        else:
            print(f"❌ Document not in processing state")
            return False
            
    except Exception as e:
        print(f"❌ OCR submission failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_textract_e2e()
    sys.exit(0 if success else 1)