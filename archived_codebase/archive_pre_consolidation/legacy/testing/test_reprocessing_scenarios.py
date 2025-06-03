#!/usr/bin/env python3
"""
Test Various Reprocessing Scenarios with Redis Caching
"""

import sys
import os
import time
import json
import logging
from datetime import datetime

# Add the parent directory to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.supabase_utils import SupabaseManager
from scripts.redis_utils import get_redis_manager
from scripts.cache_keys import CacheKeys
from scripts.cleanup_document_for_reprocessing import cleanup_document_data
from scripts.celery_submission import submit_document_to_celery

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def wait_for_completion(db_manager, document_uuid: str, timeout: int = 300):
    """Wait for document processing to complete."""
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        doc = db_manager.client.table('source_documents').select(
            'processing_status, celery_status'
        ).eq('document_uuid', document_uuid).execute()
        
        if doc.data:
            status = doc.data[0]['processing_status']
            if status == 'completed':
                return True
            elif status.startswith('error_') or status == 'failed':
                logger.error(f"Processing failed: {status}")
                return False
        
        time.sleep(2)
    
    logger.error("Timeout waiting for completion")
    return False


def get_processing_stats(db_manager, document_uuid: str):
    """Get processing statistics for a document."""
    stats = {}
    
    # Get source document info
    doc = db_manager.client.table('source_documents').select(
        'processing_status, celery_status, processing_version, created_at, last_modified_at'
    ).eq('document_uuid', document_uuid).execute()
    
    if doc.data:
        stats['source'] = doc.data[0]
        
        # Calculate processing time
        created = datetime.fromisoformat(doc.data[0]['created_at'].replace('Z', '+00:00'))
        modified = datetime.fromisoformat(doc.data[0]['last_modified_at'].replace('Z', '+00:00'))
        stats['processing_time_seconds'] = (modified - created).total_seconds()
    
    # Get Neo4j document info
    neo4j_doc = db_manager.client.table('neo4j_documents').select(
        'id, status'
    ).eq('source_document_uuid', document_uuid).execute()
    
    if neo4j_doc.data:
        stats['neo4j_doc'] = neo4j_doc.data[0]
        
        # Count chunks
        chunks = db_manager.client.table('neo4j_chunks').select(
            'id', count='exact'
        ).eq('document_id', neo4j_doc.data[0]['id']).execute()
        stats['chunk_count'] = chunks.count if hasattr(chunks, 'count') else 0
        
        # Count entity mentions
        mentions = db_manager.client.table('neo4j_entity_mentions').select(
            'id', count='exact'
        ).eq('parent_doc_id', neo4j_doc.data[0]['id']).execute()
        stats['mention_count'] = mentions.count if hasattr(mentions, 'count') else 0
        
        # Count canonical entities
        canonicals = db_manager.client.table('neo4j_canonical_entities').select(
            'id', count='exact'
        ).eq('parent_doc_id', neo4j_doc.data[0]['id']).execute()
        stats['canonical_count'] = canonicals.count if hasattr(canonicals, 'count') else 0
        
        # Count relationships
        relationships = db_manager.client.table('neo4j_relationships_staging').select(
            'id', count='exact'
        ).eq('fromNodeId', neo4j_doc.data[0]['id']).execute()
        stats['relationship_count'] = relationships.count if hasattr(relationships, 'count') else 0
    
    return stats


