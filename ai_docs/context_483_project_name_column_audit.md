# Context 483: Project Name Column Audit and Fix Proposal

## Date: January 9, 2025

## Executive Summary

A comprehensive search of the `/scripts/` directory reveals that while "project_name" appears in several locations, most are correctly used as function parameters or variable names. The actual database column is correctly referenced as `name` in SQL queries within the scripts directory. However, the monitor_full_pipeline.py script (outside /scripts/) had an incorrect reference that has been fixed.

## Audit Results

### 1. scripts/production_processor.py

#### Line 51: Function Definition
```python
def ensure_project_exists(self, project_id: int, project_name: str) -> None:
```
**Status**: ✅ Correct - This is a function parameter name, not a column reference

#### Lines 62-65: SQL Query
```sql
INSERT INTO projects (id, name, created_at, updated_at)
VALUES (:id, :name, NOW(), NOW())
ON CONFLICT (id) DO NOTHING
```
**Status**: ✅ Correct - Uses `name` column correctly

#### Line 66: Parameter Binding
```python
'name': project_name
```
**Status**: ✅ Correct - Maps the function parameter to the correct column name

#### Line 75: Log Message
```python
self.logger.info(f"Ensured project exists: ID={project_id}, Name={project_name}")
```
**Status**: ✅ Correct - Uses variable in log message

#### Line 471: CLI Function Parameter
```python
def process(files, project_id, project_name, batch_size, skip_validation):
```
**Status**: ✅ Correct - CLI function parameter

#### Line 476: Function Call
```python
processor.ensure_project_exists(project_id, project_name)
```
**Status**: ✅ Correct - Passing parameter to function

### 2. scripts/validation/flexible_validator.py

#### Line 223: Validation Details
```python
"project_name": project.name
```
**Status**: ✅ Correct - Dictionary key for validation results, not a database column

## Database Schema Verification

From the schema inspection performed on January 9, 2025:

### Projects Table Actual Schema
| Column Name | Data Type | Nullable | Purpose |
|------------|-----------|----------|---------|
| `id` | INTEGER | False | Auto-increment ID |
| `project_id` | UUID | False | Unique project identifier |
| `name` | TEXT | False | **Project name (NOT project_name)** |
| `client_name` | TEXT | True | Client name |
| `matter_type` | TEXT | True | Type of legal matter |
| ... | ... | ... | ... |

## Summary of Findings

### Within /scripts/ Directory
- **Total occurrences of "project_name"**: 6
- **Incorrect SQL column references**: 0
- **Correct usage as parameters/variables**: 6

### Outside /scripts/ Directory
- **monitor_full_pipeline.py**: Had 1 incorrect SQL reference (already fixed)

## SQL Query Analysis

### Correct SQL in scripts/production_processor.py
```sql
-- Line 62-65: Correctly uses 'name' column
INSERT INTO projects (id, name, created_at, updated_at)
VALUES (:id, :name, NOW(), NOW())
ON CONFLICT (id) DO NOTHING
```

### Previously Incorrect SQL (fixed)
```sql
-- Was in monitor_full_pipeline.py
INSERT INTO projects (project_name, active)  -- WRONG
VALUES (:name, true)

-- Fixed to:
INSERT INTO projects (name, active)  -- CORRECT
VALUES (:name, true)
```

## Recommendations

### 1. No Changes Required in /scripts/
All references to "project_name" within the scripts directory are appropriate uses as:
- Function parameter names
- Variable names
- Dictionary keys
- CLI option names

The actual SQL queries correctly use the `name` column.

### 2. Best Practices Going Forward

1. **Naming Consistency**: Consider using consistent naming between function parameters and database columns to avoid confusion
2. **Schema Documentation**: Maintain up-to-date schema documentation
3. **Validation**: Add schema validation tests to catch column name mismatches
4. **Code Reviews**: Check SQL queries against actual database schema

### 3. Additional Checks Performed

Searched for other potential column name variations:
- `proj_name`: Not found
- `projectName`: Not found
- `project_title`: Not found

## Conclusion

The audit reveals that the scripts directory correctly uses the `name` column in SQL queries. The confusion arose from:
1. Function parameters named `project_name` (which is fine)
2. One incorrect SQL query outside the scripts directory (now fixed)

No further code changes are required within the /scripts/ directory. The codebase correctly distinguishes between the parameter name `project_name` and the database column `name`.