Okay, here's a detailed markdown guide for implementing the AWS Textract refactor. This guide is designed to be comprehensive for an agentic coding tool.

```markdown
# AWS Textract Refactor Implementation Guide

## 1. Configuration Changes (`config.py`)

### 1.1. Remove Mistral OCR Configuration
**Action:** Delete all environment variables and Python constants related to Mistral OCR.
**Lines to Remove/Modify (approximate based on provided `config.py`):**
- `MISTRAL_API_KEY` (Lines 132-137 or similar)
- `USE_MISTRAL_FOR_OCR`
- `MISTRAL_OCR_MODEL`
- `MISTRAL_OCR_PROMPT`
- `MISTRAL_OCR_TIMEOUT`
- Any related validation checks for `MISTRAL_API_KEY` in `validate_cloud_services()` or `StageConfig`.

**Example (Illustrative):**
```python
# Before
# Mistral OCR Configuration
# MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
# USE_MISTRAL_FOR_OCR = os.getenv("USE_MISTRAL_FOR_OCR", "true").lower() in ("true", "1", "yes")
# ...

# After
# (Mistral OCR Configuration section completely removed)
```

### 1.2. Simplify S3 Bucket Configuration
**Action:** Modify S3 configuration to reflect the use of a single private bucket for documents. Remove configurations for public and temporary OCR buckets.
**Lines to Modify/Remove (approximate):**
- `S3_BUCKET_PUBLIC` (Line 124 or similar)
- `S3_BUCKET_TEMP` (Line 125 or similar)
- Update any logic that uses these constants. `S3_BUCKET_NAME` (Line 118) should now represent the primary private document bucket (e.g., `samu-docs-private-upload`). Rename if necessary for clarity, e.g., `S3_PRIVATE_BUCKET_NAME`. For this guide, we'll assume `S3_BUCKET_NAME` is repurposed or a new `S3_PRIMARY_DOCUMENT_BUCKET` is defined.

**Example (Illustrative - assuming `S3_BUCKET_NAME` is now the primary private bucket):**
```python
# Before
# S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME", "legal-docs-bucket") # Generic
# S3_BUCKET_PRIVATE = os.getenv('S3_BUCKET_PRIVATE', 'samu-docs-private-upload')
# S3_BUCKET_PUBLIC = os.getenv('S3_BUCKET_PUBLIC', 'samu-docs-public-ocr')
# S3_BUCKET_TEMP = os.getenv('S3_BUCKET_TEMP', 'samu-docs-temp-ocr')

# After
# S3 Configuration
USE_S3_FOR_INPUT = os.getenv("USE_S3_FOR_INPUT", "false").lower() in ("true", "1", "yes")
# S3_BUCKET_NAME should be the primary private bucket for documents.
S3_PRIMARY_DOCUMENT_BUCKET = os.getenv("S3_PRIMARY_DOCUMENT_BUCKET", "samu-docs-private-upload") # More specific
S3_TEMP_DOWNLOAD_DIR = os.getenv("S3_TEMP_DOWNLOAD_DIR", str(BASE_DIR / "s3_downloads")) # Still needed for local processing if files are downloaded

# AWS Configuration (ensure these are present if not already)
AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')
AWS_DEFAULT_REGION = os.getenv('AWS_DEFAULT_REGION', 'us-east-1') # Example, use your target region
```
**Note:** Retain `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and `AWS_DEFAULT_REGION` as these are needed for `boto3` and Textract.

### 1.3. Add AWS Textract Configuration
**Action:** Add new configuration variables for AWS Textract as specified in the "Configuration Requirements - Complete Settings" section of the problem description.
**Location:** Add a new section in `config.py` for Textract settings.

```python
# config.py
# ... other imports and configurations ...

# AWS Textract Configuration
# Ensure AWS_DEFAULT_REGION is defined, as it's used by Textract client
# AWS_REGION = AWS_DEFAULT_REGION # If AWS_DEFAULT_REGION is already globally defined

# Feature selection for Textract AnalyzeDocument (comma-separated list: TABLES, FORMS, QUERIES, SIGNATURES, LAYOUT)
# For DetectDocumentText (basic OCR), this is not directly used but good to have for future AnalyzeDocument use.
TEXTRACT_ANALYZE_FEATURE_TYPES = os.getenv('TEXTRACT_ANALYZE_FEATURE_TYPES', 'TABLES,FORMS').split(',') # Example for AnalyzeDocument

# Confidence threshold for accepting extracted text/elements (0-100)
TEXTRACT_CONFIDENCE_THRESHOLD = float(os.getenv('TEXTRACT_CONFIDENCE_THRESHOLD', '80.0'))

# For pagination if directly getting results (max results per GetDocumentTextDetection call)
TEXTRACT_MAX_RESULTS_PER_PAGE = int(os.getenv('TEXTRACT_MAX_RESULTS_PER_PAGE', '1000'))

# Determines if StartDocumentTextDetection (async) or DetectDocumentText (sync) is preferred for PDFs.
# Async is generally recommended for multi-page PDFs.
TEXTRACT_USE_ASYNC_FOR_PDF = os.getenv('TEXTRACT_USE_ASYNC_FOR_PDF', 'true').lower() in ('true', '1', 'yes')

# Async job polling configuration
TEXTRACT_ASYNC_MAX_POLLING_TIME_SECONDS = int(os.getenv('TEXTRACT_ASYNC_MAX_POLLING_TIME_SECONDS', '600'))  # 10 minutes
TEXTRACT_ASYNC_POLLING_INTERVAL_SECONDS = int(os.getenv('TEXTRACT_ASYNC_POLLING_INTERVAL_SECONDS', '5'))   # 5 seconds
TEXTRACT_ASYNC_INITIAL_DELAY_SECONDS = int(os.getenv('TEXTRACT_ASYNC_INITIAL_DELAY_SECONDS', '5')) # Initial delay before first poll

# SNS configuration for async job notifications (optional)
TEXTRACT_SNS_TOPIC_ARN = os.getenv('TEXTRACT_SNS_TOPIC_ARN') # e.g., 'arn:aws:sns:us-east-1:123456789012:MyTextractTopic'
TEXTRACT_SNS_ROLE_ARN = os.getenv('TEXTRACT_SNS_ROLE_ARN')   # e.g., 'arn:aws:iam::123456789012:role/TextractSNSRole'

# Output configuration for Textract results (e.g., saving raw JSON to S3)
TEXTRACT_OUTPUT_S3_BUCKET = os.getenv('TEXTRACT_OUTPUT_S3_BUCKET', S3_PRIMARY_DOCUMENT_BUCKET) # Can be same as input or a dedicated one
TEXTRACT_OUTPUT_S3_PREFIX = os.getenv('TEXTRACT_OUTPUT_S3_PREFIX', 'textract-output/')

# KMS Key ID for Textract output encryption (optional)
TEXTRACT_KMS_KEY_ID = os.getenv('TEXTRACT_KMS_KEY_ID')
```

