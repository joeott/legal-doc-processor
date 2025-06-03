#!/usr/bin/env python3
"""
Apply database migration to fix textract status enum issues
"""
import os
import sys
from scripts.supabase_utils import SupabaseManager
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def apply_migration():
    """Apply the migration to fix status enum constraints"""
    try:
        db = SupabaseManager()
        
        # Read the migration file
        migration_path = os.path.join(
            os.path.dirname(__file__), 
            "..", 
            "frontend", 
            "database", 
            "migrations", 
            "00005_fix_status_enums_and_triggers.sql"
        )
        
        with open(migration_path, 'r') as f:
            migration_sql = f.read()
        
        logger.info("Applying migration 00005_fix_status_enums_and_triggers...")
        
        # Execute the migration using raw SQL
        result = db.client.rpc('execute_sql', {
            'query': migration_sql
        }).execute()
        
        logger.info("Migration applied successfully!")
        return True
        
    except Exception as e:
        logger.error(f"Error applying migration: {e}")
        
        # Try a simpler approach - just fix the constraint
        try:
            logger.info("Trying simplified constraint fix...")
            simple_fix = """
            -- Drop the existing constraint
            ALTER TABLE textract_jobs DROP CONSTRAINT IF EXISTS textract_jobs_job_status_check;
            
            -- Add the constraint with lowercase values
            ALTER TABLE textract_jobs 
            ADD CONSTRAINT textract_jobs_job_status_check 
            CHECK (job_status IN ('submitted', 'in_progress', 'succeeded', 'failed', 'partial_success'));
            """
            
            result = db.client.rpc('execute_sql', {
                'query': simple_fix
            }).execute()
            
            logger.info("Simplified constraint fix applied!")
            return True
            
        except Exception as e2:
            logger.error(f"Simplified fix also failed: {e2}")
            return False

if __name__ == "__main__":
    success = apply_migration()
    sys.exit(0 if success else 1)