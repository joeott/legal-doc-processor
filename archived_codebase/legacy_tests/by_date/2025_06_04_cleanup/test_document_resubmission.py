#!/usr/bin/env python3
"""
Resubmit test document to pipeline after fixing validation error
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.pdf_tasks import process_pdf_document
from scripts.db import get_db
from sqlalchemy import text

def check_and_resubmit_document():
    """Check document status and resubmit to pipeline"""
    doc_uuid = '4909739b-8f12-40cd-8403-04b8b1a79281'
    
    # First check document exists and get details
    session = next(get_db())
    try:
        doc = session.execute(text("""
            SELECT document_uuid, file_name, project_uuid, status, 
                   textract_job_status, s3_key, s3_bucket
            FROM source_documents 
            WHERE document_uuid = :uuid
        """), {"uuid": doc_uuid}).fetchone()
        
        if not doc:
            print(f"ERROR: Document {doc_uuid} not found!")
            return False
            
        print(f"Document found: {doc.file_name}")
        print(f"Current status: {doc.status}")
        print(f"Textract status: {doc.textract_job_status}")
        print(f"S3 location: s3://{doc.s3_bucket}/{doc.s3_key}")
        
        # Construct file path
        file_path = f"input_docs/Paul, Michael (Acuity)/Paul, Michael - Wombat Corp Disclosure Stmt 10-23-24.pdf"
        
        print(f"\nResubmitting document to pipeline...")
        print(f"Document UUID: {doc_uuid}")
        print(f"File path: {file_path}")
        print(f"Project UUID: {doc.project_uuid}")
        
        # Submit to pipeline
        result = process_pdf_document.delay(
            document_uuid=doc_uuid,
            file_path=file_path,
            project_uuid=str(doc.project_uuid)
        )
        
        print(f"\nTask submitted successfully!")
        print(f"Task ID: {result.id}")
        print(f"Task status: {result.status}")
        
        # Update database to ensure processing state
        session.execute(text("""
            UPDATE source_documents 
            SET status = 'processing', updated_at = NOW()
            WHERE document_uuid = :uuid
        """), {"uuid": doc_uuid})
        session.commit()
        
        print(f"\nDocument status updated to 'processing'")
        print(f"\nTo monitor progress, run:")
        print(f"python3 scripts/monitor_document_complete.py {doc_uuid}")
        
        return result.id
        
    except Exception as e:
        print(f"ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        session.close()

if __name__ == "__main__":
    print("="*60)
    print("DOCUMENT RESUBMISSION TEST")
    print("="*60)
    
    task_id = check_and_resubmit_document()
    
    if task_id:
        print(f"\n✓ SUCCESS - Task ID: {task_id}")
        sys.exit(0)
    else:
        print(f"\n✗ FAILED")
        sys.exit(1)