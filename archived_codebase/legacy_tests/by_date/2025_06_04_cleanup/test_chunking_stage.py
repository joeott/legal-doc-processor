#!/usr/bin/env python3
"""
Test chunking stage of the pipeline
Phase 1 of recovery plan from context_362
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.pdf_tasks import chunk_document_text
from scripts.db import get_db, DatabaseManager
from sqlalchemy import text

def test_chunking_stage():
    """Test the chunking stage with our recovered document"""
    document_uuid = "4909739b-8f12-40cd-8403-04b8b1a79281"
    
    print("="*60)
    print("CHUNKING STAGE TEST")
    print("="*60)
    print(f"Document UUID: {document_uuid}")
    print(f"Time: {datetime.now()}")
    
    # First verify document has OCR text
    print("\n1. Checking document OCR status...")
    extracted_text = None
    session = next(get_db())
    try:
        doc = session.execute(text("""
            SELECT 
                document_uuid,
                file_name,
                textract_job_status,
                raw_extracted_text,
                LENGTH(raw_extracted_text) as text_length
            FROM source_documents
            WHERE document_uuid = :uuid
        """), {"uuid": document_uuid}).fetchone()
        
        if not doc:
            print("✗ Document not found!")
            return False
            
        print(f"✓ Document: {doc.file_name}")
        print(f"  OCR Status: {doc.textract_job_status}")
        print(f"  Text Length: {doc.text_length} chars")
        
        if not doc.text_length or doc.text_length == 0:
            print("✗ No OCR text found! Run OCR first.")
            return False
        
        extracted_text = doc.raw_extracted_text
            
    finally:
        session.close()
    
    # Check existing chunks
    print("\n2. Checking existing chunks...")
    session = next(get_db())
    try:
        chunk_count = session.execute(text("""
            SELECT COUNT(*) as count
            FROM document_chunks
            WHERE document_uuid = :uuid
        """), {"uuid": document_uuid}).scalar()
        
        print(f"  Existing chunks: {chunk_count}")
        
    finally:
        session.close()
    
    # Trigger chunking
    print("\n3. Triggering chunking task...")
    try:
        result = chunk_document_text.delay(document_uuid, extracted_text)
        print(f"✓ Task submitted: {result.id}")
        print(f"  Status: {result.status}")
        
        # Wait for completion
        print("\n4. Waiting for task completion...")
        import time
        for i in range(30):  # Wait up to 30 seconds
            if result.ready():
                break
            time.sleep(1)
            if i % 5 == 0:
                print(f"  Waiting... ({i}s)")
        
        if result.successful():
            print(f"✓ Task completed successfully!")
            print(f"  Result: {result.result}")
        elif result.failed():
            print(f"✗ Task failed!")
            print(f"  Error: {result.info}")
            if hasattr(result, 'traceback'):
                print(f"  Traceback:\n{result.traceback}")
        else:
            print(f"  Task status: {result.status}")
            
    except Exception as e:
        print(f"✗ Error triggering task: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    
    # Verify chunks created
    print("\n5. Verifying chunks created...")
    session = next(get_db())
    try:
        chunks = session.execute(text("""
            SELECT 
                id,
                chunk_index,
                LENGTH(text) as content_length,
                metadata_json
            FROM document_chunks
            WHERE document_uuid = :uuid
            ORDER BY chunk_index
            LIMIT 5
        """), {"uuid": document_uuid}).fetchall()
        
        if chunks:
            print(f"✓ Created {len(chunks)} chunks (showing first 5)")
            for chunk in chunks:
                print(f"  Chunk {chunk.chunk_index}: {chunk.content_length} chars")
        else:
            print("✗ No chunks created!")
            
    finally:
        session.close()
    
    return True

if __name__ == "__main__":
    success = test_chunking_stage()
    print("\n" + "="*60)
    if success:
        print("✓ CHUNKING STAGE TEST COMPLETE")
    else:
        print("✗ CHUNKING STAGE TEST FAILED")
    print("="*60)