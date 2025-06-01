# Context Update 169: Additional Schema and Validation Fixes

## Date: 2025-05-28

## Summary
This update documents additional fixes required after the initial Pydantic and schema corrections, including confidence score validation and more column name mismatches.

## New Issues Discovered

### 1. OCRPageResult Confidence Validation Error

**Problem**:
```
ValidationError: 1 validation error for OCRPageResult
confidence: Input should be less than or equal to 1
```

**Root Cause**:
Textract returns confidence scores on a 0-100 scale, but the Pydantic model expects 0-1 scale.

**Fix Required in `scripts/celery_tasks/ocr_tasks.py`**:
```python
# Convert confidence from 0-100 to 0-1 scale
confidence = meta.get('confidence_threshold', 0.0) if isinstance(meta, dict) else 0.0
if confidence > 1:
    confidence = confidence / 100.0  # Convert percentage to decimal
```

### 2. Additional Schema Mismatch

**Problem**:
```
column neo4j_chunks.chunk_uuid does not exist
```

**Actual Column Names in `neo4j_chunks`**:
- `chunkId` (UUID of the chunk)
- `document_uuid` (links to document)
- NOT `chunk_uuid`

**Fix Required in `scripts/cli/monitor.py`**:
All queries using `chunk_uuid` should use `chunkId` instead.

## Database Schema Reference

### neo4j_chunks Table
```
id                      INT
chunkId                 UUID    ← This is the chunk UUID
document_id             INT     ← Legacy FK
document_uuid           UUID    ← Document reference
supabaseChunkId         INT
chunkIndex              INT
text                    TEXT
cleanedText             TEXT
... other fields
```

### neo4j_entity_mentions Table
```
id                      INT
entityMentionId         UUID
chunk_fk_id             INT     ← Legacy FK
chunk_uuid              UUID    ← References chunkId from neo4j_chunks
value                   TEXT
... other fields
```

## Fixes to Implement

### 1. Fix Confidence Score Scaling

In `scripts/celery_tasks/ocr_tasks.py`, around lines where OCRPageResult is created:

```python
# Line ~287 (image processing)
confidence = confidence_score
if confidence > 1:
    confidence = confidence / 100.0

# Line ~732 (PDF processing)
confidence = meta.get('confidence_threshold', 0.0) if isinstance(meta, dict) else 0.0
if confidence > 1:
    confidence = confidence / 100.0
```

### 2. Fix Monitor Queries

In `scripts/cli/monitor.py`, update the chunk queries:

```python
# OLD
chunks = self.supabase.table('neo4j_chunks').select('chunk_uuid').eq('document_uuid', document_uuid).execute()

# NEW
chunks = self.supabase.table('neo4j_chunks').select('chunkId').eq('document_uuid', document_uuid).execute()

# And update the reference:
chunk_uuids = [c['chunkId'] for c in chunks.data]
```

## Complete Schema Mapping

```
Document Processing Flow:
source_documents.document_uuid
    ↓
neo4j_documents.documentId
    ↓
neo4j_chunks.document_uuid + neo4j_chunks.chunkId
    ↓
neo4j_entity_mentions.chunk_uuid (references neo4j_chunks.chunkId)
```

## Verification Steps

1. **Check Confidence Values**:
```python
# Textract metadata should show confidence as percentage
# OCRPageResult should show confidence as decimal (0-1)
```

2. **Test Query Flow**:
```sql
-- Get chunks for document
SELECT chunkId FROM neo4j_chunks WHERE document_uuid = 'xxx';

-- Get entities for chunks
SELECT * FROM neo4j_entity_mentions WHERE chunk_uuid IN (chunk_ids);
```

## Lessons Learned

1. **Data Scale Conversion**: Always check the scale of numeric values between systems
2. **Column Naming**: Database columns don't always follow consistent naming patterns
3. **Legacy Schema**: Mixed camelCase and snake_case indicates schema evolution
4. **Validation Ranges**: Pydantic's numeric validators help catch scale mismatches

## Impact

These fixes will allow:
- Proper OCR result caching without validation errors
- Correct entity mention queries in the monitor
- Full pipeline processing from OCR through entity extraction

## Next Steps

1. Apply the confidence scaling fix
2. Update all monitor queries to use correct column names
3. Consider creating a schema documentation file
4. Add unit tests for scale conversions