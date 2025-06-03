# Scripts Consolidation Summary - Quick Reference

## Major Consolidations

### 1. Entity Operations → `entity_service.py`
```
entity_extraction.py          ┐
entity_resolution.py          ├──→ entity_service.py
entity_resolution_enhanced.py ┤
structured_extraction.py      ┘
```

### 2. Database Operations → `database.py`
```
supabase_utils.py       ┐
core/db_migration_helper.py  ├──→ database.py
core/pydantic_db.py     ┘
```

### 3. Caching → `cache.py`
```
redis_utils.py         ┐
cache_keys.py          ├──→ cache.py
core/cache_manager.py  ┤
core/cache_models.py   ┤
core/model_cache.py    ┘
```

### 4. Celery Tasks → `celery_tasks/pdf_tasks.py`
```
celery_tasks/ocr_tasks.py      ┐
celery_tasks/text_tasks.py     ├──→ celery_tasks/pdf_tasks.py
celery_tasks/entity_tasks.py   ┤
celery_tasks/embedding_tasks.py┘
```

## Complete Removal List (38 legacy + 15 obsolete = 53 scripts)

### Entire Directories to Remove:
- `/scripts/legacy/` (38 scripts)
- `/scripts/recovery/` (3 scripts)
- `/scripts/archive/` (old utilities)

### Individual Scripts to Remove:
- `ocr_extraction_backup.py`
- `celery_tasks/ocr_tasks_backup.py`
- `models_init.py` (old initialization)
- `structured_extraction.py` (after merging)
- `plain_text_chunker.py` (obsolete)
- `core/document_processor.py` (replaced by pdf_pipeline.py)
- `core/db_manager_v2.py` (old version)
- `entity_resolution.py` (after merging)
- `entity_resolution_enhanced.py` (after merging)
- `core/entity_processor.py` (after merging)

## Final Structure (25 Essential Scripts)

```
/scripts/
├── Core (8)
│   ├── cache.py
│   ├── config.py
│   ├── database.py
│   ├── entity_service.py
│   ├── logging_config.py
│   ├── pdf_pipeline.py
│   ├── s3_storage.py
│   └── text_processing.py
│
├── Services (4)
│   ├── document_categorization.py
│   ├── graph_service.py (new)
│   ├── project_association.py
│   └── semantic_naming.py
│
├── Celery (4)
│   ├── celery_app.py
│   ├── pdf_tasks.py
│   ├── cleanup_tasks.py
│   └── graph_tasks.py
│
├── CLI (4)
│   ├── admin.py
│   ├── import.py
│   ├── monitor.py
│   └── __init__.py
│
└── Utils (5)
    ├── ocr_extraction.py
    ├── textract_utils.py
    ├── error_handler.py
    ├── json_serializer.py
    └── pipeline_monitor.py
```

## Impact: 79% Reduction

**Before**: 120+ scripts  
**After**: 25 scripts  
**Removed**: 95 scripts  
**Efficiency Gain**: 79%