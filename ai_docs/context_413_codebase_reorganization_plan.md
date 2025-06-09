# Context 413: Codebase Reorganization Plan

## Executive Summary

This plan proposes a systematic reorganization of the legal document processor codebase to clearly separate production runtime components from development, debugging, and testing utilities. The goal is to reduce cognitive load, improve maintainability, and create a clear boundary between what runs in production versus what supports development.

## Current State Analysis

### Existing Organization (Positive)
- ✅ `tests/` directory with proper subdirectories (unit, integration, e2e)
- ✅ `archived_codebase/` for legacy code
- ✅ `scripts/cli/` for command-line interfaces
- ✅ `scripts/core/` for core functionality
- ✅ `scripts/monitoring/` and `scripts/validation/` partially organized

### Issues Identified
1. **Mixed Purpose Scripts**: Development/debug scripts mixed with production code in `scripts/`
2. **Redundant Model Definitions**: Multiple Pydantic model files creating confusion
3. **Scattered Debug Utilities**: Various `check_*`, `test_*`, `verify_*` scripts in main directory
4. **Manual Intervention Scripts**: Retry and manual trigger scripts mixed with automated pipeline
5. **macOS Metadata Files**: ~480 `._*` files cluttering the codebase (now archived)

## Proposed Directory Structure

```
/opt/legal-doc-processor/
├── scripts/                    # PRODUCTION RUNTIME ONLY
│   ├── __init__.py
│   ├── core/                   # Core business logic
│   │   ├── __init__.py
│   │   ├── models.py          # Single source of truth for data models
│   │   ├── error_handler.py
│   │   ├── json_serializer.py
│   │   └── conformance_validator.py
│   ├── services/              # Business services
│   │   ├── __init__.py
│   │   ├── entity_service.py
│   │   ├── graph_service.py
│   │   ├── intake_service.py
│   │   └── project_association.py
│   ├── processors/            # Document processors
│   │   ├── __init__.py
│   │   ├── production_processor.py
│   │   ├── batch_processor.py
│   │   └── pdf_tasks.py
│   ├── storage/               # Storage interfaces
│   │   ├── __init__.py
│   │   ├── s3_storage.py
│   │   ├── db.py
│   │   ├── rds_utils.py
│   │   └── cache.py
│   ├── extractors/            # Text/entity extraction
│   │   ├── __init__.py
│   │   ├── ocr_extraction.py
│   │   ├── textract_utils.py
│   │   └── chunking_utils.py
│   ├── config/                # Configuration
│   │   ├── __init__.py
│   │   ├── config.py
│   │   ├── celery_app.py
│   │   └── logging_config.py
│   ├── operational/           # Runtime support
│   │   ├── __init__.py
│   │   ├── status_manager.py
│   │   ├── audit_logger.py
│   │   └── start_worker.py
│   └── enhancements/          # Feature enhancements
│       ├── __init__.py
│       ├── semantic_naming.py
│       ├── document_categorization.py
│       └── core_enhancements_immediate.py
│
├── dev_tools/                 # DEVELOPMENT & DEBUGGING
│   ├── __init__.py
│   ├── debug/                 # Debug utilities
│   │   ├── check_celery_task_status.py
│   │   ├── check_doc_status.py
│   │   ├── check_latest_tasks.py
│   │   ├── check_ocr_task_status.py
│   │   ├── check_task_details.py
│   │   └── monitor_document_complete.py
│   ├── database/              # Database utilities
│   │   ├── check_schema.py
│   │   ├── verify_current_model_issues.py
│   │   └── test_model_consistency.py
│   ├── manual_ops/            # Manual intervention scripts
│   │   ├── retry_entity_extraction.py
│   │   ├── retry_entity_resolution_with_cache.py
│   │   ├── run_entity_extraction_with_chunks.py
│   │   └── manual_poll_textract.py
│   ├── validation/            # Validation & verification
│   │   ├── validate_document_results.py
│   │   ├── verify_actual_documents.py
│   │   └── verify_production_readiness.py
│   ├── migration/             # Migration utilities
│   │   ├── migrate_to_standard_models.py
│   │   ├── api_compatibility.py
│   │   └── model_migration.py
│   └── testing/               # Test helpers
│       ├── test_textract_e2e.py
│       ├── test_phase3_stability.py
│       └── test_uuid_flow.py
│
├── tests/                     # AUTOMATED TESTS
│   ├── unit/
│   ├── integration/
│   ├── e2e/
│   └── verification/
│
├── cli/                       # COMMAND LINE INTERFACES
│   ├── __init__.py
│   ├── monitor.py            # Production monitoring
│   ├── admin.py              # Administrative operations
│   └── import.py             # Document import
│
└── docs/                      # DOCUMENTATION
    ├── README_PRODUCTION.md
    ├── architecture.md
    └── api_reference.md
```

