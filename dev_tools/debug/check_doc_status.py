#!/usr/bin/env python3
"""Check document processing status"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.db import get_db
from sqlalchemy import text

doc_uuid = sys.argv[1] if len(sys.argv) > 1 else "c48a5aad-9c51-4b4c-aba9-5c6f4fabd9ba"

session = next(get_db())
try:
    # Check if document exists
    result = session.execute(text("""
        SELECT document_uuid, file_name, status, textract_job_status, created_at 
        FROM source_documents 
        WHERE document_uuid = :uuid
    """), {"uuid": doc_uuid}).fetchone()
    
    if result:
        print(f"Document found: {result.file_name}")
        print(f"Status: {result.status}")
        print(f"Textract status: {result.textract_job_status}")
        print(f"Created: {result.created_at}")
    else:
        print(f"Document {doc_uuid} not found in database")
        
        # Check recent documents
        print("\nRecent documents:")
        recent = session.execute(text("""
            SELECT document_uuid, file_name, created_at 
            FROM source_documents 
            ORDER BY created_at DESC 
            LIMIT 5
        """)).fetchall()
        
        for doc in recent:
            print(f"  {doc.document_uuid}: {doc.file_name} ({doc.created_at})")
            
    # Check processing tasks
    print("\nProcessing tasks for document:")
    tasks = session.execute(text("""
        SELECT task_id, task_type, status, created_at, error_message
        FROM processing_tasks
        WHERE document_uuid = :uuid
        ORDER BY created_at DESC
    """), {"uuid": doc_uuid}).fetchall()
    
    for task in tasks:
        print(f"  {task.task_type}: {task.status} ({task.created_at})")
        if task.error_message:
            print(f"    Error: {task.error_message}")
            
finally:
    session.close()