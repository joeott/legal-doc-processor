# Schema Mismatches Analysis

## Date: 2025-06-09

Based on analysis of the database schema export and codebase, the following mismatches were identified between SQL queries/ORM references and the actual database schema:

## 1. Foreign Key Column Mismatches

### processing_tasks table
**Issue**: The table uses `document_id` to reference `source_documents.document_uuid`
- **Actual Schema**: `document_id UUID` with FK to `source_documents.document_uuid`
- **Code References**: Some code may expect `document_uuid` instead
- **Location**: `/opt/legal-doc-processor/scripts/db.py:1134` - table definition shows `document_id`

### entity_mentions table
**Issue**: Has duplicate column `chunk_id` that should not be used
- **Actual Schema**: Has both `chunk_uuid` (correct) and `chunk_id` (legacy)
- **Code References**: `entity_service.py` uses `chunk_id` in several places
- **Locations**:
  - `/opt/legal-doc-processor/scripts/entity_service.py:lines 429-438` - uses `chunk_id` parameter
  - `/opt/legal-doc-processor/scripts/cache.py` - uses `chunk_id` in cache keys

## 2. Column Name Mismatches

### source_documents table
**Issue**: Code references `processing_status` but column doesn't exist
- **Actual Schema**: Uses `status` column
- **Code References**: 
  - `/opt/legal-doc-processor/scripts/db.py:521` - tries to update `processing_status`
  - `/opt/legal-doc-processor/scripts/pdf_tasks.py` - checks `document.processing_status`
- **Fix**: Use `status` column instead

### textract_jobs table
**Issue**: Code uses different column names
- **Actual Schema**: `status` (not `job_status`)
- **Code References**:
  - `/opt/legal-doc-processor/scripts/db.py:634` - uses `job_status` in create
  - `/opt/legal-doc-processor/scripts/db.py:694` - updates `job_status`
- **Fix**: Map to `status` column

## 3. Missing Enhanced Column Mappings

**Issue**: Code imports `enhanced_column_mappings.py` but file doesn't exist
- **Location**: `/opt/legal-doc-processor/scripts/rds_utils.py:75-78`
- **Impact**: Falls back to basic mappings which may be incomplete
- **Fix**: Either create the file or remove the import

## 4. Model Property Mismatches

### DocumentChunkMinimal
**Correct**: Uses backward compatibility properties correctly
- Maps `start_char` → `char_start_index`
- Maps `end_char` → `char_end_index`
- Maps `text_content` → `text`

### CanonicalEntityMinimal
**Correct**: Uses backward compatibility property
- Maps `entity_name` → `canonical_name`

## 5. Relationship References

### relationship_staging table
**Issue**: Code might expect `relationship_uuid` but it doesn't exist in DB
- **Actual Schema**: Only has `id` (integer) as primary key
- **Model**: Correctly doesn't include `relationship_uuid`

### import_sessions table
**Issue**: FK references `projects.project_id` not `projects.id`
- **Actual Schema**: FK from `project_uuid` to `projects.project_id`
- **Potential Issue**: Code might use wrong join column

## 6. Processing Tasks Primary Key

**Issue**: `processing_tasks` table uses UUID for `id` column
- **Actual Schema**: `id UUID` with default `gen_random_uuid()`
- **Model**: `ProcessingTaskMinimal` expects `id: Optional[int]`
- **Fix**: Update model to use `id: Optional[UUID]`

## 7. Cache Key Mismatches

**Issue**: Cache keys use `chunk_id` but should use `chunk_uuid`
- **Location**: `/opt/legal-doc-processor/scripts/cache.py`
- **Affected Keys**:
  - `DOC_ENTITIES = "doc:entities:{document_uuid}:{chunk_id}"`
  - `DOC_STRUCTURED = "doc:structured:{document_uuid}:{chunk_id}"`
  - `EMB_CHUNK = "emb:chunk:{chunk_id}:v{version}"`
  - `EMB_SIMILARITY_CACHE = "emb:sim:{chunk_id1}:{chunk_id2}"`
  - `IDEMPOTENT_ENTITY = "idempotent:entity:{document_uuid}:{chunk_id}"`
- **Fix**: Replace `chunk_id` with `chunk_uuid` in all cache key patterns

## Recommended Fixes

1. **Update db.py**:
   - Line 521: Change `"processing_status"` to `"status"`
   - Line 634: Change `'job_status': job_status` to `'status': job_status`
   - Line 694: Change `"job_status": status` to `"status": status`

2. **Update entity_service.py**:
   - Replace `chunk_id` parameters with `chunk_uuid`
   - Update cache key generation to use `chunk_uuid`

3. **Update models.py**:
   - Change `ProcessingTaskMinimal.id` from `Optional[int]` to `Optional[UUID]`

4. **Create or remove enhanced_column_mappings.py**:
   - Either implement the missing file or update rds_utils.py to remove the import

5. **Update pdf_tasks.py**:
   - Change references from `document.processing_status` to `document.status`

6. **Update cache.py**:
   - Replace all `chunk_id` references with `chunk_uuid` in cache key patterns

## Summary

Most mismatches are related to:
1. Column naming inconsistencies (status vs processing_status, job_status)
2. Legacy column references (chunk_id instead of chunk_uuid)
3. Missing enhanced mapping configuration
4. Type mismatches in models (int vs UUID for processing_tasks.id)

The models.py file correctly implements backward compatibility for most cases, but some direct SQL queries and column references need to be updated to match the actual schema.