#!/usr/bin/env python3
"""Check the actual database schema"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from scripts.rds_utils import execute_query

# List tables
print("=== Tables in database ===")
tables_query = """
    SELECT table_name 
    FROM information_schema.tables 
    WHERE table_schema = 'public' 
    ORDER BY table_name
"""
tables = execute_query(tables_query)
for table in tables:
    print(f"  - {table['table_name']}")

# Check source_documents columns
print("\n=== Columns in source_documents ===")
columns_query = """
    SELECT column_name, data_type 
    FROM information_schema.columns 
    WHERE table_name = 'source_documents' 
    ORDER BY ordinal_position
"""
columns = execute_query(columns_query)
for col in columns:
    print(f"  - {col['column_name']} ({col['data_type']})")

# Check if there's a 'documents' table
print("\n=== Columns in documents table (if exists) ===")
docs_query = """
    SELECT column_name, data_type 
    FROM information_schema.columns 
    WHERE table_name = 'documents' 
    ORDER BY ordinal_position
"""
docs_columns = execute_query(docs_query)
if docs_columns:
    for col in docs_columns:
        print(f"  - {col['column_name']} ({col['data_type']})")
else:
    print("  No 'documents' table found")

# Sample documents
print("\n=== Sample documents ===")
try:
    sample = execute_query("SELECT * FROM source_documents LIMIT 2")
    if sample:
        print(f"Found {len(sample)} documents")
        for doc in sample:
            print(f"\nDocument: {doc.get('document_uuid', 'N/A')}")
            for key, value in doc.items():
                if value is not None:
                    print(f"  {key}: {str(value)[:50]}...")
except:
    # Try documents table
    try:
        sample = execute_query("SELECT * FROM documents LIMIT 2")
        if sample:
            print(f"Found {len(sample)} documents in 'documents' table")
            for doc in sample:
                print(f"\nDocument: {doc.get('id', 'N/A')}")
                for key, value in doc.items():
                    if value is not None:
                        print(f"  {key}: {str(value)[:50]}...")
    except Exception as e:
        print(f"Error: {e}")