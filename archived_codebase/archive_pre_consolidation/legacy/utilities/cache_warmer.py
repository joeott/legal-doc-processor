# cache_warmer.py
"""Cache warming utilities for preloading frequently accessed documents."""

import asyncio
import logging
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import json

from scripts.redis_utils import get_redis_manager
from scripts.cache_keys import CacheKeys
from scripts.supabase_utils import SupabaseManager
from scripts.textract_utils import TextractProcessor

logger = logging.getLogger(__name__)


class CacheWarmer:
    """Preload cache for frequently accessed documents."""
    
    def __init__(self, db_manager: Optional[SupabaseManager] = None):
        self.db_manager = db_manager or SupabaseManager()
        self.redis_mgr = get_redis_manager()
        
    async def warm_recent_documents(self, hours: int = 24, limit: int = 100) -> Dict:
        """
        Warm cache for recently processed documents.
        
        Args:
            hours: Number of hours to look back
            limit: Maximum number of documents to warm
            
        Returns:
            Statistics about the warming process
        """
        if not self.redis_mgr.is_available():
            logger.warning("Redis not available, skipping cache warming")
            return {'error': 'Redis not available'}
            
        cutoff_time = datetime.now() - timedelta(hours=hours)
        
        try:
            # Get recent documents
            recent_docs = self.db_manager.client.table('source_documents').select(
                'id', 'document_uuid', 's3_key', 's3_bucket', 
                'initial_processing_status', 'extracted_text'
            ).gte('created_at', cutoff_time.isoformat()).order(
                'created_at', desc=True
            ).limit(limit).execute()
            
            if not recent_docs.data:
                logger.info("No recent documents found to warm cache")
                return {'documents_found': 0, 'documents_warmed': 0}
            
            # Warm documents in parallel
            tasks = []
            for doc in recent_docs.data:
                if doc.get('initial_processing_status') in ['completed', 'ocr_complete']:
                    tasks.append(self._warm_document_cache(doc))
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Count successes and failures
            success_count = sum(1 for r in results if r is True)
            failure_count = sum(1 for r in results if isinstance(r, Exception) or r is False)
            
            logger.info(f"Cache warming complete: {success_count}/{len(tasks)} documents warmed successfully")
            
            return {
                'documents_found': len(recent_docs.data),
                'documents_attempted': len(tasks),
                'documents_warmed': success_count,
                'failures': failure_count
            }
            
        except Exception as e:
            logger.error(f"Error warming recent documents: {e}")
            return {'error': str(e)}
    
    async def _warm_document_cache(self, doc: Dict) -> bool:
        """
        Warm cache for a single document.
        
        Args:
            doc: Document data from database
            
        Returns:
            True if successful, False otherwise
        """
        try:
            document_uuid = doc['document_uuid']
            
            # Check if already cached
            state_key = CacheKeys.format_key(CacheKeys.DOC_STATE, document_uuid=document_uuid)
            if self.redis_mgr.exists(state_key):
                logger.debug(f"Document {document_uuid} already has cached state")
                # Still warm other caches
            
            # Cache document state
            state_data = {
                'status': doc.get('initial_processing_status', 'unknown'),
                'last_warmed': datetime.now().isoformat()
            }
            self.redis_mgr.hset(state_key, 'warmed_state', json.dumps(state_data))
            
            # Cache OCR result if available
            if doc.get('extracted_text'):
                ocr_key = CacheKeys.format_key(CacheKeys.DOC_OCR_RESULT, document_uuid=document_uuid)
                ocr_data = {
                    'text': doc['extracted_text'][:1000],  # Cache first 1000 chars
                    'cached_at': datetime.now().isoformat()
                }
                self.redis_mgr.set_cached(ocr_key, ocr_data, ttl=3600)  # 1 hour TTL
            
            # Get and cache related data
            await self._warm_related_data(document_uuid)
            
            logger.debug(f"Successfully warmed cache for document {document_uuid}")
            return True
            
        except Exception as e:
            logger.error(f"Error warming cache for document {doc.get('document_uuid', 'unknown')}: {e}")
            return False
    
    async def _warm_related_data(self, document_uuid: str):
        """Warm cache for related document data (chunks, entities, etc.)."""
        try:
            # Get chunks
            chunks = self.db_manager.client.table('neo4j_chunks').select(
                'id', 'chunk_index', 'chunk_text'
            ).eq('document_uuid', document_uuid).limit(10).execute()
            
            if chunks.data:
                # Cache chunk count
                chunks_key = CacheKeys.format_key(CacheKeys.DOC_CHUNKS, document_uuid=document_uuid)
                self.redis_mgr.set_cached(chunks_key, {'count': len(chunks.data)}, ttl=3600)
                
                # Cache first few chunks
                for chunk in chunks.data[:3]:  # Cache first 3 chunks
                    chunk_key = CacheKeys.format_key(
                        CacheKeys.DOC_ENTITIES, 
                        document_uuid=document_uuid,
                        chunk_id=chunk['id']
                    )
                    self.redis_mgr.set_cached(
                        chunk_key, 
                        {'chunk_index': chunk['chunk_index'], 'preview': chunk['chunk_text'][:100]},
                        ttl=3600
                    )
            
        except Exception as e:
            logger.debug(f"Error warming related data for {document_uuid}: {e}")
    
    async def warm_active_textract_jobs(self) -> Dict:
        """Warm cache for active Textract jobs."""
        if not self.redis_mgr.is_available():
            return {'error': 'Redis not available'}
            
        try:
            # Get recent Textract jobs
            recent_jobs = self.db_manager.client.table('textract_jobs').select(
                'job_id', 'job_status', 'source_document_id'
            ).in_('job_status', ['IN_PROGRESS', 'SUCCEEDED']).gte(
                'created_at', (datetime.now() - timedelta(hours=1)).isoformat()
            ).execute()
            
            warmed_count = 0
            for job in recent_jobs.data:
                job_key = CacheKeys.format_key(
                    CacheKeys.TEXTRACT_JOB_STATUS,
                    job_id=job['job_id']
                )
                self.redis_mgr.set_cached(
                    job_key, 
                    {'JobStatus': job['job_status']},
                    ttl=300  # 5 minutes
                )
                warmed_count += 1
            
            logger.info(f"Warmed cache for {warmed_count} Textract jobs")
            return {'jobs_warmed': warmed_count}
            
        except Exception as e:
            logger.error(f"Error warming Textract job cache: {e}")
            return {'error': str(e)}
    
    def warm_frequently_accessed_patterns(self) -> Dict:
        """
        Warm cache for frequently accessed key patterns.
        This is useful after Redis restart or cache clear.
        """
        if not self.redis_mgr.is_available():
            return {'error': 'Redis not available'}
            
        try:
            patterns_warmed = 0
            
            # Warm rate limit counters with initial values
            rate_limit_keys = [
                CacheKeys.format_key(CacheKeys.RATE_LIMIT_OPENAI, function_name='extract_entities'),
                CacheKeys.format_key(CacheKeys.RATE_LIMIT_TEXTRACT, operation='start_document_text_detection'),
            ]
            
            for key in rate_limit_keys:
                # Initialize rate limit counter
                self.redis_mgr.set_cached(key, 0, ttl=60)
                patterns_warmed += 1
            
            # Warm global metrics
            metrics_key = "cache:metrics:total"
            if not self.redis_mgr.exists(metrics_key):
                self.redis_mgr.hset(metrics_key, 'hits', '0')
                self.redis_mgr.hset(metrics_key, 'misses', '0')
                self.redis_mgr.hset(metrics_key, 'sets', '0')
                patterns_warmed += 1
            
            logger.info(f"Warmed {patterns_warmed} frequently accessed patterns")
            return {'patterns_warmed': patterns_warmed}
            
        except Exception as e:
            logger.error(f"Error warming frequently accessed patterns: {e}")
            return {'error': str(e)}


