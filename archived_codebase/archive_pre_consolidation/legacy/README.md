# Legacy Scripts Archive

This directory contains scripts that have been replaced by the unified CLI tools or are no longer actively used in the pipeline.

## Directory Structure

### import/
Scripts replaced by `scripts/cli/import.py`:
- import_client_files.py
- import_dashboard.py
- import_from_manifest.py
- import_from_manifest_fixed.py
- import_from_manifest_targeted.py
- import_tracker.py

### monitoring/
Scripts replaced by `scripts/cli/monitor.py`:
- live_monitor.py
- redis_monitor.py
- enhanced_pipeline_monitor.py
- monitor_cache_performance.py
- monitor_live_test.py
- pipeline_monitor.py
- standalone_pipeline_monitor.py

### testing/
Test scripts for manual testing (use pytest for automated tests):
- test_airtable_document_matching.py
- test_airtable_e2e.py
- test_celery_e2e.py
- test_chunk_cache_invalidation.py
- test_chunk_list_caching.py
- test_chunking_reprocessing.py
- test_direct_ocr.py
- test_e2e_with_caching.py
- test_error_recovery.py
- test_full_pipeline.py
- test_fuzzy_matching_debug.py
- test_idempotent_chunking.py
- test_import_verification.py
- test_multiple_documents.py
- test_recursive_project_assignment.py
- test_redis_cloud_connection.py
- test_redis_connection.py
- test_reprocessing_scenarios.py
- test_single_document.py

### debugging/
Scripts replaced by `scripts/cli/admin.py` and `scripts/cli/monitor.py`:
- debug_celery_document.py
- debug_project_matching.py
- check_celery_status.py
- check_doc_status_simple.py
- check_import_completion.py

### fixes/
One-time fix scripts (functionality now in admin CLI):
- fix_all_imports.py
- fix_celery_imports.py
- fix_common_errors.py
- fix_openai_params.py
- fix_triggers.py

### cleanup/
Scripts replaced by `scripts/cli/admin.py cleanup` commands:
- cleanup_database.py
- cleanup_test_documents.py

### verification/
Scripts replaced by `scripts/cli/admin.py` commands:
- verify_celery_migration.py
- verify_celery_tasks.py
- verify_import.py
- validate_graph_completion.py
- generate_test_report.py

### processing/
Scripts replaced by `scripts/cli/admin.py` batch commands:
- migrate_to_celery.py
- migrate_to_optimized_redis.py
- process_pending_document.py
- process_stuck_documents.py
- recover_stuck_documents.py

### utilities/
Miscellaneous utility scripts:
- analyze_client_files.py
- apply_celery_migrations.py
- apply_migration.py
- backfill_project_uuids.py
- cache_warmer.py
- celery_submission.py
- diagnose_document_failure.py
- execute_migration_steps.py
- extract_current_schema.py
- filter_manifest_no_av.py
- install_project.py
- list_projects.py
- live_document_test.py
- simple_chunking_fallback.py

## Migration Guide

### Import Operations
Instead of:
```bash
python scripts/import_from_manifest.py manifest.json
```
Use:
```bash
python scripts/cli/import.py from-manifest manifest.json
```

### Monitoring
Instead of:
```bash
python scripts/live_monitor.py
```
Use:
```bash
python scripts/cli/monitor.py pipeline
```

### Admin Operations
Instead of:
```bash
python scripts/process_stuck_documents.py
```
Use:
```bash
python scripts/cli/admin.py documents stuck --reset
```

### Testing
Instead of:
```bash
python scripts/test_single_document.py
```
Use the actual pipeline with monitoring:
```bash
# Submit document
python scripts/cli/import.py from-manifest manifest.json
# Monitor progress
python scripts/cli/monitor.py pipeline
```

## Note
These scripts are preserved for reference but should not be used in production. All functionality has been consolidated into the unified CLI tools.