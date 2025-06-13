#!/usr/bin/env python3
"""Check canonical entities table schema"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.db import DatabaseManager
from sqlalchemy import text as sql_text, inspect

def main():
    db_manager = DatabaseManager()
    session = next(db_manager.get_session())
    
    try:
        # Check canonical_entities columns
        print("Canonical Entities Table Schema:")
        print("-" * 60)
        
        result = session.execute(sql_text("""
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_name = 'canonical_entities'
            ORDER BY ordinal_position
        """))
        
        for row in result:
            print(f"  {row.column_name:<30} {row.data_type:<20} {'NULL' if row.is_nullable == 'YES' else 'NOT NULL'}")
        
        print("\n\nEntity Mentions Table Schema:")
        print("-" * 60)
        
        result = session.execute(sql_text("""
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_name = 'entity_mentions'
            ORDER BY ordinal_position
        """))
        
        for row in result:
            print(f"  {row.column_name:<30} {row.data_type:<20} {'NULL' if row.is_nullable == 'YES' else 'NOT NULL'}")
            
    finally:
        session.close()

if __name__ == "__main__":
    main()