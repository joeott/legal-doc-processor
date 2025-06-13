#!/usr/bin/env python3
"""
Quick test to identify API errors without Celery
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Test imports
print("Testing imports...")

try:
    from scripts.s3_storage import S3StorageManager
    print("✓ S3StorageManager imported")
except Exception as e:
    print(f"✗ S3StorageManager import failed: {e}")

try:
    from scripts.cache import get_redis_manager
    redis = get_redis_manager()
    print("✓ Redis manager created")
except Exception as e:
    print(f"✗ Redis manager failed: {e}")

try:
    from scripts.db import get_db
    from sqlalchemy import text
    # get_db() is a generator, need to call next()
    session = next(get_db())
    try:
        result = session.execute(text("SELECT version()")).fetchone()
        print(f"✓ Database connected: {result[0][:20]}...")
    finally:
        session.close()
except Exception as e:
    print(f"✗ Database connection failed: {e}")

try:
    from scripts.entity_service import EntityService
    print("✓ EntityService imported")
except Exception as e:
    print(f"✗ EntityService import failed: {e}")

# Test S3 operations
print("\nTesting S3 operations...")
try:
    s3 = S3StorageManager()
    # Test method existence
    if hasattr(s3, 'upload_document'):
        print("✓ s3.upload_document exists")
    else:
        print("✗ s3.upload_document missing")
        
    if hasattr(s3, 'upload_document_with_uuid_naming'):
        print("✓ s3.upload_document_with_uuid_naming exists")
    else:
        print("✗ s3.upload_document_with_uuid_naming missing")
except Exception as e:
    print(f"✗ S3 test failed: {e}")

# Test Redis operations
print("\nTesting Redis operations...")
try:
    redis = get_redis_manager()
    # Test method existence
    if hasattr(redis, 'set'):
        print("✓ redis.set exists")
    else:
        print("✗ redis.set missing")
        
    if hasattr(redis, 'set_cached'):
        print("✓ redis.set_cached exists")
    else:
        print("✗ redis.set_cached missing")
        
    if hasattr(redis, 'get'):
        print("✓ redis.get exists")
    else:
        print("✗ redis.get missing")
        
    if hasattr(redis, 'get_cached'):
        print("✓ redis.get_cached exists")
    else:
        print("✗ redis.get_cached missing")
except Exception as e:
    print(f"✗ Redis test failed: {e}")

print("\nDone.")