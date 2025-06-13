#!/usr/bin/env python3
import os
import json
import redis
from pathlib import Path
from dotenv import load_dotenv

# Load environment
load_dotenv(Path(__file__).parent / '.env')

# Batch and document info
BATCH_ID = "7bfd9fb9-1975-457a-886f-24cff2d6f9f3"
DOCUMENT_UUIDS = [
    "bab6cb20-fae7-4a7f-bef3-5b368e6d9235",
    "fbda9de2-1586-44ec-91e7-ad5c1d8eb660",
    "6f31669d-3294-4ef6-9c91-f3d244f3c24b",
    "e506579e-938a-436f-8dc3-2366f73747d5",
    "31d8e704-ebb6-44fb-9865-31d45d70c43f",
    "044172a9-2300-47f7-901d-daeff939e357",
    "17fbe286-9c74-4482-b027-5f4a3a1fcbe5",
    "49863f63-692d-4afe-8c8f-17fa5bc35807",
    "f3cd5d2e-4327-4fdb-bb01-d99dbb80f265",
    "df4ef52b-05ea-4fa4-aa14-61cfd6dd7704"
]

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

print(f"Redis connection info:")
print(f"  Host: {REDIS_HOST}")
print(f"  Port: {REDIS_PORT}")
print(f"  Has password: {'Yes' if REDIS_PASSWORD else 'No'}")
print(f"  Has username: {'Yes' if REDIS_USERNAME else 'No'}")

try:
    # Try to connect to Redis
    r = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        password=REDIS_PASSWORD,
        username=REDIS_USERNAME,
        decode_responses=True
    )
    
    # Test connection
    r.ping()
    print("\nRedis connection successful!")
    
    # Check for batch keys
    print(f"\nSearching for batch {BATCH_ID}...")
    
    all_keys = []
    cursor = 0
    while True:
        cursor, keys = r.scan(cursor, match=f"*{BATCH_ID}*", count=100)
        all_keys.extend(keys)
        if cursor == 0:
            break
    
    if all_keys:
        print(f"Found {len(all_keys)} keys containing batch ID:")
        for key in all_keys[:10]:
            print(f"  - {key}")
    else:
        print("No keys found with batch ID")
    
    # Check for document keys
    print("\nChecking for document keys...")
    for doc_uuid in DOCUMENT_UUIDS[:3]:
        doc_keys = []
        cursor = 0
        while True:
            cursor, keys = r.scan(cursor, match=f"*{doc_uuid}*", count=100)
            doc_keys.extend(keys)
            if cursor == 0:
                break
        
        if doc_keys:
            print(f"\nDocument {doc_uuid}: Found {len(doc_keys)} keys")
            for key in doc_keys[:5]:
                value = r.get(key)
                if value:
                    print(f"  {key}: {value[:100]}...")
        else:
            print(f"\nDocument {doc_uuid}: No keys found")
    
    # Check Celery queues
    print("\n\nChecking Celery queues...")
    queue_names = ['default', 'ocr', 'text', 'entity', 'graph', 'cleanup', 
                   'batch.high', 'batch.normal', 'batch.low']
    
    for queue in queue_names:
        length = r.llen(queue)
        if length > 0:
            print(f"  Queue '{queue}': {length} messages")
    
except redis.ConnectionError as e:
    print(f"\nFailed to connect to Redis: {e}")
except Exception as e:
    print(f"\nError: {e}")

# Try to check database separately
print("\n\nChecking database...")
try:
    import psycopg2
    from urllib.parse import urlparse
    
    DATABASE_URL = os.getenv('DATABASE_URL') or os.getenv('DATABASE_URL_DIRECT')
    if DATABASE_URL:
        # Parse database URL
        parsed = urlparse(DATABASE_URL)
        
        conn = psycopg2.connect(
            host=parsed.hostname,
            port=parsed.port or 5432,
            database=parsed.path[1:],
            user=parsed.username,
            password=parsed.password
        )
        
        cur = conn.cursor()
        
        # Check processing tasks
        for doc_uuid in DOCUMENT_UUIDS[:3]:
            cur.execute("""
                SELECT task_type, status, created_at, error_message 
                FROM processing_tasks 
                WHERE document_id = %s 
                ORDER BY created_at DESC 
                LIMIT 3
            """, (doc_uuid,))
            
            results = cur.fetchall()
            if results:
                print(f"\nDocument {doc_uuid}:")
                for row in results:
                    print(f"  {row[0]}: {row[1]} (created: {row[2]}) {row[3][:50] if row[3] else ''}")
            else:
                print(f"\nDocument {doc_uuid}: No processing tasks found")
        
        cur.close()
        conn.close()
    else:
        print("No database URL found in environment")
        
except Exception as e:
    print(f"Database error: {e}")