# Context 158: Single PDF Processing Issues Summary

## Test Configuration
- **Date**: 2025-05-28
- **Document**: Paul, Michael - Wombat Corp Disclosure Stmt 10-23-24.pdf
- **Document UUID**: e10e1aa3-b657-4208-ac94-2f9d8dc34ee9
- **Celery Task ID**: 971f7639-83bd-4195-8f18-667ec5cf89a7
- **File Size**: 101,838 bytes

## Processing Results

### Successful Stages
1. ✅ **Prerequisites Check**
   - Redis connected successfully
   - Supabase database accessible
   - AWS credentials configured
   - OpenAI API key set
   - S3 bucket configured: samu-docs-private-upload

2. ✅ **Celery Workers**
   - All required workers running
   - Multiple workers available for each queue type
   - Worker `all_worker@Mac` handling all queues

3. ✅ **Document Intake (Stage 1)**
   - Project created successfully (ID: 613, UUID: b508832b-64e3-47d9-bbbe-ce9d2c520f2d)
   - Source document entry created (ID: 1458)
   - Correct file type set: ".pdf" (with dot)
   - Initial status properly set

4. ✅ **Celery Task Submission (Stage 2)**
   - Task submitted to OCR queue
   - Task ID generated and stored
   - Document status updated to "processing"

### Failed Stage
❌ **OCR Processing (Stage 3)**
- **Final Status**: `ocr_failed`
- **Processing Status**: `extraction_failed`
- **OCR Provider**: `textract`
- **Textract Job ID**: `N/A_EXCEPTION`
- **Textract Status**: `failed`
- **Error Message**: `RuntimeError: OCR failed to extract text from Paul, Michael - Wombat Corp Disclosure Stmt 10-23-24.pdf`

## Issues Identified

### 1. Textract Processing Failure
**Symptoms**:
- Textract job ID shows as "N/A_EXCEPTION" indicating the job was never created
- OCR provider was correctly set to "textract"
- No raw text extracted

**Possible Causes**:
1. **S3 Upload Issue**: Document may have failed to upload to S3 before Textract submission
2. **AWS Permissions**: IAM role may lack necessary Textract permissions
3. **File Corruption**: PDF might be corrupted or use unsupported features
4. **Network/Timeout**: AWS API call may have timed out

### 2. Error Logging Gaps
**Observation**: The error message is generic without specific details about what failed

**Missing Information**:
- No S3 upload confirmation
- No specific AWS error codes
- No detailed exception traceback in database
- OCR metadata JSON is null (should contain error details)

### 3. Monitoring Script Timeout
**Issue**: The verbose monitoring script crashed with a connection timeout to Supabase
- This appears to be a separate issue from the document processing
- Suggests potential network instability or rate limiting

## Recommendations for Resolution

### Immediate Actions
1. **Check S3 Upload**:
   ```python
   # Verify if document exists in S3
   from scripts.s3_storage import S3StorageManager
   s3_mgr = S3StorageManager()
   exists = s3_mgr.check_file_exists('e10e1aa3-b657-4208-ac94-2f9d8dc34ee9.pdf')
   ```

2. **Test Textract Directly**:
   ```python
   # Try direct Textract call with the local file
   from scripts.textract_utils import TextractProcessor
   processor = TextractProcessor()
   result = processor.process_pdf_sync(pdf_path)
   ```

3. **Check AWS Permissions**:
   ```bash
   aws textract detect-document-text --help
   aws s3 ls s3://samu-docs-private-upload/
   ```

### Code Improvements Needed

1. **Enhanced Error Logging in `ocr_extraction.py`**:
   - Capture specific AWS error codes
   - Log S3 upload status separately
   - Store detailed error context in `ocr_metadata_json`

2. **Add S3 Upload Verification**:
   - Confirm upload before Textract submission
   - Add retry logic for S3 operations
   - Store S3 metadata in database

3. **Improve Textract Error Handling**:
   ```python
   try:
       # S3 upload
       s3_key = upload_to_s3(file_path)
       logger.info(f"S3 upload successful: {s3_key}")
       
       # Textract submission
       job_id = submit_to_textract(s3_key)
       logger.info(f"Textract job submitted: {job_id}")
       
   except ClientError as e:
       error_code = e.response['Error']['Code']
       error_message = e.response['Error']['Message']
       logger.error(f"AWS Error {error_code}: {error_message}")
       # Store in ocr_metadata_json
   ```

4. **Add Pre-flight Checks**:
   - Validate PDF before processing
   - Check file size limits (Textract has 500MB limit)
   - Verify S3 bucket accessibility

### Database Schema Improvements
1. Add columns to `source_documents`:
   - `s3_upload_status`: Track upload separately from OCR
   - `s3_upload_timestamp`: When upload completed
   - `aws_error_code`: Specific AWS error codes
   - `preprocessing_checks`: JSON field for validation results

### Monitoring Improvements
1. **Celery Task Events**:
   - Enable task events for better tracking
   - Use Flower dashboard for real-time monitoring

2. **Processing Checkpoints**:
   - Log each micro-step (S3 upload, Textract submit, etc.)
   - Use Redis to track processing state

3. **Health Checks**:
   - Periodic S3 connectivity test
   - Textract API availability check
   - Document processing SLA monitoring

## Next Steps

1. **Manually test the failed document**:
   - Try uploading to S3 manually
   - Submit to Textract via AWS CLI
   - Check if PDF opens correctly

2. **Review AWS Configuration**:
   - Verify IAM permissions
   - Check S3 bucket policy
   - Confirm AWS region consistency

3. **Implement error handling improvements**:
   - Add detailed logging as outlined above
   - Create retry mechanism for transient failures
   - Add circuit breaker for AWS services

4. **Create integration tests**:
   - Test S3 upload independently
   - Test Textract with known-good PDFs
   - Mock AWS failures for error path testing

This analysis reveals that while the pipeline structure is sound, the error handling and logging need significant improvement to diagnose and recover from failures effectively.