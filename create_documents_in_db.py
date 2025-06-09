#!/usr/bin/env python3
# create_documents_in_db.py

import json
import os
from datetime import datetime
from scripts.db import DatabaseManager
from scripts.core.models_minimal import SourceDocumentMinimal

# Load manifest
manifest_path = 'production_test_manifest_20250604_142117.json'
print(f"Loading manifest from: {manifest_path}")
with open(manifest_path, 'r') as f:
    manifest = json.load(f)

print(f"Loaded manifest with {len(manifest['documents'])} documents")

# Initialize database
db = DatabaseManager()
created_count = 0
failed_count = 0

print(f"\nCreating documents in database...")
print("="*60)

for i, doc in enumerate(manifest['documents']):
    try:
        # Get file info
        file_path = doc['file_path']
        file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
        
        # Create document record
        source_doc = SourceDocumentMinimal(
            document_uuid=doc['document_uuid'],
            project_uuid=doc['project_uuid'],
            original_file_name=doc['metadata']['original_filename'],
            source_path=file_path,
            file_size_bytes=file_size,
            upload_timestamp=datetime.utcnow(),
            document_hash=doc['metadata']['sha256']
        )
        
        # Save to database
        saved_doc = db.create_source_document(source_doc)
        
        if saved_doc:
            created_count += 1
            if (i + 1) % 10 == 0:
                print(f"Progress: {i+1}/{len(manifest['documents'])} documents created")
        else:
            failed_count += 1
            print(f"Failed to create document: {doc['metadata']['original_filename']}")
            
    except Exception as e:
        failed_count += 1
        print(f"Error creating document {doc['document_uuid']}: {str(e)}")

print(f"\n{'='*60}")
print(f"Document Creation Complete")
print(f"{'='*60}")
print(f"Total: {len(manifest['documents'])}")
print(f"Created: {created_count}")
print(f"Failed: {failed_count}")
print(f"Success Rate: {(created_count/len(manifest['documents'])*100):.1f}%")

# Verify documents in database
from scripts.models import SourceDocument
from scripts.rds_utils import DBSessionLocal
session = DBSessionLocal()
doc_count = session.query(SourceDocument).count()
session.close()
print(f"\nTotal documents in database: {doc_count}")

# Update manifest with database IDs if needed
if created_count > 0:
    print("\n✅ Documents successfully created in database!")
    print("You can now run: python3 run_production_test_v2.py")
else:
    print("\n❌ No documents were created in database!")
    print("Check error messages above for details.")