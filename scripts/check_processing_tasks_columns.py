#!/usr/bin/env python3
"""Check processing_tasks columns"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from scripts.rds_utils import execute_query

# Check columns
result = execute_query("""
    SELECT column_name 
    FROM information_schema.columns 
    WHERE table_name = 'processing_tasks'
    ORDER BY ordinal_position
""")

print('Columns in processing_tasks:')
for row in result:
    print(f'  - {row["column_name"]}')