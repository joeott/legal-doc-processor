#!/usr/bin/env python3
"""
Comprehensive document monitoring with correct schema
"""
import sys
import os
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.db import get_db
from scripts.logging_config import get_logger
from sqlalchemy import text

logger = get_logger(__name__)

def monitor_document(doc_uuid):
    """Monitor document with proper column names"""
    session = next(get_db())
    try:
        # Main document status
        doc_query = """
        SELECT 
            sd.document_uuid,
            sd.file_name,
            sd.status,
            sd.textract_job_status,
            sd.textract_job_id,
            sd.created_at,
            sd.s3_key,
            sd.s3_bucket
        FROM source_documents sd
        WHERE sd.document_uuid = :uuid
        """
        
        doc = session.execute(text(doc_query), {"uuid": doc_uuid}).fetchone()
        
        if not doc:
            print(f"Document {doc_uuid} not found!")
            return
            
        print(f"\nDocument: {doc.file_name}")
        print(f"UUID: {doc.document_uuid}")
        print(f"Status: {doc.status}")
        print(f"Created: {doc.created_at}")
        print(f"Textract: {doc.textract_job_status or 'Not started'} (Job: {doc.textract_job_id or 'None'})")
        if doc.s3_key:
            print(f"S3: s3://{doc.s3_bucket}/{doc.s3_key}")
        
        # Pipeline stages - using correct column names and joins
        stages_query = """
        SELECT 
            (SELECT COUNT(*) FROM document_chunks WHERE document_uuid = :uuid) as chunks,
            (SELECT COUNT(*) FROM entity_mentions WHERE document_uuid = :uuid) as entities,
            (SELECT COUNT(DISTINCT canonical_entity_uuid) FROM entity_mentions WHERE document_uuid = :uuid AND canonical_entity_uuid IS NOT NULL) as canonical,
            (SELECT COUNT(*) FROM relationship_staging rs 
             WHERE rs.source_entity_uuid IN (SELECT canonical_entity_uuid FROM entity_mentions WHERE document_uuid = :uuid)
                OR rs.target_entity_uuid IN (SELECT canonical_entity_uuid FROM entity_mentions WHERE document_uuid = :uuid)) as relationships
        """
        
        stages = session.execute(text(stages_query), {"uuid": doc_uuid}).fetchone()
        
        print(f"\nPipeline Progress:")
        print(f"  1. Document Created: ✓")
        print(f"  2. OCR: {'✓' if doc.textract_job_status == 'SUCCEEDED' else '○ pending'}")
        print(f"  3. Chunks: {'✓' if stages.chunks > 0 else '○'} ({stages.chunks})")
        print(f"  4. Entities: {'✓' if stages.entities > 0 else '○'} ({stages.entities})")
        print(f"  5. Canonical: {'✓' if stages.canonical > 0 else '○'} ({stages.canonical})")
        print(f"  6. Relationships: {'✓' if stages.relationships > 0 else '○'} ({stages.relationships})")
        
        completed_stages = sum([
            1,  # Document created
            1 if doc.textract_job_status == 'SUCCEEDED' else 0,
            1 if stages.chunks > 0 else 0,
            1 if stages.entities > 0 else 0,
            1 if stages.canonical > 0 else 0,
            1 if stages.relationships > 0 else 0
        ])
        
        print(f"\nSummary: {completed_stages}/6 stages completed")
        
        # Check for errors
        errors_query = """
        SELECT task_type, status, error_message, created_at
        FROM processing_tasks
        WHERE document_id = :uuid AND status = 'failed'
        ORDER BY created_at DESC
        LIMIT 5
        """
        
        errors = session.execute(text(errors_query), {"uuid": doc_uuid}).fetchall()
        if errors:
            print(f"\n⚠️  Errors Found:")
            for err in errors:
                print(f"  - {err.task_type} ({err.created_at.strftime('%H:%M:%S')}): {err.error_message}")
                
        # Recent processing tasks
        tasks_query = """
        SELECT task_type, status, created_at, completed_at
        FROM processing_tasks
        WHERE document_id = :uuid
        ORDER BY created_at DESC
        LIMIT 10
        """
        
        tasks = session.execute(text(tasks_query), {"uuid": doc_uuid}).fetchall()
        if tasks:
            print(f"\nRecent Tasks:")
            for task in tasks:
                duration = ""
                if task.completed_at and task.created_at:
                    dur_sec = (task.completed_at - task.created_at).total_seconds()
                    duration = f" ({dur_sec:.1f}s)"
                print(f"  - {task.task_type}: {task.status}{duration}")
                
    except Exception as e:
        logger.error(f"Error monitoring document: {e}")
        print(f"Error: {e}")
    finally:
        session.close()

def main():
    """Main entry point"""
    if len(sys.argv) > 1:
        doc_uuid = sys.argv[1]
    else:
        # Try to get the most recent document
        session = next(get_db())
        try:
            result = session.execute(text("""
                SELECT document_uuid, file_name 
                FROM source_documents 
                ORDER BY created_at DESC 
                LIMIT 5
            """)).fetchall()
            
            if result:
                print("Recent documents:")
                for i, (uuid, name) in enumerate(result):
                    print(f"{i+1}. {uuid} - {name}")
                
                choice = input("\nEnter document number or UUID: ")
                if choice.isdigit() and 1 <= int(choice) <= len(result):
                    doc_uuid = result[int(choice)-1][0]
                else:
                    doc_uuid = choice
            else:
                doc_uuid = input("Enter document UUID: ")
        finally:
            session.close()
    
    monitor_document(doc_uuid)

if __name__ == "__main__":
    main()