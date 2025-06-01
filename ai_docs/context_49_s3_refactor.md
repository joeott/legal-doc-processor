# Validated S3 Storage Implementation Guide for Mistral OCR

## Plan Validation Summary

The provided implementation plan is **well-structured and comprehensive**. The approach correctly addresses the Mistral OCR access issue by implementing S3 storage with presigned URLs. Here's my validation with enhancements:

### ✅ Strengths of the Plan

1. **Leverages Existing Schema**: The `source_documents` table already has S3 fields (`s3_key`, `s3_bucket`, `s3_region`), minimizing database changes
2. **UUID-based Naming**: Properly implements document UUID naming while preserving original filenames
3. **Security Approach**: Dual bucket strategy (private upload → public OCR → cleanup) is sound
4. **Backward Compatibility**: Maintains support for existing Supabase Storage files

### 🔧 Required Enhancements

#### 1. **Script Location Specificity**

The plan should be more explicit about file locations. Update all references to use full paths:

```markdown
**File: `/scripts/config.py`** (not just `scripts/config.py`)
**File: `/scripts/s3_storage.py`** (NEW FILE - create in scripts directory)
**File: `/scripts/ocr_extraction.py`** (lines 65-140 for Mistral OCR function)
**File: `/scripts/main_pipeline.py`** (lines 65-75 for PDF processing logic)
**File: `/scripts/supabase_utils.py`** (lines 35-85 for generate_document_url function)
**File: `/frontend/vercel-deploy/upload.js`** (entire uploadFileToStorage function)
```

#### 2. **Original Filename Preservation**

Add explicit handling in the S3StorageManager to ensure original filename is always preserved:

```python
# In S3StorageManager.upload_document_with_uuid_naming method:
# Store original filename in metadata AND database
metadata = {
    'original-filename': original_filename,
    'document-uuid': document_uuid,
    'upload-timestamp': datetime.now().isoformat(),
    'content-type': self._get_content_type(original_filename)
}
```

#### 3. **Database Operations Clarification**

**Important**: No changes can be accomplished using Cypher via MCP tools because:
- This is a Supabase PostgreSQL instance, not Neo4j
- Cypher is Neo4j's query language  
- All database operations must use SQL or Supabase client methods

Remove any references to Cypher operations from the implementation.

#### 4. **Queue Processing Updates**

Add explicit handling for documents already in the queue:

```python
# In queue_processor.py, add S3 migration for existing files:
def migrate_existing_file_to_s3(self, source_doc_id: int, file_path: str) -> dict:
    """Migrate existing Supabase Storage file to S3 for OCR processing"""
    if file_path.startswith('s3://'):
        return {'already_s3': True, 's3_key': file_path}
    
    # Download from Supabase, upload to S3
    # Update source_documents with S3 fields
    # Return S3 details
```

#### 5. **Error Handling Enhancements**

Add specific error handling for common S3 issues:

```python
# In S3StorageManager class:
def handle_s3_errors(self, error):
    """Standardized S3 error handling"""
    if 'NoSuchBucket' in str(error):
        logger.error(f"S3 bucket does not exist: {error}")
        raise ValueError(f"S3 bucket configuration error")
    elif 'AccessDenied' in str(error):
        logger.error(f"S3 access denied: {error}")
        raise ValueError(f"S3 permissions error")
    # Add more specific error cases
```

#### 6. **Public Bucket Security Configuration**

