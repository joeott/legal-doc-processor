#!/usr/bin/env python3
"""Disable the problematic trigger"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import text
from scripts.config import db_engine

with db_engine.connect() as conn:
    # Disable the trigger
    conn.execute(text("""
        ALTER TABLE source_documents DISABLE TRIGGER populate_integer_fks_trigger;
    """))
    conn.commit()
    print("Trigger disabled!")