#!/usr/bin/env python3
"""Find documents with real S3 keys"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from scripts.rds_utils import execute_query

# Look for documents with real S3 keys
query = """
    SELECT document_uuid, original_file_name, s3_key, s3_bucket, status, celery_status
    FROM source_documents
    WHERE s3_key IS NOT NULL
    AND s3_bucket IS NOT NULL
    AND s3_bucket != 'test-bucket'
    AND detected_file_type IN ('application/pdf', 'pdf')
    ORDER BY created_at DESC
    LIMIT 10
"""

results = execute_query(query)

if results:
    print(f"Found {len(results)} documents with real S3 keys:")
    for doc in results:
        print(f"\nDocument: {doc['document_uuid']}")
        print(f"  File: {doc['original_file_name']}")
        print(f"  S3: s3://{doc['s3_bucket']}/{doc['s3_key']}")
        print(f"  Status: {doc['status']} | Celery: {doc['celery_status']}")
else:
    print("No documents found with real S3 keys")
    
    # Check any documents
    any_docs = execute_query("""
        SELECT document_uuid, original_file_name, s3_key, s3_bucket, detected_file_type
        FROM source_documents
        WHERE s3_key IS NOT NULL
        LIMIT 5
    """)
    
    if any_docs:
        print("\nFound these documents with S3 keys:")
        for doc in any_docs:
            print(f"\nDocument: {doc['document_uuid']}")
            print(f"  File: {doc['original_file_name']}")
            print(f"  Type: {doc['detected_file_type']}")
            print(f"  S3: s3://{doc['s3_bucket']}/{doc['s3_key']}")