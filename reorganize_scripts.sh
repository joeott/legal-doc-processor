#!/bin/bash
# Auto-generated reorganization script
set -e  # Exit on error

echo 'Creating backup...'
tar -czf scripts_backup_$(date +%Y%m%d_%H%M%S).tar.gz scripts/

echo 'Creating directories...'
mkdir -p dev_tools/{debug,database,manual_ops,validation,migration,testing}
mkdir -p scripts/{processors,storage,extractors,config,operational,enhancements}

echo 'Moving development scripts...'
mv scripts/check_doc_status.py dev_tools/debug/ 2>/dev/null || true
mv scripts/check_schema.py dev_tools/debug/ 2>/dev/null || true
mv scripts/check_ocr_task_status.py dev_tools/debug/ 2>/dev/null || true
mv scripts/check_task_details.py dev_tools/debug/ 2>/dev/null || true
mv scripts/check_celery_task_status.py dev_tools/debug/ 2>/dev/null || true
mv scripts/check_latest_tasks.py dev_tools/debug/ 2>/dev/null || true
mv scripts/test_uuid_flow.py dev_tools/testing/ 2>/dev/null || true
mv scripts/test_model_consistency.py dev_tools/testing/ 2>/dev/null || true
mv scripts/test_textract_e2e.py dev_tools/testing/ 2>/dev/null || true
mv scripts/test_phase3_stability.py dev_tools/testing/ 2>/dev/null || true
mv scripts/verify_actual_documents.py dev_tools/validation/ 2>/dev/null || true
mv scripts/verify_current_model_issues.py dev_tools/validation/ 2>/dev/null || true
mv scripts/validate_document_results.py dev_tools/validation/ 2>/dev/null || true
mv scripts/verify_production_readiness.py dev_tools/validation/ 2>/dev/null || true
mv scripts/retry_entity_resolution_with_cache.py dev_tools/manual_ops/ 2>/dev/null || true
mv scripts/manual_poll_textract.py dev_tools/manual_ops/ 2>/dev/null || true
mv scripts/retry_entity_extraction.py dev_tools/manual_ops/ 2>/dev/null || true
mv scripts/run_entity_extraction_with_chunks.py dev_tools/manual_ops/ 2>/dev/null || true

echo '✅ Reorganization complete!'
echo 'Remember to update imports after moving files.'