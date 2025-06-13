#!/usr/bin/env python3
"""Check pipeline stages for a document"""

from scripts.db import DatabaseManager
from sqlalchemy import text

document_uuid = "ad63957e-8a09-4cf3-a423-ac1f4e784fc3"

db_manager = DatabaseManager(validate_conformance=False)
with next(db_manager.get_session()) as session:
    # Check all processing tasks for this document
    result = session.execute(text("""
        SELECT task_type, status, error_message, created_at
        FROM processing_tasks
        WHERE document_id = :doc_id
        ORDER BY created_at DESC
    """), {'doc_id': document_uuid})
    
    print(f"Processing tasks for document {document_uuid}:")
    print("-" * 80)
    
    for row in result:
        print(f"{row.created_at} | {row.task_type:20} | {row.status:10}")
        if row.error_message:
            print(f"  Error: {row.error_message[:100]}...")
    
    # Check specifically for recent relationship_building and finalization
    print("\n\nRecent stage 5-6 tasks (last hour):")
    print("-" * 80)
    
    recent_result = session.execute(text("""
        SELECT task_type, status, error_message, created_at
        FROM processing_tasks
        WHERE document_id = :doc_id
        AND task_type IN ('relationship_building', 'finalization')
        AND created_at > NOW() - INTERVAL '1 hour'
        ORDER BY created_at DESC
    """), {'doc_id': document_uuid})
    
    found_recent = False
    for row in recent_result:
        found_recent = True
        print(f"{row.created_at} | {row.task_type:20} | {row.status:10}")
        if row.error_message:
            print(f"  Error: {row.error_message}")
    
    if not found_recent:
        print("No recent relationship_building or finalization tasks found.")
        
    # Check canonical entities
    print("\n\nCanonical entities:")
    canon_result = session.execute(text("""
        SELECT COUNT(*) as count
        FROM canonical_entities
        WHERE canonical_entity_uuid IN (
            SELECT canonical_entity_uuid
            FROM entity_mentions
            WHERE document_uuid = :doc_id
        )
    """), {'doc_id': document_uuid})
    
    count = canon_result.scalar()
    print(f"Found {count} canonical entities for this document")