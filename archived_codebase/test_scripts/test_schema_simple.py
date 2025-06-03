#!/usr/bin/env python3
"""
Simple Schema Conformance Test
Direct database connection test without DatabaseManager
"""

import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# Load environment
load_dotenv()

def test_schema():
    """Test schema conformance directly."""
    # Force use tunnel connection
    DATABASE_URL = 'postgresql://app_user:LegalDoc2025!Secure@localhost:5433/legal_doc_processing'
    
    print(f"Connecting to: {DATABASE_URL}")
    engine = create_engine(DATABASE_URL)
    
    expected_tables = [
        'projects',
        'source_documents',
        'import_sessions',
        'neo4j_documents',
        'document_chunks',
        'entity_mentions',
        'canonical_entities',
        'relationship_staging',
        'textract_jobs',
        'chunk_embeddings',
        'canonical_entity_embeddings',
        'document_processing_history'
    ]
    
    print("\n=== SCHEMA CONFORMANCE TEST ===\n")
    
    with engine.connect() as conn:
        # Get existing tables
        result = conn.execute(text("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """))
        
        existing_tables = [row[0] for row in result]
        
        print("Expected tables:")
        all_found = True
        for table in expected_tables:
            exists = table in existing_tables
            status = "✓" if exists else "✗"
            print(f"  {status} {table}")
            if not exists:
                all_found = False
                
        print(f"\nOther tables in database:")
        for table in existing_tables:
            if table not in expected_tables and table != 'schema_version':
                print(f"  - {table}")
                
        # Test a sample insert
        print("\n=== TESTING DATABASE OPERATIONS ===\n")
        
        try:
            # Insert test project
            result = conn.execute(text("""
                INSERT INTO projects (name, client_name, matter_type)
                VALUES (:name, :client_name, :matter_type)
                RETURNING project_uuid, id
            """), {
                'name': 'Test Project',
                'client_name': 'Test Client',
                'matter_type': 'Test Matter'
            })
            
            row = result.fetchone()
            project_uuid = row[0]
            project_id = row[1]
            print(f"✓ Created project: {project_uuid} (id: {project_id})")
            
            # Insert test document
            result = conn.execute(text("""
                INSERT INTO source_documents (project_uuid, filename, file_type)
                VALUES (:project_uuid, :filename, :file_type)
                RETURNING document_uuid, id, project_fk_id
            """), {
                'project_uuid': project_uuid,
                'filename': 'test.pdf',
                'file_type': 'pdf'
            })
            
            row = result.fetchone()
            document_uuid = row[0]
            document_id = row[1]
            project_fk_id = row[2]
            print(f"✓ Created document: {document_uuid} (id: {document_id}, project_fk_id: {project_fk_id})")
            
            # Verify trigger populated FK
            if project_fk_id == project_id:
                print("✓ Trigger correctly populated project_fk_id")
            else:
                print(f"✗ Trigger failed: expected project_fk_id={project_id}, got {project_fk_id}")
                
            # Cleanup
            conn.execute(text("DELETE FROM source_documents WHERE document_uuid = :uuid"), {'uuid': document_uuid})
            conn.execute(text("DELETE FROM projects WHERE project_uuid = :uuid"), {'uuid': project_uuid})
            conn.commit()
            print("✓ Cleanup successful")
            
        except Exception as e:
            print(f"✗ Operation failed: {e}")
            conn.rollback()
            
        print("\n=== SUMMARY ===")
        if all_found:
            print("\n✅ ALL TABLES EXIST - Schema is conformant!")
        else:
            print("\n❌ MISSING TABLES - Schema needs attention")


if __name__ == '__main__':
    test_schema()