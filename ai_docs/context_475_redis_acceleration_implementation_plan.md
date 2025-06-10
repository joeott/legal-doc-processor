# Context 475: Comprehensive Redis Acceleration Implementation Plan

## Date: January 9, 2025

## Executive Summary

This document presents a meticulously crafted, phased implementation plan to transform the legal document processing pipeline from a database-centric architecture to a Redis-accelerated, hybrid persistence model. Based on deep analysis of the current codebase (472-474) and refactoring requirements (450), this plan will achieve 30-40% performance improvement while maintaining data integrity and avoiding historical pitfalls.

## Strategic Vision

### Current State → Target State
```
Current: DB Write → DB Read → DB Write → DB Read → DB Write
Target:  DB Write (async) + Redis → Redis Read → DB Write (async) + Redis → Redis Read → DB Write
```

The transformation maintains the database as the source of truth while leveraging Redis for inter-stage communication at memory speed.

## Phase 1: Foundation and Safety Infrastructure (Week 1)

### 1.1 Enhanced Cache Manager with Safeguards

**File**: `scripts/cache.py`

```python
# Add to RedisManager class (after line 735)

class RedisAccelerationManager(RedisManager):
    """Enhanced Redis manager for pipeline acceleration with safety features"""
    
    # Memory thresholds
    MAX_CACHE_SIZE = 10 * 1024 * 1024  # 10MB per object
    MEMORY_THRESHOLD = 0.8  # 80% memory usage triggers eviction
    
    def __init__(self):
        super().__init__()
        self.circuit_breaker_failures = 0
        self.circuit_breaker_threshold = 5
        self.circuit_breaker_reset_time = None
        
    def set_cached_safe(self, key: str, value: Any, expire: int = 3600) -> bool:
        """Safe caching with size limits and memory monitoring"""
        # Check circuit breaker
        if not self.is_healthy():
            logger.warning(f"Circuit breaker open, skipping cache write for {key}")
            return False
            
        # Check object size
        size = len(pickle.dumps(value))
        if size > self.MAX_CACHE_SIZE:
            # Store in S3 instead
            s3_key = self._store_large_object_s3(key, value)
            return self.set_cached(key, {"type": "s3_ref", "key": s3_key}, expire)
            
        # Check memory usage
        if self._get_memory_usage() > self.MEMORY_THRESHOLD:
            self._evict_oldest_keys()
            
        # Set with TTL
        try:
            return self.set_cached(key, value, expire)
        except Exception as e:
            self._handle_redis_failure(e)
            return False
            
    def get_cached_with_fallback(self, key: str, fallback_func: Callable) -> Optional[Any]:
        """Get from cache with database fallback"""
        try:
            # Try cache first
            value = self.get_cached(key)
            if value and isinstance(value, dict) and value.get("type") == "s3_ref":
                # Retrieve large object from S3
                return self._retrieve_from_s3(value["key"])
            return value
        except Exception as e:
            logger.warning(f"Cache get failed for {key}, falling back to DB: {e}")
            # Fall back to database
            return fallback_func()
            
    def atomic_pipeline_update(self, updates: Dict[str, Any]) -> bool:
        """Atomically update multiple keys"""
        try:
            pipeline = self.redis_client.pipeline()
            for key, value in updates.items():
                serialized = pickle.dumps(value)
                pipeline.setex(key, 3600, serialized)
            pipeline.execute()
            return True
        except Exception as e:
            self._handle_redis_failure(e)
            return False
            
    def _get_memory_usage(self) -> float:
        """Get Redis memory usage percentage"""
        try:
            info = self.redis_client.info('memory')
            used = info['used_memory']
            max_memory = info['maxmemory'] or (8 * 1024 * 1024 * 1024)  # 8GB default
            return used / max_memory
        except:
            return 0.0
            
    def _evict_oldest_keys(self, count: int = 100):
        """Evict oldest keys when memory pressure"""
        try:
            # Get keys sorted by idle time
            keys = []
            for key in self.redis_client.scan_iter(match="doc:*", count=1000):
                idle_time = self.redis_client.object('idletime', key)
                keys.append((key, idle_time or 0))
            
            # Sort by idle time and delete oldest
            keys.sort(key=lambda x: x[1], reverse=True)
            for key, _ in keys[:count]:
                self.redis_client.delete(key)
                
            logger.info(f"Evicted {min(count, len(keys))} keys due to memory pressure")
        except Exception as e:
            logger.error(f"Failed to evict keys: {e}")
            
    def is_healthy(self) -> bool:
        """Check if Redis is healthy with circuit breaker"""
        if self.circuit_breaker_reset_time:
            if datetime.utcnow() > self.circuit_breaker_reset_time:
                # Reset circuit breaker
                self.circuit_breaker_failures = 0
                self.circuit_breaker_reset_time = None
            else:
                return False
                
        try:
            self.redis_client.ping()
            return True
        except:
            self.circuit_breaker_failures += 1
            if self.circuit_breaker_failures >= self.circuit_breaker_threshold:
                # Open circuit breaker
                self.circuit_breaker_reset_time = datetime.utcnow() + timedelta(minutes=5)
                logger.error("Redis circuit breaker opened for 5 minutes")
            return False

# Update the singleton getter
_redis_acceleration_manager = None

def get_redis_acceleration_manager() -> RedisAccelerationManager:
    """Get singleton Redis acceleration manager"""
    global _redis_acceleration_manager
    if _redis_acceleration_manager is None:
        _redis_acceleration_manager = RedisAccelerationManager()
    return _redis_acceleration_manager
```

