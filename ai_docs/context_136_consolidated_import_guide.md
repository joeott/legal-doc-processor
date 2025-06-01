# Context 136: Consolidated Client Import Guide

This guide provides the production-ready workflow for importing client files using the consolidated monitoring system that leverages existing infrastructure.

## Prerequisites

1. **Apply Database Migration**:
   ```bash
   # Apply import session tracking migration through Supabase dashboard
   # File: frontend/database/migrations/00017_add_import_sessions.sql
   ```

2. **Environment Setup**:
   ```bash
   export PYTHONPATH=/path/to/project:$PYTHONPATH
   source .env  # Load all required environment variables
   ```

## Step-by-Step Import Process

### Step 1: Analyze Client Files
Use the new analysis script to understand what will be imported:

```bash
python scripts/analyze_client_files.py /path/to/client/files \
    --case-name "Client Name (Case Reference)" \
    --output client_manifest.json
```

This generates a manifest with:
- File inventory and deduplication
- Cost estimates
- Processing requirements
- Folder categorization

### Step 2: Start Background Services

#### Terminal 1: Celery Workers
```bash
celery -A scripts.celery_app worker --loglevel=info --concurrency=4 \
    --queues=default,ocr,text,entity,graph,embeddings
```

#### Terminal 2: Flower Monitor (Web UI)
```bash
celery -A scripts.celery_app flower
# Access at http://localhost:5555
```

#### Terminal 3: Pipeline Monitor (Console)
```bash
python scripts/standalone_pipeline_monitor.py --refresh-interval 5
# This now includes import session tracking
```

### Step 3: Import Documents

#### Dry Run First
```bash
python scripts/import_from_manifest.py client_manifest.json \
    --dry-run \
    --workers 4 \
    --batch-size 50
```

#### Full Import
```bash
python scripts/import_from_manifest.py client_manifest.json \
    --workers 4 \
    --batch-size 50
```

The import will:
1. Create/reuse project in Supabase
2. Create import session for tracking
3. Check for existing documents (deduplication)
4. Upload files to S3 in batches
5. Submit to Celery for processing
6. Track costs in real-time
7. Update progress in database

### Step 4: Monitor Progress

#### Option 1: Flower Web UI
Navigate to http://localhost:5555 to see:
- Active tasks by type
- Worker status
- Task history
- Queue depths

#### Option 2: Enhanced Pipeline Monitor
The `standalone_pipeline_monitor.py` now shows:
- Document processing stages
- Celery queue depths
- Redis cache statistics
- Active import sessions with progress
- Recent failures
- Cost tracking

#### Option 3: Check Specific Import
```bash
# Check specific import session
python scripts/check_import_completion.py --session SESSION_ID

# Check recent imports
python scripts/check_import_completion.py --recent 24
```

### Step 5: Verify Completion

```bash
# Basic verification
python scripts/check_import_completion.py --session SESSION_ID

# For detailed verification, use existing tools:
python scripts/check_celery_status.py
python scripts/validate_graph_completion.py --project PROJECT_ID
```

## Key Differences from Original Plan

### What We Kept
1. **analyze_client_files.py** - Valuable pre-import analysis
2. **Cost tracking** - Now in Supabase instead of SQLite
3. **Manifest-based import** - Structured import process

### What We Consolidated
1. **Monitoring**: Use Flower + enhanced standalone_pipeline_monitor.py
2. **Import tracking**: Supabase tables instead of SQLite
3. **Document submission**: Reuse existing celery_submission.py
4. **Verification**: Extended existing scripts

### What We Removed
1. **import_dashboard.py** - Redundant with Flower
2. **import_tracker.py** - SQLite replaced with Supabase
3. **import_client_files.py** - Replaced with simpler import_from_manifest.py
4. **verify_import.py** - Use existing verification tools

## Production Workflow Example

```bash
# 1. Clear test data if needed
python scripts/cleanup_database.py --project TEST_PROJECT_ID

# 2. Analyze files
python scripts/analyze_client_files.py /Volumes/ClientDrive/CaseFiles \
    --case-name "Smith v. Jones (2024)" \
    --output smith_jones_manifest.json

# 3. Start services (each in separate terminal)
# Terminal 1:
celery -A scripts.celery_app worker --loglevel=info --concurrency=4 \
    --queues=default,ocr,text,entity,graph,embeddings

# Terminal 2:
celery -A scripts.celery_app flower

# Terminal 3:
python scripts/standalone_pipeline_monitor.py

# 4. Import documents
python scripts/import_from_manifest.py smith_jones_manifest.json \
    --workers 6 --batch-size 100

# 5. Monitor until complete
# Watch Flower UI or pipeline monitor

# 6. Verify
python scripts/check_import_completion.py --recent 1
```

## Cost Tracking

Costs are now tracked in the `processing_costs` table and aggregated in `import_sessions`:

```sql
-- View import costs
SELECT 
    s.case_name,
    s.total_files,
    s.processed_files,
    s.total_cost,
    s.cost_breakdown
FROM import_sessions s
WHERE s.id = 'SESSION_ID';

-- Detailed cost breakdown
SELECT 
    service,
    operation,
    SUM(units) as total_units,
    SUM(total_cost) as total_cost
FROM processing_costs
WHERE import_session_id = 'SESSION_ID'
GROUP BY service, operation;
```

## Troubleshooting

### Check Import Session Status
```bash
python scripts/check_import_completion.py --session SESSION_ID
```

### Debug Stuck Documents
```bash
# Check specific document
python scripts/debug_celery_document.py --uuid DOCUMENT_UUID

# Check all stuck documents
python scripts/debug_celery_document.py --stuck 30
```

### Monitor Redis/Celery Health
```bash
# Check Redis connection
python scripts/test_redis_connection.py

# Check Celery workers
celery -A scripts.celery_app inspect active
celery -A scripts.celery_app inspect stats
```

## Benefits of Consolidated Approach

1. **Single Source of Truth**: All data in Supabase
2. **Unified Monitoring**: One view for all activity
3. **Proven Infrastructure**: Reuses battle-tested code
4. **Simpler Operations**: Fewer scripts and databases
5. **Better Integration**: Seamless with existing pipeline

This consolidated approach maintains all functionality while reducing complexity and leveraging the robust monitoring systems already in place.