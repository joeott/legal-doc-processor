#!/usr/bin/env python3
"""
Clean test data from the database before E2E testing.
"""
import os
import sys
from datetime import datetime, timedelta

# Set environment variables
os.environ['USE_MINIMAL_MODELS'] = 'true'
os.environ['SKIP_CONFORMANCE_CHECK'] = 'true'

from scripts.db import DatabaseManager
from scripts.cache import get_redis_manager
from sqlalchemy import text

def clean_test_data(hours_back=24):
    """Clean test data from the last N hours"""
    print(f"=== Cleaning Test Data ===")
    print(f"Removing data from the last {hours_back} hours...")
    
    db_manager = DatabaseManager()
    redis_manager = get_redis_manager()
    
    cutoff_time = datetime.utcnow() - timedelta(hours=hours_back)
    
    # Clean database
    for session in db_manager.get_session():
        try:
            # Get document UUIDs to clean
            result = session.execute(
                text("SELECT document_uuid FROM source_documents WHERE created_at > :cutoff"),
                {"cutoff": cutoff_time}
            )
            doc_uuids = [row[0] for row in result]
            
            if doc_uuids:
                print(f"\nFound {len(doc_uuids)} documents to clean")
                
                # Clean in reverse order of dependencies
                tables = [
                    "relationship_staging",
                    "canonical_entities", 
                    "entity_mentions",
                    "document_chunks",
                    "textract_jobs",
                    "source_documents"
                ]
                
                for table in tables:
                    try:
                        result = session.execute(
                            text(f"DELETE FROM {table} WHERE document_uuid = ANY(:uuids)"),
                            {"uuids": doc_uuids}
                        )
                        print(f"  - Deleted {result.rowcount} rows from {table}")
                    except Exception as e:
                        print(f"  - Error cleaning {table}: {e}")
                
                session.commit()
                
                # Clean Redis cache for each document
                print("\nCleaning Redis cache...")
                for doc_uuid in doc_uuids:
                    patterns = [
                        f"doc:*:{doc_uuid}*",
                        f"cache:*:{doc_uuid}*",
                        f"task:*:{doc_uuid}*"
                    ]
                    
                    total_deleted = 0
                    for pattern in patterns:
                        deleted = redis_manager.delete_pattern(pattern)
                        total_deleted += deleted
                    
                    if total_deleted > 0:
                        print(f"  - Deleted {total_deleted} keys for {doc_uuid}")
            else:
                print("No test documents found to clean")
                
        except Exception as e:
            print(f"Error during cleanup: {e}")
            session.rollback()
            return False
            
    print("\n✅ Cleanup completed successfully")
    return True

if __name__ == "__main__":
    hours = int(sys.argv[1]) if len(sys.argv) > 1 else 24
    success = clean_test_data(hours)
    sys.exit(0 if success else 1)