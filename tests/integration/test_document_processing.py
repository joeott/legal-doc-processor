#!/usr/bin/env python3
"""
Test document processing with a real document to verify Fix #2 and Fix #3
"""
import os
import sys
import time
import uuid
from datetime import datetime

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from scripts.cache import get_redis_manager, CacheKeys
from scripts.db import DatabaseManager
from scripts.intake_service import create_document_with_validation
from scripts.pdf_tasks import process_pdf_document
from scripts.models import SourceDocumentMinimal
from sqlalchemy import text
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    # Test document path
    document_path = "/opt/legal-doc-processor/input_docs/Paul, Michael (Acuity)/Paul, Michael - Lora Prop Disclosure Stmt 10-21-24.pdf"
    
    if not os.path.exists(document_path):
        logger.error(f"Document not found: {document_path}")
        return
    
    # Create project and document IDs
    project_uuid = str(uuid.uuid4())
    document_uuid = str(uuid.uuid4())
    
    logger.info(f"Starting document processing test")
    logger.info(f"Document: {os.path.basename(document_path)}")
    logger.info(f"Project UUID: {project_uuid}")
    logger.info(f"Document UUID: {document_uuid}")
    
    db_manager = DatabaseManager()
    redis_manager = get_redis_manager()
    
    try:
        # Create document in database
        session = next(db_manager.get_session())
        
        # First create a dummy project
        # Check if project exists first
        existing_project = session.execute(text("""
            SELECT id FROM projects WHERE project_id = :project_uuid
        """), {'project_uuid': project_uuid})
        
        project_fk_id = existing_project.scalar()
        
        if not project_fk_id:
            project_result = session.execute(text("""
                INSERT INTO projects (project_id, name, created_at, updated_at)
                VALUES (:project_uuid, :name, NOW(), NOW())
                RETURNING id
            """), {
                'project_uuid': project_uuid,
                'name': 'Test Project - Fix Verification'
            })
            project_fk_id = project_result.scalar()
            session.commit()
        
        # Create source document with pending status using raw SQL
        insert_query = text("""
            INSERT INTO source_documents (
                document_uuid, project_fk_id, original_file_name, file_name,
                s3_bucket, s3_key, status, created_at, file_size_bytes
            ) VALUES (
                :doc_uuid, :project_id, :filename, :filename,
                :s3_bucket, :s3_key, 'pending', NOW(), :file_size
            )
            RETURNING id, status
        """)
        
        result = session.execute(insert_query, {
            'doc_uuid': document_uuid,
            'project_id': project_fk_id,
            'filename': os.path.basename(document_path),
            's3_bucket': 'samu-docs-private-upload',
            's3_key': f"documents/{document_uuid}/{os.path.basename(document_path)}",
            'file_size': os.path.getsize(document_path)
        })
        
        doc_id, status = result.fetchone()
        session.commit()
        logger.info(f"✅ Created document in database with status: {status}")
        
        # Store metadata in Redis for pipeline
        metadata_key = f"doc:metadata:{document_uuid}"
        metadata = {
            'project_uuid': project_uuid,
            'file_name': os.path.basename(document_path),
            'created_at': datetime.now().isoformat()
        }
        redis_manager.store_dict(metadata_key, metadata)
        logger.info("✅ Stored document metadata in Redis")
        
        # Start processing
        logger.info("\n🚀 Starting document processing pipeline...")
        
        # Call process_pdf_document task
        result = process_pdf_document.apply_async(
            args=[document_uuid, document_path, project_uuid, {}]
        )
        
        logger.info(f"Task submitted: {result.id}")
        logger.info("Waiting for OCR to complete...")
        
        # Wait for processing with timeout
        timeout = 120  # 2 minutes
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            # Check document status
            session.expire_all()  # Refresh session
            status_result = session.execute(text("""
                SELECT status FROM source_documents WHERE document_uuid = :doc_uuid
            """), {'doc_uuid': document_uuid})
            
            status = status_result.scalar()
            if status == 'completed':
                logger.info("✅ Document processing completed!")
                break
                
            # Check OCR cache
            ocr_cache_key = CacheKeys.format_key(CacheKeys.DOC_OCR_RESULT, document_uuid=document_uuid)
            ocr_data = redis_manager.get_dict(ocr_cache_key)
            
            if ocr_data and not hasattr(main, '_ocr_logged'):
                logger.info("✅ OCR result found in cache!")
                logger.info(f"  - Text length: {ocr_data.get('length', 0)}")
                logger.info(f"  - Method: {ocr_data.get('method', 'unknown')}")
                main._ocr_logged = True
            
            # Check processing tasks
            result = session.execute(text("""
                SELECT task_type, status, created_at, completed_at 
                FROM processing_tasks 
                WHERE document_id = :doc_id 
                ORDER BY created_at DESC
            """), {'doc_id': document_uuid})
            
            tasks = list(result)
            if tasks and not hasattr(main, '_tasks_logged'):
                logger.info(f"✅ Found {len(tasks)} processing task records:")
                for task in tasks[:5]:  # Show first 5
                    logger.info(f"  - {task[0]}: {task[1]} (created: {task[2]})")
                main._tasks_logged = True
            
            time.sleep(2)
        
        # Final checks
        logger.info("\n📊 Final Results:")
        
        # Check final document status
        final_status_result = session.execute(text("""
            SELECT status FROM source_documents WHERE document_uuid = :doc_uuid
        """), {'doc_uuid': document_uuid})
        final_status = final_status_result.scalar()
        logger.info(f"Document status: {final_status if final_status else 'NOT FOUND'}")
        
        # Check all cache entries
        cache_checks = {
            'OCR Result': CacheKeys.DOC_OCR_RESULT,
            'Chunks': CacheKeys.DOC_CHUNKS,
            'All Mentions': CacheKeys.DOC_ALL_EXTRACTED_MENTIONS,
            'Canonical Entities': CacheKeys.DOC_CANONICAL_ENTITIES,
            'Resolved Mentions': CacheKeys.DOC_RESOLVED_MENTIONS
        }
        
        logger.info("\nCache entries:")
        for name, key_template in cache_checks.items():
            key = CacheKeys.format_key(key_template, document_uuid=document_uuid)
            exists = redis_manager.get_client().exists(key)
            logger.info(f"  - {name}: {'✅ EXISTS' if exists else '❌ MISSING'}")
        
        # Check processing tasks
        result = session.execute(text("""
            SELECT task_type, status, COUNT(*) 
            FROM processing_tasks 
            WHERE document_id = :doc_id 
            GROUP BY task_type, status
            ORDER BY task_type
        """), {'doc_id': document_uuid})
        
        logger.info("\nProcessing tasks summary:")
        task_count = 0
        for row in result:
            logger.info(f"  - {row[0]}: {row[1]} ({row[2]} records)")
            task_count += row[2]
        
        if task_count == 0:
            logger.info("  ❌ No processing tasks found!")
        
        # Check chunk creation
        result = session.execute(text("""
            SELECT COUNT(*) FROM document_chunks WHERE document_uuid = :doc_id
        """), {'doc_id': document_uuid})
        chunk_count = result.scalar()
        logger.info(f"\nChunks created: {chunk_count}")
        
        # Check entity extraction
        result = session.execute(text("""
            SELECT COUNT(*) FROM entity_mentions WHERE document_uuid = :doc_id
        """), {'doc_id': document_uuid})
        entity_count = result.scalar()
        logger.info(f"Entities extracted: {entity_count}")
        
        session.close()
        
    except Exception as e:
        logger.error(f"Error during processing: {str(e)}", exc_info=True)
    finally:
        if 'session' in locals():
            session.close()

if __name__ == "__main__":
    main()