### 1.4. Update Validation Logic
**Action:** If `StageConfig` or `validate_cloud_services` had Mistral-specific checks, remove them. Add checks for AWS credentials if Textract is a primary cloud service.
```python
# config.py (within StageConfig or validate_cloud_services or a new Textract validation)

# Example modification to validate_cloud_services()
def validate_cloud_services():
    """Validate cloud service configurations."""
    validations = []
    
    # OpenAI validation (existing)
    if USE_OPENAI_FOR_ENTITY_EXTRACTION or USE_OPENAI_FOR_STRUCTURED_EXTRACTION: # or other OpenAI uses
        if not OPENAI_API_KEY:
            validations.append("OpenAI API key missing but OpenAI services enabled")
        else:
            validations.append("✓ OpenAI API key configured")
    
    # AWS Credentials Validation (New - for Textract)
    # Textract will be used in all stages for PDF OCR if local Qwen is not preferred or for fallback.
    # Assuming Textract is now the primary PDF OCR:
    if not AWS_ACCESS_KEY_ID or not AWS_SECRET_ACCESS_KEY or not AWS_DEFAULT_REGION:
        validations.append("AWS credentials (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_DEFAULT_REGION) are required for Textract OCR.")
    else:
        validations.append("✓ AWS credentials configured for Textract.")
        
    # Remove Mistral validation
    # if USE_MISTRAL_FOR_OCR:
    #     if not MISTRAL_API_KEY:
    #         validations.append("Mistral API key missing but Mistral OCR enabled")
    #     else:
    #         validations.append("✓ Mistral API key configured")
    
    return validations

# Update StageConfig if it had Mistral-specific keys or requirements.
# For example, if 'require_mistral_key' was a property, remove it.
# If TEXTRACT_SNS_TOPIC_ARN and TEXTRACT_SNS_ROLE_ARN are set, ensure the IAM role has `sns:Publish` to the topic.
```

## 2. S3 Utilities Update (`s3_storage.py`)

### 2.1. Remove Public/Temp Bucket Functions
**Action:** Delete functions that manage or interact with public/temporary S3 buckets, as Textract uses IAM roles to access private buckets directly.
-   **Delete `copy_to_public_bucket()`** (Lines 78-96 approx.)
-   **Delete `generate_presigned_url_for_ocr()`** (Lines 98-114 approx.)
-   **Delete `cleanup_ocr_file()`** (Lines 116-124 approx.)

### 2.2. Simplify `upload_document_with_uuid_naming()`
**Action:** Modify this function to only work with the primary private document bucket.
**File:** `s3_storage.py`
```python
# Before (example structure)
# def upload_document_with_uuid_naming(self, local_file_path: str, document_uuid: str,
#                                        original_filename: str, bucket: str = None) -> dict:
#     bucket = bucket or S3_BUCKET_PRIVATE
#     # ... rest of the logic ...

# After
import boto3
import logging
import os
import hashlib
from typing import Optional, Dict # Added Dict
from datetime import datetime
# Ensure S3_PRIMARY_DOCUMENT_BUCKET and AWS_DEFAULT_REGION are imported from config
from config import AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_DEFAULT_REGION, S3_PRIMARY_DOCUMENT_BUCKET

logger = logging.getLogger(__name__)

class S3StorageManager:
    def __init__(self):
        self.s3_client = boto3.client(
            's3',
            region_name=AWS_DEFAULT_REGION,
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY
        )
        self.private_bucket_name = S3_PRIMARY_DOCUMENT_BUCKET

    def _get_content_type(self, filename: str) -> str:
        # ... (no change to this helper)
        ext = os.path.splitext(filename)[1].lower()
        content_types = {
            '.pdf': 'application/pdf',
            '.txt': 'text/plain',
            '.doc': 'application/msword',
            '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.tiff': 'image/tiff',
            '.tif': 'image/tiff',
        }
        return content_types.get(ext, 'application/octet-stream')

    def upload_document_with_uuid_naming(self, local_file_path: str, document_uuid: str,
                                       original_filename: str) -> Dict[str, any]:
        """Upload document with UUID-based naming to the primary private S3 bucket."""
        file_ext = os.path.splitext(original_filename)[1].lower()
        s3_key = f"documents/{document_uuid}{file_ext}" # Assuming a 'documents/' prefix

        with open(local_file_path, 'rb') as f:
            file_content = f.read()
            md5_hash = hashlib.md5(file_content).hexdigest()

        content_type = self._get_content_type(original_filename)
        metadata = {
            'original-filename': original_filename,
            'document-uuid': document_uuid,
            'upload-timestamp': datetime.now().isoformat(),
            'content-type': content_type # Store determined content type in S3 metadata
        }

        try:
            self.s3_client.put_object(
                Bucket=self.private_bucket_name,
                Key=s3_key,
                Body=file_content,
                Metadata=metadata,
                ContentType=content_type # Set ContentType for the S3 object
            )
            logger.info(f"Uploaded {original_filename} to s3://{self.private_bucket_name}/{s3_key}")
            return {
                's3_key': s3_key,
                's3_bucket': self.private_bucket_name,
                's3_region': AWS_DEFAULT_REGION, # Or self.s3_client.meta.region_name
                'md5_hash': md5_hash,
                'file_size': len(file_content),
                'metadata': metadata
            }
        except Exception as error:
            self.handle_s3_errors(error) # Ensure this method is robust
            raise

    # ... (keep handle_s3_errors)
    def handle_s3_errors(self, error):
        """Standardized S3 error handling"""
        # (Existing implementation, ensure it's comprehensive)
        # For Boto3 ClientError: error.response['Error']['Code'] and error.response['Error']['Message']
        from botocore.exceptions import ClientError, NoCredentialsError, PartialCredentialsError

        if isinstance(error, NoCredentialsError):
            logger.error(f"S3 credentials not found: {error}")
            raise ValueError(f"S3 credentials configuration error: {error}")
        elif isinstance(error, PartialCredentialsError):
            logger.error(f"Incomplete S3 credentials: {error}")
            raise ValueError(f"Incomplete S3 credentials: {error}")
        elif isinstance(error, ClientError):
            error_code = error.response.get('Error', {}).get('Code')
            error_message = error.response.get('Error', {}).get('Message')
            logger.error(f"S3 ClientError - Code: {error_code}, Message: {error_message}, Full Error: {error}")
            if error_code == 'NoSuchBucket':
                raise ValueError(f"S3 bucket '{self.private_bucket_name}' does not exist.")
            elif error_code == 'AccessDenied':
                raise PermissionError(f"S3 access denied for operation on bucket '{self.private_bucket_name}'. Check IAM permissions.")
            else:
                raise # Re-raise other client errors
        else:
            logger.error(f"Unknown S3 error: {error}")
            raise
```

