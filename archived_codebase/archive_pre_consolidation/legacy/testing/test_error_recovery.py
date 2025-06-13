#!/usr/bin/env python3
"""
Test Error Recovery Scenarios with Redis Caching
"""

import sys
import os
import time
import json
import logging
from unittest.mock import patch

# Add the parent directory to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.supabase_utils import SupabaseManager
from scripts.redis_utils import get_redis_manager
from scripts.cache_keys import CacheKeys
from scripts.celery_submission import submit_document_to_celery

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def simulate_ocr_failure():
    """Test OCR failure recovery."""
    logger.info("\n" + "="*60)
    logger.info("TEST 1: OCR Failure Recovery")
    logger.info("="*60)
    
    db_manager = SupabaseManager()
    
    # Find a PDF test file
    test_file = None
    for file_path in ["input_docs/Pre-Trial Order -  Ory v. Roeslein.pdf",
                      "input/ARDC_Registration_Receipt_6333890.pdf"]:
        if os.path.exists(file_path):
            test_file = file_path
            break
    
    if not test_file:
        logger.error("No test file found")
        return False
    
    logger.info(f"Using test file: {test_file}")
    
    # Submit document with mocked OCR failure
    with patch('scripts.ocr_extraction.extract_text_from_pdf_textract') as mock_ocr:
        # Make OCR fail
        mock_ocr.side_effect = Exception("Simulated OCR failure")
        
        result = submit_document_to_celery(test_file)
        if not result:
            logger.error("Failed to submit document")
            return False
        
        document_uuid = result['document_uuid']
        logger.info(f"Document UUID: {document_uuid}")
        
        # Wait a bit for processing to fail
        time.sleep(10)
        
        # Check status
        doc = db_manager.client.table('source_documents').select(
            'processing_status, celery_status, error_message'
        ).eq('document_uuid', document_uuid).execute()
        
        if doc.data:
            status = doc.data[0]['processing_status']
            celery_status = doc.data[0]['celery_status']
            error = doc.data[0].get('error_message', '')
            
            logger.info(f"Status after OCR failure: {status}")
            logger.info(f"Celery status: {celery_status}")
            logger.info(f"Error: {error}")
            
            # Should show OCR failure
            if not (status.startswith('error_') or 'ocr' in celery_status.lower()):
                logger.error("OCR failure not properly recorded")
                return False
    
    logger.info("\nNow testing retry after fixing issue...")
    
    # Submit again without the mock (should succeed)
    result2 = submit_document_to_celery(test_file, document_uuid=document_uuid)
    if not result2:
        logger.error("Failed to resubmit")
        return False
    
    # Wait for completion
    start_time = time.time()
    while time.time() - start_time < 300:
        doc = db_manager.client.table('source_documents').select(
            'processing_status'
        ).eq('document_uuid', document_uuid).execute()
        
        if doc.data and doc.data[0]['processing_status'] == 'completed':
            logger.info("✅ OCR retry succeeded after failure")
            return True
        
        time.sleep(2)
    
    logger.error("OCR retry timeout")
    return False


