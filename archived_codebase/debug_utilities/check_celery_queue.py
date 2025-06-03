#!/usr/bin/env python3
"""
Check Celery queue status
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.celery_app import app

# Get queue info
i = app.control.inspect()

# Check active tasks
active = i.active()
print("Active tasks:")
if active:
    for worker, tasks in active.items():
        print(f"  {worker}: {len(tasks)} tasks")
        for task in tasks:
            print(f"    - {task['name']} [{task['id']}]")
else:
    print("  None")

# Check scheduled tasks
scheduled = i.scheduled()
print("\nScheduled tasks:")
if scheduled:
    for worker, tasks in scheduled.items():
        print(f"  {worker}: {len(tasks)} tasks")
        for task in tasks:
            print(f"    - {task['request']['name']} [{task['request']['id']}]")
else:
    print("  None")

# Check reserved tasks
reserved = i.reserved()
print("\nReserved tasks:")
if reserved:
    for worker, tasks in reserved.items():
        print(f"  {worker}: {len(tasks)} tasks")
        for task in tasks:
            print(f"    - {task['name']} [{task['id']}]")
else:
    print("  None")