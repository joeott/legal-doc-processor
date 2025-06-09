#!/usr/bin/env python3
"""
Monitor batch processing status
"""

import sys
import json
import time
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from scripts.cache import get_redis_manager
from scripts.db import DatabaseManager

# Load batch submission data
with open("batch_submission_20250606_210142.json", "r") as f:
    batch_data = json.load(f)

redis_manager = get_redis_manager()
db_manager = DatabaseManager()

def check_document_status(doc_uuid: str, filename: str):
    """Check status of a single document"""
    print(f"\n{'='*60}")
    print(f"Document: {filename}")
    print(f"UUID: {doc_uuid}")
    print(f"{'='*60}")
    
    # Check Redis state
    state = redis_manager.get_dict(f"doc:state:{doc_uuid}")
    if state:
        print(f"\nRedis State:")
        print(f"  Status: {state.get('status', 'unknown')}")
        print(f"  Current Stage: {state.get('current_stage', 'unknown')}")
        
        stages = state.get('stages', {})
        if stages:
            print(f"\nStage Progress:")
            for stage_name, stage_info in stages.items():
                status = stage_info.get('status', 'unknown')
                timestamp = stage_info.get('timestamp', 'N/A')
                print(f"  {stage_name}: {status} (at {timestamp})")
                
                # Show result details if available
                result = stage_info.get('result', {})
                if result:
                    if stage_name == 'ocr':
                        print(f"    - Text length: {result.get('text_length', 0)}")
                        print(f"    - Confidence: {result.get('confidence', 0)}%")
                    elif stage_name == 'chunking':
                        print(f"    - Chunks created: {result.get('chunks', 0)}")
                    elif stage_name == 'entity_extraction':
                        print(f"    - Entities found: {result.get('entities', 0)}")
                        print(f"    - Chunks processed: {result.get('chunks_processed', 0)}")
                    elif stage_name == 'entity_resolution':
                        print(f"    - Canonical entities: {result.get('canonical_entities', 0)}")
                        print(f"    - Resolved entities: {result.get('resolved_entities', 0)}")
    else:
        print("  No Redis state found")
    
    # Check database
    print(f"\nDatabase Check:")
    
    # Check source document
    from sqlalchemy import text
    from scripts.config import DBSessionLocal
    session = DBSessionLocal()
    try:
        result = session.execute(
            text("SELECT status, raw_extracted_text IS NOT NULL as has_ocr, LENGTH(raw_extracted_text) as text_length FROM source_documents WHERE document_uuid = :uuid"),
            {"uuid": doc_uuid}
        )
        row = result.fetchone()
        if row:
            print(f"  Document status: {row[0]}")
            print(f"  Has OCR text: {row[1]}")
            if row[2]:
                print(f"  OCR text length: {row[2]:,} characters")
        
        # Check chunks
        result = session.execute(
            text("SELECT COUNT(*) FROM document_chunks WHERE document_uuid = :uuid"),
            {"uuid": doc_uuid}
        )
        chunk_count = result.scalar()
        print(f"  Chunks in DB: {chunk_count}")
        
        # Check entity mentions
        result = session.execute(
            text("SELECT COUNT(*), COUNT(DISTINCT entity_type) FROM entity_mentions WHERE document_uuid = :uuid"),
            {"uuid": doc_uuid}
        )
        row = result.fetchone()
        if row:
            print(f"  Entity mentions in DB: {row[0]}")
            print(f"  Distinct entity types: {row[1]}")
            
            # Get sample entities
            result = session.execute(
                text("""SELECT entity_text, entity_type, confidence_score 
                   FROM entity_mentions 
                   WHERE document_uuid = :uuid 
                   ORDER BY confidence_score DESC 
                   LIMIT 5"""),
                {"uuid": doc_uuid}
            )
            entities = result.fetchall()
            if entities:
                print(f"\n  Sample entities:")
                for entity in entities:
                    print(f"    - {entity[0]} ({entity[1]}) - confidence: {entity[2]:.2f}")
        
        # Check canonical entities
        result = session.execute(
            text("SELECT COUNT(*) FROM canonical_entities WHERE document_uuid = :uuid"),
            {"uuid": doc_uuid}
        )
        canonical_count = result.scalar()
        print(f"  Canonical entities in DB: {canonical_count}")
    finally:
        session.close()

def main():
    """Main monitoring function"""
    print(f"\n{'='*80}")
    print(f"BATCH PROCESSING MONITOR - {datetime.now()}")
    print(f"Batch ID: {batch_data['batch_id']}")
    print(f"Documents: {len(batch_data['documents'])}")
    print(f"{'='*80}")
    
    # Check each document
    for doc in batch_data['documents']:
        check_document_status(doc['document_uuid'], doc['filename'])
    
    print(f"\n{'='*80}")
    print("Monitor complete")

if __name__ == "__main__":
    main()