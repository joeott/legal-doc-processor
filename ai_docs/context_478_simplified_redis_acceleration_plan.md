# Context 478: Simplified Redis Acceleration Implementation Plan

## Date: January 9, 2025

## Executive Summary

This document presents a dramatically simplified Redis acceleration plan that achieves the core goal of 30-40% performance improvement while adhering to the principle of "absolute simplest solution; function over form; short code over long." The plan modifies existing scripts without creating new ones and can be verified with actual production data.

## Core Principle: Simplicity First

**What We're Doing**: Replace blocking database reads between pipeline stages with fast Redis reads.

**What We're NOT Doing (in V1)**:
- S3 fallback for large objects
- Custom memory eviction logic
- Async database writes
- Complex pre-warming strategies
- Rich LLM context building

## The Simplest Possible Implementation

### 1. Minimal Redis Manager Enhancement (50 lines)

**File**: `scripts/cache.py` (modify existing `RedisManager`)

```python
# Add these methods to existing RedisManager class (after line 735)

def set_with_ttl(self, key: str, value: Any, ttl: int = 3600) -> bool:
    """Set cache with TTL. Skip if too large."""
    try:
        # Simple size check - skip large objects
        data = pickle.dumps(value) if not isinstance(value, str) else value.encode()
        if len(data) > 5 * 1024 * 1024:  # 5MB limit
            logger.warning(f"Skipping cache for {key} - too large ({len(data)} bytes)")
            return False
            
        return self.set_cached(key, value, expire=ttl)
    except Exception as e:
        logger.error(f"Cache set failed for {key}: {e}")
        return False

def get_with_fallback(self, key: str, fallback_func: Callable) -> Optional[Any]:
    """Get from cache or fallback to function (usually DB query)."""
    try:
        # Try cache first
        value = self.get_cached(key)
        if value is not None:
            logger.debug(f"Cache hit for {key}")
            return value
    except Exception as e:
        logger.warning(f"Cache error for {key}: {e}")
    
    # Fallback
    logger.debug(f"Cache miss for {key}, using fallback")
    return fallback_func()

# Simple circuit breaker
_redis_failures = 0
_redis_disabled_until = None

def is_redis_healthy(self) -> bool:
    """Simple circuit breaker - disable Redis for 5 minutes after 5 failures."""
    global _redis_failures, _redis_disabled_until
    
    if _redis_disabled_until and datetime.utcnow() < _redis_disabled_until:
        return False
        
    try:
        self.redis_client.ping()
        _redis_failures = 0  # Reset on success
        return True
    except:
        _redis_failures += 1
        if _redis_failures >= 5:
            _redis_disabled_until = datetime.utcnow() + timedelta(minutes=5)
            logger.error("Redis circuit breaker opened - disabled for 5 minutes")
        return False
```

### 2. Update Pipeline Tasks (Simple Pattern)

**File**: `scripts/pdf_tasks.py`

The pattern for EVERY stage is identical:
1. Try to read input from Redis
2. Fall back to DB if not in Redis
3. Process the data
4. Write output to Redis
5. Save to DB (synchronously)
6. Trigger next stage

