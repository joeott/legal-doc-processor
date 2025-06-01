"""Cleanup tasks for document reprocessing"""
from celery import Task
from celery_app import app
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

@app.task(bind=True, base=Task, name='cleanup_document_for_reprocessing')
def cleanup_document_for_reprocessing(self, document_uuid: str, 
                                     stages_to_clean: Optional[List[str]] = None,
                                     preserve_ocr: bool = True) -> dict:
    """
    Remove derived data for a document to allow reprocessing
    
    Args:
        document_uuid: Document identifier
        stages_to_clean: List of stages to clean (None = all)
        preserve_ocr: Keep OCR results to avoid re-calling Textract
    
    Returns:
        Dictionary with cleanup statistics
    """
    from supabase_utils import SupabaseManager
    from redis_utils import get_redis_manager, CacheKeys
    
    db = SupabaseManager()
    stats = {
        'document_uuid': document_uuid,
        'cleaned_stages': [],
        'preserved_stages': [],
        'deleted_records': {}
    }
    
    try:
        # Get document info
        source_doc = db.client.table('source_documents').select(
            'id', 'processing_version'
        ).eq('document_uuid', document_uuid).single().execute()
        
        if not source_doc.data:
            raise ValueError(f"Document {document_uuid} not found")
        
        source_doc_id = source_doc.data['id']
        current_version = source_doc.data.get('processing_version', 1)
        
        # Determine what to clean
        all_stages = ['entities', 'chunks', 'neo4j_doc', 'ocr']
        stages = stages_to_clean or all_stages
        
        # Get neo4j_document if it exists
        neo4j_doc = db.client.table('neo4j_documents').select(
            'id'
        ).eq('documentId', document_uuid).maybe_single().execute()
        
        if neo4j_doc.data:
            neo4j_doc_id = neo4j_doc.data['id']
            
            # 1. Clean entity mentions (deepest dependency)
            if 'entities' in stages:
                # Get all chunks for this document
                chunks = db.client.table('neo4j_chunks').select(
                    'id'
                ).eq('document_id', neo4j_doc_id).execute()
                
                chunk_ids = [c['id'] for c in chunks.data]
                
                if chunk_ids:
                    # Delete all entity mentions for these chunks
                    result = db.client.table('neo4j_entity_mentions').delete().in_(
                        'chunk_fk_id', chunk_ids
                    ).execute()
                    
                    stats['deleted_records']['entity_mentions'] = len(chunk_ids)
                    stats['cleaned_stages'].append('entities')
                    logger.info(f"Deleted entity mentions for {len(chunk_ids)} chunks")
                    
                    # Also delete canonical entities
                    canon_result = db.client.table('neo4j_canonical_entities').delete().eq(
                        'documentId', neo4j_doc_id
                    ).execute()
                    stats['deleted_records']['canonical_entities'] = len(canon_result.data) if canon_result.data else 0
            
            # 2. Clean chunks
            if 'chunks' in stages:
                # Get chunk UUIDs before deletion for cache cleanup
                chunks_for_cache = db.client.table('neo4j_chunks').select(
                    'chunkId'
                ).eq('document_id', neo4j_doc_id).execute()
                
                chunk_uuids_to_clear = [c['chunkId'] for c in chunks_for_cache.data]
                
                # Now delete the chunks
                result = db.client.table('neo4j_chunks').delete().eq(
                    'document_id', neo4j_doc_id
                ).execute()
                
                stats['deleted_records']['chunks'] = len(result.data) if result.data else 0
                stats['deleted_records']['chunk_uuids_for_cache'] = chunk_uuids_to_clear
                stats['cleaned_stages'].append('chunks')
                logger.info(f"Deleted {stats['deleted_records']['chunks']} chunks")
            
            # 3. Clean neo4j_document
            if 'neo4j_doc' in stages:
                result = db.client.table('neo4j_documents').delete().eq(
                    'id', neo4j_doc_id
                ).execute()
                
                stats['deleted_records']['neo4j_document'] = 1
                stats['cleaned_stages'].append('neo4j_doc')
                logger.info(f"Deleted neo4j_document")
        
        # 4. Handle OCR data
        if 'ocr' in stages and not preserve_ocr:
            # Clear OCR-related fields
            db.client.table('source_documents').update({
                'raw_extracted_text': None,
                'ocr_metadata_json': None,
                'textract_job_id': None,
                'textract_job_status': 'not_started',
                'ocr_completed_at': None
            }).eq('id', source_doc_id).execute()
            
            # Also clean up any Textract jobs
            textract_result = db.client.table('textract_jobs').delete().eq(
                'source_document_id', source_doc_id
            ).execute()
            
            stats['deleted_records']['textract_jobs'] = len(textract_result.data) if textract_result.data else 0
            stats['cleaned_stages'].append('ocr')
            logger.info("Cleared OCR data")
        elif preserve_ocr:
            stats['preserved_stages'].append('ocr')
        
        # 5. Update document status and increment version
        update_data = {
            'processing_version': current_version + 1,
            'last_successful_stage': 'ocr_complete' if preserve_ocr else None,
            'celery_status': 'ocr_complete' if preserve_ocr else 'pending',
            'celery_task_id': None,
            'error_message': None,
            'processing_attempts': 0,
            'force_reprocess': False  # Reset the flag
        }
        
        db.client.table('source_documents').update(
            update_data
        ).eq('id', source_doc_id).execute()
        
        # 6. Clear Redis state
        redis_mgr = get_redis_manager()
        if redis_mgr:
            try:
                redis_client = redis_mgr.get_client()
                
                # Use the comprehensive cache invalidation method
                redis_mgr.invalidate_document_cache(document_uuid)
                
                # Additionally handle chunk-specific caches if chunks were cleaned
                if 'chunks' in stages and 'chunk_uuids_for_cache' in stats.get('deleted_records', {}):
                    chunk_uuids = stats['deleted_records']['chunk_uuids_for_cache']
                    
                    # Clear chunk-specific text caches
                    for chunk_uuid in chunk_uuids:
                        chunk_text_key = CacheKeys.format_key(CacheKeys.DOC_CHUNK_TEXT, chunk_uuid=chunk_uuid)
                        redis_client.delete(chunk_text_key)
                    
                    logger.info(f"Cleared cache for {len(chunk_uuids)} chunks")
                
                # Preserve OCR cache if requested
                if preserve_ocr and 'ocr' not in stages:
                    # Re-fetch and restore OCR cache if it exists
                    ocr_data = db.client.table('source_documents').select(
                        'raw_extracted_text', 'ocr_metadata_json'
                    ).eq('id', source_doc_id).single().execute()
                    
                    if ocr_data.data and ocr_data.data.get('raw_extracted_text'):
                        ocr_cache_key = CacheKeys.format_key(CacheKeys.DOC_OCR_RESULT, document_uuid=document_uuid)
                        redis_mgr.set_cached(ocr_cache_key, {
                            'text': ocr_data.data['raw_extracted_text'],
                            'metadata': ocr_data.data.get('ocr_metadata_json')
                        }, ttl=7 * 24 * 3600)  # 7 days
                        logger.info("Restored OCR cache after cleanup")
                    
                logger.info("Cleared Redis state")
            except Exception as e:
                logger.warning(f"Failed to clear Redis state: {e}")
        
        logger.info(f"Cleanup completed for document {document_uuid}")
        stats['new_version'] = current_version + 1
        stats['ready_for_reprocessing'] = True
        
        return stats
        
    except Exception as e:
        logger.error(f"Error in cleanup_document_for_reprocessing: {e}")
        stats['error'] = str(e)
        raise

