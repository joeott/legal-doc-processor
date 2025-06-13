# Context 485: Comprehensive Schema Mismatches Analysis

## Date: January 9, 2025

## Executive Summary

This document provides a detailed analysis of all schema and column mismatches discovered during pipeline testing, cross-referenced with the actual database schema exported on 2025-06-09_21-41-46_UTC. Each mismatch includes specific script locations, line numbers, current code, and proposed fixes.

## Schema Export Reference
- **Export Path**: `/opt/legal-doc-processor/monitoring/reports/2025-06-09_21-41-46_UTC/schema_export_database_schema.json`
- **Database**: database1.cuviucyodbeg.us-east-1.rds.amazonaws.com:5432/legal_doc_processing
- **Total Tables**: 14
- **Total Columns**: 187

## 1. Projects Table Mismatches

### 1.1 Column: project_name → name
**Location**: monitor_full_pipeline.py (fixed)
**Line**: 202-206
**Current Code**:
```sql
INSERT INTO projects (project_name, active)  -- WRONG
VALUES (:name, true)
```
**Actual Schema**: Column is `name` (TEXT, NOT NULL)
**Proposed Fix**:
```sql
INSERT INTO projects (name, active)  -- CORRECT
VALUES (:name, true)
```
**Status**: ✅ Fixed in context_483

### 1.2 Column: project_uuid (doesn't exist)
**Location**: monitor_full_pipeline.py (fixed)  
**Line**: 205
**Current Code**:
```sql
RETURNING project_id, project_uuid  -- WRONG
```
**Actual Schema**: Only has `project_id` (UUID, NOT NULL)
**Proposed Fix**:
```sql
RETURNING id, project_id  -- CORRECT
```
**Status**: ✅ Fixed

## 2. Canonical Entities Table Mismatches

### 2.1 Column: document_uuid (doesn't exist)
**Location**: monitor_full_pipeline.py
**Line**: 145-149
**Current Code**:
```sql
SELECT COUNT(*) FROM canonical_entities 
WHERE document_uuid = :uuid  -- WRONG
```
**Actual Schema Columns**:
- id (INTEGER)
- canonical_entity_uuid (UUID)
- entity_type (TEXT)
- canonical_name (TEXT)
- normalized_name (TEXT)
- disambiguation_context (TEXT)
- confidence_score (NUMERIC)
- mention_count (INTEGER)
- created_at (TIMESTAMP)
- updated_at (TIMESTAMP)

**Note**: No direct document_uuid column exists
**Proposed Fix**: Need to join through entity_mentions table
```sql
SELECT COUNT(DISTINCT ce.canonical_entity_uuid) 
FROM canonical_entities ce
JOIN entity_mentions em ON em.canonical_entity_uuid = ce.canonical_entity_uuid
WHERE em.document_uuid = :uuid
```

## 3. Processing Tasks Table Mismatches

### 3.1 Primary Key Type Mismatch
**Location**: scripts/models.py
**Line**: ProcessingTaskMinimal model definition
**Current Code**:
```python
id: Optional[int] = Field(None, description="Task ID")
```
**Actual Schema**: `id` is UUID type with default gen_random_uuid()
**Proposed Fix**:
```python
id: Optional[UUID] = Field(None, description="Task ID")
```

### 3.2 Foreign Key Reference
**Actual Schema**: Has `document_id` (UUID) that references `source_documents.document_uuid`
**Note**: This is correct but naming is confusing (document_id → document_uuid)

## 4. Source Documents Table Mismatches

### 4.1 Column: processing_status → status
**Location**: scripts/db.py
**Line**: 521
**Current Code**:
```python
update_data["processing_status"] = status  # WRONG
```
**Actual Schema**: Column is `status` (VARCHAR(50))
**Proposed Fix**:
```python
update_data["status"] = status  # CORRECT
```

### 4.2 Column Reference in pdf_tasks.py
**Location**: scripts/pdf_tasks.py
**Line**: Various locations checking document.processing_status
**Current Code**:
```python
if document.processing_status == "completed":  # WRONG
```
**Proposed Fix**:
```python
if document.status == "completed":  # CORRECT
```

## 5. Textract Jobs Table Mismatches

