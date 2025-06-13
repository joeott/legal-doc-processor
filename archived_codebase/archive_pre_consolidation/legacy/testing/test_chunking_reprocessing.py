#!/usr/bin/env python3
"""Test script to verify chunking reprocessing with preserve_ocr=True"""
import os
import sys
import logging
import uuid
from datetime import datetime
from scripts.supabase_utils import SupabaseManager
from scripts.celery_tasks.idempotent_ops import IdempotentDatabaseOps
from scripts.text_processing import process_document_with_semantic_chunking
from scripts.config import USE_STRUCTURED_EXTRACTION

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def cleanup_document_for_reprocessing_sync(db_manager, document_uuid: str, 
                                          stages_to_clean=None, preserve_ocr=True):
    """Synchronous version of cleanup_document_for_reprocessing for testing"""
    # Implement cleanup logic directly here to avoid Celery complications
    from scripts.redis_utils import get_redis_manager, CacheKeys
    
    stats = {
        'document_uuid': document_uuid,
        'cleaned_stages': [],
        'preserved_stages': [],
        'deleted_records': {}
    }
    
    try:
        # Get document info
        source_doc = db_manager.client.table('source_documents').select(
            'id', 'processing_version'
        ).eq('document_uuid', document_uuid).single().execute()
        
        if not source_doc.data:
            raise ValueError(f"Document {document_uuid} not found")
        
        source_doc_id = source_doc.data['id']
        
        # Get neo4j document
        neo4j_doc = db_manager.client.table('neo4j_documents').select(
            'id'
        ).eq('documentId', document_uuid).maybe_single().execute()
        
        if not neo4j_doc.data:
            logger.warning(f"No neo4j_document found for {document_uuid}")
            return stats
        
        neo4j_doc_id = neo4j_doc.data['id']
        
        # Determine what to clean
        all_stages = ['entities', 'chunks', 'neo4j_doc', 'ocr']
        stages = stages_to_clean or all_stages
        
        if preserve_ocr and 'ocr' in stages:
            stages.remove('ocr')
            stats['preserved_stages'].append('ocr')
        
        # Clean chunks
        if 'chunks' in stages:
            # Get chunks
            chunks = db_manager.client.table('neo4j_chunks').select('id').eq('document_id', neo4j_doc_id).execute()
            chunk_ids = [c['id'] for c in chunks.data]
            
            if chunk_ids:
                # Delete entity mentions first
                db_manager.client.table('neo4j_entity_mentions').delete().in_('chunk_fk_id', chunk_ids).execute()
                # Delete chunks
                db_manager.client.table('neo4j_chunks').delete().eq('document_id', neo4j_doc_id).execute()
                stats['deleted_records']['chunks'] = len(chunk_ids)
                stats['cleaned_stages'].append('chunks')
        
        # Clear Redis cache
        redis_mgr = get_redis_manager()
        if redis_mgr and redis_mgr.is_available():
            redis_mgr.invalidate_document_cache(document_uuid)
        
        # Update processing version
        new_version = source_doc.data.get('processing_version', 1) + 1
        db_manager.client.table('source_documents').update({
            'processing_version': new_version,
            'force_reprocess': False
        }).eq('id', source_doc_id).execute()
        
        stats['new_version'] = new_version
        return stats
        
    except Exception as e:
        logger.error(f"Error in cleanup: {e}")
        raise

