#!/usr/bin/env python3
"""Test 2.2: Document Creation with Minimal Models"""

print("=== Test 2.2: Document Creation with Minimal Models ===")
import sys
import os
import uuid
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

try:
    from scripts.core.model_factory import get_source_document_model
    from scripts.db import DatabaseManager
    from scripts.config import USE_MINIMAL_MODELS
    
    print(f"USE_MINIMAL_MODELS: {USE_MINIMAL_MODELS}")
    
    # Get the appropriate model class
    SourceDocument = get_source_document_model()
    print(f"Using model: {SourceDocument.__name__}")
    
    # Create test document with minimal fields
    test_uuid = str(uuid.uuid4())
    print(f"\nCreating test document with UUID: {test_uuid}")
    
    doc = SourceDocument(
        document_uuid=test_uuid,
        original_file_name="test_minimal_models.pdf",
        s3_bucket="samu-docs-private-upload",
        s3_key=f"test/{test_uuid}/test.pdf"
    )
    
    # Display document fields
    print(f"\nDocument fields ({len(doc.__dict__)} attributes):")
    for key, value in doc.__dict__.items():
        if not key.startswith('_'):
            print(f"  - {key}: {value}")
    
    # Save to database
    print("\nSaving to database...")
    db = DatabaseManager(validate_conformance=False)
    
    # Use the create_source_document method
    result = db.create_source_document(doc)
    
    if result:
        print(f"✓ Document created successfully")
        print(f"  Document UUID: {result.document_uuid}")
        
        # Verify retrieval
        print("\nRetrieving document from database...")
        retrieved = db.get_source_document(test_uuid)
        
        if retrieved:
            print("✓ Document retrieved successfully")
            print(f"  Retrieved UUID: {retrieved.document_uuid}")
            print(f"  Retrieved filename: {retrieved.original_file_name}")
            print("\n✓ Test 2.2 PASSED")
            
            # Save UUID for later tests
            with open('/tmp/test_doc_uuid.txt', 'w') as f:
                f.write(test_uuid)
            print(f"\nTest document UUID saved to /tmp/test_doc_uuid.txt")
        else:
            print("✗ Failed to retrieve document")
            sys.exit(1)
    else:
        print("✗ Document creation failed")
        sys.exit(1)
        
except Exception as e:
    print(f"\n✗ Test failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)