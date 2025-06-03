# Column Name Refactoring Task List

## Overview
This document lists all references to deprecated column names in the codebase that need to be updated to match the Pydantic models and new database schema.

## Column Mappings Required
- `project_uuid` → `project_id`
- `filename` → `file_name`
- `processing_status` → `status`
- `original_filename` → `original_file_name`

## Files Requiring Updates

### 1. **scripts/pdf_tasks.py**
- Line 208: `document.processing_status` → `document.status`
- Lines 577, 586, 601, 629, 637, 664: `project_uuid` parameter → `project_id`

### 2. **scripts/db.py**
- Line 502: `"processing_status": status.value` → `"status": status.value`

### 3. **scripts/rds_utils.py**
- Lines 97, 101: Column mapping for `project_uuid` → `project_id`
- Line 173-175: Special handling for `original_filename` mapping

### 4. **scripts/cli/import.py**
- Lines 142, 152, 181, 209, 227, 246, 251, 297, 343, 362, 401, 474: `project_uuid` → `project_id`

### 5. **scripts/cli/monitor.py**
- Lines 567-568, 575-576: `filename` variable (local var, may not need change)
- Lines 593, 614: `doc['original_file_name']` (already correct)
- Line 675: `job['file_name']` (already correct)

### 6. **scripts/ocr_extraction.py**
- Line 199: `original_filename=document.original_filename` → `original_file_name=document.original_file_name`

### 7. **scripts/pdf_pipeline.py**
- Line 176: `original_filename=original_name` → `original_file_name=original_name`
- Line 200: `pipeline.document.original_filename` → `pipeline.document.original_file_name`

### 8. **scripts/test_minimal_pipeline.py**
- Line 126: `doc.get('original_filename', 'N/A')` → `doc.get('original_file_name', 'N/A')`
- Line 141: SQL query `original_filename` → `original_file_name`

### 9. **scripts/minimal_pipeline_test.py**
- Line 141: SQL query `original_filename` → `original_file_name`
- Line 146: `doc['original_filename']` → `doc['original_file_name']`

### 10. **scripts/graph_service.py**
Multiple occurrences of `project_uuid` that need to be changed to `project_id`

### 11. **scripts/entity_service.py**
Check for any references to old column names

### 12. **scripts/services/project_association.py**
- Line references to `original_filename` → `original_file_name`

### 13. **scripts/services/document_categorization.py**
- Line references to `original_filename` → `original_file_name`

### 14. **scripts/services/semantic_naming.py**
- Line references to `original_filename` → `original_file_name`

### 15. **scripts/core/schemas.py**
Verify all models use correct field names:
- `project_id` not `project_uuid`
- `file_name` not `filename`
- `status` not `processing_status`
- `original_file_name` not `original_filename`

### 16. **scripts/enhanced_column_mappings.py**
Update mappings to ensure:
- `project_uuid` maps to `project_id`
- `filename` maps to `file_name`
- `processing_status` maps to `status`
- `original_filename` maps to `original_file_name`

## SQL Queries to Update
Look for any raw SQL queries in:
- Test files
- Migration scripts
- Database utilities

## Verification Steps
1. Run grep for each old column name to ensure no occurrences remain
2. Test database operations with new column names
3. Verify Pydantic model validation passes
4. Run integration tests

## Priority Order
1. Update `enhanced_column_mappings.py` first
2. Update database layer (`db.py`, `rds_utils.py`)
3. Update core task files (`pdf_tasks.py`)
4. Update CLI tools
5. Update test files
6. Update service files

## Notes
- Some occurrences may be in comments or local variables that don't need changing
- Archive files under `archive_pre_consolidation/` are lower priority
- Ensure backward compatibility during migration period