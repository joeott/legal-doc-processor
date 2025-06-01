# Context 229: Pragmatic RDS Migration for Scripts (Revised)

**Date**: 2025-05-30
**Type**: Minimal Migration Plan
**Status**: SIMPLIFIED APPROACH
**Philosophy**: Change only what's necessary, preserve what works

## Executive Summary

This revised plan takes a minimalist approach to migrating `/scripts/` from Supabase to RDS. We preserve all existing functionality, workers, and flow while making only the essential changes for database compatibility. No architectural changes, no new patterns - just pragmatic updates.

## Core Principle: Minimal Viable Changes

### What We KEEP (No Changes)
- ✅ All Celery workers and task definitions
- ✅ Current file storage in S3
- ✅ Existing database relationships
- ✅ Current error handling that works
- ✅ Directory structure as-is
- ✅ All processing logic

### What We MUST Change
- ❌ Supabase connection strings → RDS
- ❌ Supabase-specific imports → PostgreSQL/SQLAlchemy
- ❌ Remove `supabase_utils.py`
- ❌ Update `database.py` connection only

## Implementation: 3 Simple Steps

### Step 1: Update Database Connection

**In `database.py`** - Just change the connection:
```python
# OLD (Supabase)
# from supabase import create_client
# supabase = create_client(url, key)

# NEW (RDS) - Minimal change
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Use existing DATABASE_URL from .env
DATABASE_URL = os.getenv('DATABASE_URL')

# Simple engine with basic retry
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,  # This alone handles most connection issues
    pool_recycle=3600    # Recycle connections after 1 hour
)

SessionLocal = sessionmaker(bind=engine)

# Keep the same session pattern used elsewhere
def get_db():
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except:
        db.rollback()
        raise
    finally:
        db.close()
```

### Step 2: Replace Supabase Utils

**Create minimal `rds_utils.py`** to replace `supabase_utils.py`:
```python
"""Minimal RDS utilities to replace Supabase-specific functions"""

from database import SessionLocal, get_db
from sqlalchemy import text
import logging

logger = logging.getLogger(__name__)

def test_connection():
    """Test database connection"""
    try:
        db = next(get_db())
        result = db.execute(text("SELECT 1"))
        return bool(result.scalar())
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return False
    finally:
        db.close()

def execute_query(query: str, params: dict = None):
    """Execute a query - direct replacement for supabase.rpc()"""
    db = next(get_db())
    try:
        result = db.execute(text(query), params or {})
        return result.fetchall()
    except Exception as e:
        logger.error(f"Query execution failed: {e}")
        raise
    finally:
        db.close()

# Add other minimal replacements as needed
```

### Step 3: Update Imports Only Where Needed

**Simple find/replace in affected files:**
```python
# Find all files using supabase
# grep -r "from supabase" scripts/
# grep -r "import supabase" scripts/

# Replace:
# from supabase_utils import X
# with:
# from rds_utils import X

# No logic changes, just import updates
```

## What We DON'T Change

### 1. Keep Existing Models
The current SQLAlchemy models in `database.py` already work with PostgreSQL. No changes needed beyond connection.

### 2. Keep Celery Tasks As-Is
All tasks in `pdf_tasks.py`, `celery_app.py` etc. remain unchanged. They already use SQLAlchemy sessions.

### 3. Keep Current Error Handling
The existing error handling in `core/error_handler.py` works fine. No changes.

### 4. Keep Directory Structure
```
/scripts/
├── Everything stays exactly where it is
├── Just add rds_utils.py
├── Update database.py connection
└── Update imports where needed
```

## Connection Resilience (Simple)

Instead of complex retry logic, use SQLAlchemy's built-in features:

```python
# In database.py, this is ALL we need:
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,      # Checks connection before use
    pool_recycle=3600,       # Recycle stale connections
    connect_args={
        "connect_timeout": 10,
        "options": "-c statement_timeout=30000"
    }
)
```

This handles 99% of connection issues without any custom code.

## Testing Strategy (Pragmatic)

1. **Connection Test**
   ```bash
   python -c "from database import test_connection; print(test_connection())"
   ```

2. **Run Existing Tests**
   ```bash
   # Your existing test suite should just work
   pytest tests/
   ```

3. **Test One Document**
   ```bash
   python scripts/submit_single_document.py --file test.pdf
   ```

## Migration Checklist

### Phase 1: Preparation (30 minutes)
- [ ] Ensure `.env` has `DATABASE_URL` for RDS
- [ ] Back up any critical data
- [ ] Have SSH tunnel ready for testing

### Phase 2: Code Changes (1 hour)
- [ ] Update `database.py` connection (5 min)
- [ ] Create `rds_utils.py` (15 min)
- [ ] Find/replace Supabase imports (20 min)
- [ ] Remove `supabase_utils.py` (1 min)
- [ ] Test connection (5 min)

### Phase 3: Verification (30 minutes)
- [ ] Run existing test suite
- [ ] Process one test document
- [ ] Check Celery workers start properly
- [ ] Verify database queries work

## Risk Mitigation

1. **Minimal Changes** = Minimal Risk
   - We're not refactoring architecture
   - We're not changing business logic
   - We're not moving files around

2. **Easy Rollback**
   - Just revert 3-4 files in git
   - Switch DATABASE_URL back to Supabase

3. **Gradual Testing**
   - Test with single document first
   - Monitor for 24 hours
   - Then full production load

## Future Extensibility (Preserved)

By keeping the current structure:
- Stage 2 local model swap remains trivial
- Can add new document types easily
- Can enhance monitoring later if needed
- Can optimize queries when actually needed

## What About Performance?

Current performance is acceptable for 450 documents. Optimizations can wait until:
- We have 10x more documents
- We identify actual bottlenecks
- We have metrics showing issues

Premature optimization is the root of all evil.

## Summary

This pragmatic approach:
- **Changes only 3-4 files**
- **Preserves all working code**
- **Maintains current architecture**
- **Reduces migration risk to near zero**
- **Can be completed in 2 hours**
- **Requires no new patterns to learn**

The beauty is in what we DON'T change. The existing system works well - we're just swapping the database connection layer. Everything else continues functioning exactly as before, with the same workers, same flow, same quality guarantees.

## Next Steps

1. Update `database.py` (5 minutes)
2. Create `rds_utils.py` (15 minutes)
3. Update imports (20 minutes)
4. Test with one document
5. Deploy with confidence

No architectural astronautics. Just pragmatic engineering.