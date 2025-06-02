#!/usr/bin/env python3
"""Check database triggers"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from scripts.rds_utils import execute_query

print("=== Database Triggers ===")
triggers_query = """
    SELECT 
        tgname as trigger_name,
        tgrelid::regclass as table_name,
        pg_get_triggerdef(oid) as definition
    FROM pg_trigger
    WHERE tgisinternal = false
    ORDER BY tgrelid::regclass::text, tgname
"""

triggers = execute_query(triggers_query)
for trigger in triggers:
    print(f"\nTrigger: {trigger['trigger_name']}")
    print(f"Table: {trigger['table_name']}")
    print(f"Definition: {trigger['definition'][:200]}...")

# Check the specific function
print("\n\n=== Function populate_integer_fks ===")
func_query = """
    SELECT pg_get_functiondef(oid) 
    FROM pg_proc 
    WHERE proname = 'populate_integer_fks'
"""
funcs = execute_query(func_query)
if funcs:
    print(funcs[0]['pg_get_functiondef'])