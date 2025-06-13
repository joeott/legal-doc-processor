"""
Celery tasks for generating and managing vector embeddings.
Uses OpenAI text-embedding-3-large for semantic understanding.
"""

import os
import json
import hashlib
import logging
import numpy as np
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
import time

from celery import Task
from celery_app import app
from supabase_utils import SupabaseManager
from redis_utils import get_redis_manager
from cache_keys import CacheKeys
from celery_tasks.task_utils import (
    update_document_state, 
    check_stage_completed,
    atomic_cache_update
)

from openai import OpenAI

logger = logging.getLogger(__name__)

# Initialize OpenAI client
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

class EmbeddingTask(Task):
    """Base class for embedding tasks with database connection management"""
    _db_manager = None
    
    @property
    def db_manager(self):
        if self._db_manager is None:
            self._db_manager = SupabaseManager()
        return self._db_manager
    
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Called when the task fails."""
        document_uuid = kwargs.get('document_uuid', 'unknown')
        logger.error(f"Task {task_id} failed for document {document_uuid}: {exc}")
        update_document_state(document_uuid, "embeddings", "failed", {"error": str(exc), "task_id": task_id})


def get_text_hash(text: str) -> str:
    """Generate SHA256 hash of text for change detection"""
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def batch_chunks_for_embedding(chunks: List[Dict[str, Any]], max_batch_size: int = 50) -> List[List[Dict[str, Any]]]:
    """
    Batch chunks for efficient API calls.
    OpenAI allows up to 2048 embedding inputs per request.
    We use a conservative batch size for reliability.
    """
    batches = []
    current_batch = []
    current_tokens = 0
    
    for chunk in chunks:
        # Estimate tokens (rough approximation: 1 token ≈ 4 characters)
        estimated_tokens = len(chunk.get('chunkText', '')) // 4
        
        # Start new batch if adding this chunk would exceed limits
        if current_batch and (len(current_batch) >= max_batch_size or current_tokens + estimated_tokens > 8000):
            batches.append(current_batch)
            current_batch = []
            current_tokens = 0
        
        current_batch.append(chunk)
        current_tokens += estimated_tokens
    
    if current_batch:
        batches.append(current_batch)
    
    return batches


def generate_embeddings_batch(texts: List[str], model: str = "text-embedding-3-large") -> List[np.ndarray]:
    """
    Generate embeddings for a batch of texts using OpenAI API.
    Returns list of numpy arrays.
    """
    try:
        # Clean texts - OpenAI doesn't like empty strings
        cleaned_texts = [text.strip() if text.strip() else "." for text in texts]
        
        response = openai_client.embeddings.create(
            model=model,
            input=cleaned_texts
        )
        
        embeddings = []
        for data in response.data:
            embedding_array = np.array(data.embedding, dtype=np.float32)
            embeddings.append(embedding_array)
        
        return embeddings
        
    except Exception as e:
        logger.error(f"Error generating embeddings: {e}")
        raise


def store_embedding_in_db(db_manager: SupabaseManager, chunk_id: str, embedding: np.ndarray, 
                         text_hash: str, metadata: Dict[str, Any], processing_version: int = 1) -> bool:
    """Store embedding in database with pgvector"""
    try:
        # Convert numpy array to list for JSON serialization
        embedding_list = embedding.tolist()
        
        # Prepare embedding data
        embedding_data = {
            'chunk_id': chunk_id,
            'embedding': embedding_list,
            'model_name': 'text-embedding-3-large',
            'model_version': '2024-01',
            'embedding_text_hash': text_hash,
            'metadata': json.dumps(metadata),
            'processing_version': processing_version
        }
        
        # Check if embedding already exists
        existing = db_manager.service_client.table('chunk_embeddings').select(
            'id'
        ).eq('chunk_id', chunk_id).eq('processing_version', processing_version).execute()
        
        if existing.data:
            # Update existing
            result = db_manager.service_client.table('chunk_embeddings').update(
                embedding_data
            ).eq('chunk_id', chunk_id).eq('processing_version', processing_version).execute()
        else:
            # Insert new
            result = db_manager.service_client.table('chunk_embeddings').insert(
                embedding_data
            ).execute()
        
        return bool(result.data)
        
    except Exception as e:
        # Check if it's a table not found error
        if 'relation "public.chunk_embeddings" does not exist' in str(e):
            logger.warning("chunk_embeddings table does not exist - embeddings will only be cached in Redis")
            logger.warning("Please apply migration 00015_add_chunk_embeddings_table.sql to enable database storage")
            # Return True so processing continues with Redis caching only
            return True
        else:
            logger.error(f"Error storing embedding for chunk {chunk_id}: {e}")
            return False


def cache_embedding_in_redis(chunk_id: str, embedding: np.ndarray, 
                           document_uuid: str, processing_version: int = 1) -> bool:
    """Cache embedding in Redis for fast retrieval"""
    redis_mgr = get_redis_manager()
    if not redis_mgr or not redis_mgr.is_available():
        return False
    
    try:
        # Create cache keys
        chunk_key = f"emb:chunk:{chunk_id}:v{processing_version}"
        doc_list_key = f"emb:doc:{document_uuid}:chunks:v{processing_version}"
        
        # Serialize embedding as compressed bytes
        embedding_bytes = embedding.astype(np.float32).tobytes()
        
        # Store with 24 hour TTL
        redis_mgr.redis_client.setex(chunk_key, 86400, embedding_bytes)
        
        # Add to document's chunk list
        redis_mgr.redis_client.sadd(doc_list_key, chunk_id)
        redis_mgr.redis_client.expire(doc_list_key, 86400)
        
        return True
        
    except Exception as e:
        logger.warning(f"Error caching embedding: {e}")
        return False


def get_cached_embedding(chunk_id: str, processing_version: int = 1) -> Optional[np.ndarray]:
    """Retrieve cached embedding from Redis"""
    redis_mgr = get_redis_manager()
    if not redis_mgr or not redis_mgr.is_available():
        return None
    
    try:
        chunk_key = f"emb:chunk:{chunk_id}:v{processing_version}"
        embedding_bytes = redis_mgr.redis_client.get(chunk_key)
        
        if embedding_bytes:
            # Deserialize from bytes
            embedding = np.frombuffer(embedding_bytes, dtype=np.float32)
            return embedding
        
        return None
        
    except Exception as e:
        logger.warning(f"Error retrieving cached embedding: {e}")
        return None


@app.task(bind=True, base=EmbeddingTask, max_retries=3, default_retry_delay=60, queue='embeddings')
def generate_chunk_embeddings(self, document_uuid: str, source_doc_sql_id: int,
                            chunks: List[Dict[str, Any]] = None, 
                            processing_version: int = 1) -> Dict[str, Any]:
    """
    Generate embeddings for document chunks using OpenAI text-embedding-3-large.
    
    Args:
        document_uuid: UUID of the source document
        source_doc_sql_id: SQL ID of the source document
        chunks: List of chunk dictionaries (optional - will fetch if not provided)
        processing_version: Version for caching and storage
    
    Returns:
        Dict with embedding generation results
    """
    logger.info(f"[EMBEDDING_TASK:{self.request.id}] Starting embedding generation for document {document_uuid}")
    
    # Update state
    update_document_state(document_uuid, "embeddings", "processing", {"task_id": self.request.id})
    
    # Fetch chunks if not provided
    if chunks is None:
        chunks_result = self.db_manager.client.table('neo4j_chunks').select(
            'chunkId, chunkText, chunkIndex, document_uuid'
        ).eq('document_uuid', document_uuid).order('chunkIndex').execute()
        
        chunks = chunks_result.data
        logger.info(f"[EMBEDDING_TASK:{self.request.id}] Fetched {len(chunks)} chunks from database")
    
    if not chunks:
        logger.warning(f"[EMBEDDING_TASK:{self.request.id}] No chunks found for document")
        update_document_state(document_uuid, "embeddings", "completed", {"chunk_count": 0})
        return {"status": "completed", "embeddings_generated": 0}
    
    # Process chunks in batches
    embeddings_generated = 0
    embeddings_cached = 0
    embeddings_failed = 0
    
    batches = batch_chunks_for_embedding(chunks)
    logger.info(f"[EMBEDDING_TASK:{self.request.id}] Processing {len(chunks)} chunks in {len(batches)} batches")
    
    for batch_idx, batch in enumerate(batches):
        try:
            # Check cache first
            texts_to_embed = []
            chunks_to_embed = []
            
            for chunk in batch:
                chunk_id = chunk['chunkId']
                
                # Check if we already have this embedding cached
                cached_embedding = get_cached_embedding(chunk_id, processing_version)
                if cached_embedding is not None:
                    embeddings_cached += 1
                    logger.debug(f"Using cached embedding for chunk {chunk_id}")
                    continue
                
                texts_to_embed.append(chunk['chunkText'])
                chunks_to_embed.append(chunk)
            
            # Generate embeddings for non-cached chunks
            if texts_to_embed:
                logger.info(f"[EMBEDDING_TASK:{self.request.id}] Generating embeddings for batch {batch_idx + 1}/{len(batches)} ({len(texts_to_embed)} chunks)")
                
                start_time = time.time()
                embeddings = generate_embeddings_batch(texts_to_embed)
                api_time = time.time() - start_time
                
                # Store embeddings
                for chunk, embedding in zip(chunks_to_embed, embeddings):
                    chunk_id = chunk['chunkId']
                    text_hash = get_text_hash(chunk['chunkText'])
                    
                    metadata = {
                        'chunk_index': chunk['chunkIndex'],
                        'text_length': len(chunk['chunkText']),
                        'api_time_ms': int(api_time * 1000 / len(texts_to_embed)),
                        'batch_idx': batch_idx
                    }
                    
                    # Store in database
                    if store_embedding_in_db(self.db_manager, chunk_id, embedding, text_hash, metadata, processing_version):
                        embeddings_generated += 1
                        
                        # Cache in Redis
                        cache_embedding_in_redis(chunk_id, embedding, document_uuid, processing_version)
                    else:
                        embeddings_failed += 1
                
            # Small delay between batches to respect rate limits
            if batch_idx < len(batches) - 1:
                time.sleep(0.1)
                
        except Exception as e:
            logger.error(f"[EMBEDDING_TASK:{self.request.id}] Error processing batch {batch_idx}: {e}")
            embeddings_failed += len(batch)
            
            # If it's a rate limit error, retry the task
            if "rate_limit" in str(e).lower():
                raise self.retry(exc=e, countdown=60)
    
    # Calculate document-level embedding (mean pooling)
    try:
        doc_embedding_result = self.db_manager.service_client.rpc(
            'get_document_embedding',
            {'doc_uuid': document_uuid}
        ).execute()
        
        if doc_embedding_result.data:
            # Cache document-level embedding
            doc_embedding = np.array(doc_embedding_result.data)
            doc_key = f"emb:doc:{document_uuid}:mean:v{processing_version}"
            redis_mgr = get_redis_manager()
            if redis_mgr and redis_mgr.is_available():
                redis_mgr.redis_client.setex(doc_key, 86400, doc_embedding.tobytes())
                
    except Exception as e:
        logger.warning(f"Error calculating document-level embedding: {e}")
    
    # Update final state
    result = {
        "status": "completed",
        "embeddings_generated": embeddings_generated,
        "embeddings_cached": embeddings_cached,
        "embeddings_failed": embeddings_failed,
        "total_chunks": len(chunks)
    }
    
    update_document_state(document_uuid, "embeddings", "completed", result)
    
    # Cache stage results
    atomic_cache_update(document_uuid, "embeddings", result, processing_version)
    
    # Chain to next task - entity extraction (embeddings run in parallel)
    # The entity extraction can now use embeddings for enhanced resolution
    from celery_tasks.entity_tasks import extract_entities_from_chunks
    extract_entities_from_chunks.delay(
        document_uuid=document_uuid,
        source_doc_sql_id=source_doc_sql_id,
        chunks=[{'chunkId': c['chunkId'], 'chunkText': c['chunkText']} for c in chunks]
    )
    
    logger.info(f"[EMBEDDING_TASK:{self.request.id}] Completed: {embeddings_generated} new, {embeddings_cached} cached, {embeddings_failed} failed")
    
    return result


@app.task(bind=True, base=EmbeddingTask, queue='embeddings')
def compute_chunk_similarity(self, chunk_id1: str, chunk_id2: str) -> float:
    """
    Compute cosine similarity between two chunk embeddings.
    Used for deduplication and relationship discovery.
    """
    try:
        # Try cache first
        emb1 = get_cached_embedding(chunk_id1)
        emb2 = get_cached_embedding(chunk_id2)
        
        # Fallback to database
        if emb1 is None:
            result1 = self.db_manager.service_client.table('chunk_embeddings').select(
                'embedding'
            ).eq('chunk_id', chunk_id1).single().execute()
            if result1.data:
                emb1 = np.array(result1.data['embedding'])
        
        if emb2 is None:
            result2 = self.db_manager.service_client.table('chunk_embeddings').select(
                'embedding'
            ).eq('chunk_id', chunk_id2).single().execute()
            if result2.data:
                emb2 = np.array(result2.data['embedding'])
        
        if emb1 is None or emb2 is None:
            return 0.0
        
        # Compute cosine similarity
        similarity = np.dot(emb1, emb2) / (np.linalg.norm(emb1) * np.linalg.norm(emb2))
        return float(similarity)
        
    except Exception as e:
        logger.error(f"Error computing similarity: {e}")
        return 0.0


@app.task(bind=True, base=EmbeddingTask, queue='embeddings')
def find_similar_chunks_task(self, query_text: str, threshold: float = 0.7, 
                           max_results: int = 10) -> List[Dict[str, Any]]:
    """
    Find chunks similar to a query text using embeddings.
    """
    try:
        # Generate embedding for query
        query_embedding = generate_embeddings_batch([query_text])[0]
        
        # Use database function to find similar chunks
        result = self.db_manager.service_client.rpc(
            'find_similar_chunks',
            {
                'query_embedding': query_embedding.tolist(),
                'similarity_threshold': threshold,
                'max_results': max_results
            }
        ).execute()
        
        return result.data
        
    except Exception as e:
        logger.error(f"Error finding similar chunks: {e}")
        return []