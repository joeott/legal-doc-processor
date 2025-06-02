#!/usr/bin/env python3
"""Check table columns"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from scripts.rds_utils import execute_query

# Check source_documents columns
result = execute_query("""
    SELECT column_name 
    FROM information_schema.columns 
    WHERE table_name = 'source_documents'
    ORDER BY ordinal_position
""")

print('Columns in source_documents:')
for row in result:
    print(f'  - {row["column_name"]}')
    
# Check if there's a project_id column
has_project_id = any(row['column_name'] == 'project_id' for row in result)
has_project_uuid = any(row['column_name'] == 'project_uuid' for row in result)

print(f'\nHas project_id: {has_project_id}')
print(f'Has project_uuid: {has_project_uuid}')