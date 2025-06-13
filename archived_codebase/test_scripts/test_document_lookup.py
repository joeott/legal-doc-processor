#!/usr/bin/env python3
import os
import sys
import logging

# Set up Python path
sys.path.insert(0, '/opt/legal-doc-processor')

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Import the necessary modules
from scripts.db import DatabaseManager
from scripts.rds_utils import execute_query

# Test document UUID from earlier
document_uuid = "4dcc5583-b2cc-4d68-bdd0-6e227a98cf8b"

print(f"\nTesting document lookup for UUID: {document_uuid}")
print("="*50)

# First, let's check if the document exists with a direct SQL query
print("\n1. Direct SQL query:")
query = "SELECT document_uuid, file_name, status FROM source_documents WHERE document_uuid = :uuid"
results = execute_query(query, {"uuid": document_uuid})
print(f"Results: {results}")

# Now test through the DatabaseManager
print("\n2. DatabaseManager lookup:")
db_manager = DatabaseManager(validate_conformance=False)
document = db_manager.get_source_document(document_uuid)
print(f"Document found: {document is not None}")
if document:
    print(f"Document details: {document}")

# Test with PydanticDatabase directly
print("\n3. PydanticDatabase lookup:")
from scripts.db import PydanticDatabase
from scripts.core.schemas import SourceDocumentModel
pydantic_db = PydanticDatabase()
document = pydantic_db.get("source_documents", SourceDocumentModel, {"document_uuid": document_uuid})
print(f"Document found: {document is not None}")
if document:
    print(f"Document details: {document}")

# Let's also check what all documents are in the database
print("\n4. All documents in database:")
all_docs_query = "SELECT document_uuid, file_name, status FROM source_documents LIMIT 5"
all_docs = execute_query(all_docs_query)
for doc in all_docs:
    print(f"  - UUID: {doc['document_uuid']}, File: {doc['file_name']}, Status: {doc['status']}")