#!/usr/bin/env python3
"""Check task error details"""

import os
import sys
sys.path.append('/opt/legal-doc-processor')

os.environ['USE_MINIMAL_MODELS'] = 'true'
os.environ['SKIP_CONFORMANCE_CHECK'] = 'true'

from scripts.celery_app import app
from celery.result import AsyncResult

task_id = "a1946d01-9267-42ed-81ea-43a1e3d54f94"

print(f"Checking task: {task_id}")
print("-" * 80)

result = AsyncResult(task_id, app=app)

print(f"State: {result.state}")
print(f"Ready: {result.ready()}")
print(f"Successful: {result.successful()}")
print(f"Failed: {result.failed()}")

if result.failed():
    print(f"\nError info:")
    print(f"Exception: {result.info}")
    print(f"Traceback: {result.traceback}")
elif result.successful():
    print(f"\nResult: {result.result}")
else:
    print(f"\nInfo: {result.info}")