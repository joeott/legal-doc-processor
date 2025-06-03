#!/usr/bin/env python3
"""
Check document processing status.
"""

import sys
from pathlib import Path

# Setup Python path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.rds_utils import execute_query
from scripts.cache import get_redis_manager
import json

def check_document_status(doc_uuid: str):
    """Check the status of a document in the pipeline."""
    
    print(f"\n🔍 Checking status for document: {doc_uuid}\n")
    
    # Check database
    doc_result = execute_query(
        "SELECT * FROM source_documents WHERE document_uuid = :uuid",
        {"uuid": doc_uuid}
    )
    
    if not doc_result:
        print("❌ Document not found in database")
        return
    
    doc = doc_result[0]
    print("📄 Document Information:")
    print(f"  - File: {doc['original_filename']}")
    print(f"  - Status: {doc['processing_status']}")
    print(f"  - Celery Status: {doc['celery_status']}")
    print(f"  - S3 Location: s3://{doc['s3_bucket']}/{doc['s3_key']}")
    
    if doc.get('error_message'):
        print(f"  - Error: {doc['error_message']}")
    
    # Check chunks
    chunks_result = execute_query(
        "SELECT COUNT(*) as count FROM document_chunks WHERE document_uuid = :uuid",
        {"uuid": doc_uuid}
    )
    chunk_count = chunks_result[0]['count'] if chunks_result else 0
    print(f"\n📑 Chunks: {chunk_count}")
    
    # Check entities
    entities_result = execute_query(
        "SELECT COUNT(*) as count, entity_type FROM entity_mentions WHERE document_uuid = :uuid GROUP BY entity_type",
        {"uuid": doc_uuid}
    )
    
    if entities_result:
        print("\n👥 Entities:")
        for row in entities_result:
            print(f"  - {row['entity_type']}: {row['count']}")
    else:
        print("\n👥 Entities: None found")
    
    # Check Redis cache
    try:
        redis = get_redis_manager()
        
        # Check OCR result
        ocr_key = f"doc:{doc_uuid}:ocr_result"
        ocr_cached = redis.exists(ocr_key)
        print(f"\n💾 Cache Status:")
        print(f"  - OCR Result: {'✅ Cached' if ocr_cached else '❌ Not cached'}")
        
        # Check chunks cache
        chunks_key = f"doc:{doc_uuid}:chunks"
        chunks_cached = redis.exists(chunks_key)
        print(f"  - Chunks: {'✅ Cached' if chunks_cached else '❌ Not cached'}")
        
    except Exception as e:
        print(f"\n⚠️  Redis error: {e}")
    
    # Check processing history (if table exists)
    try:
        history_result = execute_query(
            """
            SELECT stage, status, started_at, completed_at, error_message 
            FROM document_processing_history 
            WHERE document_uuid = :uuid 
            ORDER BY started_at DESC
            """,
            {"uuid": doc_uuid}
        )
        
        if history_result:
            print("\n📊 Processing History:")
            for entry in history_result:
                status_emoji = "✅" if entry['status'] == 'completed' else "❌" if entry['status'] == 'failed' else "⏳"
                print(f"  {status_emoji} {entry['stage']}: {entry['status']}")
                if entry.get('error_message'):
                    print(f"     Error: {entry['error_message']}")
    except Exception as e:
        # Table might not exist
        pass

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python check_document_status.py <document_uuid>")
        sys.exit(1)
    
    doc_uuid = sys.argv[1]
    check_document_status(doc_uuid)