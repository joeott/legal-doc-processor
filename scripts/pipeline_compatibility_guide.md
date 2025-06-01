# Pipeline Compatibility Guide

## The Problem

The preprocessing pipeline expects a complex Supabase schema with tables like:
- `source_documents`
- `document_chunks` 
- `entity_mentions`
- `canonical_entities`
- `relationship_staging`

But the actual deployed schema uses simplified table names:
- `documents`
- `chunks`
- `entities`
- `relationships`

## The Solution

### Option 1: Schema Mapping Layer (Implemented in rds_utils.py)

I've added a transparent mapping layer in `rds_utils.py` that:

1. **Maps table names** automatically:
   - `source_documents` → `documents`
   - `document_chunks` → `chunks`
   - `entity_mentions` → `entities`
   - `canonical_entities` → `entities` (unified)
   - `relationship_staging` → `relationships`

2. **Maps column names** to match the simplified schema:
   - `original_file_name` → `original_filename`
   - `detected_file_type` → `mime_type`
   - `celery_status` → `processing_status`
   - `text` → `content` (for chunks)
   - `value` → `entity_text` (for entities)
   - And many more...

3. **Simplifies processing statuses**:
   - Complex statuses like `ocr_processing`, `entity_completed` → simple `processing`/`completed`/`failed`

### Option 2: Direct Schema Fix (Alternative)

If you prefer to fix the schema instead of using mapping:

```sql
-- Add missing tables as views that map to simplified tables
CREATE VIEW source_documents AS 
SELECT 
    document_uuid,
    project_uuid,
    original_filename as original_file_name,
    mime_type as detected_file_type,
    s3_bucket,
    s3_key,
    file_size_bytes,
    file_hash as md5_hash,
    processing_status as celery_status,
    processing_error as error_message,
    celery_task_id,
    page_count,
    chunk_count,
    entity_count,
    metadata as ocr_metadata_json,
    created_at,
    updated_at
FROM documents;

CREATE VIEW document_chunks AS
SELECT
    chunk_id as chunk_uuid,
    document_uuid,
    chunk_index,
    content as text,
    page_number,
    token_count as word_count,
    metadata as metadata_json,
    created_at
FROM chunks;

CREATE VIEW entity_mentions AS
SELECT
    entity_id as entity_mention_uuid,
    document_uuid,
    chunk_id as chunk_uuid,
    entity_type,
    entity_text as value,
    canonical_name as normalized_value,
    confidence_score,
    start_offset as offset_start,
    end_offset as offset_end,
    attributes as attributes_json,
    created_at
FROM entities;

CREATE VIEW canonical_entities AS
SELECT DISTINCT
    entity_id as canonical_entity_uuid,
    canonical_name,
    entity_type,
    document_uuid,
    attributes as attributes_json,
    created_at
FROM entities
WHERE canonical_name IS NOT NULL;

CREATE VIEW relationship_staging AS
SELECT
    relationship_id,
    document_uuid as source_id,
    from_entity_id as from_node_id,
    to_entity_id as to_node_id,
    relationship_type,
    confidence_score,
    metadata as properties,
    created_at
FROM relationships;
```

### Option 3: Minimal Code Changes (Simplest)

Modify only the critical parts:

1. **In `scripts/db.py`**, add at the top after imports:
```python
# Import the mapping from rds_utils
from scripts.rds_utils import map_table_name, map_columns
```

2. The rds_utils.py changes are already implemented.

3. **Test with**: 
```bash
python scripts/test_schema_mapping.py
```

## Testing the Fix

1. **Test schema mapping**:
```bash
python scripts/test_schema_mapping.py
```

2. **Test document processing**:
```bash
# Create a test document entry
python -c "
from scripts.db import DatabaseManager
from scripts.core.schemas import SourceDocumentModel
import uuid

db = DatabaseManager()
doc = SourceDocumentModel(
    document_uuid=uuid.uuid4(),
    original_file_name='test.pdf',
    detected_file_type='application/pdf',
    s3_bucket='test-bucket',
    s3_key='test/test.pdf'
)
result = db.create_source_document(doc)
print(f'Created document: {result.document_uuid if result else \"FAILED\"}')
"
```

3. **Run a simple pipeline test**:
```bash
# This should now work with the mapping
python scripts/pdf_tasks.py
```

## What This Fixes

With the schema mapping in place:

1. ✅ The Celery tasks can store documents in the `documents` table
2. ✅ Chunks are stored in `chunks` table with proper column mapping
3. ✅ Entities are stored in `entities` table (both mentions and canonical)
4. ✅ Relationships work with the simplified schema
5. ✅ Status tracking works with simplified status values

## Remaining Issues

Even with schema mapping, you may need to:

1. Ensure the database has the simplified schema deployed
2. Handle any missing columns by adding them or adjusting the models
3. Test the full pipeline end-to-end

## Summary

The simplest path is to use the schema mapping layer I've implemented in `rds_utils.py`. This allows the existing pipeline code to work with the simplified database schema without major changes. The mapping is transparent and handles both table names and column names automatically.