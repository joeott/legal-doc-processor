#!/usr/bin/env python3
"""
Check latest task results and errors
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.celery_app import app
from celery.result import AsyncResult

def check_latest_tasks():
    """Check status of recent tasks"""
    print("="*60)
    print("LATEST TASK STATUS")
    print("="*60)
    
    # Task IDs from our submissions
    task_ids = [
        ("Initial submission", "046e4330-9687-45a0-a60a-6a5ab964d820"),
        ("OCR task", "58def991-8aa1-440f-a4b1-8dbf95e42697"),
        ("Resubmission", "54c37843-9d17-4979-86ad-3dc8a30d8f72")
    ]
    
    for name, task_id in task_ids:
        print(f"\n{name}: {task_id}")
        result = AsyncResult(task_id, app=app)
        print(f"  Status: {result.status}")
        
        if result.status == 'SUCCESS':
            print(f"  Result: {result.result}")
        elif result.status == 'FAILURE':
            print(f"  Error: {result.info}")
            if hasattr(result.info, '__traceback__'):
                import traceback
                print("\n  Traceback:")
                tb_lines = traceback.format_tb(result.info.__traceback__)
                for line in tb_lines[-3:]:  # Show last 3 frames
                    print(f"    {line.strip()}")
        else:
            print(f"  Info: {result.info}")
    
    # Check for any new OCR tasks
    print("\n\nChecking for new tasks spawned...")
    if task_ids[-1][1]:  # If we have the resubmission task
        result = AsyncResult(task_ids[-1][1], app=app)
        if result.status == 'SUCCESS' and isinstance(result.result, dict):
            ocr_task_id = result.result.get('ocr_task_id')
            if ocr_task_id:
                print(f"\nNew OCR task spawned: {ocr_task_id}")
                ocr_result = AsyncResult(ocr_task_id, app=app)
                print(f"  Status: {ocr_result.status}")
                if ocr_result.status == 'FAILURE':
                    print(f"  Error: {ocr_result.info}")

if __name__ == "__main__":
    check_latest_tasks()