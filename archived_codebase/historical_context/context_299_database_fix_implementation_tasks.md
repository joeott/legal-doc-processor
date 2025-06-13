# Context 299: Database Fix Implementation Tasks with Verification Criteria

## Phase 1: Immediate Fix Tasks (Priority: CRITICAL)

### Task 1.1: Update test_region_fix_complete.py
**File**: `scripts/test_region_fix_complete.py`
**Changes**: Add document visibility verification before Celery submission

```python
# Insert after line 89 (doc = db_manager.create_source_document(doc_model))
# Add visibility verification loop
max_retries = 5
document_visible = False
for i in range(max_retries):
    verify_db = DatabaseManager(validate_conformance=False)
    if verify_db.get_source_document(doc_uuid):
        document_visible = True
        print(f"   ✓ Document visibility confirmed on attempt {i+1}")
        break
    time.sleep(0.5)
    if i > 0:
        print(f"   ⟳ Retrying visibility check (attempt {i+1}/{max_retries})...")

if not document_visible:
    print(f"   ❌ Document not visible after {max_retries} attempts")
    raise RuntimeError(f"Document {doc_uuid} not visible after {max_retries} attempts")
```

**Verification Criteria**:
- [ ] Script shows "Document visibility confirmed" message
- [ ] No RuntimeError raised for visibility
- [ ] Celery task receives document that exists in database
- [ ] Test progresses past step 7 without "Document not found" error

### Task 1.2: Update validate_document_exists in pdf_tasks.py
**File**: `scripts/pdf_tasks.py`
**Line**: 191-200 (replace entire function)

```python
def validate_document_exists(db_manager: DatabaseManager, document_uuid: str) -> bool:
    """Validate document exists with retry logic for cross-process visibility."""
    import time
    from scripts.rds_utils import DBSessionLocal
    from sqlalchemy import text
    
    max_attempts = 3
    
    for attempt in range(max_attempts):
        try:
            # Use direct SQL to bypass any caching
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
                    logger.warning(f"Document {document_uuid} not found on attempt {attempt + 1}, retrying...")
                    time.sleep(1)  # Wait 1 second before retry
                    
            finally:
                session.close()
                
        except Exception as e:
            logger.error(f"Error validating document {document_uuid} on attempt {attempt + 1}: {e}")
            if attempt < max_attempts - 1:
                time.sleep(1)
            
    logger.error(f"Document {document_uuid} not found after {max_attempts} attempts")
    return False
```

**Verification Criteria**:
- [ ] Function includes retry logic with 3 attempts
- [ ] Logs show retry attempts when document not immediately found
- [ ] Function uses direct SQL query, not db_manager methods
- [ ] 1-second delay between retries
- [ ] Returns True when document found on any attempt

### Task 1.3: Add necessary imports
**File**: `scripts/pdf_tasks.py`
**Line**: Add at top with other imports (around line 10)

```python
import time
from collections import defaultdict
```

**Verification Criteria**:
- [ ] No import errors when running tasks
- [ ] `time` module available for sleep calls
- [ ] `defaultdict` available for Phase 4 circuit breaker

## Phase 2: Configuration Update Tasks

### Task 2.1: Update DB_POOL_CONFIG
**File**: `scripts/config.py`
**Line**: Find `DB_POOL_CONFIG` dictionary (around line 250)

```python
DB_POOL_CONFIG = {
    'pool_size': 5,  # Reduced from 20 for better per-process handling
    'max_overflow': 10,  # Reduced from 40
    'pool_timeout': 30,
    'pool_recycle': 300,  # Recycle every 5 minutes instead of 3600 (1 hour)
    'pool_pre_ping': True,
    'isolation_level': 'READ COMMITTED',  # Add this line
    'connect_args': {
        'connect_timeout': 10,
        'options': '-c statement_timeout=300000',
        'keepalives': 1,
        'keepalives_idle': 30,
        'keepalives_interval': 10,
        'keepalives_count': 5,
        'sslmode': DB_SSL_MODE  # Ensure this uses the config value
    }
}
```

**Verification Criteria**:
- [ ] `isolation_level` set to 'READ COMMITTED'
- [ ] `pool_recycle` reduced to 300 seconds
- [ ] `pool_size` reduced to 5
- [ ] No startup errors when importing config
- [ ] Database connections work with new settings

## Phase 3: Worker Enhancement Tasks

### Task 3.1: Enhance PDFTask base class
**File**: `scripts/pdf_tasks.py`
**Line**: Find `class PDFTask(Task):` (around line 90)

```python
class PDFTask(Task):
    """Enhanced base task with connection management"""
    _db_manager = None
    _last_connection_check = None
    
    @property
    def db_manager(self):
        from datetime import datetime
        
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
                    logger.debug("Database connection verified")
                except Exception as e:
                    logger.info(f"Database connection stale ({e}), creating new manager")
                    self._db_manager = None
            
            if self._db_manager is None:
                logger.info("Creating new DatabaseManager for worker")
                self._db_manager = DatabaseManager(validate_conformance=False)
                
            self._last_connection_check = now
            
        return self._db_manager

    def validate_conformance(self):
        """Validate model conformance for database operations"""
        if os.getenv('SKIP_CONFORMANCE_CHECK', '').lower() == 'true':
            logger.debug(f"Skipping conformance check for task {self.name}")
            return
            
        try:
            from scripts.db import ConformanceValidator
            validator = ConformanceValidator(self.db_manager)
            is_valid, errors = validator.validate_models()
            
            if not is_valid:
                error_msg = f"Model conformance validation failed:\n" + "\n".join(errors)
                logger.error(error_msg)
                if os.getenv('ENVIRONMENT') == 'production':
                    raise ValueError(error_msg)
                else:
                    logger.warning("Continuing despite conformance errors (non-production)")
        except ImportError:
            logger.warning("ConformanceValidator not available, skipping validation")
        except Exception as e:
            logger.error(f"Conformance validation error: {e}")
            if os.getenv('ENVIRONMENT') == 'production':
                raise
```

