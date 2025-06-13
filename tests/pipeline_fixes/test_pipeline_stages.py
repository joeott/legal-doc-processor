#!/usr/bin/env python3
"""
Test pipeline stages 5-6 with an existing document
"""

import time
from datetime import datetime
from scripts.pdf_tasks import resolve_document_entities
from scripts.db import DatabaseManager
from sqlalchemy import text

# Test with a known document that has entity mentions
document_uuid = "ad63957e-8a09-4cf3-a423-ac1f4e784fc3"

print(f"Testing pipeline stages for document: {document_uuid}")

# Get entity mentions for this document
db_manager = DatabaseManager(validate_conformance=False)
with next(db_manager.get_session()) as session:
    # Get entity mentions
    result = session.execute(text("""
        SELECT COUNT(*) as mention_count 
        FROM entity_mentions 
        WHERE document_uuid = :doc_id
    """), {'doc_id': document_uuid})
    
    mention_count = result.scalar()
    print(f"Found {mention_count} entity mentions")
    
    if mention_count > 0:
        # Get entity mentions
        mentions_result = session.execute(text("""
            SELECT mention_uuid, entity_text, entity_type
            FROM entity_mentions
            WHERE document_uuid = :doc_id
            LIMIT 5
        """), {'doc_id': document_uuid})
        
        mentions = []
        for row in mentions_result:
            mentions.append({
                'mention_uuid': str(row.mention_uuid),
                'entity_text': row.entity_text,
                'entity_type': row.entity_type
            })
            print(f"  - {row.entity_text} ({row.entity_type})")
        
        # Manually trigger entity resolution
        print("\nManually triggering entity resolution...")
        
        # Get all mentions for resolution
        all_mentions_result = session.execute(text("""
            SELECT em.*, c."text" as chunk_text
            FROM entity_mentions em
            JOIN document_chunks c ON em.chunk_uuid = c.chunk_uuid
            WHERE em.document_uuid = :doc_id
        """), {'doc_id': document_uuid})
        
        entity_mentions = []
        for row in all_mentions_result:
            entity_mentions.append({
                'mention_uuid': str(row.mention_uuid),
                'chunk_uuid': str(row.chunk_uuid),
                'document_uuid': str(row.document_uuid),
                'entity_text': row.entity_text,
                'entity_type': row.entity_type,
                'start_char': row.start_char,
                'end_char': row.end_char,
                'confidence_score': row.confidence_score,
                'extraction_method': row.extraction_method,
                'chunk_text': row.chunk_text
            })
        
        print(f"Calling resolve_document_entities with {len(entity_mentions)} mentions...")
        
        # Call the task directly
        task = resolve_document_entities.apply_async(
            args=[document_uuid, entity_mentions]
        )
        
        print(f"Task ID: {task.id}")
        print("Waiting for completion...")
        
        # Wait for task
        for i in range(30):
            if task.ready():
                print(f"\nTask completed with status: {task.status}")
                if task.successful():
                    result = task.result
                    print(f"Result: {result}")
                else:
                    print(f"Error: {task.info}")
                break
            time.sleep(2)
            print(".", end="", flush=True)
        
        # Check if relationship building was triggered
        print("\n\nChecking for relationship building task...")
        rel_result = session.execute(text("""
            SELECT task_type, status, error_message, created_at
            FROM processing_tasks
            WHERE document_id = :doc_id
            AND task_type IN ('relationship_building', 'finalization')
            AND created_at > NOW() - INTERVAL '5 minutes'
            ORDER BY created_at DESC
        """), {'doc_id': document_uuid})
        
        for row in rel_result:
            print(f"\n{row.task_type}: {row.status}")
            if row.error_message:
                print(f"  Error: {row.error_message}")
            print(f"  Created: {row.created_at}")
    else:
        print("No entity mentions found for this document")