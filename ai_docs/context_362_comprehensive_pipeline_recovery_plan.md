# Context 362: Comprehensive Pipeline Recovery Plan - From OCR to 99% Efficacy

## Date: 2025-06-03 23:00

### Executive Summary
We've successfully recovered OCR (Stage 2 of 6). This plan outlines the systematic approach to recover the remaining 4 stages while maintaining our goal of a clean, microservices-style codebase where each script has a single, well-defined purpose.

### Current State Analysis

#### What's Working
- Document creation and S3 upload
- Celery task orchestration
- OCR extraction via Textract
- Redis caching layer
- Database connectivity

#### What Needs Recovery
1. **Text Chunking** (Stage 3)
2. **Entity Extraction** (Stage 4)
3. **Entity Resolution** (Stage 5)
4. **Relationship Building** (Stage 6)

### Recovery Philosophy

1. **Maintain Single Responsibility**: Each script does ONE thing well
2. **Fix Don't Expand**: Repair API mismatches without adding complexity
3. **Document Everything**: Every fix gets documented for future reference
4. **Test Incrementally**: Verify each stage before moving to the next

## Phase 1: Text Chunking Recovery (Est. 2-3 hours)

### Expected Issues
Based on OCR recovery patterns, we'll likely encounter:
- Column name mismatches (text_content vs content)
- Missing chunking utility functions
- Parameter mismatches in chunk creation
- Foreign key reference issues

### Step-by-Step Plan

1. **Trigger Chunking Manually**
   ```python
   # Create test script: scripts/test_chunking_stage.py
   from scripts.pdf_tasks import chunk_document_text
   result = chunk_document_text.delay('4909739b-8f12-40cd-8403-04b8b1a79281')
   ```

2. **Expected Errors & Fixes**
   - `AttributeError: 'ChunkingUtils' object has no attribute 'X'`
     - Fix: Verify chunking_utils.py has all required methods
   - `Column 'source_document_uuid' does not exist`
     - Fix: Update to use 'document_uuid' 
   - `TypeError: create_chunk() got unexpected keyword argument`
     - Fix: Align parameters with actual method signatures

3. **Verification**
   - Check document_chunks table for new records
   - Verify chunk overlap and boundaries
   - Ensure metadata is properly stored

## Phase 2: Entity Extraction Recovery (Est. 3-4 hours)

### Expected Issues
- OpenAI API integration changes
- Entity model validation errors
- Batch processing parameter mismatches
- Missing entity type mappings

### Step-by-Step Plan

1. **Test Entity Extraction**
   ```python
   # Create test script: scripts/test_entity_extraction.py
   from scripts.pdf_tasks import extract_entities_from_chunks
   result = extract_entities_from_chunks.delay('4909739b-8f12-40cd-8403-04b8b1a79281')
   ```

2. **Likely Fixes Needed**
   - Update OpenAI client initialization
   - Fix entity_mentions table column names
   - Repair JSON serialization for entity data
   - Ensure proper chunk-to-entity linking

3. **Critical Checks**
   - Verify OpenAI API key is loaded
   - Check rate limiting implementation
   - Validate entity type classifications

## Phase 3: Entity Resolution Recovery (Est. 2-3 hours)

### Expected Issues
- Deduplication algorithm references
- Canonical entity creation errors
- Missing similarity calculation functions
- Graph database integration issues

### Step-by-Step Plan

1. **Test Resolution Logic**
   ```python
   # Create test script: scripts/test_entity_resolution.py
   from scripts.pdf_tasks import resolve_document_entities
   result = resolve_document_entities.delay('4909739b-8f12-40cd-8403-04b8b1a79281')
   ```

2. **Expected Fixes**
   - Update canonical_entities table references
   - Fix entity matching algorithms
   - Repair confidence score calculations
   - Ensure proper mention-to-canonical linking

## Phase 4: Relationship Building Recovery (Est. 2-3 hours)

### Expected Issues
- Graph staging table mismatches
- Missing relationship extraction logic
- Neo4j integration errors (if used)
- Relationship type mappings

### Step-by-Step Plan

1. **Test Relationship Extraction**
   ```python
   # Create test script: scripts/test_relationship_building.py
   from scripts.pdf_tasks import build_document_relationships
   result = build_document_relationships.delay('4909739b-8f12-40cd-8403-04b8b1a79281')
   ```

2. **Required Fixes**
   - Update relationship_staging table operations
   - Fix entity pair extraction logic
   - Ensure proper relationship typing
   - Validate graph export format

## Phase 5: End-to-End Testing (Est. 2 hours)

### Comprehensive Test Suite

1. **Single Document Test**
   ```python
   # scripts/test_single_document_e2e.py
   - Submit new document
   - Monitor all 6 stages
   - Verify final output
   ```

2. **Batch Processing Test**
   ```python
   # scripts/test_batch_processing.py
   - Submit 10 documents
   - Track success rates
   - Identify bottlenecks
   ```

3. **Error Recovery Test**
   ```python
   # scripts/test_error_recovery.py
   - Simulate failures at each stage
   - Verify retry mechanisms
   - Test cleanup procedures
   ```

## Phase 6: Production Hardening (Est. 3 hours)

### Code Quality Improvements

1. **Standardize Error Handling**
   - Consistent exception types
   - Proper error propagation
   - Meaningful error messages

2. **Optimize Performance**
   - Batch database operations
   - Implement connection pooling
   - Add progress tracking

3. **Enhance Monitoring**
   ```python
   # scripts/cli/monitor.py enhancements
   - Real-time pipeline status
   - Performance metrics
   - Error rate tracking
   ```

## Implementation Schedule

### Day 1 (Immediate)
- **Morning**: Phase 1 - Chunking Recovery
- **Afternoon**: Phase 2 - Entity Extraction Recovery

### Day 2
- **Morning**: Phase 3 - Entity Resolution
- **Afternoon**: Phase 4 - Relationship Building

### Day 3
- **Morning**: Phase 5 - E2E Testing
- **Afternoon**: Phase 6 - Production Hardening

## Success Metrics

### Stage-by-Stage
- Stage 3 (Chunking): 100+ chunks per document
- Stage 4 (Entities): 50+ entities extracted
- Stage 5 (Resolution): 80%+ deduplication rate
- Stage 6 (Relationships): 20+ relationships identified

### Overall Pipeline
- **Target**: 99% document completion rate
- **Performance**: <5 min per document
- **Reliability**: <1% failure rate

## Risk Mitigation

1. **API Changes**: Document all API contracts
2. **Performance**: Add caching at each stage
3. **Failures**: Implement circuit breakers
4. **Data Loss**: Ensure idempotent operations

## Maintenance Guidelines

### Each Script Should:
1. Have a single, clear purpose
2. Use consistent parameter names
3. Include comprehensive logging
4. Handle errors gracefully
5. Be independently testable

### Avoid:
1. Cross-script dependencies
2. Shared mutable state
3. Implicit assumptions
4. Hard-coded values
5. Complex inheritance chains

## Next Immediate Action

1. Create `scripts/test_chunking_stage.py`
2. Run chunking test
3. Document first error
4. Apply fix methodology from OCR recovery
5. Repeat until chunking works

## Key Principles

1. **One Fix at a Time**: Don't try to fix multiple issues simultaneously
2. **Test After Each Fix**: Verify the fix worked before moving on
3. **Document Everything**: Future you will thank current you
4. **Keep It Simple**: Resist the urge to over-engineer
5. **Stay Focused**: Each script = one responsibility

This plan provides a clear roadmap from our current 50% completion to the target 99% efficacy while maintaining code quality and manageability.