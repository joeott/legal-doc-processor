# Context 266: Database Trigger Function Bug Analysis

## Date: May 31, 2025
## Issue: populate_integer_fks() trigger function has a bug

## Problem Description

When inserting records into `source_documents` table, the trigger function `populate_integer_fks()` is failing with:

```
record "new" has no field "chunk_uuid"
CONTEXT: SQL expression "TG_TABLE_NAME = 'entity_mentions' AND NEW.chunk_uuid IS NOT NULL"
PL/pgSQL function populate_integer_fks() line 14 at IF
```

## Root Cause Analysis

The trigger function has conditional logic based on `TG_TABLE_NAME`:

```sql
-- For entity_mentions
IF TG_TABLE_NAME = 'entity_mentions' AND NEW.chunk_uuid IS NOT NULL THEN
    SELECT id INTO NEW.chunk_fk_id FROM document_chunks WHERE chunk_uuid = NEW.chunk_uuid;
END IF;
```

However, when this trigger runs on `source_documents` inserts, it's still evaluating `NEW.chunk_uuid` even though:
1. We're inserting into `source_documents` (not `entity_mentions`)
2. `source_documents` table doesn't have a `chunk_uuid` column

## PostgreSQL Trigger Behavior

The issue is that PostgreSQL evaluates the entire expression `TG_TABLE_NAME = 'entity_mentions' AND NEW.chunk_uuid IS NOT NULL` even when the first part is false. Since `NEW.chunk_uuid` doesn't exist on the `source_documents` table, this causes the error.

## Solution Options

### Option 1: Fix the Trigger Logic (Recommended)
Use nested IF statements to avoid evaluating non-existent fields:

```sql
BEGIN
    -- For source_documents
    IF TG_TABLE_NAME = 'source_documents' THEN
        IF NEW.project_uuid IS NOT NULL THEN
            SELECT id INTO NEW.project_fk_id FROM projects WHERE project_uuid = NEW.project_uuid;
        END IF;
    END IF;
    
    -- For document_chunks
    IF TG_TABLE_NAME = 'document_chunks' THEN
        IF NEW.document_uuid IS NOT NULL THEN
            SELECT id INTO NEW.document_fk_id FROM source_documents WHERE document_uuid = NEW.document_uuid;
        END IF;
    END IF;
    
    -- For entity_mentions
    IF TG_TABLE_NAME = 'entity_mentions' THEN
        IF NEW.chunk_uuid IS NOT NULL THEN
            SELECT id INTO NEW.chunk_fk_id FROM document_chunks WHERE chunk_uuid = NEW.chunk_uuid;
        END IF;
    END IF;
    
    RETURN NEW;
END;
```

### Option 2: Temporarily Disable Trigger for Testing
```sql
ALTER TABLE source_documents DISABLE TRIGGER populate_source_documents_fks;
```

### Option 3: Create Table-Specific Trigger Functions
Split into separate functions for each table to avoid cross-table field references.

## Recommended Action

Fix the trigger function to use proper nested IF logic to prevent evaluating fields that don't exist on the current table.

## Implementation Plan

1. Update the trigger function with nested IF statements
2. Test the fix with our schema alignment tests
3. Verify all table operations work correctly
4. Document the fix for future reference