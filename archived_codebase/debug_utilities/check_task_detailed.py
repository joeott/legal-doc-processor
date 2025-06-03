#!/usr/bin/env python3
"""Check task error with full details"""

import os
import sys
sys.path.append('/opt/legal-doc-processor')

os.environ['USE_MINIMAL_MODELS'] = 'true'
os.environ['SKIP_CONFORMANCE_CHECK'] = 'true'

from scripts.celery_app import app
from celery.result import AsyncResult

task_id = "f57f52a0-70f4-4544-8661-32c6a34f3428"

result = AsyncResult(task_id, app=app)

print(f"Task ID: {task_id}")
print(f"State: {result.state}")
print(f"Info: {result.info}")
print(f"Result: {result.result}")

if result.traceback:
    print(f"\nFull traceback:")
    print(result.traceback)