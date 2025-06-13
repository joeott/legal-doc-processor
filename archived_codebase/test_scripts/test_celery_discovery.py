#!/usr/bin/env python3
"""Test script to check if Celery can discover tasks."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

from scripts.celery_app import app

print("Testing Celery task discovery...")
print(f"Celery app name: {app.main}")
print(f"Broker URL: {app.conf.broker_url[:30]}...")
print(f"Backend URL: {app.conf.result_backend[:30]}...")

print("\nRegistered tasks:")
for task_name in sorted(app.tasks.keys()):
    if not task_name.startswith('celery.'):  # Skip built-in Celery tasks
        print(f"  - {task_name}")

# Try to get specific task
print("\nChecking specific task 'scripts.pdf_tasks.process_pdf_document':")
try:
    task = app.tasks.get('scripts.pdf_tasks.process_pdf_document')
    if task:
        print(f"  ✓ Found: {task}")
        print(f"  Queue: {task.queue if hasattr(task, 'queue') else 'default'}")
    else:
        print("  ✗ Not found")
except Exception as e:
    print(f"  ✗ Error: {e}")

# Check imports
print("\nChecking imports:")
try:
    import scripts.pdf_tasks
    print("  ✓ scripts.pdf_tasks imported successfully")
    
    # List functions in module
    print("\nFunctions in scripts.pdf_tasks:")
    for name in dir(scripts.pdf_tasks):
        obj = getattr(scripts.pdf_tasks, name)
        if hasattr(obj, '__wrapped__'):  # Celery task
            print(f"    - {name} (Celery task)")
        elif callable(obj) and not name.startswith('_'):
            print(f"    - {name} (function)")
            
except ImportError as e:
    print(f"  ✗ Import error: {e}")

print("\nTask routes configuration:")
for pattern, route in app.conf.task_routes.items():
    print(f"  {pattern} -> {route}")