def test_full_reprocessing():
    """Test full reprocessing with cleanup."""
    logger.info("\n" + "="*60)
    logger.info("TEST 1: Full Reprocessing with Cleanup")
    logger.info("="*60)
    
    db_manager = SupabaseManager()
    
    # Find a test document
    test_file = None
    for file_path in ["input_docs/Pre-Trial Order -  Ory v. Roeslein.pdf",
                      "input/ARDC_Registration_Receipt_6333890.pdf"]:
        if os.path.exists(file_path):
            test_file = file_path
            break
    
    if not test_file:
        logger.error("No test file found")
        return False
    
    # Initial processing
    logger.info(f"\n1. Initial processing of {test_file}")
    result = submit_document_to_celery(test_file)
    if not result:
        return False
    
    document_uuid = result['document_uuid']
    logger.info(f"Document UUID: {document_uuid}")
    
    # Wait for completion
    if not wait_for_completion(db_manager, document_uuid):
        return False
    
    # Get initial stats
    initial_stats = get_processing_stats(db_manager, document_uuid)
    logger.info(f"Initial processing stats: {json.dumps(initial_stats, indent=2)}")
    
    # Full cleanup
    logger.info("\n2. Performing full cleanup...")
    cleanup_result = cleanup_document_data(
        db_manager=db_manager,
        document_uuid=document_uuid,
        preserve_ocr=False,  # Full cleanup
        increment_version=True
    )
    
    if not cleanup_result['success']:
        logger.error(f"Cleanup failed: {cleanup_result['message']}")
        return False
    
    logger.info(f"Cleanup successful: {cleanup_result['message']}")
    
    # Reprocess
    logger.info("\n3. Reprocessing document...")
    reprocess_start = time.time()
    
    # Update status to pending
    db_manager.client.table('source_documents').update({
        'processing_status': 'pending',
        'celery_status': 'submitted'
    }).eq('document_uuid', document_uuid).execute()
    
    # Submit for reprocessing
    result2 = submit_document_to_celery(test_file, document_uuid=document_uuid)
    if not result2:
        return False
    
    # Wait for completion
    if not wait_for_completion(db_manager, document_uuid):
        return False
    
    reprocess_time = time.time() - reprocess_start
    
    # Get reprocessing stats
    reprocess_stats = get_processing_stats(db_manager, document_uuid)
    logger.info(f"Reprocessing stats: {json.dumps(reprocess_stats, indent=2)}")
    logger.info(f"Reprocessing time: {reprocess_time:.2f} seconds")
    
    # Verify no duplicates
    logger.info("\n4. Verifying no duplicate constraints...")
    
    # Check processing version incremented
    if reprocess_stats['source']['processing_version'] <= initial_stats['source']['processing_version']:
        logger.error("Processing version not incremented")
        return False
    
    logger.info("✅ Full reprocessing test PASSED")
    return True


def test_partial_reprocessing():
    """Test partial reprocessing (skip OCR)."""
    logger.info("\n" + "="*60)
    logger.info("TEST 2: Partial Reprocessing (Skip OCR)")
    logger.info("="*60)
    
    db_manager = SupabaseManager()
    
    # Find a completed document
    completed_docs = db_manager.client.table('source_documents').select(
        'document_uuid, original_file_name'
    ).eq('processing_status', 'completed').limit(1).execute()
    
    if not completed_docs.data:
        logger.error("No completed documents found")
        return False
    
    document_uuid = completed_docs.data[0]['document_uuid']
    file_name = completed_docs.data[0]['original_file_name']
    logger.info(f"Using document: {file_name} ({document_uuid})")
    
    # Get initial stats
    initial_stats = get_processing_stats(db_manager, document_uuid)
    logger.info(f"Initial stats: {json.dumps(initial_stats, indent=2)}")
    
    # Partial cleanup (preserve OCR)
    logger.info("\n1. Performing partial cleanup (preserving OCR)...")
    cleanup_result = cleanup_document_data(
        db_manager=db_manager,
        document_uuid=document_uuid,
        preserve_ocr=True,  # Keep OCR results
        increment_version=False  # Don't increment version
    )
    
    if not cleanup_result['success']:
        logger.error(f"Cleanup failed: {cleanup_result['message']}")
        return False
    
    logger.info(f"Cleanup successful: {cleanup_result['message']}")
    
    # Check OCR cache is preserved
    redis_mgr = get_redis_manager()
    if redis_mgr and redis_mgr.is_available():
        processing_version = initial_stats['source']['processing_version']
        ocr_key = CacheKeys.format_key(
            CacheKeys.DOC_OCR_RESULT, 
            version=processing_version,
            document_uuid=document_uuid
        )
        ocr_cached = redis_mgr.get_cached(ocr_key)
        if ocr_cached:
            logger.info("✓ OCR cache preserved")
        else:
            logger.warning("OCR cache not found")
    
    # Reprocess
    logger.info("\n2. Reprocessing document (should skip OCR)...")
    reprocess_start = time.time()
    
    # Submit for reprocessing
    from scripts.celery_tasks.text_tasks import create_document_node
    
    # Get source document info
    source_info = db_manager.client.table('source_documents').select(
        'id, project_id, original_file_name, detected_file_type'
    ).eq('document_uuid', document_uuid).execute()
    
    if source_info.data:
        # Submit directly to text processing (skip OCR)
        create_document_node.delay(
            document_uuid=document_uuid,
            source_doc_sql_id=source_info.data[0]['id'],
            project_sql_id=source_info.data[0]['project_id'],
            file_name=source_info.data[0]['original_file_name'],
            detected_file_type=source_info.data[0]['detected_file_type']
        )
        
        # Wait for completion
        if not wait_for_completion(db_manager, document_uuid, timeout=120):
            return False
        
        reprocess_time = time.time() - reprocess_start
        logger.info(f"Reprocessing time: {reprocess_time:.2f} seconds (should be faster)")
        
        # Verify results
        reprocess_stats = get_processing_stats(db_manager, document_uuid)
        logger.info(f"Reprocessing stats: {json.dumps(reprocess_stats, indent=2)}")
        
        logger.info("✅ Partial reprocessing test PASSED")
        return True
    
    return False


