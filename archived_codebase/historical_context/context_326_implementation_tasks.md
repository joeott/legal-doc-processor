# Context 326: Implementation Tasks - Minimal Models Migration

## Overview
This document provides detailed, actionable tasks for implementing the minimal models adoption plan. Each task includes specific files, commands, and validation steps.

## Phase 1: Model Consolidation (Priority: HIGH)

### Task 1.1: Complete scripts/models.py
**Status**: ✅ COMPLETED
- [x] Create initial models.py file
- [x] Fix pydantic Config issue in DocumentChunkMinimal
- [x] Test all models work correctly
- [x] Add docstrings with database column mappings

**Commands**:
```bash
python3 test_models_migration.py
```

### Task 1.2: Update Core Pipeline Imports
**Status**: ✅ COMPLETED
- [x] Update pdf_tasks.py imports (partial)
- [x] Complete pdf_tasks.py import updates
- [x] Update resolution_task.py imports (no changes needed)
- [x] Update celery_app.py imports (no model imports)

### Task 1.5: Fix Relationship Building (CRITICAL FIX)
**Status**: ✅ COMPLETED
- [x] Fix document metadata to include document_uuid
- [x] Update graph_service.py to accept both documentId and document_uuid
- [x] Fix ProcessingResultStatus enum values (FAILED -> FAILURE)
- [x] Test relationship building stage
- [x] Verify pipeline progression

**Pipeline Success Rate**: Improved from 66.7% to 83.3%!

**Files to modify**:
- `scripts/pdf_tasks.py` - Replace all model imports
- `scripts/resolution_task.py` - Replace all model imports
- `scripts/celery_app.py` - No model imports needed

**Search/Replace patterns**:
```python
# Find: from scripts.core.models_minimal import
# Replace: from scripts.models import

# Find: from scripts.core.model_factory import
# Replace: from scripts.models import ModelFactory

# Find: from scripts.core.pdf_models import
# Replace: from scripts.models import

# Find: from scripts.core.processing_models import
# Replace: from scripts.models import
```

### Task 1.3: Update Supporting Scripts
**Status**: ❌ TODO
- [ ] Update entity_service.py
- [ ] Update graph_service.py
- [ ] Update chunking_utils.py
- [ ] Update ocr_extraction.py

**Key changes for entity_service.py**:
```python
# Remove all references to .text attribute
# Use .entity_text consistently
# Remove complex model conversions
```

### Task 1.4: Remove Conformance from Database Layer
**Status**: ❌ TODO
- [ ] Update db.py to remove conformance validation
- [ ] Remove ConformanceValidator class
- [ ] Update DatabaseManager.__init__ to remove validate_conformance parameter
- [ ] Test database operations still work

**File**: `scripts/db.py`
```python
# Remove:
- validate_conformance parameter
- _validate_conformance method
- ConformanceValidator class
- All conformance-related imports
```

## Phase 2: Script Adaptation

### Task 2.1: Fix Entity Service
**Status**: ❌ TODO
- [ ] Replace all hasattr checks for text/entity_text
- [ ] Use EntityMentionMinimal exclusively
- [ ] Remove EntityMention (non-minimal) imports
- [ ] Test entity extraction still works

**File**: `scripts/entity_service.py`
**Critical sections to fix**:
```python
# Line ~150-160: Fix text attribute access
# Line ~200-210: Fix model creation
# Line ~300-310: Fix entity mention handling
```

### Task 2.2: Fix Graph Service
**Status**: ❌ TODO
- [ ] Use RelationshipStagingMinimal exclusively
- [ ] Update column names (source_uuid, target_uuid)
- [ ] Remove complex relationship models
- [ ] Test relationship building

**File**: `scripts/graph_service.py`

### Task 2.3: Update Cache Keys
**Status**: ❌ TODO
- [ ] Ensure cache.py uses minimal model serialization
- [ ] Update any model-specific cache keys
- [ ] Test cache operations

**File**: `scripts/cache.py`

### Task 2.4: Update Config
**Status**: ❌ TODO
- [ ] Remove conformance-related config
- [ ] Remove USE_MINIMAL_MODELS flag (always true now)
- [ ] Clean up model-related imports

**File**: `scripts/config.py`

## Phase 3: Codebase Cleanup

### Task 3.1: Create Archive Directory
**Status**: ❌ TODO
```bash
mkdir -p scripts/archive_pre_consolidation
mkdir -p scripts/archive_pre_consolidation/core
mkdir -p scripts/archive_pre_consolidation/database
mkdir -p scripts/archive_pre_consolidation/legacy
```

