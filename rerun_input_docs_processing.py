#!/usr/bin/env python3
"""Re-run document processing for the 3 test documents after UUID fix"""

import os
import sys
sys.path.insert(0, '/opt/legal-doc-processor')

import time
from datetime import datetime
from scripts.db import DatabaseManager
from scripts.pdf_tasks import extract_text_from_document
from scripts.cache import get_redis_manager
from sqlalchemy import text
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_test_documents():
    """Get the 3 test documents from the previous run"""
    db = DatabaseManager(validate_conformance=False)
    session = next(db.get_session())
    
    try:
        # Find documents from today's test project
        query = text("""
            SELECT sd.document_uuid, sd.file_name, sd.s3_bucket, sd.s3_key, sd.status,
                   sd.celery_task_id, p.name as project_name
            FROM source_documents sd
            JOIN projects p ON sd.project_fk_id = p.id
            WHERE p.name LIKE 'PIPELINE_TEST_%'
            AND sd.created_at::date = CURRENT_DATE
            ORDER BY sd.created_at DESC
            LIMIT 3
        """)
        
        results = session.execute(query).fetchall()
        
        if not results:
            logger.error("No test documents found from today")
            return []
        
        documents = []
        for row in results:
            doc_info = {
                'document_uuid': str(row.document_uuid),
                'file_name': row.file_name,
                's3_bucket': row.s3_bucket,
                's3_key': row.s3_key,
                'status': row.status,
                'celery_task_id': row.celery_task_id,
                'project_name': row.project_name
            }
            documents.append(doc_info)
            logger.info(f"Found document: {doc_info['file_name']} (status: {doc_info['status']})")
        
        return documents
        
    finally:
        session.close()

def clear_document_state(document_uuid: str):
    """Clear Redis state for a document to allow fresh processing"""
    redis_mgr = get_redis_manager()
    
    # Clear all Redis keys for the document
    keys_to_clear = [
        f"doc:state:{document_uuid}",
        f"doc:ocr:{document_uuid}",
        f"doc:chunks:{document_uuid}",
        f"doc:entities:{document_uuid}",
        f"doc:processing:{document_uuid}",
        f"doc:metadata:{document_uuid}"
    ]
    
    for key in keys_to_clear:
        redis_mgr.delete(key)
    
    logger.info(f"Cleared Redis state for document {document_uuid}")

def reset_document_status(document_uuid: str):
    """Reset document status in database for reprocessing"""
    db = DatabaseManager(validate_conformance=False)
    session = next(db.get_session())
    
    try:
        update_query = text("""
            UPDATE source_documents 
            SET status = 'processing',
                celery_task_id = NULL,
                raw_extracted_text = NULL,
                ocr_completed_at = NULL,
                textract_job_id = NULL
            WHERE document_uuid = :doc_uuid
        """)
        
        session.execute(update_query, {'doc_uuid': document_uuid})
        session.commit()
        logger.info(f"Reset database status for document {document_uuid}")
        
    finally:
        session.close()

def resubmit_document(doc_info: dict):
    """Resubmit a document for processing"""
    document_uuid = doc_info['document_uuid']
    s3_url = f"s3://{doc_info['s3_bucket']}/{doc_info['s3_key']}"
    
    logger.info(f"Resubmitting document {document_uuid}: {doc_info['file_name']}")
    
    # Clear Redis state
    clear_document_state(document_uuid)
    
    # Reset database status
    reset_document_status(document_uuid)
    
    # Start OCR extraction which triggers the full pipeline
    result = extract_text_from_document.apply_async(
        args=[document_uuid, s3_url]
    )
    
    logger.info(f"Submitted task {result.id} for document {document_uuid}")
    
    # Update database with new task ID
    db = DatabaseManager(validate_conformance=False)
    session = next(db.get_session())
    try:
        update_query = text("""
            UPDATE source_documents 
            SET celery_task_id = :task_id,
                updated_at = NOW()
            WHERE document_uuid = :doc_uuid
        """)
        session.execute(update_query, {
            'task_id': result.id,
            'doc_uuid': document_uuid
        })
        session.commit()
    finally:
        session.close()
    
    return result.id

def main():
    """Main execution"""
    print("=" * 80)
    print("Re-running Document Processing After UUID Fix")
    print("=" * 80)
    
    # Get test documents
    documents = get_test_documents()
    
    if not documents:
        print("No test documents found!")
        return
    
    print(f"\nFound {len(documents)} test documents")
    
    # Resubmit each document
    task_ids = []
    for doc in documents:
        print(f"\nProcessing: {doc['file_name']}")
        print(f"  UUID: {doc['document_uuid']}")
        print(f"  Current status: {doc['status']}")
        
        task_id = resubmit_document(doc)
        task_ids.append({
            'document_uuid': doc['document_uuid'],
            'file_name': doc['file_name'],
            'task_id': task_id
        })
        
        # Brief pause between submissions
        time.sleep(1)
    
    print("\n" + "=" * 80)
    print("All documents resubmitted!")
    print("=" * 80)
    
    print("\nTask IDs:")
    for task_info in task_ids:
        print(f"  {task_info['file_name']}: {task_info['task_id']}")
    
    print("\nUse the monitoring script to track progress:")
    print("  python3 monitor_reprocessing.py")

if __name__ == "__main__":
    main()