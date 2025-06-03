# Scripts Directory Consolidation Analysis for PDF-Only Pipeline

## Current Directory Structure

### Main Scripts (/scripts/)
1. **pdf_pipeline.py** - NEW: Integrated PDF processing pipeline (main entry point)
2. **celery_app.py** - Celery application configuration
3. **config.py** - Central configuration
4. **logging_config.py** - Logging setup
5. **models_init.py** - Model initialization utilities
6. **cache_keys.py** - Redis cache key definitions

### Core Services (/scripts/core/)
1. **pdf_models.py** - NEW: Pydantic models for PDF processing
2. **processing_models.py** - Document processing models
3. **schemas.py** - Database schemas
4. **task_models.py** - Celery task models
5. **cache_manager.py** - Cache management
6. **cache_models.py** - Cache-related models
7. **db_manager_v2.py** - Database management
8. **document_processor.py** - Document processing logic
9. **entity_processor.py** - Entity processing
10. **error_handler.py** - Error handling utilities

### Processing Scripts
1. **ocr_extraction.py** - PDF text extraction via Textract
2. **text_processing.py** - Text chunking and processing
3. **chunking_utils.py** - Chunking utilities
4. **plain_text_chunker.py** - Simple text chunking
5. **entity_extraction.py** - Entity extraction from text
6. **entity_resolution.py** - Entity resolution/deduplication
7. **entity_resolution_enhanced.py** - Enhanced entity resolution
8. **relationship_builder.py** - Relationship extraction
9. **structured_extraction.py** - Structured data extraction

### Storage & Infrastructure
1. **s3_storage.py** - S3 file management
2. **supabase_utils.py** - Supabase database utilities
3. **redis_utils.py** - Redis cache utilities
4. **textract_utils.py** - AWS Textract wrapper
5. **cloudwatch_logger.py** - AWS CloudWatch logging

### Service Layer (/scripts/services/)
1. **document_categorization.py** - Document type classification
2. **project_association.py** - Project matching logic
3. **semantic_naming.py** - Intelligent file naming

### Celery Tasks (/scripts/celery_tasks/)
1. **ocr_tasks.py** - OCR processing tasks
2. **text_tasks.py** - Text processing tasks
3. **entity_tasks.py** - Entity extraction tasks
4. **embedding_tasks.py** - Embedding generation tasks
5. **graph_tasks.py** - Graph building tasks
6. **cleanup_tasks.py** - Cleanup and maintenance
7. **task_utils.py** - Task utilities
8. **processing_state.py** - Processing state management
9. **idempotent_ops.py** - Idempotent operations

### CLI Tools (/scripts/cli/)
1. **import.py** - Document import commands
2. **monitor.py** - Pipeline monitoring
3. **admin.py** - Administrative commands

### Legacy Scripts (/scripts/legacy/)
- **All scripts here are deprecated** - functionality moved to CLI tools

### Recovery Scripts (/scripts/recovery/)
1. **full_cleanup.py** - Full cleanup utilities
2. **pipeline_verification_test.py** - Pipeline verification
3. **quick_status_check.py** - Quick status checking

### Shell Scripts
1. **start_celery_workers.sh** - Start Celery workers
2. **stop_celery_workers.sh** - Stop Celery workers
3. **monitor_celery_workers.sh** - Monitor workers
4. **start_flower_monitor.sh** - Start Flower UI

## Consolidation Recommendations

### 1. Scripts to Keep (Essential for PDF Pipeline)

**Core Pipeline:**
- `pdf_pipeline.py` - Main pipeline orchestrator
- `celery_app.py` - Celery configuration
- `config.py` - Configuration
- `logging_config.py` - Logging setup

**Processing:**
- `ocr_extraction.py` - PDF text extraction
- `text_processing.py` - Text chunking
- `entity_extraction.py` - Entity extraction
- `relationship_builder.py` - Relationship extraction

**Storage:**
- `s3_storage.py` - S3 operations
- `supabase_utils.py` - Database operations
- `redis_utils.py` - Cache operations
- `textract_utils.py` - Textract wrapper

**Services:**
- All files in `/scripts/services/` - Essential business logic

**Celery Tasks:**
- All files in `/scripts/celery_tasks/` - Task definitions

