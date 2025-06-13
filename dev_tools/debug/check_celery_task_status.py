#!/usr/bin/env python3
"""
Check Celery task status and inspect workers
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.celery_app import app
from celery.result import AsyncResult
from scripts.db import get_db
from sqlalchemy import text

def check_task_and_workers(task_id):
    """Check task status and worker health"""
    print("="*60)
    print("CELERY TASK AND WORKER STATUS")
    print("="*60)
    
    # Check task status
    print(f"\nTask ID: {task_id}")
    result = AsyncResult(task_id, app=app)
    print(f"Status: {result.status}")
    print(f"Result: {result.result}")
    if result.info:
        print(f"Info: {result.info}")
    
    # Check worker status
    print("\n\nWorker Status:")
    print("-"*60)
    i = app.control.inspect()
    
    # Active tasks
    active = i.active()
    if active:
        print("\nActive tasks:")
        for worker, tasks in active.items():
            print(f"  {worker}: {len(tasks)} tasks")
            for task in tasks:
                print(f"    - {task['name']} ({task['id'][:8]}...)")
    else:
        print("No active tasks")
    
    # Registered tasks
    registered = i.registered()
    if registered:
        print("\nRegistered tasks per worker:")
        for worker, tasks in registered.items():
            print(f"  {worker}: {len(tasks)} tasks")
            # Show OCR-related tasks
            ocr_tasks = [t for t in tasks if 'ocr' in t.lower() or 'textract' in t.lower()]
            if ocr_tasks:
                print("    OCR-related tasks:")
                for task in ocr_tasks:
                    print(f"      - {task}")
    
    # Reserved tasks (queued)
    reserved = i.reserved()
    if reserved:
        print("\nReserved (queued) tasks:")
        for worker, tasks in reserved.items():
            print(f"  {worker}: {len(tasks)} tasks")
    
    # Check active queues
    active_queues = i.active_queues()
    if active_queues:
        print("\nActive queues per worker:")
        for worker, queues in active_queues.items():
            print(f"  {worker}:")
            for queue in queues:
                print(f"    - {queue['name']}")
    
    # Check recent processing tasks
    print("\n\nRecent Processing Tasks:")
    print("-"*60)
    session = next(get_db())
    try:
        recent_tasks = session.execute(text("""
            SELECT 
                celery_task_id,
                task_type,
                status,
                error_message,
                created_at
            FROM processing_tasks
            WHERE document_id = '4909739b-8f12-40cd-8403-04b8b1a79281'
            ORDER BY created_at DESC
            LIMIT 10
        """)).fetchall()
        
        if recent_tasks:
            for task in recent_tasks:
                print(f"\nTask: {task.celery_task_id}")
                print(f"  Type: {task.task_type}")
                print(f"  Status: {task.status}")
                if task.error_message:
                    print(f"  Error: {task.error_message}")
                print(f"  Created: {task.created_at}")
        else:
            print("No processing tasks found for this document")
            
    finally:
        session.close()

if __name__ == "__main__":
    # Use the task ID from the resubmission
    task_id = "046e4330-9687-45a0-a60a-6a5ab964d820"
    check_task_and_workers(task_id)