# Context 277: Phase 2 - Database Schema Mismatches Identified

## Critical Findings

### 1. Column Name Mismatches

**source_documents table:**
- Database has: `original_filename` 
- Pydantic expects: `original_file_name` (with underscore)

### 2. Data Type Mismatches

**projects table:**
- `supabase_project_id`: Database returns integer, Pydantic expects UUID
- `data_layer`: Database has TEXT with default 'production', Pydantic expects Dict[str, Any]

### 3. JSON Field Issues

- `ocr_metadata_json` and `transcription_metadata_json` are being double-serialized
- The code is putting metadata inside these JSON fields incorrectly

### 4. Default Value Conflicts

**Database defaults that conflict with Pydantic:**
- `ocr_metadata_json`: Database default '{}', Pydantic default None
- `transcription_metadata_json`: Database default '{}', Pydantic default None

## SQL Migrations Required

### Fix Column Names

```sql
-- Fix original_filename to match Pydantic model
ALTER TABLE source_documents 
RENAME COLUMN original_filename TO original_file_name;
```

### Fix Data Types

```sql
-- Change data_layer to JSONB to match Pydantic Dict expectation
ALTER TABLE projects 
ALTER COLUMN data_layer TYPE JSONB 
USING CASE 
    WHEN data_layer IS NULL THEN NULL 
    ELSE jsonb_build_object('layer', data_layer) 
END;

-- Update default to empty JSON object
ALTER TABLE projects 
ALTER COLUMN data_layer SET DEFAULT '{}'::jsonb;
```

### Fix JSON Field Defaults

```sql
-- Remove defaults that conflict with Pydantic None defaults
ALTER TABLE source_documents 
ALTER COLUMN ocr_metadata_json DROP DEFAULT;

ALTER TABLE source_documents 
ALTER COLUMN transcription_metadata_json DROP DEFAULT;

-- Same for projects metadata if needed
ALTER TABLE projects 
ALTER COLUMN metadata DROP DEFAULT;
```

### Add Missing Indexes

```sql
-- Add indexes for common lookups
CREATE INDEX IF NOT EXISTS idx_source_documents_document_uuid 
ON source_documents(document_uuid);

CREATE INDEX IF NOT EXISTS idx_projects_project_uuid 
ON projects(project_uuid);
```

## Column Mapping Issues

The error shows column mappings are working but causing problems:
- `original_file_name` → `original_filename` (mapping works)
- But direct SQL fails because it uses Pydantic field names

## Key Observations

1. **UUID Generation**: Database has `gen_random_uuid()` defaults, but Pydantic models don't use them
2. **Timestamps**: Database has `CURRENT_TIMESTAMP` defaults - this is good
3. **Foreign Keys**: Properly enforced (project_fk_id constraint works)
4. **project_uuid vs supabase_project_id**: Confusing dual UUID columns in projects table

## Next Steps

1. Apply column name fixes
2. Fix data type mismatches
3. Remove conflicting defaults
4. Test CRUD operations again
5. Eventually remove column mapping layer

## Important Notes

- The database schema is close but has subtle mismatches
- Column mappings are masking some issues but not all
- Once fixed, we can remove the entire mapping layer
- Foreign key constraints are properly enforced