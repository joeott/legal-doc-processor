# Context 76: Comprehensive Trigger Fix Plan

## Overview

Based on the errors encountered during end-to-end testing, this plan addresses all database trigger issues preventing successful document processing. The main errors are:

1. `record "new" has no field "source_document_uuid"` 
2. `record "new" has no field "status"`
3. Various constraint violations and trigger conflicts

## Error Analysis

### Error 1: Missing source_document_uuid Field
**Location**: When inserting into neo4j_documents table
**Cause**: Triggers on neo4j_documents table trying to access NEW.source_document_uuid which doesn't exist after our schema migration
**Impact**: Prevents creation of neo4j_documents entries

### Error 2: Missing status Field  
**Location**: When updating source_documents table
**Cause**: Triggers on source_documents trying to access NEW.status which doesn't exist
**Impact**: Prevents status updates after processing

### Error 3: Constraint Violations
**Location**: Various tables
**Cause**: Duplicate key violations, check constraint failures
**Impact**: Prevents data updates

## Trigger Categories

### 1. Essential Triggers (Keep with modifications)
- **Queue Creation**: Create document_processing_queue entries when documents are uploaded
- **Status Synchronization**: Keep queue status in sync with document processing
- **UUID Generation**: Ensure document UUIDs are properly generated

### 2. Problematic Triggers (Disable or fix)
- Triggers referencing non-existent fields (source_document_uuid, status)
- Complex notification triggers causing errors
- Redundant triggers doing the same job

### 3. Unnecessary Triggers (Remove)
- Old migration triggers
- Deprecated workflow triggers
- Test/debug triggers

## Implementation Plan

### Phase 1: Immediate Fixes (Critical Path)

#### 1.1 Disable All Problematic Triggers
```sql
-- Disable triggers causing field reference errors
ALTER TABLE source_documents DISABLE TRIGGER ALL;
ALTER TABLE neo4j_documents DISABLE TRIGGER ALL;
ALTER TABLE document_processing_queue DISABLE TRIGGER ALL;

-- Re-enable only essential triggers after fixing
```

#### 1.2 Create Minimal Working Triggers

**For source_documents:**
```sql
-- Simple queue creation trigger
CREATE OR REPLACE FUNCTION create_queue_entry_simple()
RETURNS TRIGGER AS $$
BEGIN
    -- Only create queue entry for new documents
    IF TG_OP = 'INSERT' THEN
        INSERT INTO document_processing_queue (
            document_uuid,
            source_document_id,
            source_document_uuid,  -- This column exists in queue table
            processing_step,
            status,
            priority,
            retry_count,
            max_retries,
            created_at,
            updated_at
        ) VALUES (
            NEW.document_uuid,
            NEW.id,
            NEW.document_uuid,
            'intake',
            'pending',
            100,
            0,
            3,
            NOW(),
            NOW()
        ) ON CONFLICT (source_document_uuid) DO NOTHING;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER minimal_queue_creation
AFTER INSERT ON source_documents
FOR EACH ROW
EXECUTE FUNCTION create_queue_entry_simple();
```

**For neo4j_documents:**
```sql
-- No triggers needed on neo4j_documents for basic operation
-- All necessary data is passed during INSERT
```

### Phase 2: Fix Specific Errors

#### 2.1 Fix source_document_uuid References
- Remove all references to NEW.source_document_uuid in neo4j_documents triggers
- The unified schema uses documentId as the primary identifier

#### 2.2 Fix status Field References  
- Remove all references to NEW.status in source_documents triggers
- Use initial_processing_status instead where needed

#### 2.3 Fix Constraint Violations
```sql
-- Ensure constraints match actual usage
-- Remove or modify unique constraints causing issues
ALTER TABLE textract_jobs 
DROP CONSTRAINT IF EXISTS unique_source_document_uuid;

-- Fix check constraints
ALTER TABLE textract_jobs
DROP CONSTRAINT IF EXISTS textract_jobs_job_status_check;

ALTER TABLE textract_jobs
ADD CONSTRAINT textract_jobs_job_status_check 
CHECK (job_status IN ('submitted', 'in_progress', 'succeeded', 'failed', 'partial_success'));
```

### Phase 3: Validation Triggers

Create simple validation triggers that don't interfere with operations:

```sql
-- Ensure document_uuid is always set
CREATE OR REPLACE FUNCTION ensure_document_uuid()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.document_uuid IS NULL THEN
        NEW.document_uuid = gen_random_uuid();
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER ensure_uuid_trigger
BEFORE INSERT ON source_documents
FOR EACH ROW
EXECUTE FUNCTION ensure_document_uuid();
```

### Phase 4: Monitoring Triggers (Optional)

Only if needed for debugging:
```sql
-- Simple notification without field access issues
CREATE OR REPLACE FUNCTION notify_document_change()
RETURNS TRIGGER AS $$
BEGIN
    PERFORM pg_notify(
        'document_changes',
        json_build_object(
            'table', TG_TABLE_NAME,
            'operation', TG_OP,
            'id', COALESCE(NEW.id, OLD.id)
        )::text
    );
    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;
```

## Migration Script Structure

```sql
-- 00010_comprehensive_trigger_fix.sql

-- Step 1: Disable all triggers
ALTER TABLE source_documents DISABLE TRIGGER ALL;
ALTER TABLE neo4j_documents DISABLE TRIGGER ALL;
ALTER TABLE document_processing_queue DISABLE TRIGGER ALL;

-- Step 2: Drop problematic functions
DROP FUNCTION IF EXISTS [...list of functions...] CASCADE;

-- Step 3: Create minimal required functions
[Insert minimal functions above]

-- Step 4: Create minimal required triggers
[Insert minimal triggers above]

-- Step 5: Fix constraints
[Insert constraint fixes above]

-- Step 6: Verify
DO $$
BEGIN
    RAISE NOTICE 'Trigger cleanup complete';
    RAISE NOTICE 'Enabled triggers: %', (
        SELECT string_agg(tgname, ', ')
        FROM pg_trigger
        WHERE tgrelid IN ('source_documents'::regclass, 'neo4j_documents'::regclass)
        AND tgenabled = 'O'
    );
END $$;
```

## Testing Plan

1. **Upload Test**: Verify document upload creates queue entry
2. **Processing Test**: Verify queue processor can update statuses
3. **Neo4j Creation**: Verify neo4j_documents can be created
4. **No Errors**: Verify no trigger errors in logs

## Minimal Trigger Set

For successful operation, we only need:

1. **source_documents**:
   - `ensure_uuid_trigger`: Generate UUID if missing
   - `minimal_queue_creation`: Create queue entry on insert

2. **neo4j_documents**:
   - No triggers required

3. **document_processing_queue**:
   - No triggers required

## Benefits

1. **Simplicity**: Minimal trigger set reduces complexity
2. **Reliability**: No field reference errors
3. **Performance**: Fewer triggers = faster operations
4. **Maintainability**: Easy to understand and modify

## Rollback Plan

If issues arise:
```sql
-- Re-enable all triggers
ALTER TABLE source_documents ENABLE TRIGGER ALL;
ALTER TABLE neo4j_documents ENABLE TRIGGER ALL;
ALTER TABLE document_processing_queue ENABLE TRIGGER ALL;
```

## Conclusion

This plan eliminates all trigger-related errors by:
1. Removing references to non-existent fields
2. Simplifying trigger logic to essential operations only
3. Fixing constraint violations
4. Creating a minimal, working trigger set

The result will be a stable, error-free document processing pipeline that can complete end-to-end processing successfully.