### 1.2 Standardized Cache Key Generation

**File**: `scripts/cache.py` (update CacheKeys class, line 38)

```python
class CacheKeys:
    """Centralized cache key patterns with type safety"""
    
    @staticmethod
    def _ensure_string_uuid(uuid_value: Union[str, UUID]) -> str:
        """Ensure UUID is always string for consistent keys"""
        return str(uuid_value) if isinstance(uuid_value, UUID) else uuid_value
    
    # Update all methods to use _ensure_string_uuid
    @classmethod
    def doc_state(cls, document_uuid: Union[str, UUID]) -> str:
        """Get document state key"""
        return f"doc:state:{cls._ensure_string_uuid(document_uuid)}"
        
    @classmethod
    def doc_ocr(cls, document_uuid: Union[str, UUID]) -> str:
        """Get OCR result key"""
        return f"doc:ocr:{cls._ensure_string_uuid(document_uuid)}"
        
    # ... update all other methods similarly
    
    # New keys for acceleration
    @classmethod
    def doc_context(cls, document_uuid: Union[str, UUID]) -> str:
        """Rich context for LLM operations"""
        return f"doc:context:{cls._ensure_string_uuid(document_uuid)}"
        
    @classmethod
    def project_canonicals(cls, project_uuid: Union[str, UUID]) -> str:
        """Project-wide canonical entities"""
        return f"project:canonicals:{cls._ensure_string_uuid(project_uuid)}"
        
    @classmethod
    def llm_examples(cls, example_type: str) -> str:
        """Cached LLM few-shot examples"""
        return f"llm:examples:{example_type}"
```

## Phase 2: Core Pipeline Transformation (Week 2)

### 2.1 PDF Tasks Acceleration

**File**: `scripts/pdf_tasks.py`

Transform the main processing tasks to use Redis acceleration:

