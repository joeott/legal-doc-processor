# Context 135: Monitoring System Consolidation Plan

## Executive Summary

After reviewing the existing monitoring infrastructure and newly created import scripts, there is significant duplication of functionality. This document outlines a consolidation plan to create a unified production flow leveraging existing systems.

## Duplicate Functionality Analysis

### 1. **Monitoring Dashboards**

**Existing:**
- `standalone_pipeline_monitor.py` - Comprehensive Celery/Redis monitoring
- `enhanced_pipeline_monitor.py` - Cache visualization and analytics
- Flower (http://localhost:5555) - Web-based Celery monitoring

**New (Duplicate):**
- `import_dashboard.py` - Curses-based import monitoring

**Consolidation:** The new import dashboard duplicates Flower's functionality. We should extend `standalone_pipeline_monitor.py` to include import session tracking.

### 2. **Document Submission & Tracking**

**Existing:**
- `test_celery_e2e.py` - Batch document submission with tracking
- `celery_submission.py` - Core submission functionality
- Database tables: `source_documents` with `celery_status` field

**New (Duplicate):**
- `import_client_files.py` - Batch import with SQLite tracking
- `import_tracker.py` - SQLite-based session management

**Consolidation:** SQLite tracking is redundant when we have Supabase. Should integrate session tracking into existing database schema.

### 3. **Cost Tracking**

**Existing:**
- None (this is a genuine gap)

**New (Valuable):**
- Cost estimation in `analyze_client_files.py`
- Cost tracking in `import_tracker.py`

**Consolidation:** Keep cost tracking but integrate into Supabase instead of SQLite.

### 4. **Verification & Validation**

**Existing:**
- `validate_graph_completion.py` - Graph validation
- `check_celery_status.py` - Simple status checking
- `test_error_recovery.py` - Error pattern analysis

**New (Partially Duplicate):**
- `verify_import.py` - Comprehensive import verification

**Consolidation:** Extend existing validation scripts rather than creating new ones.

## Consolidated Production Flow

### Phase 1: Pre-Import Analysis (Keep New)
```bash
# Analyze files and generate manifest
python scripts/analyze_client_files.py /path/to/files \
    --case-name "Case Name" \
    --output manifest.json
```

### Phase 2: Database Setup (Modify)
Instead of SQLite, add import session tracking to Supabase:

```sql
-- New table for import sessions
CREATE TABLE import_sessions (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    case_name TEXT NOT NULL,
    project_id UUID REFERENCES projects(id),
    manifest JSONB,
    started_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,
    total_files INTEGER DEFAULT 0,
    processed_files INTEGER DEFAULT 0,
    failed_files INTEGER DEFAULT 0,
    total_cost DECIMAL(10,2) DEFAULT 0,
    status TEXT DEFAULT 'active'
);

-- Add import session reference to source_documents
ALTER TABLE source_documents 
ADD COLUMN import_session_id UUID REFERENCES import_sessions(id);

-- Cost tracking table
CREATE TABLE processing_costs (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    import_session_id UUID REFERENCES import_sessions(id),
    document_id UUID REFERENCES source_documents(documentid),
    service TEXT NOT NULL,
    operation TEXT NOT NULL,
    units INTEGER DEFAULT 1,
    unit_cost DECIMAL(10,4) NOT NULL,
    total_cost DECIMAL(10,2) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### Phase 3: Document Import (Refactor)

Modify `test_celery_e2e.py` to support manifest-based import:

```python
# Enhanced version of test_celery_e2e.py
class ManifestImporter(CeleryE2ETester):
    def __init__(self, manifest_path: str):
        super().__init__()
        self.manifest = self.load_manifest(manifest_path)
        self.session_id = self.create_import_session()
    
    def import_from_manifest(self):
        """Import all files from manifest"""
        # Use existing submission logic
        # Add cost tracking
        # Update session progress in Supabase
```

### Phase 4: Monitoring (Use Existing)

**Option 1: Flower Web UI**
```bash
celery -A scripts.celery_app flower
# Navigate to http://localhost:5555
```

**Option 2: Enhanced Pipeline Monitor**
```bash
# Extend to show import sessions
python scripts/standalone_pipeline_monitor.py --show-imports
```

### Phase 5: Verification (Extend Existing)

Enhance `check_celery_status.py` to include import session filtering:

```python
def check_import_session_status(session_id: str):
    """Check status of all documents in an import session"""
    # Query by import_session_id
    # Show progress statistics
    # Identify failed documents
```

## Implementation Steps

### 1. Database Migrations
Create migration to add import session tracking:
```bash
python scripts/apply_migration.py --file migrations/00017_add_import_sessions.sql
```

### 2. Refactor Import Logic
- Remove SQLite dependency from `import_tracker.py`
- Integrate with `SupabaseManager` for session tracking
- Modify `import_client_files.py` to use existing `celery_submission.py`

### 3. Enhance Existing Monitors
- Add import session view to `standalone_pipeline_monitor.py`
- Add cost tracking display
- Include manifest analysis results

### 4. Simplify Workflow
Single command to import with monitoring:
```bash
# Start import with automatic monitoring
python scripts/import_from_manifest.py manifest.json --monitor
```

## Benefits of Consolidation

1. **Single Source of Truth**: All data in Supabase, no SQLite files
2. **Unified Monitoring**: One dashboard for all pipeline activity
3. **Reuse Existing Code**: Leverage battle-tested submission logic
4. **Simpler Operations**: Fewer scripts to maintain
5. **Better Integration**: Cost tracking integrated with existing tables

## Minimal New Code Needed

Keep only:
1. `analyze_client_files.py` - Valuable pre-import analysis
2. Cost tracking logic (integrate into Supabase)
3. Manifest-based import coordination

Remove/Refactor:
1. `import_dashboard.py` - Use Flower instead
2. `import_tracker.py` - Use Supabase tables
3. `import_client_files.py` - Extend `test_celery_e2e.py`
4. `verify_import.py` - Extend existing validation scripts

## Production Workflow

```bash
# 1. Analyze files
python scripts/analyze_client_files.py /path/to/files \
    --case-name "Case Name" --output case_manifest.json

# 2. Start monitoring (in separate terminal)
celery -A scripts.celery_app flower

# 3. Import documents
python scripts/import_from_manifest.py case_manifest.json \
    --project-name "Case Name" \
    --workers 4 \
    --batch-size 50

# 4. Monitor progress
# Either use Flower UI or:
python scripts/standalone_pipeline_monitor.py --session SESSION_ID

# 5. Verify completion
python scripts/check_import_completion.py --session SESSION_ID
```

This consolidated approach maintains all functionality while reducing code duplication and complexity.