### 2.3. Add S3 Object Reference Helper (Optional but Recommended)
**Action:** Add a method to construct the `DocumentLocation` dictionary required by Textract.
**File:** `s3_storage.py`
```python
# In S3StorageManager class
    def get_s3_document_location(self, s3_key: str, s3_bucket: Optional[str] = None, version_id: Optional[str] = None) -> Dict[str, any]:
        """
        Returns the DocumentLocation structure for Textract API calls.
        """
        bucket_name = s3_bucket or self.private_bucket_name
        s3_object_loc = {
            'S3Object': {
                'Bucket': bucket_name,
                'Name': s3_key
            }
        }
        if version_id:
            s3_object_loc['S3Object']['Version'] = version_id
        return s3_object_loc

    def check_s3_object_exists(self, s3_key: str, s3_bucket: Optional[str] = None) -> bool:
        """Checks if an object exists in the S3 bucket."""
        bucket_name = s3_bucket or self.private_bucket_name
        try:
            self.s3_client.head_object(Bucket=bucket_name, Key=s3_key)
            return True
        except ClientError as e:
            if e.response['Error']['Code'] == '404':
                return False
            else:
                logger.error(f"Error checking S3 object s3://{bucket_name}/{s3_key}: {e}")
                raise # Or return False, depending on desired behavior for other errors
        except Exception as e:
            logger.error(f"Unexpected error checking S3 object s3://{bucket_name}/{s3_key}: {e}")
            raise
```

## 3. New Textract Utilities (`textract_utils.py`)

**Action:** Create a new file named `textract_utils.py`. This file will contain all core logic for interacting with AWS Textract.
**File:** `textract_utils.py`

