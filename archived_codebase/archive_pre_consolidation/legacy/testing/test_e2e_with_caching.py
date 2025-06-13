#!/usr/bin/env python3
"""
End-to-End Test with Redis Caching and Optimizations
Tests the full pipeline with all caching and idempotency features.
"""

import sys
import os
import time
from datetime import datetime
import json
import logging

# Add the parent directory to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.supabase_utils import SupabaseManager
from scripts.celery_submission import submit_document_to_celery
from scripts.redis_utils import get_redis_manager
from scripts.cache_keys import CacheKeys

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def check_cache_status(document_uuid: str, processing_version: int = 1):
    """Check what's cached for a document."""
    redis_mgr = get_redis_manager()
    if not redis_mgr or not redis_mgr.is_available():
        logger.warning("Redis not available")
        return {}
    
    cache_status = {}
    
    # Check OCR result
    ocr_key = CacheKeys.format_key(CacheKeys.DOC_OCR_RESULT, version=processing_version, document_uuid=document_uuid)
    ocr_data = redis_mgr.get_cached(ocr_key)
    cache_status['ocr'] = bool(ocr_data)
    
    # Check cleaned text
    cleaned_key = CacheKeys.format_key(CacheKeys.DOC_CLEANED_TEXT, version=processing_version, document_uuid=document_uuid)
    cleaned_data = redis_mgr.get_cached(cleaned_key)
    cache_status['cleaned_text'] = bool(cleaned_data)
    
    # Check chunks list
    chunks_key = CacheKeys.format_key(CacheKeys.DOC_CHUNKS_LIST, version=processing_version, document_uuid=document_uuid)
    chunks_data = redis_mgr.get_cached(chunks_key)
    cache_status['chunks'] = len(chunks_data) if chunks_data else 0
    
    # Check entity mentions
    mentions_key = CacheKeys.format_key(CacheKeys.DOC_ALL_EXTRACTED_MENTIONS, version=processing_version, document_uuid=document_uuid)
    mentions_data = redis_mgr.get_cached(mentions_key)
    cache_status['mentions'] = len(mentions_data) if mentions_data else 0
    
    # Check canonical entities
    canonical_key = CacheKeys.format_key(CacheKeys.DOC_CANONICAL_ENTITIES, version=processing_version, document_uuid=document_uuid)
    canonical_data = redis_mgr.get_cached(canonical_key)
    cache_status['canonical_entities'] = len(canonical_data) if canonical_data else 0
    
    # Check document state
    state_key = CacheKeys.format_key(CacheKeys.DOC_STATE, document_uuid=document_uuid)
    state_data = redis_mgr.hgetall(state_key)
    cache_status['state'] = state_data
    
    return cache_status


def monitor_document_progress(db_manager, document_uuid: str, timeout: int = 600):
    """Monitor document processing progress."""
    start_time = time.time()
    last_status = None
    last_stage = None
    
    logger.info(f"Monitoring document {document_uuid}")
    
    while time.time() - start_time < timeout:
        try:
            # Get document status
            doc = db_manager.client.table('source_documents').select(
                'processing_status, celery_status, processing_version'
            ).eq('document_uuid', document_uuid).execute()
            
            if not doc.data:
                logger.error(f"Document {document_uuid} not found")
                return False
            
            current_status = doc.data[0]['processing_status']
            celery_status = doc.data[0]['celery_status']
            processing_version = doc.data[0].get('processing_version', 1)
            
            # Check if status changed
            if current_status != last_status or celery_status != last_stage:
                elapsed = int(time.time() - start_time)
                logger.info(f"[{elapsed}s] Status: {current_status}, Stage: {celery_status}")
                
                # Check cache status
                cache_status = check_cache_status(document_uuid, processing_version)
                logger.info(f"Cache status: {json.dumps(cache_status, indent=2)}")
                
                last_status = current_status
                last_stage = celery_status
            
            # Check if completed or failed
            if current_status == 'completed':
                logger.info(f"✅ Document processing completed in {int(time.time() - start_time)} seconds")
                
                # Final cache check
                final_cache = check_cache_status(document_uuid, processing_version)
                logger.info(f"Final cache status: {json.dumps(final_cache, indent=2)}")
                
                # Check Neo4j readiness
                neo4j_doc = db_manager.client.table('neo4j_documents').select(
                    'id, status'
                ).eq('source_document_uuid', document_uuid).execute()
                
                if neo4j_doc.data:
                    neo4j_status = neo4j_doc.data[0]['status']
                    logger.info(f"Neo4j document status: {neo4j_status}")
                    
                    # Count relationships
                    rel_count = db_manager.client.table('neo4j_relationships_staging').select(
                        'id', count='exact'
                    ).eq('fromNodeId', neo4j_doc.data[0]['id']).execute()
                    
                    if hasattr(rel_count, 'count'):
                        logger.info(f"Relationships staged: {rel_count.count}")
                
                return True
                
            elif current_status.startswith('error_') or current_status == 'failed':
                logger.error(f"❌ Document processing failed: {current_status}")
                return False
            
            # Wait before next check
            time.sleep(2)
            
        except Exception as e:
            logger.error(f"Error monitoring document: {e}")
            time.sleep(5)
    
    logger.error(f"⏱️ Timeout after {timeout} seconds")
    return False


def test_full_pipeline():
    """Test the full pipeline with a sample document."""
    db_manager = SupabaseManager()
    
    # Select a test file
    test_files = [
        "input_docs/Pre-Trial Order -  Ory v. Roeslein.pdf",
        "input/ali auto body - check .pdf",
        "input/ARDC_Registration_Receipt_6333890.pdf"
    ]
    
    test_file = None
    for file_path in test_files:
        if os.path.exists(file_path):
            test_file = file_path
            break
    
    if not test_file:
        logger.error("No test file found")
        return False
    
    logger.info(f"\n{'='*60}")
    logger.info(f"Testing full pipeline with: {test_file}")
    logger.info(f"{'='*60}\n")
    
    # Submit document
    result = submit_document_to_celery(test_file)
    
    if not result or 'document_uuid' not in result:
        logger.error("Failed to submit document")
        return False
    
    document_uuid = result['document_uuid']
    logger.info(f"Document submitted: {document_uuid}")
    logger.info(f"Initial cache check:")
    initial_cache = check_cache_status(document_uuid)
    logger.info(json.dumps(initial_cache, indent=2))
    
    # Monitor progress
    success = monitor_document_progress(db_manager, document_uuid)
    
    if success:
        logger.info("\n✅ End-to-end test PASSED")
        
        # Test reprocessing (should use cache)
        logger.info(f"\n{'='*60}")
        logger.info("Testing reprocessing with cache...")
        logger.info(f"{'='*60}\n")
        
        # Update processing status to trigger reprocessing
        db_manager.client.table('source_documents').update({
            'processing_status': 'pending',
            'celery_status': 'submitted'
        }).eq('document_uuid', document_uuid).execute()
        
        # Submit again
        result2 = submit_document_to_celery(test_file, document_uuid=document_uuid)
        if result2:
            logger.info("Reprocessing submitted, monitoring...")
            success2 = monitor_document_progress(db_manager, document_uuid, timeout=120)
            
            if success2:
                logger.info("✅ Reprocessing test PASSED (should be faster with cache)")
            else:
                logger.error("❌ Reprocessing test FAILED")
    else:
        logger.error("\n❌ End-to-end test FAILED")
    
    return success


if __name__ == "__main__":
    test_full_pipeline()