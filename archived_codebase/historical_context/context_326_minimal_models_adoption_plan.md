# Context 326: Minimal Models Adoption and Codebase Cleanup Plan

## Executive Summary

This plan outlines the migration to minimal models as the single source of truth, cleaning the codebase of legacy scripts, and consolidating tests. The goal is a clean, operable codebase that uses Celery microservices for PDF pipeline processing.

## Current State Analysis

### Working Components (Keep & Standardize)
1. **Core Pipeline Tasks** (`scripts/pdf_tasks.py`)
2. **Standalone Resolution Task** (`scripts/resolution_task.py`) 
3. **Minimal Models** (`scripts/core/models_minimal.py`)
4. **Database Layer** (`scripts/db.py` with minimal model support)
5. **Cache Layer** (`scripts/cache.py`)
6. **Supporting Utilities**:
   - `scripts/ocr_extraction.py`
   - `scripts/chunking_utils.py`
   - `scripts/entity_service.py` (needs adaptation)
   - `scripts/graph_service.py`
   - `scripts/textract_job_manager.py`

### Models Hierarchy (Current)

```
scripts/core/
├── models_minimal.py        # ✅ KEEP - Working minimal models
├── schemas.py              # ❌ REMOVE - Complex, unused
├── schemas_generated.py    # ❌ REMOVE - Auto-generated, unused
├── processing_models.py    # ⚠️  ADAPT - Some utilities needed
├── pdf_models.py          # ⚠️  ADAPT - Some enums needed
├── task_models.py         # ❌ REMOVE - Unused
├── conformance_*.py       # ❌ REMOVE - Over-engineered
└── cache_models.py        # ❌ REMOVE - Unused
```

## Phase 1: Model Consolidation (Week 1)

### 1.1 Create Single Source of Truth
**File**: `scripts/models.py` (new consolidated file)

```python
"""
Minimal models for legal document processing pipeline.
These models are the single source of truth derived from working code.
"""

# From models_minimal.py - KEEP ALL
- SourceDocumentMinimal
- DocumentChunkMinimal  
- EntityMentionMinimal
- CanonicalEntityMinimal
- RelationshipStagingMinimal

# From pdf_models.py - EXTRACT ONLY:
- ProcessingStatus (enum)
- EntityType (enum)

# From processing_models.py - EXTRACT ONLY:
- ProcessingResultStatus (enum)
- ProcessingResult (dataclass)

# Add new consolidated model factory
class ModelFactory:
    """Single factory for all model access"""
    @staticmethod
    def get_document_model():
        return SourceDocumentMinimal
    # ... etc for all models
```

### 1.2 Update Import Strategy
Replace all imports across the codebase:
```python
# OLD
from scripts.core.models_minimal import SourceDocumentMinimal
from scripts.core.pdf_models import ProcessingStatus

# NEW
from scripts.models import SourceDocumentMinimal, ProcessingStatus
```

## Phase 2: Script Adaptation (Week 1-2)

### 2.1 Core Scripts to Adapt

| Script | Current Model Usage | Required Changes |
|--------|-------------------|------------------|
| `entity_service.py` | Mixed models | Use EntityMentionMinimal exclusively |
| `graph_service.py` | Complex models | Use RelationshipStagingMinimal |
| `db.py` | Conformance checks | Remove conformance, use minimal models only |
| `cli/*.py` | Various | Standardize on minimal models |

### 2.2 Adaptation Pattern
```python
# Before (entity_service.py)
if hasattr(mention, 'text'):
    text = mention.text
elif hasattr(mention, 'entity_text'):
    text = mention.entity_text

# After
# EntityMentionMinimal always has entity_text
text = mention.entity_text
```

## Phase 3: Codebase Cleanup (Week 2)

### 3.1 Scripts to Remove

**Archive Folder** (`scripts/archive_pre_consolidation/`)
- Move all legacy scripts here first (for 30-day retention)

**Legacy Scripts** (150+ files to remove):
```
scripts/legacy/               # Entire folder
scripts/core/conformance_*.py
scripts/core/schemas*.py
scripts/core/model_migration.py
scripts/database/conformance_*.py
scripts/database/migrate_*.py
scripts/recovery/            # Old recovery scripts
```

**Redundant Scripts**:
- Multiple monitoring scripts → Keep only `scripts/cli/monitor.py`
- Multiple test scripts → Consolidate to `tests/` folder
- Multiple import scripts → Keep only `scripts/cli/import.py`

