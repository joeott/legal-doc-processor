#!/usr/bin/env python3
"""Process documents stuck in the pipeline"""
import sys
import os
import logging
from datetime import datetime, timedelta

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.supabase_utils import SupabaseManager
from scripts.redis_utils import get_redis_manager
from scripts.cache_keys import CacheKeys

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def check_document_progress(document_uuid: str) -> dict:
    """Check the actual progress of a document through Redis state."""
    redis_mgr = get_redis_manager()
    if not redis_mgr or not redis_mgr.is_available():
        return {}
    
    state_key = CacheKeys.format_key(CacheKeys.DOC_STATE, document_uuid=document_uuid)
    state_data = redis_mgr.hgetall(state_key)
    
    # Decode Redis data
    progress = {}
    for key, value in state_data.items():
        key_str = key.decode() if isinstance(key, bytes) else key
        val_str = value.decode() if isinstance(value, bytes) else value
        progress[key_str] = val_str
    
    return progress

def process_stuck_word_docs(dry_run: bool = False):
    """Find and process stuck Word documents."""
    db = SupabaseManager()
    
    # Get stuck DOCX files
    stuck_docs = db.client.table('source_documents').select(
        'id', 'document_uuid', 'original_file_name', 'celery_status', 
        'last_modified_at', 'project_fk_id'
    ).eq('celery_status', 'text_processing').ilike(
        'original_file_name', '%.docx'
    ).execute()
    
    logger.info(f"Found {len(stuck_docs.data)} stuck DOCX files")
    
    processed_count = 0
    
    for doc in stuck_docs.data:
        logger.info(f"\nProcessing: {doc['original_file_name']} (ID: {doc['id']})")
        
        # Check Redis state
        progress = check_document_progress(doc['document_uuid'])
        logger.info(f"Progress state: {progress}")
        
        # Check if chunking is actually complete
        if progress.get('chunking_status') != 'completed':
            logger.warning(f"Chunking not complete for {doc['original_file_name']}, skipping")
            continue
        
        # Get chunks from database
        chunks = db.client.table('neo4j_chunks').select(
            'id', 'chunkId', 'chunkIndex', 'text'
        ).eq('document_uuid', doc['document_uuid']).order(
            'chunkIndex'
        ).execute()
        
        if not chunks.data:
            logger.warning(f"No chunks found for {doc['original_file_name']}, skipping")
            continue
            
        logger.info(f"Document has {len(chunks.data)} chunks")
        
        # Get neo4j document info
        neo4j_doc = db.client.table('neo4j_documents').select(
            'id', 'documentId'
        ).eq('documentId', doc['document_uuid']).maybe_single().execute()
        
        if not neo4j_doc.data:
            logger.error(f"No neo4j document found for {doc['original_file_name']}")
            continue
        
        if dry_run:
            logger.info(f"[DRY RUN] Would submit entity extraction for {doc['original_file_name']}")
            continue
        
        try:
            # Submit entity extraction directly
            from scripts.celery_tasks.entity_tasks import extract_entities
            
            chunk_data = [{
                'chunk_id': c['id'],
                'chunk_uuid': c['chunkId'],
                'chunk_index': c['chunkIndex'],
                'chunk_text': c['text']
            } for c in chunks.data]
            
            task = extract_entities.delay(
                document_uuid=doc['document_uuid'],
                source_doc_sql_id=doc['id'],
                neo4j_doc_sql_id=neo4j_doc.data['id'],
                neo4j_doc_uuid=neo4j_doc.data['documentId'],
                chunk_data=chunk_data
            )
            
            # Update status
            db.client.table('source_documents').update({
                'celery_status': 'entity_extraction',
                'celery_task_id': task.id,
                'last_modified_at': datetime.now().isoformat()
            }).eq('id', doc['id']).execute()
            
            logger.info(f"✓ Submitted entity extraction for {doc['original_file_name']}: Task {task.id}")
            processed_count += 1
            
        except Exception as e:
            logger.error(f"Failed to process {doc['original_file_name']}: {e}")
    
    logger.info(f"\nProcessed {processed_count} stuck documents")
    return processed_count

def find_all_stuck_documents(max_age_minutes: int = 10):
    """Find all documents stuck in any processing stage."""
    db = SupabaseManager()
    
    cutoff_time = (datetime.now() - timedelta(minutes=max_age_minutes)).isoformat()
    
    # Check various stuck states
    stuck_states = [
        'text_processing',
        'entity_extraction', 
        'entity_resolution',
        'graph_building'
    ]
    
    stuck_docs = db.client.table('source_documents').select(
        'id', 'document_uuid', 'original_file_name', 'celery_status',
        'last_modified_at', 'detected_file_type'
    ).in_('celery_status', stuck_states).lt(
        'last_modified_at', cutoff_time
    ).execute()
    
    logger.info(f"\nDocuments stuck for more than {max_age_minutes} minutes:")
    logger.info(f"{'File Name':<50} {'Status':<20} {'Type':<10} {'Last Modified'}")
    logger.info("-" * 100)
    
    by_status = {}
    for doc in stuck_docs.data:
        status = doc['celery_status']
        by_status[status] = by_status.get(status, 0) + 1
        
        last_mod = datetime.fromisoformat(doc['last_modified_at'].replace('Z', '+00:00'))
        age = datetime.now(last_mod.tzinfo) - last_mod
        
        logger.info(
            f"{doc['original_file_name'][:50]:<50} "
            f"{status:<20} "
            f"{doc['detected_file_type']:<10} "
            f"{age.total_seconds()/60:.1f} min ago"
        )
    
    logger.info(f"\nSummary by status:")
    for status, count in by_status.items():
        logger.info(f"  {status}: {count}")
    
    return stuck_docs.data

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Process stuck documents in pipeline")
    parser.add_argument('--dry-run', action='store_true', help="Show what would be done without doing it")
    parser.add_argument('--find-all', action='store_true', help="Find all stuck documents")
    parser.add_argument('--max-age', type=int, default=10, help="Max age in minutes to consider stuck")
    
    args = parser.parse_args()
    
    if args.find_all:
        find_all_stuck_documents(args.max_age)
    else:
        process_stuck_word_docs(dry_run=args.dry_run)