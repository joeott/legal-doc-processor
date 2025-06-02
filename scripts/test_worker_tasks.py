#!/usr/bin/env python3
"""Test worker task visibility by manually starting a Celery app."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Manual import to debug
print("Importing Celery app...")
from celery import Celery

# Get Redis config manually
from scripts.config import (
    REDIS_HOST, REDIS_PORT, REDIS_DB, REDIS_PASSWORD, REDIS_SSL,
    DEPLOYMENT_STAGE, STAGE_CLOUD_ONLY, get_redis_config_for_stage,
    REDIS_USERNAME
)

# Build Redis URL
redis_config = get_redis_config_for_stage(DEPLOYMENT_STAGE)
redis_host = redis_config.get('host', REDIS_HOST)
redis_port = redis_config.get('port', REDIS_PORT)
redis_ssl = redis_config.get('ssl', REDIS_SSL)

if REDIS_PASSWORD:
    if REDIS_USERNAME:
        redis_url = f"{'rediss' if redis_ssl else 'redis'}://{REDIS_USERNAME}:{REDIS_PASSWORD}@{redis_host}:{redis_port}/{REDIS_DB}"
    else:
        redis_url = f"{'rediss' if redis_ssl else 'redis'}://:{REDIS_PASSWORD}@{redis_host}:{redis_port}/{REDIS_DB}"
else:
    redis_url = f"{'rediss' if redis_ssl else 'redis'}://{redis_host}:{redis_port}/{REDIS_DB}"

print(f"Redis URL: {redis_url[:30]}...")

# Create a fresh Celery app
app = Celery(
    'test_pipeline',
    broker=redis_url,
    backend=redis_url
)

# Import tasks manually
print("\nImporting pdf_tasks module...")
import scripts.pdf_tasks

# List all attributes in pdf_tasks that are Celery tasks
print("\nManually checking for tasks in pdf_tasks:")
for attr_name in dir(scripts.pdf_tasks):
    attr = getattr(scripts.pdf_tasks, attr_name)
    if hasattr(attr, 'delay'):  # Celery task method
        print(f"  Found task: {attr_name}")
        print(f"    Name: {attr.name if hasattr(attr, 'name') else 'unknown'}")
        print(f"    Module: {attr.__module__ if hasattr(attr, '__module__') else 'unknown'}")

# Now check the app from celery_app
print("\nChecking tasks in celery_app...")
from scripts.celery_app import app as celery_app
print(f"Celery app includes: {celery_app.conf.include}")
print(f"Number of registered tasks: {len([t for t in celery_app.tasks if not t.startswith('celery.')])}")

# List non-celery tasks
print("\nRegistered custom tasks:")
for task_name in sorted(celery_app.tasks.keys()):
    if not task_name.startswith('celery.'):
        print(f"  - {task_name}")

# Try to manually register a task
print("\nAttempting manual task call...")
try:
    # Get the function directly
    process_func = getattr(scripts.pdf_tasks, 'process_pdf_document', None)
    if process_func:
        print(f"  Found process_pdf_document: {process_func}")
        print(f"  Is Celery task: {hasattr(process_func, 'delay')}")
        if hasattr(process_func, 'name'):
            print(f"  Task name: {process_func.name}")
except Exception as e:
    print(f"  Error: {e}")
    import traceback
    traceback.print_exc()