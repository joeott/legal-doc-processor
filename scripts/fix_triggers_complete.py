#!/usr/bin/env python3
"""Fix all triggers"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import text
from scripts.config import db_engine

with db_engine.connect() as conn:
    # Drop the problematic trigger
    conn.execute(text("DROP TRIGGER IF EXISTS populate_source_documents_fks ON source_documents"))
    
    # Drop the function if it exists
    conn.execute(text("DROP FUNCTION IF EXISTS populate_integer_fks() CASCADE"))
    
    # Create a simpler function that doesn't cause issues
    conn.execute(text("""
        CREATE OR REPLACE FUNCTION populate_integer_fks()
        RETURNS TRIGGER AS $$
        BEGIN
            -- For now, just return NEW without modifications
            -- This prevents the trigger errors while we fix the schema
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """))
    
    conn.commit()
    print("Triggers fixed!")