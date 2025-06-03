# Context 163: Monitor Enhancements and OCR Processing Fix

## Date: 2025-01-28

## Issues Identified

### 1. OCR Task Submission Problem
When submitting a document via `test_single_document.py`, the Celery task was created but never picked up by workers. The document remained in "submitted" status indefinitely.

### 2. File Path Resolution
The OCR task is being submitted with a relative path (`input/Paul, Michael (Acuity)/Paul, Michael - JDH EOA 1-27-25.pdf`) instead of an absolute path. This causes issues when the worker tries to access the file.

### 3. Textract Job Monitoring Gap
The system needs to monitor pending Textract jobs and trigger continuation when they complete. AWS Textract jobs are asynchronous and can take several minutes to process.

## Monitor Enhancements Implemented

### 1. Enhanced Live Feed
- Shows last 10 documents processed in past 5 minutes
- Displays time, UUID, filename, and status (✅/❌)
- Located in left panel of live dashboard

### 2. Textract Job Monitoring
Added new features to track AWS Textract jobs:
- `get_textract_jobs()` method to query pending jobs
- Display panel in live dashboard showing:
  - Number of pending Textract jobs
  - File names, status, and duration
  - Visual indicator in the monitoring dashboard

### 3. Textract Command
New command to check and process completed Textract jobs:
```bash
# Check once
python scripts/cli/monitor.py textract --once

# Monitor continuously (every 15 seconds)
python scripts/cli/monitor.py textract

# Custom interval
python scripts/cli/monitor.py textract --check-interval 30
```

This command:
- Queries textract_jobs table for SUBMITTED/IN_PROGRESS jobs
- Checks AWS for actual job status
- Triggers processing continuation when jobs complete
- Handles failures and updates error status

### 4. Document Control Commands
Enhanced control over individual documents:
```bash
# Stop processing
python scripts/cli/monitor.py control stop <uuid>

# Start/restart processing
python scripts/cli/monitor.py control start <uuid>

# Retry from specific stage
python scripts/cli/monitor.py control retry <uuid> --stage ocr
```

## Schema Issues Fixed

### 1. Table Column Names
- `neo4j_documents`: Uses `documentId` not `document_uuid`
- `textract_jobs`: Uses `job_status` not `status`
- `textract_jobs`: Uses `processed_pages` not `pages_processed`

### 2. Missing Columns
The `neo4j_entity_mentions` table is missing `document_uuid` column, causing errors in the monitor. This needs to be addressed in the schema.

## Next Steps to Fix OCR Processing

### 1. Fix File Path in Task Submission
The `control start` command needs to use absolute file paths:
```python
# Current (problematic)
file_path=doc['original_file_name']  # 'input/Paul, Michael...'

# Should be
file_path=os.path.abspath(doc['original_file_name'])
```

### 2. Add Textract Result Handler
Need to ensure `process_textract_result` task exists in `scripts/celery_tasks/ocr_tasks.py` to handle completed Textract jobs.

### 3. Fix Task Routing
Ensure OCR tasks are properly routed to the OCR queue and that OCR workers are listening to the correct queue.

### 4. Add S3 Upload Verification
Before submitting to Textract, verify:
- File uploaded to S3 successfully
- S3 key stored in database
- Proper permissions for Textract to access S3 bucket

## Monitoring Best Practices

1. **Use Live Dashboard**: `python scripts/cli/monitor.py live` provides real-time visibility
2. **Check Textract Jobs**: Run `python scripts/cli/monitor.py textract` periodically or in background
3. **Monitor Stage Errors**: The dashboard now shows errors grouped by pipeline stage
4. **Control Individual Documents**: Use control commands to stop/start/retry specific documents

## Current State

- Enhanced monitor is fully functional
- Can track documents, workers, queues, and Textract jobs
- Can control individual document processing
- Stage-specific error tracking helps identify bottlenecks
- Recent activity feed shows processing flow

The system is ready for processing once we fix the file path issue in the OCR task submission.