```python
# textract_utils.py
import boto3
import time
import json
import logging
from typing import List, Dict, Tuple, Optional, Any
from botocore.exceptions import ClientError
from collections import defaultdict

# Import necessary configurations from config.py
from config import (
    AWS_DEFAULT_REGION,
    AWS_ACCESS_KEY_ID, # For explicit client creation if needed, though IAM roles are preferred for EC2/Lambda
    AWS_SECRET_ACCESS_KEY, # Same as above
    TEXTRACT_ASYNC_MAX_POLLING_TIME_SECONDS,
    TEXTRACT_ASYNC_POLLING_INTERVAL_SECONDS,
    TEXTRACT_ASYNC_INITIAL_DELAY_SECONDS,
    TEXTRACT_SNS_TOPIC_ARN,
    TEXTRACT_SNS_ROLE_ARN,
    TEXTRACT_OUTPUT_S3_BUCKET,
    TEXTRACT_OUTPUT_S3_PREFIX,
    TEXTRACT_KMS_KEY_ID,
    TEXTRACT_CONFIDENCE_THRESHOLD,
    TEXTRACT_MAX_RESULTS_PER_PAGE, # Renamed from TEXTRACT_MAX_RESULTS for clarity
    TEXTRACT_ANALYZE_FEATURE_TYPES # Use this for AnalyzeDocument calls
)

logger = logging.getLogger(__name__)

class TextractProcessor:
    def __init__(self, region_name: str = AWS_DEFAULT_REGION):
        # It's best practice to rely on IAM roles when running on AWS infrastructure.
        # Explicitly passing keys is more for local development or non-AWS environments.
        self.client = boto3.client(
            'textract',
            region_name=region_name
            # aws_access_key_id=AWS_ACCESS_KEY_ID, # Only if not using IAM roles
            # aws_secret_access_key=AWS_SECRET_ACCESS_KEY # Only if not using IAM roles
        )
        logger.info(f"TextractProcessor initialized for region: {region_name}")

    def start_document_text_detection(self, s3_bucket: str, s3_key: str, client_request_token: Optional[str] = None, job_tag: Optional[str] = None) -> Optional[str]:
        """
        Starts an asynchronous job to detect text in a document stored in S3.
        Uses StartDocumentTextDetection API.

        Args:
            s3_bucket: The S3 bucket where the document is stored.
            s3_key: The key of the document in the S3 bucket.
            client_request_token: Idempotency token.
            job_tag: A tag for the job.

        Returns:
            The JobId if the job started successfully, None otherwise.
        """
        try:
            params = {
                'DocumentLocation': {
                    'S3Object': {
                        'Bucket': s3_bucket,
                        'Name': s3_key
                    }
                }
            }
            if client_request_token:
                params['ClientRequestToken'] = client_request_token
            if job_tag:
                params['JobTag'] = job_tag

            if TEXTRACT_SNS_TOPIC_ARN and TEXTRACT_SNS_ROLE_ARN:
                params['NotificationChannel'] = {
                    'SNSTopicArn': TEXTRACT_SNS_TOPIC_ARN,
                    'RoleArn': TEXTRACT_SNS_ROLE_ARN
                }
            
            # Optional: Configure output to be saved to S3 directly by Textract
            # This is useful for large responses or if you want to persist the raw Textract JSON.
            if TEXTRACT_OUTPUT_S3_BUCKET and TEXTRACT_OUTPUT_S3_PREFIX:
                 params['OutputConfig'] = {
                    'S3Bucket': TEXTRACT_OUTPUT_S3_BUCKET,
                    'S3Prefix': TEXTRACT_OUTPUT_S3_PREFIX.rstrip('/') + '/' # Ensure trailing slash
                }
            if TEXTRACT_KMS_KEY_ID:
                params['KMSKeyId'] = TEXTRACT_KMS_KEY_ID

            logger.info(f"Starting Textract job for s3://{s3_bucket}/{s3_key} with params: {params}")
            response = self.client.start_document_text_detection(**params)
            job_id = response.get('JobId')
            logger.info(f"Textract job started. JobId: {job_id} for s3://{s3_bucket}/{s3_key}")
            return job_id
        except ClientError as e:
            logger.error(f"Error starting Textract job for s3://{s3_bucket}/{s3_key}: {e.response['Error']['Message']}")
            # Consider specific error handling as per "Error Handling - Comprehensive Guide"
            # e.g., ProvisionedThroughputExceededException, InvalidS3ObjectException
            raise # Re-raise after logging, or handle more gracefully

    def get_text_detection_results(self, job_id: str) -> Tuple[Optional[List[Dict[str, Any]]], Optional[Dict[str, Any]]]:
        """
        Polls for the results of an asynchronous text detection job and retrieves all pages.

        Args:
            job_id: The JobId of the Textract job.

        Returns:
            A tuple containing:
            - A list of all Block objects from Textract if successful, None otherwise.
            - Document metadata (e.g., page count).
        """
        logger.info(f"Polling for Textract job results. JobId: {job_id}")
        start_time = time.time()
        
        time.sleep(TEXTRACT_ASYNC_INITIAL_DELAY_SECONDS) # Initial delay

        while True:
            elapsed_time = time.time() - start_time
            if elapsed_time > TEXTRACT_ASYNC_MAX_POLLING_TIME_SECONDS:
                logger.error(f"Textract job {job_id} timed out after {elapsed_time:.2f} seconds.")
                return None, None # Timeout

            try:
                response = self.client.get_document_text_detection(JobId=job_id, MaxResults=TEXTRACT_MAX_RESULTS_PER_PAGE)
                job_status = response.get('JobStatus')
                logger.debug(f"Textract job {job_id} status: {job_status}. Elapsed time: {elapsed_time:.2f}s")

                if job_status == 'SUCCEEDED':
                    all_blocks = response.get('Blocks', [])
                    document_metadata = response.get('DocumentMetadata', {})
                    next_token = response.get('NextToken')

                    while next_token:
                        logger.debug(f"Fetching next page of results for job {job_id} with token {next_token[:10]}...")
                        time.sleep(1) # Brief pause before next pagination call
                        response = self.client.get_document_text_detection(JobId=job_id, MaxResults=TEXTRACT_MAX_RESULTS_PER_PAGE, NextToken=next_token)
                        all_blocks.extend(response.get('Blocks', []))
                        next_token = response.get('NextToken')
                    
                    logger.info(f"Textract job {job_id} Succeeded. Retrieved {len(all_blocks)} blocks. Pages: {document_metadata.get('Pages')}")
                    return all_blocks, document_metadata
                
                elif job_status == 'FAILED':
                    logger.error(f"Textract job {job_id} Failed. StatusMessage: {response.get('StatusMessage')}, Warnings: {response.get('Warnings')}")
                    return None, None # Job failed
                
                elif job_status == 'PARTIAL_SUCCESS':
                    logger.warning(f"Textract job {job_id} PARTIAL_SUCCESS. StatusMessage: {response.get('StatusMessage')}, Warnings: {response.get('Warnings')}")
                    # Decide if partial results are acceptable or treat as failure
                    all_blocks = response.get('Blocks', [])
                    document_metadata = response.get('DocumentMetadata', {})
                    next_token = response.get('NextToken')
                    while next_token:
                        # ... (pagination logic as above) ...
                        response = self.client.get_document_text_detection(JobId=job_id, MaxResults=TEXTRACT_MAX_RESULTS_PER_PAGE, NextToken=next_token)
                        all_blocks.extend(response.get('Blocks', []))
                        next_token = response.get('NextToken')
                    return all_blocks, document_metadata # Or return None, None if partial is not okay

                # If IN_PROGRESS or other status, continue polling
                time.sleep(TEXTRACT_ASYNC_POLLING_INTERVAL_SECONDS)

            except ClientError as e:
                # Handle potential errors during polling (e.g., throttling)
                logger.error(f"ClientError while polling job {job_id}: {e.response['Error']['Message']}")
                # Implement backoff or retry for specific errors if needed
                time.sleep(TEXTRACT_ASYNC_POLLING_INTERVAL_SECONDS * 2) # Longer sleep on error
            except Exception as e:
                logger.error(f"Unexpected error while polling job {job_id}: {e}")
                return None, None


    def process_textract_blocks_to_text(self, blocks: List[Dict[str, Any]], doc_metadata: Dict[str, Any]) -> str:
        """
        Processes Textract Block objects to reconstruct the document text,
        respecting reading order as much as possible.

        Args:
            blocks: A list of Block objects from Textract.
            doc_metadata: Document metadata from Textract (contains page count).

        Returns:
            A string containing the extracted text from the document.
        """
        if not blocks:
            return ""

        page_texts = defaultdict(list)
        line_blocks = [block for block in blocks if block['BlockType'] == 'LINE']

        # Group lines by page and sort them by vertical position, then horizontal
        for line in line_blocks:
            page_number = line.get('Page', 1) # Default to page 1 if not present
            # Filter by confidence
            if line.get('Confidence', 0) < TEXTRACT_CONFIDENCE_THRESHOLD:
                logger.debug(f"Skipping LINE block on page {page_number} due to low confidence: {line.get('Confidence')}. Text: '{line.get('Text', '')[:50]}...'")
                continue
            
            # Geometry might be missing for some blocks if an error occurred.
            geometry = line.get('Geometry', {}).get('BoundingBox', {})
            if not geometry:
                logger.warning(f"LINE block on page {page_number} missing BoundingBox. Text: '{line.get('Text', '')[:50]}...'")
                # Fallback: append without geometric sorting for this line, or sort by block ID if needed.
                # For simplicity, we'll just append it to its page.
                page_texts[page_number].append({'text': line.get('Text', ''), 'top': float('inf'), 'left': float('inf')})
                continue

            page_texts[page_number].append({
                'text': line.get('Text', ''),
                'top': geometry.get('Top', 0),
                'left': geometry.get('Left', 0)
            })

        full_text_parts = []
        num_pages = doc_metadata.get('Pages', 0) if doc_metadata else max(page_texts.keys() or [0])

        for page_num in range(1, num_pages + 1):
            if page_num in page_texts:
                # Sort lines: primarily by 'top', secondarily by 'left' for reading order
                # This simple sort works for many single-column layouts.
                # For multi-column, a more sophisticated layout analysis (e.g., using Textract's LAYOUT feature) would be needed.
                sorted_lines_on_page = sorted(page_texts[page_num], key=lambda item: (item['top'], item['left']))
                page_content = "\n".join([item['text'] for item in sorted_lines_on_page])
                full_text_parts.append(page_content)
            else:
                # Placeholder for blank or unprocessable pages
                full_text_parts.append(f"[Page {page_num} - No text detected or processed]")
        
        return "\n\n<END_OF_PAGE>\n\n".join(full_text_parts) # Use a clear page separator

    # Placeholder for table extraction (if TEXTRACT_ANALYZE_FEATURE_TYPES includes 'TABLES')
    def extract_tables_from_blocks(self, blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Extracts structured table data from Textract blocks.
        This requires 'TABLES' feature in AnalyzeDocument or parsing TABLE and CELL blocks.
        """
        # This is a simplified example. Real table parsing can be complex.
        # You'd iterate through TABLE blocks, then CELL blocks, using RowIndex and ColumnIndex.
        # This function would typically be used with AnalyzeDocument results.
        # For DetectDocumentText, TABLE blocks are present but might be less structured.
        tables_data = []
        table_blocks = [block for block in blocks if block['BlockType'] == 'TABLE']
        
        for table_block in table_blocks:
            # Get associated CELL blocks using Relationships
            cell_ids = []
            for rel in table_block.get('Relationships', []):
                if rel.get('Type') == 'CHILD':
                    cell_ids.extend(rel.get('Ids', []))
            
            cells_in_table = [block for block in blocks if block['Id'] in cell_ids and block['BlockType'] == 'CELL']
            
            if not cells_in_table:
                continue

            # Determine max rows/cols for this table
            max_row = max(cell.get('RowIndex', 0) for cell in cells_in_table)
            max_col = max(cell.get('ColumnIndex', 0) for cell in cells_in_table)
            
            # Initialize table matrix
            table_matrix = [["" for _ in range(max_col)] for _ in range(max_row)]
            
            for cell in cells_in_table:
                row_idx = cell.get('RowIndex', 1) - 1 # 0-indexed
                col_idx = cell.get('ColumnIndex', 1) - 1 # 0-indexed
                
                # Get text from WORD blocks within this CELL
                cell_text_parts = []
                for rel_word in cell.get('Relationships', []):
                    if rel_word.get('Type') == 'CHILD':
                        for word_id in rel_word.get('Ids', []):
                            word_block = next((b for b in blocks if b['Id'] == word_id and b['BlockType'] == 'WORD'), None)
                            if word_block and word_block.get('Confidence', 0) >= TEXTRACT_CONFIDENCE_THRESHOLD:
                                cell_text_parts.append(word_block.get('Text', ''))
                
                cell_text = " ".join(cell_text_parts)

                if 0 <= row_idx < max_row and 0 <= col_idx < max_col:
                    # Handle cell spans if necessary (RowSpan, ColumnSpan)
                    # For simplicity, this example assigns to the primary cell.
                    table_matrix[row_idx][col_idx] = cell_text
            
            tables_data.append({
                'page': table_block.get('Page', 1),
                'confidence': table_block.get('Confidence'),
                'rows': table_matrix
                # You might want to add bounding box, etc.
            })
        return tables_data

    # --- AnalyzeDocument specific methods (if extending beyond simple text detection) ---
    # def start_document_analysis(self, s3_bucket: str, s3_key: str, feature_types: List[str], ...) -> Optional[str]:
    #     """Starts an asynchronous job using AnalyzeDocument API."""
    #     # Similar to start_document_text_detection, but calls self.client.start_document_analysis
    #     # with 'FeatureTypes': feature_types (e.g., ['TABLES', 'FORMS'])
    #     pass

    # def get_analysis_results(self, job_id: str) -> Optional[List[Dict[str, Any]]]:
    #     """Polls for AnalyzeDocument results."""
    #     # Similar to get_text_detection_results, but calls self.client.get_document_analysis
    #     pass

```