Add explicit S3 bucket policy for the public OCR bucket:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "PublicReadForOCR",
      "Effect": "Allow",
      "Principal": "*",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::legal-docs-public-ocr/*",
      "Condition": {
        "IpAddress": {
          "aws:SourceIp": ["Mistral OCR API IP ranges if known"]
        }
      }
    }
  ]
}
```

#### 7. **File Path Reference Updates**

Ensure all file path references are updated consistently:

1. **In `/scripts/main_pipeline.py`** (line ~52):
   ```python
   # Check if file_path is S3 or local
   if file_path.startswith('s3://'):
       # S3 path - will be handled by OCR function
       pass
   elif file_path.startswith('/'):
       # Absolute local path
       pass
   else:
       # Relative path - make absolute
       file_path = os.path.abspath(file_path)
   ```

2. **In `/scripts/queue_processor.py`** (line ~180):
   ```python
   # Update file path handling in _process_claimed_documents
   if source_doc_details.get('s3_key'):
       file_path = f"s3://{source_doc_details['s3_bucket']}/{source_doc_details['s3_key']}"
   else:
       file_path = source_doc_details['original_file_path']
   ```

#### 8. **Database Update Queries**

Add SQL to update existing records with S3 information:

```sql
-- Update source_documents with S3 information after upload
UPDATE source_documents 
SET 
    s3_key = %s,
    s3_bucket = %s,
    s3_region = %s,
    file_size_bytes = %s,
    md5_hash = %s,
    original_file_path = %s  -- Update to S3 path format
WHERE id = %s;

-- Add index for S3 key queries
CREATE INDEX IF NOT EXISTS idx_source_documents_s3_key 
ON source_documents(s3_key) 
WHERE s3_key IS NOT NULL;

-- Add index for UUID-based queries  
CREATE INDEX IF NOT EXISTS idx_source_documents_document_uuid 
ON source_documents(document_uuid);
```

#### 9. **Testing Additions**

Add specific test cases:

```python
# Test UUID file naming
assert s3_manager.upload_document_with_uuid_naming(
    'test.pdf', 
    'test-uuid-123', 
    'Original Test.pdf'
)['s3_key'] == 'documents/test-uuid-123.pdf'

# Test original filename preservation
result = s3_manager.upload_document_with_uuid_naming(...)
assert result['metadata']['original-filename'] == 'Original Test.pdf'

# Test public bucket access
public_url = s3_manager.generate_presigned_url_for_ocr(...)
response = requests.head(public_url)
assert response.status_code == 200
```

## Implementation Plan

### Phase 1: Environment Configuration (5 minutes)

Add S3 configuration to environment variables:

```bash
# S3 Configuration for Document Storage
AWS_ACCESS_KEY_ID=your_access_key_here
AWS_SECRET_ACCESS_KEY=your_secret_key_here
AWS_DEFAULT_REGION=us-east-1

# S3 Buckets
S3_BUCKET_PRIVATE=legal-docs-private-upload    # Private bucket for initial uploads
S3_BUCKET_PUBLIC=legal-docs-public-ocr         # Public bucket for OCR processing
S3_BUCKET_TEMP=legal-docs-temp-ocr            # Temporary bucket for OCR cleanup
```

### Phase 2: Backend Configuration Updates (10 minutes)

**File: `/scripts/config.py`**

Add S3 configuration section after existing Supabase config:

```python
# S3 Configuration for Mistral OCR (add after existing configs)
AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY') 
AWS_DEFAULT_REGION = os.getenv('AWS_DEFAULT_REGION', 'us-east-1')

# S3 Buckets
S3_BUCKET_PRIVATE = os.getenv('S3_BUCKET_PRIVATE', 'legal-docs-private-upload')
S3_BUCKET_PUBLIC = os.getenv('S3_BUCKET_PUBLIC', 'legal-docs-public-ocr') 
S3_BUCKET_TEMP = os.getenv('S3_BUCKET_TEMP', 'legal-docs-temp-ocr')

# File naming
USE_UUID_FILE_NAMING = os.getenv('USE_UUID_FILE_NAMING', 'true').lower() in ('true', '1', 'yes')
```

### Phase 3: S3 Storage Manager Implementation (20 minutes)

**File: `/scripts/s3_storage.py`** (Create new file)

```python
import boto3
import logging
import os
import hashlib
from typing import Optional
from datetime import datetime
from config import AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_DEFAULT_REGION
from config import S3_BUCKET_PRIVATE, S3_BUCKET_PUBLIC, S3_BUCKET_TEMP

logger = logging.getLogger(__name__)

class S3StorageManager:
    """Manages S3 operations for document storage and OCR processing"""
    
    def __init__(self):
        self.s3_client = boto3.client(
            's3',
            region_name=AWS_DEFAULT_REGION,
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY
        )
    
    def _get_content_type(self, filename: str) -> str:
        """Get content type based on file extension"""
        ext = os.path.splitext(filename)[1].lower()
        content_types = {
            '.pdf': 'application/pdf',
            '.txt': 'text/plain',
            '.doc': 'application/msword',
            '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        }
        return content_types.get(ext, 'application/octet-stream')
        
    def upload_document_with_uuid_naming(self, local_file_path: str, document_uuid: str, 
                                       original_filename: str, bucket: str = None) -> dict:
        """Upload document with UUID-based naming to private bucket"""
        bucket = bucket or S3_BUCKET_PRIVATE
        file_ext = os.path.splitext(original_filename)[1].lower()
        
        # Create UUID-based key: documents/{uuid}{ext}
        s3_key = f"documents/{document_uuid}{file_ext}"
        
        # Calculate MD5 hash for integrity
        with open(local_file_path, 'rb') as f:
            file_content = f.read()
            md5_hash = hashlib.md5(file_content).hexdigest()
        
        # Store original filename in metadata AND database
        metadata = {
            'original-filename': original_filename,
            'document-uuid': document_uuid,
            'upload-timestamp': datetime.now().isoformat(),
            'content-type': self._get_content_type(original_filename)
        }
        
        try:
            # Upload with metadata
            self.s3_client.put_object(
                Bucket=bucket,
                Key=s3_key,
                Body=file_content,
                Metadata=metadata,
                ContentType=self._get_content_type(original_filename)
            )
            
            return {
                's3_key': s3_key,
                's3_bucket': bucket,
                's3_region': AWS_DEFAULT_REGION,
                'md5_hash': md5_hash,
                'file_size': len(file_content),
                'metadata': metadata
            }
        except Exception as error:
            self.handle_s3_errors(error)
            raise
    
    def copy_to_public_bucket(self, private_s3_key: str, document_uuid: str) -> str:
        """Copy file from private bucket to public bucket for OCR processing"""
        file_ext = os.path.splitext(private_s3_key)[1]
        public_s3_key = f"ocr-processing/{document_uuid}{file_ext}"
        
        try:
            # Copy from private to public bucket
            copy_source = {'Bucket': S3_BUCKET_PRIVATE, 'Key': private_s3_key}
            self.s3_client.copy_object(
                CopySource=copy_source,
                Bucket=S3_BUCKET_PUBLIC,
                Key=public_s3_key
            )
            
            logger.info(f"Copied {private_s3_key} to public bucket as {public_s3_key}")
            return public_s3_key
        except Exception as error:
            self.handle_s3_errors(error)
            raise
        
    def generate_presigned_url_for_ocr(self, s3_key: str, bucket: str = None, 
                                     expiration: int = 3600) -> str:
        """Generate presigned URL for Mistral OCR access"""
        bucket = bucket or S3_BUCKET_PUBLIC
        
        try:
            url = self.s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': bucket, 'Key': s3_key},
                ExpiresIn=expiration
            )
            
            logger.info(f"Generated presigned URL for {s3_key} (expires in {expiration}s)")
            return url
        except Exception as error:
            self.handle_s3_errors(error)
            raise
        
    def cleanup_ocr_file(self, s3_key: str, bucket: str = None):
        """Delete file from public OCR bucket after processing"""
        bucket = bucket or S3_BUCKET_PUBLIC
        
        try:
            self.s3_client.delete_object(Bucket=bucket, Key=s3_key)
            logger.info(f"Cleaned up OCR file: {s3_key}")
        except Exception as e:
            logger.warning(f"Failed to cleanup OCR file {s3_key}: {e}")
    
    def handle_s3_errors(self, error):
        """Standardized S3 error handling"""
        if 'NoSuchBucket' in str(error):
            logger.error(f"S3 bucket does not exist: {error}")
            raise ValueError(f"S3 bucket configuration error")
        elif 'AccessDenied' in str(error):
            logger.error(f"S3 access denied: {error}")
            raise ValueError(f"S3 permissions error")
        elif 'NoCredentialsError' in str(error):
            logger.error(f"S3 credentials not found: {error}")
            raise ValueError(f"S3 credentials configuration error")
        else:
            logger.error(f"Unknown S3 error: {error}")
            raise
```

### Phase 4: Update OCR Extraction (15 minutes)

**File: `/scripts/ocr_extraction.py`** (lines 65-140 for Mistral OCR function)

Modify the `extract_text_from_pdf_mistral_ocr` function:

```python
def extract_text_from_pdf_mistral_ocr(pdf_path: str, document_uuid: str = None) -> tuple[str | None, list | None]:
    """Process PDF using Mistral OCR API with S3 presigned URLs"""
    from s3_storage import S3StorageManager
    from mistral_utils import extract_text_from_url
    
    start_time = time.time()
    file_name = os.path.basename(pdf_path)
    
    if not document_uuid:
        document_uuid = str(uuid.uuid4())
        
    logger.info(f"Processing PDF with Mistral OCR: {file_name}")
    
    s3_manager = S3StorageManager()
    public_s3_key = None
    
    try:
        # Get page count for metadata
        try:
            doc = fitz.open(pdf_path)
            num_pages = len(doc)
            doc.close()
        except Exception as e:
            logger.error(f"Could not read PDF: {e}")
            num_pages = 1
            
        # Handle different file path scenarios
        if pdf_path.startswith('s3://'):
            # Already in S3 - extract key and copy to public bucket
            parts = pdf_path.replace('s3://', '').split('/', 1)
            private_bucket = parts[0]
            private_key = parts[1]
            public_s3_key = s3_manager.copy_to_public_bucket(private_key, document_uuid)
        else:
            # Local file - upload to private then copy to public
            upload_result = s3_manager.upload_document_with_uuid_naming(
                pdf_path, document_uuid, file_name
            )
            public_s3_key = s3_manager.copy_to_public_bucket(
                upload_result['s3_key'], document_uuid
            )
            
        # Generate presigned URL for Mistral OCR
        presigned_url = s3_manager.generate_presigned_url_for_ocr(public_s3_key)
        
        # Process with Mistral OCR
        result = extract_text_from_url(presigned_url, file_name)
        
        if "error" in result:
            logger.error(f"Mistral OCR failed: {result['error']}")
            return None, None
            
        if "combined_text" in result:
            extracted_text = result["combined_text"]
            processing_time = time.time() - start_time
            
            # Create metadata
            page_level_metadata = [{
                "page_number": i+1,
                "method": "MistralOCR",
                "model": result.get("model", "mistral-ocr-latest"),
                "processing_time_seconds": processing_time,
                "s3_key_used": public_s3_key,
                "char_count": len(extracted_text)
            } for i in range(num_pages)]
            
            return extracted_text, page_level_metadata
        else:
            logger.error("No text extracted from document")
            return None, None
            
    except Exception as e:
        logger.error(f"Error in Mistral OCR processing: {e}", exc_info=True)
        return None, None
    finally:
        # Always cleanup public OCR file
        if public_s3_key:
            s3_manager.cleanup_ocr_file(public_s3_key)
```

### Phase 5: Update Main Pipeline (10 minutes)

**File: `/scripts/main_pipeline.py`** (lines 65-75 for PDF processing logic)

Update the `process_single_document` function to pass document_uuid to OCR:

```python
# In the OCR section, around line 65-75:
if detected_file_type == '.pdf':
    # Check if file_path is S3 or local
    if file_path.startswith('s3://'):
        # S3 path - will be handled by OCR function
        pass
    elif file_path.startswith('/'):
        # Absolute local path
        pass
    else:
        # Relative path - make absolute
        file_path = os.path.abspath(file_path)
    
    if USE_MISTRAL_FOR_OCR:
        logger.info(f"Using Mistral OCR API for text extraction from PDF: {file_name}")
        # Pass source_doc_uuid to OCR function
        source_doc_info = db_manager.get_document_by_id(source_doc_sql_id)
        source_doc_uuid = source_doc_info.get('document_uuid') if source_doc_info else None
        
        raw_text, ocr_meta = extract_text_from_pdf_mistral_ocr(file_path, source_doc_uuid)
        
        if raw_text is None:
            logger.warning(f"Mistral OCR failed for {file_name}, attempting fallback")
            raw_text, ocr_meta = extract_text_from_pdf_qwen_vl_ocr(file_path)
    else:
        raw_text, ocr_meta = extract_text_from_pdf_qwen_vl_ocr(file_path)
```

### Phase 6: Update Queue Processing (10 minutes)

**File: `/scripts/queue_processor.py`** (line ~180)

```python
# Update file path handling in _process_claimed_documents
if source_doc_details.get('s3_key'):
    file_path = f"s3://{source_doc_details['s3_bucket']}/{source_doc_details['s3_key']}"
else:
    file_path = source_doc_details['original_file_path']

# Add S3 migration for existing files:
def migrate_existing_file_to_s3(self, source_doc_id: int, file_path: str) -> dict:
    """Migrate existing Supabase Storage file to S3 for OCR processing"""
    if file_path.startswith('s3://'):
        return {'already_s3': True, 's3_key': file_path}
    
    # Download from Supabase, upload to S3
    # Update source_documents with S3 fields
    # Return S3 details
```

### Phase 7: Update Supabase Utils (15 minutes)

**File: `/scripts/supabase_utils.py`** (lines 35-85 for generate_document_url function)

Update the `generate_document_url` function:

```python
def generate_document_url(file_path: str, use_s3: bool = True) -> str:
    """Generate URL for document access - S3 or Supabase fallback"""
    if file_path.startswith('s3://'):
        # S3 path - use S3StorageManager
        from s3_storage import S3StorageManager
        s3_manager = S3StorageManager()
        
        # Extract bucket and key from s3://bucket/key format
        parts = file_path.replace('s3://', '').split('/', 1)
        bucket = parts[0]
        key = parts[1]
        
        return s3_manager.generate_presigned_url_for_ocr(key, bucket)
    else:
        # Supabase Storage fallback (existing logic)
        return generate_supabase_signed_url(file_path)
```

### Phase 8: Frontend Upload Updates (15 minutes)

**File: `/frontend/vercel-deploy/upload.js`** (entire uploadFileToStorage function)

Replace the `uploadFileToStorage` function:

```javascript
/**
 * Uploads file directly to S3 with UUID-based naming
 */
