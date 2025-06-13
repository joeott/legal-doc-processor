#!/usr/bin/env python3
import os
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from scripts.db import DatabaseManager
from sqlalchemy import text

db = DatabaseManager()
session = next(db.get_session())

# Check projects table columns
result = session.execute(text("""
    SELECT column_name, data_type 
    FROM information_schema.columns 
    WHERE table_name = 'projects' 
    ORDER BY ordinal_position
"""))

print("Projects table columns:")
for row in result:
    print(f"  - {row[0]}: {row[1]}")

session.close()