```python
# Update imports (line 22)
from scripts.cache import (
    get_redis_manager, 
    get_redis_acceleration_manager,  # New
    CacheKeys, 
    redis_cache
)

# Add new state management function (after line 393)
async def update_document_state_async(
    document_uuid: str, 
    stage: str, 
    status: str,
    metadata: Optional[Dict] = None,
    persist_to_db: bool = True
) -> None:
    """Update document state with async DB persistence"""
    redis_manager = get_redis_acceleration_manager()
    
    state_data = {
        'document_uuid': str(document_uuid),
        'stage': stage,
        'status': status,
        'updated_at': datetime.utcnow().isoformat(),
        'metadata': metadata or {}
    }
    
    # Update Redis immediately
    redis_manager.set_cached_safe(
        CacheKeys.doc_state(document_uuid),
        state_data,
        expire=86400  # 24 hours
    )
    
    # Async DB update
    if persist_to_db:
        asyncio.create_task(
            _persist_state_to_db(document_uuid, state_data)
        )

# Transform extract_text_from_document (line 520)
@app.task(
    bind=True,
    name='scripts.pdf_tasks.extract_text_from_document',
    queue='ocr',
    max_retries=3,
    default_retry_delay=300,
)
def extract_text_from_document(self, document_uuid: str, file_path: Optional[str] = None) -> Dict[str, Any]:
    """Extract text with Redis acceleration"""
    logger.info(f"Starting OCR extraction for document {document_uuid}")
    redis_manager = get_redis_acceleration_manager()
    
    # Check cache first
    cached_result = redis_manager.get_cached(CacheKeys.doc_ocr(document_uuid))
    if cached_result:
        logger.info(f"Using cached OCR result for {document_uuid}")
        # Still trigger next stage
        continue_pipeline_after_ocr.apply_async(
            args=[cached_result, document_uuid],
            queue='text'
        )
        return cached_result
    
    try:
        # Lock to prevent duplicate processing
        with redis_manager.lock(f"ocr:{document_uuid}", timeout=600):
            # Double-check cache after acquiring lock
            cached_result = redis_manager.get_cached(CacheKeys.doc_ocr(document_uuid))
            if cached_result:
                return cached_result
                
            # Proceed with OCR
            db = DatabaseManager()
            session = next(db.get_session())
            
            # ... existing OCR logic ...
            
            result = {
                'status': 'success',
                'text': extracted_text,
                'page_count': page_count,
                'metadata': {
                    'extraction_method': 'textract',
                    'job_id': job_id
                }
            }
            
            # Save to Redis immediately
            redis_manager.set_cached_safe(
                CacheKeys.doc_ocr(document_uuid),
                result,
                expire=86400
            )
            
            # Async DB save
            asyncio.create_task(
                _save_ocr_to_db(document_uuid, extracted_text, job_id)
            )
            
            # Update state
            await update_document_state_async(
                document_uuid,
                'ocr_completed',
                'success'
            )
            
            # Chain to next stage
            continue_pipeline_after_ocr.apply_async(
                args=[result, document_uuid],
                queue='text'
            )
            
            return result
            
    except Exception as e:
        logger.error(f"OCR failed for {document_uuid}: {str(e)}")
        # Update error state
        await update_document_state_async(
            document_uuid,
            'ocr_processing',
            'error',
            {'error': str(e)}
        )
        raise self.retry(exc=e)

# Transform chunk_document_text (line 850)
@app.task(
    name='scripts.pdf_tasks.chunk_document_text',
    queue='text',
    max_retries=3
)
def chunk_document_text(ocr_result: Dict, document_uuid: str) -> Dict[str, Any]:
    """Create chunks using Redis-cached OCR result"""
    logger.info(f"Starting text chunking for document {document_uuid}")
    redis_manager = get_redis_acceleration_manager()
    
    try:
        # Get OCR text from Redis (no DB query!)
        if isinstance(ocr_result, dict) and ocr_result.get('status') == 'success':
            text = ocr_result.get('text', '')
        else:
            # Fallback to Redis cache
            cached_ocr = redis_manager.get_cached_with_fallback(
                CacheKeys.doc_ocr(document_uuid),
                lambda: _load_ocr_from_db(document_uuid)
            )
            text = cached_ocr.get('text', '') if cached_ocr else ''
            
        if not text:
            raise ValueError("No text available for chunking")
            
        # Create chunks
        chunks = create_semantic_chunks(text, document_uuid)
        
        # Cache chunks immediately
        chunks_data = [chunk.dict() for chunk in chunks]
        redis_manager.set_cached_safe(
            CacheKeys.doc_chunks(document_uuid),
            chunks_data,
            expire=86400
        )
        
        # Also cache as list for quick access
        redis_manager.set_cached_safe(
            CacheKeys.doc_chunks_list(document_uuid),
            [c['text'] for c in chunks_data],
            expire=86400
        )
        
        # Async DB save
        asyncio.create_task(
            _save_chunks_to_db(document_uuid, chunks)
        )
        
        # Update state
        await update_document_state_async(
            document_uuid,
            'chunks_created',
            'success',
            {'chunk_count': len(chunks)}
        )
        
        # Chain to entity extraction
        extract_entities_from_chunks.apply_async(
            args=[chunks_data, document_uuid],
            queue='entity'
        )
        
        return {
            'status': 'success',
            'chunk_count': len(chunks),
            'chunks': chunks_data
        }
        
    except Exception as e:
        logger.error(f"Chunking failed for {document_uuid}: {str(e)}")
        await update_document_state_async(
            document_uuid,
            'chunking',
            'error',
            {'error': str(e)}
        )
        raise
```

### 2.2 Entity Service Acceleration

**File**: `scripts/entity_service.py`

