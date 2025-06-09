#!/usr/bin/env python3
"""Comprehensive cleanup script to clear all test data from Redis, S3, and RDS."""

import os
import sys
import boto3
from scripts.cache import get_redis_manager
from scripts.db import DatabaseManager
from scripts.config import S3_PRIMARY_DOCUMENT_BUCKET, S3_BUCKET_REGION, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY
from sqlalchemy import text

def clear_redis_cache():
    """Clear all document-related cache entries from Redis."""
    print("\n=== Clearing Redis Cache ===")
    try:
        redis = get_redis_manager()
        client = redis.get_client()
        
        # Patterns to clear
        patterns = [
            "doc:*",
            "batch:*",
            "chunks:*",
            "entities:*",
            "ocr:*",
            "entity_cache:*",
            "chunk_cache:*",
            "validation:*",
            "task:*",
            "result:*",
            "textract:*",
            "processing:*"
        ]
        
        total_deleted = 0
        
        for pattern in patterns:
            keys = client.keys(pattern)
            if keys:
                deleted = client.delete(*keys)
                print(f"  Deleted {deleted} keys matching '{pattern}'")
                total_deleted += deleted
        
        print(f"\nTotal Redis keys deleted: {total_deleted}")
        return True
        
    except Exception as e:
        print(f"Error clearing Redis: {e}")
        return False

def clear_s3_documents():
    """Clear all documents from S3 bucket (keeping bucket intact)."""
    print("\n=== Clearing S3 Documents ===")
    try:
        # Initialize S3 client
        s3_client = boto3.client(
            's3',
            region_name=S3_BUCKET_REGION,
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY
        )
        
        # List and delete all objects in the documents/ prefix
        paginator = s3_client.get_paginator('list_objects_v2')
        pages = paginator.paginate(Bucket=S3_PRIMARY_DOCUMENT_BUCKET, Prefix='documents/')
        
        total_deleted = 0
        objects_to_delete = []
        
        for page in pages:
            if 'Contents' in page:
                for obj in page['Contents']:
                    objects_to_delete.append({'Key': obj['Key']})
                    
                    # Delete in batches of 1000 (S3 limit)
                    if len(objects_to_delete) >= 1000:
                        response = s3_client.delete_objects(
                            Bucket=S3_PRIMARY_DOCUMENT_BUCKET,
                            Delete={'Objects': objects_to_delete}
                        )
                        total_deleted += len(objects_to_delete)
                        objects_to_delete = []
        
        # Delete remaining objects
        if objects_to_delete:
            response = s3_client.delete_objects(
                Bucket=S3_PRIMARY_DOCUMENT_BUCKET,
                Delete={'Objects': objects_to_delete}
            )
            total_deleted += len(objects_to_delete)
        
        print(f"  Deleted {total_deleted} documents from S3 bucket: {S3_PRIMARY_DOCUMENT_BUCKET}")
        return True
        
    except Exception as e:
        print(f"Error clearing S3: {e}")
        return False

def clear_rds_test_data():
    """Clear test data from RDS database while preserving projects."""
    print("\n=== Clearing RDS Test Data ===")
    try:
        db = DatabaseManager(validate_conformance=False)
        
        for session in db.get_session():
            try:
                # Clear tables in reverse dependency order
                tables = [
                    ('relationship_staging', 'Entity relationships'),
                    ('canonical_entities', 'Canonical entities'),
                    ('entity_mentions', 'Entity mentions'),
                    ('document_chunks', 'Document chunks'),
                    ('processing_tasks', 'Processing tasks'),
                    ('textract_jobs', 'Textract jobs'),
                    ('source_documents', 'Source documents'),
                    # Projects table is preserved
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
                
                # Show remaining projects
                project_count = session.execute(text("SELECT COUNT(*) FROM projects")).scalar()
                if project_count > 0:
                    print(f"\nProjects preserved: {project_count}")
                    projects = session.execute(text(
                        "SELECT id, project_name FROM projects ORDER BY id LIMIT 5"
                    )).fetchall()
                    for p in projects:
                        print(f"  ID: {p[0]}, Name: {p[1]}")
                
                return True
                        
            except Exception as e:
                session.rollback()
                print(f"Error clearing RDS data: {e}")
                return False
                
    except Exception as e:
        print(f"Error connecting to RDS: {e}")
        return False

def main():
    """Main cleanup function."""
    print("=== Comprehensive Test Data Cleanup ===")
    print("This will clear all test data from:")
    print("  - Redis cache")
    print("  - S3 documents bucket")
    print("  - RDS database (except projects)")
    
    # Check for --no-confirm flag
    if len(sys.argv) > 1 and sys.argv[1] == '--no-confirm':
        print("\nRunning without confirmation...")
    else:
        print("\nPress Enter to continue or Ctrl+C to cancel...")
        try:
            input()
        except KeyboardInterrupt:
            print("\nCleanup cancelled.")
            sys.exit(0)
    
    # Track success
    all_success = True
    
    # Clear Redis
    if not clear_redis_cache():
        all_success = False
    
    # Clear S3
    if not clear_s3_documents():
        all_success = False
    
    # Clear RDS
    if not clear_rds_test_data():
        all_success = False
    
    # Summary
    print("\n=== Cleanup Summary ===")
    if all_success:
        print("✓ All test data cleared successfully!")
        print("✓ Ready for clean single document test run")
    else:
        print("✗ Some cleanup operations failed. Check error messages above.")
        sys.exit(1)

if __name__ == "__main__":
    main()