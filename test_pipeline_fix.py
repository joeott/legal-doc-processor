#!/usr/bin/env python3
"""Test the pipeline with OCR and chunking fixes"""

from scripts.celery_app import app
from scripts.pdf_tasks import process_pdf_document
import time

# Submit the document that already has OCR completed
doc_uuid = '5805f7b5-09ca-4f95-a990-da2dd758fd9e'
file_path = 'documents/5805f7b5-09ca-4f95-a990-da2dd758fd9e.pdf'
project_uuid = 'e0c57112-c755-4798-bc1f-4ecc3f0eec78'

print(f"Submitting document {doc_uuid} for processing...")
task = process_pdf_document.delay(
    document_uuid=doc_uuid,
    file_path=file_path,
    project_uuid=project_uuid,
    document_metadata={'file_name': 'Paul, Michael - Wombat Corp Disclosure Stmt 10-23-24.pdf'}
)
print(f"Task ID: {task.id}")
print("Document submitted successfully")

# Wait a moment
time.sleep(2)

# Check status
from scripts.check_document_status import check_document_full_status
print("\nChecking document status...")
check_document_full_status(doc_uuid)