```python
# Example: Update extract_text_from_document (line 520)
@app.task(bind=True, name='scripts.pdf_tasks.extract_text_from_document', queue='ocr')
def extract_text_from_document(self, document_uuid: str, file_path: Optional[str] = None):
    """Extract text with Redis acceleration - SIMPLIFIED."""
    logger.info(f"Starting OCR extraction for document {document_uuid}")
    
    redis_manager = get_redis_manager()
    cache_key = CacheKeys.doc_ocr(document_uuid)
    
    # 1. Check Redis first
    if redis_manager.is_redis_healthy():
        cached_result = redis_manager.get_cached(cache_key)
        if cached_result:
            logger.info(f"Using cached OCR result for {document_uuid}")
            # Still chain to next stage
            continue_pipeline_after_ocr.apply_async(
                args=[cached_result, document_uuid],
                queue='text'
            )
            return cached_result
    
    # 2. Process normally
    db = DatabaseManager()
    session = next(db.get_session())
    
    # ... existing OCR logic ...
    
    result = {
        'status': 'success',
        'text': extracted_text,
        'page_count': page_count
    }
    
    # 3. Cache result (ignore failures)
    if redis_manager.is_redis_healthy():
        redis_manager.set_with_ttl(cache_key, result, ttl=86400)
    
    # 4. Save to DB (synchronously - simple!)
    try:
        doc.raw_extracted_text = extracted_text
        doc.textract_job_id = job_id
        doc.textract_job_status = 'SUCCEEDED'
        session.commit()
    except Exception as e:
        session.rollback()
        raise
    finally:
        session.close()
    
    # 5. Chain to next stage
    continue_pipeline_after_ocr.apply_async(
        args=[result, document_uuid],
        queue='text'
    )
    
    return result

# Update chunk_document_text (line 850) - SAME PATTERN
@app.task(name='scripts.pdf_tasks.chunk_document_text', queue='text')
def chunk_document_text(ocr_result: Dict, document_uuid: str):
    """Create chunks using Redis acceleration - SIMPLIFIED."""
    logger.info(f"Starting text chunking for document {document_uuid}")
    
    redis_manager = get_redis_manager()
    
    # 1. Get OCR text (from passed result or Redis or DB)
    if isinstance(ocr_result, dict) and ocr_result.get('status') == 'success':
        text = ocr_result.get('text', '')
    else:
        # Try Redis, then DB
        text = redis_manager.get_with_fallback(
            CacheKeys.doc_ocr(document_uuid),
            lambda: get_ocr_text_from_db(document_uuid)  # Simple DB function
        )
    
    if not text:
        raise ValueError("No text available for chunking")
    
    # 2. Create chunks
    chunks = create_semantic_chunks(text, document_uuid)
    
    # 3. Cache chunks
    if redis_manager.is_redis_healthy():
        chunks_data = [chunk.dict() for chunk in chunks]
        redis_manager.set_with_ttl(
            CacheKeys.doc_chunks(document_uuid),
            chunks_data,
            ttl=86400
        )
    
    # 4. Save to DB (synchronously)
    db = DatabaseManager()
    session = next(db.get_session())
    try:
        for chunk in chunks:
            session.add(chunk)
        session.commit()
    except Exception as e:
        session.rollback()
        raise
    finally:
        session.close()
    
    # 5. Chain to entity extraction
    extract_entities_from_chunks.apply_async(
        args=[chunks_data if redis_manager.is_redis_healthy() else None, document_uuid],
        queue='entity'
    )
    
    return {'status': 'success', 'chunk_count': len(chunks)}
```

### 3. Simple Helper Functions

**File**: `scripts/pdf_tasks.py` (add these simple DB fallback functions)

```python
# Add these simple DB query functions for fallback
def get_ocr_text_from_db(document_uuid: str) -> Optional[str]:
    """Simple DB query for OCR text."""
    db = DatabaseManager()
    session = next(db.get_session())
    try:
        doc = session.query(SourceDocumentMinimal).filter_by(
            document_uuid=document_uuid
        ).first()
        return doc.raw_extracted_text if doc else None
    finally:
        session.close()

def get_chunks_from_db(document_uuid: str) -> List[Dict]:
    """Simple DB query for chunks."""
    db = DatabaseManager()
    session = next(db.get_session())
    try:
        chunks = session.query(DocumentChunkMinimal).filter_by(
            document_uuid=document_uuid
        ).order_by(DocumentChunkMinimal.chunk_index).all()
        return [chunk.dict() for chunk in chunks]
    finally:
        session.close()

def get_entities_from_db(document_uuid: str) -> List[Dict]:
    """Simple DB query for entities."""
    db = DatabaseManager()
    session = next(db.get_session())
    try:
        entities = session.query(EntityMentionMinimal).filter_by(
            document_uuid=document_uuid
        ).all()
        return [entity.dict() for entity in entities]
    finally:
        session.close()
```

### 4. Update Entity Service (Same Pattern)

**File**: `scripts/entity_service.py`

