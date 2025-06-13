#!/usr/bin/env python3
"""Quick script to check the status of the latest pipeline run."""

import os
import sys
from datetime import datetime, timedelta

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from scripts.db import DatabaseManager
from scripts.cache import get_redis_manager, CacheKeys
from sqlalchemy import text

def main():
    # Initialize managers
    db = DatabaseManager()
    redis = get_redis_manager()
    
    session = next(db.get_session())
    try:
        # Get latest document
        result = session.execute(text("""
            SELECT document_uuid, status, file_name, created_at
            FROM source_documents 
            ORDER BY created_at DESC 
            LIMIT 1
        """))
        
        row = result.fetchone()
        if not row:
            print("No documents found in database")
            return
            
        doc_uuid, status, file_name, created_at = row
        print(f"\nLatest Document:")
        print(f"  UUID: {doc_uuid}")
        print(f"  File: {file_name}")
        print(f"  Status: {status}")
        print(f"  Created: {created_at}")
        # Handle timezone-aware datetime
        from datetime import timezone
        now = datetime.now(timezone.utc) if created_at.tzinfo else datetime.now()
        print(f"  Age: {now - created_at}")
        
        # Check processing tasks
        print("\nProcessing Tasks:")
        tasks_result = session.execute(text("""
            SELECT task_type, status, started_at, completed_at, error_message
            FROM processing_tasks
            WHERE document_id = :uuid
            ORDER BY created_at
        """), {'uuid': doc_uuid})
        
        for task in tasks_result:
            task_type, task_status, started, completed, error = task
            duration = ""
            if started and completed:
                duration = f" ({(completed - started).total_seconds():.2f}s)"
            print(f"  {task_type}: {task_status}{duration}")
            if error:
                print(f"    Error: {error[:100]}...")
        
        # Check database records
        print("\nDatabase Records:")
        
        # Chunks
        chunks_count = session.execute(text(
            "SELECT COUNT(*) FROM document_chunks WHERE document_uuid = :uuid"
        ), {'uuid': doc_uuid}).scalar()
        print(f"  Chunks: {chunks_count}")
        
        # Entity mentions
        mentions_count = session.execute(text(
            "SELECT COUNT(*) FROM entity_mentions WHERE document_uuid = :uuid"
        ), {'uuid': doc_uuid}).scalar()
        print(f"  Entity Mentions: {mentions_count}")
        
        # Canonical entities (through mentions)
        canonical_count = session.execute(text("""
            SELECT COUNT(DISTINCT canonical_entity_uuid) 
            FROM entity_mentions 
            WHERE document_uuid = :uuid AND canonical_entity_uuid IS NOT NULL
        """), {'uuid': doc_uuid}).scalar()
        print(f"  Canonical Entities: {canonical_count}")
        
        # Relationships
        rel_count = session.execute(text("""
            SELECT COUNT(*) FROM relationship_staging rs
            WHERE rs.source_entity_uuid IN (
                SELECT DISTINCT canonical_entity_uuid 
                FROM entity_mentions 
                WHERE document_uuid = :uuid
            )
        """), {'uuid': doc_uuid}).scalar()
        print(f"  Relationships: {rel_count}")
        
        # Check Redis cache
        if redis.is_available():
            print("\nRedis Cache:")
            cache_checks = [
                ('OCR Result', CacheKeys.DOC_OCR_RESULT),
                ('Chunks', CacheKeys.DOC_CHUNKS),
                ('All Mentions', CacheKeys.DOC_ALL_EXTRACTED_MENTIONS),
                ('Canonical Entities', CacheKeys.DOC_CANONICAL_ENTITIES),
                ('Resolved Mentions', CacheKeys.DOC_RESOLVED_MENTIONS),
                ('State', CacheKeys.DOC_STATE),
            ]
            
            for name, key_template in cache_checks:
                key = CacheKeys.format_key(key_template, document_uuid=doc_uuid)
                exists = redis.exists(key)
                print(f"  {name}: {'✓ Cached' if exists else '✗ Not cached'}")
        
    finally:
        session.close()

if __name__ == "__main__":
    main()