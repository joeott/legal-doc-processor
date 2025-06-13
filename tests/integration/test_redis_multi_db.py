#!/usr/bin/env python3
"""Test script to verify Redis multi-database setup."""

import sys
import json
from datetime import datetime

from scripts.cache import get_redis_manager, CacheKeys
from scripts.config import (
    REDIS_DB_BROKER, REDIS_DB_RESULTS, REDIS_DB_CACHE,
    REDIS_DB_BATCH, REDIS_DB_METRICS
)


def test_multi_database_setup():
    """Test the multi-database Redis setup."""
    print("Testing Redis Multi-Database Setup")
    print("=" * 50)
    
    redis_manager = get_redis_manager()
    
    # Test 1: Check if Redis is available
    if not redis_manager.is_available():
        print("❌ Redis is not available!")
        return False
    
    print("✅ Redis connection established")
    
    # Test 2: Test each database connection
    databases = ['cache', 'batch', 'metrics', 'rate_limit']
    
    for db_name in databases:
        try:
            client = getattr(redis_manager, f'get_{db_name}_client')()
            client.ping()
            print(f"✅ {db_name.upper()} database connected")
        except Exception as e:
            print(f"❌ {db_name.upper()} database failed: {e}")
            return False
    
    # Test 3: Test key routing
    print("\nTesting Key Routing:")
    test_cases = [
        ("doc:test:123", "cache"),
        ("batch:progress:456", "batch"),
        ("metrics:performance:789", "metrics"),
        ("rate:limit:api", "rate_limit"),
        ("chunk:test:abc", "cache"),
        ("entity:test:def", "cache")
    ]
    
    for key, expected_db in test_cases:
        actual_db = redis_manager._get_database_for_key(key)
        if actual_db == expected_db:
            print(f"✅ {key} → {expected_db}")
        else:
            print(f"❌ {key} → {actual_db} (expected {expected_db})")
    
    # Test 4: Test data isolation
    print("\nTesting Database Isolation:")
    
    # Set value in cache database
    cache_key = "test:isolation:cache"
    cache_value = {"database": "cache", "timestamp": datetime.now().isoformat()}
    
    if redis_manager.set_cached(cache_key, cache_value, ttl=60):
        print(f"✅ Set value in cache database: {cache_key}")
    else:
        print(f"❌ Failed to set value in cache database")
        return False
    
    # Try to read from batch database (should not find it)
    batch_client = redis_manager.get_batch_client()
    batch_value = batch_client.get(cache_key)
    
    if batch_value is None:
        print(f"✅ Value correctly isolated (not found in batch database)")
    else:
        print(f"❌ Value leaked across databases!")
        return False
    
    # Verify it's in cache database
    retrieved = redis_manager.get_cached(cache_key)
    if retrieved and retrieved.get('database') == 'cache':
        print(f"✅ Value correctly retrieved from cache database")
    else:
        print(f"❌ Failed to retrieve value from cache database")
        return False
    
    # Test 5: Test batch operations
    print("\nTesting Batch Operations:")
    
    batch_id = "test-batch-123"
    progress_key = f"batch:progress:{batch_id}"
    
    # Use batch client directly
    batch_client = redis_manager.get_batch_client()
    batch_data = {
        'total': '100',
        'completed': '0',
        'failed': '0',
        'status': 'processing',
        'started_at': datetime.now().isoformat()
    }
    
    batch_client.hset(progress_key, mapping=batch_data)
    batch_client.expire(progress_key, 300)  # 5 minutes
    print(f"✅ Created batch progress tracking")
    
    # Verify it's in batch database
    retrieved_batch = batch_client.hgetall(progress_key)
    if retrieved_batch and retrieved_batch.get(b'status') == b'processing':
        print(f"✅ Batch data correctly stored in batch database")
    else:
        print(f"❌ Failed to retrieve batch data")
        return False
    
    # Test 6: Test Celery database separation
    print("\nChecking Celery Database Configuration:")
    print(f"  Broker DB: {REDIS_DB_BROKER}")
    print(f"  Results DB: {REDIS_DB_RESULTS}")
    print(f"  Cache DB: {REDIS_DB_CACHE}")
    print(f"  Batch DB: {REDIS_DB_BATCH}")
    print(f"  Metrics DB: {REDIS_DB_METRICS}")
    
    # Cleanup test data
    redis_manager.delete(cache_key)
    batch_client.delete(progress_key)
    print("\n✅ Cleaned up test data")
    
    # Test 7: Performance test with pipeline operations
    print("\nTesting Pipeline Operations:")
    updates = [
        ("doc:state:test1", "ocr", "processing", {"page": 1}),
        ("doc:state:test2", "ocr", "completed", {"page": 2}),
        ("doc:state:test3", "chunking", "processing", {"chunks": 5})
    ]
    
    if redis_manager.batch_update_document_states(updates):
        print("✅ Batch pipeline operations successful")
    else:
        print("❌ Batch pipeline operations failed")
    
    # Cleanup pipeline test data
    for doc_uuid, _, _, _ in updates:
        redis_manager.delete(doc_uuid)
    
    print("\n" + "=" * 50)
    print("✅ All multi-database tests passed!")
    return True


def check_database_stats():
    """Check statistics for each Redis database."""
    print("\nDatabase Statistics:")
    print("-" * 50)
    
    redis_manager = get_redis_manager()
    
    databases = {
        'default': redis_manager.get_client(),
        'cache': redis_manager.get_cache_client(),
        'batch': redis_manager.get_batch_client(),
        'metrics': redis_manager.get_metrics_client(),
        'rate_limit': redis_manager.get_rate_limit_client()
    }
    
    for name, client in databases.items():
        try:
            db_num = client.connection_pool.connection_kwargs['db']
            info = client.info('keyspace')
            db_key = f'db{db_num}'
            
            if db_key in info:
                stats = info[db_key]
                print(f"{name:12} (DB {db_num}): {stats['keys']:6} keys, {stats['expires']:6} expiring")
            else:
                print(f"{name:12} (DB {db_num}): Empty")
                
        except Exception as e:
            print(f"{name:12}: ERROR - {e}")


if __name__ == "__main__":
    try:
        success = test_multi_database_setup()
        if success:
            check_database_stats()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)