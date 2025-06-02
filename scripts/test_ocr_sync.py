#!/usr/bin/env python3
"""
Test OCR processing synchronously (bypassing Celery)
"""

import os
import sys
from pathlib import Path
from datetime import datetime
import uuid
from sqlalchemy import text

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.db import DatabaseManager
from scripts.cache import get_redis_manager
from scripts.s3_storage import S3StorageManager
from scripts.pdf_tasks import extract_text_from_document
from scripts.core.model_factory import get_source_document_model

def test_sync_ocr():
    """Test OCR processing synchronously"""
    print("=" * 80)
    print("SYNCHRONOUS OCR TEST")
    print("=" * 80)
    
    # Initialize components
    db_manager = DatabaseManager(validate_conformance=False)
    redis_manager = get_redis_manager()
    s3_manager = S3StorageManager()
    
    # Use test file
    test_file = "/opt/legal-doc-processor/input_docs/Paul, Michael (Acuity)/Paul, Michael - Wombat Corp Disclosure Stmt 10-23-24.pdf"
    
    if not os.path.exists(test_file):
        print(f"❌ Test file not found: {test_file}")
        return
        
    # Generate UUID
    doc_uuid = str(uuid.uuid4())
    file_name = os.path.basename(test_file)
    
    print(f"\n1. Creating document record...")
    print(f"   UUID: {doc_uuid}")
    
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
        s3_uri = f"s3://{s3_bucket}/{s3_key}"
        
        print(f"   ✓ Uploaded to: {s3_uri}")
        print(f"   ✓ Region: {upload_result['s3_region']}")
        
        # Create database record
        print(f"\n3. Creating database record...")
        DocumentModel = get_source_document_model()
        
        doc_data = {
            'document_uuid': doc_uuid,
            'project_uuid': "e0c57112-c755-4798-bc1f-4ecc3f0eec78",
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
        print(f"   ✓ Document created")
        
        # Verify in database
        print(f"\n4. Verifying document exists...")
        test_doc = db_manager.get_source_document(doc_uuid)
        if test_doc:
            print(f"   ✓ Document found in database")
        else:
            print(f"   ❌ Document NOT found in database!")
            return
            
        # Store metadata
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
        
        # Now test OCR synchronously
        print(f"\n6. Testing OCR synchronously...")
        
        # Create a mock Celery task context
        class MockTask:
            def __init__(self):
                self.request = type('obj', (object,), {'id': 'sync-test-task'})
                self.name = 'extract_text_from_document'
                self.db_manager = DatabaseManager(validate_conformance=False)
                
            def validate_conformance(self):
                # Mock validation
                pass
                
        mock_task = MockTask()
        
        # Call the task function directly
        result = extract_text_from_document(mock_task, doc_uuid, s3_uri)
        
        print(f"\n   ✓ OCR completed successfully!")
        print(f"   Result keys: {list(result.keys())}")
        
        # Check if chunks were created
        for session in db_manager.get_session():
            chunk_result = session.execute(
                text("SELECT COUNT(*) FROM document_chunks WHERE document_id = :doc_id"),
                {"doc_id": doc_uuid}
            )
            chunk_count = chunk_result.scalar()
            print(f"   Chunks created: {chunk_count}")
            break
            
    except Exception as e:
        print(f"\n   ❌ Error: {e}")
        import traceback
        traceback.print_exc()
        
    print("\n" + "=" * 80)
    print("TEST COMPLETE")
    print("=" * 80)

if __name__ == "__main__":
    test_sync_ocr()