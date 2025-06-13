#!/usr/bin/env python3
import os
import json
import redis
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime

# Load environment
load_dotenv(Path(__file__).parent / '.env')

# Get Redis config from environment
REDIS_ENDPOINT = os.getenv('REDIS_PUBLIC_ENDPOINT', '')
if REDIS_ENDPOINT:
    # Parse endpoint
    if ':' in REDIS_ENDPOINT:
        REDIS_HOST, REDIS_PORT = REDIS_ENDPOINT.rsplit(':', 1)
        REDIS_PORT = int(REDIS_PORT)
    else:
        REDIS_HOST = REDIS_ENDPOINT
        REDIS_PORT = 6379
else:
    REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
    REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))

REDIS_PASSWORD = os.getenv('REDIS_PW') or os.getenv('REDIS_PASSWORD')
REDIS_USERNAME = os.getenv('REDIS_USERNAME', 'joe_ott')

try:
    # Connect to Redis
    r = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        password=REDIS_PASSWORD,
        username=REDIS_USERNAME,
        decode_responses=True
    )
    
    # Test connection
    r.ping()
    print("Redis connection successful!")
    
    # Get all keys
    print("\nScanning all Redis keys...")
    all_keys = []
    cursor = 0
    while True:
        cursor, keys = r.scan(cursor, count=1000)
        all_keys.extend(keys)
        if cursor == 0:
            break
    
    print(f"\nTotal keys in Redis: {len(all_keys)}")
    
    # Categorize keys
    categories = {
        'batch': [],
        'celery': [],
        'doc': [],
        'task': [],
        'ocr': [],
        'chunk': [],
        'entity': [],
        'queue': [],
        'other': []
    }
    
    for key in all_keys:
        if 'batch' in key:
            categories['batch'].append(key)
        elif 'celery' in key:
            categories['celery'].append(key)
        elif key.startswith('doc:') or 'document' in key:
            categories['doc'].append(key)
        elif 'task' in key:
            categories['task'].append(key)
        elif 'ocr' in key:
            categories['ocr'].append(key)
        elif 'chunk' in key:
            categories['chunk'].append(key)
        elif 'entity' in key or 'entities' in key:
            categories['entity'].append(key)
        elif any(q in key for q in ['default', 'text', 'graph', 'cleanup']):
            categories['queue'].append(key)
        else:
            categories['other'].append(key)
    
    # Print categorized keys
    for category, keys in categories.items():
        if keys:
            print(f"\n{category.upper()} keys ({len(keys)}):")
            for key in keys[:10]:  # Show first 10
                print(f"  - {key}")
            if len(keys) > 10:
                print(f"  ... and {len(keys) - 10} more")
    
    # Check for lists (queues)
    print("\n\nChecking queues:")
    for key in all_keys:
        try:
            key_type = r.type(key)
            if key_type == 'list':
                length = r.llen(key)
                if length > 0:
                    print(f"  Queue '{key}': {length} messages")
        except:
            pass
    
    # Look for recent keys (check TTL)
    print("\n\nChecking for keys with TTL (recently set):")
    ttl_keys = []
    for key in all_keys[:100]:  # Check first 100
        ttl = r.ttl(key)
        if ttl > 0:
            ttl_keys.append((key, ttl))
    
    if ttl_keys:
        ttl_keys.sort(key=lambda x: x[1], reverse=True)
        for key, ttl in ttl_keys[:10]:
            hours = ttl / 3600
            print(f"  {key}: expires in {hours:.1f} hours")
    else:
        print("  No keys with TTL found")
        
except redis.ConnectionError as e:
    print(f"\nFailed to connect to Redis: {e}")
except Exception as e:
    print(f"\nError: {e}")