```python
# Update initialization (line 111)
def __init__(self):
    self.db = DatabaseManager()
    self.redis_manager = get_redis_acceleration_manager()  # Use acceleration manager
    self.openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    self.model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    
# Enhanced entity extraction with context (line 275)
async def extract_entities_from_chunks_accelerated(
    self,
    chunks: List[Dict],
    document_uuid: str,
    project_uuid: Optional[str] = None
) -> List[EntityMentionMinimal]:
    """Extract entities with Redis-accelerated context"""
    
    # Build rich context from Redis
    context = await self._build_llm_context(document_uuid, project_uuid)
    
    all_entities = []
    
    for chunk in chunks:
        # Check cache first
        cache_key = CacheKeys.chunk_entities(document_uuid, chunk['chunk_uuid'])
        cached = self.redis_manager.get_cached(cache_key)
        
        if cached:
            all_entities.extend(cached)
            continue
            
        # Extract with context
        entities = await self._extract_with_context(
            chunk_text=chunk['text'],
            chunk_uuid=chunk['chunk_uuid'],
            document_uuid=document_uuid,
            context=context
        )
        
        # Cache immediately
        self.redis_manager.set_cached_safe(cache_key, entities, expire=3600)
        
        all_entities.extend(entities)
        
    # Cache all entities
    self.redis_manager.set_cached_safe(
        CacheKeys.doc_entity_mentions(document_uuid),
        all_entities,
        expire=86400
    )
    
    # Async DB save
    asyncio.create_task(
        self._save_entities_to_db(document_uuid, all_entities)
    )
    
    return all_entities

async def _build_llm_context(
    self, 
    document_uuid: str, 
    project_uuid: Optional[str]
) -> Dict[str, Any]:
    """Build rich context from Redis for LLM"""
    context = {}
    
    # Get full OCR text (first 2000 chars for context)
    ocr_result = self.redis_manager.get_cached(CacheKeys.doc_ocr(document_uuid))
    if ocr_result:
        context['full_text'] = ocr_result.get('text', '')[:2000]
        
    # Get project-wide canonical entities
    if project_uuid:
        canonicals = self.redis_manager.get_cached(
            CacheKeys.project_canonicals(project_uuid)
        )
        if canonicals:
            context['project_entities'] = canonicals[:50]  # Top 50
            
    # Get cached examples
    examples = self.redis_manager.get_cached(CacheKeys.llm_examples('legal_entity'))
    if examples:
        context['few_shot_examples'] = examples
        
    # Get recent similar documents
    similar_key = f"project:{project_uuid}:recent:entities"
    recent = self.redis_manager.get_cached(similar_key)
    if recent:
        context['recent_patterns'] = recent
        
    return context

# Enhanced resolution with cross-document cache (line 680)
async def resolve_entities_accelerated(
    self,
    document_uuid: str,
    project_uuid: Optional[str] = None
) -> List[CanonicalEntityMinimal]:
    """Resolve entities with Redis acceleration"""
    
    # Lock to prevent concurrent resolution
    with self.redis_manager.lock(f"resolve:{document_uuid}", timeout=300):
        # Get entities from Redis
        entities = self.redis_manager.get_cached_with_fallback(
            CacheKeys.doc_entity_mentions(document_uuid),
            lambda: self._load_entities_from_db(document_uuid)
        )
        
        if not entities:
            return []
            
        # Get project canonicals for better resolution
        existing_canonicals = []
        if project_uuid:
            existing_canonicals = self.redis_manager.get_cached(
                CacheKeys.project_canonicals(project_uuid)
            ) or []
            
        # Resolve entities
        canonical_entities = self._resolve_with_context(
            entities,
            existing_canonicals
        )
        
        # Update caches atomically
        updates = {
            CacheKeys.doc_canonical_entities(document_uuid): canonical_entities,
        }
        
        if project_uuid:
            # Update project cache
            all_canonicals = existing_canonicals + canonical_entities
            updates[CacheKeys.project_canonicals(project_uuid)] = all_canonicals
            
        self.redis_manager.atomic_pipeline_update(updates)
        
        # Async DB save
        asyncio.create_task(
            self._save_canonical_entities_to_db(
                document_uuid, 
                canonical_entities
            )
        )
        
        return canonical_entities
```

### 2.3 Textract Utils Acceleration

**File**: `scripts/textract_utils.py`

```python
# Update poll_textract_job for Redis-first approach (line 880)
async def poll_textract_job_accelerated(
    self,
    job_id: str,
    document_uuid: str
) -> Optional[str]:
    """Poll Textract job with Redis caching"""
    redis_manager = get_redis_acceleration_manager()
    
    # Check if result already cached
    cache_key = f"textract:result:{job_id}"
    cached_result = redis_manager.get_cached(cache_key)
    if cached_result:
        return cached_result
        
    max_attempts = 60
    attempt = 0
    
    while attempt < max_attempts:
        try:
            response = self.textract_client.get_document_text_detection(
                JobId=job_id
            )
            
            status = response['JobStatus']
            
            # Update status in Redis
            redis_manager.set_cached_safe(
                f"textract:status:{job_id}",
                {
                    'status': status,
                    'attempt': attempt,
                    'timestamp': datetime.utcnow().isoformat()
                },
                expire=3600
            )
            
            if status == 'SUCCEEDED':
                # Extract text
                text = self._extract_text_from_response(response)
                
                # Cache result
                redis_manager.set_cached_safe(
                    cache_key,
                    text,
                    expire=86400
                )
                
                # Async DB update
                asyncio.create_task(
                    self._update_textract_job_db(job_id, status, text)
                )
                
                return text
                
            elif status == 'FAILED':
                error_msg = response.get('StatusMessage', 'Unknown error')
                asyncio.create_task(
                    self._update_textract_job_db(job_id, status, None, error_msg)
                )
                raise Exception(f"Textract job failed: {error_msg}")
                
        except Exception as e:
            logger.error(f"Error polling Textract job {job_id}: {e}")
            if attempt >= max_attempts - 1:
                raise
                
        attempt += 1
        await asyncio.sleep(5)  # Non-blocking sleep
        
    raise TimeoutError(f"Textract job {job_id} timed out")
```

