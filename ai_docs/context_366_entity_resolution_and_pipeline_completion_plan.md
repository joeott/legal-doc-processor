# Context 366: Entity Resolution and Pipeline Completion Plan

## Date: 2025-06-04 01:20

### Historical Context and Current State

#### The Journey So Far
1. **The Great Culling**: We intentionally reduced 700+ scripts to create a clean, maintainable codebase
2. **Pipeline Breakdown**: This consolidation broke the document processing pipeline (0% efficacy)
3. **Systematic Recovery**: We've been methodically recovering each stage:
   - Stage 1: Document Creation ✓ (Working)
   - Stage 2: OCR via Textract ✓ (3,290 chars extracted)
   - Stage 3: Text Chunking ✓ (4 chunks created)
   - Stage 4: Entity Extraction ✓ (29 entities extracted)
   - Stage 5: Entity Resolution ✗ (Failed - fixable)
   - Stage 6: Relationship Building ○ (Not tested)

**Current Status**: 66% Pipeline Complete (4 of 6 stages operational)

### Critical Philosophy: No New Scripts
Missing modules are EXPECTED - they were intentionally culled. The solution is NOT to recreate them but to:
1. Implement missing functionality inline where needed
2. Keep each script focused on its single responsibility
3. Maintain the clean architecture we've achieved

### Entity Resolution Fix Plan

#### The Current Error
```
AttributeError: 'NoneType' object has no attribute 'lower'
File: /opt/legal-doc-processor/scripts/pdf_tasks.py, Line: 952
Context: similarity = SequenceMatcher(None, text1.lower(), text2.lower()).ratio()
```

#### Root Cause Analysis
The error occurs because:
1. Entity extraction is passing entity data as dictionaries from cache
2. Some entity texts might be None or missing the expected key
3. The resolve_entities_simple function expects 'entity_text' but might be getting 'text'

#### Detailed Fix Implementation

**Step 1: Add Defensive Checks in resolve_entities_simple**
```python
# In pdf_tasks.py, around line 945
text1 = mention1.entity_text if hasattr(mention1, 'entity_text') else mention1.get('entity_text')
# Add null check
if not text1:
    logger.warning(f"Skipping entity with null text at index {i}")
    continue
```

**Step 2: Ensure Consistent Data Structure**
- Entity extraction returns dictionaries with 'text' key
- Entity resolution expects 'entity_text' key
- Need to normalize this in the data passed between stages

**Step 3: Add Data Validation**
Before processing entities, validate structure:
```python
# Validate and normalize entity data
for mention in entity_mentions:
    if 'text' in mention and 'entity_text' not in mention:
        mention['entity_text'] = mention['text']
    if not mention.get('entity_text'):
        logger.warning(f"Skipping entity with missing text: {mention}")
        continue
```

### Relationship Building Preparation

#### Expected Missing Modules
Based on the pattern, we expect these modules might be missing:
1. `relationship_extraction_utils.py`
2. `graph_staging_helpers.py`
3. `structural_relationship_builder.py`

#### Preemptive Implementation Plan
The GraphService in graph_service.py should handle relationships, but may reference missing utilities. We'll need to:
1. Check what GraphService.stage_structural_relationships expects
2. Implement any missing helper functions inline
3. Ensure proper data flow from resolved entities to relationship building

### Validation Criteria for Mission Success

#### Stage 5: Entity Resolution Success Criteria
1. **No Null Errors**: All entity texts properly validated before processing
2. **Deduplication Working**: Similar entities grouped (e.g., "Javier Hinojo" appears 3 times, should resolve to 1 canonical)
3. **Canonical Entities Created**: Database should show canonical_entities records
4. **Mentions Updated**: entity_mentions table should have canonical_entity_uuid populated
5. **Resolution Metrics**: Expect ~50-70% deduplication rate for this test document
6. **Next Stage Triggered**: build_document_relationships task should start automatically