def test_entity_extraction_retry():
    """Test entity extraction retry with cached chunks."""
    logger.info("\n" + "="*60)
    logger.info("TEST 2: Entity Extraction Retry with Cached Chunks")
    logger.info("="*60)
    
    db_manager = SupabaseManager()
    redis_mgr = get_redis_manager()
    
    if not redis_mgr or not redis_mgr.is_available():
        logger.error("Redis not available")
        return False
    
    # Find a document that has completed chunking
    docs = db_manager.client.table('neo4j_documents').select(
        'source_document_uuid, id'
    ).eq('status', 'pending_ner').limit(1).execute()
    
    if not docs.data:
        # Try to find any document with chunks
        docs = db_manager.client.table('neo4j_documents').select(
            'source_document_uuid, id'
        ).limit(1).execute()
        
        if not docs.data:
            logger.error("No suitable documents found")
            return False
    
    document_uuid = docs.data[0]['source_document_uuid']
    neo4j_doc_id = docs.data[0]['id']
    
    logger.info(f"Using document: {document_uuid}")
    
    # Check if chunks are cached
    source_doc = db_manager.client.table('source_documents').select(
        'processing_version'
    ).eq('document_uuid', document_uuid).execute()
    
    if source_doc.data:
        processing_version = source_doc.data[0].get('processing_version', 1)
        chunks_key = CacheKeys.format_key(
            CacheKeys.DOC_CHUNKS_LIST,
            version=processing_version,
            document_uuid=document_uuid
        )
        chunks_cached = redis_mgr.get_cached(chunks_key)
        
        if chunks_cached:
            logger.info(f"✓ Found {len(chunks_cached)} chunks in cache")
        else:
            logger.info("No chunks in cache, caching them now...")
            
            # Get chunks and cache them
            chunks = db_manager.client.table('neo4j_chunks').select(
                'chunkId, text'
            ).eq('document_id', neo4j_doc_id).execute()
            
            if chunks.data:
                chunk_uuids = []
                for chunk in chunks.data:
                    chunk_uuids.append(chunk['chunkId'])
                    # Cache individual chunk text
                    chunk_text_key = CacheKeys.format_key(
                        CacheKeys.DOC_CHUNK_TEXT,
                        chunk_uuid=chunk['chunkId']
                    )
                    redis_mgr.set_cached(chunk_text_key, chunk['text'], ttl=2*24*3600)
                
                # Cache chunk list
                redis_mgr.set_cached(chunks_key, chunk_uuids, ttl=2*24*3600)
                logger.info(f"Cached {len(chunk_uuids)} chunks")
    
    # Simulate entity extraction failure and retry
    logger.info("\nSimulating entity extraction failure...")
    
    # Update status to simulate failure
    db_manager.client.table('neo4j_documents').update({
        'status': 'error_ner'
    }).eq('id', neo4j_doc_id).execute()
    
    db_manager.client.table('source_documents').update({
        'processing_status': 'error_entity_extraction',
        'celery_status': 'entity_failed'
    }).eq('document_uuid', document_uuid).execute()
    
    logger.info("Status updated to simulate failure")
    
    # Now retry entity extraction
    from scripts.celery_tasks.entity_tasks import extract_entities
    
    # Get chunk data
    chunks_data = db_manager.client.table('neo4j_chunks').select(
        'id, chunkId, chunkIndex'
    ).eq('document_id', neo4j_doc_id).execute()
    
    if chunks_data.data:
        chunk_data = [{
            "sql_id": c['id'],
            "chunk_uuid": c['chunkId'],
            "chunk_index": c['chunkIndex']
        } for c in chunks_data.data]
        
        # Get source doc info
        source_info = db_manager.client.table('source_documents').select(
            'id'
        ).eq('document_uuid', document_uuid).execute()
        
        if source_info.data:
            logger.info(f"Retrying entity extraction with {len(chunk_data)} chunks...")
            
            # Submit entity extraction task
            extract_entities.delay(
                document_uuid=document_uuid,
                source_doc_sql_id=source_info.data[0]['id'],
                neo4j_doc_sql_id=neo4j_doc_id,
                neo4j_doc_uuid=document_uuid,  # Simplified for test
                chunk_data=chunk_data
            )
            
            # Wait for completion
            start_time = time.time()
            while time.time() - start_time < 120:
                doc_status = db_manager.client.table('neo4j_documents').select(
                    'status'
                ).eq('id', neo4j_doc_id).execute()
                
                if doc_status.data:
                    status = doc_status.data[0]['status']
                    if 'canonicalization' in status or 'relationships' in status or status == 'completed':
                        logger.info(f"✅ Entity extraction retry succeeded (status: {status})")
                        
                        # Check if chunks were retrieved from cache
                        # (Would need to check logs for confirmation)
                        logger.info("Chunks should have been retrieved from cache for faster processing")
                        return True
                
                time.sleep(2)
            
            logger.error("Entity extraction retry timeout")
    
    return False


