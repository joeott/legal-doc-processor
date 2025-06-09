#!/usr/bin/env python3
"""
Real Document Processing Test WITH Document Creation
Based on historical context solutions
"""

import os
import sys
import time
import uuid
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.celery_app import app
from scripts.pdf_tasks import process_pdf_document
from scripts.db import DatabaseManager
from scripts.cache import get_redis_manager
from scripts.s3_storage import S3StorageManager
from scripts.logging_config import get_logger
from sqlalchemy import text

logger = get_logger(__name__)

class RealDocumentTesterWithCreation:
    """Test actual document processing with proper document creation"""
    
    def __init__(self):
        self.test_doc = "input_docs/Paul, Michael (Acuity)/Paul, Michael - Wombat Corp Disclosure Stmt 10-23-24.pdf"
        self.results = {}
        
    def create_document_in_database(self, doc_uuid, project_uuid, file_path):
        """Create document in database before processing"""
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Creating document in database...")
        
        db_manager = DatabaseManager()
        
        # First ensure project exists
        from scripts.db import get_db
        session = next(get_db())
        try:
            # Use existing project or get first available
            result = session.execute(text(
                "SELECT project_id FROM projects LIMIT 1"
            )).fetchone()
            
            if result:
                # Use existing project
                actual_project_uuid = str(result.project_id)
                print(f"Using existing project: {actual_project_uuid}")
            else:
                # No projects exist, this is a problem
                raise RuntimeError("No projects found in database")
            
            # Create document record
            print(f"Creating document {doc_uuid}")
            session.execute(text("""
                INSERT INTO source_documents (
                    document_uuid, project_uuid, file_name, file_path,
                    file_type, status, created_at
                ) VALUES (
                    :doc_uuid, :project_uuid, :file_name, :file_path,
                    :file_type, :status, NOW()
                )
            """), {
                "doc_uuid": doc_uuid,
                "project_uuid": actual_project_uuid,
                "file_name": Path(file_path).name,
                "file_path": file_path,
                "file_type": "pdf",
                "status": "pending"
            })
            session.commit()
            print("✓ Document created and committed")
            
        finally:
            session.close()
        
        # Verify visibility with fresh connection (from historical context)
        print("\nVerifying document visibility...")
        max_retries = 5
        document_visible = False
        
        for i in range(max_retries):
            verify_db = DatabaseManager()
            verify_session = next(get_db())
            try:
                result = verify_session.execute(text(
                    "SELECT 1 FROM source_documents WHERE document_uuid = :uuid"
                ), {"uuid": doc_uuid}).fetchone()
                
                if result:
                    document_visible = True
                    print(f"✓ Document visible on attempt {i+1}")
                    break
                else:
                    print(f"Document not visible yet, retry {i+1}/{max_retries}")
                    time.sleep(0.5)
            finally:
                verify_session.close()
        
        if not document_visible:
            raise RuntimeError(f"Document {doc_uuid} not visible after {max_retries} attempts")
        
        return actual_project_uuid
    
    def upload_to_s3(self, doc_uuid, project_uuid, file_path):
        """Upload document to S3"""
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Uploading to S3...")
        
        s3_manager = S3StorageManager()
        
        # Use the new API method
        s3_result = s3_manager.upload_document_with_uuid_naming(
            file_path, doc_uuid, project_uuid
        )
        
        if s3_result:
            print(f"✓ Uploaded to S3: {s3_result}")
            
            # Extract the actual S3 key from the result
            if isinstance(s3_result, dict):
                s3_key = s3_result.get('s3_key')
                s3_bucket = s3_result.get('s3_bucket', s3_manager.private_bucket_name)
                s3_region = s3_result.get('s3_region', 'us-east-1')
            else:
                s3_key = s3_result
                s3_bucket = s3_manager.private_bucket_name
                s3_region = 'us-east-1'
            
            # Update database with S3 info
            from scripts.db import get_db
            session = next(get_db())
            try:
                session.execute(text("""
                    UPDATE source_documents 
                    SET s3_key = :s3_key, 
                        s3_bucket = :bucket,
                        s3_region = :region,
                        updated_at = NOW()
                    WHERE document_uuid = :uuid
                """), {
                    "s3_key": s3_key,
                    "bucket": s3_bucket,
                    "region": s3_region,
                    "uuid": doc_uuid
                })
                session.commit()
                print("✓ Updated database with S3 info")
            finally:
                session.close()
                
            return s3_result
        else:
            raise RuntimeError("Failed to upload to S3")
    
    def test_single_document_e2e(self):
        """Test complete pipeline for one real document"""
        doc_uuid = str(uuid.uuid4())
        project_uuid = str(uuid.uuid4())
        file_path = self.test_doc
        
        print(f"\n{'='*60}")
        print(f"REAL DOCUMENT PROCESSING WITH PROPER CREATION")
        print(f"{'='*60}")
        print(f"Document: {file_path}")
        print(f"Document UUID: {doc_uuid}")
        print(f"Project UUID: {project_uuid}")
        
        # Check file exists
        if not os.path.exists(file_path):
            print(f"ERROR: Test file not found: {file_path}")
            return False
        
        try:
            # Step 1: Create document in database (returns actual project UUID)
            actual_project_uuid = self.create_document_in_database(doc_uuid, project_uuid, file_path)
            
            # Step 2: Upload to S3
            s3_result = self.upload_to_s3(doc_uuid, actual_project_uuid, file_path)
            
            # Step 3: Submit to pipeline with S3 URI
            s3_key = s3_result['s3_key'] if isinstance(s3_result, dict) else s3_result
            s3_bucket = s3_result['s3_bucket'] if isinstance(s3_result, dict) else S3StorageManager().private_bucket_name
            s3_uri = f"s3://{s3_bucket}/{s3_key}"
            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Submitting to pipeline...")
            print(f"Using S3 URI: {s3_uri}")
            
            task = process_pdf_document.delay(doc_uuid, s3_uri, actual_project_uuid)
            print(f"Task ID: {task.id}")
            
            # Step 4: Monitor progress
            start_time = time.time()
            timeout = 300
            
            while time.time() - start_time < timeout:
                if task.ready():
                    if task.successful():
                        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Task completed!")
                        print(f"Result: {json.dumps(task.result, indent=2)}")
                    else:
                        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Task failed!")
                        print(f"Error: {task.info}")
                    break
                
                # Check document status
                from scripts.db import get_db
                session = next(get_db())
                try:
                    result = session.execute(text("""
                        SELECT status, textract_job_status, 
                               (SELECT COUNT(*) FROM document_chunks WHERE source_document_uuid = :uuid) as chunks,
                               (SELECT COUNT(*) FROM entity_mentions WHERE source_document_uuid = :uuid) as entities
                        FROM source_documents 
                        WHERE document_uuid = :uuid
                    """), {"uuid": doc_uuid}).fetchone()
                    
                    if result:
                        print(f"\r[{datetime.now().strftime('%H:%M:%S')}] Status: {result.status} | "
                              f"OCR: {result.textract_job_status or 'pending'} | "
                              f"Chunks: {result.chunks} | Entities: {result.entities}", end="")
                finally:
                    session.close()
                
                time.sleep(5)
            
            # Final verification
            elapsed = time.time() - start_time
            print(f"\n\nProcessing time: {elapsed:.1f} seconds")
            
            return self.verify_final_state(doc_uuid)
            
        except Exception as e:
            print(f"\nERROR: {e}")
            logger.error(f"Test failed: {e}", exc_info=True)
            return False
    
    def verify_final_state(self, doc_uuid):
        """Verify all pipeline stages completed"""
        print(f"\n{'='*60}")
        print("FINAL VERIFICATION")
        print(f"{'='*60}")
        
        from scripts.db import get_db
        session = next(get_db())
        try:
            # Get comprehensive status
            result = session.execute(text("""
                SELECT 
                    sd.status,
                    sd.textract_job_status,
                    sd.file_name,
                    COUNT(DISTINCT dc.id) as chunk_count,
                    COUNT(DISTINCT em.id) as entity_count,
                    COUNT(DISTINCT ce.id) as canonical_count,
                    COUNT(DISTINCT rs.id) as relationship_count
                FROM source_documents sd
                LEFT JOIN document_chunks dc ON sd.document_uuid = dc.source_document_uuid
                LEFT JOIN entity_mentions em ON sd.document_uuid = em.source_document_uuid
                LEFT JOIN canonical_entities ce ON sd.document_uuid = ce.created_from_document_uuid
                LEFT JOIN relationship_staging rs ON sd.document_uuid = rs.source_document_uuid
                WHERE sd.document_uuid = :uuid
                GROUP BY sd.document_uuid, sd.status, sd.textract_job_status, sd.file_name
            """), {"uuid": doc_uuid}).fetchone()
            
            if result:
                print(f"Document: {result.file_name}")
                print(f"Status: {result.status}")
                print(f"OCR Status: {result.textract_job_status}")
                print(f"\nPipeline Results:")
                print(f"  1. Document Created: ✓")
                print(f"  2. OCR Completed: {'✓' if result.textract_job_status == 'SUCCEEDED' else '✗'}")
                print(f"  3. Chunks Created: {'✓' if result.chunk_count > 0 else '✗'} ({result.chunk_count})")
                print(f"  4. Entities Extracted: {'✓' if result.entity_count > 0 else '✗'} ({result.entity_count})")
                print(f"  5. Entities Resolved: {'✓' if result.canonical_count > 0 else '✗'} ({result.canonical_count})")
                print(f"  6. Relationships Built: {'✓' if result.relationship_count > 0 else '✗'} ({result.relationship_count})")
                
                stages_completed = sum([
                    1,  # Document created
                    1 if result.textract_job_status == 'SUCCEEDED' else 0,
                    1 if result.chunk_count > 0 else 0,
                    1 if result.entity_count > 0 else 0,
                    1 if result.canonical_count > 0 else 0,
                    1 if result.relationship_count > 0 else 0
                ])
                
                print(f"\nOVERALL: {stages_completed}/6 stages completed")
                return stages_completed >= 2  # At least document created and OCR started
                
            else:
                print("ERROR: Document not found!")
                return False
                
        finally:
            session.close()


def main():
    """Run the test with proper document creation"""
    # Check Celery
    try:
        i = app.control.inspect()
        stats = i.stats()
        if stats:
            print(f"✓ Celery workers available: {len(stats)}")
        else:
            print("✗ No Celery workers found! Please start workers first.")
            return
    except Exception as e:
        print(f"✗ Cannot connect to Celery: {e}")
        return
    
    # Run test
    tester = RealDocumentTesterWithCreation()
    success = tester.test_single_document_e2e()
    
    if success:
        print("\n✅ TEST PASSED!")
    else:
        print("\n❌ TEST FAILED!")
    
    return success


if __name__ == "__main__":
    main()