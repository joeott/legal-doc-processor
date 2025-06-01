# Context Update 168: Pydantic Cache Model and Database Schema Fixes

## Date: 2025-05-28

## Summary
This update documents the fixes applied to resolve Pydantic validation errors in the OCR caching system and database schema mismatches in the entity mentions queries.

## Issues Fixed

### 1. Pydantic CachedOCRResultModel Validation Error

**Problem**:
```
ValidationError: 3 validation errors for CachedOCRResultModel
metadata: Field required
ocr_result: Field required  
file_hash: Field required
```

**Root Cause**:
The OCR tasks were creating `CachedOCRResultModel` instances with incorrect field names:
- Using `raw_text`, `ocr_meta`, `confidence_score` instead of proper model structure
- Not using the factory method `CachedOCRResultModel.create()`
- Missing required fields: `metadata`, `ocr_result`, `file_hash`

**Solution**:
Updated `scripts/celery_tasks/ocr_tasks.py` to:
1. Create proper `OCRResultModel` instances first
2. Use `OCRPageResult` for page-level data
3. Use the factory method `CachedOCRResultModel.create()`
4. Include proper file hash generation

### 2. Database Schema Mismatch

**Problem**:
```
column neo4j_entity_mentions.document_uuid does not exist
```

**Root Cause**:
The `neo4j_entity_mentions` table doesn't have a `document_uuid` column. Entity mentions are linked to chunks, not documents directly. The correct column is `chunk_uuid`.

**Table Structure**:
```
neo4j_entity_mentions
├── id
├── entityMentionId
├── chunk_fk_id
├── chunk_uuid (← correct column)
├── value
├── normalizedValue
└── ... other fields
```

**Solution**:
Updated `scripts/cli/monitor.py` to:
1. First query `neo4j_chunks` to get chunk UUIDs for a document
2. Then query `neo4j_entity_mentions` using `chunk_uuid IN (chunk_uuids)`
3. Fixed all three query types: SELECT, COUNT, and DELETE

## Code Changes

### 1. OCR Task Fixes (`scripts/celery_tasks/ocr_tasks.py`)

**Image Processing Cache** (line ~279):
```python
# OLD: Direct model creation with wrong fields
cached_result = CachedOCRResultModel(
    document_uuid=uuid.UUID(document_uuid),
    raw_text=extracted_text,
    ocr_meta=[processing_metadata],
    ...
)

# NEW: Proper model creation with factory method
ocr_page = OCRPageResult(
    page_number=1,
    text=extracted_text,
    confidence=confidence_score,
    word_count=len(extracted_text.split()) if extracted_text else 0
)

ocr_result = OCRResultModel(
    provider='o4_mini_vision',
    total_pages=1,
    pages=[ocr_page],
    full_text=extracted_text,
    average_confidence=confidence_score,
    file_type=detected_file_type,
    processing_status='completed',
    metadata={'image_type': image_type}
)

file_hash = hashlib.md5(file_path.encode()).hexdigest()

cached_result = CachedOCRResultModel.create(
    document_uuid=uuid.UUID(document_uuid),
    ocr_result=ocr_result,
    file_hash=file_hash,
    provider='o4_mini_vision',
    ttl_seconds=86400
)
```

**PDF/Textract Cache** (line ~721):
Similar pattern applied - create proper `OCRResultModel` with pages, then use factory method.

### 2. Monitor Query Fixes (`scripts/cli/monitor.py`)

**Entity Count Query** (line ~218):
```python
# OLD: Direct query on non-existent column
entities = self.supabase.table('neo4j_entity_mentions').select('id').eq('document_uuid', document_uuid).limit(1).execute()

# NEW: Join through chunks table
chunks = self.supabase.table('neo4j_chunks').select('chunk_uuid').eq('document_uuid', document_uuid).execute()
if chunks.data:
    chunk_uuids = [c['chunk_uuid'] for c in chunks.data]
    entities = self.supabase.table('neo4j_entity_mentions').select('id').in_('chunk_uuid', chunk_uuids).limit(1).execute()
else:
    entities = {'data': []}
```

**Delete Queries** (lines 1070, 1075, 1079):
```python
# OLD: Delete with non-existent column
monitor.supabase.table('neo4j_entity_mentions').delete().eq('document_uuid', document_uuid).execute()

# NEW: Delete through chunk relationship
chunks_to_delete = monitor.supabase.table('neo4j_chunks').select('chunk_uuid').eq('document_uuid', document_uuid).execute()
if chunks_to_delete.data:
    chunk_uuids = [c['chunk_uuid'] for c in chunks_to_delete.data]
    monitor.supabase.table('neo4j_entity_mentions').delete().in_('chunk_uuid', chunk_uuids).execute()
```

## Verification

### 1. Test OCR Caching
```python
# The cache should now properly store:
# - CacheMetadataModel with TTL and versioning
# - OCRResultModel with page-level details
# - File hash for validation
# - Provider information
```

### 2. Test Entity Queries
```bash
# Monitor should now properly display:
# - Entity counts for documents
# - Clean up entities when retrying
# - No more "column does not exist" errors
```

## Impact

1. **OCR Processing**: Documents can now be cached properly without validation errors
2. **Monitor Display**: Entity information displays correctly
3. **Pipeline Flow**: OCR results can be retrieved from cache for reprocessing
4. **Error Recovery**: Retry operations properly clean up related entities

## Lessons Learned

1. **Pydantic Models**: Always use factory methods when available
2. **Database Relationships**: Understand the full schema before writing queries
3. **Entity-Chunk Relationship**: Entity mentions belong to chunks, not documents
4. **Model Evolution**: Keep cache models synchronized with processing models

## Next Steps

1. **Test Full Pipeline**: Verify document processes through all stages
2. **Monitor Performance**: Check if caching improves processing speed
3. **Update Other Queries**: Search for similar schema issues in other files
4. **Add Tests**: Create unit tests for cache model creation

## Related Files

- `/scripts/celery_tasks/ocr_tasks.py` - OCR task implementation
- `/scripts/core/cache_models.py` - Pydantic cache model definitions
- `/scripts/core/processing_models.py` - Processing result models
- `/scripts/cli/monitor.py` - Monitoring tool with fixed queries
- `/fix_ocr_caching.py` - Analysis script (can be deleted)
- `/fix_monitor_queries.py` - Fix script (can be deleted)

## Database Schema Reference

```
Document → Chunks → Entity Mentions
         ↓
   document_uuid → chunk_uuid → chunk_uuid
                               (in entity_mentions)
```

This relationship structure must be respected in all queries involving entity mentions.