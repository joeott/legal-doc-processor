# Context 356: Critical API Mismatches - Round 2

## Date: 2025-06-03

### Summary
While implementing Phase 2 of the supplemental plan, discovered multiple critical API mismatches preventing pipeline execution.

### Critical Issues Found

1. **Import Error - Fixed**
   - `scripts.textract_job_manager` module missing
   - Fixed by updating to use `TextractProcessor` from `textract_utils`

2. **DatabaseManager Table Name Issue - CRITICAL**
   - `DatabaseManager.get_source_document()` queries wrong table
   - Looking for "documents" table instead of "source_documents"
   - Error: `relation "documents" does not exist`

3. **Worker Queue Configuration - Fixed**
   - Workers were not listening to OCR queue
   - Fixed by restarting with `--queues=default,ocr,text,entity,graph,cleanup`

4. **Column Name Issues - Documented**
   - Multiple column name mismatches throughout
   - Created schema_reference.py to document correct names

### Current Blocker
The DatabaseManager is fundamentally broken - it's querying the wrong table name. This prevents:
- Document retrieval
- Status updates
- Pipeline progression

### Evidence
```python
# Test shows the issue
from scripts.db import DatabaseManager
db = DatabaseManager(validate_conformance=False)
doc = db.get_source_document('4909739b-8f12-40cd-8403-04b8b1a79281')
# Error: relation "documents" does not exist
# SQL: SELECT * FROM documents WHERE id = '4909739b-8f12-40cd-8403-...'
```

### Root Cause Analysis
The consolidation appears to have introduced inconsistencies:
1. Some code expects table "documents"
2. Actual table is "source_documents"
3. Column name mismatches (id vs document_uuid)

### Immediate Action Required
Must fix DatabaseManager to use correct table and column names:
- Table: `source_documents` (not `documents`)
- Primary key: `document_uuid` (not `id`)

### Impact
Until this is fixed:
- No document can be processed
- OCR tasks fail immediately
- Pipeline is completely blocked

### Recommendation
This requires immediate attention before continuing with Phase 2 or 3. The DatabaseManager is a core component that everything depends on.