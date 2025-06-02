#!/usr/bin/env python3
"""Apply RDS schema fixes to match Pydantic models"""

import os
import sys
from pathlib import Path

# Set up Python path
sys.path.insert(0, str(Path(__file__).parent))

# Load environment
from dotenv import load_dotenv
load_dotenv()

from scripts.config import db_engine
from sqlalchemy import text
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def execute_sql(conn, sql, description):
    """Execute a single SQL statement with proper error handling"""
    try:
        logger.info(f"Executing: {description}")
        conn.execute(text(sql))
        conn.commit()
        logger.info(f"✓ Success: {description}")
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"✗ Failed: {description}")
        logger.error(f"  Error: {e}")
        return False

def main():
    """Apply schema fixes"""
    
    with db_engine.connect() as conn:
        # 1. Fix source_documents table
        execute_sql(conn, 
            "ALTER TABLE source_documents RENAME COLUMN filename TO file_name",
            "Rename filename to file_name")
        
        execute_sql(conn,
            "ALTER TABLE source_documents RENAME COLUMN processing_status TO status",
            "Rename processing_status to status")
        
        execute_sql(conn, """
            ALTER TABLE source_documents 
            ADD COLUMN IF NOT EXISTS processing_completed_at TIMESTAMP WITH TIME ZONE,
            ADD COLUMN IF NOT EXISTS error_message TEXT,
            ADD COLUMN IF NOT EXISTS retry_count INTEGER DEFAULT 0,
            ADD COLUMN IF NOT EXISTS last_retry_at TIMESTAMP WITH TIME ZONE
        """, "Add missing columns to source_documents")
        
        # 2. Create processing_tasks table
        execute_sql(conn, """
            CREATE TABLE IF NOT EXISTS processing_tasks (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                document_id UUID NOT NULL,
                task_type VARCHAR(50) NOT NULL,
                status VARCHAR(50) NOT NULL DEFAULT 'pending',
                celery_task_id VARCHAR(255),
                error_message TEXT,
                retry_count INTEGER DEFAULT 0,
                started_at TIMESTAMP WITH TIME ZONE,
                completed_at TIMESTAMP WITH TIME ZONE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
        """, "Create processing_tasks table")
        
        # Add foreign key constraint separately
        execute_sql(conn, """
            ALTER TABLE processing_tasks
            ADD CONSTRAINT processing_tasks_document_id_fkey 
            FOREIGN KEY (document_id) 
            REFERENCES source_documents(document_uuid) 
            ON DELETE CASCADE
        """, "Add foreign key to processing_tasks")
        
        # Create indexes
        execute_sql(conn, 
            "CREATE INDEX IF NOT EXISTS idx_processing_tasks_document_id ON processing_tasks(document_id)",
            "Create index on processing_tasks.document_id")
        
        execute_sql(conn,
            "CREATE INDEX IF NOT EXISTS idx_processing_tasks_status ON processing_tasks(status)",
            "Create index on processing_tasks.status")
        
        # 3. Fix document_chunks table
        execute_sql(conn,
            "ALTER TABLE document_chunks RENAME COLUMN content TO text",
            "Rename content to text in document_chunks")
        
        execute_sql(conn, """
            ALTER TABLE document_chunks 
            ADD COLUMN IF NOT EXISTS start_char_index INTEGER,
            ADD COLUMN IF NOT EXISTS end_char_index INTEGER,
            ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}'
        """, "Add missing columns to document_chunks")
        
        # 4. Fix entity_mentions
        execute_sql(conn, """
            ALTER TABLE entity_mentions 
            ADD COLUMN IF NOT EXISTS chunk_id UUID,
            ADD COLUMN IF NOT EXISTS confidence_score NUMERIC(5,4)
        """, "Add missing columns to entity_mentions")
        
        # 5. Fix projects table
        execute_sql(conn, """
            ALTER TABLE projects 
            ADD COLUMN IF NOT EXISTS description TEXT,
            ADD COLUMN IF NOT EXISTS status VARCHAR(50) DEFAULT 'active',
            ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}',
            ADD COLUMN IF NOT EXISTS client_name VARCHAR(255),
            ADD COLUMN IF NOT EXISTS matter_number VARCHAR(100)
        """, "Add missing columns to projects")
        
        # 6. Create update trigger function
        execute_sql(conn, """
            CREATE OR REPLACE FUNCTION update_updated_at_column()
            RETURNS TRIGGER AS $$
            BEGIN
                NEW.updated_at = CURRENT_TIMESTAMP;
                RETURN NEW;
            END;
            $$ language 'plpgsql'
        """, "Create update_updated_at trigger function")
        
        # 7. Create trigger for processing_tasks
        execute_sql(conn, """
            CREATE TRIGGER update_processing_tasks_updated_at 
            BEFORE UPDATE ON processing_tasks 
            FOR EACH ROW 
            EXECUTE FUNCTION update_updated_at_column()
        """, "Create updated_at trigger for processing_tasks")
        
        # 8. Create performance indexes
        execute_sql(conn,
            "CREATE INDEX IF NOT EXISTS idx_source_documents_status ON source_documents(status)",
            "Create index on source_documents.status")
        
        execute_sql(conn,
            "CREATE INDEX IF NOT EXISTS idx_source_documents_document_uuid ON source_documents(document_uuid)",
            "Create index on source_documents.document_uuid")
        
        # 9. Verify the changes
        logger.info("\n=== Verifying Schema Changes ===")
        
        # Check source_documents columns
        result = conn.execute(text("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'source_documents' 
            AND column_name IN ('file_name', 'status', 'processing_completed_at')
            ORDER BY column_name
        """))
        
        logger.info("\nSource_documents key columns:")
        for col_name, data_type in result:
            logger.info(f"  - {col_name}: {data_type}")
        
        # Check if processing_tasks exists
        result = conn.execute(text("""
            SELECT COUNT(*) 
            FROM information_schema.tables 
            WHERE table_name = 'processing_tasks'
        """))
        
        if result.scalar() > 0:
            logger.info("\n✓ processing_tasks table created successfully")
        else:
            logger.error("\n✗ processing_tasks table not found")
        
        # Check document_chunks columns
        result = conn.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'document_chunks' 
            AND column_name = 'text'
        """))
        
        if result.fetchone():
            logger.info("✓ document_chunks.text column exists")
        else:
            logger.error("✗ document_chunks.text column not found")

if __name__ == "__main__":
    main()