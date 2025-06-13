#!/usr/bin/env python3
"""
Clear all test data from RDS database for fresh start.
This script removes data from all tables while preserving schema.
Tables cleared:
- processing_tasks
- relationship_staging
- canonical_entities
- entity_mentions
- document_chunks
- textract_jobs
- source_documents
- projects
"""

import os
import sys
import logging
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# Add the project root to Python path
sys.path.append('/opt/legal-doc-processor')

# Load environment variables from .env file
env_path = Path('/opt/legal-doc-processor/.env')
if env_path.exists():
    load_dotenv(env_path)

# Set environment variables
os.environ['USE_MINIMAL_MODELS'] = 'true'
os.environ['SKIP_CONFORMANCE_CHECK'] = 'true'

from scripts.db import get_db, engine
from sqlalchemy import text, inspect

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def clear_all_rds_data(preserve_schema=True):
    """Clear all data from RDS tables."""
    try:
        logger.info("Starting RDS data clearing...")
        
        # Tables to clear in order (respecting foreign key constraints)
        tables_to_clear = [
            'processing_tasks',
            'relationship_staging',
            'canonical_entities',
            'entity_mentions',
            'document_chunks',
            'textract_jobs',
            'source_documents',
            'projects'
        ]
        
        # Get database session
        db = next(get_db())
        try:
            # Note: Cannot disable foreign key checks without superuser privileges
            # Will delete in proper order to respect constraints
            
            total_deleted = 0
            
            for table in tables_to_clear:
                try:
                    # Check if table exists
                    inspector = inspect(engine)
                    if table not in inspector.get_table_names():
                        logger.warning(f"Table '{table}' does not exist, skipping...")
                        continue
                    
                    # Count rows before deletion
                    result = db.execute(text(f"SELECT COUNT(*) FROM {table}"))
                    count = result.scalar()
                    
                    if count > 0:
                        # Delete all data from table
                        db.execute(text(f"TRUNCATE TABLE {table} CASCADE"))
                        db.commit()
                        
                        logger.info(f"Cleared {count} rows from table '{table}'")
                        total_deleted += count
                    else:
                        logger.info(f"Table '{table}' is already empty")
                        
                except Exception as e:
                    logger.error(f"Error clearing table '{table}': {str(e)}")
                    db.rollback()
            
            db.commit()
            
            logger.info(f"Total rows deleted: {total_deleted}")
            
            # Verify tables are empty
            logger.info("\nVerifying tables are empty:")
            for table in tables_to_clear:
                try:
                    result = db.execute(text(f"SELECT COUNT(*) FROM {table}"))
                    count = result.scalar()
                    logger.info(f"  {table}: {count} rows")
                except:
                    pass
            
            # Reset sequences if PostgreSQL
            if 'postgresql' in str(engine.url):
                logger.info("\nResetting sequences...")
                for table in tables_to_clear:
                    try:
                        # Find all sequences for the table
                        seq_query = text("""
                            SELECT column_name, column_default 
                            FROM information_schema.columns 
                            WHERE table_name = :table 
                            AND column_default LIKE 'nextval%'
                        """)
                        sequences = db.execute(seq_query, {"table": table}).fetchall()
                        
                        for col_name, col_default in sequences:
                            # Extract sequence name from default value
                            seq_name = col_default.split("'")[1]
                            db.execute(text(f"ALTER SEQUENCE {seq_name} RESTART WITH 1"))
                            logger.info(f"  Reset sequence {seq_name} for {table}.{col_name}")
                            
                    except Exception as e:
                        logger.warning(f"Could not reset sequences for {table}: {str(e)}")
                
                db.commit()
            
        finally:
            db.close()
            
        logger.info("\nRDS data clearing completed successfully!")
        return True
        
    except Exception as e:
        logger.error(f"Error clearing RDS data: {str(e)}")
        return False


def clear_specific_documents(document_uuids):
    """Clear data for specific documents only."""
    try:
        logger.info(f"Clearing data for {len(document_uuids)} documents...")
        
        # Get database session
        db = next(get_db())
        try:
            # Delete in reverse order of dependencies
            tables_and_columns = [
                ('processing_tasks', 'document_uuid'),
                ('relationship_staging', 'document_uuid'),
                ('canonical_entities', 'document_uuid'),
                ('entity_mentions', 'document_uuid'),
                ('document_chunks', 'document_uuid'),
                ('textract_jobs', 'document_uuid'),
                ('source_documents', 'document_uuid')
            ]
            
            total_deleted = 0
            
            for table, column in tables_and_columns:
                try:
                    # Build parameterized query
                    placeholders = ', '.join([f':uuid_{i}' for i in range(len(document_uuids))])
                    query = text(f"DELETE FROM {table} WHERE {column} IN ({placeholders})")
                    
                    # Create parameters dict
                    params = {f'uuid_{i}': str(uuid) for i, uuid in enumerate(document_uuids)}
                    
                    result = db.execute(query, params)
                    deleted = result.rowcount
                    
                    if deleted > 0:
                        logger.info(f"Deleted {deleted} rows from {table}")
                        total_deleted += deleted
                        
                except Exception as e:
                    logger.error(f"Error clearing {table}: {str(e)}")
                    
            db.commit()
            logger.info(f"Total rows deleted: {total_deleted}")
            
        finally:
            db.close()
            
        return True
        
    except Exception as e:
        logger.error(f"Error clearing specific documents: {str(e)}")
        return False


if __name__ == "__main__":
    # Parse command line arguments
    import argparse
    parser = argparse.ArgumentParser(description="Clear RDS test data")
    parser.add_argument('--documents', nargs='+', help='Clear specific document UUIDs only')
    parser.add_argument('--confirm', action='store_true', 
                        help='Skip confirmation prompt')
    args = parser.parse_args()
    
    if args.documents:
        # Clear specific documents
        if not args.confirm:
            response = input(f"Clear data for {len(args.documents)} documents? (yes/no): ")
            if response.lower() != 'yes':
                logger.info("Aborted.")
                sys.exit(0)
        
        success = clear_specific_documents(args.documents)
    else:
        # Clear all data
        if not args.confirm:
            response = input("WARNING: This will delete ALL data from the database. Continue? (yes/no): ")
            if response.lower() != 'yes':
                logger.info("Aborted.")
                sys.exit(0)
        
        success = clear_all_rds_data()
    
    sys.exit(0 if success else 1)