### Task 3.2: Archive Legacy Scripts
**Status**: ❌ TODO
- [ ] Move scripts/legacy/* to archive
- [ ] Move scripts/core/schemas*.py to archive
- [ ] Move scripts/core/conformance*.py to archive
- [ ] Move scripts/core/model_migration.py to archive
- [ ] Move scripts/core/task_models.py to archive
- [ ] Move scripts/core/cache_models.py to archive

**Commands**:
```bash
git mv scripts/legacy scripts/archive_pre_consolidation/
git mv scripts/core/schemas*.py scripts/archive_pre_consolidation/core/
git mv scripts/core/conformance*.py scripts/archive_pre_consolidation/core/
git mv scripts/core/model_migration.py scripts/archive_pre_consolidation/core/
git mv scripts/core/task_models.py scripts/archive_pre_consolidation/core/
git mv scripts/core/cache_models.py scripts/archive_pre_consolidation/core/
```

### Task 3.3: Archive Database Scripts
**Status**: ❌ TODO
- [ ] Move database/conformance*.py to archive
- [ ] Move database/migrate*.py to archive (except apply_migration_210.py)
- [ ] Move recovery/* to archive

**Commands**:
```bash
git mv scripts/database/conformance*.py scripts/archive_pre_consolidation/database/
git mv scripts/database/migrate_to_conformance.py scripts/archive_pre_consolidation/database/
git mv scripts/recovery scripts/archive_pre_consolidation/
```

### Task 3.4: Clean Up Test Scripts
**Status**: ❌ TODO
- [ ] Identify working test scripts
- [ ] Move redundant test_*.py to archive
- [ ] Keep only essential test utilities

**Essential test scripts to keep**:
- test_e2e_pipeline_comprehensive.py
- test_schema_conformance.py (update for minimal models)
- test_async_ocr.py

### Task 3.5: Remove models_minimal.py
**Status**: ❌ TODO
- [ ] Verify all imports updated to use scripts.models
- [ ] Archive core/models_minimal.py
- [ ] Test pipeline still works

## Phase 4: Test Consolidation

### Task 4.1: Create Test Directory Structure
**Status**: ❌ TODO
```bash
mkdir -p tests/unit
mkdir -p tests/integration  
mkdir -p tests/e2e
mkdir -p tests/fixtures/sample_docs
```

### Task 4.2: Migrate Unit Tests
**Status**: ❌ TODO
- [ ] Create tests/unit/test_models.py
- [ ] Create tests/unit/test_cache.py
- [ ] Create tests/unit/test_utils.py
- [ ] Move existing unit tests

**Template for test_models.py**:
```python
import pytest
from scripts.models import ModelFactory, SourceDocumentMinimal

def test_document_creation():
    doc = ModelFactory.create_document(...)
    assert isinstance(doc, SourceDocumentMinimal)
```

### Task 4.3: Migrate Integration Tests
**Status**: ❌ TODO
- [ ] Create tests/integration/test_ocr.py
- [ ] Create tests/integration/test_chunking.py
- [ ] Create tests/integration/test_entities.py
- [ ] Create tests/integration/test_relationships.py

### Task 4.4: Migrate E2E Tests
**Status**: ❌ TODO
- [ ] Move test_e2e_pipeline_comprehensive.py to tests/e2e/
- [ ] Create tests/e2e/test_performance.py
- [ ] Add sample documents to fixtures/

### Task 4.5: Create Test Runner
**Status**: ❌ TODO
- [ ] Create pytest.ini configuration
- [ ] Create scripts/cli/test.py for running tests
- [ ] Document test commands in README

## Phase 5: Database Schema Alignment

### Task 5.1: Create Schema Migration Script
**Status**: ❌ TODO
- [ ] Create scripts/database/standardize_columns.sql
- [ ] Add column standardization for relationship_staging
- [ ] Add missing document_uuid where needed
- [ ] Create rollback script

**File**: `scripts/database/standardize_columns.sql`
```sql
-- Standardize relationship_staging columns
ALTER TABLE relationship_staging 
  RENAME COLUMN source_entity_uuid TO source_uuid;
  
ALTER TABLE relationship_staging 
  RENAME COLUMN target_entity_uuid TO target_uuid;

ALTER TABLE relationship_staging 
  ADD COLUMN IF NOT EXISTS document_uuid UUID;

-- Add indexes
CREATE INDEX IF NOT EXISTS idx_relationship_staging_document 
  ON relationship_staging(document_uuid);
```

### Task 5.2: Update Models to Match
**Status**: ❌ TODO
- [ ] Verify RelationshipStagingMinimal matches new schema
- [ ] Update any SQL queries using old column names
- [ ] Test relationship operations

### Task 5.3: Run Migration
**Status**: ❌ TODO
- [ ] Backup database
- [ ] Run standardize_columns.sql
- [ ] Verify schema changes
- [ ] Test pipeline with new schema

## Phase 6: Documentation & Deployment

### Task 6.1: Update CLAUDE.md
**Status**: ❌ TODO
- [ ] Update model references
- [ ] Update import examples
- [ ] Remove conformance references
- [ ] Add minimal models documentation

### Task 6.2: Create Migration Guide
**Status**: ❌ TODO
- [ ] Create docs/minimal_models_migration.md
- [ ] Document model mappings
- [ ] Document breaking changes
- [ ] Add troubleshooting section

### Task 6.3: Update Environment
**Status**: ❌ TODO
- [ ] Remove SKIP_CONFORMANCE_CHECK from .env
- [ ] Remove USE_MINIMAL_MODELS from .env
- [ ] Update .env.example
- [ ] Document required variables only

### Task 6.4: Final Cleanup
**Status**: ❌ TODO
- [ ] Remove empty directories
- [ ] Update .gitignore
- [ ] Run final test suite
- [ ] Create migration completion checklist

## Validation Checkpoints

### After Phase 1:
```bash
# Test models work
python3 test_models_migration.py

# Test imports work
python3 -c "from scripts.models import ModelFactory; print('✅ Imports work')"

# Test pipeline starts
python3 -c "from scripts.pdf_tasks import process_pdf_document; print('✅ Pipeline imports work')"
```

### After Phase 2:
```bash
# Test entity extraction
python3 scripts/tests/test_entity_extraction.py

# Test full pipeline
python3 test_e2e_existing_doc.py
```

### After Phase 3:
```bash
# Verify no broken imports
find scripts -name "*.py" -exec python3 -m py_compile {} \;

# Check for orphaned imports
grep -r "from scripts.core" scripts/ || echo "✅ No core imports found"
grep -r "from scripts.legacy" scripts/ || echo "✅ No legacy imports found"
```

### After Phase 4:
```bash
# Run all tests
python -m pytest tests/

# Check test coverage
python -m pytest --cov=scripts tests/
```

### After Phase 5:
```bash
# Verify schema
psql -c "\d relationship_staging"

# Test relationship creation
python3 scripts/tests/test_relationships.py
```

### After Phase 6:
```bash
# Full pipeline test
source load_env.sh
python3 test_e2e_pipeline_comprehensive.py

# Verify 99% success rate
```

## Implementation Order (Recommended)

1. **Day 1**: Complete Phase 1 (Model Consolidation)
   - Fix models.py
   - Update all imports
   - Test basic functionality

2. **Day 2**: Complete Phase 2 (Script Adaptation)
   - Fix entity_service.py
   - Fix graph_service.py
   - Remove conformance

3. **Day 3**: Complete Phase 3 (Codebase Cleanup)
   - Archive legacy code
   - Remove unused files
   - Clean imports

4. **Day 4**: Complete Phase 4 (Test Consolidation)
   - Migrate tests
   - Create test structure
   - Run full test suite

5. **Day 5**: Complete Phase 5 & 6
   - Database migration
   - Documentation
   - Final validation

## Success Metrics

- [ ] All pipeline stages work with minimal models
- [ ] 99% success rate maintained
- [ ] Zero conformance validation errors
- [ ] All tests pass
- [ ] Codebase reduced by 60%+
- [ ] Single source of truth (scripts/models.py)

## Quick Command Reference

```bash
# Test models
python3 test_models_migration.py

# Test pipeline
python3 test_e2e_existing_doc.py

# Find broken imports
find scripts -name "*.py" -exec python3 -m py_compile {} \;

# Run tests
python -m pytest tests/

# Check for old imports
grep -r "models_minimal\|schemas\|conformance" scripts/
```

## Notes for Implementation

1. **Test after each task** - Don't batch changes
2. **Commit working code** - Use descriptive commit messages
3. **Keep backups** - Archive before deleting
4. **Document issues** - Update this file with blockers
5. **Validate continuously** - Run pipeline tests frequently

This task list is designed to be followed sequentially. Each task builds on the previous one. Mark tasks as complete as you progress.