def run_cache_warming(hours: int = 24, limit: int = 100):
    """
    Run cache warming synchronously.
    
    Args:
        hours: Number of hours to look back
        limit: Maximum number of documents to warm
    """
    warmer = CacheWarmer()
    
    # Run async warming
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        # Warm recent documents
        doc_results = loop.run_until_complete(
            warmer.warm_recent_documents(hours=hours, limit=limit)
        )
        logger.info(f"Document warming results: {doc_results}")
        
        # Warm Textract jobs
        job_results = loop.run_until_complete(
            warmer.warm_active_textract_jobs()
        )
        logger.info(f"Textract job warming results: {job_results}")
        
        # Warm frequently accessed patterns
        pattern_results = warmer.warm_frequently_accessed_patterns()
        logger.info(f"Pattern warming results: {pattern_results}")
        
        return {
            'documents': doc_results,
            'textract_jobs': job_results,
            'patterns': pattern_results
        }
        
    finally:
        loop.close()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Warm Redis cache for document processing pipeline")
    parser.add_argument('--hours', type=int, default=24, help='Number of hours to look back')
    parser.add_argument('--limit', type=int, default=100, help='Maximum number of documents to warm')
    
    args = parser.parse_args()
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    results = run_cache_warming(hours=args.hours, limit=args.limit)
    print(f"\nCache warming completed:")
    print(json.dumps(results, indent=2))