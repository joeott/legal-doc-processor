#!/usr/bin/env python3
"""Clear test data from RDS database."""

from scripts.db import DatabaseManager
from sqlalchemy import text

def clear_test_data():
    """Clear test data from database while preserving projects."""
    db = DatabaseManager(validate_conformance=False)
    
    print("Clearing RDS test data...")
    
    for session in db.get_session():
        try:
            # Clear tables in reverse dependency order
            tables = [
                ('relationship_staging', 'Entity relationships'),
                ('canonical_entities', 'Canonical entities'),
                ('entity_mentions', 'Entity mentions'),
                ('document_chunks', 'Document chunks'),
                ('processing_tasks', 'Processing tasks'),
                ('textract_jobs', 'Textract jobs'),  # Clear before source_documents
                ('source_documents', 'Source documents'),
                # Keep projects table intact
            ]
            
            for table, description in tables:
                # Get count before deletion
                count = session.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
                
                if count > 0:
                    # Delete all records
                    session.execute(text(f"DELETE FROM {table}"))
                    print(f"  Deleted {count} records from {table} ({description})")
                else:
                    print(f"  No records in {table}")
            
            # Commit all deletions
            session.commit()
            print("\nRDS test data cleared successfully!")
            
            # Show remaining projects
            project_count = session.execute(text("SELECT COUNT(*) FROM projects")).scalar()
            if project_count > 0:
                print(f"\nProjects preserved: {project_count}")
                projects = session.execute(text(
                    "SELECT id, project_name FROM projects ORDER BY id LIMIT 5"
                )).fetchall()
                for p in projects:
                    print(f"  ID: {p[0]}, Name: {p[1]}")
                    
        except Exception as e:
            session.rollback()
            print(f"Error clearing data: {e}")
            raise

if __name__ == "__main__":
    clear_test_data()