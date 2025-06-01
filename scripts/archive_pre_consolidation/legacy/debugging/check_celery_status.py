#!/usr/bin/env python3
"""Check Celery status of existing documents"""
import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.supabase_utils import SupabaseManager

def check_status():
    db = SupabaseManager()
    result = db.client.table('source_documents').select('id, original_file_name, celery_status, celery_task_id, error_message').execute()
    
    print("📊 Document Celery Status Report")
    print("=" * 80)
    
    for doc in result.data:
        status = doc.get('celery_status', 'None')
        task_id = doc.get('celery_task_id', '')[:8] + '...' if doc.get('celery_task_id') else 'None'
        error = doc.get('error_message', '')
        
        # Status emoji
        emoji = "⏳" if status == "pending" else "✅" if status == "completed" else "❌" if status and status.endswith("_failed") else "🔄"
        
        print(f"{emoji} ID: {doc['id']:3d} | {doc['original_file_name'][:40]:40s} | {status:20s} | Task: {task_id}")
        if error:
            print(f"   └─ Error: {error[:60]}...")
    
    # Summary
    print("\n📈 Summary:")
    statuses = {}
    for doc in result.data:
        status = doc.get('celery_status', 'no_status')
        statuses[status] = statuses.get(status, 0) + 1
    
    for status, count in sorted(statuses.items()):
        print(f"  {status}: {count}")
        
if __name__ == "__main__":
    check_status()