### 3.2 Scripts to Consolidate

**Monitoring** → `scripts/cli/monitor.py`:
- Merge functionality from all monitor_*.py scripts
- Single entry point for all monitoring needs

**Testing Utilities** → `scripts/cli/test.py`:
- Merge all test_*.py utilities
- Provide subcommands for different test scenarios

## Phase 4: Test Consolidation (Week 2)

### 4.1 New Test Structure
```
tests/
├── unit/
│   ├── test_models.py         # Test minimal models
│   ├── test_cache.py          # Test caching
│   └── test_utils.py          # Test utilities
├── integration/
│   ├── test_ocr.py           # Test OCR stage
│   ├── test_chunking.py      # Test chunking stage
│   ├── test_entities.py      # Test entity stages
│   └── test_relationships.py  # Test relationship building
├── e2e/
│   ├── test_pipeline.py      # Full pipeline tests
│   └── test_performance.py   # Performance benchmarks
└── fixtures/
    └── sample_docs/          # Test documents
```

### 4.2 Tests to Migrate
- Keep tests that validate current working functionality
- Remove tests for deprecated features
- Consolidate duplicate tests

## Phase 5: Database Schema Alignment (Week 3)

### 5.1 Column Standardization
Create migration to standardize column names:
```sql
-- Standardize UUID columns
ALTER TABLE relationship_staging 
  RENAME COLUMN source_entity_uuid TO source_uuid;
ALTER TABLE relationship_staging 
  RENAME COLUMN target_entity_uuid TO target_uuid;

-- Add missing columns where needed
ALTER TABLE relationship_staging 
  ADD COLUMN IF NOT EXISTS document_uuid UUID;
```

### 5.2 Update Models to Match
Ensure minimal models exactly match standardized schema.

## Phase 6: Documentation & Deployment (Week 3)

### 6.1 Update Documentation
- `CLAUDE.md` - Update with new structure
- `README.md` - Simplify, focus on pipeline usage
- `docs/pipeline_architecture.md` - Document microservices

### 6.2 Environment Cleanup
- Remove unused environment variables
- Consolidate configuration to `scripts/config.py`
- Single `.env.example` with only required vars

## Implementation Approach

### Step 1: Create Migration Branch
```bash
git checkout -b feat/minimal-models-adoption
```

### Step 2: Implement Model Consolidation
1. Create `scripts/models.py` with all minimal models
2. Update imports in working scripts (pdf_tasks.py, resolution_task.py)
3. Test pipeline still works

### Step 3: Progressive Script Updates
1. Update one script at a time
2. Test after each update
3. Commit working changes frequently

### Step 4: Archive Legacy Code
```bash
mkdir -p scripts/archive_pre_consolidation
git mv scripts/legacy scripts/archive_pre_consolidation/
# Move other deprecated files
```

### Step 5: Test Migration
```bash
mkdir -p tests/unit tests/integration tests/e2e
# Move and consolidate tests
python -m pytest tests/
```

## Success Criteria

1. **All pipeline stages work with minimal models**
2. **99% success rate maintained**
3. **Codebase reduced by 60%+**
4. **Single source of truth for models**
5. **All tests pass in new structure**
6. **No conformance validation errors**

## Risk Mitigation

1. **Backup Strategy**: Archive all removed code for 30 days
2. **Incremental Changes**: Test after each change
3. **Rollback Plan**: Git branches for each phase
4. **Validation**: E2E tests after each phase

## Quick Wins (Do First)

1. **Fix relationship building** ✅ (Already done)
2. **Create scripts/models.py** with minimal models
3. **Update pdf_tasks.py imports**
4. **Remove conformance checks from db.py**
5. **Archive scripts/legacy folder**

## Long-term Benefits

1. **Maintainability**: Single model definition
2. **Performance**: No conformance overhead
3. **Clarity**: Clear microservice boundaries
4. **Extensibility**: Easy to add new stages
5. **Reliability**: Proven working models only

## Next Steps

1. Review and approve this plan
2. Create implementation checklist
3. Begin with Phase 1 (Model Consolidation)
4. Daily progress updates in ai_docs

This plan prioritizes keeping what works while removing complexity. The minimal models have proven themselves in production and should be the foundation moving forward.