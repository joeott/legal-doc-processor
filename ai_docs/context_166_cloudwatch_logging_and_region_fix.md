# Context Update 166: CloudWatch Logging Integration and AWS Region Fix

## Date: 2025-05-28

## Summary
This update documents the implementation of CloudWatch logging for Textract operations and the critical fix for AWS region misconfiguration that was causing S3 access errors.

## Issues Addressed

### 1. AWS Region Misconfiguration
- **Problem**: S3 bucket `samu-docs-private-upload` is in `us-east-2`, but system was using `us-east-1`
- **Impact**: Textract jobs failing with "Unable to get object metadata from S3" errors
- **Root Cause**: `.env` file had `AWS_DEFAULT_REGION=us-east-1`

### 2. Insufficient Logging for Textract Operations
- **Problem**: Limited visibility into Textract API calls and job failures
- **Impact**: Difficult to diagnose issues with document processing
- **Solution**: Implemented CloudWatch logging integration

## Changes Implemented

### 1. AWS Region Configuration Fix

Updated `.env` file:
```bash
# Before
AWS_REGION=us-east-1
AWS_DEFAULT_REGION=us-east-1

# After
AWS_REGION=us-east-2
AWS_DEFAULT_REGION=us-east-2
```

### 2. CloudWatch Log Group Configuration

Created CloudWatch log group using AWS CLI:
```bash
# Create log group
aws logs create-log-group \
  --log-group-name /aws/textract/document-processing \
  --region us-east-2

# Set retention policy (30 days)
aws logs put-retention-policy \
  --log-group-name /aws/textract/document-processing \
  --retention-in-days 30 \
  --region us-east-2
```

**CloudWatch Log Group Details:**
- **Name**: `/aws/textract/document-processing`
- **Region**: `us-east-2`
- **Retention**: 30 days
- **Purpose**: Centralized logging for all Textract operations

### 3. CloudWatch Logger Implementation

Created `scripts/cloudwatch_logger.py`:
- Structured JSON logging format for better searchability
- Log levels: DEBUG, INFO, WARN, ERROR
- Event types: `job_started`, `job_start_failed`, `api_call`, `processing_metrics`
- Automatic log stream creation with timestamp
- Sequence token management for reliable log delivery
- Parameter sanitization to remove sensitive data

Key features:
```python
# Log Textract events with structured data
log_textract_event(event_type, document_uuid, job_id, metadata, error, level)

# Log API calls with request/response
log_api_call(api_method, request_params, response, error)

# Log processing metrics
log_processing_metrics(document_uuid, metrics)
```

### 4. Textract Utils Integration

Updated `scripts/textract_utils.py`:
- Added CloudWatch logger integration
- Log all Textract API calls
- Log job start success/failure events
- Include metadata: S3 locations, job IDs, error codes

### 5. Monitor Enhancement

Updated `scripts/cli/monitor.py`:
- Use S3 URI when document has `s3_key` field
- Construct proper S3 URI: `s3://bucket/key`
- Pass S3 URI to OCR tasks instead of local paths

## Technical Details

### CloudWatch Log Format
```json
{
  "timestamp": "2025-05-28T15:24:45.123Z",
  "level": "INFO",
  "event_type": "job_started",
  "document_uuid": "1d4282be-6a1a-4c03-829d-8dfdce34828a",
  "job_id": "abc123...",
  "service": "textract",
  "region": "us-east-2",
  "metadata": {
    "s3_bucket": "samu-docs-private-upload",
    "s3_key": "documents/1d4282be-6a1a-4c03-829d-8dfdce34828a.pdf",
    "source_doc_id": 1461
  }
}
```

### IAM Permissions Required

For CloudWatch logging to work, ensure the execution role has:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": "arn:aws:logs:us-east-2:*:log-group:/aws/textract/*"
    }
  ]
}
```

## Monitoring and Analysis

### CloudWatch Insights Queries

1. **Find all Textract errors**:
```
fields @timestamp, document_uuid, error, metadata.error_code
| filter event_type = "job_start_failed"
| sort @timestamp desc
```

2. **Track job duration**:
```
fields @timestamp, document_uuid, job_id, event_type
| filter event_type in ["job_started", "job_completed"]
| stats count() by document_uuid
```

3. **API call analysis**:
```
fields @timestamp, api_method, request_params.DocumentLocation.S3Object.Key
| filter event_type = "api_call"
| stats count() by api_method
```

## Verification Steps

1. **Check AWS region**:
```bash
echo $AWS_DEFAULT_REGION  # Should show: us-east-2
aws s3api get-bucket-location --bucket samu-docs-private-upload
# Should return: {"LocationConstraint": "us-east-2"}
```

2. **Verify CloudWatch log group**:
```bash
aws logs describe-log-groups \
  --log-group-name-prefix /aws/textract \
  --region us-east-2
```

3. **Test document processing**:
```bash
# Retry document with proper S3 path
python scripts/cli/monitor.py control retry <document_uuid>
python scripts/cli/monitor.py control start <document_uuid>
```

## Benefits

1. **Enhanced Debugging**: Full visibility into Textract API interactions
2. **Performance Monitoring**: Track processing times and bottlenecks
3. **Error Analysis**: Structured error data for pattern identification
4. **Audit Trail**: Complete record of all document processing attempts
5. **Cost Optimization**: Monitor API usage and optimize retry strategies

## Next Steps

1. **Enable CloudWatch Alarms**: Set up alerts for high error rates
2. **Create Dashboard**: Visualize processing metrics
3. **Implement Distributed Tracing**: Add X-Ray integration
4. **Log Aggregation**: Consider streaming to OpenSearch for advanced analytics

## Related Files
- `/scripts/cloudwatch_logger.py` - CloudWatch logging implementation
- `/scripts/textract_utils.py` - Updated with logging integration
- `/scripts/cli/monitor.py` - Fixed to use S3 URIs
- `/.env` - Updated AWS region configuration

## Notes
- CloudWatch logs will incur AWS charges based on data ingestion and retention
- Consider implementing log sampling for high-volume processing
- The CloudWatch logger gracefully degrades if initialization fails
- All sensitive parameters (tokens, ARNs) are sanitized before logging