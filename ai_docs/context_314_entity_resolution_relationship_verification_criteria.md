# Context 314: Entity Resolution and Relationship Building Verification Criteria

## Current Pipeline Status
- ✅ OCR Extraction: Successfully extracting text from documents
- ✅ Text Chunking: Creating multiple chunks with proper overlap and character indices
- ✅ Entity Extraction: Extracting Person, Org, Location, and Date entities
- ⏳ **Entity Resolution**: Next stage to verify
- ⏳ **Relationship Building**: Final stage to verify

## Stage 1: Entity Resolution Verification Criteria

### 1.1 **Successful Task Execution**
- [ ] Entity resolution task (`resolve_document_entities`) completes without errors
- [ ] Task processes all entity mentions from document
- [ ] No timeout or memory errors during resolution
- [ ] Proper error handling for edge cases

### 1.2 **Deduplication Quality**
- [ ] Similar entity mentions are grouped correctly
  - "John Smith" and "J. Smith" → same canonical entity
  - "Acuity Insurance" and "Acuity, A Mutual Insurance Company" → same canonical entity
- [ ] Entity type consistency maintained (PERSON stays PERSON)
- [ ] No over-merging (different entities kept separate)
- [ ] Confidence scores properly aggregated

### 1.3 **Canonical Entity Creation**
- [ ] Each canonical entity has required fields:
  - `canonical_entity_uuid`: Unique identifier
  - `entity_name`: Normalized/canonical name
  - `entity_type`: Consistent type (PERSON, ORG, LOCATION, DATE)
  - `aliases`: List of all variations found
  - `mention_count`: Total occurrences
  - `confidence_score`: Aggregated confidence
- [ ] Canonical names are clean and normalized
- [ ] All mentions linked to canonical entities

### 1.4 **Database Persistence**
- [ ] Canonical entities saved to `canonical_entities` table
- [ ] Entity mentions updated with `canonical_entity_uuid`
- [ ] Proper foreign key relationships maintained
- [ ] Transaction integrity (all or nothing)

### 1.5 **Resolution Logic**
- [ ] Name similarity matching works correctly
- [ ] Context-aware resolution (uses document context)
- [ ] Handles edge cases:
  - Single letter differences
  - Abbreviations and acronyms
  - Titles and suffixes
  - Common variations

### 1.6 **Performance Metrics**
- [ ] Processes typical document in < 10 seconds
- [ ] Memory usage stays reasonable
- [ ] Results cached in Redis
- [ ] Batch processing for efficiency

## Stage 2: Relationship Building Verification Criteria

### 2.1 **Successful Task Execution**
- [ ] Relationship building task (`build_entity_relationships`) completes without errors
- [ ] Task processes all canonical entities
- [ ] Relationships extracted from document context
- [ ] Pipeline marks as complete after this stage

### 2.2 **Relationship Detection**
- [ ] Extracts multiple relationship types:
  - Legal relationships (plaintiff vs defendant)
  - Corporate relationships (subsidiary of, represents)
  - Location relationships (located in, jurisdiction of)
  - Temporal relationships (filed on, dated)
- [ ] Relationships have directionality (from → to)
- [ ] Confidence scores for each relationship

### 2.3 **Relationship Data Quality**
- [ ] Each relationship has required fields:
  - `relationship_uuid`: Unique identifier
  - `source_entity_uuid`: From entity
  - `target_entity_uuid`: To entity
  - `relationship_type`: Type of relationship
  - `confidence_score`: Relationship confidence
  - `context`: Text evidence for relationship
  - `document_uuid`: Source document
- [ ] No self-relationships (entity to itself)
- [ ] No duplicate relationships
- [ ] Bidirectional relationships handled correctly

### 2.4 **Database Persistence**
- [ ] Relationships saved to `relationship_staging` table
- [ ] Proper foreign key constraints to canonical entities
- [ ] Relationship metadata preserved
- [ ] Ready for graph database export

