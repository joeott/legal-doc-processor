#!/usr/bin/env python3
"""
Check OCR task status and debug any issues
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.celery_app import app
from celery.result import AsyncResult
from scripts.db import get_db
from sqlalchemy import text

def check_ocr_task(ocr_task_id):
    """Check OCR task status"""
    print("="*60)
    print("OCR TASK STATUS")
    print("="*60)
    
    # Check task status
    print(f"\nOCR Task ID: {ocr_task_id}")
    result = AsyncResult(ocr_task_id, app=app)
    print(f"Status: {result.status}")
    
    if result.status == 'FAILURE':
        print(f"Error: {result.info}")
        if hasattr(result.info, '__traceback__'):
            import traceback
            print("\nTraceback:")
            print(''.join(traceback.format_tb(result.info.__traceback__)))
    else:
        print(f"Result: {result.result}")
    
    # Check if task is in any queue
    print("\n\nChecking task in queues:")
    i = app.control.inspect()
    
    # Check scheduled tasks
    scheduled = i.scheduled()
    if scheduled:
        for worker, tasks in scheduled.items():
            for task in tasks:
                if task['request']['id'] == ocr_task_id:
                    print(f"Found in scheduled queue on {worker}")
                    print(f"ETA: {task.get('eta', 'Not set')}")
    
    # Check reserved tasks
    reserved = i.reserved()
    if reserved:
        for worker, tasks in reserved.items():
            for task in tasks:
                if task['request']['id'] == ocr_task_id:
                    print(f"Found in reserved queue on {worker}")
    
    # Check document Textract status
    print("\n\nDocument Textract Status:")
    session = next(get_db())
    try:
        doc = session.execute(text("""
            SELECT 
                document_uuid,
                textract_job_id,
                textract_job_status,
                status,
                error_message
            FROM source_documents
            WHERE document_uuid = '4909739b-8f12-40cd-8403-04b8b1a79281'
        """)).fetchone()
        
        if doc:
            print(f"Document status: {doc.status}")
            print(f"Textract job ID: {doc.textract_job_id}")
            print(f"Textract status: {doc.textract_job_status}")
            if doc.error_message:
                print(f"Error message: {doc.error_message}")
        else:
            print("Document not found!")
            
    finally:
        session.close()
    
    # Check for any errors in logs
    print("\n\nRecent Errors:")
    session = next(get_db())
    try:
        errors = session.execute(text("""
            SELECT 
                task_type,
                error_message,
                created_at
            FROM processing_tasks
            WHERE document_id = '4909739b-8f12-40cd-8403-04b8b1a79281'
              AND status = 'failed'
            ORDER BY created_at DESC
            LIMIT 5
        """)).fetchall()
        
        if errors:
            for err in errors:
                print(f"\n{err.created_at} - {err.task_type}")
                print(f"  {err.error_message}")
        else:
            print("No recent errors found")
            
    finally:
        session.close()

if __name__ == "__main__":
    # Check the OCR task
    ocr_task_id = "58def991-8aa1-440f-a4b1-8dbf95e42697"
    check_ocr_task(ocr_task_id)