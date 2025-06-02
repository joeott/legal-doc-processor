#!/usr/bin/env python3
"""
Phase 2: Test database schema conformance with Pydantic models
"""
import os
import sys
sys.path.insert(0, '/opt/legal-doc-processor')

from dotenv import load_dotenv
load_dotenv()

import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

from scripts.db import DatabaseManager
from scripts.core.schemas import ProjectModel, SourceDocumentModel, ChunkModel
from scripts.rds_utils import execute_query
import uuid
from datetime import datetime, timezone

print("Phase 2: Database Schema Conformance Testing")
print("=" * 50)

# Test 1: Direct table inspection
print("\n1. Inspecting actual database schema:")
print("-" * 50)

# Check projects table
projects_schema = execute_query("""
    SELECT column_name, data_type, is_nullable, column_default
    FROM information_schema.columns
    WHERE table_name = 'projects'
    ORDER BY ordinal_position
""")

print("\nProjects table columns:")
for col in projects_schema:
    print(f"  {col['column_name']}: {col['data_type']} (nullable: {col['is_nullable']}, default: {col['column_default']})")

# Check source_documents table
docs_schema = execute_query("""
    SELECT column_name, data_type, is_nullable, column_default
    FROM information_schema.columns
    WHERE table_name = 'source_documents'
    ORDER BY ordinal_position
""")

print("\nSource_documents table columns:")
for col in docs_schema:
    print(f"  {col['column_name']}: {col['data_type']} (nullable: {col['is_nullable']}, default: {col['column_default']})")

# Test 2: Try to create a project using Pydantic model
print("\n\n2. Testing CRUD operations with Pydantic models:")
print("-" * 50)

db_manager = DatabaseManager(validate_conformance=False)

# Create a project with minimal data
print("\nCreating project with minimal data...")
project = ProjectModel(name="Test Project Phase 2")
print(f"Model created: project_id={project.project_id}, name={project.name}")

try:
    created_project = db_manager.create_project(project)
    print(f"✓ Project created in database: id={created_project.id}")
except Exception as e:
    print(f"✗ Failed to create project: {e}")
    import traceback
    traceback.print_exc()

# Test 3: Create a source document
print("\n\nCreating source document...")
test_uuid = uuid.uuid4()
doc = SourceDocumentModel(
    document_uuid=test_uuid,
    original_file_name="test_phase2.pdf",
    detected_file_type="application/pdf",
    project_fk_id=1,  # Assume project exists
    s3_bucket="test-bucket",
    s3_key=f"documents/{test_uuid}.pdf"
)

try:
    created_doc = db_manager.create_source_document(doc)
    print(f"✓ Document created in database: id={created_doc.id}")
except Exception as e:
    print(f"✗ Failed to create document: {e}")
    import traceback
    traceback.print_exc()

# Test 4: Retrieve the document
print("\n\nRetrieving document...")
try:
    retrieved_doc = db_manager.get_source_document(str(test_uuid))
    if retrieved_doc:
        print(f"✓ Document retrieved: {retrieved_doc.original_file_name}")
        print(f"  Status: {retrieved_doc.status}")
        print(f"  Created at: {retrieved_doc.created_at}")
    else:
        print("✗ Document not found")
except Exception as e:
    print(f"✗ Failed to retrieve document: {e}")

# Test 5: Check for column mapping issues
print("\n\n3. Column Mapping Analysis:")
print("-" * 50)

# Try direct insert without mappings to see what fails
print("\nTesting direct insert (no column mappings)...")
test_data = {
    "document_uuid": str(uuid.uuid4()),
    "original_file_name": "direct_test.pdf",
    "detected_file_type": "application/pdf",
    "status": "pending",
    "file_name": "direct_test.pdf"
}

try:
    result = execute_query("""
        INSERT INTO source_documents (document_uuid, original_file_name, detected_file_type, status, file_name)
        VALUES (:document_uuid, :original_file_name, :detected_file_type, :status, :file_name)
        RETURNING id
    """, test_data)
    print(f"✓ Direct insert succeeded: id={result[0]['id']}")
except Exception as e:
    print(f"✗ Direct insert failed: {e}")
    print("  This indicates column name or constraint issues")

# Summary
print("\n\n4. Summary of Findings:")
print("-" * 50)
print("Check the output above for:")
print("  - Column name mismatches")
print("  - Missing columns")
print("  - Type mismatches")
print("  - Default value issues")