# Context 542: Pipeline Stage 5-6 Blocking Issue Root Cause Identified and Resolved

## Date: 2025-06-13

### Critical Discovery: Dual-Path Entity Resolution with Inconsistent Implementations

#### Problem Summary
The pipeline was successfully executing stages 1-4 but failing to trigger stages 5-6 (relationship building and finalization). The root cause was a combination of:
1. Early-return path for cached entities that skipped normal flow
2. Incorrect SQL column names in chunk retrieval queries
3. Field name mismatches between cached and database-retrieved chunks

### Code Analysis with Verbatim Citations

#### 1. Early Return Path Issue
**Location**: `/opt/legal-doc-processor/scripts/pdf_tasks.py:1821-1928`

The `resolve_document_entities` function has two distinct paths:

**Path A - Cached Entities (Early Return)**:
```python
# Line 1821-1824
if REDIS_ACCELERATION_ENABLED and redis_manager.is_redis_healthy():
    cache_key = CacheKeys.format_key(CacheKeys.DOC_CANONICAL_ENTITIES, document_uuid=document_uuid)
    cached_entities = redis_manager.get_cached(cache_key)
    if cached_entities:
```

This path only executes if canonical entities are already cached. The relationship building trigger is at:
```python
# Lines 1907-1921
if project_uuid and chunks and cached_entities:
    logger.info(f"Triggering relationship building with {len(cached_entities)} cached canonical entities")
    build_document_relationships.apply_async(
        args=[
            document_uuid,
            document_metadata,
            project_uuid,
            chunks,
            entity_mentions_list,
            cached_entities
        ],
        queue='graph'
    )
else:
    logger.warning(f"Missing required data for relationship building: project_uuid={project_uuid}, chunks={len(chunks) if chunks else 0}, entities={len(cached_entities)}")
```

**Path B - Normal Entity Resolution**:
The normal path continues at line 1929 and eventually triggers relationship building at:
```python
# Lines 2447-2465
if project_uuid and chunks and resolution_result['canonical_entities']:
    logger.info(f"Triggering relationship building with {len(resolution_result['canonical_entities'])} canonical entities")
    
    # Ensure document_uuid is in metadata
    if 'document_uuid' not in document_metadata:
        document_metadata['document_uuid'] = document_uuid
    
    build_document_relationships.apply_async(
        args=[
            document_uuid,
            document_metadata,
            project_uuid,
            chunks,
            entity_mentions_list,
            resolution_result['canonical_entities']
        ]
    )
else:
    logger.warning(f"Skipping relationship building - missing data: project_uuid={bool(project_uuid)}, chunks={len(chunks) if chunks else 0}, entities={len(resolution_result['canonical_entities'])}")
```

#### 2. SQL Column Name Errors
**Location**: `/opt/legal-doc-processor/scripts/pdf_tasks.py`

Multiple locations had incorrect column names:

**First occurrence** (Lines 1843-1849):
```python
chunks_query = sql_text("""
    SELECT chunk_uuid, document_uuid, chunk_index, text_content, 
           start_char, end_char, metadata
    FROM document_chunks
    WHERE document_uuid = :doc_uuid
    ORDER BY chunk_index
""")
```

**Second occurrence** (Lines 2391-2397):
```python
chunks_query = sql_text("""
    SELECT chunk_uuid, document_uuid, chunk_index, text_content, 
           start_char, end_char, metadata
    FROM document_chunks
    WHERE document_uuid = :doc_uuid
    ORDER BY chunk_index
""")
```

**Correct column names** (from database schema):
- `text` (not `text_content`)
- `start_char_index` (not `start_char`)
- `end_char_index` (not `end_char`)

#### 3. Field Name Mismatch in Cached Chunks
**Location**: `/opt/legal-doc-processor/scripts/pdf_tasks.py:1550-1556`

When chunks are cached during the chunking stage:
```python
serialized_chunks.append({
    'chunk_uuid': chunk_data['chunk_uuid'],
    'chunk_text': chunk_data['text'],  # Map 'text' to 'chunk_text'
    'chunk_index': chunk_data['chunk_index'],
    'start_char': chunk_data.get('char_start_index', 0),
    'end_char': chunk_data.get('char_end_index', len(chunk_data['text']))
})
```

But when retrieved from database in entity resolution (Lines 1855-1863):
```python
chunks.append({
    'chunk_uuid': str(row.chunk_uuid),
    'document_uuid': str(row.document_uuid),
    'chunk_index': row.chunk_index,
    'text': row.text_content,  # Note: field name difference
    'start_char': row.start_char,
    'end_char': row.end_char,
    'metadata': row.metadata or {}
})
```

The cached chunks use `chunk_text` while database-retrieved chunks use `text`.

### Worker Log Evidence

From `/opt/legal-doc-processor/logs/worker_main.log`:
```
WARNING:scripts.pdf_tasks:Skipping relationship building - missing data: project_uuid=True, chunks=0, entities=17
```

This showed that:
- `project_uuid` was found ✅
- `chunks=0` (not found in cache) ❌
- `entities=17` (canonical entities created) ✅

### Debug Results

From `debug_chunks_retrieval.py` output:
```
Chunks key: cache:doc:chunks:ad63957e-8a09-4cf3-a423-ac1f4e784fc3
get_cached result: <class 'list'>, length: 4
First chunk: {'chunk_uuid': 'a67629eb-0a03-4579-8088-c5ebc443444f', 'chunk_text': '...', 'chunk_index': 0, 'start_char': 0, 'end_char': 1000}
```

This confirmed chunks WERE in cache but with field name `chunk_text` instead of `text`.

### Resolution Applied

1. **Fixed SQL queries**: Changed column names to match actual database schema
   - `text_content` → `text`
   - `start_char` → `start_char_index`
   - `end_char` → `end_char_index`

2. **Next steps**: Need to ensure field name consistency between cached and DB-retrieved chunks

### Impact
This blocking issue prevented the pipeline from completing stages 5-6 for ALL documents, effectively making the system unable to build relationships or finalize document processing. The fix should restore full 6-stage pipeline functionality.