### 5.1 Column: job_status → status
**Location**: scripts/db.py
**Line**: 634
**Current Code**:
```python
'job_status': job_status,  # WRONG
```
**Actual Schema**: Column is `status` (VARCHAR(50))
**Proposed Fix**:
```python
'status': job_status,  # CORRECT
```

**Location**: scripts/db.py
**Line**: 694
**Current Code**:
```python
"job_status": status  # WRONG
```
**Proposed Fix**:
```python
"status": status  # CORRECT
```

## 6. Entity Mentions Table Mismatches

### 6.1 Duplicate Columns: chunk_id vs chunk_uuid
**Issue**: Table has both columns but should only use chunk_uuid
**Actual Schema**:
- chunk_uuid (UUID) - Correct FK to document_chunks.chunk_uuid
- chunk_id (INTEGER) - Legacy column, should not be used

**Location**: scripts/entity_service.py
**Lines**: 429-438
**Current Code**:
```python
def extract_entities_from_chunk(chunk_id: str, ...):  # WRONG
```
**Proposed Fix**:
```python
def extract_entities_from_chunk(chunk_uuid: str, ...):  # CORRECT
```

**Location**: scripts/cache.py
**Lines**: 44-45, 84-88
**Current Code**:
```python
DOC_ENTITIES = "doc:entities:{document_uuid}:{chunk_id}"  # WRONG
DOC_STRUCTURED = "doc:structured:{document_uuid}:{chunk_id}"  # WRONG
```
**Proposed Fix**:
```python
DOC_ENTITIES = "doc:entities:{document_uuid}:{chunk_uuid}"  # CORRECT
DOC_STRUCTURED = "doc:structured:{document_uuid}:{chunk_uuid}"  # CORRECT
```

## 7. Missing File References

### 7.1 enhanced_column_mappings.py
**Location**: scripts/rds_utils.py
**Lines**: 75-78
**Current Code**:
```python
try:
    from scripts.db.enhanced_column_mappings import ENHANCED_COLUMN_MAPPING
except ImportError:
    ENHANCED_COLUMN_MAPPING = {}
```
**Issue**: File doesn't exist
**Proposed Fix**: Either:
1. Create the file with proper mappings, or
2. Remove the import and use only BASE_COLUMN_MAPPING

## 8. S3 Storage Manager Mismatches

### 8.1 Method Signature
**Location**: monitor_full_pipeline.py (fixed)
**Issue**: upload_document_with_uuid_naming() doesn't accept project_id
**Actual Signature**:
```python
def upload_document_with_uuid_naming(self, local_file_path: str, 
                                   document_uuid: str, 
                                   original_filename: str)
```
**Status**: ✅ Fixed

## 9. Create Document Validation Mismatches

### 9.1 Method Signature
**Location**: monitor_full_pipeline.py (fixed)
**Issue**: create_document_with_validation() doesn't accept session parameter
**Actual Signature**:
```python
def create_document_with_validation(document_uuid: str, filename: str, 
                                  s3_bucket: str, s3_key: str, 
                                  project_id: int = DEFAULT_PROJECT_ID)
```
**Status**: ✅ Fixed

## Summary of Required Fixes

### High Priority (Blocking Pipeline)
1. **canonical_entities query** - Need to join through entity_mentions
2. **processing_status → status** - Update all references
3. **job_status → status** - Update textract_jobs references
4. **chunk_id → chunk_uuid** - Update all cache keys and function parameters

### Medium Priority (Type Safety)
1. **ProcessingTaskMinimal.id** - Change from Optional[int] to Optional[UUID]
2. **Remove chunk_id usage** - Use only chunk_uuid throughout

### Low Priority (Cleanup)
1. **Create or remove enhanced_column_mappings.py**
2. **Document the document_id → document_uuid FK naming**

## Verification Commands

To verify these fixes:
```bash
# Check for remaining incorrect references
grep -r "project_name" scripts/ --include="*.py"
grep -r "processing_status" scripts/ --include="*.py"
grep -r "job_status" scripts/ --include="*.py"
grep -r "chunk_id" scripts/ --include="*.py" | grep -v "chunk_uuid"
```

## Next Steps

1. Apply the high-priority fixes to unblock pipeline processing
2. Run schema validation tests after each fix
3. Update models.py with correct types
4. Consider creating a schema validation script to catch future mismatches