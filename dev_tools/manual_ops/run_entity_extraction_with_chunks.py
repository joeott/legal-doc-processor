#!/usr/bin/env python3
"""Run entity extraction with chunks from database"""

import os
import sys
import logging

# Add the parent directory to the Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.pdf_tasks import extract_entities_from_chunks
from scripts.db import DatabaseManager
from sqlalchemy import text as sql_text

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def main():
    document_uuid = "4909739b-8f12-40cd-8403-04b8b1a79281"
    
    logger.info(f"Running entity extraction with chunks for {document_uuid}")
    
    # Get chunks from database
    db = DatabaseManager()
    session = next(db.get_session())
    try:
        result = session.execute(
            sql_text("SELECT chunk_uuid, text, chunk_number FROM document_chunks WHERE document_uuid = :doc_uuid ORDER BY chunk_number"),
            {"doc_uuid": document_uuid}
        )
        rows = result.fetchall()
        
        chunks = []
        for chunk_uuid, text, chunk_number in rows:
            chunks.append({
                'chunk_uuid': str(chunk_uuid),
                'chunk_text': text,  # Changed from 'text' to 'chunk_text'
                'chunk_number': chunk_number
            })
        
        logger.info(f"Found {len(chunks)} chunks in database")
    finally:
        session.close()
    
    if not chunks:
        logger.error("No chunks found!")
        return
    
    # Trigger entity extraction
    result = extract_entities_from_chunks.delay(document_uuid, chunks)
    
    logger.info(f"Entity extraction task submitted: {result.id}")
    logger.info(f"Waiting for result...")
    
    # Wait for completion (max 60 seconds)
    try:
        task_result = result.get(timeout=60)
        logger.info(f"Task completed successfully!")
        logger.info(f"Extracted {len(task_result.get('entity_mentions', []))} entities")
        
        # Check database
        db = DatabaseManager()
        session = next(db.get_session())
        try:
            count_result = session.execute(
                sql_text("SELECT COUNT(*) FROM entity_mentions WHERE document_uuid = :doc_uuid"),
                {"doc_uuid": document_uuid}
            )
            count = count_result.scalar()
            logger.info(f"Entity mentions in database: {count}")
        finally:
            session.close()
            
    except Exception as e:
        logger.error(f"Task failed: {e}")
        logger.error(f"Task state: {result.state}")
        if hasattr(result, 'info'):
            logger.error(f"Task info: {result.info}")

if __name__ == "__main__":
    main()