#!/usr/bin/env python3
"""Check actual schema columns"""

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

with db_engine.connect() as conn:
    # Check source_documents columns
    result = conn.execute(text("""
        SELECT column_name, data_type 
        FROM information_schema.columns 
        WHERE table_name = 'source_documents'
        ORDER BY ordinal_position
    """))
    
    print("source_documents columns:")
    for col_name, data_type in result:
        print(f"  - {col_name}: {data_type}")
    
    print("\n" + "="*50 + "\n")
    
    # Now check if our document exists
    doc_uuid = "fdae171c-5d99-47d2-8533-4dfc7f8a6ca4"
    
    result = conn.execute(text("""
        SELECT * FROM source_documents WHERE document_uuid = :doc_id
    """), {"doc_id": doc_uuid})
    
    row = result.fetchone()
    if row:
        print("Document found in database!")
        # Get column names
        cols = result.keys()
        for i, col in enumerate(cols):
            print(f"  {col}: {row[i]}")
    else:
        print("Document NOT found in database!")
    
    # Check all documents
    result = conn.execute(text("SELECT COUNT(*) FROM source_documents"))
    count = result.scalar()
    print(f"\nTotal documents in database: {count}")
    
    if count > 0:
        result = conn.execute(text("""
            SELECT id, filename FROM source_documents 
            ORDER BY created_at DESC LIMIT 5
        """))
        print("\nRecent documents:")
        for doc_id, filename in result:
            print(f"  - {doc_id}: {filename}")