## Pre-Reorganization Cleanup

### Remove macOS Metadata Files
```bash
# Archive all macOS hidden files
mkdir -p archived_codebase/macos_metadata
find . -name "._*" -type f | while read file; do 
    mv "$file" archived_codebase/macos_metadata/
done
```
✅ **Completed**: Archived 480 macOS metadata files

### Fix Broken Generated Files
- `scripts/core/schemas_generated.py` has syntax errors (line 15)
- Should either fix or archive if not used

## Reorganization Tasks

### Phase 1: Create Directory Structure
```bash
# Create new directories
mkdir -p dev_tools/{debug,database,manual_ops,validation,migration,testing}
mkdir -p scripts/{processors,storage,extractors,config,operational,enhancements}
mkdir -p cli
mkdir -p docs
```

### Phase 2: Move Development Scripts (24 files)
```bash
# Move debug scripts (7 files)
mv scripts/check_*.py dev_tools/debug/
mv scripts/monitor_document_complete.py dev_tools/debug/

# Move test scripts (4 files)  
mv scripts/test_*.py dev_tools/testing/

# Move validation scripts (4 files)
mv scripts/validate_document_results.py dev_tools/validation/
mv scripts/verify_*.py dev_tools/validation/

# Move manual operation scripts (4 files)
mv scripts/retry_*.py dev_tools/manual_ops/
mv scripts/run_entity_extraction_with_chunks.py dev_tools/manual_ops/
mv scripts/manual_poll_textract.py dev_tools/manual_ops/

# Move migration/compatibility scripts (5 files)
mv scripts/api_compatibility.py dev_tools/migration/
mv scripts/migrate_to_standard_models.py dev_tools/migration/
mv scripts/core/schemas.py dev_tools/migration/deprecated_models/
mv scripts/core/pdf_models.py dev_tools/migration/deprecated_models/
mv scripts/core/schemas_generated.py dev_tools/migration/deprecated_models/
```

### Phase 3: Reorganize Production Scripts
```bash
# Move processors
mv scripts/production_processor.py scripts/processors/
mv scripts/batch_processor.py scripts/processors/
mv scripts/pdf_tasks.py scripts/processors/

# Move storage
mv scripts/s3_storage.py scripts/storage/
mv scripts/db.py scripts/storage/
mv scripts/rds_utils.py scripts/storage/
mv scripts/cache.py scripts/storage/

# Move extractors
mv scripts/ocr_extraction.py scripts/extractors/
mv scripts/textract_utils.py scripts/extractors/
mv scripts/chunking_utils.py scripts/extractors/

# Move config
mv scripts/config.py scripts/config/
mv scripts/celery_app.py scripts/config/
mv scripts/logging_config.py scripts/config/

# Move operational
mv scripts/status_manager.py scripts/operational/
mv scripts/audit_logger.py scripts/operational/
mv scripts/start_worker.py scripts/operational/

# Move enhancements
mv scripts/semantic_naming.py scripts/enhancements/
mv scripts/document_categorization.py scripts/enhancements/
mv scripts/core_enhancements_immediate.py scripts/enhancements/
```

### Phase 4: Consolidate Models
1. Keep only `scripts/core/models.py` as the single source of truth
2. Archive other model files:
   - `core/schemas.py` → `archived_codebase/models/`
   - `core/pdf_models.py` → `archived_codebase/models/`
   - `core/models_minimal.py` → `archived_codebase/models/`
3. Update all imports to use `scripts.core.models`

### Phase 5: Move CLI Scripts
```bash
mv scripts/cli/* cli/
rmdir scripts/cli
```

## Verification Criteria

### 1. Import Verification
```python
#!/usr/bin/env python3
"""Verify all imports still work after reorganization"""
import ast
import os
from pathlib import Path

def check_imports(directory):
    errors = []
    for path in Path(directory).rglob("*.py"):
        with open(path, 'r') as f:
            try:
                tree = ast.parse(f.read())
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            # Check if import is valid
                            pass
                    elif isinstance(node, ast.ImportFrom):
                        # Check if from import is valid
                        pass
            except Exception as e:
                errors.append(f"{path}: {e}")
    return errors
```