## 4. OCR Extraction Logic Update (`ocr_extraction.py`)

### 4.1. Remove Mistral-related Imports and Functions
**Action:** Delete `extract_text_from_pdf_mistral_ocr()` and the import for `mistral_utils`.
-   **Delete `extract_text_from_pdf_mistral_ocr()` function** (Lines 211-288 approx. in original)
-   **Remove `from mistral_utils import extract_text_from_url`** (Line 21 approx.)
-   **Remove `from supabase_utils import generate_document_url` if only used by Mistral function.** (Line 22 approx.) - `generate_document_url` seems more general, but its S3 part relied on presigned URLs for Mistral. Textract doesn't need presigned URLs.

### 4.2. Add Textract Imports and Implement `extract_text_from_pdf_textract()`
**Action:** Import `TextractProcessor` from the new `textract_utils.py`. Implement the new Textract PDF processing function.
**File:** `ocr_extraction.py`

```python
# ocr_extraction.py
# ... other imports like os, logging, fitz, boto3, time ...
# from config import (
#     QWEN2_VL_OCR_PROMPT, QWEN2_VL_OCR_MAX_NEW_TOKENS, # Qwen2-VL-OCR configs
#     # REMOVE: USE_MISTRAL_FOR_OCR, MISTRAL_OCR_TIMEOUT, MISTRAL_OCR_MODEL, MISTRAL_OCR_PROMPT,
#     DEPLOYMENT_STAGE, OPENAI_API_KEY, USE_OPENAI_FOR_AUDIO_TRANSCRIPTION,  # Stage management
#     STAGE_CLOUD_ONLY, S3_PRIMARY_DOCUMENT_BUCKET # Add S3_PRIMARY_DOCUMENT_BUCKET
# )
from config import (
    QWEN2_VL_OCR_PROMPT, QWEN2_VL_OCR_MAX_NEW_TOKENS,
    DEPLOYMENT_STAGE, OPENAI_API_KEY, USE_OPENAI_FOR_AUDIO_TRANSCRIPTION,
    STAGE_CLOUD_ONLY, S3_PRIMARY_DOCUMENT_BUCKET, TEXTRACT_USE_ASYNC_FOR_PDF # Import Textract configs
)

# ... (model_init imports remain) ...
# from models_init import (
#     get_qwen2_vl_ocr_model, get_qwen2_vl_ocr_processor, 
#     get_qwen2_vl_ocr_device, get_process_vision_info,
#     get_whisper_model, should_load_local_models
# )

# NEW Imports for Textract
from textract_utils import TextractProcessor
from s3_storage import S3StorageManager # To upload local files to S3 if needed
import uuid # For client request token or job tag

logger = logging.getLogger(__name__)

# ... (render_pdf_page_to_image, extract_text_from_pdf_qwen_vl_ocr, etc. remain) ...

def extract_text_from_pdf_textract(pdf_path: str, document_uuid_for_job: Optional[str] = None) -> tuple[Optional[str], Optional[List[Dict[str, Any]]]]:
    """
    Extracts text from a PDF using AWS Textract.
    If pdf_path is local, it's uploaded to S3 first.
    If pdf_path is an S3 URI, it's used directly.

    Args:
        pdf_path: Path to the PDF file (local or s3://bucket/key).
        document_uuid_for_job: An optional UUID for client request token or job tag.

    Returns:
        A tuple (extracted_text, page_level_metadata_list).
        Returns (None, None) on failure.
    """
    logger.info(f"Starting PDF text extraction with AWS Textract for: {pdf_path}")
    s3_manager = S3StorageManager()
    textract_processor = TextractProcessor()

    s3_bucket_name = S3_PRIMARY_DOCUMENT_BUCKET
    s3_object_key = ""

    # Ensure document_uuid_for_job is available
    if not document_uuid_for_job:
        document_uuid_for_job = str(uuid.uuid4())
        logger.info(f"Generated document_uuid_for_job: {document_uuid_for_job} for Textract processing.")

    try:
        if pdf_path.startswith('s3://'):
            parts = pdf_path.replace('s3://', '').split('/', 1)
            if len(parts) == 2:
                s3_bucket_name = parts[0]
                s3_object_key = parts[1]
                logger.info(f"Processing existing S3 object: s3://{s3_bucket_name}/{s3_object_key}")
            else:
                logger.error(f"Invalid S3 path format: {pdf_path}")
                return None, None
        elif os.path.exists(pdf_path):
            logger.info(f"Local file detected: {pdf_path}. Uploading to S3.")
            original_filename = os.path.basename(pdf_path)
            # Use the provided document_uuid_for_job for S3 naming consistency if it's the document's main UUID
            upload_info = s3_manager.upload_document_with_uuid_naming(
                local_file_path=pdf_path,
                document_uuid=document_uuid_for_job, # This should be the document's actual UUID
                original_filename=original_filename
            )
            s3_object_key = upload_info['s3_key']
            s3_bucket_name = upload_info['s3_bucket'] # Should be S3_PRIMARY_DOCUMENT_BUCKET
            logger.info(f"Uploaded local file to s3://{s3_bucket_name}/{s3_object_key}")
        else:
            logger.error(f"File not found at path: {pdf_path}")
            return None, None

        # Check if the S3 object actually exists before calling Textract
        if not s3_manager.check_s3_object_exists(s3_key=s3_object_key, s3_bucket=s3_bucket_name):
            logger.error(f"S3 object s3://{s3_bucket_name}/{s3_object_key} not found or accessible after upload/check.")
            return None, None

        start_time = time.time()
        extracted_text = None
        textract_doc_metadata = None
        page_level_metadata = [] # Store per-page info

        if TEXTRACT_USE_ASYNC_FOR_PDF:
            logger.info(f"Using ASYNC Textract processing for s3://{s3_bucket_name}/{s3_object_key}")
            job_id = textract_processor.start_document_text_detection(
                s3_bucket=s3_bucket_name,
                s3_key=s3_object_key,
                client_request_token=f"token-{document_uuid_for_job}", # Example token
                job_tag=f"job-{document_uuid_for_job}" # Example tag
            )

            if not job_id:
                logger.error(f"Failed to start Textract job for s3://{s3_bucket_name}/{s3_object_key}")
                return None, None

            blocks, textract_doc_metadata = textract_processor.get_text_detection_results(job_id)
            if blocks:
                extracted_text = textract_processor.process_textract_blocks_to_text(blocks, textract_doc_metadata)
                # Optionally extract tables if 'TABLES' was part of the features (for AnalyzeDocument)
                # tables = textract_processor.extract_tables_from_blocks(blocks)
                # You can add table data to metadata if needed
            else:
                logger.error(f"No blocks returned from Textract job {job_id}.")
                # textract_doc_metadata might still have page count or error info
        else:
            # Synchronous processing (DetectDocumentText) - suitable for single-page or quick results
            # Note: DetectDocumentText only processes one page at a time from an S3 object
            # For multi-page PDFs with sync, you'd need to render pages as images and send bytes,
            # or use StartDocumentTextDetection (async).
            # Given the pipeline usually handles multi-page PDFs, async is almost always preferred.
            # This 'else' branch might be rarely used for PDFs unless they are guaranteed single-page.
            logger.warning(f"TEXTRACT_USE_ASYNC_FOR_PDF is false. Synchronous Textract (DetectDocumentText) for PDFs is limited. "
                           f"Consider using async or ensure PDFs are single-page or use AnalyzeDocument for multi-page sync.")
            # Placeholder for sync:
            # response = textract_processor.client.detect_document_text(
            #     Document={'S3Object': {'Bucket': s3_bucket_name, 'Name': s3_object_key}}
            # )
            # blocks = response.get('Blocks', [])
            # textract_doc_metadata = response.get('DocumentMetadata', {})
            # extracted_text = textract_processor.process_textract_blocks_to_text(blocks, textract_doc_metadata)
            logger.error("Synchronous PDF processing via DetectDocumentText is not fully implemented here for multi-page. Defaulting to async behavior or failure.")
            return None, None # Or implement single-page sync / image conversion if strictly needed.

        processing_time = time.time() - start_time

        if extracted_text is not None:
            logger.info(f"Textract processing completed in {processing_time:.2f}s for s3://{s3_bucket_name}/{s3_object_key}. Extracted {len(extracted_text)} chars.")
            num_pages = textract_doc_metadata.get('Pages', 1) if textract_doc_metadata else 1
            
            # Create basic page_level_metadata
            # More detailed metadata could be extracted from blocks if needed (e.g., per-page char count)
            page_level_metadata = [{
                "page_number": i + 1,
                "method": "AWS Textract",
                "engine": "DetectDocumentText" if TEXTRACT_USE_ASYNC_FOR_PDF else "DetectDocumentText (Sync - Placeholder)", # Or AnalyzeDocument if used
                "processing_time_seconds": processing_time / num_pages, # Approximate per page
                "s3_key_used": s3_object_key,
                "char_count_page": len(extracted_text) / num_pages, # Approximate
                "confidence_avg_page": "N/A" # Would require iterating blocks
            } for i in range(num_pages)]
            
            # Add overall document metadata to the list as a special entry or to the first page
            doc_meta_entry = {
                "document_level": True,
                "total_pages_processed": num_pages,
                "total_chars_extracted": len(extracted_text),
                "total_processing_time_seconds": processing_time,
                "textract_job_id": job_id if TEXTRACT_USE_ASYNC_FOR_PDF else "N/A (Sync)"
            }
            if textract_doc_metadata and textract_doc_metadata.get('Warnings'):
                 doc_meta_entry['textract_warnings'] = textract_doc_metadata['Warnings']

            page_level_metadata.insert(0, doc_meta_entry) # Prepend document level summary

            return extracted_text, page_level_metadata
        else:
            logger.error(f"Textract failed to extract text from s3://{s3_bucket_name}/{s3_object_key}.")
            # Log warnings if present in textract_doc_metadata
            if textract_doc_metadata and textract_doc_metadata.get('Warnings'):
                logger.warning(f"Textract Warnings: {textract_doc_metadata['Warnings']}")
            
            # Populate some failure metadata
            page_level_metadata.append({
                "document_level": True,
                "status": "extraction_failed",
                "error_message": f"Textract job {job_id if TEXTRACT_USE_ASYNC_FOR_PDF else 'N/A'} did not return text.",
                "s3_key_used": s3_object_key,
                "textract_job_id": job_id if TEXTRACT_USE_ASYNC_FOR_PDF else "N/A (Sync)",
                "processing_time_seconds": processing_time,
                "textract_warnings": textract_doc_metadata.get('Warnings') if textract_doc_metadata else None
            })
            return None, page_level_metadata

    except Exception as e:
        logger.error(f"Exception during Textract PDF processing for {pdf_path}: {e}", exc_info=True)
        return None, [{"status": "exception", "error_message": str(e), "file_path": pdf_path}]

```

