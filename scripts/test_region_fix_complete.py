#!/usr/bin/env python3
"""
Complete test of region fix with proper document creation
"""
import os
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

# Set environment variables
os.environ['USE_MINIMAL_MODELS'] = 'true'
os.environ['SKIP_CONFORMANCE_CHECK'] = 'true'

from scripts.db import DatabaseManager
from scripts.s3_storage import S3StorageManager
from scripts.pdf_tasks import extract_text_from_document
from scripts.cache import get_redis_manager
from scripts.core.model_factory import get_source_document_model
from sqlalchemy import text

def test_complete_pipeline():
    """Test complete pipeline with region fix"""
    print("="*80)
    print("COMPLETE REGION FIX TEST")
    print("="*80)
    
    # Initialize managers
    db_manager = DatabaseManager(validate_conformance=False)
    s3_manager = S3StorageManager()
    redis_manager = get_redis_manager()
    
    print(f"✓ S3 Bucket: {s3_manager.private_bucket_name}")
    print(f"✓ S3 Region: {s3_manager.s3_client.meta.region_name}")
    print(f"✓ Database connected")
    print(f"✓ Redis connected")
    
    # Test file
    test_file = "/opt/legal-doc-processor/input_docs/Paul, Michael (Acuity)/Paul, Michael - Wombat Corp Disclosure Stmt 10-23-24.pdf"
    
    if not os.path.exists(test_file):
        print(f"❌ Test file not found: {test_file}")
        return
    
    # Create new document UUID
    doc_uuid = str(uuid.uuid4())
    file_name = os.path.basename(test_file)
    
    print(f"\n1. Creating document record...")
    print(f"   UUID: {doc_uuid}")
    print(f"   File: {file_name}")
    
    try:
        # Upload to S3
        print(f"\n2. Uploading to S3...")
        upload_result = s3_manager.upload_document_with_uuid_naming(
            test_file, 
            doc_uuid,
            file_name
        )
        
        s3_key = upload_result['s3_key']
        s3_bucket = upload_result['s3_bucket']
        print(f"   ✓ Uploaded to: s3://{s3_bucket}/{s3_key}")
        print(f"   ✓ Using region: {upload_result['s3_region']}")
        
        # Create database record using minimal model
        print(f"\n3. Creating database record...")
        DocumentModel = get_source_document_model()
        
        # Create minimal document data
        doc_data = {
            'document_uuid': doc_uuid,
            'project_uuid': "e0c57112-c755-4798-bc1f-4ecc3f0eec78",  # Test project
            'file_name': file_name,
            'original_file_name': file_name,
            'file_path': test_file,
            'file_size_bytes': os.path.getsize(test_file),
            's3_key': s3_key,
            's3_bucket': s3_bucket,
            's3_region': upload_result['s3_region'],
            'status': 'pending',
            'created_at': datetime.utcnow()
        }
        
        doc_model = DocumentModel(**doc_data)
        doc = db_manager.create_source_document(doc_model)
        print(f"   ✓ Document created in database")
        
        # Add delay to ensure transaction visibility across connections
        import time
        time.sleep(1)  # Wait 1 second for transaction to be visible to other connections
        
        # Verify document exists
        print(f"\n4. Verifying document in database...")
        for session in db_manager.get_session():
            result = session.execute(
                text("SELECT document_uuid, file_name, s3_key FROM source_documents WHERE document_uuid = :uuid"),
                {"uuid": doc_uuid}
            )
            row = result.first()
            if row:
                print(f"   ✓ Document found: {row[0]}")
                print(f"   ✓ File name: {row[1]}")
                print(f"   ✓ S3 key: {row[2]}")
            else:
                print(f"   ❌ Document not found!")
                return
            break
        
        # Store metadata in Redis
        print(f"\n5. Storing metadata in Redis...")
        metadata_key = f"doc:metadata:{doc_uuid}"
        redis_manager.store_dict(metadata_key, {
            'project_uuid': "e0c57112-c755-4798-bc1f-4ecc3f0eec78",
            'document_metadata': {
                'title': file_name,
                'test_run': True,
                'created_at': datetime.utcnow().isoformat()
            }
        })
        print(f"   ✓ Metadata stored")
        
        # Submit OCR task
        print(f"\n6. Submitting OCR task...")
        s3_uri = f"s3://{s3_bucket}/{s3_key}"
        print(f"   S3 URI: {s3_uri}")
        print(f"   Region: {upload_result['s3_region']}")
        
        task = extract_text_from_document.apply_async(
            args=[doc_uuid, s3_uri]
        )
        
        print(f"   ✓ Task submitted: {task.id}")
        
        # Monitor task
        print(f"\n7. Monitoring task progress...")
        for i in range(30):  # 30 seconds timeout
            if task.ready():
                if task.successful():
                    print(f"   ✓ Task completed successfully!")
                    print(f"   Result: {task.result}")
                else:
                    print(f"   ❌ Task failed!")
                    print(f"   Error: {task.info}")
                break
            
            # Check document status
            for session in db_manager.get_session():
                result = session.execute(
                    text("SELECT celery_status, textract_job_id, textract_job_status FROM source_documents WHERE document_uuid = :uuid"),
                    {"uuid": doc_uuid}
                )
                row = result.first()
                if row:
                    print(f"   [{i:2d}s] Celery: {row[0]}, Textract ID: {row[1]}, Textract Status: {row[2]}")
                break
            
            time.sleep(1)
        
        # Final status check
        print(f"\n8. Final status check...")
        for session in db_manager.get_session():
            # Check document
            result = session.execute(
                text("""
                    SELECT status, celery_status, textract_job_id, textract_job_status,
                           ocr_provider, ocr_completed_at, error_message
                    FROM source_documents 
                    WHERE document_uuid = :uuid
                """),
                {"uuid": doc_uuid}
            )
            row = result.first()
            if row:
                print(f"   Document status: {row[0]}")
                print(f"   Celery status: {row[1]}")
                print(f"   Textract job ID: {row[2]}")
                print(f"   Textract status: {row[3]}")
                print(f"   OCR provider: {row[4]}")
                print(f"   OCR completed: {row[5]}")
                if row[6]:
                    print(f"   Error: {row[6]}")
            
            # Check chunks
            result = session.execute(
                text("SELECT COUNT(*) FROM document_chunks WHERE document_uuid = :uuid"),
                {"uuid": doc_uuid}
            )
            chunk_count = result.scalar()
            print(f"\n   Chunks created: {chunk_count}")
            
            break
        
        print(f"\n{'='*80}")
        print("TEST COMPLETE")
        print("="*80)
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_complete_pipeline()