### 2. Pipeline Functionality Test
```bash
# Test core pipeline still works
python3 -c "
from scripts.processors.pdf_tasks import extract_text_from_document
from scripts.services.entity_service import EntityService
from scripts.storage.db import DatabaseManager
print('✅ Core imports working')
"
```

### 3. Celery Worker Test
```bash
# Ensure Celery can still find tasks
celery -A scripts.config.celery_app inspect registered
```

### 4. End-to-End Processing Test
```bash
# Run a test document through the pipeline
python3 scripts/processors/production_processor.py --test
```

### 5. No Production Code in Dev Tools
```bash
# Verify no production code imports from dev_tools
grep -r "from dev_tools" scripts/ --include="*.py" | wc -l
# Should return 0
```

## Rollback Plan

1. Create backup before starting:
```bash
tar -czf scripts_backup_$(date +%Y%m%d_%H%M%S).tar.gz scripts/
```

2. If issues arise:
```bash
rm -rf scripts/
tar -xzf scripts_backup_*.tar.gz
```

## Benefits

1. **Clear Separation**: Production code is isolated from development utilities
2. **Easier Navigation**: Logical grouping of related functionality
3. **Reduced Confusion**: Single source of truth for models
4. **Better Onboarding**: New developers can understand structure quickly
5. **Cleaner Deployments**: Easy to exclude dev_tools from production builds

## Migration Script

```bash
#!/bin/bash
# reorganize_codebase.sh

set -e  # Exit on error

echo "Starting codebase reorganization..."

# Create backup
BACKUP_FILE="scripts_backup_$(date +%Y%m%d_%H%M%S).tar.gz"
tar -czf $BACKUP_FILE scripts/
echo "✅ Backup created: $BACKUP_FILE"

# Create directory structure
echo "Creating new directory structure..."
mkdir -p dev_tools/{debug,database,manual_ops,validation,migration,testing}
mkdir -p scripts/{processors,storage,extractors,config,operational,enhancements}

# Move files (with error checking)
echo "Moving development scripts..."
# ... (implement moves with error checking)

# Update imports
echo "Updating imports..."
python3 update_imports.py

# Run verification
echo "Running verification tests..."
python3 verify_reorganization.py

echo "✅ Reorganization complete!"
```

## Implementation Timeline

1. **Day 1**: Create directory structure and migration scripts
2. **Day 2**: Move development/debug scripts to dev_tools
3. **Day 3**: Reorganize production scripts into logical directories
4. **Day 4**: Consolidate models and update imports
5. **Day 5**: Run comprehensive testing and fix any issues

## Success Metrics

- ✅ All automated tests pass
- ✅ Celery workers start without import errors
- ✅ End-to-end document processing succeeds
- ✅ No circular imports
- ✅ Production code has zero dependencies on dev_tools
- ✅ Reduced cognitive load (subjective but important)

## Notes

1. The `api_compatibility.py` file should remain in `dev_tools/migration/` temporarily but should be actively deprecated
2. Consider creating a `scripts/__main__.py` to make the scripts directory executable
3. Update deployment scripts to exclude `dev_tools/` from production builds
4. Update `.gitignore` to exclude any generated files in new structure
5. Consider adding `__all__` exports to `__init__.py` files for cleaner imports

## Current State Summary

Based on analysis:
- **76 total Python scripts** in scripts directory
- **40 production scripts** (53%) - essential for runtime
- **24 development scripts** (32%) - debug/test/validation tools
- **12 interface scripts** (16%) - CLI and monitoring tools

### Key Findings:
1. **Good separation already exists** in subdirectories (cli/, monitoring/, validation/)
2. **Main issue** is development scripts mixed with production scripts at root level
3. **Core functionality** is well-identified and isolated
4. **macOS metadata files** (480 files) have been successfully archived

## Implementation Priority

1. **Immediate**: Move the 24 development scripts to `dev_tools/`
2. **Short-term**: Reorganize root-level production scripts into logical subdirectories
3. **Medium-term**: Consolidate model definitions into single source of truth
4. **Long-term**: Deprecate api_compatibility.py and complete model migration

## Expected Impact

- **50% reduction** in root-level script clutter
- **Clear separation** between production and development code
- **Easier onboarding** for new developers
- **Simpler deployment** (can exclude entire dev_tools/ directory)
- **Better maintainability** through logical organization

## Conclusion

This reorganization will create a cleaner, more maintainable codebase with clear boundaries between production and development code. The systematic approach with verification criteria ensures we don't break functionality while improving organization. The plan is conservative, focusing on moving obvious development tools while preserving all production functionality.