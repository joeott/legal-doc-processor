# Context 537: Immediate Scripts Directory Cleanup Plan

**Date**: 2025-06-13 15:00 UTC  
**Branch**: fix/pipeline-langchain-optimizations  
**Purpose**: Execute immediate cleanup before implementing new features

## Executive Summary

Before implementing LangChain optimizations, we must clean up the scripts directory. Currently only 20-25 of 71 scripts (28-35%) are used in production. This cleanup will reduce complexity, prevent confusion, and provide a solid foundation for new features.

## Cleanup Categories & Actions

### 1. IMMEDIATE REMOVAL - Deprecated/Unused (17 scripts)
**Action**: Archive and delete
**Risk**: Very Low - These are confirmed unused

```bash
# Create backup archive
tar -czf deprecated_scripts_$(date +%Y%m%d_%H%M%S).tar.gz \
  scripts/batch_processor.py \
  scripts/core/ \
  scripts/utils/neo4j_utils.py \
  scripts/utils/supabase_utils.py \
  migrate_redis_databases.py \
  core_enhancements_immediate.py \
  clear_redis_cache.py \
  clear_rds_test_data.py \
  services/document_analysis_service.py \
  services/semantic_search_service.py \
  services/summarization_service.py

# Remove the files
git rm scripts/batch_processor.py
git rm -r scripts/core/
git rm scripts/utils/neo4j_utils.py
git rm scripts/utils/supabase_utils.py
git rm migrate_redis_databases.py
git rm core_enhancements_immediate.py
git rm clear_redis_cache.py
git rm clear_rds_test_data.py
```

### 2. MOVE TO SEPARATE REPOS - Non-Production Tools (19 scripts)
**Action**: Create new repositories
**Risk**: Low - These are auxiliary tools

#### legal-doc-cli Repository
```bash
# scripts/cli/ (4 files)
- enhanced_monitor.py
- import.py
- monitor.py
- __init__.py
```

#### legal-doc-monitoring Repository
```bash
# scripts/monitoring/ (4 files)
- monitor_workers.sh
- check_unprocessed_documents.py
- log_analyzer.py
- performance_metrics.py
```

#### legal-doc-utilities Repository
```bash
# scripts/utilities/ (11 files)
- analyze_chunks.py
- analyze_entities.py
- check_document_flow.py
- check_entity_resolution.py
- diagnose_chunking_issue.py
- fix_project_associations.py
- inspect_celery_tasks.py
- redis_performance_test.py
- test_cache_effectiveness.py
- test_ocr_job.py
- verify_s3_access.py
```

### 3. CONSOLIDATE - Validation Scripts (7 → 3 scripts)
**Action**: Merge related functionality
**Risk**: Medium - Requires careful testing

```python
# NEW: scripts/validation/unified_validator.py
"""Consolidated validation functionality"""

class UnifiedValidator:
    def __init__(self):
        self.ocr = OCRValidator()
        self.entity = EntityValidator()
        self.pipeline = PipelineValidator()
        
# Keep only:
- unified_validator.py
- conformance_validator.py (for data validation)
- quality_analyzer.py (for metrics)

# Remove:
- ocr_validator.py
- entity_validator.py
- pipeline_validator.py
- flexible_validator.py
```

### 4. ORGANIZE - Core Production Scripts (~30-35 remain)
**Action**: Ensure clear organization
**Structure**:

```
scripts/
├── __init__.py
├── # Core Pipeline (15 scripts)
│   ├── pdf_tasks.py              ✓ KEEP - Main pipeline
│   ├── celery_app.py            ✓ KEEP - Task queue
│   ├── batch_tasks.py           ✓ KEEP - Batch processing
│   ├── textract_utils.py        ✓ KEEP - OCR
│   ├── chunking_utils.py        ✓ KEEP - Chunking
│   ├── entity_service.py        ✓ KEEP - Entity extraction
│   ├── graph_service.py         ✓ KEEP - Relationships
│   └── ...
├── # Data Layer (4 scripts)
│   ├── db.py                    ✓ KEEP - Database
│   ├── cache.py                 ✓ KEEP - Redis
│   ├── models.py                ✓ KEEP - Data models
│   └── rds_utils.py            ✓ KEEP - RDS utilities
├── # Infrastructure (5 scripts)
│   ├── config.py                ✓ KEEP - Configuration
│   ├── logging_config.py        ✓ KEEP - Logging
│   └── ...
└── # Services (3 scripts)
    ├── intake_service.py        ✓ KEEP - Document intake
    ├── audit_logger.py          ✓ KEEP - Audit trails
    └── status_manager.py        ✓ KEEP - Status tracking
```