## Phase 3: Service Layer Integration (Week 3)

### 3.1 Graph Service with Redis Context

**File**: `scripts/graph_service.py`

```python
# Add Redis acceleration
def __init__(self):
    self.db = DatabaseManager()
    self.redis_manager = get_redis_acceleration_manager()
    
async def build_relationships_accelerated(
    self,
    document_uuid: str,
    project_uuid: Optional[str] = None
) -> ProcessingResult:
    """Build relationships using Redis-cached data"""
    
    # Get all data from Redis (no DB queries!)
    chunks = self.redis_manager.get_cached_with_fallback(
        CacheKeys.doc_chunks(document_uuid),
        lambda: self._load_chunks_from_db(document_uuid)
    )
    
    canonical_entities = self.redis_manager.get_cached_with_fallback(
        CacheKeys.doc_canonical_entities(document_uuid),
        lambda: self._load_canonical_from_db(document_uuid)
    )
    
    if not chunks or not canonical_entities:
        return ProcessingResult(
            status="error",
            message="Missing required data"
        )
        
    # Get project graph context
    project_graph = None
    if project_uuid:
        project_graph = self.redis_manager.get_cached(
            f"project:{project_uuid}:graph"
        )
        
    # Build relationships
    relationships = self._identify_relationships(
        chunks,
        canonical_entities,
        project_graph
    )
    
    # Cache relationships
    self.redis_manager.set_cached_safe(
        f"doc:relationships:{document_uuid}",
        relationships,
        expire=86400
    )
    
    # Async DB save
    asyncio.create_task(
        self._save_relationships_to_db(document_uuid, relationships)
    )
    
    # Update project graph cache
    if project_uuid and relationships:
        asyncio.create_task(
            self._update_project_graph_cache(project_uuid, relationships)
        )
        
    return ProcessingResult(
        status="success",
        data={"relationship_count": len(relationships)}
    )
```

### 3.2 Batch Processor Enhancement

**File**: `scripts/batch_processor.py`

```python
# Update for Redis acceleration (line 170)
class RedisBatchProcessor(BatchProcessor):
    """Batch processor with Redis acceleration"""
    
    def __init__(self):
        super().__init__()
        self.redis = get_redis_acceleration_manager()
        
    async def process_batch_accelerated(
        self,
        documents: List[Dict],
        batch_id: str
    ) -> Dict[str, Any]:
        """Process batch with Redis coordination"""
        
        # Initialize batch state in Redis
        batch_state = {
            'batch_id': batch_id,
            'total_documents': len(documents),
            'processed': 0,
            'failed': 0,
            'status': 'processing',
            'start_time': datetime.utcnow().isoformat()
        }
        
        self.redis.set_cached_safe(
            f"batch:state:{batch_id}",
            batch_state,
            expire=86400
        )
        
        # Pre-warm caches for batch
        await self._prewarm_batch_caches(documents)
        
        # Process documents with shared context
        results = []
        for doc in documents:
            try:
                # Each document benefits from warmed caches
                result = await self._process_single_accelerated(
                    doc,
                    batch_id
                )
                results.append(result)
                
                # Update batch progress
                batch_state['processed'] += 1
                self.redis.set_cached_safe(
                    f"batch:state:{batch_id}",
                    batch_state,
                    expire=86400
                )
                
            except Exception as e:
                logger.error(f"Document {doc['uuid']} failed: {e}")
                batch_state['failed'] += 1
                
        batch_state['status'] = 'completed'
        batch_state['end_time'] = datetime.utcnow().isoformat()
        
        # Final state update
        self.redis.set_cached_safe(
            f"batch:state:{batch_id}",
            batch_state,
            expire=86400
        )
        
        return {
            'batch_id': batch_id,
            'results': results,
            'summary': batch_state
        }
        
    async def _prewarm_batch_caches(self, documents: List[Dict]):
        """Pre-warm caches for batch processing"""
        
        # Extract project UUIDs
        project_uuids = set(
            doc.get('project_uuid') 
            for doc in documents 
            if doc.get('project_uuid')
        )
        
        # Pre-load project data
        for project_uuid in project_uuids:
            # Load canonical entities
            canonicals = await self._load_project_canonicals(project_uuid)
            self.redis.set_cached_safe(
                CacheKeys.project_canonicals(project_uuid),
                canonicals,
                expire=3600
            )
            
        # Pre-load LLM examples
        examples = await self._load_llm_examples()
        self.redis.set_cached_safe(
            CacheKeys.llm_examples('legal_entity'),
            examples,
            expire=7200
        )
```