## 5. Main Pipeline Logic (`main_pipeline.py`)

### 5.1. Update Imports
**Action:** Change the import for PDF extraction function.
**File:** `main_pipeline.py`
```python
# Before
# from ocr_extraction import (
#     extract_text_from_pdf_qwen_vl_ocr, extract_text_from_pdf_mistral_ocr,
#     extract_text_from_docx, extract_text_from_txt, extract_text_from_eml,
#     transcribe_audio_whisper
# )
# from config import USE_MISTRAL_FOR_OCR # etc.

# After
from ocr_extraction import (
    extract_text_from_pdf_qwen_vl_ocr, # Keep if Qwen is still a fallback for non-PDFs or specific cases
    extract_text_from_pdf_textract,   # NEW: For PDF processing
    extract_text_from_docx, extract_text_from_txt, extract_text_from_eml,
    transcribe_audio_whisper
)
# REMOVE: from config import USE_MISTRAL_FOR_OCR
# No longer need USE_MISTRAL_FOR_OCR check.
```

### 5.2. Modify PDF Processing Logic in `process_single_document()`
**Action:** Replace the Mistral OCR call and associated logic with a direct call to `extract_text_from_pdf_textract()`. Remove the Qwen VL fallback for PDFs as Textract is now primary.
**File:** `main_pipeline.py`, within `process_single_document` function.
**Lines to Modify (approximate original lines 109-115):**

