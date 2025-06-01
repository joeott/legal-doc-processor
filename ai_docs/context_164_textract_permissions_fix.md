# Context 164: Textract Permissions Fix and Enhanced Monitoring

## Date: 2025-01-28

## Root Cause Identified

The OCR processing was failing with "RuntimeError: OCR failed to extract text" but no detailed error information. Through debugging, we discovered:

1. **Missing S3 Bucket Policy**: AWS Textract requires explicit permission to read from S3 buckets
2. **Sync vs Async API Confusion**: The system was attempting to use synchronous `detect_document_text` API for PDFs, which only supports images

## Solution Implemented

### 1. S3 Bucket Policy for Textract Access

Created and applied the following bucket policy to `samu-docs-private-upload`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowTextractAccess",
      "Effect": "Allow",
      "Principal": {
        "Service": "textract.amazonaws.com"
      },
      "Action": [
        "s3:GetObject"
      ],
      "Resource": "arn:aws:s3:::samu-docs-private-upload/*"
    }
  ]
}
```

This grants AWS Textract service permission to read objects from the bucket.

### 2. Verification Steps

```bash
# Apply bucket policy
aws s3api put-bucket-policy --bucket samu-docs-private-upload --policy file://textract_bucket_policy.json

# Test async Textract (correct for PDFs)
aws textract start-document-text-detection \
  --document-location '{"S3Object":{"Bucket":"samu-docs-private-upload","Name":"documents/1d4282be-6a1a-4c03-829d-8dfdce34828a.pdf"}}' \
  --region us-east-2

# Check job status
aws textract get-document-text-detection --job-id <job-id> --region us-east-2
```

### 3. Enhanced Debugging Script

Created `test_textract_debug.py` with:
- Boto3 debug logging enabled
- Step-by-step S3 upload verification
- Sync vs async API testing
- IAM identity verification
- Detailed error capture

## Key Learnings

### 1. Textract API Selection
- **Synchronous API** (`detect_document_text`): Only for single-page images (PNG, JPEG)
- **Asynchronous API** (`start_document_text_detection`): Required for PDFs and multi-page documents

### 2. Permission Requirements
Textract needs:
- S3 bucket policy allowing `textract.amazonaws.com` principal
- Objects must be in the same region as Textract API calls
- No special object ACLs required if bucket policy is correct

### 3. Error Messages
- "Unable to get object metadata from S3" = Permission issue
- "UnsupportedDocumentException" = Using wrong API (sync for PDF)
- "InvalidS3ObjectException" = Usually permissions or region mismatch

## Monitor Enhancements for Textract

The enhanced monitor (`/scripts/cli/monitor.py`) now includes:

1. **Textract Jobs Panel**: Shows pending/in-progress Textract jobs
2. **Textract Command**: `python scripts/cli/monitor.py textract`
   - Monitors pending jobs every 15 seconds
   - Automatically triggers continuation when jobs complete
   - Handles failures and updates error status

3. **Debug Information**:
   - Job duration tracking
   - AWS status vs database status comparison
   - Automatic retry capability

## Current System State

1. **S3 Bucket**: Configured with proper Textract permissions
2. **Monitor**: Enhanced with Textract job tracking and processing
3. **OCR Processing**: Should now work correctly with proper async handling
4. **Error Logging**: Enhanced with detailed metadata capture

## Next Steps

1. Ensure `extract_text_from_pdf_textract` in `ocr_extraction.py` uses async API for PDFs
2. Update OCR task to properly handle async Textract job polling
3. Add automatic retry for transient S3 permission errors
4. Consider adding CloudWatch logging for Textract jobs

## Testing Checklist

- [x] S3 bucket policy applied
- [x] Textract can access S3 objects
- [x] Async API works for PDFs
- [x] Monitor can track Textract jobs
- [ ] End-to-end document processing
- [ ] Error recovery and retry logic

The system is now properly configured for Textract processing. Documents should process successfully once the async handling is properly implemented in the OCR tasks.