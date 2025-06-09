#!/usr/bin/env python3
"""Check actual database schema"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.db import get_db
from sqlalchemy import text

# Check source_documents columns
session = next(get_db())
try:
    result = session.execute(text("""
        SELECT column_name, data_type 
        FROM information_schema.columns 
        WHERE table_name = 'source_documents'
        ORDER BY ordinal_position
    """)).fetchall()
    
    print("source_documents columns:")
    for col in result:
        print(f"  - {col.column_name}: {col.data_type}")
    
    # Check projects table too
    print("\nprojects columns:")
    result = session.execute(text("""
        SELECT column_name, data_type 
        FROM information_schema.columns 
        WHERE table_name = 'projects'
        ORDER BY ordinal_position
    """)).fetchall()
    
    for col in result:
        print(f"  - {col.column_name}: {col.data_type}")
    
    # Check canonical_entities table
    print("\ncanonical_entities columns:")
    result = session.execute(text("""
        SELECT column_name, data_type 
        FROM information_schema.columns 
        WHERE table_name = 'canonical_entities'
        ORDER BY ordinal_position
    """)).fetchall()
    
    for col in result:
        print(f"  - {col.column_name}: {col.data_type}")
    
    # Check entity_mentions table
    print("\nentity_mentions columns:")
    result = session.execute(text("""
        SELECT column_name, data_type 
        FROM information_schema.columns 
        WHERE table_name = 'entity_mentions'
        ORDER BY ordinal_position
    """)).fetchall()
    
    for col in result:
        print(f"  - {col.column_name}: {col.data_type}")
    
    # Check textract_jobs table
    print("\ntextract_jobs columns:")
    result = session.execute(text("""
        SELECT column_name, data_type 
        FROM information_schema.columns 
        WHERE table_name = 'textract_jobs'
        ORDER BY ordinal_position
    """)).fetchall()
    
    for col in result:
        print(f"  - {col.column_name}: {col.data_type}")
        
finally:
    session.close()