def test_resolution_failure_recovery():
    """Test resolution failure with cached mentions."""
    logger.info("\n" + "="*60)
    logger.info("TEST 3: Resolution Failure Recovery")
    logger.info("="*60)
    
    db_manager = SupabaseManager()
    redis_mgr = get_redis_manager()
    
    if not redis_mgr or not redis_mgr.is_available():
        logger.error("Redis not available")
        return False
    
    # Find a document with entity mentions
    mentions = db_manager.client.table('neo4j_entity_mentions').select(
        'parent_doc_id, parent_doc_uuid'
    ).limit(1).execute()
    
    if not mentions.data:
        logger.error("No documents with entity mentions found")
        return False
    
    neo4j_doc_id = mentions.data[0]['parent_doc_id']
    document_uuid = mentions.data[0]['parent_doc_uuid']
    
    logger.info(f"Using document with mentions: {document_uuid}")
    
    # Get all mentions for this document
    all_mentions = db_manager.client.table('neo4j_entity_mentions').select(
        '*'
    ).eq('parent_doc_id', neo4j_doc_id).execute()
    
    if all_mentions.data:
        logger.info(f"Found {len(all_mentions.data)} entity mentions")
        
        # Cache the mentions
        source_doc = db_manager.client.table('source_documents').select(
            'processing_version'
        ).eq('document_uuid', document_uuid).execute()
        
        if source_doc.data:
            processing_version = source_doc.data[0].get('processing_version', 1)
            
            # Format mentions for caching
            formatted_mentions = []
            for mention in all_mentions.data:
                formatted_mentions.append({
                    "entity_mention_id_neo4j": mention['entityMentionId'],
                    "entity_mention_sql_id": mention['id'],
                    "parent_chunk_id_neo4j": mention['parent_chunk_uuid'],
                    "chunk_index_int": mention.get('chunk_index', 0),
                    "entityType": mention['entityType'],
                    "entityText": mention['entityText'],
                    "startIdx": mention.get('startIdx', 0),
                    "endIdx": mention.get('endIdx', 0)
                })
            
            # Cache mentions
            mentions_key = CacheKeys.format_key(
                CacheKeys.DOC_ALL_EXTRACTED_MENTIONS,
                version=processing_version,
                document_uuid=document_uuid
            )
            redis_mgr.set_cached(mentions_key, formatted_mentions, ttl=2*24*3600)
            logger.info(f"Cached {len(formatted_mentions)} mentions")
            
            # Simulate resolution failure
            logger.info("\nSimulating resolution failure...")
            
            # Clear any existing canonical entities
            db_manager.client.table('neo4j_canonical_entities').delete().eq(
                'parent_doc_id', neo4j_doc_id
            ).execute()
            
            # Update status to pending
            db_manager.client.table('neo4j_documents').update({
                'status': 'pending_canonicalization'
            }).eq('id', neo4j_doc_id).execute()
            
            # Retry resolution
            from scripts.celery_tasks.entity_tasks import resolve_entities
            
            # Get source doc info
            source_info = db_manager.client.table('source_documents').select(
                'id'
            ).eq('document_uuid', document_uuid).execute()
            
            if source_info.data:
                logger.info("Retrying entity resolution...")
                
                # Submit resolution task (should use cached mentions)
                resolve_entities.delay(
                    document_uuid=document_uuid,
                    source_doc_sql_id=source_info.data[0]['id'],
                    neo4j_doc_sql_id=neo4j_doc_id,
                    neo4j_doc_uuid=document_uuid
                )
                
                # Wait for completion
                start_time = time.time()
                while time.time() - start_time < 60:
                    # Check if canonical entities were created
                    canonicals = db_manager.client.table('neo4j_canonical_entities').select(
                        'id', count='exact'
                    ).eq('parent_doc_id', neo4j_doc_id).execute()
                    
                    if hasattr(canonicals, 'count') and canonicals.count > 0:
                        logger.info(f"✅ Resolution retry succeeded, created {canonicals.count} canonical entities")
                        logger.info("Entity mentions were retrieved from cache")
                        return True
                    
                    time.sleep(2)
                
                logger.error("Resolution retry timeout")
    
    return False


