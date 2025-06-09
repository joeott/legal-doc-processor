# Context 358: API Fixes Progress and Worker Restart

## Date: 2025-06-03 21:35

### Summary
Successfully fixed multiple critical API mismatches but encountered persistent import caching issue. Pipeline is progressing but needs worker restart to load updated code.

### Critical Fixes Applied

1. **SourceDocumentMinimal Validation - FIXED**
   - Made `original_file_name` optional in models_minimal.py
   - Allows processing of documents with NULL original_file_name

2. **Dictionary Access Error - FIXED**
   - Fixed pdf_tasks.py line 377-381
   - Changed from dict access (`doc['s3_bucket']`) to attribute access (`doc.s3_bucket`)

3. **Import Error - FIXED**
   - Removed references to non-existent `textract_job_manager` module
   - Updated to use `TextractProcessor` from `textract_utils`

4. **Column Mapping Error - FIXED**
   - Fixed COLUMN_MAPPINGS in rds_utils.py
   - Removed incorrect mapping of `document_uuid` to `id`
   - Now correctly preserves `document_uuid` in queries

### Current Issue
Celery worker has cached the old bytecode with import errors. Need to restart worker to load updated code.

### Test Document Progress
- UUID: 4909739b-8f12-40cd-8403-04b8b1a79281
- Multiple submission attempts, all failing at OCR due to import caching
- Latest task: 0800596a-1605-4a97-91b9-d17f9b905023
- OCR task: ff80ffd2-a89e-43d2-b7b7-14126b597719 (failed with cached import)

### Next Steps

1. **Restart Celery Worker**
   ```bash
   # Kill existing workers
   pkill -f celery
   
   # Start fresh worker with all queues
   celery -A scripts.celery_app worker --loglevel=info --queues=default,ocr,text,entity,graph,cleanup --detach
   ```

2. **Resubmit Document**
   - Use existing test document
   - Monitor for Textract job creation

3. **Check Textract Permissions**
   - If OCR starts but fails, check S3-Textract permissions
   - May need to apply bucket policy from context_293

### Progress Summary
- ✓ Fixed 4 critical API mismatches
- ✓ Document submission working
- ✓ OCR task creation working
- ⏸️ OCR execution blocked by cached imports
- Next: Worker restart to clear cache

### Key Learning
Python bytecode caching can persist old imports even after source fixes. Always restart workers after fixing import errors.