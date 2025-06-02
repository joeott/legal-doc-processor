# Context 301: Textract Endpoints and Pipeline Fix Implementation

## AWS Textract Endpoints for us-east-2

### Standard Endpoints
- **API Endpoint**: `textract.us-east-2.amazonaws.com`
- **FIPS Endpoint**: `textract-fips.us-east-2.amazonaws.com`
- **Service Name**: `com.amazonaws.us-east-2.textract`

### VPC Endpoints (if using private connectivity)
- **Interface Endpoint**: `com.amazonaws.vpce.us-east-2.vpce-svc-[id]`
- **Service DNS**: `textract.us-east-2.vpce.amazonaws.com`

## Current Endpoint Usage Analysis

Checking our current implementation:

1. **In textract_job_manager.py**:
   ```python
   self.textract_client = boto3.client('textract', region_name=region_name)
   ```
   This uses the default endpoint, which should automatically resolve to `textract.us-east-2.amazonaws.com` when region is set to 'us-east-2'.

2. **Region Configuration**:
   - S3_BUCKET_REGION = 'us-east-2' ✓
   - Textract client uses S3_BUCKET_REGION ✓
   - This is correct for same-region access

## Identified Issues and Solutions

### Issue 1: Celery Workers Missing AWS Credentials
**Root Cause**: Environment variables not propagated to Celery worker processes
**Impact**: "Failed to start Textract job" error

### Issue 2: Potential Endpoint Mismatch
**Root Cause**: AWS_DEFAULT_REGION might override S3_BUCKET_REGION
**Impact**: Cross-region API calls may fail

### Issue 3: IAM Permissions
**Root Cause**: Textract needs specific S3 bucket permissions
**Impact**: Access denied errors even with valid credentials

## Implementation Plan

### Step 1: Fix Celery Worker Environment
### Step 2: Verify Textract Endpoint Configuration  
### Step 3: Test and Monitor Pipeline Completion
### Step 4: Achieve Success Criteria