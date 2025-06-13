#!/usr/bin/env python3
"""
End-to-end production test with column/field mismatch detection
"""
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from scripts.db import DatabaseManager
from scripts.intake_service import create_document_with_validation
from scripts.pdf_tasks import process_pdf_document
from scripts.cache import get_redis_manager
from sqlalchemy import text
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_phase_1_document_creation():
    """Phase 1: Test document creation and intake"""
    print("\n=== PHASE 1: Document Creation ===")
    
    db_manager = DatabaseManager(validate_conformance=False)
    redis_manager = get_redis_manager()
    
    # Test document
    test_file = "/opt/legal-doc-processor/input_docs/Paul, Michael (Acuity)/Paul, Michael - Lora Prop Disclosure Stmt 10-21-24.pdf"
    
    if not os.path.exists(test_file):
        print(f"❌ Test file not found: {test_file}")
        return None
        
    try:
        # Create project first
        project_uuid = str(uuid.uuid4())
        project_name = "E2E Test Project"
        
        session = next(db_manager.get_session())
        
        # Create project with all required fields
        project_result = session.execute(text("""
            INSERT INTO projects (project_id, name, created_at, updated_at)
            VALUES (:project_uuid, :name, NOW(), NOW())
            RETURNING id
        """), {
            'project_uuid': project_uuid,
            'name': project_name
        })
        project_fk_id = project_result.scalar()
        session.commit()
        print(f"✅ Created project: {project_name} (ID: {project_fk_id})")
        
        # Use intake service to create document
        from scripts.intake_service import DocumentIntakeService
        intake_service = DocumentIntakeService()
        
        # Call create_document_with_validation from intake_service
        document_uuid = str(uuid.uuid4())
        result = create_document_with_validation(
            document_uuid=document_uuid,
            project_id=project_fk_id,
            filename=os.path.basename(test_file),
            s3_bucket='samu-docs-private-upload',
            s3_key=f'documents/{document_uuid}/{os.path.basename(test_file)}'
        )
        
        print(f"✅ Document created: {result['document_uuid']}")
        
        session.close()
        return result
        
    except Exception as e:
        print(f"❌ Error in Phase 1: {str(e)}")
        logger.error(f"Phase 1 error: {str(e)}", exc_info=True)
        return None

def test_phase_2_ocr_processing(document_uuid: str, file_path: str, project_uuid: str):
    """Phase 2: Test OCR processing"""
    print("\n=== PHASE 2: OCR Processing ===")
    
    try:
        # Start OCR processing
        result = process_pdf_document.apply_async(
            args=[document_uuid, file_path, project_uuid, {}]
        )
        
        print(f"✅ OCR task submitted: {result.id}")
        
        # Wait briefly for task to start
        import time
        time.sleep(5)
        
        # Check if task started
        db_manager = DatabaseManager(validate_conformance=False)
        session = next(db_manager.get_session())
        
        task_result = session.execute(text("""
            SELECT task_type, status, error_message 
            FROM processing_tasks 
            WHERE document_id = :doc_id
            ORDER BY created_at DESC
            LIMIT 1
        """), {'doc_id': document_uuid})
        
        row = task_result.fetchone()
        if row:
            print(f"Task status: {row[0]} - {row[1]}")
            if row[2]:
                print(f"Error: {row[2][:200]}")
                
        session.close()
        return result.id
        
    except Exception as e:
        print(f"❌ Error in Phase 2: {str(e)}")
        logger.error(f"Phase 2 error: {str(e)}", exc_info=True)
        return None

def test_phase_3_chunk_processing(document_uuid: str):
    """Phase 3: Test chunk processing"""
    print("\n=== PHASE 3: Chunk Processing ===")
    
    try:
        db_manager = DatabaseManager(validate_conformance=False)
        session = next(db_manager.get_session())
        
        # Check if chunks exist
        chunk_count = session.execute(text("""
            SELECT COUNT(*) FROM document_chunks WHERE document_uuid = :doc_id
        """), {'doc_id': document_uuid}).scalar()
        
        print(f"Chunks created: {chunk_count}")
        
        if chunk_count > 0:
            # Get a sample chunk
            chunk = session.execute(text("""
                SELECT chunk_uuid, chunk_index, chunk_text 
                FROM document_chunks 
                WHERE document_uuid = :doc_id 
                LIMIT 1
            """), {'doc_id': document_uuid}).fetchone()
            
            if chunk:
                print(f"✅ Sample chunk: {chunk[0]} (index: {chunk[1]})")
                print(f"   Text preview: {chunk[2][:100]}...")
                
        session.close()
        return chunk_count > 0
        
    except Exception as e:
        print(f"❌ Error in Phase 3: {str(e)}")
        logger.error(f"Phase 3 error: {str(e)}", exc_info=True)
        return False

def main():
    print("Starting Production End-to-End Test")
    print("===================================")
    
    # Phase 1: Document Creation
    doc_result = test_phase_1_document_creation()
    if not doc_result:
        print("\n❌ Phase 1 failed, stopping test")
        return
        
    document_uuid = doc_result['document_uuid']
    project_uuid = doc_result.get('project_uuid', str(uuid.uuid4()))
    test_file = "/opt/legal-doc-processor/input_docs/Paul, Michael (Acuity)/Paul, Michael - Lora Prop Disclosure Stmt 10-21-24.pdf"
    
    # Phase 2: OCR Processing
    task_id = test_phase_2_ocr_processing(document_uuid, test_file, project_uuid)
    if not task_id:
        print("\n❌ Phase 2 failed, stopping test")
        return
        
    # Wait for processing
    print("\nWaiting for pipeline to process...")
    import time
    time.sleep(30)
    
    # Phase 3: Chunk Processing
    chunks_ok = test_phase_3_chunk_processing(document_uuid)
    if not chunks_ok:
        print("\n❌ Phase 3 failed")
    else:
        print("\n✅ Phase 3 completed successfully")
    
    # Final status check
    print("\n=== FINAL STATUS ===")
    db_manager = DatabaseManager(validate_conformance=False)
    session = next(db_manager.get_session())
    
    status_result = session.execute(text("""
        SELECT status FROM source_documents WHERE document_uuid = :doc_id
    """), {'doc_id': document_uuid})
    
    status = status_result.scalar()
    print(f"Document final status: {status}")
    
    session.close()

if __name__ == "__main__":
    main()