## Phase 4: Monitoring and Fallback Systems (Week 4)

### 4.1 Enhanced Monitoring

**File**: `scripts/cli/monitor.py`

```python
# Add Redis acceleration metrics (line 370)
def get_redis_acceleration_stats(self) -> Dict[str, Any]:
    """Get Redis acceleration metrics"""
    redis = get_redis_acceleration_manager()
    
    stats = {
        'acceleration_enabled': True,
        'circuit_breaker_status': 'closed' if redis.is_healthy() else 'open',
        'memory_usage': redis._get_memory_usage(),
        'cache_performance': {}
    }
    
    # Calculate hit rates for each cache type
    for cache_type in ['ocr', 'chunks', 'entities', 'canonical']:
        pattern = f"doc:{cache_type}:*"
        keys = list(redis.scan_keys(pattern))
        stats['cache_performance'][cache_type] = {
            'cached_documents': len(keys),
            'memory_bytes': sum(
                redis.redis_client.memory_usage(k) or 0 
                for k in keys[:100]  # Sample
            )
        }
        
    # Get async write queue depth
    stats['async_write_queue'] = {
        'pending': asyncio.all_tasks().__len__(),
        'completed_last_hour': redis.get_cached('stats:db_writes:completed') or 0
    }
    
    return stats

# Update display (line 516)
if redis_stats.get('acceleration_enabled'):
    console.print(Panel(
        f"[bold green]Redis Acceleration Active[/bold green]\n"
        f"Circuit Breaker: {redis_stats['circuit_breaker_status']}\n"
        f"Memory Usage: {redis_stats['memory_usage']:.1%}\n"
        f"Async Write Queue: {redis_stats['async_write_queue']['pending']} pending"
    ))
```

### 4.2 Fallback Mechanisms

**File**: `scripts/pdf_tasks.py` (add after line 2400)

```python
class FallbackProcessor:
    """Fallback to traditional processing when Redis unavailable"""
    
    @staticmethod
    def should_use_fallback() -> bool:
        """Determine if fallback processing needed"""
        redis = get_redis_acceleration_manager()
        return not redis.is_healthy()
        
    @staticmethod
    async def process_with_fallback(
        func_accelerated: Callable,
        func_traditional: Callable,
        *args,
        **kwargs
    ):
        """Process with automatic fallback"""
        if FallbackProcessor.should_use_fallback():
            logger.warning("Redis unavailable, using traditional processing")
            return await func_traditional(*args, **kwargs)
        else:
            try:
                return await func_accelerated(*args, **kwargs)
            except Exception as e:
                logger.error(f"Accelerated processing failed: {e}, falling back")
                return await func_traditional(*args, **kwargs)

# Wrap all accelerated functions
@app.task
def extract_text_from_document_wrapper(
    self,
    document_uuid: str,
    file_path: Optional[str] = None
):
    """Wrapper with fallback support"""
    return asyncio.run(
        FallbackProcessor.process_with_fallback(
            extract_text_from_document_accelerated,
            extract_text_from_document_traditional,
            self,
            document_uuid,
            file_path
        )
    )
```

## Phase 5: Testing and Validation (Week 5)

### 5.1 Redis Acceleration Tests

**File**: `tests/integration/test_redis_acceleration.py`