```python
# process_single_document function in main_pipeline.py

    # ... (fetch source_doc_uuid early - this is good practice) ...
    # source_doc_info = db_manager.get_document_by_id(source_doc_sql_id)
    # source_doc_uuid = source_doc_info.get('document_uuid') if source_doc_info else None
    # if not source_doc_uuid: # Generate one if missing, though intake should create it
    #     source_doc_uuid = str(uuid.uuid4()) 
    #     logger.warning(f"Source document SQL ID {source_doc_sql_id} missing UUID, generated one: {source_doc_uuid}")
        # Potentially update DB with this new UUID if this scenario is possible

    if detected_file_type == '.pdf':
        logger.info(f"Using AWS Textract for text extraction from PDF: {file_name}")
        # The `file_path` can be local or an s3:// URI.
        # `extract_text_from_pdf_textract` handles uploading local files to S3.
        # Pass `source_doc_uuid` to be used for S3 object naming and Textract job tags/tokens.
        raw_text, ocr_meta = extract_text_from_pdf_textract(file_path, document_uuid_for_job=source_doc_uuid)

        # Qwen VL is no longer a direct fallback for PDFs if Textract is primary.
        # If Textract fails, `raw_text` will be None.
        # The `extract_text_from_pdf_textract` function should return meaningful metadata on failure.
        if raw_text is None:
            logger.error(f"AWS Textract failed for {file_name}. OCR Metadata: {ocr_meta}")
            # The status update for failure will be handled by the subsequent `if raw_text:` block.

    elif detected_file_type == '.docx':
        # ... (existing logic for docx, txt, eml, audio) ...
```
**Note on Qwen VL Fallback:** The problem description stated "Remove: Fallback logic to Qwen VL OCR (lines 113-115)". This means Textract is the sole PDF OCR method. If Textract fails, the document processing for that PDF fails at the OCR stage.

### 5.3. Error Handling and Status Updates
**Action:** Ensure error handling and status updates correctly reflect Textract processing.
**File:** `main_pipeline.py`, within `process_single_document` function.
```python
    # ... (after OCR attempts) ...
    if raw_text:
        db_manager.update_source_document_text(source_doc_sql_id, raw_text,
                                    ocr_meta_json=json.dumps(ocr_meta) if ocr_meta else None,
                                    status="ocr_complete_pending_doc_node")
    else:
        logger.error(f"Failed to extract text for {file_name} using all available methods.")
        # Ensure ocr_meta from Textract (even on failure) is captured if it contains error details
        failure_meta_json = json.dumps(ocr_meta) if ocr_meta else json.dumps({"error": "Text extraction failed, no further details."})
        db_manager.update_source_document_text(source_doc_sql_id, None, 
                                               ocr_meta_json=failure_meta_json,
                                               status="extraction_failed")
        return # Exit processing for this document
```

## 6. Queue Processor Adjustments (`queue_processor.py`)

### 6.1. Simplify File Path Handling in `_process_claimed_documents()`
**Action:** The logic for downloading S3 files or handling public S3 URLs is no longer needed for Mistral. `extract_text_from_pdf_textract` will handle local files by uploading them. The queue should pass the S3 path if the file is already in S3 (e.g., `s3://bucket/key`), or a local path if it was ingested locally.
**File:** `queue_processor.py`, within `_process_claimed_documents` method.

