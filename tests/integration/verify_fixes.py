#!/usr/bin/env python3
"""
Quick verification script to check our E2E fixes.
This will check the latest document in the database and verify:
1. Document status is correct
2. All cache keys are populated
3. Processing tasks are tracked
"""

import os
os.environ['SKIP_CONFORMANCE_CHECK'] = 'true'

import sys
sys.path.append('/opt/legal-doc-processor')

from scripts.db import DatabaseManager
from scripts.cache import get_redis_manager, CacheKeys
from scripts.models import ProcessingStatus
from datetime import datetime

def main():
    print("🔍 Verifying E2E Test Fixes")
    print("=" * 50)
    
    # Get database connection
    db_manager = DatabaseManager()
    redis_manager = get_redis_manager()
    
    try:
        # Get latest document
        session = next(db_manager.get_session())
        from sqlalchemy import text
        
        result = session.execute(text("""
            SELECT document_uuid, status, file_name, created_at, processing_completed_at
            FROM source_documents 
            ORDER BY created_at DESC 
            LIMIT 1
        """)).fetchone()
        
        if not result:
            print("❌ No documents found in database")
            return
            
        doc_uuid = str(result[0])
        status = result[1] 
        file_name = result[2]
        created_at = result[3]
        completed_at = result[4]
        
        print(f"📄 Latest Document: {file_name}")
        print(f"   UUID: {doc_uuid}")
        print(f"   Status: {status}")
        print(f"   Created: {created_at}")
        print(f"   Completed: {completed_at}")
        print()
        
        # Check document status
        print("✅ Document Status Verification:")
        if status == ProcessingStatus.PENDING.value:
            print(f"   ✓ Status is 'pending' (not 'uploaded') - Fix #1 VERIFIED")
        elif status == ProcessingStatus.COMPLETED.value:
            print(f"   ✓ Status is 'completed' - Processing successful")
        else:
            print(f"   ⚠️  Status is '{status}' - may still be processing")
        print()
        
        # Check cache keys
        print("🗄️  Cache Keys Verification:")
        cache_keys = [
            ('OCR Result', 'DOC_OCR_RESULT'),
            ('Chunks', 'DOC_CHUNKS'),
            ('All Mentions', 'DOC_ALL_EXTRACTED_MENTIONS'),
            ('Canonical Entities', 'DOC_CANONICAL_ENTITIES'),
            ('Resolved Mentions', 'DOC_RESOLVED_MENTIONS'),
            ('State', 'DOC_STATE')
        ]
        
        cache_results = {}
        for name, key_attr in cache_keys:
            cache_key = CacheKeys.format_key(getattr(CacheKeys, key_attr), document_uuid=doc_uuid)
            exists = redis_manager.exists(cache_key)
            cache_results[name] = exists
            status_icon = "✓" if exists else "✗"
            print(f"   {status_icon} {name}: {'Cached' if exists else 'Not cached'}")
            
        print()
        
        # Verify Fix #2 - Missing cache entries
        fix2_keys = ['OCR Result', 'All Mentions', 'Resolved Mentions']
        fix2_success = all(cache_results.get(key, False) for key in fix2_keys)
        if fix2_success:
            print("✅ Fix #2 VERIFIED - All missing cache entries are now populated")
        else:
            missing = [k for k in fix2_keys if not cache_results.get(k, False)]
            print(f"⚠️  Fix #2 PARTIAL - Missing cache entries: {', '.join(missing)}")
        print()
        
        # Check processing tasks
        print("📋 Processing Tasks Verification:")
        task_result = session.execute(text("""
            SELECT task_type, status, started_at, completed_at, error_message
            FROM processing_tasks 
            WHERE document_id = :doc_uuid
            ORDER BY started_at
        """), {'doc_uuid': doc_uuid}).fetchall()
        
        if task_result:
            print(f"   ✓ Found {len(task_result)} processing task records")
            for task in task_result:
                task_type, task_status, started, completed, error = task
                duration = ""
                if started and completed:
                    delta = (completed - started).total_seconds()
                    duration = f" ({delta:.1f}s)"
                error_info = f" - ERROR: {error[:50]}..." if error else ""
                print(f"   • {task_type}: {task_status}{duration}{error_info}")
            
            # Verify Fix #3 - Processing tasks tracking
            print()
            print("✅ Fix #3 VERIFIED - Processing tasks are being tracked")
        else:
            print("   ✗ No processing task records found")
            print("❌ Fix #3 NOT WORKING - Processing tasks decorator may have issues")
        
        print()
        
        # Summary
        print("📊 SUMMARY:")
        print("=" * 30)
        
        fix1_ok = status in [ProcessingStatus.PENDING.value, ProcessingStatus.COMPLETED.value]
        fix2_ok = fix2_success 
        fix3_ok = len(task_result) > 0
        
        print(f"Fix #1 (Document Status): {'✅ PASS' if fix1_ok else '❌ FAIL'}")
        print(f"Fix #2 (Cache Entries): {'✅ PASS' if fix2_ok else '❌ FAIL'}")  
        print(f"Fix #3 (Task Tracking): {'✅ PASS' if fix3_ok else '❌ FAIL'}")
        
        overall_success = fix1_ok and fix2_ok and fix3_ok
        print(f"\nOverall: {'🎉 ALL FIXES VERIFIED' if overall_success else '⚠️  SOME ISSUES REMAIN'}")
        
    except Exception as e:
        print(f"❌ Error during verification: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        session.close()

if __name__ == "__main__":
    main()