## Implementation Steps

### Step 1: Create Backup (5 minutes)
```bash
# Full backup of current state
tar -czf scripts_backup_full_$(date +%Y%m%d_%H%M%S).tar.gz scripts/

# Verify backup
tar -tzf scripts_backup_full_*.tar.gz | head -20
```

### Step 2: Update Dependencies (15 minutes)
```bash
# Find all imports of deprecated modules
grep -r "from scripts.batch_processor" scripts/
grep -r "from scripts.core" scripts/
grep -r "import batch_processor" scripts/
grep -r "neo4j_utils" scripts/
grep -r "supabase_utils" scripts/

# Update production_processor.py
# Change: from scripts.batch_processor import BatchProcessor
# To: from scripts.batch_tasks import submit_batch, get_batch_status
```

### Step 3: Execute Removal (10 minutes)
```bash
# Remove deprecated files
./cleanup_scripts/remove_deprecated.sh

# Verify removal
ls scripts/core/  # Should error - directory not found
ls scripts/batch_processor.py  # Should error - file not found
```

### Step 4: Create New Repositories (20 minutes)
```bash
# Create legal-doc-cli
gh repo create legal-doc-cli --private
git clone https://github.com/joeott/legal-doc-cli.git ../legal-doc-cli
cp -r scripts/cli/* ../legal-doc-cli/
cd ../legal-doc-cli && git add . && git commit -m "Initial CLI tools migration"

# Repeat for monitoring and utilities repos
```

### Step 5: Test Core Functionality (30 minutes)
```python
# Run essential tests
pytest tests/unit/test_pdf_tasks.py
pytest tests/unit/test_batch_tasks.py
pytest tests/integration/test_pipeline.py

# Test batch processing
python test_single_doc/test_document.py
```

## Verification Checklist

### Pre-Cleanup
- [ ] Full backup created and verified
- [ ] All import dependencies mapped
- [ ] Team notified of cleanup

### During Cleanup
- [ ] Deprecated files removed (17 files)
- [ ] Non-production tools moved (19 files)
- [ ] Validation consolidated (7→3 files)
- [ ] No broken imports
- [ ] All tests passing

### Post-Cleanup
- [ ] Script count reduced to ~35
- [ ] Clear directory structure
- [ ] Documentation updated
- [ ] CI/CD pipelines working
- [ ] Team can find everything

## Benefits After Cleanup

1. **Immediate Benefits**
   - 51% reduction in scripts (71→35)
   - Clear separation of concerns
   - Faster navigation and development
   - Reduced confusion about what's production

2. **Development Benefits**
   - Easier to implement LangChain features
   - Clear dependency graph
   - Better test coverage visibility
   - Faster CI/CD runs

3. **Operational Benefits**
   - Smaller Docker images
   - Clearer monitoring scope
   - Easier troubleshooting
   - Reduced maintenance burden

## Risk Mitigation

1. **Backup Everything**
   - Full scripts directory backup
   - Git commits for each removal
   - Keep archives for 30 days

2. **Test Continuously**
   - Run tests after each removal
   - Verify imports still work
   - Check production functionality

3. **Gradual Rollout**
   - Remove deprecated first (low risk)
   - Move tools second (medium risk)
   - Consolidate last (higher risk)

## Timeline

**Total Time: 3-4 hours**

1. Hour 1: Backup and dependency analysis
2. Hour 2: Remove deprecated, update imports
3. Hour 3: Move non-production tools
4. Hour 4: Test and verify

## Conclusion

This cleanup is essential before implementing new features. It will:
- Reduce scripts from 71 to ~35 (51% reduction)
- Eliminate confusion about production vs non-production code
- Provide clean foundation for LangChain implementation
- Make the codebase more maintainable

After cleanup, we can proceed with confidence to implement the pipeline fixes and LangChain optimizations on a clean, well-organized codebase.