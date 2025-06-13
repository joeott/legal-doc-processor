# Context 482: Projects Table Column Name Mismatch

## Date: January 9, 2025

## Issue Summary

During pipeline processing, an SQL error occurred when attempting to create a new project record. The error revealed a column name mismatch between the code and the actual database schema.

## Error Details

### Error Message
```
ERROR: column "project_name" of relation "projects" does not exist
LINE 2: INSERT INTO projects (project_name, active)
                              ^
```

### Error Context
- **Script**: `monitor_full_pipeline.py`
- **Function**: Project creation (lines 96-110)
- **SQL Statement**:
```sql
INSERT INTO projects (project_name, active)
VALUES (:name, true)
RETURNING project_id, project_uuid
```

## Schema Inspector Findings

Running `schema_inspector.py` on January 9, 2025, revealed the actual projects table schema:

### Actual Database Schema (from schema_export_database_schema.json)
```
Projects table columns:
  - id (INTEGER, nullable: False)
  - project_id (UUID, nullable: False)
  - supabase_project_id (UUID, nullable: True)
  - name (TEXT, nullable: False)           <-- This is the correct column
  - client_name (TEXT, nullable: True)
  - matter_type (TEXT, nullable: True)
  - data_layer (JSONB, nullable: True)
  - airtable_id (TEXT, nullable: True)
  - metadata (JSONB, nullable: True)
  - active (BOOLEAN, nullable: True)
  - script_run_count (INTEGER, nullable: True)
  - processed_by_scripts (BOOLEAN, nullable: True)
  - last_synced_at (TIMESTAMP, nullable: True)
  - created_at (TIMESTAMP, nullable: True)
  - updated_at (TIMESTAMP, nullable: True)
  - description (TEXT, nullable: True)
  - status (VARCHAR(50), nullable: True)
  - matter_number (VARCHAR(100), nullable: True)
```

## Column Name Discrepancy

| Expected in Code | Actual in Database | Type |
|-----------------|-------------------|------|
| `project_name` | `name` | TEXT, NOT NULL |

## Impact

1. **Immediate**: Project creation fails, preventing document processing
2. **Scope**: Affects all scripts that attempt to create projects using `project_name`
3. **Severity**: High - Blocks entire pipeline execution

## Root Cause Analysis

The discrepancy likely stems from:
1. **Schema Evolution**: The column may have been renamed from `project_name` to `name` at some point
2. **Code-Database Drift**: Scripts were not updated to reflect the schema change
3. **Model Mismatch**: Pydantic models may be using outdated field names

## Affected Code Locations

### 1. monitor_full_pipeline.py (lines 96-110)
```python
result = session.execute(text("""
    INSERT INTO projects (project_name, active)  # <-- Should be 'name'
    VALUES (:name, true)
    RETURNING project_id, project_uuid
"""), {'name': f'PIPELINE_TEST_{datetime.now().strftime("%Y%m%d_%H%M%S")}'})
```

### 2. Potential Other Locations
- Any script creating projects
- Pydantic models for projects
- Schema reference files

## Required Fixes

### Immediate Fix
Change all references from `project_name` to `name` in SQL queries:

```sql
-- Before
INSERT INTO projects (project_name, active)

-- After  
INSERT INTO projects (name, active)
```

### Comprehensive Fix
1. Search all Python files for `project_name` references
2. Update Pydantic models if they use `project_name`
3. Update any schema reference documentation
4. Add database schema validation to prevent future drift

## Verification Steps

1. **Schema Export Path**: `/opt/legal-doc-processor/monitoring/reports/2025-06-09_21-41-46_UTC/`
2. **Schema Inspector Output**: Successfully exported full database schema
3. **Database Stats**:
   - Total Tables: 14
   - Total Columns: 187
   - Foreign Keys: 17
   - Triggers: 6
   - Functions: 12

## Recommendations

1. **Immediate**: Fix the SQL query in monitor_full_pipeline.py
2. **Short-term**: Audit all project creation code for similar issues
3. **Long-term**: Implement automated schema validation in CI/CD
4. **Best Practice**: Use SQLAlchemy ORM or prepared statements to avoid hardcoded column names

## Related Context

- Context 454: Schema reference correction verification
- Context 416: Pydantic models database alignment analysis
- Context 241: Schema mapping implementation plan

This issue highlights the importance of maintaining synchronization between code and database schema, especially in production systems with evolving schemas.