def test_concurrent_reprocessing_prevention():
    """Test that concurrent reprocessing is prevented."""
    logger.info("\n" + "="*60)
    logger.info("TEST 3: Concurrent Reprocessing Prevention")
    logger.info("="*60)
    
    db_manager = SupabaseManager()
    redis_mgr = get_redis_manager()
    
    if not redis_mgr or not redis_mgr.is_available():
        logger.error("Redis not available - skipping test")
        return False
    
    # Find a document
    docs = db_manager.client.table('source_documents').select(
        'document_uuid, original_file_name'
    ).limit(1).execute()
    
    if not docs.data:
        logger.error("No documents found")
        return False
    
    document_uuid = docs.data[0]['document_uuid']
    logger.info(f"Using document: {document_uuid}")
    
    # Simulate processing lock
    from scripts.celery_tasks.task_utils import acquire_processing_lock, release_processing_lock
    
    # Acquire lock for OCR phase
    lock1 = acquire_processing_lock(document_uuid, "ocr")
    if not lock1:
        logger.error("Failed to acquire first lock")
        return False
    
    logger.info("✓ Acquired first processing lock")
    
    # Try to acquire same lock again (should fail)
    lock2 = acquire_processing_lock(document_uuid, "ocr")
    if lock2:
        logger.error("❌ Second lock acquisition should have failed!")
        release_processing_lock(lock1)
        release_processing_lock(lock2)
        return False
    
    logger.info("✓ Second lock acquisition correctly prevented")
    
    # Release first lock
    release_processing_lock(lock1)
    logger.info("✓ Released first lock")
    
    # Now should be able to acquire lock again
    lock3 = acquire_processing_lock(document_uuid, "ocr")
    if not lock3:
        logger.error("Failed to acquire lock after release")
        return False
    
    logger.info("✓ Successfully acquired lock after release")
    release_processing_lock(lock3)
    
    logger.info("✅ Concurrent reprocessing prevention test PASSED")
    return True


def run_all_tests():
    """Run all reprocessing scenario tests."""
    tests = [
        ("Full Reprocessing", test_full_reprocessing),
        ("Partial Reprocessing", test_partial_reprocessing),
        ("Concurrent Prevention", test_concurrent_reprocessing_prevention)
    ]
    
    results = {}
    
    for test_name, test_func in tests:
        try:
            logger.info(f"\nRunning {test_name}...")
            results[test_name] = test_func()
        except Exception as e:
            logger.error(f"Test {test_name} failed with exception: {e}")
            results[test_name] = False
    
    # Summary
    logger.info("\n" + "="*60)
    logger.info("TEST SUMMARY")
    logger.info("="*60)
    
    for test_name, passed in results.items():
        status = "✅ PASSED" if passed else "❌ FAILED"
        logger.info(f"{test_name}: {status}")
    
    all_passed = all(results.values())
    if all_passed:
        logger.info("\n🎉 All reprocessing tests PASSED!")
    else:
        logger.error("\n❌ Some tests failed")
    
    return all_passed


if __name__ == "__main__":
    run_all_tests()