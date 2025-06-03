#!/usr/bin/env python3
import os
import sys

# Set up Python path
sys.path.insert(0, '/opt/legal-doc-processor')

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Set logging to debug
import logging
logging.basicConfig(level=logging.DEBUG)

print("Importing celery_app...")
from scripts.celery_app import app

print("\nTasks before importing pdf_tasks:", list(app.tasks.keys()))

print("\nImporting pdf_tasks...")
try:
    import scripts.pdf_tasks
    print("Successfully imported pdf_tasks")
except Exception as e:
    print(f"Error importing pdf_tasks: {e}")
    import traceback
    traceback.print_exc()

print("\nTasks after importing pdf_tasks:", list(app.tasks.keys()))

# Try to get specific task
print("\nChecking for extract_text_from_document task...")
if 'scripts.pdf_tasks.extract_text_from_document' in app.tasks:
    print("Found extract_text_from_document task!")
    task = app.tasks['scripts.pdf_tasks.extract_text_from_document']
    print(f"Task: {task}")
    print(f"Queue: {task.queue}")
else:
    print("extract_text_from_document task not found!")

# List all pdf_tasks
print("\nAll pdf_tasks:")
for task_name in app.tasks:
    if 'pdf_tasks' in task_name:
        print(f"  - {task_name}")