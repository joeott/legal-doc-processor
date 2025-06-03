#!/usr/bin/env python3
"""Check for resolution task errors"""

from celery.result import AsyncResult
from scripts.celery_app import app
import sys

task_id = sys.argv[1] if len(sys.argv) > 1 else '86ff363b-b975-4289-a8fc-b7420f1c5258'

result = AsyncResult(task_id, app=app)
print(f"Task ID: {task_id}")
print(f"State: {result.state}")
print(f"Info: {result.info}")

if result.failed():
    print(f"\nTraceback:")
    print(result.traceback)