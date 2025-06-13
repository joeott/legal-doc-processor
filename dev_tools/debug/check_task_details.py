#!/usr/bin/env python3
"""
Check detailed task information and errors
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.celery_app import app
from celery.result import AsyncResult

def check_task_details(task_id):
    """Check detailed task information"""
    print(f"Task ID: {task_id}")
    result = AsyncResult(task_id, app=app)
    
    print(f"Status: {result.status}")
    print(f"Backend: {result.backend}")
    
    if result.ready():
        if result.successful():
            print(f"Result: {result.result}")
            # Check if it spawned an OCR task
            if isinstance(result.result, dict) and 'ocr_task_id' in result.result:
                ocr_task_id = result.result['ocr_task_id']
                print(f"\nOCR Task spawned: {ocr_task_id}")
                ocr_result = AsyncResult(ocr_task_id, app=app)
                print(f"OCR Status: {ocr_result.status}")
                if ocr_result.failed():
                    print(f"OCR Error: {ocr_result.info}")
                    print(f"OCR Traceback: {ocr_result.traceback}")
                elif ocr_result.successful():
                    print(f"OCR Result: {ocr_result.result}")
        else:
            print(f"Error: {result.info}")
            print(f"Traceback:\n{result.traceback}")
    else:
        print("Task is still pending or running")
        print(f"Info: {result.info}")

if __name__ == "__main__":
    # Check the latest task
    task_id = "928f1c99-8321-4439-9578-162cee0c37fe"
    check_task_details(task_id)