**CLI:**
- All files in `/scripts/cli/` - User interface

**Core Models:**
- `core/pdf_models.py` - PDF-specific models
- `core/processing_models.py` - Processing models
- `core/schemas.py` - Database schemas
- `core/cache_manager.py` - Cache management
- `core/error_handler.py` - Error handling

### 2. Scripts to Remove/Archive

**Duplicates:**
- `ocr_extraction_backup.py` - Backup file
- `celery_tasks/ocr_tasks_backup.py` - Backup file
- `image_processing.py` - Not needed for PDF-only
- `models_init.py` - Functionality in core models

**Legacy:**
- Entire `/scripts/legacy/` directory - Already marked deprecated

**Redundant:**
- `entity_resolution_enhanced.py` - Consolidate with `entity_resolution.py`
- `plain_text_chunker.py` - Functionality in `text_processing.py`
- `structured_extraction.py` - Integrate into entity extraction
- `chunking_utils.py` - Merge with `text_processing.py`

### 3. Consolidation Actions

#### A. Merge Entity Processing
Combine:
- `entity_extraction.py`
- `entity_resolution.py`
- `entity_resolution_enhanced.py`
- `structured_extraction.py`

Into single module: `entity_processor.py`

#### B. Merge Text Processing
Combine:
- `text_processing.py`
- `chunking_utils.py`
- `plain_text_chunker.py`

Into single module: `text_processor.py`

#### C. Consolidate Core Models
Move remaining models from:
- `core/cache_models.py`
- `core/task_models.py`
- `core/processing_models.py`

Into unified model structure under `core/models/`

#### D. Simplify Database Layer
Consolidate:
- `core/db_manager_v2.py`
- `core/db_migration_helper.py`
- `core/pydantic_db.py`

Into single: `core/database.py`

### 4. Final Recommended Structure

```
/scripts/
├── __init__.py
├── celery_app.py           # Celery configuration
├── config.py               # Central configuration
├── logging_config.py       # Logging setup
├── cache_keys.py          # Cache key definitions
│
├── core/                   # Core functionality
│   ├── __init__.py
│   ├── models.py          # All Pydantic models
│   ├── database.py        # Database operations
│   ├── cache.py           # Cache management
│   └── errors.py          # Error handling
│
├── processors/            # Document processors
│   ├── __init__.py
│   ├── pdf_pipeline.py    # Main pipeline
│   ├── ocr_processor.py   # OCR extraction
│   ├── text_processor.py  # Text processing/chunking
│   ├── entity_processor.py # Entity extraction/resolution
│   └── relationship_processor.py # Relationships
│
├── services/              # Business logic services
│   ├── __init__.py
│   ├── document_categorization.py
│   ├── project_association.py
│   └── semantic_naming.py
│
├── storage/               # Storage backends
│   ├── __init__.py
│   ├── s3.py             # S3 operations
│   ├── supabase.py       # Database operations
│   ├── redis.py          # Cache operations
│   └── textract.py       # AWS Textract
│
├── tasks/                 # Celery tasks (rename from celery_tasks)
│   ├── __init__.py
│   ├── ocr.py
│   ├── text.py
│   ├── entity.py
│   ├── embedding.py
│   ├── graph.py
│   ├── cleanup.py
│   └── utils.py
│
├── cli/                   # CLI commands
│   ├── __init__.py
│   ├── import.py
│   ├── monitor.py
│   └── admin.py
│
└── scripts/               # Shell scripts
    ├── start_workers.sh
    ├── stop_workers.sh
    └── monitor_workers.sh
```

### 5. Benefits of Consolidation

1. **Reduced Duplication**: Merge overlapping functionality
2. **Clearer Organization**: Logical grouping by function
3. **Easier Maintenance**: Fewer files to manage
4. **Better Imports**: Clear module boundaries
5. **PDF-Focused**: Remove non-PDF processing code

### 6. Migration Steps

1. Create new directory structure
2. Merge and refactor modules as specified
3. Update all imports in existing code
4. Test each module independently
5. Remove deprecated/legacy code
6. Update CLI tools to use new structure
7. Archive old structure for reference

This consolidation will reduce the codebase by approximately 40% while maintaining all essential PDF processing functionality.