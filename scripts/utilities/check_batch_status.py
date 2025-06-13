#!/usr/bin/env python3
import os
import sys
import json
from datetime import datetime
from pathlib import Path

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent / 'scripts'))

# Load environment
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / '.env')

import redis
from scripts.db import DatabaseManager
from scripts.models import ProcessingTaskMinimal

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

def check_redis_status():
    """Check Redis for batch and document status"""
    print("\n=== REDIS STATUS CHECK ===")
    
    try:
        # Connect to Redis
        r = redis.Redis(
            host=os.getenv('REDIS_HOST', 'localhost'),
            port=int(os.getenv('REDIS_PORT', 6379)),
            password=os.getenv('REDIS_PASSWORD'),
            decode_responses=True
        )
        
        # Check connection
        r.ping()
        print("Redis connection successful")
        
        # Check batch status
        print(f"\nChecking batch {BATCH_ID}...")
        
        # Look for batch keys
        batch_patterns = [
            f"batch:{BATCH_ID}",
            f"batch:{BATCH_ID}:*",
            f"batch:status:{BATCH_ID}",
            f"batch:documents:{BATCH_ID}",
            f"batch:progress:{BATCH_ID}",
            f"celery-task-meta-{BATCH_ID}",
            f"task:{BATCH_ID}:*"
        ]
        
        for pattern in batch_patterns:
            keys = r.keys(pattern)
            if keys:
                print(f"\nFound keys matching '{pattern}':")
                for key in keys[:5]:  # Show first 5
                    value = r.get(key)
                    if value:
                        try:
                            # Try to parse as JSON
                            parsed = json.loads(value)
                            print(f"  {key}: {json.dumps(parsed, indent=2)[:200]}...")
                        except:
                            print(f"  {key}: {value[:200]}...")
        
        # Check document states
        print("\n\nChecking document states...")
        for doc_uuid in DOCUMENT_UUIDS[:3]:  # Check first 3
            print(f"\nDocument {doc_uuid}:")
            
            # Check various possible keys
            doc_patterns = [
                f"doc:state:{doc_uuid}",
                f"document:{doc_uuid}:*",
                f"task:{doc_uuid}:*",
                f"ocr:result:{doc_uuid}",
                f"chunks:{doc_uuid}",
                f"entities:{doc_uuid}"
            ]
            
            found_any = False
            for pattern in doc_patterns:
                keys = r.keys(pattern)
                if keys:
                    found_any = True
                    for key in keys[:2]:
                        value = r.get(key)
                        if value:
                            try:
                                parsed = json.loads(value)
                                print(f"  {key}: {json.dumps(parsed, indent=2)[:150]}...")
                            except:
                                print(f"  {key}: {value[:150]}...")
            
            if not found_any:
                print("  No keys found in Redis")
                
    except Exception as e:
        print(f"Redis error: {e}")

def check_database_status():
    """Check database for processing tasks"""
    print("\n\n=== DATABASE STATUS CHECK ===")
    
    try:
        db = DatabaseManager()
        
        print(f"\nChecking processing tasks for batch documents...")
        
        # Query processing tasks for our documents
        with db.get_session() as session:
            for doc_uuid in DOCUMENT_UUIDS[:5]:  # Check first 5
                tasks = session.query(ProcessingTaskMinimal).filter_by(
                    document_id=doc_uuid
                ).order_by(ProcessingTaskMinimal.created_at.desc()).limit(5).all()
                
                if tasks:
                    print(f"\nDocument {doc_uuid}:")
                    for task in tasks:
                        print(f"  Task: {task.task_type}, Status: {task.status}, "
                              f"Created: {task.created_at}, Error: {task.error_message[:50] if task.error_message else 'None'}")
                else:
                    print(f"\nDocument {doc_uuid}: No tasks found")
                    
    except Exception as e:
        print(f"Database error: {e}")

def check_celery_result_backend():
    """Check Celery result backend for task results"""
    print("\n\n=== CELERY RESULT BACKEND CHECK ===")
    
    try:
        r = redis.Redis(
            host=os.getenv('REDIS_HOST', 'localhost'),
            port=int(os.getenv('REDIS_PORT', 6379)),
            password=os.getenv('REDIS_PASSWORD'),
            decode_responses=True,
            db=1  # Celery result backend typically uses db 1
        )
        
        # Check for Celery task results
        celery_patterns = [
            "celery-task-meta-*",
            "_kombu.binding.celery",
            "_kombu.binding.batch.*",
            "unacked_index"
        ]
        
        for pattern in celery_patterns:
            keys = r.keys(pattern)
            if keys:
                print(f"\nFound {len(keys)} keys matching '{pattern}'")
                for key in keys[:3]:
                    value = r.get(key)
                    if value:
                        try:
                            parsed = json.loads(value)
                            print(f"  {key}: {json.dumps(parsed, indent=2)[:150]}...")
                        except:
                            print(f"  {key}: {value[:150]}...")
                            
    except Exception as e:
        print(f"Celery backend error: {e}")

if __name__ == "__main__":
    print(f"Checking batch status for: {BATCH_ID}")
    print(f"Submitted at: ~2024-11-06 (based on UUID timestamp)")
    print(f"Number of documents: {len(DOCUMENT_UUIDS)}")
    
    check_redis_status()
    check_database_status()
    check_celery_result_backend()
    
    print("\n\nDone!")