#!/usr/bin/env python3
"""Test if Celery can import all tasks"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

print("Testing Celery imports...")

try:
    from scripts.celery_app import app
    print("✓ Celery app imported")
    
    # List all registered tasks
    print("\nRegistered tasks:")
    for task_name in sorted(app.tasks.keys()):
        if not task_name.startswith('celery.'):
            print(f"  - {task_name}")
    
    # Try to import pdf_tasks directly
    from scripts import pdf_tasks
    print("\n✓ pdf_tasks module imported successfully")
    
except Exception as e:
    print(f"\n✗ Import failed: {e}")
    import traceback
    traceback.print_exc()

print("\nDone.")