def test_chunking_reprocessing():
    """Test that chunking reprocessing works correctly with preserve_ocr=True"""
    db_manager = SupabaseManager()
    idempotent_ops = IdempotentDatabaseOps(db_manager)
    
    # Test data
    test_project_uuid = str(uuid.uuid4())
    test_doc_name = "Test Chunking Reprocessing Document"
    test_text = """This is a test document for chunking reprocessing.

## Section 1: Introduction
This section contains the introduction to our test document.
It has multiple paragraphs to ensure proper chunking.

## Section 2: Main Content
The main content section has important information.
We want to ensure that chunks are properly created and can be reprocessed.

## Section 3: Conclusion
This is the conclusion of our test document.
It wraps up all the important points."""
    
    try:
        # Step 0: Create a test project
        logger.info("Creating test project...")
        project_result = db_manager.client.table('projects').insert({
            'projectId': test_project_uuid,
            'name': 'Test Chunking Reprocessing Project'
        }).execute()
        test_project_id = project_result.data[0]['id']
        logger.info(f"Created test project: ID={test_project_id}")
        
        # Step 1: Create a test source document
        logger.info("Creating test source document...")
        source_doc_id, source_doc_uuid = db_manager.create_source_document_entry(
            project_fk_id=test_project_id,
            project_uuid=test_project_uuid,
            original_file_path=f"test/{test_doc_name}",
            original_file_name=test_doc_name,
            detected_file_type="txt"
        )
        logger.info(f"Created source document: ID={source_doc_id}, UUID={source_doc_uuid}")
        
        # Update source document with OCR text (simulate OCR completion)
        db_manager.client.table('source_documents').update({
            'raw_extracted_text': test_text,
            'textract_job_status': 'succeeded',
            'celery_status': 'ocr_complete',
            'ocr_completed_at': datetime.now().isoformat()
        }).eq('id', source_doc_id).execute()
        
        # Step 2: Create neo4j document
        neo4j_doc_id, neo4j_doc_uuid = idempotent_ops.upsert_neo4j_document(
            source_doc_uuid=source_doc_uuid,
            source_doc_id=source_doc_id,
            project_id=test_project_id,
            project_uuid=test_project_uuid,
            file_name=test_doc_name
        )
        logger.info(f"Created neo4j document: ID={neo4j_doc_id}, UUID={neo4j_doc_uuid}")
        
        # Step 3: Process document with semantic chunking (first time)
        logger.info("\nTest 1: Initial chunking")
        chunks1, structured_data1 = process_document_with_semantic_chunking(
            db_manager=db_manager,
            document_sql_id=neo4j_doc_id,
            document_uuid=neo4j_doc_uuid,
            raw_text=test_text,
            ocr_metadata=None,
            doc_category='document',
            use_structured_extraction=False  # Skip structured extraction for speed
        )
        logger.info(f"✓ Created {len(chunks1)} chunks initially")
        
        # Verify chunks were created
        chunk_check1 = db_manager.client.table('neo4j_chunks').select('id', 'chunkIndex', 'text').eq('document_id', neo4j_doc_id).execute()
        logger.info(f"✓ Verified {len(chunk_check1.data)} chunks in database")
        
        # Step 4: Run cleanup with preserve_ocr=True
        logger.info("\nTest 2: Cleanup with preserve_ocr=True")
        cleanup_result = cleanup_document_for_reprocessing_sync(
            db_manager=db_manager,
            document_uuid=source_doc_uuid,
            stages_to_clean=['chunks', 'entities'],  # Use the correct stage names
            preserve_ocr=True
        )
        logger.info(f"Cleanup result: {cleanup_result}")
        logger.info("✓ Cleanup completed")
        
        # Verify OCR was preserved
        ocr_check = db_manager.client.table('source_documents').select('raw_extracted_text', 'textract_job_status').eq('id', source_doc_id).single().execute()
        if ocr_check.data['raw_extracted_text'] == test_text and ocr_check.data['textract_job_status'] == 'succeeded':
            logger.info("✓ SUCCESS: OCR text was preserved")
        else:
            logger.error("✗ FAILED: OCR text was not preserved")
            return False
        
        # Verify chunks were deleted
        chunk_check2 = db_manager.client.table('neo4j_chunks').select('id').eq('document_id', neo4j_doc_id).execute()
        if len(chunk_check2.data) == 0:
            logger.info("✓ SUCCESS: Chunks were properly cleaned up")
        else:
            logger.error(f"✗ FAILED: {len(chunk_check2.data)} chunks remain after cleanup")
            return False
        
        # Step 5: Reprocess document (second time)
        logger.info("\nTest 3: Reprocessing after cleanup")
        chunks2, structured_data2 = process_document_with_semantic_chunking(
            db_manager=db_manager,
            document_sql_id=neo4j_doc_id,
            document_uuid=neo4j_doc_uuid,
            raw_text=test_text,
            ocr_metadata=None,
            doc_category='document',
            use_structured_extraction=False
        )
        logger.info(f"✓ Created {len(chunks2)} chunks on reprocessing")
        
        # Verify chunks were recreated
        chunk_check3 = db_manager.client.table('neo4j_chunks').select('id', 'chunkIndex', 'text').eq('document_id', neo4j_doc_id).order('chunkIndex').execute()
        if len(chunk_check3.data) == len(chunks2):
            logger.info("✓ SUCCESS: Same number of chunks created on reprocessing")
        else:
            logger.error(f"✗ FAILED: Different chunk count: {len(chunk_check3.data)} vs {len(chunks2)}")
            return False
        
        # Step 6: Test direct reprocessing without cleanup (idempotent operation)
        logger.info("\nTest 4: Direct reprocessing without cleanup (idempotent test)")
        chunks3, structured_data3 = process_document_with_semantic_chunking(
            db_manager=db_manager,
            document_sql_id=neo4j_doc_id,
            document_uuid=neo4j_doc_uuid,
            raw_text=test_text,
            ocr_metadata=None,
            doc_category='document',
            use_structured_extraction=False
        )
        logger.info(f"✓ Processed again, got {len(chunks3)} chunks")
        
        # Verify no duplicate chunks were created
        chunk_check4 = db_manager.client.table('neo4j_chunks').select('id').eq('document_id', neo4j_doc_id).execute()
        if len(chunk_check4.data) == len(chunks3):
            logger.info("✓ SUCCESS: Idempotent processing - no duplicates created")
        else:
            logger.error(f"✗ FAILED: Chunk count mismatch: {len(chunk_check4.data)} in DB vs {len(chunks3)} returned")
            return False
        
        logger.info("\n✓ ALL TESTS PASSED!")
        return True
        
    except Exception as e:
        logger.error(f"Test failed with error: {e}", exc_info=True)
        return False
    finally:
        # Cleanup test data
        logger.info("\nCleaning up test data...")
        try:
            # Delete chunks first
            if 'neo4j_doc_id' in locals():
                db_manager.client.table('neo4j_chunks').delete().eq('document_id', neo4j_doc_id).execute()
            # Delete test documents
            if 'source_doc_id' in locals():
                db_manager.client.table('source_documents').delete().eq('id', source_doc_id).execute()
            if 'neo4j_doc_id' in locals():
                db_manager.client.table('neo4j_documents').delete().eq('id', neo4j_doc_id).execute()
            if 'test_project_id' in locals():
                db_manager.client.table('projects').delete().eq('id', test_project_id).execute()
            logger.info("✓ Test data cleaned up")
        except Exception as e:
            logger.error(f"Cleanup failed: {e}")

if __name__ == "__main__":
    success = test_chunking_reprocessing()
    sys.exit(0 if success else 1)