#!/usr/bin/env python3
"""
Check if Textract job ID is being persisted to database
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.db import DatabaseManager
from sqlalchemy import text

def check_job_persistence(document_uuid: str):
    """Check document for job ID persistence"""
    db = DatabaseManager(validate_conformance=False)
    session = next(db.get_session())
    
    try:
        result = session.execute(
            text("""
                SELECT 
                    document_uuid,
                    textract_job_id,
                    textract_job_status,
                    celery_status,
                    ocr_provider,
                    updated_at
                FROM source_documents
                WHERE document_uuid = :uuid
            """),
            {"uuid": document_uuid}
        ).first()
        
        if result:
            print(f"Document UUID: {result[0]}")
            print(f"Textract Job ID: {result[1]}")
            print(f"Textract Status: {result[2]}")
            print(f"Celery Status: {result[3]}")
            print(f"OCR Provider: {result[4]}")
            print(f"Last Updated: {result[5]}")
            
            # Check Redis for task state
            from scripts.cache import get_redis_manager
            redis = get_redis_manager()
            
            state_key = f"doc:state:{document_uuid}"
            doc_state = redis.get_dict(state_key)
            
            if doc_state:
                print("\nRedis State:")
                print(f"OCR State: {doc_state.get('ocr', {})}")
        else:
            print(f"Document {document_uuid} not found")
            
    finally:
        session.close()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        doc_uuid = sys.argv[1]
    else:
        doc_uuid = "fe41794e-f2eb-4d00-b277-961c9c9530d0"
    
    check_job_persistence(doc_uuid)