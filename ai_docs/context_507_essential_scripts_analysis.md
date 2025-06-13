# Context 507: Essential Scripts Analysis from Production Testing

## Date: 2025-06-12
## Purpose: Document essential scripts identified during batch processing test

## Test Summary

Attempted to process 10 documents from Paul, Michael (Acuity) folder through production pipeline.

### Key Findings

1. **Memory Constraints**
   - System at 88.2% memory usage (3384/3837MB)
   - Circuit breaker blocking processing
   - Workers need restart to free memory

2. **Database Prerequisites**
   - Documents must exist in `source_documents` table before processing
   - Foreign key constraint on `processing_tasks.document_id`
   - Need proper document registration workflow

3. **API Mismatches**
   - `batch_tasks.py` passes extra kwargs (`warm_cache`, `entity_resolution`, etc.)
   - `process_pdf_document()` only accepts: `document_uuid`, `file_path`, `project_uuid`, `document_metadata`
   - Need parameter filtering in batch processing

## Essential Production Scripts Identified

### Core Processing Scripts (/scripts/)
1. **celery_app.py** - Celery configuration and task routing ✅ ESSENTIAL
2. **pdf_tasks.py** - Main pipeline tasks (6 stages) ✅ ESSENTIAL
3. **batch_tasks.py** - Batch processing coordination ✅ ESSENTIAL (needs fix)
4. **db.py** - Database operations ✅ ESSENTIAL
5. **cache.py** - Redis caching ✅ ESSENTIAL
6. **config.py** - Environment configuration ✅ ESSENTIAL
7. **models.py** - Pydantic models (single source of truth) ✅ ESSENTIAL

### Processing Services (/scripts/)
8. **ocr_extraction.py** - PDF text extraction ✅ ESSENTIAL
9. **textract_utils.py** - AWS Textract integration ✅ ESSENTIAL
10. **chunking_utils.py** - Text chunking ✅ ESSENTIAL
11. **entity_service.py** - Entity extraction/resolution ✅ ESSENTIAL
12. **graph_service.py** - Relationship building ✅ ESSENTIAL
13. **s3_storage.py** - S3 operations ✅ ESSENTIAL
14. **status_manager.py** - Pipeline status tracking ✅ ESSENTIAL
15. **logging_config.py** - Logging setup ✅ ESSENTIAL

### Worker Management (/scripts/)
16. **start_all_workers.sh** - Production worker startup ✅ ESSENTIAL
17. **start_celery_worker.sh** - Individual worker startup (backup)

### Monitoring Scripts (/scripts/monitoring/)
18. **monitor_workers.sh** - Real-time worker health ✅ ESSENTIAL
19. **monitor_full_pipeline.py** - Pipeline progress monitoring

### Utility Scripts (/scripts/utilities/)
20. **schema_inspector.py** - Database schema export ✅ ESSENTIAL
21. **clear_redis_cache.py** - Cache maintenance
22. **clear_rds_test_data.py** - Test data cleanup

### Validation (/scripts/validation/)
23. **conformance_validator.py** - Model validation ✅ ESSENTIAL
24. **ocr_validator.py** - OCR validation ✅ ESSENTIAL
25. **entity_validator.py** - Entity validation ✅ ESSENTIAL
26. **pipeline_validator.py** - Pipeline validation ✅ ESSENTIAL

### Import/CLI (/scripts/cli/)
27. **import.py** - Document import (needs fixing)
28. **monitor.py** - CLI monitoring tool

## Scripts to Remove/Consolidate

### Redundant Test Scripts
- All test_*.py files in root (moved to /tests/)
- verify_fixes.py (test utility)
- check_*.py utilities (mostly debug tools)

### Deprecated Scripts
- process_with_redis_monitoring.py (use monitor_full_pipeline.py)
- monitor_redis_acceleration.py (integrated into main monitoring)

### One-time Scripts
- batch_metrics.py (if not actively used)
- batch_recovery.py (if error handling integrated)
- cache_warmer.py (if not needed for performance)
- migrate_redis_databases.py (migration complete)

## Required Fixes

1. **Fix batch_tasks.py parameter passing**:
```python
# Filter kwargs before passing to process_pdf_document
task_kwargs = {'project_uuid': project_uuid}
if 'document_metadata' in options:
    task_kwargs['document_metadata'] = options['document_metadata']
```

2. **Add document registration step**:
```python
# Ensure document exists in source_documents before processing
# Either in batch_tasks or as separate registration step
```

3. **Memory management**:
- Restart workers to free memory
- Consider memory limits in worker configuration
- Add memory monitoring to prevent circuit breaker

## Production Readiness Assessment

- **Worker Configuration**: ✅ Complete (8 workers running)
- **Queue Coverage**: ✅ All queues monitored
- **Database Schema**: ✅ Verified and exported
- **Core Scripts**: ✅ Identified and organized
- **Memory Management**: ⚠️ Needs attention (88% usage)
- **Document Registration**: ❌ Missing workflow
- **Batch Processing**: ⚠️ Needs parameter fix

## Next Steps

1. Free memory by restarting workers
2. Fix batch_tasks.py parameter passing
3. Implement document registration workflow
4. Re-run batch with fixes
5. Remove non-essential scripts after successful test