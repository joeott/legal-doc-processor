#!/usr/bin/env python3
"""
Test end-to-end processing of a single document
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

import logging
import uuid
from datetime import datetime
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Import Celery app and tasks
from scripts.celery_app import app
from scripts.pdf_tasks import process_pdf_document

# Import database and utilities
from scripts.db import DatabaseManager
from scripts.cache import get_redis_manager
from scripts.s3_storage import S3StorageManager

def find_test_document():
    """Find a suitable test document in the database"""
    db_manager = DatabaseManager()
    
    # Look for a PDF document that's ready for processing
    query = """
        SELECT document_uuid, original_file_name, s3_key, processing_status
        FROM source_documents
        WHERE detected_file_type = 'pdf'
        AND s3_key IS NOT NULL
        ORDER BY created_at DESC
        LIMIT 5
    """
    
    results = db_manager.execute_query(query)
    
    if results:
        logger.info(f"Found {len(results)} PDF documents:")
        for doc in results:
            logger.info(f"  - {doc['document_uuid']}: {doc['original_file_name']} (status: {doc['processing_status']})")
        
        # Return the first one
        return results[0]['document_uuid']
    
    return None

def reset_document_status(document_uuid: str):
    """Reset document to pending status for reprocessing"""
    db_manager = DatabaseManager()
    
    logger.info(f"Resetting document {document_uuid} to pending status...")
    
    # Update document status
    db_manager.update_record(
        'source_documents',
        {
            'processing_status': 'pending',
            'celery_status': 'pending',
            'error_message': None,
            'processing_started_at': None,
            'processing_completed_at': None
        },
        {'document_uuid': document_uuid}
    )
    
    # Clear any existing chunks
    db_manager.execute_query(
        "DELETE FROM document_chunks WHERE document_uuid = :document_uuid",
        {"document_uuid": document_uuid}
    )
    
    # Clear any existing entities
    db_manager.execute_query(
        "DELETE FROM entity_mentions WHERE document_uuid = :document_uuid",
        {"document_uuid": document_uuid}
    )
    
    # Clear cache
    redis_manager = get_redis_manager()
    redis_manager.clear_document_cache(document_uuid)
    
    logger.info("Document reset complete")

def submit_document_for_processing(document_uuid: str):
    """Submit document to Celery for processing"""
    logger.info(f"Submitting document {document_uuid} for processing...")
    
    try:
        # Call the task asynchronously
        result = process_pdf_document.delay(document_uuid)
        
        logger.info(f"Task submitted successfully!")
        logger.info(f"Task ID: {result.id}")
        logger.info(f"Task state: {result.state}")
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to submit task: {e}")
        import traceback
        traceback.print_exc()
        return None

def monitor_task_progress(task_result):
    """Monitor the progress of a Celery task"""
    import time
    
    logger.info("Monitoring task progress...")
    
    start_time = time.time()
    last_state = None
    
    while True:
        current_state = task_result.state
        
        if current_state != last_state:
            logger.info(f"Task state changed: {last_state} → {current_state}")
            
            if current_state == 'SUCCESS':
                logger.info("✅ Task completed successfully!")
                logger.info(f"Result: {task_result.result}")
                break
            elif current_state == 'FAILURE':
                logger.error("❌ Task failed!")
                logger.error(f"Error: {task_result.info}")
                break
            
            last_state = current_state
        
        # Check document status in database
        db_manager = DatabaseManager()
        doc_status = db_manager.select_records(
            'source_documents',
            {'document_uuid': task_result.args[0]},
            limit=1
        )
        
        if doc_status:
            doc = doc_status[0]
            logger.info(f"Document status: {doc['processing_status']} | Celery status: {doc['celery_status']}")
            
            # Check stage progress
            chunks = db_manager.execute_query(
                "SELECT COUNT(*) as count FROM document_chunks WHERE document_uuid = :doc_uuid",
                {"doc_uuid": task_result.args[0]}
            )
            entities = db_manager.execute_query(
                "SELECT COUNT(*) as count FROM entity_mentions WHERE document_uuid = :doc_uuid",
                {"doc_uuid": task_result.args[0]}
            )
            
            logger.info(f"  Chunks: {chunks[0]['count'] if chunks else 0}")
            logger.info(f"  Entities: {entities[0]['count'] if entities else 0}")
        
        # Timeout after 10 minutes
        if time.time() - start_time > 600:
            logger.warning("Task timeout - stopping monitoring")
            break
        
        time.sleep(5)  # Check every 5 seconds

def main():
    """Main test function"""
    logger.info("=== Starting End-to-End Document Processing Test ===")
    
    # 1. Find or specify a test document
    document_uuid = find_test_document()
    
    if not document_uuid:
        logger.error("No suitable test document found!")
        
        # Try to find any document
        db_manager = DatabaseManager()
        any_docs = db_manager.execute_query("SELECT document_uuid FROM source_documents LIMIT 1")
        if any_docs:
            document_uuid = any_docs[0]['document_uuid']
            logger.info(f"Using any available document: {document_uuid}")
        else:
            logger.error("No documents found in database!")
            return
    
    logger.info(f"Using document: {document_uuid}")
    
    # 2. Reset document status
    reset_document_status(document_uuid)
    
    # 3. Submit for processing
    task_result = submit_document_for_processing(document_uuid)
    
    if task_result:
        # 4. Monitor progress
        monitor_task_progress(task_result)
        
        # 5. Final status check
        db_manager = DatabaseManager()
        final_status = db_manager.select_records(
            'source_documents',
            {'document_uuid': document_uuid},
            limit=1
        )
        
        if final_status:
            doc = final_status[0]
            logger.info("\n=== Final Document Status ===")
            logger.info(f"Processing Status: {doc['processing_status']}")
            logger.info(f"Celery Status: {doc['celery_status']}")
            logger.info(f"Error Message: {doc.get('error_message', 'None')}")
            
            # Check what was produced
            chunks = db_manager.execute_query(
                "SELECT COUNT(*) as count FROM document_chunks WHERE document_uuid = :doc_uuid",
                {"doc_uuid": document_uuid}
            )
            entities = db_manager.execute_query(
                "SELECT COUNT(*) as count FROM entity_mentions WHERE document_uuid = :doc_uuid",
                {"doc_uuid": document_uuid}
            )
            canonicals = db_manager.execute_query(
                "SELECT COUNT(DISTINCT canonical_entity_uuid) as count FROM entity_mentions WHERE document_uuid = :doc_uuid",
                {"doc_uuid": document_uuid}
            )
            
            logger.info(f"\n=== Processing Results ===")
            logger.info(f"Chunks created: {chunks[0]['count'] if chunks else 0}")
            logger.info(f"Entity mentions: {entities[0]['count'] if entities else 0}")
            logger.info(f"Canonical entities: {canonicals[0]['count'] if canonicals else 0}")
    else:
        logger.error("Failed to submit task for processing!")

if __name__ == "__main__":
    main()