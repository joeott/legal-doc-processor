#!/usr/bin/env python3
"""Test entity resolution directly with existing entity mentions"""

import os
import sys
import logging
import json

# Add the parent directory to the Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.cache import get_redis_manager
from scripts.db import DatabaseManager
from scripts.pdf_tasks import resolve_document_entities

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def main():
    document_uuid = "4909739b-8f12-40cd-8403-04b8b1a79281"
    
    logger.info(f"Testing entity resolution directly for document {document_uuid}")
    
    # Get entity mentions from database
    db = DatabaseManager()
    session = next(db.get_session())
    try:
        from sqlalchemy import text
        result = session.execute(
            text("SELECT mention_uuid, entity_text, entity_type, chunk_uuid FROM entity_mentions WHERE document_uuid = :doc_uuid"),
            {"doc_uuid": document_uuid}
        )
        rows = result.fetchall()
        
        # Convert to dicts with both 'text' and 'entity_text' for compatibility
        entity_mentions = []
        for row in rows:
            entity_mentions.append({
                'mention_uuid': str(row[0]),
                'entity_text': row[1],
                'text': row[1],  # Add 'text' key for compatibility
                'entity_type': row[2],
                'type': row[2],  # Add 'type' key for compatibility
                'chunk_uuid': str(row[3]),
                'attributes': {
                    'mention_uuid': str(row[0]),
                    'chunk_uuid': str(row[3]),
                    'document_uuid': document_uuid
                }
            })
        
        logger.info(f"Found {len(entity_mentions)} entity mentions in database")
        
        if not entity_mentions:
            logger.error("No entity mentions found!")
            return
        
        # Log a sample of the mentions
        logger.info("Sample mentions:")
        for i, mention in enumerate(entity_mentions[:5]):
            logger.info(f"  {i+1}. {mention['entity_text']} ({mention['entity_type']})")
    finally:
        session.close()
    
    # Trigger the resolution task with entity mentions
    result = resolve_document_entities.delay(document_uuid, entity_mentions)
    
    logger.info(f"Task submitted: {result.id}")
    logger.info(f"Waiting for result...")
    
    # Wait for completion (max 30 seconds)
    try:
        task_result = result.get(timeout=30)
        logger.info(f"Task completed successfully!")
        logger.info(f"Result: {json.dumps(task_result, indent=2)}")
    except Exception as e:
        logger.error(f"Task failed: {e}")
        logger.error(f"Task state: {result.state}")
        if hasattr(result, 'info'):
            logger.error(f"Task info: {result.info}")

if __name__ == "__main__":
    main()