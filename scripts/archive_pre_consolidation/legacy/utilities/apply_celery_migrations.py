#!/usr/bin/env python3
"""Apply Celery migration SQL files to Supabase"""
import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.supabase_utils import SupabaseManager
import glob
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def apply_migrations():
    """Apply migration SQL files"""
    db = SupabaseManager()
    migration_files = sorted(glob.glob('frontend/database/migrations/0001[2-3]_*.sql'))
    
    if not migration_files:
        logger.error("No migration files found")
        return False
    
    for migration_file in migration_files:
        logger.info(f"Reading {migration_file}...")
        with open(migration_file, 'r') as f:
            sql_content = f.read()
        
        # Split by semicolons to execute individual statements
        statements = [s.strip() for s in sql_content.split(';') if s.strip()]
        
        for i, statement in enumerate(statements):
            if statement.startswith('--') or not statement:
                continue
                
            try:
                # Note: Supabase Python client doesn't have direct SQL execution
                # We'll need to use the Supabase SQL editor or create a function
                logger.warning(f"Statement {i+1} from {migration_file}:")
                logger.warning("Please execute the following SQL in Supabase SQL editor:")
                logger.warning("-" * 60)
                print(statement + ";")
                logger.warning("-" * 60)
                
            except Exception as e:
                logger.error(f"Failed to apply statement {i+1} from {migration_file}: {e}")
                return False
    
    logger.info("\n✅ Migration SQL generated. Please execute in Supabase SQL editor.")
    logger.info("After execution, run: python scripts/verify_celery_migration.py")
    return True

if __name__ == "__main__":
    apply_migrations()