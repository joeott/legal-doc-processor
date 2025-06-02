#!/usr/bin/env python3
"""
Check document_chunks table schema
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.db import DatabaseManager
from sqlalchemy import text

def check_chunk_schema():
    """Check document_chunks table column names"""
    db = DatabaseManager(validate_conformance=False)
    session = next(db.get_session())
    
    try:
        # Get column names
        result = session.execute(
            text("""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_name = 'document_chunks'
                ORDER BY ordinal_position
            """)
        )
        
        print("Document chunks table columns:")
        for row in result:
            print(f"  {row[0]} - {row[1]}")
            
    finally:
        session.close()

if __name__ == "__main__":
    check_chunk_schema()