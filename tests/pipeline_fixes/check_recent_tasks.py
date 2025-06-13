#!/usr/bin/env python3
"""Check recent processing tasks"""

from scripts.db import DatabaseManager
from sqlalchemy import text

db_manager = DatabaseManager(validate_conformance=False)
with next(db_manager.get_session()) as session:
    # Check recent tasks
    result = session.execute(text("""
        SELECT task_type, status, error_message, created_at
        FROM processing_tasks
        WHERE created_at > NOW() - INTERVAL '30 minutes'
        ORDER BY created_at DESC
        LIMIT 20
    """))
    
    print("Recent processing tasks:")
    print("-" * 100)
    print(f"{'Created At':25} | {'Task Type':20} | {'Status':10} | {'Error'}")
    print("-" * 100)
    
    for row in result:
        error = (row.error_message[:50] + '...') if row.error_message and len(row.error_message) > 50 else (row.error_message or '')
        print(f"{str(row.created_at)[:25]} | {row.task_type:20} | {row.status:10} | {error}")
    
    # Check specifically for relationship_building tasks
    print("\n\nRelationship building tasks in last hour:")
    rel_result = session.execute(text("""
        SELECT document_id, status, error_message, created_at
        FROM processing_tasks
        WHERE task_type = 'relationship_building'
        AND created_at > NOW() - INTERVAL '1 hour'
        ORDER BY created_at DESC
    """))
    
    count = 0
    for row in rel_result:
        count += 1
        print(f"\nDocument: {row.document_id}")
        print(f"Status: {row.status}")
        print(f"Created: {row.created_at}")
        if row.error_message:
            print(f"Error: {row.error_message}")
    
    if count == 0:
        print("No relationship_building tasks found in the last hour")
    else:
        print(f"\nTotal: {count} relationship_building tasks")