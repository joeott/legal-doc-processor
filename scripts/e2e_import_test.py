#!/usr/bin/env python3
"""
End-to-End Import Test Script
Import selected legal documents and track their processing.
"""
import os
import sys
import json
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

# Test documents to import
TEST_DOCUMENTS = [
    "/opt/legal-doc-processor/input_docs/Paul, Michael (Acuity)/Paul, Michael - Wombat Corp Disclosure Stmt 10-23-24.pdf",
    "/opt/legal-doc-processor/input_docs/Paul, Michael (Acuity)/Paul, Michael - Riverdale Disclosure Stmt 10-25-24.pdf",
    "/opt/legal-doc-processor/input_docs/Paul, Michael (Acuity)/Paul, Michael - Plaintiff Acuity Disclosure Stmt 9-20-24.pdf",
    "/opt/legal-doc-processor/input_docs/Paul, Michael (Acuity)/Paul, Michael - Lora Prop Disclosure Stmt 10-21-24.pdf",
    "/opt/legal-doc-processor/input_docs/Paul, Michael (Acuity)/Paul, Michael - Acuity Answer to Counterclaim 1-23-25.pdf"
]

def import_document(file_path, db_manager, s3_manager, project_uuid=None):
    """Import a single document"""
    print(f"\n{'='*60}")
    print(f"📄 Importing: {Path(file_path).name}")
    print(f"{'='*60}")
    
    DocumentModel = get_source_document_model()
    
    # Generate valid project UUID if not provided
    if project_uuid is None:
        project_uuid = str(uuid.uuid4())
    
    # Check file exists
    if not os.path.exists(file_path):
        print(f"❌ File not found: {file_path}")
        return None
        
    file_size = os.path.getsize(file_path)
    file_name = os.path.basename(file_path)
    
    # Generate document UUID first
    doc_uuid = str(uuid.uuid4())
    
    # Upload to S3
    print("📤 Uploading to S3...")
    try:
        upload_result = s3_manager.upload_document_with_uuid_naming(
            file_path, 
            doc_uuid,
            file_name
        )
        s3_key = upload_result['s3_key']
        s3_url = upload_result.get('s3_url', f"s3://{s3_manager.private_bucket_name}/{s3_key}")
        print(f"✅ Uploaded to S3: {s3_key}")
    except Exception as e:
        print(f"❌ S3 upload failed: {e}")
        import traceback
        traceback.print_exc()
        return None
    
    # Create document record
    
    try:
        doc_model = DocumentModel(
            document_uuid=doc_uuid,
            project_uuid=project_uuid,
            file_name=file_name,
            original_file_name=file_name,
            file_path=file_path,
            file_size=file_size,
            mime_type='application/pdf',
            s3_key=s3_key,
            s3_bucket=os.environ.get('S3_PRIMARY_DOCUMENT_BUCKET'),
            upload_timestamp=datetime.utcnow(),
            processing_status='pending'
        )
        
        # Store in database
        doc = db_manager.create_source_document(doc_model)
        print(f"✅ Created document record: {doc.document_uuid}")
        
        # Store metadata in Redis
        redis_manager = get_redis_manager()
        metadata_key = f"doc:metadata:{doc.document_uuid}"
        redis_manager.store_dict(metadata_key, {
            'project_uuid': project_uuid,
            'document_metadata': {
                'title': file_name,
                'created_at': datetime.utcnow().isoformat(),
                's3_url': s3_url
            }
        })
        
        # Submit for processing with S3 URI
        print("🚀 Submitting for OCR processing...")
        s3_uri = f"s3://{s3_manager.private_bucket_name}/{s3_key}"
        task = extract_text_from_document.apply_async(
            args=[doc.document_uuid, s3_uri]
        )
        print(f"✅ OCR task submitted: {task.id}")
        
        return {
            'document_uuid': str(doc.document_uuid),
            'file_name': file_name,
            'task_id': task.id,
            'submitted_at': datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        print(f"❌ Import failed: {e}")
        import traceback
        traceback.print_exc()
        return None

def main():
    """Run E2E import test"""
    print("=== E2E Document Import Test ===")
    print(f"Testing with {len(TEST_DOCUMENTS)} documents")
    print(f"Start time: {datetime.now()}")
    
    # Initialize services
    db_manager = DatabaseManager()
    s3_manager = S3StorageManager()
    
    # Use existing project UUID
    test_project_uuid = "e0c57112-c755-4798-bc1f-4ecc3f0eec78"  # Test Legal Project
    print(f"Using existing project UUID: {test_project_uuid}")
    
    # Import documents
    imported_docs = []
    
    for doc_path in TEST_DOCUMENTS:
        result = import_document(doc_path, db_manager, s3_manager, test_project_uuid)
        if result:
            imported_docs.append(result)
        time.sleep(2)  # Small delay between imports
    
    # Summary
    print(f"\n{'='*60}")
    print("📊 Import Summary")
    print(f"{'='*60}")
    print(f"Total documents: {len(TEST_DOCUMENTS)}")
    print(f"Successfully imported: {len(imported_docs)}")
    print(f"Failed: {len(TEST_DOCUMENTS) - len(imported_docs)}")
    
    # Save results for tracking
    results_file = "/opt/legal-doc-processor/e2e_test_results.json"
    with open(results_file, 'w') as f:
        json.dump({
            'test_run': datetime.utcnow().isoformat(),
            'documents': imported_docs
        }, f, indent=2)
    
    print(f"\n✅ Results saved to: {results_file}")
    print("\nUse the monitor to track processing:")
    print("  python scripts/cli/monitor.py live")
    
    return len(imported_docs) == len(TEST_DOCUMENTS)

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)