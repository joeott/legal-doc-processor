# Context 67: Queue Processor Fixes and Schema Conformance

## Date: 2025-05-23

## Overview
This document captures the critical fixes applied to the queue processor and schema conformance issues discovered during Phase 1 end-to-end testing.

## Progress Summary

### 1. Environment Configuration Cleanup
- **Issue**: Legacy S3 bucket variables from Mistral OCR era were still present in .env
- **Resolution**: 
  - Removed deprecated variables: `S3_BUCKET_PRIVATE`, `S3_BUCKET_PUBLIC`, `S3_BUCKET_TEMP`
  - Retained only `S3_PRIMARY_DOCUMENT_BUCKET=samu-docs-private-upload`
  - Fixed Redis password syntax error where `DEPLOYMENT_STAGE=1` was accidentally appended

### 2. Database Connectivity Tests Completed
Successfully verified all critical connections:
- ✅ **Supabase connection**: 1 project record found
- ✅ **S3 access**: Bucket exists with documents/ folder
- ✅ **Textract CLI**: Available and configured
- ✅ **Recent documents**: 3 documents found (Pre-Trial Order PDFs in pending_ocr/pending_intake status)

### 3. Queue Processor Schema Fixes

#### Issue 1: Project Query Failure
- **Error**: `406 Not Acceptable` when querying projects table
- **Root Cause**: Queue processor was using direct SQL query instead of SupabaseManager method
- **Fix Applied**:
  ```python
  # OLD (line 38-42):
  response_project = self.db_manager.client.table('projects').select('id').eq('projectId', PROJECT_ID_GLOBAL).maybe_single().execute()
  
  # NEW:
  project_sql_id, project_uuid = self.db_manager.get_or_create_project(PROJECT_ID_GLOBAL)
  ```

#### Issue 2: Source Documents Column Mismatch
- **Error**: `Could not find the 'updated_at' column of 'source_documents'`
- **Root Cause**: Method was using 'updated_at' but table has 'last_modified_at'
- **Fix Applied** in `supabase_utils.py` line 859:
  ```python
  # OLD:
  'updated_at': datetime.now().isoformat()
  
  # NEW:
  'last_modified_at': datetime.now().isoformat()
  ```

#### Issue 3: Missing Imports
- **Error**: `USE_S3_FOR_INPUT` and `S3_TEMP_DOWNLOAD_DIR` not defined
- **Fix Applied** in `queue_processor.py` line 13:
  ```python
  from config import PROJECT_ID_GLOBAL, USE_S3_FOR_INPUT, S3_TEMP_DOWNLOAD_DIR
  ```

## Confirmed Schema Information

### source_documents Table Columns
Based on MCP Supabase query, the actual columns are:
- `id` (integer) - Primary key
- `project_fk_id` (integer) - Foreign key to projects
- `project_uuid` (varchar) - UUID reference
- `document_uuid` (varchar) - Document UUID
- `intake_timestamp` (timestamp) - When document was ingested
- `last_modified_at` (timestamp) - Update tracking
- `initial_processing_status` (varchar) - Processing state
- `textract_job_id` (varchar) - AWS Textract job ID
- `textract_job_status` (varchar) - Textract processing status
- `ocr_provider` (user-defined type) - OCR provider enum
- `raw_extracted_text` (text) - Extracted text content
- Plus additional S3, Textract, and metadata fields

### Key Findings
1. **No 'created_at' or 'updated_at' columns** - Use `intake_timestamp` and `last_modified_at` instead
2. **OCR provider is an enum type** - Must use valid values like 'textract'
3. **Textract integration columns are present** - Full support for job tracking

## Current System State

### Documents in Queue
- 3 Pre-Trial Order PDFs waiting to be processed
- Status: `pending_ocr` or `pending_intake`
- Ready for queue processor to claim and process

### Processing Flow Confirmed
1. Documents uploaded to Supabase Storage
2. Queue entries created in `document_processing_queue`
3. Queue processor claims documents
4. Textract processes PDFs via S3
5. Results stored back in source_documents
6. Neo4j document nodes created
7. Entity extraction and relationship building follow

## Next Steps

### Immediate Actions
1. **Restart Queue Processor** with fixed code
2. **Monitor Processing** of the 3 pending documents
3. **Verify Textract Integration** works end-to-end

### Testing Checklist
- [ ] Queue processor successfully claims documents
- [ ] Textract jobs are created and tracked
- [ ] OCR text is extracted and stored
- [ ] Neo4j document nodes are created
- [ ] Entity extraction begins automatically
- [ ] No schema-related errors occur

### Potential Issues to Watch
1. **Textract Permissions** - Ensure S3 bucket has proper IAM policies
2. **Async Job Handling** - Monitor Textract job completion
3. **Error Handling** - Watch for any new column mismatches

## Code Quality Notes

### Pylance Warnings Detected
Several code quality issues were flagged:
- Unreachable code after exception handling (lines 287, 350)
- Unused variables (response objects that could be removed)
- These are non-critical but should be cleaned up

### Recommended Cleanup
1. Remove unreachable code blocks
2. Remove unused variable assignments
3. Consider adding type hints for better IDE support

## Configuration Reminders

### Critical Environment Variables
```bash
# Deployment Stage
DEPLOYMENT_STAGE=1

# S3 Configuration (Single Private Bucket)
S3_PRIMARY_DOCUMENT_BUCKET=samu-docs-private-upload
USE_UUID_FILE_NAMING=true

# AWS Credentials (Required for Textract)
AWS_ACCESS_KEY_ID=<set>
AWS_SECRET_ACCESS_KEY=<set>
AWS_DEFAULT_REGION=us-east-1

# Supabase Configuration
SUPABASE_URL=<set>
SUPABASE_ANON_KEY=<set>

# OpenAI (Stage 1 requirement)
OPENAI_API_KEY=<set>
```

## Lessons Learned

1. **Always use SupabaseManager methods** instead of direct queries to ensure schema compatibility
2. **Column names vary by table** - source_documents uses different conventions than neo4j_* tables
3. **MCP tools are invaluable** for real-time schema inspection
4. **Import all config variables** explicitly to avoid runtime errors

This completes the queue processor fixes and prepares the system for successful Phase 1 processing.