### 2.5 **Context Analysis**
- [ ] Uses entity proximity in text
- [ ] Analyzes sentence structure
- [ ] Identifies relationship indicators:
  - Legal terms (vs, plaintiff, defendant)
  - Corporate terms (subsidiary, parent, owns)
  - Prepositions (of, in, by, for)
- [ ] Preserves evidence text

### 2.6 **Performance and Completion**
- [ ] Completes within reasonable time (< 20 seconds)
- [ ] Updates document status to "completed"
- [ ] Triggers any post-processing tasks
- [ ] Full pipeline metrics recorded

## Test Plan for Entity Resolution

### 1. **Pre-test Setup**
```python
# Clear existing canonical entities
DELETE FROM canonical_entities WHERE document_uuid = :uuid
UPDATE entity_mentions SET canonical_entity_uuid = NULL WHERE document_uuid = :uuid
```

### 2. **Trigger Entity Resolution**
```python
# Option 1: Direct call
resolve_document_entities.delay(document_uuid, entity_mentions_data)

# Option 2: Continuation from entity extraction
# Should trigger automatically after entity extraction
```

### 3. **Verify Resolution Results**
```sql
-- Check canonical entities created
SELECT ce.entity_name, ce.entity_type, 
       COUNT(em.id) as mention_count,
       ce.aliases
FROM canonical_entities ce
JOIN entity_mentions em ON ce.canonical_entity_uuid = em.canonical_entity_uuid
WHERE ce.document_uuid = :uuid
GROUP BY ce.canonical_entity_uuid;

-- Check all mentions are resolved
SELECT COUNT(*) as unresolved
FROM entity_mentions
WHERE document_uuid = :uuid
AND canonical_entity_uuid IS NULL;
```

## Test Plan for Relationship Building

### 1. **Pre-test Setup**
```python
# Clear existing relationships
DELETE FROM relationship_staging WHERE document_uuid = :uuid
```

### 2. **Trigger Relationship Building**
```python
# Should trigger automatically after entity resolution
build_entity_relationships.delay(document_uuid, canonical_entities_data)
```

### 3. **Verify Relationship Results**
```sql
-- Check relationships created
SELECT 
    s.entity_name as source,
    r.relationship_type,
    t.entity_name as target,
    r.confidence_score
FROM relationship_staging r
JOIN canonical_entities s ON r.source_entity_uuid = s.canonical_entity_uuid
JOIN canonical_entities t ON r.target_entity_uuid = t.canonical_entity_uuid
WHERE r.document_uuid = :uuid;

-- Check document marked complete
SELECT processing_status, processing_completed_at
FROM source_documents
WHERE document_uuid = :uuid;
```

## Expected Results

### Entity Resolution Success Metrics
- **Deduplication rate**: 20-40% (typical for legal documents)
- **Average aliases per entity**: 1.5-3
- **Resolution confidence**: > 0.8 average
- **Unresolved entities**: < 5%

### Relationship Building Success Metrics
- **Relationships per document**: 5-20 (varies by document type)
- **Relationship types found**: 3-5 different types
- **Average confidence**: > 0.7
- **Context preservation**: 100% (all relationships have evidence)

## Common Issues to Watch For

### Entity Resolution Issues
1. **Over-merging**: Different people with same name merged
2. **Under-merging**: Same entity not recognized due to variations
3. **Type conflicts**: Entity type changes during resolution
4. **Performance**: Large documents with many entities

### Relationship Building Issues
1. **False positives**: Proximity doesn't mean relationship
2. **Missing relationships**: Subtle relationships not detected
3. **Wrong direction**: From/to entities reversed
4. **Context loss**: Relationship detected but evidence not preserved

## Pipeline Completion Indicators

When both stages complete successfully:
1. Document status = "completed"
2. All entities have canonical forms
3. Relationships ready for graph export
4. Processing metrics recorded
5. All caches populated
6. No pending tasks for document