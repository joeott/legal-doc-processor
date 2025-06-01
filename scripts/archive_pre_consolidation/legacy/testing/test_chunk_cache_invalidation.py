#!/usr/bin/env python3
"""Test script to verify chunk-level cache invalidation works correctly"""
import os
import sys
import logging
import uuid
from datetime import datetime
from scripts.supabase_utils import SupabaseManager
from scripts.celery_tasks.idempotent_ops import IdempotentDatabaseOps
from scripts.redis_utils import get_redis_manager, CacheKeys
from scripts.text_processing import process_document_with_semantic_chunking

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def cleanup_document_for_reprocessing_sync(db_manager, document_uuid: str, 
                                          stages_to_clean=None, preserve_ocr=True):
    """Synchronous version of cleanup_document_for_reprocessing for testing"""
    # Import the actual function and execute it directly
    from scripts.celery_tasks import cleanup_tasks
    
    # Create a mock object to act as self parameter
    class MockTask:
        request = type('obj', (object,), {'id': 'test-task-id'})
    
    # Call the task directly, bypassing Celery
    task = cleanup_tasks.cleanup_document_for_reprocessing
    return task.run(document_uuid, stages_to_clean, preserve_ocr)

def test_chunk_cache_invalidation():
    """Test that chunk-level cache invalidation works correctly"""
    db_manager = SupabaseManager()
    idempotent_ops = IdempotentDatabaseOps(db_manager)
    redis_mgr = get_redis_manager()
    
    if not redis_mgr or not redis_mgr.is_available():
        logger.error("Redis is not available. Cannot test cache invalidation.")
        return False
    
    redis_client = redis_mgr.get_client()
    
    # Test data
    test_project_uuid = str(uuid.uuid4())
    test_doc_name = "Test Chunk Cache Invalidation Document"
    test_text = """This is a test document for cache invalidation testing.

## Section 1: Cache Testing
This section will be cached and then invalidated.
We need to verify that all cache keys are properly cleared.

## Section 2: More Content
Additional content to ensure multiple chunks are created.
This will help us test that all chunk caches are cleared.

## Section 3: Final Section
The final section of our test document.
This ensures we have enough content for proper chunking."""
    
    try:
        # Step 0: Create a test project
        logger.info("Creating test project...")
        project_result = db_manager.client.table('projects').insert({
            'projectId': test_project_uuid,
            'name': 'Test Cache Invalidation Project'
        }).execute()
        test_project_id = project_result.data[0]['id']
        logger.info(f"Created test project: ID={test_project_id}")
        
        # Step 1: Create test documents
        logger.info("Creating test documents...")
        source_doc_id, source_doc_uuid = db_manager.create_source_document_entry(
            project_fk_id=test_project_id,
            project_uuid=test_project_uuid,
            original_file_path=f"test/{test_doc_name}",
            original_file_name=test_doc_name,
            detected_file_type="txt"
        )
        
        # Simulate OCR completion
        db_manager.client.table('source_documents').update({
            'raw_extracted_text': test_text,
            'textract_job_status': 'succeeded',
            'celery_status': 'ocr_complete',
            'ocr_completed_at': datetime.now().isoformat()
        }).eq('id', source_doc_id).execute()
        
        neo4j_doc_id, neo4j_doc_uuid = idempotent_ops.upsert_neo4j_document(
            source_doc_uuid=source_doc_uuid,
            source_doc_id=source_doc_id,
            project_id=test_project_id,
            project_uuid=test_project_uuid,
            file_name=test_doc_name
        )
        logger.info(f"Created documents: source={source_doc_uuid}, neo4j={neo4j_doc_uuid}")
        
        # Step 2: Cache some document data
        logger.info("\nTest 1: Adding cache entries")
        
        # Cache OCR result
        ocr_key = CacheKeys.format_key(CacheKeys.DOC_OCR_RESULT, document_uuid=source_doc_uuid)
        redis_mgr.set_cached(ocr_key, {'text': test_text, 'metadata': {}}, ttl=3600)
        
        # Cache cleaned text
        cleaned_text_key = CacheKeys.format_key(CacheKeys.DOC_CLEANED_TEXT, document_uuid=source_doc_uuid)
        redis_mgr.set_cached(cleaned_text_key, test_text, ttl=3600)
        
        # Cache document state
        state_key = CacheKeys.format_key(CacheKeys.DOC_STATE, document_uuid=source_doc_uuid)
        redis_mgr.set_cached(state_key, {'stage': 'testing', 'status': 'in_progress'}, ttl=3600)
        
        logger.info("✓ Added document-level cache entries")
        
        # Step 3: Process document to create chunks
        logger.info("\nTest 2: Processing document to create chunks")
        chunks, _ = process_document_with_semantic_chunking(
            db_manager=db_manager,
            document_sql_id=neo4j_doc_id,
            document_uuid=neo4j_doc_uuid,
            raw_text=test_text,
            ocr_metadata=None,
            doc_category='document',
            use_structured_extraction=False
        )
        logger.info(f"✓ Created {len(chunks)} chunks")
        
        # Step 4: Add chunk-specific caches
        logger.info("\nTest 3: Adding chunk-specific cache entries")
        chunk_cache_keys = []
        
        # Cache chunk list
        chunks_list_key = CacheKeys.format_key(CacheKeys.DOC_CHUNKS_LIST, document_uuid=source_doc_uuid)
        chunk_uuids = [chunk['chunk_uuid'] for chunk in chunks]
        redis_mgr.set_cached(chunks_list_key, chunk_uuids, ttl=3600)
        
        # Cache individual chunk texts
        for chunk in chunks:
            chunk_text_key = CacheKeys.format_key(CacheKeys.DOC_CHUNK_TEXT, chunk_uuid=chunk['chunk_uuid'])
            redis_mgr.set_cached(chunk_text_key, chunk['text'], ttl=3600)
            chunk_cache_keys.append(chunk_text_key)
        
        # Cache some entity data
        entity_key = CacheKeys.format_key(CacheKeys.DOC_ALL_EXTRACTED_MENTIONS, document_uuid=source_doc_uuid)
        redis_mgr.set_cached(entity_key, [{'entity': 'test', 'type': 'TEST'}], ttl=3600)
        
        logger.info(f"✓ Added {len(chunk_cache_keys)} chunk-specific cache entries")
        
        # Step 5: Verify all caches exist
        logger.info("\nTest 4: Verifying cache entries exist")
        cache_exists = {
            'ocr': redis_client.exists(ocr_key),
            'cleaned_text': redis_client.exists(cleaned_text_key),
            'state': redis_client.exists(state_key),
            'chunks_list': redis_client.exists(chunks_list_key),
            'entity_mentions': redis_client.exists(entity_key),
            'chunk_texts': sum(redis_client.exists(key) for key in chunk_cache_keys)
        }
        
        logger.info(f"Cache status before cleanup: {cache_exists}")
        if not all(v > 0 for v in cache_exists.values() if isinstance(v, int)):
            logger.error("✗ Not all expected caches were created")
            return False
        logger.info("✓ All cache entries verified")
        
        # Step 6: Run cleanup with preserve_ocr=True
        logger.info("\nTest 5: Running cleanup with preserve_ocr=True")
        cleanup_result = cleanup_document_for_reprocessing_sync(
            db_manager=db_manager,
            document_uuid=source_doc_uuid,
            stages_to_clean=['chunks', 'entities'],
            preserve_ocr=True
        )
        logger.info(f"Cleanup result: {cleanup_result}")
        
        # Step 7: Verify cache invalidation
        logger.info("\nTest 6: Verifying cache invalidation")
        cache_after = {
            'ocr': redis_client.exists(ocr_key),  # Should be preserved
            'cleaned_text': redis_client.exists(cleaned_text_key),  # Should be cleared
            'state': redis_client.exists(state_key),  # Should be cleared
            'chunks_list': redis_client.exists(chunks_list_key),  # Should be cleared
            'entity_mentions': redis_client.exists(entity_key),  # Should be cleared
            'chunk_texts': sum(redis_client.exists(key) for key in chunk_cache_keys)  # Should be 0
        }
        
        logger.info(f"Cache status after cleanup: {cache_after}")
        
        # Verify OCR was preserved
        if cache_after['ocr'] == 0:
            logger.error("✗ FAILED: OCR cache was not preserved")
            return False
        else:
            logger.info("✓ SUCCESS: OCR cache was preserved")
        
        # Verify other caches were cleared
        cleared_caches = ['cleaned_text', 'state', 'chunks_list', 'entity_mentions']
        for cache_name in cleared_caches:
            if cache_after[cache_name] > 0:
                logger.error(f"✗ FAILED: {cache_name} cache was not cleared")
                return False
        
        if cache_after['chunk_texts'] > 0:
            logger.error(f"✗ FAILED: {cache_after['chunk_texts']} chunk text caches were not cleared")
            return False
        
        logger.info("✓ SUCCESS: All non-OCR caches were properly cleared")
        
        # Step 8: Test cleanup without preserve_ocr
        logger.info("\nTest 7: Running cleanup without preserve_ocr")
        
        # Re-add OCR cache
        redis_mgr.set_cached(ocr_key, {'text': test_text, 'metadata': {}}, ttl=3600)
        
        cleanup_result2 = cleanup_document_for_reprocessing_sync(
            db_manager=db_manager,
            document_uuid=source_doc_uuid,
            stages_to_clean=['ocr'],
            preserve_ocr=False
        )
        
        # Verify OCR cache was cleared
        if redis_client.exists(ocr_key) > 0:
            logger.error("✗ FAILED: OCR cache was not cleared when preserve_ocr=False")
            return False
        else:
            logger.info("✓ SUCCESS: OCR cache was cleared when preserve_ocr=False")
        
        logger.info("\n✓ ALL TESTS PASSED!")
        return True
        
    except Exception as e:
        logger.error(f"Test failed with error: {e}", exc_info=True)
        return False
    finally:
        # Cleanup test data
        logger.info("\nCleaning up test data...")
        try:
            # Clear any remaining Redis keys
            patterns = CacheKeys.get_all_document_patterns(source_doc_uuid)
            for pattern in patterns:
                for key in redis_client.keys(pattern):
                    redis_client.delete(key)
            
            # Delete chunks
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
    success = test_chunk_cache_invalidation()
    sys.exit(0 if success else 1)