```python
# Simplify extract_entities_from_chunks (line 275)
def extract_entities_from_chunks_simple(
    self,
    chunks_input: Optional[List[Dict]],
    document_uuid: str
) -> List[EntityMentionMinimal]:
    """Extract entities with simplified Redis usage."""
    
    # 1. Get chunks (from input or Redis or DB)
    if chunks_input:
        chunks = chunks_input
    else:
        chunks = self.redis_manager.get_with_fallback(
            CacheKeys.doc_chunks(document_uuid),
            lambda: get_chunks_from_db(document_uuid)
        )
    
    if not chunks:
        return []
    
    all_entities = []
    
    # 2. Process each chunk (simple - no complex context)
    for chunk in chunks:
        chunk_entities = self.extract_entities_from_chunk(
            chunk_text=chunk['text'],
            chunk_uuid=chunk['chunk_uuid'],
            document_uuid=document_uuid
        )
        all_entities.extend(chunk_entities)
    
    # 3. Cache results
    if self.redis_manager.is_redis_healthy():
        self.redis_manager.set_with_ttl(
            CacheKeys.doc_entity_mentions(document_uuid),
            [e.dict() for e in all_entities],
            ttl=86400
        )
    
    # 4. Save to DB (synchronously)
    session = next(self.db.get_session())
    try:
        for entity in all_entities:
            session.add(entity)
        session.commit()
    except Exception as e:
        session.rollback()
        raise
    finally:
        session.close()
    
    return all_entities
```

## Verification Criteria

### 1. Functional Test with Single Document

```bash
# Process one document and verify Redis acceleration
python process_test_document.py /path/to/test.pdf

# Check Redis usage
redis-cli -h $REDIS_HOST -p $REDIS_PORT -a $REDIS_PASSWORD
> KEYS doc:*
# Should see: doc:ocr:*, doc:chunks:*, doc:entity_mentions:*, etc.

# Check timing improvement
# Before: ~60 seconds (with DB reads between stages)
# After: ~40 seconds (with Redis reads between stages)
```

### 2. Performance Metrics

```sql
-- Check stage transitions are faster
SELECT 
    task_type,
    AVG(EXTRACT(EPOCH FROM (completed_at - created_at))) as avg_seconds
FROM processing_tasks
WHERE created_at > NOW() - INTERVAL '1 hour'
GROUP BY task_type;
```

### 3. Fallback Test

```bash
# Stop Redis
sudo systemctl stop redis

# Process document - should still work (slower)
python process_test_document.py /path/to/test.pdf

# Verify it completed using DB fallbacks
```

### 4. Production Data Test

```bash
# Submit batch from input_docs
python batch_submit_2_documents.py

# Monitor with existing tools
python scripts/cli/monitor.py live

# Verify all stages complete
```

## Implementation Timeline (Simplified)

### Day 1: Redis Manager Updates
- [ ] Add 3 methods to RedisManager (50 lines)
- [ ] Test circuit breaker with redis-cli

### Day 2: OCR and Chunking
- [ ] Update extract_text_from_document
- [ ] Update chunk_document_text
- [ ] Add simple DB fallback functions
- [ ] Test with single document

### Day 3: Entity Processing
- [ ] Update extract_entities_from_chunks
- [ ] Update resolve_entities_simple
- [ ] Test entity extraction with cache

### Day 4: Final Stages
- [ ] Update relationship building
- [ ] Update pipeline completion
- [ ] Full pipeline test

### Day 5: Production Testing
- [ ] Process 10 documents from input_docs
- [ ] Verify 30%+ performance improvement
- [ ] Test fallback scenarios

## Configuration

Add to `.env`:
```bash
# Redis acceleration (simple flags)
REDIS_ACCELERATION_ENABLED=true
REDIS_ACCELERATION_TTL_HOURS=24
```

Update `scripts/config.py`:
```python
# Simple feature flag
REDIS_ACCELERATION_ENABLED = env.bool('REDIS_ACCELERATION_ENABLED', default=False)
```

## What This Achieves

1. **30-40% Performance Gain**: By eliminating DB reads between stages
2. **Simplicity**: ~200 lines of changes total (vs 2000+ in complex plan)
3. **Safety**: Circuit breaker and DB fallbacks ensure reliability
4. **No New Scripts**: Only modifies existing files
5. **Production Ready**: Can test with real data immediately

## What We Deferred to V2

1. S3 fallback for large objects
2. Custom memory eviction
3. Async DB writes
4. Batch pre-warming
5. Rich LLM context building
6. Complex monitoring

## Summary

This simplified plan achieves the core Redis acceleration goal with minimal complexity. The implementation pattern is identical for every stage:

1. Check Redis
2. Fall back to DB if needed
3. Process data
4. Save to Redis
5. Save to DB
6. Trigger next stage

This consistency makes it easy to implement, test, and debug. The entire implementation can be completed in one week with immediate production benefits.