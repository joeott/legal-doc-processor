#!/usr/bin/env python3
"""
Manually poll Textract job to test the fix
"""
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.db import DatabaseManager
from scripts.textract_utils import TextractProcessor

def poll_textract_manually():
    """Poll the Textract job manually"""
    job_id = "6b6aa0a2113f011f367f9cb943c501700a4e5fcca54ed94dd620d8f8d55c13a7"
    document_uuid = "4909739b-8f12-40cd-8403-04b8b1a79281"
    source_doc_id = 80
    
    print(f"Polling Textract job: {job_id}")
    print(f"Document: {document_uuid}")
    
    # Initialize managers
    db_manager = DatabaseManager(validate_conformance=False)
    textract_processor = TextractProcessor(db_manager)
    
    try:
        # Poll for results
        print("\nPolling for Textract results...")
        blocks, metadata = textract_processor.get_text_detection_results(job_id, source_doc_id)
        
        if blocks:
            print(f"\n✓ Textract completed successfully!")
            print(f"  - Pages: {metadata.get('total_pages', 'unknown')}")
            print(f"  - Blocks: {len(blocks)}")
            print(f"  - Confidence: {metadata.get('avg_confidence', 'unknown')}")
            
            # Process blocks to text
            extracted_text = textract_processor.process_textract_blocks_to_text(blocks, metadata)
            
            print(f"\nExtracted text length: {len(extracted_text)} characters")
            print(f"First 200 chars: {extracted_text[:200]}...")
            
            # Update document
            print("\nUpdating document with results...")
            result = db_manager.update_source_document_with_textract_outcome(
                source_doc_sql_id=source_doc_id,
                textract_job_id=job_id,
                textract_job_status='SUCCEEDED',
                raw_text=extracted_text,
                job_started_at=datetime.utcnow(),
                job_completed_at=datetime.utcnow()
            )
            
            print("\n✓ Document updated successfully!")
            return extracted_text
            
        else:
            status = metadata.get('job_status', 'UNKNOWN')
            print(f"\nTextract job status: {status}")
            if status == 'IN_PROGRESS':
                print("Job is still processing, please wait...")
            elif status == 'FAILED':
                print(f"Job failed: {metadata.get('status_message', 'Unknown error')}")
            
    except Exception as e:
        print(f"\n✗ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return None

if __name__ == "__main__":
    print("="*60)
    print("MANUAL TEXTRACT POLLING TEST")
    print("="*60)
    
    result = poll_textract_manually()
    if result:
        print("\n✓ SUCCESS - Text extracted")
    else:
        print("\n✗ No text extracted yet")