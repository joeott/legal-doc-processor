#!/usr/bin/env python3
import os
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from scripts.db import DatabaseManager
from sqlalchemy import text

db = DatabaseManager()
session = next(db.get_session())

result = session.execute(text("""
    SELECT task_type, status, error_message, created_at 
    FROM processing_tasks 
    ORDER BY created_at DESC 
    LIMIT 5
"""))

print("Recent processing tasks:")
for row in result:
    print(f"\nTask: {row[0]}")
    print(f"Status: {row[1]}")
    print(f"Created: {row[3]}")
    if row[2]:
        print(f"Error: {row[2][:200]}...")

session.close()