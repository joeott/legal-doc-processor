# Context 47: Revert to S3 Storage for Mistral OCR - Detailed Implementation Plan

## Executive Summary
Based on testing in context_46 and review of the original working implementation in context_12, we need to revert to using S3 presigned URLs for Mistral OCR. The Supabase Storage approach failed due to authentication issues (error 1901), while S3 presigned URLs were confirmed working in the original implementation.

## Root Cause Analysis
1. **Current Issue**: Mistral OCR cannot fetch files from Supabase URLs (public or signed)
2. **Error Pattern**: Consistent error 1901 "An error happened when fetching file from url"
3. **Working Solution**: S3 presigned URLs as documented in context_12_mistral_refactor_ocr.md

## Confirmed Working Method (from context_12)
```python
# S3 temporary storage approach that worked:
s3_key = f"temp_ocr/{document_uuid}/{filename}"
s3_client.upload_fileobj(file_obj, s3_bucket, s3_key)
url = s3_client.generate_presigned_url(
    'get_object',
    Params={'Bucket': s3_bucket, 'Key': s3_key},
    ExpiresIn=3600  # 1 hour expiry
)
```

## Implementation Plan

### Phase 1: Add S3 Configuration (30 minutes)
1. Update `scripts/config.py` to include S3 settings:
   ```python
   # S3 Configuration for Mistral OCR
   S3_BUCKET_TEMP = os.getenv('S3_BUCKET_TEMP', 'legal-docs-temp-ocr')
   S3_REGION = os.getenv('AWS_DEFAULT_REGION', 'us-east-1')
   AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID')
   AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')
   ```

2. Add boto3 dependency if not present:
   ```bash
   pip install boto3
   ```

### Phase 2: Implement S3 Storage Manager (45 minutes)
Create `scripts/s3_storage.py`:
```python
import boto3
import logging
from typing import Optional, Tuple
import os
from datetime import datetime
import uuid

logger = logging.getLogger(__name__)

class S3StorageManager:
    """Manages S3 operations for document storage and OCR processing"""
    
    def __init__(self, bucket_name: str, region: str = 'us-east-1'):
        self.bucket_name = bucket_name
        self.s3_client = boto3.client(
            's3',
            region_name=region,
            aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
            aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
        )
    
    def upload_for_ocr(self, file_path: str, document_uuid: str) -> str:
        """Upload file to temporary S3 location for OCR processing"""
        filename = os.path.basename(file_path)
        s3_key = f"temp_ocr/{document_uuid}/{filename}"
        
        # Upload file
        with open(file_path, 'rb') as f:
            self.s3_client.upload_fileobj(f, self.bucket_name, s3_key)
        
        logger.info(f"Uploaded {filename} to S3: {s3_key}")
        return s3_key
    
    def generate_presigned_url(self, s3_key: str, expiration: int = 3600) -> str:
        """Generate presigned URL for Mistral OCR access"""
        url = self.s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': self.bucket_name, 'Key': s3_key},
            ExpiresIn=expiration
        )
        logger.info(f"Generated presigned URL for {s3_key}")
        return url
    
    def cleanup_temp_file(self, s3_key: str) -> None:
        """Delete temporary file after OCR processing"""
        try:
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=s3_key)
            logger.info(f"Cleaned up temporary file: {s3_key}")
        except Exception as e:
            logger.warning(f"Failed to cleanup {s3_key}: {e}")
```

### Phase 3: Update OCR Extraction (30 minutes)
Modify `scripts/ocr_extraction.py`:
1. Import S3StorageManager
2. Update `extract_pdf_with_mistral_ocr()`:
   ```python
   def extract_pdf_with_mistral_ocr(file_path: str, document_uuid: str) -> Tuple[str, Dict]:
       """Extract text from PDF using Mistral OCR API with S3 storage"""
       from scripts.s3_storage import S3StorageManager
       from scripts.config import S3_BUCKET_TEMP, S3_REGION
       
       # Initialize S3 manager
       s3_manager = S3StorageManager(S3_BUCKET_TEMP, S3_REGION)
       
       # Upload to S3 and get presigned URL
       if file_path.startswith('s3://'):
           # Already in S3, just generate URL
           s3_key = file_path.replace('s3://', '').split('/', 1)[1]
           url = s3_manager.generate_presigned_url(s3_key)
       else:
           # Upload to temporary S3 location
           s3_key = s3_manager.upload_for_ocr(file_path, document_uuid)
           url = s3_manager.generate_presigned_url(s3_key)
       
       try:
           # Call Mistral OCR with presigned URL
           response = mistral_ocr_request(url, os.path.basename(file_path))
           
           # Cleanup temporary file
           if not file_path.startswith('s3://'):
               s3_manager.cleanup_temp_file(s3_key)
           
           return response['text'], response['metadata']
       except Exception as e:
           # Cleanup on error
           if not file_path.startswith('s3://'):
               s3_manager.cleanup_temp_file(s3_key)
           raise
   ```

### Phase 4: Update Storage Path Handling (20 minutes)
1. Modify `scripts/supabase_utils.py` to handle S3 URLs:
   ```python
   def generate_document_url(file_path: str, use_s3: bool = True) -> str:
       """Generate URL for document access"""
       if file_path.startswith('s3://'):
           # Handle S3 paths
           from scripts.s3_storage import S3StorageManager
           from scripts.config import S3_BUCKET_TEMP, S3_REGION
           
           s3_manager = S3StorageManager(S3_BUCKET_TEMP, S3_REGION)
           s3_key = file_path.replace('s3://', '').split('/', 1)[1]
           return s3_manager.generate_presigned_url(s3_key)
       else:
           # Fallback to Supabase (for non-OCR uses)
           return existing_supabase_logic(file_path)
   ```

### Phase 5: Frontend Updates (Optional - 45 minutes)
If we want to upload directly to S3:
1. Add AWS SDK to frontend
2. Create presigned POST endpoint
3. Update `upload.js` to use S3 multipart upload
4. Store S3 keys in database instead of Supabase paths

**Note**: This phase is optional. We can continue using Supabase for initial upload and copy to S3 only for OCR processing.

### Phase 6: Testing Plan (30 minutes)
1. **Unit Tests**:
   - Test S3StorageManager upload/download/cleanup
   - Test presigned URL generation
   - Test OCR with S3 URLs

2. **Integration Tests**:
   - Upload document → S3 → Mistral OCR → Cleanup
   - Error handling and cleanup on failure
   - Queue processing with S3 storage

3. **Manual Testing**:
   - Process existing documents in queue
   - Verify Mistral OCR success with S3 URLs
   - Check temporary file cleanup

## Migration Strategy
1. **Backward Compatibility**: Support both Supabase and S3 URLs
2. **Gradual Migration**: New uploads use S3, existing continue with Supabase
3. **Data Migration**: Optional script to migrate existing files to S3

## Environment Variables Required
```bash
# S3 Configuration
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
S3_BUCKET_TEMP=legal-docs-temp-ocr
AWS_DEFAULT_REGION=us-east-1
```

## Risk Mitigation
1. **Fallback**: Keep Supabase URLs as fallback option
2. **Monitoring**: Log all S3 operations for debugging
3. **Cleanup**: Ensure temporary files are always deleted
4. **Security**: Use IAM roles with minimal permissions

## Timeline Estimate
- Total implementation: ~3 hours
- Testing and debugging: ~1-2 hours
- Full deployment: ~5 hours total

## Success Criteria
1. Mistral OCR successfully processes documents via S3 URLs
2. No error 1901 from Mistral API
3. Temporary files cleaned up after processing
4. Queue processing completes successfully
5. All tests pass