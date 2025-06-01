#!/usr/bin/env python3
"""Process a pending document through Celery"""
import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.supabase_utils import SupabaseManager
from scripts.celery_submission import submit_document_to_celery

def process_pending_document():
    """Find and process a pending document"""
    db = SupabaseManager()
    
    print("🔍 Looking for pending documents...")
    
    # Get a pending document
    result = db.client.table('source_documents')\
        .select('*')\
        .eq('celery_status', 'pending')\
        .limit(1)\
        .execute()
    
    if not result.data:
        print("❌ No pending documents found")
        return
        
    doc = result.data[0]
    print(f"\n📄 Found pending document:")
    print(f"   ID: {doc['id']}")
    print(f"   UUID: {doc['document_uuid']}")
    print(f"   File: {doc['original_file_name']}")
    print(f"   Path: {doc['original_file_path']}")
    
    # Check if file exists
    file_path = doc['original_file_path']
    if file_path.startswith('s3://'):
        print(f"   ✅ File is in S3: {file_path}")
    else:
        # Check local file
        if os.path.exists(file_path):
            print(f"   ✅ Local file exists")
        else:
            print(f"   ⚠️  Local file not found, will try S3 path")
            # Construct S3 path if needed
            if doc.get('s3_bucket') and doc.get('s3_key'):
                file_path = f"s3://{doc['s3_bucket']}/{doc['s3_key']}"
                print(f"   📍 Using S3 path: {file_path}")
    
    # Submit to Celery
    print(f"\n🚀 Submitting to Celery...")
    
    try:
        task_id, success = submit_document_to_celery(
            document_id=doc['id'],
            document_uuid=doc['document_uuid'],
            file_path=file_path,
            file_type=doc['detected_file_type'] or 'pdf',
            file_name=doc['original_file_name'],
            project_sql_id=doc['project_fk_id']
        )
        
        if success:
            print(f"✅ Submitted successfully!")
            print(f"   Task ID: {task_id}")
            print(f"\n📊 Check status with:")
            print(f"   python scripts/check_celery_status.py")
            print(f"   python scripts/debug_celery_document.py --uuid {doc['document_uuid']}")
        else:
            print(f"❌ Failed to submit to Celery")
            
    except Exception as e:
        print(f"❌ Error submitting to Celery: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    process_pending_document()