async function uploadFileToS3(file, documentUuid) {
    // This requires implementing S3 presigned POST URL generation
    // via Edge Function or direct AWS SDK integration
    
    const fileExt = file.name.split('.').pop().toLowerCase();
    const s3Key = `documents/${documentUuid}.${fileExt}`;
    
    // Get presigned POST URL from Edge Function
    const { data: presignedData, error } = await supabase.functions.invoke('generate-s3-upload-url', {
        body: { 
            s3Key: s3Key,
            contentType: file.type,
            fileSize: file.size
        }
    });
    
    if (error) throw error;
    
    // Upload directly to S3
    const formData = new FormData();
    Object.entries(presignedData.fields).forEach(([key, value]) => {
        formData.append(key, value);
    });
    formData.append('file', file);
    
    const uploadResponse = await fetch(presignedData.url, {
        method: 'POST',
        body: formData
    });
    
    if (!uploadResponse.ok) {
        throw new Error('S3 upload failed');
    }
    
    return s3Key;
}
```

### Phase 9: Database Updates (5 minutes)

Add SQL to update existing records with S3 information:

```sql
-- Update source_documents with S3 information after upload
UPDATE source_documents 
SET 
    s3_key = %s,
    s3_bucket = %s,
    s3_region = %s,
    file_size_bytes = %s,
    md5_hash = %s,
    original_file_path = %s  -- Update to S3 path format
