#!/usr/bin/env python3
"""Simple document status check"""
import os
import sys
import time
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.supabase_utils import SupabaseManager

def check_document_status(doc_uuid):
    """Check status of a specific document"""
    db = SupabaseManager()
    
    print(f"🔍 Checking status for document: {doc_uuid}")
    
    try:
        result = db.client.table('source_documents')\
            .select('id, original_file_name, celery_status, celery_task_id, error_message')\
            .eq('document_uuid', doc_uuid)\
            .single()\
            .execute()
            
        if result.data:
            doc = result.data
            print(f"\n📄 Document: {doc['original_file_name']}")
            print(f"   ID: {doc['id']}")
            print(f"   Status: {doc.get('celery_status', 'None')}")
            print(f"   Task ID: {doc.get('celery_task_id', 'None')}")
            if doc.get('error_message'):
                print(f"   ❌ Error: {doc['error_message']}")
        else:
            print("❌ Document not found")
            
    except Exception as e:
        print(f"❌ Error checking status: {e}")

if __name__ == "__main__":
    # Check the document we just submitted
    check_document_status('57493510-37c4-4afb-a446-a529dcfe7908')