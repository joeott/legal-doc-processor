#!/usr/bin/env python3
"""Test script to verify chunk list Redis caching works correctly"""
import os
import sys
import logging
import uuid
from datetime import datetime
from scripts.supabase_utils import SupabaseManager
from scripts.celery_tasks.idempotent_ops import IdempotentDatabaseOps
from scripts.redis_utils import get_redis_manager, CacheKeys
from scripts.config import REDIS_CHUNK_CACHE_TTL

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def process_chunking_sync(document_uuid: str, source_doc_sql_id: int,
                         neo4j_doc_sql_id: int, neo4j_doc_uuid: str,
                         cleaned_text: str, ocr_meta_json: str,
                         doc_category: str):
    """Synchronous version of process_chunking for testing"""
    from scripts.celery_tasks import text_tasks
    
    # Call the task directly, bypassing Celery
    # Note: Function signature is (document_uuid, neo4j_doc_sql_id, neo4j_doc_uuid, cleaned_text, ocr_meta_json, doc_category, source_doc_sql_id)
    task = text_tasks.process_chunking
    return task.run(document_uuid, neo4j_doc_sql_id, neo4j_doc_uuid, 
                   cleaned_text, ocr_meta_json, doc_category, source_doc_sql_id)

def test_chunk_list_caching():
    """Test that chunk list is properly cached in Redis"""
    db_manager = SupabaseManager()
    idempotent_ops = IdempotentDatabaseOps(db_manager)
    redis_mgr = get_redis_manager()
    
    if not redis_mgr or not redis_mgr.is_available():
        logger.error("Redis is not available. Cannot test chunk list caching.")
        return False
    
    redis_client = redis_mgr.get_client()
    
    # Test data
    test_project_uuid = str(uuid.uuid4())
    test_doc_name = "Test Chunk List Caching Document"
    test_text = """This is a test document for chunk list caching.

## First Section
This section contains important information that will be chunked.
We need enough content to create multiple chunks for testing.

## Second Section
More content goes here to ensure we have at least two chunks.
The chunk list should be cached in Redis after processing.

## Third Section
Final section with additional content for testing purposes.
This ensures we have sufficient text for meaningful chunking."""
    
    try:
        # Step 0: Create test project and documents
        logger.info("Creating test project and documents...")
        project_result = db_manager.client.table('projects').insert({
            'projectId': test_project_uuid,
            'name': 'Test Chunk List Caching Project'
        }).execute()
        test_project_id = project_result.data[0]['id']
        
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
        
        # Step 1: Clear any existing cache for this document
        logger.info("\nTest 1: Ensuring clean cache state")
        chunks_list_key = CacheKeys.format_key(CacheKeys.DOC_CHUNKS_LIST, document_uuid=source_doc_uuid)
        redis_client.delete(chunks_list_key)
        
        if redis_client.exists(chunks_list_key) == 0:
            logger.info("✓ Cache is clean before test")
        else:
            logger.error("✗ Failed to clear cache")
            return False
        
        # Step 2: Process chunking
        logger.info("\nTest 2: Processing document chunks")
        result = process_chunking_sync(
            document_uuid=source_doc_uuid,
            source_doc_sql_id=source_doc_id,
            neo4j_doc_sql_id=neo4j_doc_id,
            neo4j_doc_uuid=neo4j_doc_uuid,
            cleaned_text=test_text,
            ocr_meta_json=None,  # Pass None instead of empty JSON
            doc_category='document'
        )
        
        logger.info(f"Chunking result: {result}")
        
        # Step 3: Verify chunk list was cached
        logger.info("\nTest 3: Verifying chunk list cache")
        if redis_client.exists(chunks_list_key) == 0:
            logger.error("✗ FAILED: Chunk list was not cached")
            return False
        
        cached_chunk_uuids = redis_mgr.get_cached(chunks_list_key)
        if not cached_chunk_uuids:
            logger.error("✗ FAILED: Cached chunk list is empty")
            return False
        
        logger.info(f"✓ SUCCESS: Found {len(cached_chunk_uuids)} chunks in cache")
        logger.info(f"Cached chunk UUIDs: {cached_chunk_uuids}")
        
        # Step 4: Verify individual chunk texts were cached
        logger.info("\nTest 4: Verifying individual chunk text caches")
        cached_chunk_count = 0
        for chunk_uuid in cached_chunk_uuids:
            chunk_text_key = CacheKeys.format_key(CacheKeys.DOC_CHUNK_TEXT, chunk_uuid=chunk_uuid)
            if redis_client.exists(chunk_text_key) > 0:
                cached_text = redis_mgr.get_cached(chunk_text_key)
                if cached_text:
                    cached_chunk_count += 1
                    logger.info(f"✓ Chunk {chunk_uuid}: {len(cached_text)} chars cached")
        
        if cached_chunk_count == len(cached_chunk_uuids):
            logger.info(f"✓ SUCCESS: All {cached_chunk_count} chunk texts were cached")
        else:
            logger.error(f"✗ FAILED: Only {cached_chunk_count}/{len(cached_chunk_uuids)} chunk texts were cached")
            return False
        
        # Step 5: Verify cache TTL
        logger.info("\nTest 5: Verifying cache TTL")
        ttl = redis_client.ttl(chunks_list_key)
        if ttl > 0:
            logger.info(f"✓ SUCCESS: Chunk list cache TTL is {ttl} seconds")
            if ttl <= REDIS_CHUNK_CACHE_TTL:
                logger.info(f"✓ TTL is within expected range (max {REDIS_CHUNK_CACHE_TTL} seconds)")
            else:
                logger.warning(f"⚠ TTL ({ttl}) exceeds expected max ({REDIS_CHUNK_CACHE_TTL})")
        else:
            logger.error("✗ FAILED: No TTL set on chunk list cache")
            return False
        
        # Step 6: Verify cached data matches database
        logger.info("\nTest 6: Verifying cache consistency with database")
        db_chunks = db_manager.client.table('neo4j_chunks').select(
            'chunkId', 'chunkIndex'
        ).eq('document_id', neo4j_doc_id).order('chunkIndex').execute()
        
        db_chunk_uuids = [chunk['chunkId'] for chunk in db_chunks.data]
        
        if set(cached_chunk_uuids) == set(db_chunk_uuids):
            logger.info("✓ SUCCESS: Cached chunk list matches database")
        else:
            logger.error("✗ FAILED: Cache-database mismatch")
            logger.error(f"Cached: {cached_chunk_uuids}")
            logger.error(f"Database: {db_chunk_uuids}")
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
            # Clear Redis caches
            if redis_mgr:
                patterns = CacheKeys.get_all_document_patterns(source_doc_uuid)
                for pattern in patterns:
                    for key in redis_client.keys(pattern):
                        redis_client.delete(key)
                
                # Also clear chunk text caches
                if 'cached_chunk_uuids' in locals():
                    for chunk_uuid in cached_chunk_uuids:
                        chunk_text_key = CacheKeys.format_key(CacheKeys.DOC_CHUNK_TEXT, chunk_uuid=chunk_uuid)
                        redis_client.delete(chunk_text_key)
            
            # Delete database records
            if 'neo4j_doc_id' in locals():
                db_manager.client.table('neo4j_chunks').delete().eq('document_id', neo4j_doc_id).execute()
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
    import json  # Import needed for the sync function
    success = test_chunk_list_caching()
    sys.exit(0 if success else 1)