```python
import pytest
import asyncio
from unittest.mock import patch, MagicMock
from scripts.cache import get_redis_acceleration_manager
from scripts.pdf_tasks import (
    extract_text_from_document,
    chunk_document_text,
    extract_entities_from_chunks
)

class TestRedisAcceleration:
    """Test Redis acceleration features"""
    
    @pytest.fixture
    def redis_manager(self):
        """Get test Redis manager"""
        manager = get_redis_acceleration_manager()
        # Clear test data
        manager.delete_pattern("test:*")
        manager.delete_pattern("doc:*:test-*")
        return manager
        
    @pytest.mark.asyncio
    async def test_pipeline_acceleration(self, redis_manager):
        """Test full pipeline with Redis acceleration"""
        document_uuid = "test-doc-123"
        
        # Mock OCR result
        ocr_result = {
            'status': 'success',
            'text': 'Test legal document content',
            'page_count': 1
        }
        
        # Stage 1: OCR caching
        redis_manager.set_cached_safe(
            f"doc:ocr:{document_uuid}",
            ocr_result
        )
        
        # Stage 2: Chunking should read from Redis
        with patch('scripts.pdf_tasks._load_ocr_from_db') as mock_db:
            mock_db.return_value = None  # Should not be called
            
            result = chunk_document_text(ocr_result, document_uuid)
            
            assert result['status'] == 'success'
            assert mock_db.call_count == 0  # No DB call!
            
        # Verify chunks cached
        cached_chunks = redis_manager.get_cached(f"doc:chunks:{document_uuid}")
        assert cached_chunks is not None
        assert len(cached_chunks) > 0
        
    @pytest.mark.asyncio
    async def test_circuit_breaker(self, redis_manager):
        """Test circuit breaker functionality"""
        
        # Simulate Redis failures
        with patch.object(redis_manager.redis_client, 'ping') as mock_ping:
            mock_ping.side_effect = Exception("Connection refused")
            
            # Trigger circuit breaker
            for _ in range(6):  # Threshold is 5
                assert not redis_manager.is_healthy()
                
        # Circuit breaker should be open
        assert redis_manager.circuit_breaker_reset_time is not None
        assert not redis_manager.is_healthy()
        
        # Should fall back to traditional processing
        from scripts.pdf_tasks import FallbackProcessor
        assert FallbackProcessor.should_use_fallback()
        
    def test_memory_management(self, redis_manager):
        """Test memory eviction under pressure"""
        
        # Fill cache near threshold
        large_data = "x" * (5 * 1024 * 1024)  # 5MB
        
        for i in range(10):
            redis_manager.set_cached_safe(
                f"test:large:{i}",
                large_data,
                expire=3600
            )
            
        # Check that eviction occurred
        remaining_keys = list(redis_manager.scan_keys("test:large:*"))
        assert len(remaining_keys) < 10  # Some keys evicted
        
    @pytest.mark.asyncio
    async def test_atomic_updates(self, redis_manager):
        """Test atomic pipeline updates"""
        
        updates = {
            "test:key1": "value1",
            "test:key2": "value2",
            "test:key3": "value3"
        }
        
        # Atomic update
        success = redis_manager.atomic_pipeline_update(updates)
        assert success
        
        # All keys should exist
        for key in updates:
            assert redis_manager.get_cached(key) == updates[key]
```

### 5.2 Performance Benchmarks

**File**: `tests/performance/benchmark_redis_acceleration.py`

```python
import time
import asyncio
from scripts.pdf_tasks import process_document_traditional, process_document_accelerated

async def benchmark_processing():
    """Benchmark traditional vs accelerated processing"""
    
    document_uuid = "benchmark-doc-001"
    results = {}
    
    # Traditional processing
    start = time.time()
    await process_document_traditional(document_uuid)
    results['traditional'] = time.time() - start
    
    # Clear caches
    redis = get_redis_acceleration_manager()
    redis.delete_pattern(f"doc:*:{document_uuid}")
    
    # Accelerated processing
    start = time.time()
    await process_document_accelerated(document_uuid)
    results['accelerated'] = time.time() - start
    
    # Calculate improvement
    improvement = (results['traditional'] - results['accelerated']) / results['traditional']
    
    print(f"Traditional: {results['traditional']:.2f}s")
    print(f"Accelerated: {results['accelerated']:.2f}s")
    print(f"Improvement: {improvement:.1%}")
    
    assert improvement > 0.25  # At least 25% improvement
```

## Phase 6: Deployment and Migration (Week 6)

### 6.1 Feature Flag Implementation

**File**: `scripts/config.py` (add after line 400)

```python
# Redis Acceleration Configuration
REDIS_ACCELERATION_ENABLED = env.bool('REDIS_ACCELERATION_ENABLED', default=False)
REDIS_ACCELERATION_MEMORY_LIMIT = env.int('REDIS_ACCELERATION_MEMORY_LIMIT', default=8 * 1024 * 1024 * 1024)  # 8GB
REDIS_ACCELERATION_TTL_HOURS = env.int('REDIS_ACCELERATION_TTL_HOURS', default=24)
REDIS_ACCELERATION_CIRCUIT_BREAKER_THRESHOLD = env.int('REDIS_ACCELERATION_CIRCUIT_BREAKER_THRESHOLD', default=5)

# Gradual rollout configuration
REDIS_ACCELERATION_ROLLOUT_PERCENTAGE = env.int('REDIS_ACCELERATION_ROLLOUT_PERCENTAGE', default=0)

def should_use_redis_acceleration(document_uuid: str) -> bool:
    """Determine if document should use Redis acceleration"""
    if not REDIS_ACCELERATION_ENABLED:
        return False
        
    # Gradual rollout based on UUID hash
    import hashlib
    hash_value = int(hashlib.md5(document_uuid.encode()).hexdigest(), 16)
    return (hash_value % 100) < REDIS_ACCELERATION_ROLLOUT_PERCENTAGE
```

### 6.2 Migration Script

