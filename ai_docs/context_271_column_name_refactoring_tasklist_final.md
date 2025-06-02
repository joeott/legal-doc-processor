# Column Name Refactoring Task List - Final Version

## Overview
This document provides the comprehensive list of column name updates needed to align the codebase with the Pydantic models and RDS schema.

## Key Column Mappings Required

Based on the Pydantic models in `core/schemas.py`:

1. **ProjectModel**:
   - Uses `project_id` (not `project_uuid`)
   - But SourceDocumentModel uses `project_uuid` for the foreign key reference

2. **SourceDocumentModel**:
   - Uses `original_file_name` (not `original_filename`)
   - Uses `project_uuid` for the foreign key to projects
   - Uses `celery_status` for status tracking (not `processing_status`)

3. **Neo4jDocumentModel**:
   - Uses `processing_status` (with ProcessingStatus enum)
   - Uses `project_uuid` alongside `project_id`

4. **ChunkModel**:
   - Uses `text` for content (not `text_content`)
   - Uses `chunk_id` as UUID field

## Critical Updates Required

### 1. **scripts/enhanced_column_mappings.py**
Current issues:
- Line 35: Maps `project_uuid` to itself, but should map to `project_id` in some contexts
- Line 39: Maps `original_file_name` to `original_filename` (incorrect direction)
- Line 54: Maps `processing_status` to `status` but models use different fields

**Action**: Update mappings to correctly reflect Pydantic model field names

### 2. **scripts/pdf_tasks.py**
- Line 208: `document.processing_status` - Check which model this refers to
- Lines 577-664: All `project_uuid` parameters should remain as is (matches Pydantic models)

### 3. **scripts/db.py**
- Line 502: `"processing_status": status.value` - This might be correct depending on the table

### 4. **scripts/rds_utils.py**
- Lines 97, 101: Column mappings need review
- Line 173-175: Special handling for `original_filename` mapping needs to be reversed

### 5. **scripts/cli/import.py**
- All `project_uuid` references are correct (matches Pydantic models)

### 6. **scripts/ocr_extraction.py**
- Line 199: `original_filename` should be `original_file_name`

### 7. **scripts/pdf_pipeline.py**
- Line 176: `original_filename` should be `original_file_name`
- Line 200: `pipeline.document.original_filename` should be `pipeline.document.original_file_name`

### 8. **Test files**:
- `test_minimal_pipeline.py` Line 126, 141: `original_filename` → `original_file_name`
- `minimal_pipeline_test.py` Line 141, 146: `original_filename` → `original_file_name`

## Column Mapping Strategy

The issue is that we have inconsistencies between:
1. Pydantic model field names
2. Actual database column names
3. Pipeline code expectations

### Correct Mappings Should Be:

For **source_documents** table:
```python
"original_file_name": "original_file_name",  # Pydantic field → DB column
"project_uuid": "project_uuid",              # Keep as is
"celery_status": "celery_status",            # For processing status
```

For **neo4j_documents** table:
```python
"processing_status": "processing_status",    # Uses ProcessingStatus enum
"project_uuid": "project_uuid",              # Keep as is
```

For **document_chunks** table:
```python
"text": "text_content",                      # Pydantic uses 'text', DB has 'text_content'
"chunk_id": "chunk_uuid",                    # Pydantic uses 'chunk_id', DB has 'chunk_uuid'
```

## Implementation Order

1. **First**: Fix `enhanced_column_mappings.py` to have correct mappings
2. **Second**: Update any code that directly references old column names
3. **Third**: Test with actual database operations
4. **Fourth**: Update test files

## Special Considerations

1. The `project_uuid` vs `project_id` confusion:
   - ProjectModel has both `project_id` (UUID) and `id` (int)
   - SourceDocumentModel uses `project_uuid` to reference projects
   - Keep `project_uuid` as is in most places

2. Status fields are complex:
   - SourceDocumentModel uses `celery_status`
   - Neo4jDocumentModel uses `processing_status`
   - Don't universally replace one with the other

3. The `original_filename` → `original_file_name` change is straightforward and should be done everywhere

## Verification Commands

After changes:
```bash
# Check for remaining old column names
grep -r "original_filename" scripts/ --include="*.py" | grep -v archive_pre_consolidation
grep -r "\bfilename\b" scripts/ --include="*.py" | grep -v archive_pre_consolidation | grep -v "file_name"
grep -r "processing_status" scripts/ --include="*.py" | grep -v archive_pre_consolidation

# Run schema conformance test
python scripts/test_schema_conformance.py
```