#!/usr/bin/env python3
"""Check document processing status"""

import os
import sys
from pathlib import Path

# Set up Python path
sys.path.insert(0, str(Path(__file__).parent))

# Load environment
from dotenv import load_dotenv
load_dotenv()

from scripts.config import db_engine
from sqlalchemy import text

doc_uuid = "fdae171c-5d99-47d2-8533-4dfc7f8a6ca4"

with db_engine.connect() as conn:
    # Check source document
    result = conn.execute(text("""
        SELECT id, filename, status, created_at, updated_at 
        FROM source_documents 
        WHERE id = :doc_id
    """), {"doc_id": doc_uuid})
    
    doc = result.fetchone()
    if doc:
        print(f"Document found:")
        print(f"  ID: {doc[0]}")
        print(f"  File: {doc[1]}")
        print(f"  Status: {doc[2]}")
        print(f"  Created: {doc[3]}")
        print(f"  Updated: {doc[4]}")
    else:
        print("Document not found!")
    
    # Check processing tasks
    print("\nProcessing Tasks:")
    result = conn.execute(text("""
        SELECT task_type, status, error_message, created_at, updated_at 
        FROM processing_tasks 
        WHERE document_id = :doc_id
        ORDER BY created_at DESC
    """), {"doc_id": doc_uuid})
    
    for task in result:
        print(f"  - {task[0]}: {task[1]} (created: {task[3]})")
        if task[2]:
            print(f"    Error: {task[2]}")
    
    # Check chunks
    result = conn.execute(text("""
        SELECT COUNT(*) FROM document_chunks WHERE document_id = :doc_id
    """), {"doc_id": doc_uuid})
    
    chunk_count = result.scalar()
    print(f"\nChunks created: {chunk_count}")
    
    # Check entities
    result = conn.execute(text("""
        SELECT COUNT(*) FROM entity_mentions WHERE document_id = :doc_id
    """), {"doc_id": doc_uuid})
    
    entity_count = result.scalar()
    print(f"Entities extracted: {entity_count}")