#!/usr/bin/env python3
"""
Verify Celery migration is complete and working
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.supabase_utils import SupabaseManager
from scripts.redis_utils import get_redis_manager
import subprocess

def verify_migration():
    """Run verification checks"""
    print("🔍 Verifying Celery Migration...")
    
    # 1. Check database schema
    print("\n1️⃣ Checking database schema...")
    db = SupabaseManager()
    
    # Check for celery_task_id column
    try:
        result = db.client.table('source_documents').select('celery_task_id, celery_status').limit(1).execute()
        print("✅ celery_task_id and celery_status columns exist")
    except Exception as e:
        print(f"❌ Error checking schema: {e}")
        return False
    
    # 2. Check if config.py was updated
    print("\n2️⃣ Checking configuration updates...")
    try:
        from scripts.config import DOCUMENT_INTAKE_DIR
        print(f"✅ DOCUMENT_INTAKE_DIR configured: {DOCUMENT_INTAKE_DIR}")
    except ImportError:
        print("❌ DOCUMENT_INTAKE_DIR not found in config.py")
    
    # 3. Check Redis connectivity (basic)
    print("\n3️⃣ Checking Redis connectivity...")
    try:
        redis_mgr = get_redis_manager()
        if redis_mgr and redis_mgr.is_available():
            redis_client = redis_mgr.get_client()
            # Just check we can connect, don't check queues yet
            print("✅ Redis connection available")
            
            # Check if we can access Redis (without Celery)
            try:
                # Try to get queue lengths directly
                for queue in ['default', 'ocr', 'text', 'entity', 'graph']:
                    length = redis_client.llen(queue)
                    print(f"   Queue '{queue}': {length} tasks")
            except Exception as e:
                print(f"   ⚠️  Could not check queue lengths: {e}")
        else:
            print("❌ Redis not available")
    except Exception as e:
        print(f"❌ Redis error: {e}")
    
    # 4. Check no new entries in document_processing_queue
    print("\n4️⃣ Checking deprecated queue usage...")
    try:
        from datetime import datetime, timedelta, timezone
        one_hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        
        queue_result = db.client.table('document_processing_queue')\
            .select('id', count='exact')\
            .gte('created_at', one_hour_ago)\
            .execute()
        
        if queue_result.count == 0:
            print("✅ No new entries in document_processing_queue (last hour)")
        else:
            print(f"⚠️  Found {queue_result.count} recent entries in deprecated queue")
    except Exception as e:
        print(f"   ℹ️  Could not check queue (may not exist): {e}")
    
    # 5. Check celery_submission.py exists
    print("\n5️⃣ Checking Celery submission utility...")
    celery_submission_path = os.path.join(os.path.dirname(__file__), 'celery_submission.py')
    if os.path.exists(celery_submission_path):
        print("✅ celery_submission.py exists")
        # Try to import it
        try:
            from scripts.celery_submission import submit_document_to_celery
            print("✅ Can import submit_document_to_celery function")
        except Exception as e:
            print(f"❌ Error importing: {e}")
    else:
        print("❌ celery_submission.py not found")
    
    # 6. Check monitoring updates
    print("\n6️⃣ Checking monitoring updates...")
    monitor_path = os.path.join(os.path.dirname(__file__), 'standalone_pipeline_monitor.py')
    if os.path.exists(monitor_path):
        # Check if it's been updated to use celery_status
        with open(monitor_path, 'r') as f:
            content = f.read()
            if 'celery_status' in content and 'Document Processing Status (Celery-based)' in content:
                print("✅ Pipeline monitor updated for Celery")
            else:
                print("⚠️  Pipeline monitor may need updates")
    
    # 7. Summary of document statuses
    print("\n7️⃣ Current document status summary...")
    try:
        response = db.client.table('source_documents')\
            .select('celery_status, initial_processing_status')\
            .execute()
        
        if response.data:
            from collections import Counter
            celery_statuses = Counter(item.get('celery_status', 'not_set') for item in response.data)
            
            print("   Celery status distribution:")
            for status, count in sorted(celery_statuses.items()):
                print(f"     - {status}: {count}")
        else:
            print("   No documents found")
    except Exception as e:
        print(f"   Error getting status summary: {e}")
    
    print("\n✅ Migration verification complete!")
    print("\nNext steps:")
    print("1. Start Celery workers: ./scripts/start_celery_workers.sh")
    print("2. Run pipeline monitor: python scripts/standalone_pipeline_monitor.py")
    print("3. Submit a test document to verify end-to-end flow")

if __name__ == "__main__":
    verify_migration()