@app.task(bind=True, name='cleanup_all_test_data')
def cleanup_all_test_data(self) -> dict:
    """
    Completely purge all test data from the database
    WARNING: This will delete ALL documents and related data!
    """
    from supabase_utils import SupabaseManager
    
    db = SupabaseManager()
    stats = {'deleted': {}}
    
    try:
        # Delete in reverse dependency order
        
        # 1. Delete all entity mentions
        result = db.client.table('neo4j_entity_mentions').delete().neq('id', -1).execute()
        stats['deleted']['entity_mentions'] = len(result.data) if result.data else 'all'
        
        # 2. Delete all canonical entities
        result = db.client.table('neo4j_canonical_entities').delete().neq('id', -1).execute()
        stats['deleted']['canonical_entities'] = len(result.data) if result.data else 'all'
        
        # 3. Delete all chunks
        result = db.client.table('neo4j_chunks').delete().neq('id', -1).execute()
        stats['deleted']['chunks'] = len(result.data) if result.data else 'all'
        
        # 4. Delete all neo4j documents
        result = db.client.table('neo4j_documents').delete().neq('id', -1).execute()
        stats['deleted']['neo4j_documents'] = len(result.data) if result.data else 'all'
        
        # 5. Delete all textract jobs
        result = db.client.table('textract_jobs').delete().neq('id', -1).execute()
        stats['deleted']['textract_jobs'] = len(result.data) if result.data else 'all'
        
        # 6. Delete all source documents
        result = db.client.table('source_documents').delete().neq('id', -1).execute()
        stats['deleted']['source_documents'] = len(result.data) if result.data else 'all'
        
        # 7. Delete all projects
        result = db.client.table('projects').delete().neq('id', -1).execute()
        stats['deleted']['projects'] = len(result.data) if result.data else 'all'
        
        logger.info(f"Purged all test data: {stats}")
        return stats
        
    except Exception as e:
        logger.error(f"Error purging test data: {e}")
        stats['error'] = str(e)
        raise