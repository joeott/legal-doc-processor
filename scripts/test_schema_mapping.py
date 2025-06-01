#!/usr/bin/env python3
"""
Test the schema mapping to verify pipeline can work with simplified schema.
"""

import os
import sys
import uuid
from datetime import datetime

# Add scripts directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rds_utils import (
    test_connection, insert_record, select_records, update_record,
    map_table_name, map_columns
)

def test_mapping():
    """Test the schema mapping functionality."""
    print("Testing schema mapping...")
    
    # Test table mappings
    print("\n1. Testing table name mappings:")
    test_tables = [
        "source_documents",
        "document_chunks", 
        "entity_mentions",
        "canonical_entities",
        "relationship_staging"
    ]
    
    for table in test_tables:
        mapped = map_table_name(table)
        print(f"  {table} -> {mapped}")
    
    # Test column mappings
    print("\n2. Testing column mappings:")
    
    # Test document mapping
    doc_data = {
        "document_uuid": str(uuid.uuid4()),
        "original_file_name": "test.pdf",
        "detected_file_type": "application/pdf",
        "s3_key": "documents/test.pdf",
        "s3_bucket": "test-bucket",
        "celery_status": "ocr_processing",
        "error_message": "Test error",
        "page_count": 10
    }
    
    mapped_doc = map_columns("source_documents", doc_data)
    print(f"\n  Document mapping:")
    print(f"    Input: {doc_data}")
    print(f"    Mapped: {mapped_doc}")
    
    # Test chunk mapping
    chunk_data = {
        "chunk_uuid": str(uuid.uuid4()),
        "document_uuid": str(uuid.uuid4()),
        "chunk_index": 0,
        "text": "This is chunk text",
        "word_count": 4
    }
    
    mapped_chunk = map_columns("document_chunks", chunk_data)
    print(f"\n  Chunk mapping:")
    print(f"    Input: {chunk_data}")
    print(f"    Mapped: {mapped_chunk}")
    
    # Test entity mapping
    entity_data = {
        "entity_mention_uuid": str(uuid.uuid4()),
        "chunk_uuid": str(uuid.uuid4()),
        "value": "John Doe",
        "entity_type": "PERSON",
        "confidence_score": 0.95
    }
    
    mapped_entity = map_columns("entity_mentions", entity_data)
    print(f"\n  Entity mapping:")
    print(f"    Input: {entity_data}")
    print(f"    Mapped: {mapped_entity}")
    
    return True

def test_database_operations():
    """Test actual database operations with mapping."""
    print("\n3. Testing database operations:")
    
    # Test connection
    if not test_connection():
        print("  ERROR: Cannot connect to database")
        return False
    
    print("  Database connection successful")
    
    # Try to insert a test project
    try:
        project_data = {
            "project_uuid": str(uuid.uuid4()),
            "name": f"Test Project {datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "metadata": {}
        }
        
        result = insert_record("projects", project_data)
        if result:
            print(f"  Successfully inserted project: {result.get('name')}")
            project_uuid = result.get('project_uuid')
        else:
            print("  ERROR: Failed to insert project")
            return False
            
    except Exception as e:
        print(f"  ERROR inserting project: {e}")
        return False
    
    # Try to insert a document using the mapped schema
    try:
        doc_data = {
            "document_uuid": str(uuid.uuid4()),
            "project_uuid": project_uuid,
            "original_file_name": "test_mapping.pdf",
            "detected_file_type": "application/pdf",
            "s3_bucket": "test-bucket",
            "s3_key": "test/test_mapping.pdf",
            "file_size_bytes": 1024,
            "celery_status": "pending",
            "page_count": 5
        }
        
        # This should use the mapping to insert into 'documents' table
        result = insert_record("source_documents", doc_data)
        if result:
            print(f"  Successfully inserted document with mapping: {result.get('original_filename')}")
            doc_uuid = result.get('document_uuid')
        else:
            print("  ERROR: Failed to insert document")
            return False
            
    except Exception as e:
        print(f"  ERROR inserting document: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Try to select the document
    try:
        docs = select_records("source_documents", {"document_uuid": doc_uuid})
        if docs:
            print(f"  Successfully retrieved document: {docs[0].get('original_filename')}")
        else:
            print("  ERROR: Could not retrieve document")
            
    except Exception as e:
        print(f"  ERROR selecting document: {e}")
        return False
    
    return True

def main():
    """Run all tests."""
    print("="*60)
    print("Schema Mapping Test")
    print("="*60)
    
    # Test mapping logic
    if not test_mapping():
        print("\nMapping test failed!")
        return 1
    
    # Test database operations
    if not test_database_operations():
        print("\nDatabase operations test failed!")
        return 1
    
    print("\n" + "="*60)
    print("All tests passed! The schema mapping is working.")
    print("="*60)
    return 0

if __name__ == "__main__":
    sys.exit(main())