WHERE id = %s;

-- Add index for S3 key queries
CREATE INDEX IF NOT EXISTS idx_source_documents_s3_key 
ON source_documents(s3_key) 
WHERE s3_key IS NOT NULL;

-- Add index for UUID-based queries  
CREATE INDEX IF NOT EXISTS idx_source_documents_document_uuid 
ON source_documents(document_uuid);
```

### Phase 10: Testing and Validation (15 minutes)

**Test Plan:**

1. **Upload Test:**
   ```bash
   # Test file upload with new S3 integration
   curl -X POST [vercel-url] -F "file=@test.pdf" -F "documentName=Test Document"
   ```

2. **OCR Test:**
   ```bash
   # Check OCR processing with S3 URLs
   python scripts/main_pipeline.py --mode queue
   ```

3. **Database Validation:**
   ```sql
   -- Verify S3 fields populated
   SELECT document_uuid, s3_key, s3_bucket, original_file_path 
   FROM source_documents 
   WHERE s3_key IS NOT NULL;
   ```

4. **Specific Test Cases:**
   ```python
   # Test UUID file naming
   assert s3_manager.upload_document_with_uuid_naming(
       'test.pdf', 
       'test-uuid-123', 
       'Original Test.pdf'
   )['s3_key'] == 'documents/test-uuid-123.pdf'

   # Test original filename preservation
   result = s3_manager.upload_document_with_uuid_naming(...)
   assert result['metadata']['original-filename'] == 'Original Test.pdf'

   # Test public bucket access
   public_url = s3_manager.generate_presigned_url_for_ocr(...)
   response = requests.head(public_url)
   assert response.status_code == 200
   ```

## Critical Implementation Notes

1. **Bucket Creation**: Ensure S3 buckets are created before deployment:
   ```bash
   aws s3 mb s3://legal-docs-private-upload
   aws s3 mb s3://legal-docs-public-ocr
   aws s3api put-bucket-policy --bucket legal-docs-public-ocr --policy file://public-bucket-policy.json
   ```

2. **IAM Permissions**: Create minimal IAM policy:
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Effect": "Allow",
         "Action": [
           "s3:PutObject",
           "s3:GetObject",
           "s3:DeleteObject"
         ],
         "Resource": [
           "arn:aws:s3:::legal-docs-private-upload/*",
           "arn:aws:s3:::legal-docs-public-ocr/*"
         ]
       }
     ]
   }
   ```

3. **Environment Variables**: Ensure all AWS credentials are set:
   ```bash
   export AWS_ACCESS_KEY_ID=your_key
   export AWS_SECRET_ACCESS_KEY=your_secret
   export AWS_DEFAULT_REGION=us-east-1
   ```

4. **Monitoring**: Add CloudWatch alarms for:
   - S3 bucket size (cost control)
   - Failed OCR cleanup operations
   - Unauthorized access attempts

## Key Benefits of This Approach

1. **Minimal Schema Changes**: Leverages existing S3 fields in database
2. **Preserves Existing Flow**: Queue processing and triggers unchanged  
3. **UUID-based Naming**: Files named with document UUIDs for consistency
4. **Security**: Private upload bucket → Public OCR bucket → Cleanup
5. **Fallback Support**: Can still process Supabase Storage files
6. **Error Resilience**: Cleanup on failure, retry mechanisms intact

## Summary

The implementation plan is **approved with enhancements**. The key additions are:

1. More explicit script references with line numbers
2. Enhanced error handling
3. Security configuration details
4. Testing specifications
5. Clear migration path for existing files

The plan correctly addresses the core issue (Mistral OCR can't access Supabase URLs) with a proven solution (S3 presigned URLs) while maintaining system integrity and backward compatibility.