```python
# queue_processor.py
# ... (imports)
# from config import PROJECT_ID_GLOBAL, S3_TEMP_DOWNLOAD_DIR, USE_S3_FOR_INPUT, S3_PRIMARY_DOCUMENT_BUCKET
# ...

    def _process_claimed_documents(self, claimed_items: List[Dict], project_sql_id: int) -> List[Dict]:
        """Process claimed documents and prepare them for pipeline processing"""
        documents_to_process = []
        
        for item in claimed_items:
            source_doc_details = self.db_manager.get_document_by_id(item['source_document_id'])
            if not source_doc_details:
                logger.warning(f"Could not find source document details for ID {item['source_document_id']}. Queue ID: {item['queue_id']}")
                self.mark_queue_item_failed(item['queue_id'], f"Source document ID {item['source_document_id']} not found.", item['source_document_id'])
                continue

            file_path_for_processing: str
            s3_key = source_doc_details.get('s3_key')
            s3_bucket = source_doc_details.get('s3_bucket') # This should be S3_PRIMARY_DOCUMENT_BUCKET

            if s3_key and s3_bucket:
                # File is already in S3, provide the S3 URI
                file_path_for_processing = f"s3://{s3_bucket}/{s3_key}"
                logger.info(f"Queue: Document {item['source_document_id']} found in S3: {file_path_for_processing}")
            elif source_doc_details.get('original_file_path'):
                # File is not yet in S3 (or s3_key/s3_bucket fields are not populated), use original_file_path.
                # This could be a local path or a Supabase storage URL.
                # extract_text_from_pdf_textract will handle uploading it if it's local.
                # If it's a Supabase storage URL, extract_text_from_pdf_textract needs to download it first then upload.
                # This part requires careful handling in extract_text_from_pdf_textract.
                file_path_for_processing = source_doc_details['original_file_path']
                logger.info(f"Queue: Document {item['source_document_id']} to be processed from path: {file_path_for_processing}. Textract function will manage S3 upload if needed.")
            else:
                logger.error(f"No valid S3 key or original_file_path for source document ID {item['source_document_id']}. Queue ID: {item['queue_id']}")
                self.mark_queue_item_failed(item['queue_id'], "Missing S3 key or original_file_path.", item['source_document_id'])
                continue
            
            # REMOVE old S3 download logic for USE_S3_FOR_INPUT here, as Textract function handles S3 interaction.
            # if USE_S3_FOR_INPUT and self.s3_manager and not file_path_for_processing.startswith('s3://'):
            #     # ... old download logic ...
            #     pass

            documents_to_process.append({
                'queue_id': item['queue_id'],
                'source_doc_sql_id': item['source_document_id'],
                'source_doc_uuid': item['source_document_uuid'], # Ensure this is passed and valid
                'attempts': item['attempts'],
                'file_path': file_path_for_processing,
                'file_name': source_doc_details['original_file_name'],
                'detected_file_type': source_doc_details['detected_file_type'],
                'project_sql_id': project_sql_id
            })

        return documents_to_process
```
**Important for `ocr_extraction.py` (`extract_text_from_pdf_textract`):**
If `pdf_path` received by `extract_text_from_pdf_textract` is a Supabase storage URL (e.g., `http://<supabase_url>/storage/v1/object/public/documents/uploads/file.pdf`), that function must:
1.  Download the file from this URL to a temporary local path.
2.  Upload this temporary local file to the `S3_PRIMARY_DOCUMENT_BUCKET` using `S3StorageManager`.
3.  Use the new S3 object key for Textract processing.
4.  Optionally, update the `source_documents` table with the new `s3_key` and `s3_bucket` if this migration is permanent.

### 6.2. Review `migrate_existing_file_to_s3()`
**Action:** This function (Lines 143-196 approx.) might still be relevant if you have files in Supabase storage that need to be moved to S3 *before* Textract processing, or as a one-time migration. However, the primary OCR function (`extract_text_from_pdf_textract`) should now be responsible for ensuring its input PDF is in S3.
-   If `extract_text_from_pdf_textract` robustly handles local paths and Supabase storage URLs by uploading/moving them to the primary S3 bucket, then `migrate_existing_file_to_s3` in the queue processor might become redundant or simplified.
-   For this refactor, assume `extract_text_from_pdf_textract` will manage getting the file into S3 if it's not already an `s3://` path.
-   **Recommendation:** Remove `migrate_existing_file_to_s3` from `QueueProcessor` and consolidate S3 upload logic within `extract_text_from_pdf_textract` if the source is not already an S3 object.

### 6.3. S3 Path Construction and Cleanup
-   **S3 Path:** Ensure paths passed to `process_single_document` are either S3 URIs (`s3://bucket/key`) or local paths that `extract_text_from_pdf_textract` can handle.
-   **Cleanup:** The temporary S3 file cleanup logic (`if USE_S3_FOR_INPUT and self.s3_manager and os.path.exists(...)`) in `process_queue` method (around line 290) refers to files downloaded *from S3 to local*. If `extract_text_from_pdf_textract` handles temporary local files created from Supabase URLs, it should clean them up itself. Files *in S3* for Textract are not temporary in the same way; they are the authoritative source. The `TEXTRACT_OUTPUT_S3_PREFIX` is where Textract *can* save its raw JSON output, which might have its own lifecycle policy.

### 6.4. Textract Job ID Tracking (Consideration)
-   The current polling logic is within `textract_utils.get_text_detection_results()`, meaning `process_single_document` will block until Textract is done.
-   If Textract jobs become very long (e.g., >10-15 minutes), this could lead to `max_processing_time` issues in the `QueueProcessor`.
-   **Advanced (Future):** For very long jobs, `start_document_text_detection` could be called, its `JobId` stored in the queue item or `source_documents` table, and a separate mechanism (e.g., SNS -> Lambda -> DB update, or another poller) could update the status. Then, a subsequent queue task could pick up completed jobs.
-   **For now:** Stick to the blocking poll within `process_single_document` as described. Monitor job durations.

## 7. IAM Policy and AWS SDK Setup

-   **IAM Role/User:** Ensure the EC2 instance, Lambda function, or user running this Python code has an IAM role/policy attached that grants the necessary permissions for Textract and S3, as detailed in the "IAM Policy Requirements for Textract" section of the problem description.
-   **Boto3 SDK:** Ensure `boto3` is installed (`pip install boto3`). Boto3 will automatically use credentials from the environment (for local dev with `aws configure`) or from the attached IAM role (on EC2/Lambda).

## 8. Testing Strategy

1.  **Unit Tests:**
    *   `textract_utils.py`: Test `process_textract_blocks_to_text` with mock Textract block data. Test polling logic with mock Textract responses for different job statuses.
    *   `s3_storage.py`: Test S3 upload and `get_s3_document_location`.
2.  **Integration Tests:**
    *   Test `ocr_extraction.py::extract_text_from_pdf_textract` with a sample PDF:
        *   Using a local PDF path (verifies S3 upload).
        *   Using an `s3://` path to an existing S3 object.
    *   Test the full `main_pipeline.py::process_single_document` flow with a PDF.
3.  **End-to-End Tests:**
    *   Process a document through the `QueueProcessor` (if applicable) or `direct` mode of `main_pipeline.py`.
    *   Verify correct text extraction and metadata population in the database.
    *   Test with various PDF types (scanned, text-based, multi-page).
    *   Test failure scenarios (e.g., unreadable PDF, Textract error).

This guide provides a comprehensive plan for refactoring the OCR pipeline to use AWS Textract. Remember to handle potential exceptions, log extensively, and configure AWS resources (like SNS topics if used) correctly.
```