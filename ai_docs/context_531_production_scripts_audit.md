# Context 531: Production Scripts Audit and Codebase Analysis

**Date**: 2025-06-13 12:00 UTC  
**Branch**: master  
**Purpose**: Analyze which scripts are used in production vs total scripts to maintain clean codebase

## Executive Summary

The legal document processing codebase contains **71 Python scripts**, but only **~28-35%** are actively used in production processing. This analysis identifies opportunities to reduce the codebase by **50-60%** through proper organization and removal of non-production scripts.

## Production Batch Run Analysis

### Scripts Loaded During Batch Processing

From the test batch run log (`campaign_a6723f19_20250613_021920`), these modules were explicitly loaded:

```
scripts.config
scripts.intake_service  
scripts.validation.ocr_validator
scripts.validation.entity_validator
scripts.validation.pipeline_validator
scripts.status_manager
scripts.audit_logger
scripts.cache
scripts.db
scripts.batch_tasks
scripts.production_processor
scripts.logging_config
```

### Additional Production Dependencies

Through import chain analysis, these are also used in production:

1. **From production_processor.py imports**:
   - `batch_processor.py` (being deprecated)
   - `models.py` (database models)
   - `sqlalchemy` (via db.py)

2. **From batch_tasks.py imports**:
   - `pdf_tasks.py` (core pipeline tasks)
   - `cache_warmer.py`
   - `celery_app.py`

3. **From pdf_tasks.py imports** (indirect):
   - `textract_utils.py`
   - `chunking_utils.py`
   - `entity_service.py`
   - `graph_service.py`
   - `s3_storage.py`
   - `ocr_extraction.py`

**Total Production Scripts**: ~20-25 core scripts

## Complete Script Inventory by Category

### 1. Core Processing Pipeline (17 scripts)
**Status**: ESSENTIAL for production
```
pdf_tasks.py              # Main pipeline orchestration
celery_app.py            # Task queue configuration
batch_tasks.py           # Batch processing tasks
batch_processor.py       # DEPRECATED - remove after migration
batch_metrics.py         # Batch performance tracking
batch_recovery.py        # Error recovery
cache_warmer.py          # Pre-processing optimization
textract_utils.py        # AWS OCR integration
chunking_utils.py        # Text chunking
entity_service.py        # Entity extraction
graph_service.py         # Relationship building
ocr_extraction.py        # PDF text extraction
production_processor.py  # Production orchestration
s3_storage.py           # S3 operations
pipeline_stages.py      # Stage definitions
task_utils.py           # Task helpers
validation.py           # Validation orchestrator
```

### 2. Data Layer (4 scripts)
**Status**: ESSENTIAL for production
```
db.py                    # Database operations
cache.py                # Redis caching
models.py               # Pydantic models
rds_utils.py           # RDS-specific utilities
```

### 3. Infrastructure (7 scripts)
**Status**: ESSENTIAL for production
```
config.py               # Environment configuration
logging_config.py       # Logging setup
cloud_config.py        # Cloud service config
local_paths.py         # Path management
cloudwatch_logger.py   # CloudWatch integration
setup_cloudwatch_alarms.py  # ONE-TIME setup
elasticsearch_indexer.py    # Search indexing
```

### 4. Business Services (6 scripts)
**Status**: MIXED - some essential, some unused
```
intake_service.py       # ESSENTIAL - Document intake
audit_logger.py        # ESSENTIAL - Audit trails
status_manager.py      # ESSENTIAL - Status tracking
document_analysis_service.py  # UNUSED?
semantic_search_service.py    # UNUSED?
summarization_service.py      # UNUSED?
```

### 5. CLI Tools (4 scripts)
**Status**: NOT needed in production container
```
cli/
├── enhanced_monitor.py
├── import.py
├── monitor.py
└── __init__.py
```

### 6. Monitoring (4 scripts)
**Status**: NOT needed in production container
```
monitoring/
├── monitor_workers.sh
├── check_unprocessed_documents.py
├── log_analyzer.py
└── performance_metrics.py
```

