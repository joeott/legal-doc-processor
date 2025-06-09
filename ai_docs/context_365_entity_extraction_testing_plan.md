# Context 365: Entity Extraction Testing Plan with Verification Criteria

## Date: 2025-06-04 00:30
## Updated: 2025-06-04 01:10

### Objective
Test and fix the entity extraction stage (Stage 4) to achieve 66% pipeline completion, then proceed to test entity resolution (Stage 5) and relationship building (Stage 6).

### CURRENT STATUS: Stage 4 COMPLETED ✓ (66% Pipeline Complete)
- Entity extraction is now working successfully
- 29 entities extracted from 4 chunks
- Entity resolution started but failed (fixable issue)

### Detailed Task List with Verification Criteria

#### Phase 1: Entity Extraction Testing (Stage 4)

**Task 1.1: Restart Celery Workers**
- Action: Kill existing workers and restart with updated code
- Commands:
  ```bash
  ps aux | grep "[c]elery" | awk '{print $2}' | xargs -r kill -9
  celery -A scripts.celery_app worker --loglevel=info --queues=default,ocr,text,entity,graph,cleanup &
  ```
- Verification: `ps aux | grep celery` shows new worker process

**Task 1.2: Create/Verify Test Script**
- Action: Check if test_entity_extraction_direct.py exists, create if needed
- Verification: Script exists and imports correctly

**Task 1.3: Execute Entity Extraction Test**
- Action: Run test with existing document
- Command: `python3 scripts/test_entity_extraction_direct.py`
- Success Criteria:
  - No import errors
  - OpenAI API call succeeds
  - Entities are extracted (expecting PERSON, ORG, LOCATION, DATE types only)
  - Entity mentions saved to database
  - Cache updated with results
  - Task triggers entity resolution

**Task 1.4: Monitor Extraction Results**
- Action: Check document state and entity data
- Commands:
  ```bash
  python3 scripts/monitor_document_complete.py 4909739b-8f12-40cd-8403-04b8b1a79281
  python3 scripts/check_entity_mentions.py 4909739b-8f12-40cd-8403-04b8b1a79281
  ```
- Verification:
  - Entity extraction status = "completed"
  - Entity mentions count > 0
  - Only allowed entity types present

#### Phase 2: Entity Resolution Testing (Stage 5)

**Task 2.1: Verify Resolution Triggered**
- Action: Check if resolve_document_entities task started
- Verification: Redis state shows "entity_resolution" = "in_progress" or "completed"

**Task 2.2: Monitor Resolution Progress**
- Success Criteria:
  - Canonical entities created
  - Entity mentions updated with canonical UUIDs
  - Deduplication rate calculated
  - Relationship building task triggered

**Task 2.3: Fix Resolution Errors (if any)**
- Common issues to check:
  - Database column mismatches
  - JSON serialization errors
  - UUID format issues

#### Phase 3: Relationship Building Testing (Stage 6)

**Task 3.1: Verify Relationships Task Started**
- Action: Check if build_document_relationships triggered
- Verification: Redis state shows "relationships" = "in_progress"

**Task 3.2: Monitor Relationship Building**
- Success Criteria:
  - Structural relationships created
  - Pipeline finalization triggered
  - Document status = COMPLETED

### Expected Error Patterns and Fixes

1. **OpenAI API Errors**
   - Rate limiting → Add retry logic
   - Invalid response format → Better JSON parsing
   - API key issues → Verify environment variable

2. **Database Column Mismatches**
   - entity_mentions table columns
   - canonical_entities table columns
   - Check for JSONB fields

3. **Model Validation Errors**
   - Pydantic validation failures
   - Missing required fields
   - Type mismatches

### Monitoring Commands Sequence

```bash
# 1. Watch worker logs
tail -f celery.log

# 2. Monitor document state
watch -n 2 'python3 scripts/monitor_document_complete.py 4909739b-8f12-40cd-8403-04b8b1a79281'

# 3. Check database state
psql -h localhost -p 5433 -U app_user -d legal_doc_processing -c "SELECT COUNT(*) FROM entity_mentions WHERE document_uuid = '4909739b-8f12-40cd-8403-04b8b1a79281';"

# 4. Check Redis cache
redis-cli KEYS "*4909739b-8f12-40cd-8403-04b8b1a79281*"
```

### Success Metrics

- Stage 4 (Entity Extraction): Entities extracted and saved
- Stage 5 (Entity Resolution): Canonical entities created
- Stage 6 (Relationships): Graph relationships staged
- Overall: Document processing status = COMPLETED

### Timeline
- Entity Extraction: 10-15 minutes
- Entity Resolution: 10-15 minutes  
- Relationship Building: 5-10 minutes
- Total: 30-40 minutes for full pipeline test

### Next Actions
1. ✓ Execute Phase 1 tasks - COMPLETED
2. ✓ Document any errors encountered - COMPLETED
3. ✓ Apply fixes iteratively - COMPLETED
4. ✓ Update this document with results - IN PROGRESS
5. Fix entity resolution error and complete pipeline
6. Create context_366 with final outcomes

### Phase 1 Results: Entity Extraction SUCCESSFUL

**Issues Fixed:**
1. EntityExtractionResultModel expected ExtractedEntity not EntityMentionMinimal
2. ProcessingResultStatus.FAILED → ProcessingResultStatus.FAILURE
3. Converted between model types to match expectations

**Entities Extracted:**
- Total: 29 entities from 4 chunks
- Types: PERSON (7), ORG (8), LOCATION (9), DATE (5)
- Examples: "Javier Hinojo", "Wombat Acquisitions", "North Carolina", "10/23/24"

**Next Error to Fix:**
Entity resolution failing with "'NoneType' object has no attribute 'lower'" - some entity texts are None in the data passed to resolution.