#### Stage 6: Relationship Building Success Criteria
1. **Structural Relationships**: Document→Chunk→Entity relationships created
2. **Graph Staging**: relationship_staging table populated
3. **No Import Errors**: All functionality implemented inline
4. **Pipeline Completion**: Document status = COMPLETED
5. **Final State Updated**: Redis and database show complete status

### Implementation Sequence

#### Phase 1: Fix Entity Resolution (15-20 minutes)
1. Kill worker: `ps aux | grep "[c]elery" | awk '{print $2}' | xargs -r kill -9`
2. Fix null check in resolve_entities_simple
3. Add data normalization for entity structure
4. Restart worker
5. Test with monitoring

#### Phase 2: Verify Resolution Results (10 minutes)
1. Check canonical entities created:
   ```sql
   SELECT COUNT(*), entity_type FROM canonical_entities 
   WHERE created_at > NOW() - INTERVAL '1 hour' 
   GROUP BY entity_type;
   ```
2. Verify mention updates:
   ```sql
   SELECT COUNT(*) FROM entity_mentions 
   WHERE canonical_entity_uuid IS NOT NULL 
   AND document_uuid = '4909739b-8f12-40cd-8403-04b8b1a79281';
   ```

#### Phase 3: Relationship Building (20-30 minutes)
1. Monitor for import errors when task starts
2. Implement missing functions inline as needed
3. Verify graph relationships created
4. Check final pipeline status

### Monitoring Commands

```bash
# Watch the full pipeline
watch -n 2 'python3 scripts/monitor_document_complete.py 4909739b-8f12-40cd-8403-04b8b1a79281'

# Check specific stage status
redis-cli get "doc:state:4909739b-8f12-40cd-8403-04b8b1a79281" | jq .

# Database verification
psql -h localhost -p 5433 -U app_user -d legal_doc_processing -c "
SELECT 
    (SELECT COUNT(*) FROM entity_mentions WHERE document_uuid = '4909739b-8f12-40cd-8403-04b8b1a79281') as mentions,
    (SELECT COUNT(*) FROM canonical_entities WHERE canonical_entity_uuid IN 
        (SELECT DISTINCT canonical_entity_uuid FROM entity_mentions 
         WHERE document_uuid = '4909739b-8f12-40cd-8403-04b8b1a79281')) as canonical,
    (SELECT COUNT(*) FROM relationship_staging WHERE source_id = '4909739b-8f12-40cd-8403-04b8b1a79281') as relationships;
"
```

### Risk Mitigation

1. **If GraphService References Missing Modules**:
   - Check imports in graph_service.py first
   - Implement needed functions directly in graph_service.py
   - Follow the pattern from entity_service.py fixes

2. **If Database Columns Don't Match**:
   - Use direct SQL inspection
   - Update column mappings in rds_utils.py if needed
   - Add to COLUMN_MAPPINGS dictionary

3. **If Pipeline Stalls**:
   - Check celery worker logs for specific errors
   - Each stage should trigger the next automatically
   - Manual trigger: `build_document_relationships.delay(...)`

### Expected Timeline
- Entity Resolution Fix: 15-20 minutes
- Resolution Verification: 10 minutes  
- Relationship Building: 20-30 minutes
- End-to-End Verification: 10 minutes
- **Total: 55-70 minutes to 100% pipeline completion**

### Success Metrics
- **Before**: 66% pipeline complete (4/6 stages)
- **Target**: 100% pipeline complete (6/6 stages)
- **Document Status**: COMPLETED in database
- **Quality Check**: All 29 entities resolved to ~10-15 canonical entities
- **Graph Check**: Structural relationships staged for Neo4j

### Next Context Note (367)
Will document:
1. Final pipeline completion status
2. Any additional inline implementations required
3. Performance metrics (time per stage)
4. Recommendations for production deployment
5. List of any remaining improvements needed

The key to success is maintaining our discipline: when we find missing imports, we implement the functionality inline rather than creating new files. This keeps our codebase clean and manageable while achieving full functionality.