### 7. Utilities (11 scripts)
**Status**: DIAGNOSTIC - not needed in production
```
utilities/
├── analyze_chunks.py
├── analyze_entities.py
├── check_document_flow.py
├── check_entity_resolution.py
├── diagnose_chunking_issue.py
├── fix_project_associations.py
├── inspect_celery_tasks.py
├── redis_performance_test.py
├── test_cache_effectiveness.py
├── test_ocr_job.py
└── verify_s3_access.py
```

### 8. Validation (7 scripts)
**Status**: USED but could be consolidated
```
validation/
├── __init__.py
├── conformance_validator.py
├── entity_validator.py
├── flexible_validator.py
├── ocr_validator.py
├── pipeline_validator.py
└── quality_analyzer.py
```

### 9. Utils (7 scripts)
**Status**: MIXED usage
```
utils/
├── __init__.py
├── document_utils.py
├── json_serializer.py
├── neo4j_utils.py      # UNUSED - Neo4j removed
├── performance_timer.py
├── redis_diagnostics.py
└── supabase_utils.py   # DEPRECATED - Supabase removed
```

### 10. Legacy Core (3 scripts)
**Status**: DEPRECATED - remove entirely
```
core/
├── __init__.py
├── database_handler.py
└── embeddings_processor.py
```

### 11. One-time/Migration Scripts (4 scripts)
**Status**: ARCHIVE after use
```
migrate_redis_databases.py
core_enhancements_immediate.py
clear_redis_cache.py
clear_rds_test_data.py
```

## Recommendations for Clean Codebase

### 1. Immediate Removals (17 scripts)
- `/core/` directory (3 scripts) - deprecated
- `/services/` unused scripts (3 scripts)
- `batch_processor.py` - deprecated
- `utils/neo4j_utils.py` - Neo4j removed
- `utils/supabase_utils.py` - Supabase removed
- One-time scripts (4 scripts)
- Test scripts in root (2 scripts)

### 2. Move to Separate Repositories
- **legal-doc-cli** repo: `/cli/` directory (4 scripts)
- **legal-doc-monitoring** repo: `/monitoring/` directory (4 scripts)
- **legal-doc-utilities** repo: `/utilities/` directory (11 scripts)

### 3. Consolidation Opportunities
- Validation scripts: Merge 7 scripts into 2-3
- Utils: Combine related utilities

### 4. Final Production Structure
```
scripts/
├── __init__.py
├── # Core Pipeline (15 scripts)
├── # Data Layer (4 scripts)
├── # Infrastructure (5 scripts)
├── # Services (3 scripts)
├── # Validation (2-3 scripts)
└── # Utils (3-4 scripts)

Total: ~30-35 production scripts (from 71)
```

## Benefits of Cleanup

1. **Reduced Complexity**: 50-60% fewer files
2. **Clearer Purpose**: Production-only codebase
3. **Faster Deployment**: Smaller container images
4. **Easier Maintenance**: Clear separation of concerns
5. **Better Testing**: Focused on production code

## Production Script Dependencies Graph

```
production_processor.py
├── intake_service.py
│   └── s3_storage.py
├── batch_tasks.py
│   ├── pdf_tasks.py
│   │   ├── textract_utils.py
│   │   ├── chunking_utils.py
│   │   ├── entity_service.py
│   │   └── graph_service.py
│   └── cache_warmer.py
├── status_manager.py
├── audit_logger.py
└── validation/
    ├── ocr_validator.py
    ├── entity_validator.py
    └── pipeline_validator.py
```

## Next Steps

1. Create GitHub issues for each cleanup task
2. Archive one-time scripts with documentation
3. Create separate repositories for non-production tools
4. Implement production-only build process
5. Update documentation to reflect new structure

This cleanup will result in a focused, maintainable codebase containing only the scripts necessary for production document processing.