#!/usr/bin/env python3
"""Fix the trigger function"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import text
from scripts.config import db_engine

with db_engine.connect() as conn:
    # Fix the trigger function
    conn.execute(text("""
        CREATE OR REPLACE FUNCTION populate_integer_fks()
        RETURNS TRIGGER AS $$
        BEGIN
            -- Populate project_id from project_uuid (which is actually project_id due to renaming)
            IF NEW.project_uuid IS NOT NULL AND NEW.project_id IS NULL THEN
                SELECT id INTO NEW.project_id
                FROM projects 
                WHERE project_id = NEW.project_uuid;
            END IF;
            
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """))
    conn.commit()
    print("Trigger function fixed!")