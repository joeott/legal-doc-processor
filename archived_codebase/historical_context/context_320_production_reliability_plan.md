# Context 320: Production Reliability and Code Consolidation Plan

## Executive Summary

This session focuses on transforming our functionally complete pipeline into a production-ready system with 99% reliability. We will fix critical operational issues, migrate to minimal models throughout, and consolidate the codebase for simplicity and robustness.

## Current State Analysis

### What's Working
- All 5 pipeline stages are functionally implemented and verified
- Single document successfully processed through 4/6 stages
- Async OCR with Textract operational
- Entity extraction limited to essential types (Person, Org, Location, Date)
- Fuzzy matching entity resolution functional
- Redis caching infrastructure in place

### Critical Issues Blocking Production
1. **OCR File Path Issue (80% failure rate)**:
   - System expects local files but receives S3 keys
   - Prevents processing of any new documents
   
2. **Pipeline Continuation Failure**:
   - Processing stops after entity resolution
   - Relationship building not triggered
   - Documents never marked complete

3. **Data Consistency Problems**:
   - Canonical entities created but not retrievable
   - Prevents downstream processing

4. **Code Complexity**:
   - Multiple model definitions (full vs minimal)
   - Scattered scripts with overlapping functionality
   - Inconsistent error handling patterns

## Session Goals

### Primary Objective
Achieve 99% document processing success rate by fixing operational issues and consolidating to a clean, minimal model architecture.

### Specific Goals
1. **Immediate Fixes (Hours 1-2)**:
   - Fix S3/local file path handling in OCR
   - Resolve pipeline continuation after entity resolution
   - Fix canonical entity persistence/retrieval

2. **Model Migration (Hours 3-5)**:
   - Consolidate all processing to use minimal models only
   - Remove complex columns from database schema
   - Update all scripts to use single model definitions

3. **Code Consolidation (Hours 6-8)**:
   - Merge redundant scripts
   - Standardize error handling
   - Create single entry point for pipeline

4. **Production Hardening (Hours 9-10)**:
   - Add comprehensive retry logic
   - Implement circuit breakers
   - Add performance monitoring

## Implementation Plan

### Phase 1: Critical Bug Fixes (Immediate)

1. **Fix OCR File Handling**:
   ```python
   # In pdf_tasks.py - extract_text_from_document()
   # Add S3 download logic if file_path is S3 key
   # Ensure proper local temp file management
   ```

2. **Fix Pipeline Continuation**:
   ```python
   # In pdf_tasks.py - resolve_document_entities()
   # Ensure build_document_relationships is triggered
   # Add explicit task chaining
   ```

3. **Fix Canonical Entity Persistence**:
   ```python
   # In entity_service.py
   # Debug why canonical entities aren't retrievable
   # Fix any transaction/commit issues
   ```

### Phase 2: Minimal Model Migration

1. **Database Schema Simplification**:
   - Remove unused columns from all tables
   - Keep only fields used by minimal models
   - Create migration script for production

2. **Model Consolidation**:
   - Move all minimal models to `core/models.py`
   - Delete complex model definitions
   - Update all imports throughout codebase

3. **Script Updates**:
   - Update all scripts to use consolidated models
   - Remove conformance checking code
   - Simplify validation to essential fields only

### Phase 3: Code Consolidation

1. **Core Pipeline Module** (`pipeline/core.py`):
   - Single entry point for document processing
   - Unified error handling
   - Consistent logging patterns

2. **Service Consolidation**:
   - Merge entity_service.py functionality into pdf_tasks.py
   - Consolidate cache operations
   - Unify database operations

3. **Script Cleanup**:
   - Archive legacy scripts to `archive/` directory
   - Keep only essential operational scripts
   - Update imports and dependencies

### Phase 4: Production Hardening

1. **Reliability Features**:
   - Exponential backoff on all external calls
   - Circuit breakers for OpenAI/Textract
   - Automatic recovery from transient failures

2. **Performance Optimization**:
   - Batch entity extraction requests
   - Parallel chunk processing where possible
   - Connection pooling optimization

3. **Monitoring Enhancement**:
   - Add metrics for each pipeline stage
   - Create alerts for failure patterns
   - Build dashboard for operational visibility

## Success Criteria

### Quantitative Metrics
- **99% Success Rate**: Documents complete all 6 stages
- **<5 min Processing Time**: Per document average
- **Zero Data Loss**: All extracted entities persisted
- **<1% Error Rate**: Per pipeline stage

### Qualitative Goals
- **Single Model Definition**: No more minimal vs full confusion
- **Clear Code Structure**: Obvious flow from entry to completion
- **Robust Error Recovery**: Self-healing from common failures
- **Production Confidence**: Ready for high-volume processing

## Testing Strategy

1. **Fix Verification**:
   - Test single document after each fix
   - Verify all 6 stages complete

2. **Multi-Document Testing**:
   - Process 10 documents sequentially
   - Process 5 documents in parallel
   - Verify 99% completion rate

3. **Stress Testing**:
   - Submit 50 documents rapidly
   - Monitor resource usage
   - Identify bottlenecks

4. **Recovery Testing**:
   - Simulate failures at each stage
   - Verify automatic recovery
   - Test idempotency

## Risk Mitigation

1. **Data Safety**:
   - Backup database before schema changes
   - Test migrations on copy first
   - Keep rollback scripts ready

2. **Code Safety**:
   - Archive current working code
   - Make changes incrementally
   - Test each change thoroughly

3. **Production Impact**:
   - Work on development environment
   - Deploy changes gradually
   - Monitor closely after deployment

## Expected Outcomes

By the end of this session:
1. **100% of test documents process successfully**
2. **Codebase reduced by 50%+ through consolidation**
3. **Single, clear model hierarchy**
4. **Production-ready error handling**
5. **Clear path to scale**

## Ethical Commitment

This system will process critical legal documents that affect people's lives and freedoms. Our commitment to 99% reliability is not just a technical goal but an ethical imperative. Every failure could mean delayed justice or missed opportunities for those who need legal help most. We will build this system with the robustness and reliability that vulnerable populations deserve.

## Next Immediate Steps

1. Start with fixing the S3 file path issue in OCR
2. Test with single document to verify fix
3. Fix pipeline continuation issue
4. Test full pipeline completion
5. Begin minimal model migration

The path forward is clear: fix immediate issues, simplify radically, and harden for production. Let's begin.