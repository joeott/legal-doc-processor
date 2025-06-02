#!/usr/bin/env python3
import sys
sys.path.insert(0, '/opt/legal-doc-processor')

from scripts.core.schemas import ProjectModel, SourceDocumentModel
import uuid

print("Testing ProjectModel UUID generation:")
print("-" * 50)

# Test 1: Create project without project_id
project1 = ProjectModel(name="Test Project")
print(f"Project created without project_id:")
print(f"  project_id: {project1.project_id} (type: {type(project1.project_id)})")
print(f"  project_id is None: {project1.project_id is None}")

# Test 2: Create project with explicit None
project2 = ProjectModel(name="Test Project 2", project_id=None)
print(f"\nProject created with project_id=None:")
print(f"  project_id: {project2.project_id} (type: {type(project2.project_id)})")

# Test 3: Check field names
print(f"\nField name access:")
print(f"  script_run_count: {project1.script_run_count}")
try:
    print(f"  scriptRunCount: {project1.scriptRunCount}")
except AttributeError as e:
    print(f"  scriptRunCount: AttributeError - {e}")

# Test 4: Check timestamps
print(f"\nTimestamp fields:")
print(f"  created_at: {project1.created_at}")
print(f"  updated_at: {project1.updated_at}")

# Test 5: SourceDocumentModel
print("\n\nTesting SourceDocumentModel:")
print("-" * 50)
try:
    doc = SourceDocumentModel(
        original_file_name="test.pdf",
        detected_file_type="application/pdf"
    )
    print("ERROR: Created document without document_uuid (should have failed)")
except Exception as e:
    print(f"Correctly failed without document_uuid: {e}")

# Test 6: Create with UUID
doc = SourceDocumentModel(
    document_uuid=uuid.uuid4(),
    original_file_name="test.pdf", 
    detected_file_type="application/pdf"
)
print(f"\nDocument created with UUID:")
print(f"  document_uuid: {doc.document_uuid}")
print(f"  created_at: {doc.created_at}")
print(f"  initial_processing_status: {doc.initial_processing_status}")