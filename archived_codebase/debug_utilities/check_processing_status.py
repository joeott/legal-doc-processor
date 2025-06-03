#!/usr/bin/env python3
"""Check document processing status and tasks"""

import os
import sys
from pathlib import Path

# Set up Python path
sys.path.insert(0, str(Path(__file__).parent))

# Load environment
from dotenv import load_dotenv
load_dotenv()

from scripts.config import db_engine
from sqlalchemy import text

doc_uuid = "fdae171c-5d99-47d2-8533-4dfc7f8a6ca4"

with db_engine.connect() as conn:
    # Check processing tasks
    print("Processing Tasks:")
    result = conn.execute(text("""
        SELECT task_type, status, error_message, created_at, updated_at, celery_task_id
        FROM processing_tasks 
        WHERE document_id = :doc_id
        ORDER BY created_at DESC
    """), {"doc_id": doc_uuid})
    
    tasks = list(result)
    if tasks:
        for task in tasks:
            print(f"\n  Task Type: {task[0]}")
            print(f"  Status: {task[1]}")
            print(f"  Celery ID: {task[5]}")
            print(f"  Created: {task[3]}")
            print(f"  Updated: {task[4]}")
            if task[2]:
                print(f"  Error: {task[2]}")
    else:
        print("  No processing tasks found")
    
    # Check chunks
    result = conn.execute(text("""
        SELECT COUNT(*) FROM document_chunks WHERE document_id = :doc_id
    """), {"doc_id": doc_uuid})
    
    chunk_count = result.scalar()
    print(f"\nChunks created: {chunk_count}")
    
    # Check recent OCR tasks in the logs
    print("\nChecking recent OCR worker activity...")
    
    # Let's also check Redis for any cached data
    print("\nChecking Redis cache...")
    from scripts.cache import get_redis_manager
    
    try:
        redis_mgr = get_redis_manager()
        if redis_mgr.is_available():
            # Check for OCR result
            ocr_key = f"doc:ocr:{doc_uuid}"
            ocr_result = redis_mgr.get_cached(ocr_key)
            if ocr_result:
                print(f"  ✓ OCR result cached (size: {len(str(ocr_result))} chars)")
            else:
                print(f"  ✗ No OCR result in cache")
            
            # Check for document state
            state_key = f"doc:state:{doc_uuid}"
            doc_state = redis_mgr.get_cached(state_key)
            if doc_state:
                print(f"  ✓ Document state: {doc_state}")
            else:
                print(f"  ✗ No document state in cache")
    except Exception as e:
        print(f"  Redis error: {e}")