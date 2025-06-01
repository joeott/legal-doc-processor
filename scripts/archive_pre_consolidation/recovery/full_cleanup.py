#!/usr/bin/env python3
"""
Full cleanup script to reset all processing attempts
Clears data from Supabase and Redis while preserving document records
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts.supabase_utils import get_supabase_client
from scripts.redis_utils import get_redis_manager
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def cleanup_supabase():
    """Clean up all processing data from Supabase while preserving documents"""
    client = get_supabase_client()
    
    logger.info("Starting Supabase cleanup...")
    
    # 1. Clear all processing states and errors
    logger.info("Resetting source_documents processing states...")
    result = client.table('source_documents').update({
        'initial_processing_status': 'pending',
        'error_message': None,
        'raw_extracted_text': None,
        'markdown_text': None,
        'ocr_metadata_json': None,
        'transcription_metadata_json': None,
        'textract_job_id': None,
        'textract_job_status': None,
        'textract_job_started_at': None,
        'textract_job_completed_at': None,
        'textract_confidence_avg': None,
        'textract_warnings': None,
        'textract_output_s3_key': None,
        'ocr_completed_at': None,
        'ocr_processing_seconds': None,
        'celery_task_id': None,
        'celery_status': None,
        'last_successful_stage': None,
        'processing_attempts': 0,
        'last_modified_at': datetime.now().isoformat()
    }).neq('id', 0).execute()  # Update all records
    logger.info(f"Reset {len(result.data)} document processing states")
    
    # 2. Clear entity mentions first (has foreign keys to chunks and entities)
    logger.info("Deleting all entity mentions...")
    result = client.table('neo4j_entity_mentions').delete().neq('id', 0).execute()
    logger.info(f"Deleted {len(result.data)} entity mentions")
    
    # 3. Clear chunks (referenced by entity mentions)
    logger.info("Deleting all chunks...")
    result = client.table('neo4j_chunks').delete().neq('id', 0).execute()
    logger.info(f"Deleted {len(result.data)} chunks")
    
    # 4. Clear entities
    logger.info("Deleting all canonical entities...")
    result = client.table('neo4j_canonical_entities').delete().neq('id', 0).execute()
    logger.info(f"Deleted {len(result.data)} canonical entities")
    
    # 5. Clear relationships
    logger.info("Deleting all relationships...")
    result = client.table('neo4j_relationships_staging').delete().neq('id', 0).execute()
    logger.info(f"Deleted {len(result.data)} relationships")
    
    # 6. Clear document nodes
    logger.info("Deleting all neo4j document nodes...")
    result = client.table('neo4j_documents').delete().neq('id', 0).execute()
    logger.info(f"Deleted {len(result.data)} document nodes")
    
    # 7. Clear processing queue
    logger.info("Clearing document processing queue...")
    result = client.table('document_processing_queue').delete().neq('id', 0).execute()
    logger.info(f"Deleted {len(result.data)} queue entries")
    
    # 8. Clear textract jobs
    logger.info("Clearing textract job records...")
    result = client.table('textract_jobs').delete().neq('id', 0).execute()
    logger.info(f"Deleted {len(result.data)} textract job records")
    
    logger.info("Supabase cleanup complete!")

def cleanup_redis():
    """Clean up all cached data from Redis"""
    redis_manager = get_redis_manager()
    client = redis_manager.get_client()
    
    logger.info("Starting Redis cleanup...")
    
    # Get all keys
    all_keys = client.keys('*')
    logger.info(f"Found {len(all_keys)} keys in Redis")
    
    # Group keys by type
    key_groups = {
        'celery': [],
        'documents': [],
        'chunks': [],
        'entities': [],
        'ocr_cache': [],
        'other': []
    }
    
    for key in all_keys:
        key_str = key.decode('utf-8') if isinstance(key, bytes) else key
        if key_str.startswith('celery'):
            key_groups['celery'].append(key)
        elif 'document' in key_str:
            key_groups['documents'].append(key)
        elif 'chunk' in key_str:
            key_groups['chunks'].append(key)
        elif 'entity' in key_str or 'entities' in key_str:
            key_groups['entities'].append(key)
        elif 'ocr' in key_str:
            key_groups['ocr_cache'].append(key)
        else:
            key_groups['other'].append(key)
    
    # Delete non-celery keys (preserve celery configuration)
    for group_name, keys in key_groups.items():
        if group_name == 'celery':
            logger.info(f"Preserving {len(keys)} Celery configuration keys")
        else:
            if keys:
                logger.info(f"Deleting {len(keys)} {group_name} keys...")
                for key in keys:
                    client.delete(key)
    
    # Clear specific cache patterns
    cache_patterns = [
        'doc:*',
        'chunks:*',
        'entities:*',
        'ocr:*',
        'processing:*',
        'task:*'
    ]
    
    for pattern in cache_patterns:
        keys = client.keys(pattern)
        if keys:
            logger.info(f"Deleting {len(keys)} keys matching pattern '{pattern}'")
            for key in keys:
                client.delete(key)
    
    # Cache manager cleanup is done through key deletion above
    logger.info("Cache cleanup completed through key deletion")
    
    logger.info("Redis cleanup complete!")

def verify_cleanup():
    """Verify that cleanup was successful"""
    supabase_client = get_supabase_client()
    redis_manager = get_redis_manager()
    redis_client = redis_manager.get_client()
    
    logger.info("\nVerifying cleanup...")
    
    # Check Supabase
    checks = {
        'neo4j_chunks': supabase_client.table('neo4j_chunks').select('count', count='exact').execute(),
        'neo4j_canonical_entities': supabase_client.table('neo4j_canonical_entities').select('count', count='exact').execute(),
        'neo4j_entity_mentions': supabase_client.table('neo4j_entity_mentions').select('count', count='exact').execute(),
        'neo4j_relationships_staging': supabase_client.table('neo4j_relationships_staging').select('count', count='exact').execute(),
        'neo4j_documents': supabase_client.table('neo4j_documents').select('count', count='exact').execute(),
        'document_processing_queue': supabase_client.table('document_processing_queue').select('count', count='exact').execute(),
        'textract_jobs': supabase_client.table('textract_jobs').select('count', count='exact').execute()
    }
    
    logger.info("Supabase table counts after cleanup:")
    for table, result in checks.items():
        logger.info(f"  {table}: {result.count}")
    
    # Check document states
    status_result = supabase_client.table('source_documents').select('initial_processing_status').execute()
    status_counts = {}
    for doc in status_result.data:
        status = doc['initial_processing_status']
        status_counts[status] = status_counts.get(status, 0) + 1
    
    logger.info("\nDocument status distribution:")
    for status, count in status_counts.items():
        logger.info(f"  {status}: {count}")
    
    # Check Redis
    remaining_keys = redis_client.keys('*')
    logger.info(f"\nRemaining Redis keys: {len(remaining_keys)}")
    
    # Sample some remaining keys
    if remaining_keys:
        logger.info("Sample of remaining keys:")
        for key in remaining_keys[:10]:
            key_str = key.decode('utf-8') if isinstance(key, bytes) else key
            logger.info(f"  - {key_str}")

def main():
    """Main cleanup function"""
    logger.info("="*60)
    logger.info("FULL PIPELINE CLEANUP - Resetting all processing data")
    logger.info("="*60)
    
    try:
        # Clean Supabase
        cleanup_supabase()
        
        # Clean Redis
        cleanup_redis()
        
        # Verify
        verify_cleanup()
        
        logger.info("\n" + "="*60)
        logger.info("CLEANUP COMPLETE - Ready for fresh processing")
        logger.info("="*60)
        
    except Exception as e:
        logger.error(f"Cleanup failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()