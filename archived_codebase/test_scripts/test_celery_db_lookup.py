#!/usr/bin/env python3
"""
Test if Celery can see documents in the database
"""

import os
import sys
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.celery_app import app
from scripts.db import DatabaseManager
from sqlalchemy import text

@app.task
def check_document(document_uuid: str):
    """Check if Celery can find a document"""
    db = DatabaseManager(validate_conformance=False)
    
    # Method 1: Using get_source_document
    doc = db.get_source_document(document_uuid)
    result1 = f"get_source_document: {'FOUND' if doc else 'NOT FOUND'}"
    
    # Method 2: Direct SQL query
    session_gen = db.get_session()
    session = next(session_gen)
    try:
        query_result = session.execute(
            text("SELECT document_uuid, file_name FROM source_documents WHERE document_uuid = :uuid"),
            {"uuid": document_uuid}
        )
        row = query_result.fetchone()
        result2 = f"Direct SQL: {'FOUND' if row else 'NOT FOUND'}"
        if row:
            result2 += f" - {row[1]}"
    finally:
        session.close()
        
    # Method 3: Count all documents
    session_gen2 = db.get_session()
    session2 = next(session_gen2)
    try:
        count_result = session2.execute(text("SELECT COUNT(*) FROM source_documents"))
        count = count_result.scalar()
        result3 = f"Total documents in DB: {count}"
    finally:
        session2.close()
        
    return f"{result1}\n{result2}\n{result3}"

if __name__ == "__main__":
    # Test with the most recent document
    test_uuid = "cd52cf50-ebdd-4d1a-8988-5ad578cc7db8"
    
    print(f"Testing Celery database lookup for document: {test_uuid}")
    print("-" * 60)
    
    # Submit task
    result = check_document.apply_async(args=[test_uuid])
    
    # Wait for result
    try:
        output = result.get(timeout=10)
        print(output)
    except Exception as e:
        print(f"Error: {e}")
        
    print("-" * 60)