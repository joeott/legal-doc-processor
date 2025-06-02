#!/usr/bin/env python3
"""List all triggers"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from scripts.rds_utils import execute_query

# List all triggers
result = execute_query("""
    SELECT 
        tgname as trigger_name,
        tgrelid::regclass as table_name,
        tgtype,
        tgenabled
    FROM pg_trigger
    WHERE tgrelid::regclass::text LIKE '%source_documents%'
    ORDER BY tgname
""")

print('Triggers on source_documents:')
for row in result:
    print(f'  - {row["trigger_name"]} (enabled: {row["tgenabled"]})')