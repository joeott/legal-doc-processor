#!/usr/bin/env python3
"""Check status of specific documents"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.db import DatabaseManager
from scripts.cache import get_redis_manager, CacheKeys
from sqlalchemy import text as sql_text

def check_document_status(doc_uuid):
    """Check comprehensive status of a document"""
    db = DatabaseManager()
    redis = get_redis_manager()
    session = next(db.get_session())
    
    try:
        # Get document info
        query = sql_text("""
            SELECT file_name, status, ocr_completed_at, processing_completed_at,
                   textract_job_id, textract_job_status
            FROM source_documents
            WHERE document_uuid = :uuid
        """)
        
        doc = session.execute(query, {'uuid': doc_uuid}).fetchone()
        
        if not doc:
            print(f"Document {doc_uuid} not found")
            return
        
        print(f"\n{'='*60}")
        print(f"Document: {doc.file_name}")
        print(f"UUID: {doc_uuid}")
        print(f"{'='*60}")
        
        # Database status
        print(f"Database Status: {doc.status}")
        print(f"OCR Completed: {'Yes' if doc.ocr_completed_at else 'No'}")
        print(f"Processing Completed: {'Yes' if doc.processing_completed_at else 'No'}")
        
        if doc.textract_job_id:
            print(f"Textract Job: {doc.textract_job_id[:20]}... ({doc.textract_job_status})")
        
        # Check Redis state
        state_key = CacheKeys.DOC_STATE.format(document_uuid=doc_uuid)
        doc_state = redis.get_dict(state_key) or {}
        
        print("\nPipeline Stages:")
        for stage in ['ocr', 'chunking', 'entity_extraction', 'entity_resolution', 'relationships', 'pipeline']:
            stage_info = doc_state.get(stage, {})
            status = stage_info.get('status', 'not_started')
            metadata = stage_info.get('metadata', {})
            
            print(f"  {stage}: {status}", end='')
            
            # Add relevant metadata
            if stage == 'chunking' and 'chunk_count' in metadata:
                print(f" ({metadata['chunk_count']} chunks)", end='')
            elif stage == 'entity_extraction' and 'mention_count' in metadata:
                print(f" ({metadata['mention_count']} mentions)", end='')
            elif stage == 'entity_resolution' and 'canonical_count' in metadata:
                print(f" ({metadata['canonical_count']} canonical)", end='')
            elif stage == 'relationships' and 'relationship_count' in metadata:
                print(f" ({metadata['relationship_count']} relationships)", end='')
            
            print()
        
        # Check counts in database
        chunks = session.execute(sql_text(
            "SELECT COUNT(*) FROM document_chunks WHERE document_uuid = :uuid"
        ), {'uuid': doc_uuid}).scalar()
        
        mentions = session.execute(sql_text(
            "SELECT COUNT(*) FROM entity_mentions WHERE document_uuid = :uuid"
        ), {'uuid': doc_uuid}).scalar()
        
        resolved = session.execute(sql_text(
            "SELECT COUNT(*) FROM entity_mentions WHERE document_uuid = :uuid AND canonical_entity_uuid IS NOT NULL"
        ), {'uuid': doc_uuid}).scalar()
        
        print(f"\nDatabase Counts:")
        print(f"  Chunks: {chunks}")
        print(f"  Entity Mentions: {mentions}")
        print(f"  Resolved Mentions: {resolved}")
        
    finally:
        session.close()

def main():
    """Check status of the 3 submitted documents"""
    doc_uuids = [
        '519fd8c1-40fc-4671-b20b-12a3bb919634',
        'b1588104-009f-44b7-9931-79b866d5ed79',
        '849531b3-89e0-4187-9dd2-ea8779b4f069'
    ]
    
    for doc_uuid in doc_uuids:
        check_document_status(doc_uuid)

if __name__ == "__main__":
    main()