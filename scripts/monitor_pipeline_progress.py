#!/usr/bin/env python3
"""Monitor pipeline progress for a document"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

import time
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

from scripts.rds_utils import execute_query
from scripts.cache import get_redis_manager, CacheKeys

DOCUMENT_UUID = "0697af52-8bc6-4299-90ec-5d67b7eeb858"

def check_document_progress():
    """Check detailed progress of document processing"""
    
    # Document status
    doc = execute_query(
        """SELECT 
            original_file_name, status, celery_status, error_message,
            ocr_completed_at, processing_completed_at,
            (SELECT COUNT(*) FROM document_chunks WHERE document_uuid = sd.document_uuid) as chunk_count,
            (SELECT COUNT(*) FROM entity_mentions WHERE document_uuid = sd.document_uuid) as entity_count
        FROM source_documents sd
        WHERE document_uuid = :doc_id""",
        {"doc_id": DOCUMENT_UUID}
    )[0]
    
    print(f"\n{'='*60}")
    print(f"Document: {doc['original_file_name']}")
    print(f"Status: {doc['status']} | Celery: {doc['celery_status']}")
    if doc['error_message']:
        print(f"Error: {doc['error_message']}")
    print(f"Chunks: {doc['chunk_count']} | Entities: {doc['entity_count']}")
    
    # Check cache status
    redis_manager = get_redis_manager()
    cache_keys = [
        CacheKeys.DOC_OCR_RESULT.format(document_uuid=DOCUMENT_UUID),
        CacheKeys.DOC_CHUNKS.format(document_uuid=DOCUMENT_UUID),
        CacheKeys.DOC_CANONICAL_ENTITIES.format(document_uuid=DOCUMENT_UUID),
        CacheKeys.DOC_STATE.format(document_uuid=DOCUMENT_UUID),
    ]
    
    print("\nCache Status:")
    for key in cache_keys:
        exists = redis_manager.get_client().exists(key)
        print(f"  {key.split(':')[-1]}: {'✓' if exists else '✗'}")
    
    # Check processing tasks
    tasks = execute_query(
        """SELECT task_type as task_name, status as task_status, error_message, created_at
        FROM processing_tasks
        WHERE document_id = :doc_id
        ORDER BY created_at DESC
        LIMIT 10""",
        {"doc_id": DOCUMENT_UUID}
    )
    
    if tasks:
        print("\nRecent Tasks:")
        for task in tasks:
            status_icon = '✓' if task['task_status'] == 'completed' else '✗' if task['task_status'] == 'failed' else '⋯'
            print(f"  {status_icon} {task['task_name']}: {task['task_status']}")
            if task['error_message']:
                print(f"     Error: {task['error_message'][:50]}...")
    
    return doc['status'], doc['celery_status']

def main():
    """Monitor document processing progress"""
    logger.info(f"Monitoring document {DOCUMENT_UUID}")
    
    last_status = None
    last_celery = None
    iterations = 0
    
    while iterations < 60:  # Max 5 minutes
        status, celery_status = check_document_progress()
        
        if (status, celery_status) != (last_status, last_celery):
            logger.info(f"Status changed: {last_status}/{last_celery} → {status}/{celery_status}")
            last_status = status
            last_celery = celery_status
        
        if status == 'completed' or celery_status == 'completed':
            logger.info("✅ Processing completed!")
            break
        elif status == 'failed' or celery_status == 'failed':
            logger.error("❌ Processing failed!")
            break
        
        time.sleep(5)
        iterations += 1
    
    # Final summary
    print(f"\n{'='*60}")
    print("Final Summary:")
    check_document_progress()

if __name__ == "__main__":
    main()