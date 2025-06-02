#!/usr/bin/env python3
"""
Check the current state of the database tables.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from scripts.config import EFFECTIVE_DATABASE_URL, logger
from datetime import datetime

def check_database_state():
    """Check the current state of key database tables."""
    
    # Create engine
    engine = create_engine(EFFECTIVE_DATABASE_URL)
    
    try:
        with engine.connect() as conn:
            print("✅ Successfully connected to database")
            print(f"   Database URL: {EFFECTIVE_DATABASE_URL.split('@')[1] if '@' in EFFECTIVE_DATABASE_URL else 'local'}")
            print("\n" + "="*80 + "\n")
            
            # Check source_documents table
            print("📄 SOURCE DOCUMENTS TABLE:")
            result = conn.execute(text("""
                SELECT 
                    COUNT(*) as total_count,
                    COUNT(DISTINCT project_id) as unique_projects,
                    MIN(created_at) as oldest_document,
                    MAX(created_at) as newest_document
                FROM source_documents
            """))
            row = result.fetchone()
            print(f"   Total documents: {row[0]}")
            print(f"   Unique projects: {row[1]}")
            print(f"   Oldest document: {row[2]}")
            print(f"   Newest document: {row[3]}")
            
            # Show recent documents
            if row[0] > 0:
                print("\n   Recent documents:")
                result = conn.execute(text("""
                    SELECT 
                        document_id,
                        filename,
                        project_id,
                        created_at,
                        status
                    FROM source_documents
                    ORDER BY created_at DESC
                    LIMIT 5
                """))
                for doc in result:
                    print(f"     - {doc[1]} (ID: {doc[0][:8]}..., Project: {doc[2][:8] if doc[2] else 'None'}..., Status: {doc[4]}, Created: {doc[3]})")
            
            print("\n" + "-"*80 + "\n")
            
            # Check processing_tasks table
            print("⚙️  PROCESSING TASKS TABLE:")
            result = conn.execute(text("""
                SELECT 
                    COUNT(*) as total_tasks,
                    COUNT(CASE WHEN status = 'pending' THEN 1 END) as pending_tasks,
                    COUNT(CASE WHEN status = 'running' THEN 1 END) as running_tasks,
                    COUNT(CASE WHEN status = 'completed' THEN 1 END) as completed_tasks,
                    COUNT(CASE WHEN status = 'failed' THEN 1 END) as failed_tasks,
                    COUNT(CASE WHEN status = 'retrying' THEN 1 END) as retrying_tasks
                FROM processing_tasks
            """))
            row = result.fetchone()
            print(f"   Total tasks: {row[0]}")
            print(f"   Pending: {row[1]}")
            print(f"   Running: {row[2]}")
            print(f"   Completed: {row[3]}")
            print(f"   Failed: {row[4]}")
            print(f"   Retrying: {row[5]}")
            
            # Show recent failed tasks
            if row[4] > 0:  # If there are failed tasks
                print("\n   Recent failed tasks:")
                result = conn.execute(text("""
                    SELECT 
                        task_id,
                        document_id,
                        task_type,
                        error_message,
                        created_at
                    FROM processing_tasks
                    WHERE status = 'failed'
                    ORDER BY created_at DESC
                    LIMIT 5
                """))
                for task in result:
                    print(f"     - Task {task[0][:8]}... ({task[2]}) for doc {task[1][:8]}...")
                    if task[3]:
                        print(f"       Error: {task[3][:100]}...")
            
            print("\n" + "-"*80 + "\n")
            
            # Check projects table
            print("📁 PROJECTS TABLE:")
            result = conn.execute(text("""
                SELECT 
                    COUNT(*) as total_projects,
                    MIN(created_at) as oldest_project,
                    MAX(created_at) as newest_project
                FROM projects
            """))
            row = result.fetchone()
            print(f"   Total projects: {row[0]}")
            print(f"   Oldest project: {row[1]}")
            print(f"   Newest project: {row[2]}")
            
            # Show all projects
            if row[0] > 0:
                print("\n   All projects:")
                result = conn.execute(text("""
                    SELECT 
                        project_id,
                        name,
                        airtable_record_id,
                        created_at
                    FROM projects
                    ORDER BY created_at DESC
                """))
                for proj in result:
                    print(f"     - {proj[1]} (ID: {proj[0][:8]}..., Airtable: {proj[2] or 'None'}, Created: {proj[3]})")
            
            print("\n" + "-"*80 + "\n")
            
            # Check chunk and entity counts
            print("📊 PROCESSING STATISTICS:")
            
            # Chunks
            result = conn.execute(text("SELECT COUNT(*) FROM document_chunks"))
            chunk_count = result.scalar()
            print(f"   Total chunks: {chunk_count}")
            
            # Entity mentions
            result = conn.execute(text("SELECT COUNT(*) FROM entity_mentions"))
            mention_count = result.scalar()
            print(f"   Total entity mentions: {mention_count}")
            
            # Canonical entities
            result = conn.execute(text("SELECT COUNT(*) FROM canonical_entities"))
            canonical_count = result.scalar()
            print(f"   Total canonical entities: {canonical_count}")
            
            # Relationships
            result = conn.execute(text("SELECT COUNT(*) FROM relationship_staging"))
            relationship_count = result.scalar()
            print(f"   Total relationships: {relationship_count}")
            
            print("\n" + "="*80 + "\n")
            
    except Exception as e:
        print(f"❌ Error connecting to database: {str(e)}")
        return False
    
    return True

if __name__ == "__main__":
    check_database_state()