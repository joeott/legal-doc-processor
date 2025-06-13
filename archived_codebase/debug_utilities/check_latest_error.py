#!/usr/bin/env python3
"""Check latest task error details"""

import os
import sys
sys.path.append('/opt/legal-doc-processor')

os.environ['USE_MINIMAL_MODELS'] = 'true'
os.environ['SKIP_CONFORMANCE_CHECK'] = 'true'

from scripts.celery_app import app
from celery.result import AsyncResult

task_id = "07172039-8eaa-4bf4-be59-eb4c7550cde3"

result = AsyncResult(task_id, app=app)

if result.failed():
    print(f"Error: {result.info}")
    print(f"\nFull traceback:\n{result.traceback}")