**Verification Criteria**:
- [ ] Connection freshness checked every 60 seconds
- [ ] Stale connections detected and replaced
- [ ] Logs show "Creating new DatabaseManager" when needed
- [ ] No connection timeout errors during long-running tasks
- [ ] Existing conformance validation still works

## Phase 4: Production Safety Tasks

### Task 4.1: Add monitoring task
**File**: `scripts/pdf_tasks.py`
**Line**: Add after the last task definition (end of file)

```python
@app.task(name='monitor_db_connectivity')
def monitor_db_connectivity():
    """Periodic task to verify database connectivity"""
    from scripts.db import DatabaseManager
    from sqlalchemy import text
    
    db = DatabaseManager(validate_conformance=False)
    try:
        session = next(db.get_session())
        result = session.execute(text("SELECT COUNT(*) FROM source_documents"))
        count = result.scalar()
        session.close()
        
        logger.info(f"Database connectivity check: {count} documents")
        return {"status": "healthy", "document_count": count, "timestamp": datetime.utcnow().isoformat()}
    except Exception as e:
        logger.error(f"Database connectivity check failed: {e}")
        return {"status": "unhealthy", "error": str(e), "timestamp": datetime.utcnow().isoformat()}
```

**Verification Criteria**:
- [ ] Task can be called via Celery beat or manually
- [ ] Returns document count when healthy
- [ ] Returns error details when unhealthy
- [ ] Logs include connectivity status

### Task 4.2: Add circuit breaker
**File**: `scripts/pdf_tasks.py`
**Line**: Add after imports, before PDFTask class

```python
# Circuit breaker for document validation
validation_failures = defaultdict(int)
CIRCUIT_BREAKER_THRESHOLD = 5

def validate_document_with_circuit_breaker(db_manager: DatabaseManager, document_uuid: str) -> bool:
    """Validate document with circuit breaker pattern"""
    # If too many failures, fail fast
    if validation_failures[document_uuid] >= CIRCUIT_BREAKER_THRESHOLD:
        logger.error(f"Circuit breaker OPEN for document {document_uuid} (>= {CIRCUIT_BREAKER_THRESHOLD} failures)")
        return False
        
    if validate_document_exists(db_manager, document_uuid):
        if validation_failures[document_uuid] > 0:
            logger.info(f"Document {document_uuid} found, resetting circuit breaker")
        validation_failures[document_uuid] = 0  # Reset on success
        return True
    else:
        validation_failures[document_uuid] += 1
        logger.warning(f"Document {document_uuid} validation failed (count: {validation_failures[document_uuid]})")
        return False
```

**Verification Criteria**:
- [ ] Circuit breaker prevents more than 5 validation attempts
- [ ] Failure count resets on successful validation
- [ ] Logs show circuit breaker status
- [ ] No infinite retry loops

## Test Execution Plan

### Test 1: Basic Functionality Test
```bash
cd /opt/legal-doc-processor
source load_env.sh
export S3_BUCKET_REGION=us-east-2
export PYTHONPATH=/opt/legal-doc-processor:$PYTHONPATH
python3 scripts/test_region_fix_complete.py
```

**Success Criteria**:
- [ ] All 8 stages show ✓ checkmarks
- [ ] No "Document not found in database" errors
- [ ] Task completes with status "completed"
- [ ] Chunks created > 0

### Test 2: Rapid Submission Test
```bash
# Create test script for multiple documents
cat > scripts/test_rapid_submission.py << 'EOF'
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.test_region_fix_complete import test_complete_region_fix
import time

print("Testing rapid document submission...")
for i in range(3):
    print(f"\n{'='*60}\nDocument {i+1} of 3\n{'='*60}")
    test_complete_region_fix()
    if i < 2:
        print("\nWaiting 2 seconds before next submission...")
        time.sleep(2)

print("\nRapid submission test complete!")
EOF

python3 scripts/test_rapid_submission.py
```

**Success Criteria**:
- [ ] All 3 documents process successfully
- [ ] No database visibility errors
- [ ] Retry logic visible in logs if needed

### Test 3: Worker Restart Test
```bash
# Restart workers to test fresh connections
sudo supervisorctl restart celery:*

# Wait for workers to start
sleep 10

# Run test again
python3 scripts/test_region_fix_complete.py
```

**Success Criteria**:
- [ ] Workers start without errors
- [ ] First document after restart processes successfully
- [ ] Logs show "Creating new DatabaseManager for worker"

### Test 4: Monitoring Test
```bash
# Test monitoring task
python3 -c "
from scripts.celery_app import app
result = app.send_task('monitor_db_connectivity')
print(result.get(timeout=10))
"
```

**Success Criteria**:
- [ ] Returns status "healthy"
- [ ] Shows correct document count
- [ ] Includes timestamp

## Rollback Plan

If issues occur:
1. Revert `scripts/pdf_tasks.py` to original
2. Revert `scripts/config.py` DB_POOL_CONFIG
3. Remove visibility check from test scripts
4. Document specific failure points for analysis

## Success Metrics

- **Primary**: test_region_fix_complete.py completes successfully
- **Secondary**: All 4 tests pass without errors
- **Performance**: Document validation takes < 3 seconds (including retries)
- **Reliability**: 0% failure rate after implementation
- **Monitoring**: Database connectivity checks return "healthy"