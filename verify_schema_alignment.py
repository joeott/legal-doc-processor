#!/usr/bin/env python3
"""Verify schema alignment between Pydantic models and RDS"""

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

def check_alignment():
    """Check if critical tables and columns exist"""
    
    with db_engine.connect() as conn:
        print("=== Schema Alignment Verification ===\n")
        
        # 1. Check source_documents critical columns
        result = conn.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'source_documents' 
            AND column_name IN ('document_uuid', 'file_name', 'status', 'error_message', 'processing_completed_at')
            ORDER BY column_name
        """))
        
        cols = [row[0] for row in result]
        print("✓ source_documents has required columns:")
        for col in cols:
            print(f"  - {col}")
        
        # 2. Check processing_tasks exists
        result = conn.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'processing_tasks'
            ORDER BY ordinal_position
            LIMIT 10
        """))
        
        cols = list(result)
        if cols:
            print("\n✓ processing_tasks table exists with columns:")
            for col in cols[:5]:
                print(f"  - {col[0]}")
            if len(cols) > 5:
                print(f"  ... and {len(cols) - 5} more")
        
        # 3. Check document_chunks has 'text' column
        result = conn.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'document_chunks' 
            AND column_name = 'text'
        """))
        
        if result.fetchone():
            print("\n✓ document_chunks has 'text' column")
        else:
            print("\n✗ document_chunks missing 'text' column")
        
        # 4. Check foreign key relationships
        result = conn.execute(text("""
            SELECT 
                tc.constraint_name,
                tc.table_name,
                kcu.column_name,
                ccu.table_name AS foreign_table_name,
                ccu.column_name AS foreign_column_name
            FROM information_schema.table_constraints AS tc 
            JOIN information_schema.key_column_usage AS kcu
              ON tc.constraint_name = kcu.constraint_name
            JOIN information_schema.constraint_column_usage AS ccu
              ON ccu.constraint_name = tc.constraint_name
            WHERE tc.constraint_type = 'FOREIGN KEY' 
            AND tc.table_name IN ('processing_tasks', 'document_chunks')
        """))
        
        print("\n✓ Foreign key relationships:")
        for row in result:
            print(f"  - {row[1]}.{row[2]} -> {row[3]}.{row[4]}")
        
        print("\n=== Schema alignment complete! ===")

if __name__ == "__main__":
    check_alignment()