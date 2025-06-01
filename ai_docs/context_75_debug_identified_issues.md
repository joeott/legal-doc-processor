# Context 75: Debug Analysis - Queue Processing Issues

## Executive Summary

During end-to-end testing of the document processing pipeline, we successfully uploaded a document through the Vercel frontend, but the queue processor failed during the intake phase. This document analyzes the root causes and proposes solutions.

## Issues Identified

### 1. Malformed Storage URL

**Problem**: The `original_file_path` in the database contains a malformed URL:
```
https://https://yalswdiexcuanszujjhl.supabase.co%0A/storage/v1/object/public/documents/documents/0f0eb0a9-80cc-469b-b4a8-b434be6bcac4.pdf
```

**Issues with this URL**:
- Double protocol prefix: `https://https://`
- URL-encoded newline character: `%0A` (should be `/`)
- Double directory path: `documents/documents/`

**Root Cause**: In `frontend/api/create-document-entry.ts` line 166:
```typescript
original_file_path: `https://${SUPABASE_URL}/storage/v1/object/public/documents/${s3Key}`,
```

The `SUPABASE_URL` environment variable already includes the protocol (`https://`), causing duplication. Additionally, there appears to be a newline character in the environment variable.

### 2. S3 Migration Attempt on Intake

**Problem**: The queue processor is attempting to migrate files from Supabase Storage to S3 during the intake phase, which is failing due to the malformed URL.

**Error Message**:
```
Failed to migrate file from Supabase Storage to S3: HTTPSConnectionPool(host='https', port=443): 
Max retries exceeded with url: /yalswdiexcuanszujjhl.supabase.co%0A/storage/v1/object/public/documents/documents/0f0eb0a9-80cc-469b-b4a8-b434be6bcac4.pdf
```

**Root Cause**: The S3 migration logic is being triggered even though the document should remain in Supabase Storage for OCR processing.

### 3. Database Trigger Errors

**Problem**: Multiple trigger errors during processing:
- `record "new" has no field "source_document_uuid"`
- `record "new" has no field "status"`

**Root Cause**: Despite our migrations, there are still triggers trying to access fields that don't exist on certain tables.

### 4. Storage Configuration Mismatch

**Current Storage State**:
- Supabase has a `documents` bucket (created 2025-05-20, not public)
- Frontend uploads to `documents/` prefix
- Queue processor expects files in S3 but they're in Supabase Storage

## Proposed Solutions

### Solution 1: Fix URL Construction in Frontend

**File**: `frontend/api/create-document-entry.ts`

```typescript
// Current (incorrect):
original_file_path: `https://${SUPABASE_URL}/storage/v1/object/public/documents/${s3Key}`,

// Fixed:
original_file_path: `${SUPABASE_URL.replace(/\/$/, '').trim()}/storage/v1/object/public/documents/${s3Key}`,
```

This fix:
- Removes trailing slashes from SUPABASE_URL
- Trims any whitespace/newlines
- Doesn't add duplicate protocol

### Solution 2: Fix Queue Processor Flow

The queue processor should follow this corrected flow for Stage 1:

```
1. INTAKE: 
   - Validate document exists in Supabase Storage
   - Migrate file to S3 (required for Textract)
   - Update status to 'pending_ocr'

2. S3_MIGRATION:
   - Download from Supabase Storage URL (fix malformed URL first)
   - Upload to S3 bucket
   - Update source_documents with S3 location

3. OCR:
   - Use S3 URL for Textract API
   - Send to Mistral OCR API as fallback
   - Store extracted text in source_documents table

4. DOCUMENT_PROCESSING:
   - Create neo4j_documents entry
   - Process text through main pipeline
```

### Solution 3: Fix Remaining Trigger Issues

Create a comprehensive trigger cleanup migration that:
1. Disables all non-essential triggers
2. Creates minimal, working triggers for queue management
3. Ensures no triggers reference non-existent fields

### Solution 4: Storage Strategy Clarification

For Stage 1 (Cloud-only):
- **Upload**: Files initially go to Supabase Storage
- **Migration**: Files must be migrated to S3 for Textract
- **Processing**: Textract reads from S3, Mistral can read from either
- **S3 Required**: S3 storage is mandatory for AWS Textract integration

## Implementation Plan

### Phase 1: Immediate Fixes

1. **Fix Frontend URL Construction**
   ```bash
   # Edit frontend/api/create-document-entry.ts
   # Fix line 166 to properly construct URL
   # Redeploy to Vercel
   ```

2. **Fix Existing Bad Data**
   ```sql
   -- Fix the malformed URL in the database
   UPDATE source_documents 
   SET original_file_path = REPLACE(
     REPLACE(
       REPLACE(original_file_path, 'https://https://', 'https://'),
       '%0A', ''
     ),
     'documents/documents/', 'documents/'
   )
   WHERE document_uuid = '0f0eb0a9-80cc-469b-b4a8-b434be6bcac4';
   ```

3. **Reset Queue Entry**
   ```sql
   -- Reset the failed queue entry
   UPDATE document_processing_queue
   SET status = 'pending',
       retry_count = 0,
       error_message = NULL,
       started_at = NULL
   WHERE document_uuid = '0f0eb0a9-80cc-469b-b4a8-b434be6bcac4';
   ```

### Phase 2: Queue Processor S3 Migration Fix

1. **Fix S3 Migration Logic**
   - Ensure proper URL parsing to download from Supabase Storage
   - Fix the malformed URL issue before attempting download
   - Properly construct S3 keys without duplicate paths

2. **Fix File Access Logic**
   - Parse and clean Supabase Storage URLs before use
   - Handle authentication if bucket is private
   - Ensure S3 upload includes proper metadata for Textract

### Phase 3: Long-term Improvements

1. **Environment Variable Validation**
   - Add validation to ensure SUPABASE_URL is properly formatted
   - Strip protocol, whitespace, and trailing slashes

2. **Unified Storage Interface**
   - Create abstraction layer for storage access
   - Support both Supabase Storage and S3 transparently

3. **Comprehensive Testing**
   - Add unit tests for URL construction
   - Add integration tests for storage access
   - Add end-to-end tests for each deployment stage

## Verification Steps

After implementing fixes:

1. **Check URL Format**
   ```sql
   SELECT original_file_path 
   FROM source_documents 
   WHERE document_uuid = '0f0eb0a9-80cc-469b-b4a8-b434be6bcac4';
   -- Should return: https://yalswdiexcuanszujjhl.supabase.co/storage/v1/object/public/documents/0f0eb0a9-80cc-469b-b4a8-b434be6bcac4.pdf
   ```

2. **Verify Queue Processing**
   - Queue entry status should progress: pending → processing → completed
   - S3 migration should complete successfully
   - File should be accessible in S3 for Textract
   - OCR should complete successfully using S3 URL

3. **Check Pipeline Flow**
   - Document should appear in neo4j_documents
   - Text should be extracted and chunked
   - Entities should be extracted

## Conclusion

The primary issues stem from:
1. Environment variable handling in the frontend causing malformed URLs
2. S3 migration failing due to the malformed Supabase Storage URL
3. Residual trigger complexity from previous implementations

By fixing the URL construction and ensuring proper S3 migration for Textract compatibility, we can achieve a working end-to-end pipeline. The key insight is that while files initially upload to Supabase Storage, they must be migrated to S3 for Textract OCR processing. The proposed solutions maintain the required S3 integration while fixing the URL parsing issues that prevent successful migration.