# Context 298: Database Connection Fix Implementation Plan

## Executive Summary
The Celery worker database visibility issue is a critical blocker preventing document processing. After deep analysis, the root cause is **transaction isolation between processes**, not a connection pooling issue. Jules' proposed fixes partially address the symptoms but miss the core problem.

## Root Cause Analysis

### The Real Problem
1. **Test Script Process**: Creates document, commits transaction
2. **Celery Worker Process**: Different process with different connection context
3. **Timing Gap**: Document creation → Celery task submission → Worker lookup
4. **Result**: "Document not found" despite successful creation

### Why Current Approach Fails
```python
# In test script
doc = db_manager.create_source_document(doc_model)  # Commits internally
task = extract_text_from_document.apply_async([doc_uuid, s3_uri])  # Immediate submission

# In Celery worker (different process)
if not validate_document_exists(self.db_manager, document_uuid):  # Can't see document
    raise ValueError(f"Document {document_uuid} not found in database")
```

## Critical Implementation Plan

### Phase 1: Immediate Fix (30 minutes)
**Ensure Document Visibility Before Celery Submission**

1. **Update test_region_fix_complete.py**:
```python
# After creating document
doc = db_manager.create_source_document(doc_model)

# Force visibility verification
max_retries = 5
document_visible = False
for i in range(max_retries):
    # Create fresh connection for verification
    verify_db = DatabaseManager(validate_conformance=False)
    if verify_db.get_source_document(doc_uuid):
        document_visible = True
        break
    time.sleep(0.5)  # Wait 500ms between retries

if not document_visible:
    raise RuntimeError(f"Document {doc_uuid} not visible after {max_retries} attempts")

# NOW safe to submit to Celery
task = extract_text_from_document.apply_async(args=[doc_uuid, s3_uri])
```

2. **Update pdf_tasks.py validate_document_exists**:
```python
def validate_document_exists(db_manager: DatabaseManager, document_uuid: str) -> bool:
    """Validate document exists with retry logic for cross-process visibility."""
    max_attempts = 3
    
    for attempt in range(max_attempts):
        try:
            # Use direct SQL to bypass any caching
            from scripts.rds_utils import DBSessionLocal
            session = DBSessionLocal()
            try:
                result = session.execute(
                    text("SELECT 1 FROM source_documents WHERE document_uuid = :uuid"),
                    {"uuid": str(document_uuid)}
                )
                exists = result.scalar() is not None
                
                if exists:
                    logger.info(f"Document {document_uuid} found on attempt {attempt + 1}")
                    return True
                elif attempt < max_attempts - 1:
                    logger.warning(f"Document {document_uuid} not found, retrying...")
                    time.sleep(1)  # Wait 1 second before retry
                    
            finally:
                session.close()
                
        except Exception as e:
            logger.error(f"Error validating document {document_uuid}: {e}")
            
    logger.error(f"Document {document_uuid} not found after {max_attempts} attempts")
    return False
```

### Phase 2: Configuration Update (10 minutes)
**Optimize Database Pool for Multi-Process**

1. **Update config.py DB_POOL_CONFIG**:
```python
DB_POOL_CONFIG = {
    'pool_size': 5,  # Reduced from 20 for better per-process handling
    'max_overflow': 10,  # Reduced from 40
    'pool_timeout': 30,
    'pool_recycle': 300,  # Recycle every 5 minutes instead of 1 hour
    'pool_pre_ping': True,
    'isolation_level': 'READ COMMITTED',  # Ensure fresh reads
    'connect_args': {
        'connect_timeout': 10,
        'options': '-c statement_timeout=300000',
        'keepalives': 1,
        'keepalives_idle': 30,
        'keepalives_interval': 10,
        'keepalives_count': 5,
        'sslmode': 'require'
    }
}
```

### Phase 3: Worker Process Enhancement (20 minutes)
**Ensure Fresh Connections in Celery Workers**

1. **Update PDFTask base class in pdf_tasks.py**:
```python
class PDFTask(Task):
    """Enhanced base task with connection management"""
    _db_manager = None
    _last_connection_check = None
    
    @property
    def db_manager(self):
        # Check connection freshness every 60 seconds
        now = datetime.utcnow()
        if (self._db_manager is None or 
            self._last_connection_check is None or
            (now - self._last_connection_check).seconds > 60):
            
            # Verify connection or create new
            if self._db_manager:
                try:
                    # Quick ping test
                    session = next(self._db_manager.get_session())
                    session.execute(text("SELECT 1"))
                    session.close()
                except:
                    logger.info("Database connection stale, creating new manager")
                    self._db_manager = None
            
            if self._db_manager is None:
                logger.info("Creating new DatabaseManager for worker")
                self._db_manager = DatabaseManager(validate_conformance=False)
                
            self._last_connection_check = now
            
        return self._db_manager
```

### Phase 4: Production Safety Measures (30 minutes)

1. **Add monitoring for connection issues**:
```python
# In pdf_tasks.py
@app.task
def monitor_db_connectivity():
    """Periodic task to verify database connectivity"""
    db = DatabaseManager(validate_conformance=False)
    try:
        session = next(db.get_session())
        result = session.execute(text("SELECT COUNT(*) FROM source_documents"))
        count = result.scalar()
        logger.info(f"Database connectivity check: {count} documents")
        return {"status": "healthy", "document_count": count}
    except Exception as e:
        logger.error(f"Database connectivity check failed: {e}")
        return {"status": "unhealthy", "error": str(e)}
```

2. **Add circuit breaker for document validation**:
```python
# Track validation failures
validation_failures = defaultdict(int)

def validate_document_with_circuit_breaker(db_manager, document_uuid):
    # If too many failures, fail fast
    if validation_failures[document_uuid] >= 5:
        logger.error(f"Circuit breaker open for document {document_uuid}")
        return False
        
    if validate_document_exists(db_manager, document_uuid):
        validation_failures[document_uuid] = 0  # Reset on success
        return True
    else:
        validation_failures[document_uuid] += 1
        return False
```

## Why This Approach Is Optimal

### Addresses Root Cause
- Ensures document visibility before Celery submission
- Handles cross-process transaction boundaries
- Provides retry logic for timing issues

### Production Ready
- No performance degradation (avoids creating new managers per check)
- Includes monitoring and circuit breakers
- Graceful degradation on failures

### Immediate Impact
- Phase 1 alone should resolve the current blocker
- Can be implemented and tested within 1 hour
- No architectural changes required

## Testing Protocol

1. **Unit Test**: Verify retry logic in validate_document_exists
2. **Integration Test**: Run test_region_fix_complete.py with fixes
3. **Load Test**: Submit 10 documents rapidly to verify under load
4. **Monitoring**: Check logs for retry attempts and timing

## Risk Mitigation

- **Retry delays**: Capped at 3 attempts with 1-second delays
- **Connection freshness**: Checked every 60 seconds, not per request
- **Circuit breaker**: Prevents infinite retry loops
- **Monitoring**: Tracks connectivity issues proactively

## Conclusion

This plan addresses the mission-critical database visibility issue with minimal risk and maximum effectiveness. The phased approach allows for immediate resolution while building in production safeguards. The key insight is that this is a **transaction visibility** problem, not a connection pooling problem, requiring explicit verification before cross-process operations.