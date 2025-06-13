#!/usr/bin/env python3
"""
Test script to verify why Fix #2 (OCR caching) and Fix #3 (processing task tracking) are not working.
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from scripts.cache import get_redis_manager, CacheKeys
from scripts.db import DatabaseManager
from datetime import datetime
import logging
from sqlalchemy import text

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_ocr_cache():
    """Test OCR cache functionality"""
    print("\n=== Testing OCR Cache Functionality ===")
    
    redis_manager = get_redis_manager()
    test_uuid = "test-document-uuid-123"
    
    # Test cache key generation
    ocr_cache_key = CacheKeys.format_key(CacheKeys.DOC_OCR_RESULT, document_uuid=test_uuid)
    print(f"Generated OCR cache key: {ocr_cache_key}")
    
    # Test storing OCR data
    ocr_data = {
        'text': 'This is test OCR text',
        'length': 20,
        'extracted_at': datetime.now().isoformat(),
        'method': 'test'
    }
    
    success = redis_manager.store_dict(ocr_cache_key, ocr_data, ttl=3600)
    print(f"Store OCR data result: {success}")
    
    # Test retrieving OCR data
    retrieved_data = redis_manager.get_dict(ocr_cache_key)
    print(f"Retrieved OCR data: {retrieved_data}")
    
    # Check if key exists in Redis
    client = redis_manager.get_client()
    exists = client.exists(ocr_cache_key)
    print(f"Key exists in Redis: {exists}")
    
    # List all keys with OCR pattern
    print("\nAll OCR cache keys:")
    ocr_keys = list(client.scan_iter(match="*ocr*", count=100))
    for key in ocr_keys[:10]:  # Show first 10
        print(f"  - {key}")
    
    return success

def test_processing_task_tracking():
    """Test processing task tracking"""
    print("\n=== Testing Processing Task Tracking ===")
    
    db_manager = DatabaseManager()
    
    # Test database connection
    try:
        session = next(db_manager.get_session())
        
        # Check if processing_tasks table exists
        result = session.execute(text("""
            SELECT COUNT(*) FROM information_schema.tables 
            WHERE table_name = 'processing_tasks'
        """))
        table_exists = result.scalar() > 0
        print(f"processing_tasks table exists: {table_exists}")
        
        if table_exists:
            # Check table structure
            result = session.execute(text("""
                SELECT column_name, data_type, is_nullable 
                FROM information_schema.columns 
                WHERE table_name = 'processing_tasks' 
                ORDER BY ordinal_position
            """))
            print("\nprocessing_tasks columns:")
            for row in result:
                print(f"  - {row[0]}: {row[1]} (nullable: {row[2]})")
            
            # Check recent records
            result = session.execute(text("""
                SELECT COUNT(*) FROM processing_tasks 
                WHERE created_at > NOW() - INTERVAL '24 hours'
            """))
            recent_count = result.scalar()
            print(f"\nRecords created in last 24 hours: {recent_count}")
            
        session.close()
        return table_exists
        
    except Exception as e:
        logger.error(f"Database error: {str(e)}")
        return False

def check_recent_document_processing():
    """Check if any documents were processed recently"""
    print("\n=== Recent Document Processing ===")
    
    db_manager = DatabaseManager()
    redis_manager = get_redis_manager()
    
    try:
        session = next(db_manager.get_session())
        
        # Get recent documents
        result = session.execute(text("""
            SELECT document_uuid, status, file_name, created_at 
            FROM source_documents 
            ORDER BY created_at DESC 
            LIMIT 5
        """))
        
        print("\nRecent documents:")
        for row in result:
            print(f"  - {row[0]}: {row[1]} - {row[2]} ({row[3]})")
            
            # Check if OCR cache exists for this document
            ocr_cache_key = CacheKeys.format_key(CacheKeys.DOC_OCR_RESULT, document_uuid=row[0])
            ocr_data = redis_manager.get_dict(ocr_cache_key)
            print(f"    OCR cache exists: {ocr_data is not None}")
            
        session.close()
        
    except Exception as e:
        logger.error(f"Error checking recent documents: {str(e)}")

if __name__ == "__main__":
    # Test OCR caching
    ocr_test_passed = test_ocr_cache()
    
    # Test processing task tracking
    task_tracking_passed = test_processing_task_tracking()
    
    # Check recent document processing
    check_recent_document_processing()
    
    print("\n=== Test Summary ===")
    print(f"OCR Cache Test: {'PASSED' if ocr_test_passed else 'FAILED'}")
    print(f"Task Tracking Test: {'PASSED' if task_tracking_passed else 'FAILED'}")