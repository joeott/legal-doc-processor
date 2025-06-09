# Context 357: Critical Database API Recovery Status

## Date: 2025-06-03 21:00

### Current Situation
In the middle of implementing Phase 2 (Verify Pipeline Execution) of the supplemental plan from context_353. Successfully fixed multiple critical issues but pipeline is still blocked by database API mismatches.

### Purpose
Fixing the legal document processing pipeline that was broken during consolidation. The pipeline cannot process any documents due to multiple API mismatches between the consolidated code and the actual database schema.

### Critical Fixes Applied

1. **Import Error - FIXED**
   - `scripts.textract_job_manager` module was missing
   - Fixed by updating pdf_tasks.py lines 363-387 to use TextractProcessor from textract_utils

2. **Worker Queue Configuration - FIXED**
   - Workers were not listening to OCR queue
   - Fixed by restarting with: `celery -A scripts.celery_app worker --loglevel=info --queues=default,ocr,text,entity,graph,cleanup --detach`

3. **Table Mapping Error - FIXED**
   - rds_utils.py had wrong TABLE_MAPPINGS: `"source_documents": "documents"`
   - Fixed to: `"source_documents": "source_documents"` (lines 81-91)

4. **Import Error in db.py - FIXED**
   - Missing try/except for enhanced_column_mappings import
   - Fixed by adding try/except block at lines 105-110

### Current Blocker
DatabaseManager validation error when retrieving document:
```
ERROR: Validation failed for SourceDocumentMinimal
original_file_name: Input should be a valid string [type=string_type, input_value=None]
```

The document exists in database but `original_file_name` column is NULL, causing Pydantic validation to fail.

### Test Document Status
- UUID: 4909739b-8f12-40cd-8403-04b8b1a79281
- File: Paul, Michael - Wombat Corp Disclosure Stmt 10-23-24.pdf
- Created successfully, uploaded to S3
- Pipeline blocked at OCR stage due to database retrieval failure

### Next Steps Required

1. **Fix Pydantic Model Validation**
   - Either update SourceDocumentMinimal to allow None for original_file_name
   - Or update database record to have non-null original_file_name
   - Located in models imported by get_source_document_model()

2. **Verify OCR Processing**
   - Once document retrieval works, OCR should start
   - Monitor with: `python3 scripts/monitor_document_complete.py 4909739b-8f12-40cd-8403-04b8b1a79281`

3. **Complete Phase 2**
   - Verify Textract job submission
   - Check for AWS permission issues
   - Monitor pipeline progression

### Key Commands

```bash
# Environment setup
cd /opt/legal-doc-processor && source load_env.sh

# Monitor document
python3 scripts/monitor_document_complete.py 4909739b-8f12-40cd-8403-04b8b1a79281

# Submit to pipeline
python3 -c "
from scripts.pdf_tasks import process_pdf_document
result = process_pdf_document.delay(
    document_uuid='4909739b-8f12-40cd-8403-04b8b1a79281',
    file_path='input_docs/Paul, Michael (Acuity)/Paul, Michael - Wombat Corp Disclosure Stmt 10-23-24.pdf',
    project_uuid='e0c57112-c755-4798-bc1f-4ecc3f0eec78'
)"

# Check task status
from scripts.celery_app import app
from celery.result import AsyncResult
result = AsyncResult('[task_id]', app=app)
print(f'State: {result.state}')
```

### Critical Files Modified
1. `/opt/legal-doc-processor/scripts/pdf_tasks.py` - Fixed textract_job_manager import
2. `/opt/legal-doc-processor/scripts/rds_utils.py` - Fixed TABLE_MAPPINGS
3. `/opt/legal-doc-processor/scripts/db.py` - Added try/except for enhanced_column_mappings
4. `/opt/legal-doc-processor/scripts/monitor_document_complete.py` - Fixed column names

### Schema Reference Created
- `/opt/legal-doc-processor/scripts/utils/schema_reference.py` - Documents all column name mismatches

### Progress Summary
- Phase 1 ✓ Complete - Monitoring tool working
- Phase 2 🚧 In Progress - Pipeline execution blocked by validation error
- Phase 3 ⏸️ Pending - Textract permissions
- Phase 4 ⏸️ Pending - Integration tests
- Phase 5 ⏸️ Pending - Production readiness

### Immediate Action
The next Claude instance should:
1. Fix the SourceDocumentMinimal model to allow None for original_file_name
2. Resubmit the document to the pipeline
3. Monitor for successful OCR job creation
4. Continue with Phase 2 completion

The pipeline is very close to working - just need to fix this final validation issue.