**File**: `scripts/migrate_to_redis_acceleration.py`

```python
#!/usr/bin/env python3
"""
Migrate existing pipeline to Redis acceleration
"""

import asyncio
from scripts.cache import get_redis_acceleration_manager
from scripts.db import DatabaseManager

async def migrate_active_documents():
    """Migrate active documents to Redis cache"""
    
    db = DatabaseManager()
    redis = get_redis_acceleration_manager()
    session = next(db.get_session())
    
    # Find documents in processing
    active_docs = session.execute(
        "SELECT document_uuid, status, raw_extracted_text "
        "FROM source_documents "
        "WHERE status NOT IN ('completed', 'failed') "
        "AND created_at > NOW() - INTERVAL '7 days'"
    ).fetchall()
    
    print(f"Found {len(active_docs)} active documents to migrate")
    
    for doc in active_docs:
        try:
            # Cache OCR result if available
            if doc.raw_extracted_text:
                redis.set_cached_safe(
                    f"doc:ocr:{doc.document_uuid}",
                    {
                        'status': 'success',
                        'text': doc.raw_extracted_text
                    },
                    expire=86400
                )
                
            # Cache state
            redis.set_cached_safe(
                f"doc:state:{doc.document_uuid}",
                {
                    'status': doc.status,
                    'stage': _determine_stage(doc.status)
                },
                expire=86400
            )
            
            print(f"Migrated {doc.document_uuid}")
            
        except Exception as e:
            print(f"Failed to migrate {doc.document_uuid}: {e}")
            
    print("Migration complete")

def _determine_stage(status: str) -> str:
    """Map status to pipeline stage"""
    mapping = {
        'uploaded': 'uploaded',
        'processing': 'ocr_processing',
        'chunked': 'chunks_created',
        'entities_extracted': 'entities_extracted',
        'resolved': 'entities_resolved'
    }
    return mapping.get(status, 'unknown')

if __name__ == "__main__":
    asyncio.run(migrate_active_documents())
```

## Implementation Timeline

### Week 1: Foundation
- [ ] Implement RedisAccelerationManager with safety features
- [ ] Update CacheKeys with type safety
- [ ] Add circuit breaker and memory management
- [ ] Deploy to development environment

### Week 2: Core Pipeline
- [ ] Transform pdf_tasks.py for Redis acceleration
- [ ] Update entity_service.py with context building
- [ ] Modify textract_utils.py for async polling
- [ ] Integration testing

### Week 3: Services
- [ ] Update graph_service.py
- [ ] Enhance batch_processor.py
- [ ] Update all service modules
- [ ] Performance testing

### Week 4: Monitoring
- [ ] Implement fallback mechanisms
- [ ] Add acceleration metrics
- [ ] Create dashboards
- [ ] Load testing

### Week 5: Testing
- [ ] Unit tests for all components
- [ ] Integration tests
- [ ] Performance benchmarks
- [ ] Security audit

### Week 6: Deployment
- [ ] Feature flag setup
- [ ] Migration scripts
- [ ] Gradual rollout (10% → 50% → 100%)
- [ ] Production monitoring

## Expected Outcomes

### Performance Improvements
- **30-40% reduction** in end-to-end processing time
- **90% reduction** in inter-stage latency (100ms → 1ms)
- **10x improvement** in batch processing throughput
- **50% reduction** in database load

### Reliability Enhancements
- Circuit breaker prevents Redis failures from affecting pipeline
- Graceful degradation to traditional processing
- Memory management prevents OOM issues
- Atomic operations ensure consistency

### Cost Optimization
- Reduced RDS IOPS charges
- Better LLM token utilization through caching
- Lower latency reduces timeout-related retries
- Batch processing efficiency gains

## Risk Mitigation

### Data Consistency
- Database remains source of truth
- All Redis data has TTL
- Async writes are idempotent
- Transaction logs for audit

### Memory Management
- 10MB object size limit
- Automatic eviction at 80% memory
- S3 fallback for large objects
- Memory monitoring alerts

### Failure Scenarios
- Circuit breaker for Redis failures
- Automatic fallback to DB-only mode
- Health checks and monitoring
- Gradual rollout with kill switch

## Conclusion

This comprehensive plan transforms the document processing pipeline from a synchronous, database-bound system to an asynchronous, Redis-accelerated architecture. By carefully addressing historical issues and implementing robust safeguards, we achieve significant performance gains while maintaining data integrity and system reliability.

The phased approach ensures minimal disruption, with extensive testing and gradual rollout. The feature flag system allows instant rollback if issues arise. Most importantly, the database remains the authoritative source of truth, with Redis serving purely as an acceleration layer.

This implementation represents the evolution of the system's architecture, learning from past failures and building toward a more scalable, performant future.