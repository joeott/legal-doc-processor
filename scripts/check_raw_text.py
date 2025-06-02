#!/usr/bin/env python3
"""
Check if raw_extracted_text is stored in database
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.db import DatabaseManager
from sqlalchemy import text

def check_raw_text(document_uuid: str):
    """Check if raw text is stored in database"""
    db = DatabaseManager(validate_conformance=False)
    session = next(db.get_session())
    
    try:
        result = session.execute(
            text("""
                SELECT 
                    document_uuid,
                    raw_extracted_text IS NOT NULL as has_text,
                    LENGTH(raw_extracted_text) as text_length,
                    ocr_completed_at,
                    textract_job_status
                FROM source_documents
                WHERE document_uuid = :uuid
            """),
            {"uuid": document_uuid}
        ).first()
        
        if result:
            print(f"Document UUID: {result[0]}")
            print(f"Has Raw Text: {result[1]}")
            print(f"Text Length: {result[2] if result[2] else 0}")
            print(f"OCR Completed At: {result[3]}")
            print(f"Textract Status: {result[4]}")
            
            # Check Redis for cached text
            from scripts.cache import get_redis_manager, CacheKeys
            redis = get_redis_manager()
            
            cache_key = CacheKeys.DOC_OCR_RESULT.format(document_uuid=document_uuid)
            cached_result = redis.get_dict(cache_key)
            
            if cached_result:
                print("\nRedis Cache:")
                print(f"  Status: {cached_result.get('status')}")
                print(f"  Text Length: {len(cached_result.get('text', ''))}")
                print(f"  Cached At: {cached_result.get('cached_at')}")
                
        else:
            print(f"Document {document_uuid} not found")
            
    finally:
        session.close()

if __name__ == "__main__":
    doc_uuid = "5805f7b5-09ca-4f95-a990-da2dd758fd9e"
    check_raw_text(doc_uuid)