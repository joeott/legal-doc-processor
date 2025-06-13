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

BATCH_ID = "7bfd9fb9-1975-457a-886f-24cff2d6f9f3"

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
    
    # Check batch metrics
    print("\nChecking batch metrics...")
    batch_keys = [
        "metrics:batch:details:3ff344fb-9ecb-47d3-a437-c0a818b8104c",
        "metrics:batch:details:c9468a11-0473-4b72-99f7-7c910a396cce"
    ]
    
    for key in batch_keys:
        value = r.get(key)
        if value:
            try:
                data = json.loads(value)
                print(f"\n{key}:")
                print(json.dumps(data, indent=2))
            except:
                print(f"\n{key}: {value}")
    
    # Check batch.high9 queue
    print("\n\nChecking batch.high9 queue messages...")
    messages = r.lrange('batch.high9', 0, -1)
    print(f"Found {len(messages)} messages in batch.high9")
    
    for i, msg in enumerate(messages):
        print(f"\nMessage {i+1}:")
        try:
            # Celery messages are typically JSON
            data = json.loads(msg)
            # Look for our batch ID
            if BATCH_ID in str(data):
                print("*** FOUND OUR BATCH ID ***")
            print(json.dumps(data, indent=2)[:500] + "...")
        except:
            print(msg[:200] + "...")
    
    # Check for any Celery task results related to our batch
    print(f"\n\nSearching for Celery tasks with batch ID {BATCH_ID}...")
    
    # Get all celery task meta keys
    celery_keys = []
    cursor = 0
    while True:
        cursor, keys = r.scan(cursor, match="celery-task-meta-*", count=100)
        celery_keys.extend(keys)
        if cursor == 0:
            break
    
    # Check recent ones
    found_tasks = []
    for key in celery_keys[:50]:  # Check first 50
        value = r.get(key)
        if value and BATCH_ID in value:
            found_tasks.append((key, value))
    
    if found_tasks:
        print(f"Found {len(found_tasks)} tasks related to batch {BATCH_ID}:")
        for key, value in found_tasks[:5]:
            try:
                data = json.loads(value)
                print(f"\n{key}:")
                print(f"  Status: {data.get('status', 'unknown')}")
                print(f"  Result: {str(data.get('result', 'N/A'))[:100]}")
                print(f"  Traceback: {str(data.get('traceback', 'N/A'))[:200]}")
            except:
                print(f"\n{key}: {value[:200]}")
    else:
        print("No Celery tasks found with this batch ID")
    
    # Check timestamp-based metrics
    print("\n\nChecking timestamp-based metrics...")
    timestamps = ["29161200", "29161198"]
    for ts in timestamps:
        start_key = f"metrics:batch:start:{ts}"
        complete_key = f"metrics:batch:complete:{ts}"
        
        start_val = r.get(start_key)
        complete_val = r.get(complete_key)
        
        if start_val or complete_val:
            print(f"\nTimestamp {ts}:")
            if start_val:
                print(f"  Start: {start_val}")
            if complete_val:
                print(f"  Complete: {complete_val}")
                
except redis.ConnectionError as e:
    print(f"\nFailed to connect to Redis: {e}")
except Exception as e:
    print(f"\nError: {e}")