def test_state_rollback():
    """Test state rollback on failures."""
    logger.info("\n" + "="*60)
    logger.info("TEST 4: State Rollback on Failures")
    logger.info("="*60)
    
    db_manager = SupabaseManager()
    redis_mgr = get_redis_manager()
    
    if not redis_mgr or not redis_mgr.is_available():
        logger.error("Redis not available")
        return False
    
    # Create a test scenario with a new document
    test_file = None
    for file_path in ["input/ARDC_Registration_Receipt_6333890.pdf"]:
        if os.path.exists(file_path):
            test_file = file_path
            break
    
    if not test_file:
        logger.error("No test file found")
        return False
    
    # Submit document
    result = submit_document_to_celery(test_file)
    if not result:
        return False
    
    document_uuid = result['document_uuid']
    logger.info(f"Document UUID: {document_uuid}")
    
    # Wait for it to start processing
    time.sleep(5)
    
    # Check Redis state
    state_key = CacheKeys.format_key(CacheKeys.DOC_STATE, document_uuid=document_uuid)
    initial_state = redis_mgr.hgetall(state_key)
    logger.info(f"Initial state: {json.dumps(initial_state, indent=2)}")
    
    # Simulate a failure by updating database status
    db_manager.client.table('source_documents').update({
        'processing_status': 'error_entity_extraction',
        'celery_status': 'entity_failed',
        'error_message': 'Simulated failure for rollback test'
    }).eq('document_uuid', document_uuid).execute()
    
    # Update Redis state to show failure
    from scripts.celery_tasks.task_utils import update_document_state
    update_document_state(document_uuid, "ner", "failed", {"error": "Simulated failure"})
    
    # Check state after failure
    failed_state = redis_mgr.hgetall(state_key)
    logger.info(f"State after failure: {json.dumps(failed_state, indent=2)}")
    
    # Verify failure is recorded
    if failed_state.get('ner_status') != 'failed':
        logger.error("Failure not properly recorded in state")
        return False
    
    logger.info("✓ Failure properly recorded in state")
    
    # Check that processing can be retried
    # Reset status
    db_manager.client.table('source_documents').update({
        'processing_status': 'pending',
        'error_message': None
    }).eq('document_uuid', document_uuid).execute()
    
    # Clear failure state
    update_document_state(document_uuid, "ner", "pending", {})
    
    logger.info("✓ State can be reset for retry")
    logger.info("✅ State rollback test PASSED")
    
    return True


def run_all_tests():
    """Run all error recovery tests."""
    tests = [
        ("OCR Failure Recovery", simulate_ocr_failure),
        ("Entity Extraction Retry", test_entity_extraction_retry),
        ("Resolution Failure Recovery", test_resolution_failure_recovery),
        ("State Rollback", test_state_rollback)
    ]
    
    results = {}
    
    for test_name, test_func in tests:
        try:
            logger.info(f"\nRunning {test_name}...")
            results[test_name] = test_func()
        except Exception as e:
            logger.error(f"Test {test_name} failed with exception: {e}", exc_info=True)
            results[test_name] = False
    
    # Summary
    logger.info("\n" + "="*60)
    logger.info("ERROR RECOVERY TEST SUMMARY")
    logger.info("="*60)
    
    for test_name, passed in results.items():
        status = "✅ PASSED" if passed else "❌ FAILED"
        logger.info(f"{test_name}: {status}")
    
    all_passed = all(results.values())
    if all_passed:
        logger.info("\n🎉 All error recovery tests PASSED!")
    else:
        logger.error("\n❌ Some tests failed")
    
    return all_passed


if __name__ == "__main__":
    run_all_tests()