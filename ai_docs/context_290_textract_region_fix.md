# Context 290: Textract Region Fix

## Issue
The S3 bucket `samu-docs-private-upload` is located in `us-east-2`, but Textract was trying to access it using `us-east-1` (the default AWS region). This caused a region mismatch error when Textract tried to access S3 objects.

## Root Cause
- S3 bucket is in `us-east-2`
- AWS_DEFAULT_REGION was set to `us-east-1` 
- Textract was using AWS_DEFAULT_REGION, causing a cross-region access issue

## Solution Implemented

### 1. Added S3_BUCKET_REGION Configuration
In `scripts/config.py`:
```python
# S3 Bucket Region Configuration
# The S3 bucket is in us-east-2, so Textract must use the same region
S3_BUCKET_REGION = os.getenv('S3_BUCKET_REGION', 'us-east-2')  # Specific region for S3 bucket operations
```

### 2. Updated Textract Initialization
Modified the following files to use S3_BUCKET_REGION:

**scripts/textract_utils.py**:
```python
class TextractProcessor:
    def __init__(self, db_manager: DatabaseManager, region_name: str = None):
        # Use S3_BUCKET_REGION for Textract to match the S3 bucket location
        if region_name is None:
            region_name = S3_BUCKET_REGION
        self.client = boto3.client('textract', region_name=region_name)
```

**scripts/textract_job_manager.py**:
```python
class TextractJobManager:
    def __init__(self, region_name: str = None):
        # Use S3_BUCKET_REGION for Textract to match the S3 bucket location
        if region_name is None:
            region_name = S3_BUCKET_REGION
        self.textract_client = boto3.client('textract', region_name=region_name)
```

**scripts/s3_storage.py**:
```python
def __init__(self):
    # Use S3_BUCKET_REGION for S3 operations to match the bucket location
    self.s3_client = boto3.client(
        's3',
        region_name=S3_BUCKET_REGION,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY
    )
```

## Benefits
1. **Consistent Region Usage**: All S3 and Textract operations now use the same region
2. **No Cross-Region Issues**: Eliminates region mismatch errors
3. **Configurable**: Can be overridden via S3_BUCKET_REGION environment variable
4. **Backward Compatible**: AWS_DEFAULT_REGION still used for other AWS services

## Testing
Created test scripts to verify:
- `scripts/test_region_fix.py`: Comprehensive test of all affected components
- `scripts/test_region_simple.py`: Simple verification of region configuration

## Configuration Options
Users can now:
1. Set `S3_BUCKET_REGION=us-east-2` in `.env` file (defaults to us-east-2)
2. Or update `AWS_DEFAULT_REGION=us-east-2` to change all AWS services to use us-east-2

## Summary
This fix ensures that Textract always uses the same AWS region as the S3 bucket, preventing region mismatch errors during OCR processing.