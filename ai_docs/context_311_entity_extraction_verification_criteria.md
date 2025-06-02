# Context 311: Entity Extraction Verification Criteria and Plan

## Current Pipeline Status
- ✅ OCR Extraction: Successfully extracting text from documents
- ✅ Text Chunking: Creating multiple chunks with proper overlap and character indices
- ⏳ **Entity Extraction**: Next stage to verify
- ⏳ Entity Resolution: Pending
- ⏳ Relationship Building: Pending

## Entity Extraction Verification Criteria

### 1. **Successful Task Execution**
- [ ] Entity extraction task (`extract_entities_from_chunks`) completes without errors
- [ ] Task returns a list of entity mentions
- [ ] No timeout or memory errors during extraction

### 2. **Entity Detection**
- [ ] Extracts multiple entity types (Person, Organization, Location, etc.)
- [ ] Finds entities across all chunks, not just the first one
- [ ] Entity count is reasonable for document content (typically 10-50 entities per document)

### 3. **Entity Data Quality**
- [ ] Each entity has required fields:
  - `entity_text`: The actual text of the entity
  - `entity_type`: Valid type (PERSON, ORG, LOCATION, etc.)
  - `chunk_uuid`: Links to source chunk
  - `start_char` and `end_char`: Position within chunk
  - `confidence_score`: Between 0.0 and 1.0
- [ ] No duplicate entities within same chunk
- [ ] Entity positions are within chunk boundaries

### 4. **Database Persistence**
- [ ] All entities saved to `entity_mentions` table
- [ ] Proper foreign key relationships:
  - `document_uuid` matches source document
  - `chunk_uuid` matches source chunk
- [ ] Character indices properly stored (not NULL)

### 5. **OpenAI Integration**
- [ ] Successfully calls OpenAI API for entity extraction
- [ ] Handles API errors gracefully (rate limits, timeouts)
- [ ] Uses appropriate model and prompts
- [ ] Respects token limits

### 6. **Performance Metrics**
- [ ] Processes chunks in parallel when possible
- [ ] Caches results in Redis
- [ ] Completes within reasonable time (< 30s for typical document)

## Test Plan

### 1. **Pre-test Setup**
```python
# Clear existing entities for test document
DELETE FROM entity_mentions WHERE document_uuid = :uuid

# Verify chunks exist
SELECT COUNT(*) FROM document_chunks WHERE document_uuid = :uuid
```

### 2. **Trigger Entity Extraction**
```python
# Option 1: Continue pipeline after chunking
continue_pipeline_after_chunking.delay(document_uuid, chunk_uuids)

# Option 2: Direct entity extraction
extract_entities_from_chunks.delay(document_uuid, chunk_data)
```

### 3. **Monitor Execution**
- Check task status and logs
- Monitor OpenAI API calls
- Verify Redis caching

### 4. **Verify Results**
```sql
-- Check entity counts by type
SELECT entity_type, COUNT(*) 
FROM entity_mentions 
WHERE document_uuid = :uuid
GROUP BY entity_type;

-- Verify entity positions
SELECT em.entity_text, em.entity_type, 
       em.start_char, em.end_char,
       LENGTH(dc.text) as chunk_length
FROM entity_mentions em
JOIN document_chunks dc ON em.chunk_uuid = dc.chunk_uuid
WHERE em.document_uuid = :uuid;
```

## Expected Issues to Watch For

### 1. **OpenAI API Issues**
- Missing or invalid API key
- Rate limiting
- Token limit exceeded
- Network timeouts

### 2. **Data Format Issues**
- Incorrect prompt format
- JSON parsing errors
- Character encoding issues

### 3. **Database Issues**
- Column mapping mismatches
- Foreign key constraints
- Duplicate entity UUIDs

### 4. **Memory/Performance Issues**
- Large chunks causing OOM
- Slow API responses
- Database connection pool exhaustion

## Success Metrics

A successful entity extraction stage should:
1. Extract 15-50 entities from a typical legal document
2. Cover all major entity types (Person, Organization, Location)
3. Have > 0.7 average confidence score
4. Complete in < 30 seconds
5. Store all entities with valid character positions
6. Continue to entity resolution stage automatically

## Next Stage Trigger

Once entity extraction is verified:
```python
# Pipeline should automatically continue to:
resolve_entities.delay(document_uuid, entity_mention_ids)
```