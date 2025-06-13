#!/usr/bin/env python3
"""
Manually trigger polling for a document with job ID
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.pdf_tasks import poll_textract_job

# Document with persisted job ID
document_uuid = "5805f7b5-09ca-4f95-a990-da2dd758fd9e"
job_id = "3b2052d56be96b739a7245ea1a36a6e434993b63b02bb98fa7034cb544cca8ad"

print(f"Triggering polling for document {document_uuid}")
print(f"Job ID: {job_id}")

# Schedule the polling task
result = poll_textract_job.apply_async(
    args=[document_uuid, job_id]
)

print(f"Polling task scheduled: {result.id}")
print("Waiting for result...")

try:
    task_result = result.get(timeout=30)
    print(f"Result: {task_result}")
except Exception as e:
    print(f"Error: {e}")