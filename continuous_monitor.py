#!/usr/bin/env python3
"""
Continuous monitoring of batch processing
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
from scripts.config import DBSessionLocal
from sqlalchemy import text

# Load batch submission data
with open("batch_submission_20250606_210841.json", "r") as f:
    batch_data = json.load(f)

redis_manager = get_redis_manager()

def check_processing_status():
    """Check processing status of all documents"""
    print(f"\n{'='*80}")
    print(f"Processing Status Check - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*80}")
    
    session = DBSessionLocal()
    all_complete = True
    
    try:
        for doc in batch_data['documents']:
            doc_uuid = doc['document_uuid']
            filename = doc['filename'][:50] + "..." if len(doc['filename']) > 50 else doc['filename']
            
            # Check Redis state
            state = redis_manager.get_dict(f"doc:state:{doc_uuid}")
            
            # Check database
            result = session.execute(
                text("""
                    SELECT 
                        sd.status,
                        sd.raw_extracted_text IS NOT NULL as has_ocr,
                        LENGTH(sd.raw_extracted_text) as text_length,
                        (SELECT COUNT(*) FROM document_chunks WHERE document_uuid = sd.document_uuid) as chunk_count,
                        (SELECT COUNT(*) FROM entity_mentions WHERE document_uuid = sd.document_uuid) as entity_count,
                        (SELECT COUNT(DISTINCT entity_type) FROM entity_mentions WHERE document_uuid = sd.document_uuid) as entity_types
                    FROM source_documents sd
                    WHERE sd.document_uuid = :uuid
                """),
                {"uuid": doc_uuid}
            )
            row = result.fetchone()
            
            print(f"\n{filename}")
            print(f"  UUID: {doc_uuid}")
            
            if state:
                status = state.get('status', 'unknown')
                current_stage = state.get('current_stage', 'unknown')
                stages = state.get('stages', {})
                completed = [s for s, info in stages.items() if info.get('status') == 'completed']
                
                print(f"  Pipeline Status: {status}")
                print(f"  Current Stage: {current_stage}")
                print(f"  Completed Stages: {', '.join(completed) if completed else 'none'}")
                
                # Check if entity extraction completed
                if 'entity_extraction' in stages:
                    ee_info = stages['entity_extraction']
                    if ee_info.get('status') == 'completed':
                        result = ee_info.get('result', {})
                        print(f"  Entity Extraction: {result.get('entities', 0)} entities found")
                
                if status != 'completed':
                    all_complete = False
            else:
                print(f"  Pipeline Status: Not started")
                all_complete = False
            
            if row:
                print(f"  DB Status: {row[0]}")
                if row[1]:  # has_ocr
                    print(f"  OCR: ✓ ({row[2]:,} characters)")
                else:
                    print(f"  OCR: ✗")
                print(f"  Chunks: {row[3]}")
                print(f"  Entities: {row[4]} ({row[5]} types)")
                
                # Get sample entities if any
                if row[4] > 0:
                    result = session.execute(
                        text("""
                            SELECT entity_text, entity_type, confidence_score
                            FROM entity_mentions
                            WHERE document_uuid = :uuid
                            ORDER BY confidence_score DESC
                            LIMIT 3
                        """),
                        {"uuid": doc_uuid}
                    )
                    entities = result.fetchall()
                    if entities:
                        print(f"  Sample entities:")
                        for entity in entities:
                            print(f"    - {entity[0]} ({entity[1]}) [{entity[2]:.2f}]")
    
    finally:
        session.close()
    
    return all_complete

def main():
    """Main monitoring loop"""
    print(f"\nContinuous monitoring started for batch: {batch_data['batch_id']}")
    print(f"Documents: {len(batch_data['documents'])}")
    print(f"Press Ctrl+C to stop\n")
    
    check_count = 0
    try:
        while True:
            check_count += 1
            all_complete = check_processing_status()
            
            if all_complete:
                print(f"\n{'='*80}")
                print("✓ All documents have completed processing!")
                print(f"{'='*80}")
                break
            
            # Wait 10 seconds between checks
            print(f"\nWaiting 10 seconds... (Check #{check_count})")
            time.sleep(10)
            
    except KeyboardInterrupt:
        print("\n\nMonitoring stopped by user")

if __name__ == "__main__":
    main()