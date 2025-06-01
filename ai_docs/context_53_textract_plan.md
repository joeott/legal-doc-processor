```markdown
# AWS Textract Refactor Implementation Guide (Revised with Claude's Feedback)

This guide incorporates Claude's feedback, including schema changes for `textract_jobs` and updates to `source_documents` and `document_processing_queue`. It assumes all SQL DDL commands for these changes have been successfully applied to the Supabase database.

## 1. Configuration Changes (`config.py`)

### 1.1. Remove Mistral OCR Configuration
**Action:** Delete all environment variables and Python constants related to Mistral OCR.
**Lines to Remove/Modify (approximate based on provided `config.py`):**
- `MISTRAL_API_KEY`
- `USE_MISTRAL_FOR_OCR`
- `MISTRAL_OCR_MODEL`
- `MISTRAL_OCR_PROMPT`
- `MISTRAL_OCR_TIMEOUT`
- Any related validation checks for `MISTRAL_API_KEY`.

### 1.2. Simplify S3 Bucket Configuration
**Action:** Modify S3 configuration to reflect the use of a single private bucket for documents. Remove configurations for public and temporary OCR buckets.
**Lines to Modify/Remove (approximate):**
- `S3_BUCKET_PUBLIC`
- `S3_BUCKET_TEMP`
- `S3_BUCKET_NAME` should now represent the primary private document bucket (e.g., `samu-docs-private-upload`). This will be referred to as `S3_PRIMARY_DOCUMENT_BUCKET`.

```python
# config.py
# ...
# S3 Configuration
USE_S3_FOR_INPUT = os.getenv("USE_S3_FOR_INPUT", "false").lower() in ("true", "1", "yes")
S3_PRIMARY_DOCUMENT_BUCKET = os.getenv("S3_PRIMARY_DOCUMENT_BUCKET", "samu-docs-private-upload") # Primary private bucket
S3_TEMP_DOWNLOAD_DIR = os.getenv("S3_TEMP_DOWNLOAD_DIR", str(BASE_DIR / "s3_downloads"))

# AWS Configuration (ensure these are present)
AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')
AWS_DEFAULT_REGION = os.getenv('AWS_DEFAULT_REGION', 'us-east-1') # Use your target region
# ...
```

### 1.3. Add/Update AWS Textract Configuration
**Action:** Add/Update configuration variables for AWS Textract.
**Location:** Add a new section in `config.py` or update existing AWS section.

```python
# config.py
# ...

# AWS Textract Configuration
TEXTRACT_FEATURE_TYPES = os.getenv('TEXTRACT_FEATURE_TYPES', 'TABLES,FORMS').split(',') # For AnalyzeDocument
TEXTRACT_CONFIDENCE_THRESHOLD = float(os.getenv('TEXTRACT_CONFIDENCE_THRESHOLD', '80.0'))
TEXTRACT_MAX_RESULTS_PER_PAGE = int(os.getenv('TEXTRACT_MAX_RESULTS_PER_PAGE', '1000'))
TEXTRACT_USE_ASYNC_FOR_PDF = os.getenv('TEXTRACT_USE_ASYNC_FOR_PDF', 'true').lower() in ('true', '1', 'yes')
TEXTRACT_ASYNC_MAX_POLLING_TIME_SECONDS = int(os.getenv('TEXTRACT_ASYNC_MAX_POLLING_TIME_SECONDS', '600'))
TEXTRACT_ASYNC_POLLING_INTERVAL_SECONDS = int(os.getenv('TEXTRACT_ASYNC_POLLING_INTERVAL_SECONDS', '5'))
TEXTRACT_ASYNC_INITIAL_DELAY_SECONDS = int(os.getenv('TEXTRACT_ASYNC_INITIAL_DELAY_SECONDS', '5'))
TEXTRACT_SNS_TOPIC_ARN = os.getenv('TEXTRACT_SNS_TOPIC_ARN')
TEXTRACT_SNS_ROLE_ARN = os.getenv('TEXTRACT_SNS_ROLE_ARN')
TEXTRACT_OUTPUT_S3_BUCKET = os.getenv('TEXTRACT_OUTPUT_S3_BUCKET', S3_PRIMARY_DOCUMENT_BUCKET) # Can be same or dedicated
TEXTRACT_OUTPUT_S3_PREFIX = os.getenv('TEXTRACT_OUTPUT_S3_PREFIX', 'textract-output/')
TEXTRACT_KMS_KEY_ID = os.getenv('TEXTRACT_KMS_KEY_ID')
```

### 1.4. Update Validation Logic
**Action:** Remove Mistral-specific checks. Add checks for AWS credentials.
```python
# config.py (within StageConfig or validate_cloud_services or a new Textract validation)

def validate_cloud_services():
    """Validate cloud service configurations."""
    validations = []
    # ... (OpenAI validation if still used) ...
    
    # AWS Credentials Validation (New - for Textract)
    if not AWS_ACCESS_KEY_ID or not AWS_SECRET_ACCESS_KEY or not AWS_DEFAULT_REGION:
        validations.append("AWS credentials (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_DEFAULT_REGION) are required for Textract OCR.")
    else:
        validations.append("✓ AWS credentials configured for Textract.")
    
    # Remove Mistral validation
    return validations
```

## 2. S3 Utilities Update (`s3_storage.py`)

### 2.1. Remove Public/Temp Bucket Functions
**Action:** Delete `copy_to_public_bucket()`, `generate_presigned_url_for_ocr()`, `cleanup_ocr_file()`.

### 2.2. Modify `upload_document_with_uuid_naming()` for Correct S3 Key Pattern
**Action:** Update the S3 key generation to use the document's UUID, not the `uploads/[timestamp]-[random]` pattern, to align with the objective of `document_uuid` based naming. This means new uploads will follow the `documents/{document_uuid}{file_ext}` pattern. An external migration script would be needed for existing files if consistency across all S3 objects is required.
**File:** `s3_storage.py`

```python
# s3_storage.py
# ... (imports: boto3, logging, os, hashlib, Dict, Optional, datetime) ...
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
        # ... (no change)
        ext = os.path.splitext(filename)[1].lower()
        content_types = {
            '.pdf': 'application/pdf', '.txt': 'text/plain', '.doc': 'application/msword',
            '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
            '.tiff': 'image/tiff', '.tif': 'image/tiff',
        }
        return content_types.get(ext, 'application/octet-stream')

    def upload_document_with_uuid_naming(self, local_file_path: str, document_uuid: str,
                                       original_filename: str) -> Dict[str, any]:
        """Upload document with UUID-based naming to the primary private S3 bucket."""
        file_ext = os.path.splitext(original_filename)[1].lower()
        # S3 key will be based on document_uuid, e.g., "documents/your-document-uuid.pdf"
        # This aligns with the refactor's intent, diverging from Claude's suggestion to keep the old pattern.
        s3_key = f"documents/{document_uuid}{file_ext}" 

        with open(local_file_path, 'rb') as f:
            file_content = f.read()
            md5_hash = hashlib.md5(file_content).hexdigest()

        content_type = self._get_content_type(original_filename)
        metadata = {
            'original-filename': original_filename, # Keep original filename in S3 metadata
            'document-uuid': document_uuid,
            'upload-timestamp': datetime.now().isoformat(),
            'content-type': content_type
        }

        try:
            self.s3_client.put_object(
                Bucket=self.private_bucket_name,
                Key=s3_key,
                Body=file_content,
                Metadata=metadata,
                ContentType=content_type
            )
            logger.info(f"Uploaded {original_filename} to s3://{self.private_bucket_name}/{s3_key}")
            return {
                's3_key': s3_key,
                's3_bucket': self.private_bucket_name,
                's3_region': AWS_DEFAULT_REGION,
                'md5_hash': md5_hash,
                'file_size': len(file_content),
                'metadata': metadata # S3 metadata, not to be confused with document's JSONB metadata
            }
        except Exception as error:
            self.handle_s3_errors(error)
            raise

    def get_s3_document_location(self, s3_key: str, s3_bucket: Optional[str] = None, version_id: Optional[str] = None) -> Dict[str, any]:
        # ... (no change from previous guide) ...
        bucket_name = s3_bucket or self.private_bucket_name
        s3_object_loc = {'S3Object': {'Bucket': bucket_name, 'Name': s3_key}}
        if version_id:
            s3_object_loc['S3Object']['Version'] = version_id
        return s3_object_loc

    def check_s3_object_exists(self, s3_key: str, s3_bucket: Optional[str] = None) -> bool:
        # ... (no change from previous guide) ...
        from botocore.exceptions import ClientError # Ensure this import is present
        bucket_name = s3_bucket or self.private_bucket_name
        try:
            self.s3_client.head_object(Bucket=bucket_name, Key=s3_key)
            return True
        except ClientError as e:
            if e.response['Error']['Code'] == '404': return False
            else: logger.error(f"Error checking S3 object s3://{bucket_name}/{s3_key}: {e}"); raise
        except Exception as e:
            logger.error(f"Unexpected error checking S3 object s3://{bucket_name}/{s3_key}: {e}"); raise

    def handle_s3_errors(self, error):
        # ... (no change from previous guide, ensure botocore.exceptions are imported) ...
        from botocore.exceptions import ClientError, NoCredentialsError, PartialCredentialsError # Ensure this import is present
        if isinstance(error, NoCredentialsError): logger.error(f"S3 credentials not found: {error}"); raise ValueError(f"S3 credentials configuration error: {error}")
        elif isinstance(error, PartialCredentialsError): logger.error(f"Incomplete S3 credentials: {error}"); raise ValueError(f"Incomplete S3 credentials: {error}")
        elif isinstance(error, ClientError):
            error_code = error.response.get('Error', {}).get('Code'); error_message = error.response.get('Error', {}).get('Message')
            logger.error(f"S3 ClientError - Code: {error_code}, Message: {error_message}, Full Error: {error}")
            if error_code == 'NoSuchBucket': raise ValueError(f"S3 bucket '{self.private_bucket_name}' does not exist.")
            elif error_code == 'AccessDenied': raise PermissionError(f"S3 access denied for operation on bucket '{self.private_bucket_name}'. Check IAM permissions.")
            else: raise
        else: logger.error(f"Unknown S3 error: {error}"); raise
```

## 3. Supabase Utilities Update (`supabase_utils.py`)

### 3.1. Add Methods for `textract_jobs` Table
**Action:** Add new methods in `SupabaseManager` to interact with the `textract_jobs` table.
**File:** `supabase_utils.py`

```python
# supabase_utils.py
# ... (existing SupabaseManager class and methods) ...

class SupabaseManager:
    # ... (existing __init__ and other methods) ...

    def create_textract_job_entry(self, source_document_id: int, document_uuid: str, job_id: str,
                                 s3_input_bucket: str, s3_input_key: str,
                                 job_type: str = 'DetectDocumentText',
                                 feature_types: Optional[List[str]] = None,
                                 s3_output_bucket: Optional[str] = None,
                                 s3_output_key: Optional[str] = None,
                                 confidence_threshold: Optional[float] = TEXTRACT_CONFIDENCE_THRESHOLD, # from config
                                 client_request_token: Optional[str] = None,
                                 job_tag: Optional[str] = None,
                                 sns_topic_arn: Optional[str] = TEXTRACT_SNS_TOPIC_ARN # from config
                                 ) -> Optional[int]:
        """Creates an entry in the textract_jobs table."""
        logger.info(f"Creating Textract job entry for source_doc_id: {source_document_id}, job_id: {job_id}")
        job_data = {
            'source_document_id': source_document_id,
            'document_uuid': document_uuid,
            'job_id': job_id,
            'job_type': job_type,
            's3_input_bucket': s3_input_bucket,
            's3_input_key': s3_input_key,
            'job_status': 'SUBMITTED', # Initial status
            'confidence_threshold': confidence_threshold,
            'client_request_token': client_request_token,
            'job_tag': job_tag,
            'sns_topic_arn': sns_topic_arn,
            'started_at': datetime.now().isoformat() # Record submission time as started_at for now
        }
        if feature_types:
            job_data['feature_types'] = feature_types
        if s3_output_bucket:
            job_data['s3_output_bucket'] = s3_output_bucket
        if s3_output_key:
            job_data['s3_output_key'] = s3_output_key
        
        try:
            response = self.client.table('textract_jobs').insert(job_data).execute()
            if response.data:
                return response.data[0]['id']
            logger.error(f"Failed to insert Textract job entry, response: {response.error if response.error else 'No data returned'}")
            return None
        except Exception as e:
            logger.error(f"Error creating Textract job entry: {e}", exc_info=True)
            raise

    def update_textract_job_status(self, job_id: str, job_status: str,
                                   page_count: Optional[int] = None,
                                   processed_pages: Optional[int] = None,
                                   avg_confidence: Optional[float] = None,
                                   warnings_json: Optional[Dict] = None,
                                   error_message: Optional[str] = None,
                                   s3_output_key: Optional[str] = None,
                                   completed_at_override: Optional[datetime] = None
                                   ) -> bool:
        """Updates an existing entry in the textract_jobs table."""
        logger.info(f"Updating Textract job_id: {job_id} to status: {job_status}")
        update_data = {'job_status': job_status}
        if page_count is not None:
            update_data['page_count'] = page_count
        if processed_pages is not None:
            update_data['processed_pages'] = processed_pages
        if avg_confidence is not None:
            update_data['avg_confidence'] = avg_confidence
        if warnings_json:
            update_data['warnings'] = warnings_json # Assumes JSONB column
        if error_message:
            update_data['error_message'] = error_message
        if s3_output_key: # If Textract saves output to S3
            update_data['s3_output_key'] = s3_output_key
            
        if job_status in ['SUCCEEDED', 'FAILED', 'PARTIAL_SUCCESS']:
            update_data['completed_at'] = (completed_at_override or datetime.now()).isoformat()

        try:
            response = self.client.table('textract_jobs').update(update_data).eq('job_id', job_id).execute()
            # Check if response indicates success (e.g., response.data is not empty or response.error is None)
            if response.data or not response.error: # Supabase returns list of updated rows or empty list if no match
                logger.info(f"Textract job {job_id} updated successfully.")
                return True
            logger.warning(f"Failed to update Textract job {job_id} or job not found. Response error: {response.error}")
            return False
        except Exception as e:
            logger.error(f"Error updating Textract job entry for job_id {job_id}: {e}", exc_info=True)
            raise

    def get_textract_job_by_job_id(self, job_id: str) -> Optional[Dict]:
        """Retrieves a Textract job entry by its job_id."""
        try:
            response = self.client.table('textract_jobs').select('*').eq('job_id', job_id).maybe_single().execute()
            return response.data
        except Exception as e:
            logger.error(f"Error fetching Textract job by job_id {job_id}: {e}", exc_info=True)
            return None

    # Method to update source_documents with Textract outcomes
    def update_source_document_with_textract_outcome(self, source_doc_sql_id: int,
                                                     textract_job_id: str,
                                                     textract_job_status: str, # From the new field in source_documents
                                                     ocr_provider_enum: str = 'textract', # Value for ocr_provider type
                                                     raw_text: Optional[str] = None,
                                                     ocr_metadata: Optional[Dict] = None, # This is Textract's page-level metadata
                                                     textract_warnings_json: Optional[Dict] = None,
                                                     textract_confidence: Optional[float] = None,
                                                     textract_output_s3_key_val: Optional[str] = None,
                                                     job_started_at: Optional[datetime] = None,
                                                     job_completed_at: Optional[datetime] = None):
        """Updates source_documents table with results from Textract processing."""
        logger.info(f"Updating source_document {source_doc_sql_id} with Textract job ({textract_job_id}) outcome: {textract_job_status}")
        
        update_payload = {
            'textract_job_id': textract_job_id,
            'textract_job_status': textract_job_status,
            'ocr_provider': ocr_provider_enum,
            'updated_at': datetime.now().isoformat() # General update timestamp
        }
        if raw_text is not None: # Only update if text was successfully extracted
            update_payload['raw_extracted_text'] = raw_text
            update_payload['initial_processing_status'] = 'ocr_complete_pending_doc_node' # Assuming success if raw_text is present
        elif textract_job_status == 'failed':
             update_payload['initial_processing_status'] = 'extraction_failed'

        if ocr_metadata:
            update_payload['ocr_metadata_json'] = json.dumps(ocr_metadata)
        if textract_warnings_json:
            update_payload['textract_warnings'] = textract_warnings_json # Assumes JSONB
        if textract_confidence is not None:
            update_payload['textract_confidence_avg'] = textract_confidence
        if textract_output_s3_key_val:
            update_payload['textract_output_s3_key'] = textract_output_s3_key_val
        
        if job_started_at:
            update_payload['textract_job_started_at'] = job_started_at.isoformat()
        if job_completed_at:
            update_payload['textract_job_completed_at'] = job_completed_at.isoformat()
            update_payload['ocr_completed_at'] = job_completed_at.isoformat() # General OCR completion
            if job_started_at: # Calculate duration if both are present
                duration = (job_completed_at - job_started_at).total_seconds()
                update_payload['ocr_processing_seconds'] = int(duration)
        
        try:
            self.client.table('source_documents').update(update_payload).eq('id', source_doc_sql_id).execute()
            logger.info(f"Source_document {source_doc_sql_id} updated with Textract job {textract_job_id} info.")
        except Exception as e:
            logger.error(f"Error updating source_document {source_doc_sql_id} with Textract info: {e}", exc_info=True)
            raise
```

## 4. New Textract Utilities (`textract_utils.py`)

### 4.1. Initialize `TextractProcessor` with `SupabaseManager`
**Action:** Pass `SupabaseManager` instance to `TextractProcessor` for DB interactions.
**File:** `textract_utils.py`

```python
# textract_utils.py
# ... (imports including SupabaseManager if not already) ...
from supabase_utils import SupabaseManager # Make sure this import is correct
from config import ( # Import all necessary config values
    AWS_DEFAULT_REGION, TEXTRACT_ASYNC_MAX_POLLING_TIME_SECONDS, TEXTRACT_ASYNC_POLLING_INTERVAL_SECONDS,
    TEXTRACT_ASYNC_INITIAL_DELAY_SECONDS, TEXTRACT_SNS_TOPIC_ARN, TEXTRACT_SNS_ROLE_ARN,
    TEXTRACT_OUTPUT_S3_BUCKET, TEXTRACT_OUTPUT_S3_PREFIX, TEXTRACT_KMS_KEY_ID,
    TEXTRACT_CONFIDENCE_THRESHOLD, TEXTRACT_MAX_RESULTS_PER_PAGE, TEXTRACT_ANALYZE_FEATURE_TYPES
)
import uuid # For client request token if not passed

class TextractProcessor:
    def __init__(self, db_manager: SupabaseManager, region_name: str = AWS_DEFAULT_REGION): # Added db_manager
        self.client = boto3.client('textract', region_name=region_name)
        self.db_manager = db_manager # Store db_manager instance
        logger.info(f"TextractProcessor initialized for region: {region_name} with DBManager.")

    def start_document_text_detection(self, s3_bucket: str, s3_key: str,
                                    source_doc_id: int, document_uuid_from_db: str, # Use document_uuid from DB
                                    client_request_token: Optional[str] = None,
                                    job_tag: Optional[str] = None) -> Optional[str]:
        try:
            params = {
                'DocumentLocation': {'S3Object': {'Bucket': s3_bucket, 'Name': s3_key}}
            }
            # Use a deterministic client request token if none provided, based on document_uuid
            params['ClientRequestToken'] = client_request_token or f"textract-{document_uuid_from_db}"
            if job_tag: params['JobTag'] = job_tag
            if TEXTRACT_SNS_TOPIC_ARN and TEXTRACT_SNS_ROLE_ARN:
                params['NotificationChannel'] = {'SNSTopicArn': TEXTRACT_SNS_TOPIC_ARN, 'RoleArn': TEXTRACT_SNS_ROLE_ARN}
            if TEXTRACT_OUTPUT_S3_BUCKET and TEXTRACT_OUTPUT_S3_PREFIX:
                 params['OutputConfig'] = {'S3Bucket': TEXTRACT_OUTPUT_S3_BUCKET, 'S3Prefix': TEXTRACT_OUTPUT_S3_PREFIX.rstrip('/') + '/'}
            if TEXTRACT_KMS_KEY_ID: params['KMSKeyId'] = TEXTRACT_KMS_KEY_ID

            logger.info(f"Starting Textract job for s3://{s3_bucket}/{s3_key} with params: {params}")
            response = self.client.start_document_text_detection(**params)
            job_id = response.get('JobId')

            if job_id:
                logger.info(f"Textract job started. JobId: {job_id} for s3://{s3_bucket}/{s3_key}")
                # Create entry in textract_jobs table
                # Note: TEXTRACT_OUTPUT_S3_PREFIX and TEXTRACT_OUTPUT_S3_BUCKET are for where Textract *saves its JSON output*,
                # not where the input PDF is. s3_output_key would be like `textract-output/{job_id}/manifest.json`
                textract_output_key_val = f"{TEXTRACT_OUTPUT_S3_PREFIX.rstrip('/')}/{job_id}/1" if params.get('OutputConfig') else None

                self.db_manager.create_textract_job_entry(
                    source_document_id=source_doc_id,
                    document_uuid=document_uuid_from_db, # Use the one from DB
                    job_id=job_id,
                    s3_input_bucket=s3_bucket,
                    s3_input_key=s3_key,
                    job_type='DetectDocumentText', # Assuming this function is for DetectDocumentText
                    s3_output_bucket=params.get('OutputConfig', {}).get('S3Bucket'),
                    s3_output_key=textract_output_key_val, # This might need adjustment based on Textract's actual output naming
                    client_request_token=params['ClientRequestToken'],
                    job_tag=job_tag,
                    sns_topic_arn=params.get('NotificationChannel', {}).get('SNSTopicArn')
                )
                # Update source_documents table with initial job info
                self.db_manager.update_source_document_with_textract_outcome(
                    source_doc_sql_id=source_doc_id,
                    textract_job_id=job_id,
                    textract_job_status='submitted', # From source_documents.textract_job_status enum
                    job_started_at=datetime.now() # Record submission time
                )
            return job_id
        except ClientError as e:
            logger.error(f"Error starting Textract job for s3://{s3_bucket}/{s3_key}: {e.response['Error']['Message']}")
            # Update textract_jobs and source_documents with failure
            if self.db_manager: # Check if db_manager is available
                # Try to log failure if job_id was obtained or for source_doc_id
                self.db_manager.update_source_document_with_textract_outcome(
                    source_doc_sql_id=source_doc_id,
                    textract_job_id="N/A_START_FAILURE", # Placeholder
                    textract_job_status='failed'
                )
            raise
    
    def get_text_detection_results(self, job_id: str, source_doc_id: int) -> Tuple[Optional[List[Dict[str, Any]]], Optional[Dict[str, Any]]]:
        logger.info(f"Polling for Textract job results. JobId: {job_id}, SourceDocId: {source_doc_id}")
        start_time = time.time()
        job_entry = self.db_manager.get_textract_job_by_job_id(job_id)
        initial_db_start_time = job_entry.get('started_at') if job_entry else datetime.now()

        time.sleep(TEXTRACT_ASYNC_INITIAL_DELAY_SECONDS)

        while True:
            elapsed_time = time.time() - start_time
            if elapsed_time > TEXTRACT_ASYNC_MAX_POLLING_TIME_SECONDS:
                logger.error(f"Textract job {job_id} timed out after {elapsed_time:.2f} seconds.")
                self.db_manager.update_textract_job_status(job_id, 'FAILED', error_message='Polling Timeout')
                self.db_manager.update_source_document_with_textract_outcome(source_doc_sql_id=source_doc_id, textract_job_id=job_id, textract_job_status='failed')
                return None, None

            try:
                response = self.client.get_document_text_detection(JobId=job_id, MaxResults=TEXTRACT_MAX_RESULTS_PER_PAGE)
                job_status_api = response.get('JobStatus') # SUCCEEDED, FAILED, IN_PROGRESS, PARTIAL_SUCCESS
                logger.debug(f"Textract job {job_id} API status: {job_status_api}. Elapsed time: {elapsed_time:.2f}s")

                # Map API status to DB enum values if different (e.g., 'SUCCEEDED' -> 'succeeded')
                db_job_status = job_status_api.lower() if job_status_api else 'in_progress'
                if job_status_api == 'IN_PROGRESS': db_job_status = 'in_progress' # Ensure mapping
                elif job_status_api == 'SUCCEEDED': db_job_status = 'succeeded'
                elif job_status_api == 'FAILED': db_job_status = 'failed'
                elif job_status_api == 'PARTIAL_SUCCESS': db_job_status = 'partial_success'


                # Update textract_jobs table with current status
                self.db_manager.update_textract_job_status(job_id, db_job_status)
                # Also update source_documents.textract_job_status
                self.db_manager.update_source_document_with_textract_outcome(source_doc_sql_id=source_doc_id, textract_job_id=job_id, textract_job_status=db_job_status)


                if job_status_api == 'SUCCEEDED' or job_status_api == 'PARTIAL_SUCCESS':
                    all_blocks = response.get('Blocks', [])
                    document_metadata_api = response.get('DocumentMetadata', {})
                    api_warnings = response.get('Warnings')
                    next_token = response.get('NextToken')

                    while next_token:
                        # ... (pagination logic as before) ...
                        time.sleep(0.5) # Small delay for paginated calls
                        response = self.client.get_document_text_detection(JobId=job_id, MaxResults=TEXTRACT_MAX_RESULTS_PER_PAGE, NextToken=next_token)
                        all_blocks.extend(response.get('Blocks', []))
                        # Aggregate warnings if any from subsequent pages
                        page_warnings = response.get('Warnings')
                        if page_warnings:
                            if api_warnings is None: api_warnings = []
                            api_warnings.extend(page_warnings)
                        next_token = response.get('NextToken')
                    
                    avg_conf = sum(b.get('Confidence',0) for b in all_blocks if 'Confidence' in b) / len(all_blocks) if all_blocks else None
                    
                    # Final update to textract_jobs and source_documents
                    completion_time = datetime.now()
                    self.db_manager.update_textract_job_status(
                        job_id, db_job_status,
                        page_count=document_metadata_api.get('Pages'),
                        processed_pages=document_metadata_api.get('Pages'), # Assuming all pages processed on SUCCEEDED/PARTIAL
                        avg_confidence=round(avg_conf, 2) if avg_conf is not None else None,
                        warnings_json=api_warnings,
                        completed_at_override=completion_time
                    )
                    self.db_manager.update_source_document_with_textract_outcome(
                        source_doc_sql_id=source_doc_id, textract_job_id=job_id, textract_job_status=db_job_status,
                        ocr_metadata=document_metadata_api, # This is Textract's DocMeta, not page-level from previous guide. Adjust if needed.
                        textract_warnings_json=api_warnings,
                        textract_confidence=round(avg_conf, 2) if avg_conf is not None else None,
                        job_completed_at=completion_time,
                        job_started_at=initial_db_start_time # Use the start time recorded in DB
                    )
                    logger.info(f"Textract job {job_id} {job_status_api}. Retrieved {len(all_blocks)} blocks. Pages: {document_metadata_api.get('Pages')}")
                    return all_blocks, document_metadata_api
                
                elif job_status_api == 'FAILED':
                    error_msg_api = response.get('StatusMessage', 'Unknown Textract job failure')
                    api_warnings = response.get('Warnings')
                    logger.error(f"Textract job {job_id} Failed. StatusMessage: {error_msg_api}, Warnings: {api_warnings}")
                    self.db_manager.update_textract_job_status(job_id, 'failed', error_message=error_msg_api, warnings_json=api_warnings, completed_at_override=datetime.now())
                    self.db_manager.update_source_document_with_textract_outcome(source_doc_sql_id=source_doc_id, textract_job_id=job_id, textract_job_status='failed', job_completed_at=datetime.now(), job_started_at=initial_db_start_time)
                    return None, None
                
                time.sleep(TEXTRACT_ASYNC_POLLING_INTERVAL_SECONDS)

            except ClientError as e:
                # ... (error handling for polling) ...
                error_message = e.response.get('Error',{}).get('Message', str(e))
                logger.error(f"ClientError while polling job {job_id}: {error_message}")
                # Potentially update DB with polling error if it's persistent
                self.db_manager.update_textract_job_status(job_id, 'failed', error_message=f"Polling ClientError: {error_message[:200]}")
                self.db_manager.update_source_document_with_textract_outcome(source_doc_sql_id=source_doc_id, textract_job_id=job_id, textract_job_status='failed')
                time.sleep(TEXTRACT_ASYNC_POLLING_INTERVAL_SECONDS * 2)
            except Exception as e:
                logger.error(f"Unexpected error while polling job {job_id}: {e}", exc_info=True)
                self.db_manager.update_textract_job_status(job_id, 'failed', error_message=f"Polling Exception: {str(e)[:200]}")
                self.db_manager.update_source_document_with_textract_outcome(source_doc_sql_id=source_doc_id, textract_job_id=job_id, textract_job_status='failed')
                return None, None # Critical error during polling
    
    # process_textract_blocks_to_text, extract_tables_from_blocks remain largely the same
    # as in the previous guide, ensure TEXTRACT_CONFIDENCE_THRESHOLD is used.
    def process_textract_blocks_to_text(self, blocks: List[Dict[str, Any]], doc_metadata: Dict[str, Any]) -> str:
        # ... (Implementation from previous guide, ensuring TEXTRACT_CONFIDENCE_THRESHOLD is used for filtering LINE/WORD blocks)
        if not blocks: return ""
        page_texts = defaultdict(list)
        line_blocks = [block for block in blocks if block['BlockType'] == 'LINE']
        for line in line_blocks:
            page_number = line.get('Page', 1)
            if line.get('Confidence', 0) < TEXTRACT_CONFIDENCE_THRESHOLD:
                logger.debug(f"Skipping LINE block on page {page_number} due to low confidence: {line.get('Confidence')}. Text: '{line.get('Text', '')[:50]}...'")
                continue
            geometry = line.get('Geometry', {}).get('BoundingBox', {})
            if not geometry:
                logger.warning(f"LINE block on page {page_number} missing BoundingBox. Text: '{line.get('Text', '')[:50]}...'")
                page_texts[page_number].append({'text': line.get('Text', ''), 'top': float('inf'), 'left': float('inf')})
                continue
            page_texts[page_number].append({'text': line.get('Text', ''), 'top': geometry.get('Top', 0), 'left': geometry.get('Left', 0)})
        full_text_parts = []
        num_pages = doc_metadata.get('Pages', 0) if doc_metadata else max(page_texts.keys() or [0])
        for page_num in range(1, num_pages + 1):
            if page_num in page_texts:
                sorted_lines_on_page = sorted(page_texts[page_num], key=lambda item: (item['top'], item['left']))
                page_content = "\n".join([item['text'] for item in sorted_lines_on_page])
                full_text_parts.append(page_content)
            else:
                full_text_parts.append(f"[Page {page_num} - No text detected or processed]")
        return "\n\n<END_OF_PAGE>\n\n".join(full_text_parts)
```

## 5. OCR Extraction Logic Update (`ocr_extraction.py`)

### 5.1. Remove Mistral-related imports and functions
**Action:** As before.

### 5.2. Update `extract_text_from_pdf_textract()`
**Action:** Modify to use `document_uuid` from the database and integrate with `TextractProcessor`'s DB tracking.
**File:** `ocr_extraction.py`

```python
# ocr_extraction.py
# ... (imports: os, logging, fitz, boto3, time, uuid, json) ...
from config import (
    # ... QWEN2_VL configs ...,
    DEPLOYMENT_STAGE, STAGE_CLOUD_ONLY, S3_PRIMARY_DOCUMENT_BUCKET, TEXTRACT_USE_ASYNC_FOR_PDF,
    TEXTRACT_CONFIDENCE_THRESHOLD # Make sure this is available if needed directly here
)
from textract_utils import TextractProcessor
from s3_storage import S3StorageManager
from supabase_utils import SupabaseManager # Added for DB interaction
import tempfile # For downloading from Supabase storage
import requests # For downloading from Supabase storage

logger = logging.getLogger(__name__)

# Helper function for downloading from Supabase storage if path is a URL
def _download_supabase_file_to_temp(supabase_url: str) -> Optional[str]:
    try:
        logger.info(f"Downloading from Supabase storage URL: {supabase_url}")
        response = requests.get(supabase_url, stream=True)
        response.raise_for_status() # Raise an exception for HTTP errors
        
        # Create a temporary file
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") # Assuming PDF
        with open(temp_file.name, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        logger.info(f"Successfully downloaded to temporary file: {temp_file.name}")
        return temp_file.name
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to download from Supabase URL {supabase_url}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error downloading from Supabase URL {supabase_url}: {e}", exc_info=True)
        return None


def extract_text_from_pdf_textract(db_manager: SupabaseManager, # Added db_manager
                                   source_doc_sql_id: int, # Added source_doc_sql_id
                                   pdf_path_or_s3_uri: str,
                                   document_uuid_from_db: str # Expect this from DB
                                   ) -> tuple[Optional[str], Optional[List[Dict[str, Any]]]]:
    
    logger.info(f"Starting PDF text extraction with AWS Textract for source_doc_id: {source_doc_sql_id}, doc_uuid: {document_uuid_from_db}, path: {pdf_path_or_s3_uri}")
    s3_manager = S3StorageManager()
    # Pass db_manager to TextractProcessor for DB updates
    textract_processor = TextractProcessor(db_manager=db_manager)

    s3_bucket_name = S3_PRIMARY_DOCUMENT_BUCKET
    s3_object_key: Optional[str] = None
    local_temp_pdf_to_clean: Optional[str] = None

    try:
        if pdf_path_or_s3_uri.startswith('s3://'):
            parts = pdf_path_or_s3_uri.replace('s3://', '').split('/', 1)
            if len(parts) == 2:
                s3_bucket_name = parts[0] # Could be different from S3_PRIMARY_DOCUMENT_BUCKET if already processed
                s3_object_key = parts[1]
                logger.info(f"Processing existing S3 object: s3://{s3_bucket_name}/{s3_object_key}")
            else: # Should not happen if queue processor formats correctly
                logger.error(f"Invalid S3 URI format: {pdf_path_or_s3_uri}")
                db_manager.update_source_document_with_textract_outcome(source_doc_sql_id, "N/A_S3_FORMAT", 'failed')
                return None, [{"status": "error", "error_message": f"Invalid S3 URI: {pdf_path_or_s3_uri}"}]
        
        elif pdf_path_or_s3_uri.startswith('http://') or pdf_path_or_s3_uri.startswith('https://'):
            # Assume it's a Supabase Storage URL or other accessible HTTP URL
            logger.info(f"HTTP(S) URL detected: {pdf_path_or_s3_uri}. Downloading temporarily.")
            local_temp_pdf_to_clean = _download_supabase_file_to_temp(pdf_path_or_s3_uri)
            if not local_temp_pdf_to_clean:
                db_manager.update_source_document_with_textract_outcome(source_doc_sql_id, "N/A_HTTP_DL_FAIL", 'failed')
                return None, [{"status": "error", "error_message": f"Failed to download from URL: {pdf_path_or_s3_uri}"}]
            
            # Now upload this temporary local file to S3 using the document_uuid_from_db
            # The original_filename for S3 metadata can be derived or fixed.
            # If source_documents table has original_file_name, fetch and use it.
            source_doc_details = db_manager.get_document_by_id(source_doc_sql_id)
            original_filename_for_s3 = source_doc_details.get('original_file_name', f"{document_uuid_from_db}.pdf") if source_doc_details else f"{document_uuid_from_db}.pdf"

            upload_info = s3_manager.upload_document_with_uuid_naming(
                local_file_path=local_temp_pdf_to_clean,
                document_uuid=document_uuid_from_db,
                original_filename=original_filename_for_s3
            )
            s3_object_key = upload_info['s3_key']
            s3_bucket_name = upload_info['s3_bucket'] # Should be S3_PRIMARY_DOCUMENT_BUCKET
            logger.info(f"Uploaded downloaded file to s3://{s3_bucket_name}/{s3_object_key}")
            # Update source_documents with the new S3 key/bucket if this is a permanent migration
            db_manager.client.table('source_documents').update({
                's3_key': s3_object_key,
                's3_bucket': s3_bucket_name,
                's3_region': AWS_DEFAULT_REGION # from config
            }).eq('id', source_doc_sql_id).execute()
            logger.info(f"Updated source_document {source_doc_sql_id} with new S3 location.")

        elif os.path.exists(pdf_path_or_s3_uri):
            logger.info(f"Local file detected: {pdf_path_or_s3_uri}. Uploading to S3.")
            original_filename = os.path.basename(pdf_path_or_s3_uri)
            upload_info = s3_manager.upload_document_with_uuid_naming(
                local_file_path=pdf_path_or_s3_uri,
                document_uuid=document_uuid_from_db,
                original_filename=original_filename
            )
            s3_object_key = upload_info['s3_key']
            s3_bucket_name = upload_info['s3_bucket']
            logger.info(f"Uploaded local file to s3://{s3_bucket_name}/{s3_object_key}")
            # Update source_documents with S3 key/bucket
            db_manager.client.table('source_documents').update({
                's3_key': s3_object_key,
                's3_bucket': s3_bucket_name,
                's3_region': AWS_DEFAULT_REGION
            }).eq('id', source_doc_sql_id).execute()
            logger.info(f"Updated source_document {source_doc_sql_id} with S3 location from local upload.")
        else:
            logger.error(f"File not found at path: {pdf_path_or_s3_uri}")
            db_manager.update_source_document_with_textract_outcome(source_doc_sql_id, "N/A_PATH_NOT_FOUND", 'failed')
            return None, [{"status": "error", "error_message": f"File not found: {pdf_path_or_s3_uri}"}]

        if not s3_object_key: # Should have been set by one of the branches above
            logger.error(f"S3 object key could not be determined for {pdf_path_or_s3_uri}")
            db_manager.update_source_document_with_textract_outcome(source_doc_sql_id, "N/A_S3_KEY_MISSING", 'failed')
            return None, [{"status": "error", "error_message": "S3 object key missing"}]

        # Check S3 object existence
        if not s3_manager.check_s3_object_exists(s3_key=s3_object_key, s3_bucket=s3_bucket_name):
            logger.error(f"S3 object s3://{s3_bucket_name}/{s3_object_key} not found or accessible.")
            db_manager.update_source_document_with_textract_outcome(source_doc_sql_id, "N/A_S3_NOT_FOUND", 'failed')
            return None, [{"status": "error", "error_message": f"S3 object s3://{s3_bucket_name}/{s3_object_key} not found"}]

        start_time = time.time()
        extracted_text = None
        textract_doc_api_metadata = None # From Textract GetDocumentTextDetection response
        page_level_metadata_for_db = [] # This is the ocr_metadata_json for source_documents

        if TEXTRACT_USE_ASYNC_FOR_PDF:
            logger.info(f"Using ASYNC Textract processing for s3://{s3_bucket_name}/{s3_object_key}")
            # Pass source_doc_sql_id and document_uuid_from_db to start_document_text_detection
            job_id = textract_processor.start_document_text_detection(
                s3_bucket=s3_bucket_name,
                s3_key=s3_object_key,
                source_doc_id=source_doc_sql_id,
                document_uuid_from_db=document_uuid_from_db
                # client_request_token and job_tag are handled inside start_document_text_detection
            )

            if not job_id: # Failure to start job (already logged and DB updated by start_document_text_detection)
                return None, [{"status": "error", "error_message": f"Failed to start Textract job for s3://{s3_bucket_name}/{s3_object_key}"}]

            # Pass source_doc_sql_id to get_text_detection_results for status updates
            blocks, textract_doc_api_metadata = textract_processor.get_text_detection_results(job_id, source_doc_sql_id)
            
            if blocks:
                extracted_text = textract_processor.process_textract_blocks_to_text(blocks, textract_doc_api_metadata)
            else: # Job might have succeeded but returned no blocks, or failed. get_text_detection_results handles DB updates.
                logger.error(f"No blocks returned from Textract job {job_id}. Check textract_jobs table for details.")
        else: # Synchronous
            logger.error("Synchronous PDF processing via DetectDocumentText is not fully supported for multi-page. Configure TEXTRACT_USE_ASYNC_FOR_PDF=true.")
            db_manager.update_source_document_with_textract_outcome(source_doc_sql_id, "N/A_SYNC_UNSUPPORTED", 'failed')
            return None, [{"status": "error", "error_message": "Sync PDF Textract not supported"}]

        processing_time_total = time.time() - start_time

        if extracted_text is not None:
            logger.info(f"Textract processing completed in {processing_time_total:.2f}s for s3://{s3_bucket_name}/{s3_object_key}. Extracted {len(extracted_text)} chars.")
            num_pages = textract_doc_api_metadata.get('Pages', 1) if textract_doc_api_metadata else 1
            
            # This becomes the ocr_metadata_json in source_documents
            page_level_metadata_for_db = [{
                "page_number": i + 1, "method": "AWS Textract", "engine": "DetectDocumentText",
                "processing_time_seconds_approx_per_page": round(processing_time_total / num_pages, 2) if num_pages > 0 else processing_time_total,
                # Add more detailed per-page metrics if process_textract_blocks_to_text can provide them
            } for i in range(num_pages)]
            
            doc_meta_summary = {
                "document_level_summary": True,
                "total_pages_processed": num_pages, "total_chars_extracted": len(extracted_text),
                "total_processing_time_seconds": round(processing_time_total, 2),
                "textract_job_id": job_id if TEXTRACT_USE_ASYNC_FOR_PDF and 'job_id' in locals() else "N/A",
                "textract_api_metadata": textract_doc_api_metadata # Store the raw Textract DocumentMetadata
            }
            page_level_metadata_for_db.insert(0, doc_meta_summary)

            # The final source_document update is handled by TextractProcessor or caller (main_pipeline)
            # This function now just returns the data.
            return extracted_text, page_level_metadata_for_db
        else: # Text extraction failed, get_text_detection_results should have updated DB.
            logger.error(f"Textract failed to extract text from s3://{s3_bucket_name}/{s3_object_key}.")
            # Construct failure metadata to return
            failure_meta = {
                "document_level_summary": True, "status": "extraction_failed",
                "error_message": f"Textract job {job_id if TEXTRACT_USE_ASYNC_FOR_PDF and 'job_id' in locals() else 'N/A'} did not return text.",
                "s3_key_used": s3_object_key,
                "textract_job_id": job_id if TEXTRACT_USE_ASYNC_FOR_PDF and 'job_id' in locals() else "N/A",
                "processing_time_seconds": round(processing_time_total,2),
                "textract_api_metadata": textract_doc_api_metadata
            }
            return None, [failure_meta]

    except Exception as e:
        logger.error(f"Outer exception during Textract PDF processing for {pdf_path_or_s3_uri} (source_id: {source_doc_sql_id}): {e}", exc_info=True)
        # Attempt to update DB with failure status
        try:
            db_manager.update_source_document_with_textract_outcome(source_doc_sql_id, "N/A_EXCEPTION", 'failed')
        except Exception as db_e:
            logger.error(f"Failed to update DB on outer exception for source_id {source_doc_sql_id}: {db_e}")
        return None, [{"status": "exception", "error_message": str(e), "file_path": pdf_path_or_s3_uri}]
    finally:
        if local_temp_pdf_to_clean and os.path.exists(local_temp_pdf_to_clean):
            try:
                os.unlink(local_temp_pdf_to_clean)
                logger.info(f"Cleaned up temporary local PDF: {local_temp_pdf_to_clean}")
            except Exception as e_clean:
                logger.warning(f"Failed to clean up temporary PDF {local_temp_pdf_to_clean}: {e_clean}")

# ... (other extraction functions: Qwen, docx, txt, eml, audio transcription)
# Ensure transcribe_audio_whisper and other non-PDF extractors are not affected or are updated if they also use S3 in a way that needs changing.
```

## 6. Main Pipeline Logic (`main_pipeline.py`)

### 6.1. Update Imports
**Action:** As before.

### 6.2. Modify PDF Processing Logic in `process_single_document()`
**Action:** Pass `db_manager`, `source_doc_sql_id`, and `source_doc_uuid` to `extract_text_from_pdf_textract`.
**File:** `main_pipeline.py`, within `process_single_document` function.

```python
# main_pipeline.py
# ... (imports including SupabaseManager) ...
# from ocr_extraction import (
#     extract_text_from_pdf_qwen_vl_ocr, extract_text_from_pdf_textract, ...
# )
# ...

def process_single_document(db_manager: SupabaseManager, source_doc_sql_id: int, file_path: str, file_name: str, detected_file_type: str, project_sql_id: int):
    logger.info(f"Processing document: {file_name} (Source SQL ID: {source_doc_sql_id}) for Project SQL ID: {project_sql_id}")
    # ... (Stage validation if any) ...

    raw_text = None
    ocr_meta_for_db = None # This will be the page_level_metadata list from Textract function

    # Fetch full source_document details, especially document_uuid
    source_doc_info = db_manager.get_document_by_id(source_doc_sql_id)
    if not source_doc_info:
        logger.error(f"CRITICAL: Source document with SQL ID {source_doc_sql_id} not found. Aborting processing for this item.")
        # Potentially update queue item if this is from queue, or log failure.
        return
    
    source_doc_uuid = source_doc_info.get('document_uuid')
    if not source_doc_uuid:
        logger.error(f"CRITICAL: Source document SQL ID {source_doc_sql_id} is missing 'document_uuid'. Aborting.")
        db_manager.update_source_document_text(source_doc_sql_id, None, status="error_missing_uuid")
        return

    # Update source_documents.ocr_provider and related fields
    # Moved this initial update to be more prominent, before calling extraction
    db_manager.client.table('source_documents').update({
        'ocr_provider': 'textract', # Set the provider early
        'textract_job_status': 'not_started', # Initial state before job submission
        'updated_at': datetime.now().isoformat()
    }).eq('id', source_doc_sql_id).execute()


    if detected_file_type == '.pdf':
        logger.info(f"Using AWS Textract for text extraction from PDF: {file_name}")
        # `file_path` can be local, s3:// URI, or Supabase storage URL.
        # `extract_text_from_pdf_textract` now handles these and S3 upload if needed.
        raw_text, ocr_meta_for_db = extract_text_from_pdf_textract(
            db_manager=db_manager,
            source_doc_sql_id=source_doc_sql_id,
            pdf_path_or_s3_uri=file_path, # This is the path from queue/direct intake
            document_uuid_from_db=source_doc_uuid
        )
        # Textract function now handles DB updates for job status and basic outcomes.
        # We only need to handle the final text and metadata here.

    elif detected_file_type == '.docx':
        raw_text = extract_text_from_docx(file_path)
        ocr_meta_for_db = [{"method": "docx_parser"}] # Example metadata
        # Update ocr_provider for non-PDFs if applicable
        db_manager.client.table('source_documents').update({'ocr_provider': 'docx_parser', 'ocr_completed_at': datetime.now().isoformat()}).eq('id', source_doc_sql_id).execute()

    # ... (elif for .txt, .eml, audio - update their ocr_provider and ocr_completed_at similarly) ...
    
    elif detected_file_type in ['.wav', '.mp3']:
        raw_text = transcribe_audio_whisper(file_path) # Assuming this also returns text
        ocr_meta_for_db = [{"method": "whisper_transcription"}]
        db_manager.client.table('source_documents').update({'ocr_provider': 'openai', 'ocr_completed_at': datetime.now().isoformat()}).eq('id', source_doc_sql_id).execute() # Example 'openai' for Whisper API

    else:
        logger.warning(f"Unsupported file type for text extraction: {detected_file_type} for {file_name}")
        db_manager.update_source_document_text(source_doc_sql_id, None, status="extraction_unsupported")
        # Update ocr_provider if you have a category for this
        db_manager.client.table('source_documents').update({'ocr_provider': None, 'initial_processing_status': 'extraction_unsupported'}).eq('id', source_doc_sql_id).execute()
        return

    # Post-extraction processing and DB updates
    if raw_text is not None: # Successfully extracted text
        # Update source_document text, final OCR metadata, and overall status.
        # The textract_job_id, textract_job_status, etc. on source_documents are updated by TextractProcessor.
        # Here, we focus on raw_extracted_text, ocr_metadata_json, and the main initial_processing_status.
        db_manager.update_source_document_text(
            source_doc_sql_id,
            raw_text,
            ocr_meta_json=json.dumps(ocr_meta_for_db) if ocr_meta_for_db else None,
            status="ocr_complete_pending_doc_node"
        )
        # The ocr_completed_at and ocr_processing_seconds should be set by the specific extraction function
        # or by the TextractProcessor callbacks.
        # For non-Textract, update them here if not done by their extractors.
        if detected_file_type != '.pdf': # Textract flow handles its own completion timestamps.
            # You might need a helper to calculate duration if not done by individual extractors
            db_manager.client.table('source_documents').update({
                'ocr_completed_at': datetime.now().isoformat(),
                # 'ocr_processing_seconds': calculate_duration_if_possible
            }).eq('id', source_doc_sql_id).execute()

    else: # Text extraction failed
        logger.error(f"Failed to extract text for {file_name} using all available methods.")
        # The specific Textract failure status should already be set on source_documents by TextractProcessor.
        # For other file types, set a generic failure status.
        if detected_file_type != '.pdf': # Textract failures are handled within its flow
            db_manager.update_source_document_text(
                source_doc_sql_id, None,
                ocr_meta_json=json.dumps(ocr_meta_for_db) if ocr_meta_for_db else json.dumps({"error": "Text extraction failed"}),
                status="extraction_failed"
            )
            db_manager.client.table('source_documents').update({
                'ocr_provider': 'unknown_failure', # Or more specific based on type
                'ocr_completed_at': datetime.now().isoformat()
            }).eq('id', source_doc_sql_id).execute()
        # If it was a PDF and raw_text is None, TextractProcessor should have updated source_documents.textract_job_status to 'failed'.
        # The overall `initial_processing_status` for source_documents should also reflect this.
        # Ensure `update_source_document_with_textract_outcome` sets `initial_processing_status` to 'extraction_failed'
        return # Exit processing for this document

    # ... (rest of the pipeline: Neo4j node creation, cleaning, chunking, etc.) ...
    # Fetch project_uuid for neo4j_document_entry
    _project_info = db_manager.get_project_by_sql_id_or_global_project_id(project_sql_id, PROJECT_ID_GLOBAL)
    _project_uuid = _project_info.get('projectId') if isinstance(_project_info, dict) else (_project_info if isinstance(_project_info, str) else None) # Adjusted based on actual return of get_project_...

    if not _project_uuid:
        logger.error(f"Critical: Could not determine project_uuid for project_sql_id {project_sql_id}. Aborting {file_name}.")
        db_manager.update_source_document_text(source_doc_sql_id, raw_text, status="error_project_uuid_lookup")
        return

    neo4j_doc_sql_id, neo4j_doc_uuid = db_manager.create_neo4j_document_entry(
        source_doc_fk_id=source_doc_sql_id, 
        source_doc_uuid=source_doc_uuid, 
        project_fk_id=project_sql_id,
        project_uuid=_project_uuid,
        file_name=file_name # file_name is original, S3 key is document_uuid based
    )
    # ... (continue pipeline)
```

## 7. Queue Processor Adjustments (`queue_processor.py`)

### 7.1. Update File Path Handling in `_process_claimed_documents()`
**Action:** Use `s3_key` and `s3_bucket` directly from `source_doc_details`.
**File:** `queue_processor.py`, within `_process_claimed_documents` method.

```python
# queue_processor.py
# ... (imports: os, logging, time, socket, uuid, datetime, timedelta, List, Dict, Optional)
from supabase_utils import SupabaseManager
from main_pipeline import process_single_document # Removed initialize_all_models from here if it's in main entry
from config import PROJECT_ID_GLOBAL # Removed S3_TEMP_DOWNLOAD_DIR, USE_S3_FOR_INPUT
# from s3_utils import S3FileManager # S3FileManager might still be needed if QueueProcessor uploads non-S3 files directly

class QueueProcessor:
    def __init__(self, batch_size: int = 5, max_processing_time_minutes: int = 60):
        self.db_manager = SupabaseManager()
        # ... (rest of __init__)
        # self.s3_manager = S3FileManager() if USE_S3_FOR_INPUT else None # Keep if direct upload from queue is a path

    def _process_claimed_documents(self, claimed_items: List[Dict], project_sql_id: int) -> List[Dict]:
        documents_to_process = []
        for item in claimed_items:
            source_doc_details = self.db_manager.get_document_by_id(item['source_document_id'])
            if not source_doc_details:
                # ... (error handling as before) ...
                logger.warning(f"Could not find source document details for ID {item['source_document_id']}. Queue ID: {item['queue_id']}")
                self.mark_queue_item_failed(item['queue_id'], f"Source document ID {item['source_document_id']} not found.", item['source_document_id'])
                continue

            file_path_for_pipeline: str
            s3_key = source_doc_details.get('s3_key')
            s3_bucket = source_doc_details.get('s3_bucket')

            if s3_key and s3_bucket:
                file_path_for_pipeline = f"s3://{s3_bucket}/{s3_key}"
                logger.info(f"Queue: Document {item['source_document_id']} found in S3: {file_path_for_pipeline}")
            elif source_doc_details.get('original_file_path'):
                # This path could be a local path (if queue worker has access) or a Supabase Storage URL.
                # extract_text_from_pdf_textract will handle both.
                file_path_for_pipeline = source_doc_details['original_file_path']
                logger.info(f"Queue: Document {item['source_document_id']} to be processed from original path: {file_path_for_pipeline}.")
            else:
                # ... (error handling as before) ...
                logger.error(f"No valid S3 key or original_file_path for source document ID {item['source_document_id']}. Queue ID: {item['queue_id']}")
                self.mark_queue_item_failed(item['queue_id'], "Missing S3 key or original_file_path.", item['source_document_id'])
                continue
            
            # Update queue item with ocr_provider (Textract for PDFs)
            if source_doc_details['detected_file_type'] == '.pdf':
                 self.db_manager.client.table('document_processing_queue').update({'ocr_provider': 'textract'}).eq('id', item['queue_id']).execute()

            documents_to_process.append({
                'queue_id': item['queue_id'],
                'source_doc_sql_id': item['source_document_id'],
                'source_doc_uuid': source_doc_details.get('document_uuid'), # Get from details
                'attempts': item['attempts'],
                'file_path': file_path_for_pipeline,
                'file_name': source_doc_details['original_file_name'], # original_file_name for display/logging
                'detected_file_type': source_doc_details['detected_file_type'],
                'project_sql_id': project_sql_id
            })
        return documents_to_process

    # ... (rest of QueueProcessor, including mark_queue_item_failed, check_for_stalled_documents, process_queue)
    # In `process_queue` method, when calling `process_single_document`:
    # The arguments are already `db_manager`, `source_doc_sql_id`, `file_path`, `file_name`, `detected_file_type`, `project_sql_id`.
    # This matches the updated signature. `source_doc_uuid` is fetched within `process_single_document`.

    def mark_queue_item_failed(self, queue_id: int, error_message: str, source_doc_sql_id: Optional[int] = None):
        # ... (ensure this updates the new Textract job fields if a job_id was associated with the queue item)
        logger.error(f"Marking queue item {queue_id} as failed. Error: {error_message}")
        try:
            update_data = {
                'status': 'failed',
                'error_message': str(error_message)[:2000],
                'completed_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat()
            }
            # If textract_job_id was added to queue table and is available on item, update it too.
            # queue_item_details = self.db_manager.client.table('document_processing_queue').select('textract_job_id').eq('id', queue_id).maybe_single().execute()
            # if queue_item_details.data and queue_item_details.data.get('textract_job_id'):
            #    self.db_manager.update_textract_job_status(queue_item_details.data['textract_job_id'], 'FAILED', error_message=f"Queue Processing Error: {error_message}")

            self.db_manager.client.table('document_processing_queue').update(update_data).eq('id', queue_id).execute()

            if source_doc_sql_id:
                # Update source_documents table to reflect failure from queue processing perspective
                self.db_manager.update_source_document_with_textract_outcome(
                    source_doc_sql_id=source_doc_sql_id,
                    textract_job_id= "N/A_QUEUE_FAIL", # Or fetch if available
                    textract_job_status='failed', # general failure indication
                    # Potentially add the error_message to source_documents.error_message too
                )
                # Also, set the main status.
                self.db_manager.client.table('source_documents').update({
                    'initial_processing_status': 'error', # General error
                    'error_message': f"Queue processing failure: {error_message[:250]}"
                }).eq('id', source_doc_sql_id).execute()

        except Exception as e:
            logger.error(f"CRITICAL: Error while marking queue item {queue_id} as failed: {e}", exc_info=True)

    def claim_pending_documents(self) -> List[Dict]:
        # ... (Existing logic to claim documents)
        # When claiming, you might want to fetch textract_job_id if it's on the queue table and pass it along,
        # though TextractProcessor is designed to create/update its own job entries.
        # The main change here is how _process_claimed_documents constructs file_path.
        # The DDL added textract_job_id to document_processing_queue.
        # If a job was started but interrupted, and then re-queued, this job_id might be useful.
        # For now, assume TextractProcessor starts a new job or handles existing based on ClientRequestToken.
        # ...
        # (No major changes here other than ensuring the new fields from document_processing_queue are available if needed by _process_claimed_documents)
        # The `rpc('claim_pending_documents_batch', ...)` needs to be replaced with direct Supabase queries
        # as shown in the previous iteration of queue_processor.py provided in the prompt.
        # This section is already updated in the prompt's queue_processor.py.
        logger.debug(f"Attempting to claim up to {self.batch_size} documents.")
        try:
            # project_sql_id, project_uuid = self.db_manager.get_or_create_project(PROJECT_ID_GLOBAL, "My Legal Project")
            # Project ID is now passed to _process_claimed_documents, fetched once.
            response_project = self.db_manager.client.table('projects').select('id').eq('projectId', PROJECT_ID_GLOBAL).maybe_single().execute()
            if not response_project.data:
                logger.error(f"Project with projectId {PROJECT_ID_GLOBAL} not found. Cannot claim documents."); return []
            project_sql_id = response_project.data['id']

        except Exception as e:
            logger.error(f"Failed to get project {PROJECT_ID_GLOBAL}: {e}"); return []

        try:
            # Updated claim logic using direct queries (from previous iteration)
            response = self.db_manager.client.table('document_processing_queue')\
                .select('*')\
                .eq('status', 'pending')\
                .lt('retry_count', 3) \
                .order('priority', desc=False)\
                .order('created_at', desc=False)\
                .limit(self.batch_size)\
                .execute()
            
            claimed_items_for_processing = []
            for item in response.data:
                try:
                    update_response = self.db_manager.client.table('document_processing_queue')\
                        .update({
                            'status': 'processing',
                            'retry_count': item['retry_count'] + 1,
                            'started_at': datetime.now().isoformat(),
                            'processor_metadata': {'processor_id': self.processor_id, 'started_at': datetime.now().isoformat()},
                            'updated_at': datetime.now().isoformat()
                            # `textract_job_id` on queue table could be set here if a new job is initiated immediately
                        })\
                        .eq('id', item['id'])\
                        .eq('status', 'pending')\
                        .execute()
                    
                    if update_response.data:
                        claimed_items_for_processing.append({
                            'queue_id': item['id'],
                            'source_document_id': item['source_document_id'],
                            'source_document_uuid': item['source_document_uuid'], # Assuming this is on the queue table
                            'attempts': item['retry_count'] + 1,
                            'existing_textract_job_id': item.get('textract_job_id') # Pass if present
                        })
                        logger.debug(f"Successfully claimed document queue ID: {item['id']}")
                    else:
                        logger.debug(f"Could not claim document {item['id']} - likely claimed by another processor")
                except Exception as e_claim:
                    logger.warning(f"Error trying to claim document {item['id']}: {e_claim}")
                    continue
            
            logger.info(f"Claimed {len(claimed_items_for_processing)} documents from queue.")
            return self._process_claimed_documents(claimed_items_for_processing, project_sql_id) # Pass project_sql_id
            
        except Exception as e:
            logger.error(f"Error claiming documents from queue: {e}", exc_info=True)
            return []

```

## 8. Final Checks & Considerations

-   **IAM Permissions:** Double-check that the IAM role/user has permissions for:
    -   `textract:StartDocumentTextDetection`, `textract:GetDocumentTextDetection` (and `textract:AnalyzeDocument` if used).
    -   `s3:GetObject` on `S3_PRIMARY_DOCUMENT_BUCKET`.
    -   `s3:PutObject` if Textract saves output to `TEXTRACT_OUTPUT_S3_BUCKET`.
    -   `sns:Publish` to `TEXTRACT_SNS_TOPIC_ARN` if SNS notifications are used.
    -   KMS permissions if `TEXTRACT_KMS_KEY_ID` is used.
-   **Error Handling:** Enhance error handling in `TextractProcessor` to catch specific `ClientError` exceptions from Textract (e.g., `InvalidS3ObjectException`, `UnsupportedDocumentException`) and update the `textract_jobs` and `source_documents` tables accordingly.
-   **Existing Files Migration:** If existing S3 keys in `source_documents` follow the `uploads/[timestamp]-[random].[ext]` pattern, and you want to standardize to `documents/{document_uuid}{file_ext}`, an SQL migration script or a Python utility will be needed to:
    1.  Rename objects in S3.
    2.  Update `s3_key` in `source_documents` table.
    This is outside the scope of the Python code refactor but important for consistency. The provided `s3_storage.py` will use the new UUID-based naming for *new* uploads.
-   **Configuration of `TEXTRACT_OUTPUT_S3_PREFIX`:** Ensure this prefix exists or can be created by Textract in the `TEXTRACT_OUTPUT_S3_BUCKET`.
-   **Idempotency:** The use of `ClientRequestToken` (e.g., based on `document_uuid`) in `start_document_text_detection` helps prevent duplicate jobs if a start request is retried.
-   **Long-Running Jobs & Queue Timeouts:** If Textract jobs frequently exceed `QueueProcessor.max_processing_time`, consider implementing a non-blocking Textract start (using SNS for completion notification) and splitting the processing into:
    1.  Queue task: Start Textract job, update status to 'submitted'.
    2.  SNS -> Lambda: On Textract completion, Lambda updates `textract_jobs` & `source_documents`, then re-queues/triggers next pipeline stage.
    This current guide implements a blocking poll within `process_single_document`.

This revised guide should align the Python implementation with Claude's schema recommendations and the goal of robust Textract integration.```markdown
# AWS Textract Refactor Implementation Guide (Revised with Claude's Feedback)

This guide incorporates Claude's feedback, including schema changes for `textract_jobs` and updates to `source_documents` and `document_processing_queue`. It assumes all SQL DDL commands for these changes have been successfully applied to the Supabase database.

## 1. Configuration Changes (`config.py`)

### 1.1. Remove Mistral OCR Configuration
**Action:** Delete all environment variables and Python constants related to Mistral OCR.
**Identified in `config.py`:**
- `MISTRAL_API_KEY`
- `USE_MISTRAL_FOR_OCR`
- `MISTRAL_OCR_MODEL`
- `MISTRAL_OCR_PROMPT`
- `MISTRAL_OCR_TIMEOUT`
- Remove `MISTRAL_API_KEY` check from `validate_cloud_services()` and `StageConfig`.
- Remove `USE_MISTRAL_FOR_OCR` and `MISTRAL_API_KEY` warning print.

### 1.2. Simplify S3 Bucket Configuration
**Action:** Modify S3 configuration to use `S3_PRIMARY_DOCUMENT_BUCKET` as the single private bucket.
**Identified in `config.py`:**
- Remove `S3_BUCKET_PUBLIC` and `S3_BUCKET_TEMP`.
- `S3_BUCKET_NAME` (line 118) will be replaced by `S3_PRIMARY_DOCUMENT_BUCKET`.
- Ensure `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION` are present.

```python
# config.py
# ... existing imports ...
# Project Identification (keep)
# Stage Definitions (keep)
# StageConfig (modify to remove Mistral checks)

class StageConfig:
    # ...
    def _build_stage_config(self) -> dict:
        base_config = {
            # ...
            "require_openai_key": False,
            # "require_mistral_key": False, # REMOVE
            "allow_local_fallback": True
        }
        if self.stage == STAGE_CLOUD_ONLY:
            return {
                # ...
                "require_openai_key": True,
                # "require_mistral_key": True, # REMOVE
                "allow_local_fallback": False
            }
        # ...
    
    def validate_requirements(self):
        errors = []
        if self._config["require_openai_key"] and not os.getenv("OPENAI_API_KEY"):
            errors.append(f"OPENAI_API_KEY required for Stage {self.stage}")
        # if self._config["require_mistral_key"] and not os.getenv("MISTRAL_API_KEY"): # REMOVE
        #     errors.append(f"MISTRAL_API_KEY required for Stage {self.stage}") # REMOVE
        if errors: raise ValueError("\n".join(errors))
        return True

# ... (validate_deployment_stage, BASE_DIR, SOURCE_DOCUMENT_DIR keep) ...

# S3 Configuration
USE_S3_FOR_INPUT = os.getenv("USE_S3_FOR_INPUT", "false").lower() in ("true", "1", "yes")
S3_PRIMARY_DOCUMENT_BUCKET = os.getenv("S3_PRIMARY_DOCUMENT_BUCKET", "samu-docs-private-upload") # UPDATED
S3_TEMP_DOWNLOAD_DIR = os.getenv("S3_TEMP_DOWNLOAD_DIR", str(BASE_DIR / "s3_downloads"))

# AWS Configuration (ensure these are present and correctly named)
AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')
AWS_DEFAULT_REGION = os.getenv('AWS_DEFAULT_REGION', 'us-east-1') # Example, use your target region

# REMOVE S3_BUCKET_PRIVATE, S3_BUCKET_PUBLIC, S3_BUCKET_TEMP explicit definitions if they were separate from primary.
# S3_BUCKET_PRIVATE (line 123) is now S3_PRIMARY_DOCUMENT_BUCKET.
# S3_BUCKET_PUBLIC (line 124) - REMOVE
# S3_BUCKET_TEMP (line 125) - REMOVE

# ... (File naming, Supabase, Processing Options keep) ...

# REMOVE Mistral OCR Configuration section (lines 132-137)
# MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
# USE_MISTRAL_FOR_OCR = os.getenv("USE_MISTRAL_FOR_OCR", "true").lower() in ("true", "1", "yes")
# MISTRAL_OCR_MODEL = os.getenv("MISTRAL_OCR_MODEL", "mistral-ocr-latest")
# MISTRAL_OCR_PROMPT = os.getenv("MISTRAL_OCR_PROMPT", "...")
# MISTRAL_OCR_TIMEOUT = int(os.getenv("MISTRAL_OCR_TIMEOUT", "120"))

# ... (Qwen2-VL OCR Configuration, OpenAI Configuration keep) ...
# ... (Stage Management Configuration, initialize stage_config, apply stage-specific overrides keep) ...

# NER Configuration (keep)
# Queue Processing (keep)
# Make sure required directories exist (keep)
# Validate required environment variables (keep Supabase, remove Mistral warning)

# REMOVE Mistral API key warning
# if USE_MISTRAL_FOR_OCR and not MISTRAL_API_KEY:
#     print("WARNING: Mistral OCR is enabled but MISTRAL_API_KEY environment variable is not set.")
#     print("Text extraction from PDFs may fail. Please set this environment variable.")

# Add AWS Textract Configuration (NEW SECTION)
TEXTRACT_FEATURE_TYPES = os.getenv('TEXTRACT_FEATURE_TYPES', 'TABLES,FORMS').split(',')
TEXTRACT_CONFIDENCE_THRESHOLD = float(os.getenv('TEXTRACT_CONFIDENCE_THRESHOLD', '80.0'))
TEXTRACT_MAX_RESULTS_PER_PAGE = int(os.getenv('TEXTRACT_MAX_RESULTS_PER_PAGE', '1000'))
TEXTRACT_USE_ASYNC_FOR_PDF = os.getenv('TEXTRACT_USE_ASYNC_FOR_PDF', 'true').lower() in ('true', '1', 'yes')
TEXTRACT_ASYNC_MAX_POLLING_TIME_SECONDS = int(os.getenv('TEXTRACT_ASYNC_MAX_POLLING_TIME_SECONDS', '600'))
TEXTRACT_ASYNC_POLLING_INTERVAL_SECONDS = int(os.getenv('TEXTRACT_ASYNC_POLLING_INTERVAL_SECONDS', '5'))
TEXTRACT_ASYNC_INITIAL_DELAY_SECONDS = int(os.getenv('TEXTRACT_ASYNC_INITIAL_DELAY_SECONDS', '5'))
TEXTRACT_SNS_TOPIC_ARN = os.getenv('TEXTRACT_SNS_TOPIC_ARN')
TEXTRACT_SNS_ROLE_ARN = os.getenv('TEXTRACT_SNS_ROLE_ARN')
TEXTRACT_OUTPUT_S3_BUCKET = os.getenv('TEXTRACT_OUTPUT_S3_BUCKET', S3_PRIMARY_DOCUMENT_BUCKET)
TEXTRACT_OUTPUT_S3_PREFIX = os.getenv('TEXTRACT_OUTPUT_S3_PREFIX', 'textract-output/')
TEXTRACT_KMS_KEY_ID = os.getenv('TEXTRACT_KMS_KEY_ID')

# Update validate_cloud_services()
def validate_cloud_services():
    validations = []
    # ... (OpenAI validation - keep) ...
    if USE_OPENAI_FOR_ENTITY_EXTRACTION or USE_OPENAI_FOR_STRUCTURED_EXTRACTION: # or other OpenAI uses
        if not OPENAI_API_KEY:
            validations.append("OpenAI API key missing but OpenAI services enabled")
        else:
            validations.append("✓ OpenAI API key configured")

    # AWS Credentials Validation for Textract
    if not AWS_ACCESS_KEY_ID or not AWS_SECRET_ACCESS_KEY or not AWS_DEFAULT_REGION:
        validations.append("AWS credentials (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_DEFAULT_REGION) are required for Textract OCR.")
    else:
        validations.append("✓ AWS credentials configured for Textract.")
    
    # REMOVE Mistral validation section
    # if USE_MISTRAL_FOR_OCR:
    #     if not MISTRAL_API_KEY:
    #         validations.append("Mistral API key missing but Mistral OCR enabled")
    #     else:
    #         validations.append("✓ Mistral API key configured")
    return validations

# ... (get_stage_info, reset_stage_config, set_stage_for_testing - review for Mistral remnants) ...
# In get_stage_info(), remove Mistral from validations.
# In reset_stage_config() and set_stage_for_testing(), ensure no Mistral-specific logic remains.
```

## 2. S3 Utilities Update (`s3_storage.py`)

### 2.1. Remove Public/Temp Bucket Functions
**Action:** Delete `copy_to_public_bucket()`, `generate_presigned_url_for_ocr()`, `cleanup_ocr_file()`. These are specific to the old Mistral workflow.

### 2.2. Modify `upload_document_with_uuid_naming()`
**Action:** Update S3 key generation to use `documents/{document_uuid}{file_ext}` pattern. `original_filename` is used for metadata and determining extension, but the S3 key itself is based on `document_uuid`.
**File:** `s3_storage.py`

```python
# s3_storage.py
import boto3
import logging
import os
import hashlib
from typing import Optional, Dict # Keep Dict
from datetime import datetime
from botocore.exceptions import ClientError, NoCredentialsError, PartialCredentialsError # Ensure these are imported

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
        ext = os.path.splitext(filename)[1].lower()
        content_types = {
            '.pdf': 'application/pdf', '.txt': 'text/plain', '.doc': 'application/msword',
            '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
            '.tiff': 'image/tiff', '.tif': 'image/tiff',
        }
        return content_types.get(ext, 'application/octet-stream')

    def upload_document_with_uuid_naming(self, local_file_path: str, document_uuid: str,
                                       original_filename: str) -> Dict[str, any]:
        """Upload document with UUID-based naming to the primary private S3 bucket."""
        file_ext = os.path.splitext(original_filename)[1].lower()
        # S3 key format: documents/{document_uuid}{file_ext}
        s3_key = f"documents/{document_uuid}{file_ext}"

        with open(local_file_path, 'rb') as f:
            file_content = f.read()
            md5_hash = hashlib.md5(file_content).hexdigest()

        content_type = self._get_content_type(original_filename)
        # S3 object metadata (distinct from Supabase table metadata_json)
        s3_object_metadata = {
            'original-filename': original_filename, # Store the original name here
            'document-uuid': document_uuid,
            'upload-timestamp': datetime.now().isoformat(),
            'content-type': content_type
        }

        try:
            self.s3_client.put_object(
                Bucket=self.private_bucket_name,
                Key=s3_key,
                Body=file_content,
                Metadata=s3_object_metadata, # Use the new variable name for clarity
                ContentType=content_type
            )
            logger.info(f"Uploaded {original_filename} to s3://{self.private_bucket_name}/{s3_key}")
            return {
                's3_key': s3_key,
                's3_bucket': self.private_bucket_name,
                's3_region': AWS_DEFAULT_REGION,
                'md5_hash': md5_hash,
                'file_size': len(file_content),
                'metadata': s3_object_metadata # Return the S3 metadata that was set
            }
        except Exception as error:
            self.handle_s3_errors(error)
            raise

    def get_s3_document_location(self, s3_key: str, s3_bucket: Optional[str] = None, version_id: Optional[str] = None) -> Dict[str, any]:
        bucket_name = s3_bucket or self.private_bucket_name
        s3_object_loc = {'S3Object': {'Bucket': bucket_name, 'Name': s3_key}}
        if version_id:
            s3_object_loc['S3Object']['Version'] = version_id
        return s3_object_loc

    def check_s3_object_exists(self, s3_key: str, s3_bucket: Optional[str] = None) -> bool:
        bucket_name = s3_bucket or self.private_bucket_name
        try:
            self.s3_client.head_object(Bucket=bucket_name, Key=s3_key)
            return True
        except ClientError as e:
            if e.response['Error']['Code'] == '404': return False
            else: logger.error(f"Error checking S3 object s3://{bucket_name}/{s3_key}: {e}"); raise
        except Exception as e: # Catch any other non-ClientError exceptions
            logger.error(f"Unexpected error checking S3 object s3://{bucket_name}/{s3_key}: {e}"); raise

    def handle_s3_errors(self, error):
        if isinstance(error, NoCredentialsError): logger.error(f"S3 credentials not found: {error}"); raise ValueError(f"S3 credentials configuration error: {error}")
        elif isinstance(error, PartialCredentialsError): logger.error(f"Incomplete S3 credentials: {error}"); raise ValueError(f"Incomplete S3 credentials: {error}")
        elif isinstance(error, ClientError):
            error_code = error.response.get('Error', {}).get('Code'); error_message = error.response.get('Error', {}).get('Message')
            logger.error(f"S3 ClientError - Code: {error_code}, Message: {error_message}, Full Error: {error}")
            if error_code == 'NoSuchBucket': raise ValueError(f"S3 bucket '{self.private_bucket_name}' does not exist.")
            elif error_code == 'AccessDenied': raise PermissionError(f"S3 access denied for operation on bucket '{self.private_bucket_name}'. Check IAM permissions.")
            else: raise
        else: logger.error(f"Unknown S3 error: {error}"); raise
```

## 3. Supabase Utilities Update (`supabase_utils.py`)

### 3.1. Add Methods for `textract_jobs` Table
**Action:** Implement `create_textract_job_entry`, `update_textract_job_status`, `get_textract_job_by_job_id`, and `update_source_document_with_textract_outcome`.
**File:** `supabase_utils.py`

```python
# supabase_utils.py
# ... (existing SupabaseManager class and methods) ...
# Add imports from config for Textract settings used as defaults
from config import TEXTRACT_CONFIDENCE_THRESHOLD, TEXTRACT_SNS_TOPIC_ARN 
import json # Ensure json is imported
from datetime import datetime # Ensure datetime is imported
from typing import List, Dict, Optional, Tuple # Ensure these are imported

class SupabaseManager:
    # ... (existing __init__ and other methods) ...

    def create_textract_job_entry(self, source_document_id: int, document_uuid: str, job_id: str,
                                 s3_input_bucket: str, s3_input_key: str,
                                 job_type: str = 'DetectDocumentText',
                                 feature_types: Optional[List[str]] = None,
                                 s3_output_bucket: Optional[str] = None,
                                 s3_output_key: Optional[str] = None,
                                 confidence_threshold: Optional[float] = None, # Default from config if None
                                 client_request_token: Optional[str] = None,
                                 job_tag: Optional[str] = None,
                                 sns_topic_arn_param: Optional[str] = None # Default from config if None
                                 ) -> Optional[int]:
        logger.info(f"Creating Textract job entry for source_doc_id: {source_document_id}, job_id: {job_id}")
        
        # Use defaults from config if parameters are None
        final_confidence_threshold = confidence_threshold if confidence_threshold is not None else TEXTRACT_CONFIDENCE_THRESHOLD
        final_sns_topic_arn = sns_topic_arn_param if sns_topic_arn_param is not None else TEXTRACT_SNS_TOPIC_ARN

        job_data = {
            'source_document_id': source_document_id,
            'document_uuid': document_uuid,
            'job_id': job_id,
            'job_type': job_type,
            's3_input_bucket': s3_input_bucket,
            's3_input_key': s3_input_key,
            'job_status': 'SUBMITTED',
            'confidence_threshold': final_confidence_threshold,
            'client_request_token': client_request_token,
            'job_tag': job_tag,
            'sns_topic_arn': final_sns_topic_arn, # Use the resolved value
            'created_at': datetime.now().isoformat(), # Set creation time
            'started_at': datetime.now().isoformat() # Set job submission time as started_at
        }
        if feature_types:
            job_data['feature_types'] = feature_types # Supabase client handles list to PG array
        if s3_output_bucket:
            job_data['s3_output_bucket'] = s3_output_bucket
        if s3_output_key:
            job_data['s3_output_key'] = s3_output_key
        
        try:
            response = self.client.table('textract_jobs').insert(job_data).execute()
            if response.data:
                return response.data[0]['id']
            logger.error(f"Failed to insert Textract job entry, response: {response.error if response.error else 'No data returned'}")
            return None
        except Exception as e:
            logger.error(f"Error creating Textract job entry: {e}", exc_info=True)
            raise

    def update_textract_job_status(self, job_id: str, job_status: str, # job_status should match ENUM values
                                   page_count: Optional[int] = None,
                                   processed_pages: Optional[int] = None,
                                   avg_confidence: Optional[float] = None,
                                   warnings_json: Optional[List[Dict]] = None, # Expect list of dicts for JSONB
                                   error_message: Optional[str] = None,
                                   s3_output_key_val: Optional[str] = None, # Renamed to avoid conflict
                                   completed_at_override: Optional[datetime] = None
                                   ) -> bool:
        logger.info(f"Updating Textract job_id: {job_id} to status: {job_status}")
        update_data = {'job_status': job_status}
        if page_count is not None:
            update_data['page_count'] = page_count
        if processed_pages is not None:
            update_data['processed_pages'] = processed_pages
        if avg_confidence is not None:
            update_data['avg_confidence'] = avg_confidence # Assumes DB column is numeric
        if warnings_json is not None: # Ensure it's a list of dicts, or a dict for JSONB
            update_data['warnings'] = warnings_json # Supabase client handles dict/list to JSONB
        if error_message:
            update_data['error_message'] = error_message
        if s3_output_key_val:
            update_data['s3_output_key'] = s3_output_key_val
            
        # Statuses that indicate completion
        if job_status.upper() in ['SUCCEEDED', 'FAILED', 'PARTIAL_SUCCESS']: # Match Textract API statuses for this check
            update_data['completed_at'] = (completed_at_override or datetime.now()).isoformat()

        try:
            response = self.client.table('textract_jobs').update(update_data).eq('job_id', job_id).execute()
            if response.data or not response.error:
                logger.info(f"Textract job {job_id} updated successfully.")
                return True
            logger.warning(f"Failed to update Textract job {job_id} or job not found. Response error: {response.error}")
            return False
        except Exception as e:
            logger.error(f"Error updating Textract job entry for job_id {job_id}: {e}", exc_info=True)
            raise

    def get_textract_job_by_job_id(self, job_id: str) -> Optional[Dict]:
        try:
            response = self.client.table('textract_jobs').select('*').eq('job_id', job_id).maybe_single().execute()
            return response.data
        except Exception as e:
            logger.error(f"Error fetching Textract job by job_id {job_id}: {e}", exc_info=True)
            return None

    def update_source_document_with_textract_outcome(self, source_doc_sql_id: int,
                                                     textract_job_id_val: str, # Renamed to avoid conflict
                                                     # Use ENUM values for source_documents.textract_job_status
                                                     textract_job_status_val: str, 
                                                     ocr_provider_enum_val: str = 'textract',
                                                     raw_text_val: Optional[str] = None,
                                                     ocr_metadata_json_val: Optional[List[Dict]] = None,
                                                     textract_warnings_json_val: Optional[List[Dict]] = None,
                                                     textract_confidence_val: Optional[float] = None,
                                                     textract_output_s3_key_val: Optional[str] = None,
                                                     job_started_at_val: Optional[datetime] = None,
                                                     job_completed_at_val: Optional[datetime] = None):
        logger.info(f"Updating source_document {source_doc_sql_id} with Textract job ({textract_job_id_val}) outcome: {textract_job_status_val}")
        
        update_payload = {
            'textract_job_id': textract_job_id_val,
            'textract_job_status': textract_job_status_val, # Should match ENUM in source_documents
            'ocr_provider': ocr_provider_enum_val, # Should match ocr_provider ENUM
            'updated_at': datetime.now().isoformat()
        }
        if raw_text_val is not None:
            update_payload['raw_extracted_text'] = raw_text_val
            # Set main status based on Textract job status
            if textract_job_status_val.lower() in ['succeeded', 'partial_success']:
                 update_payload['initial_processing_status'] = 'ocr_complete_pending_doc_node'
            elif textract_job_status_val.lower() == 'failed':
                 update_payload['initial_processing_status'] = 'extraction_failed'
            # 'submitted', 'in_progress' might map to 'ocr_in_progress' or similar

        if ocr_metadata_json_val is not None: # This is the custom page-level metadata
            update_payload['ocr_metadata_json'] = json.dumps(ocr_metadata_json_val) # Ensure it's stringified
        if textract_warnings_json_val is not None:
            update_payload['textract_warnings'] = textract_warnings_json_val # For JSONB
        if textract_confidence_val is not None:
            update_payload['textract_confidence_avg'] = textract_confidence_val
        if textract_output_s3_key_val:
            update_payload['textract_output_s3_key'] = textract_output_s3_key_val
        
        if job_started_at_val:
            update_payload['textract_job_started_at'] = job_started_at_val.isoformat()
        if job_completed_at_val:
            update_payload['textract_job_completed_at'] = job_completed_at_val.isoformat()
            update_payload['ocr_completed_at'] = job_completed_at_val.isoformat()
            if job_started_at_val:
                duration = (job_completed_at_val - job_started_at_val).total_seconds()
                update_payload['ocr_processing_seconds'] = int(duration)
        
        try:
            self.client.table('source_documents').update(update_payload).eq('id', source_doc_sql_id).execute()
            logger.info(f"Source_document {source_doc_sql_id} updated with Textract job {textract_job_id_val} info.")
        except Exception as e:
            logger.error(f"Error updating source_document {source_doc_sql_id} with Textract info: {e}", exc_info=True)
            raise
```

## 4. New Textract Utilities (`textract_utils.py`)

### 4.1. Initialize `TextractProcessor` with `SupabaseManager`
**Action:** Pass `SupabaseManager` instance to `TextractProcessor`. Modify `start_document_text_detection` and `get_text_detection_results` to use `db_manager` for creating/updating `textract_jobs` and `source_documents` tables.
**File:** `textract_utils.py`

```python
# textract_utils.py
import boto3
import time
import json # Keep
import logging
from typing import List, Dict, Tuple, Optional, Any # Keep
from botocore.exceptions import ClientError # Keep
from collections import defaultdict # Keep
import uuid # For client request token

# Import SupabaseManager for DB interactions
from supabase_utils import SupabaseManager
# Import necessary configurations from config.py
from config import (
    AWS_DEFAULT_REGION, TEXTRACT_ASYNC_MAX_POLLING_TIME_SECONDS, TEXTRACT_ASYNC_POLLING_INTERVAL_SECONDS,
    TEXTRACT_ASYNC_INITIAL_DELAY_SECONDS, TEXTRACT_SNS_TOPIC_ARN, TEXTRACT_SNS_ROLE_ARN,
    TEXTRACT_OUTPUT_S3_BUCKET, TEXTRACT_OUTPUT_S3_PREFIX, TEXTRACT_KMS_KEY_ID,
    TEXTRACT_CONFIDENCE_THRESHOLD, TEXTRACT_MAX_RESULTS_PER_PAGE #, TEXTRACT_ANALYZE_FEATURE_TYPES (if used by AnalyzeDocument methods)
)
from datetime import datetime # For timestamps

logger = logging.getLogger(__name__)

class TextractProcessor:
    def __init__(self, db_manager: SupabaseManager, region_name: str = AWS_DEFAULT_REGION):
        self.client = boto3.client('textract', region_name=region_name)
        self.db_manager = db_manager
        logger.info(f"TextractProcessor initialized for region: {region_name} with DBManager.")

    def start_document_text_detection(self, s3_bucket: str, s3_key: str,
                                    source_doc_id: int, document_uuid_from_db: str,
                                    client_request_token_param: Optional[str] = None, # Renamed for clarity
                                    job_tag_param: Optional[str] = None) -> Optional[str]: # Renamed for clarity
        try:
            params = {
                'DocumentLocation': {'S3Object': {'Bucket': s3_bucket, 'Name': s3_key}}
            }
            final_client_request_token = client_request_token_param or f"textract-detect-{document_uuid_from_db}"
            params['ClientRequestToken'] = final_client_request_token
            if job_tag_param: params['JobTag'] = job_tag_param
            
            final_sns_topic_arn = TEXTRACT_SNS_TOPIC_ARN
            final_sns_role_arn = TEXTRACT_SNS_ROLE_ARN
            if final_sns_topic_arn and final_sns_role_arn:
                params['NotificationChannel'] = {'SNSTopicArn': final_sns_topic_arn, 'RoleArn': final_sns_role_arn}
            
            final_output_s3_bucket = TEXTRACT_OUTPUT_S3_BUCKET
            final_output_s3_prefix = TEXTRACT_OUTPUT_S3_PREFIX
            if final_output_s3_bucket and final_output_s3_prefix:
                 params['OutputConfig'] = {'S3Bucket': final_output_s3_bucket, 'S3Prefix': final_output_s3_prefix.rstrip('/') + '/'}
            
            final_kms_key_id = TEXTRACT_KMS_KEY_ID
            if final_kms_key_id: params['KMSKeyId'] = final_kms_key_id

            logger.info(f"Starting Textract job for s3://{s3_bucket}/{s3_key} (source_id: {source_doc_id}) with ClientRequestToken: {final_client_request_token}")
            api_response = self.client.start_document_text_detection(**params)
            job_id = api_response.get('JobId')
            job_submission_time = datetime.now()

            if job_id:
                logger.info(f"Textract job started. JobId: {job_id} for s3://{s3_bucket}/{s3_key}")
                
                # s3_output_key for textract_jobs table
                textract_job_output_key = None
                if params.get('OutputConfig'):
                    # Textract typically creates subfolders by JobId within the prefix.
                    # Example: s3://bucket/prefix/job_id/1, s3://bucket/prefix/job_id/output.json
                    # For simplicity, store the prefix; actual file names vary.
                    textract_job_output_key = f"{params['OutputConfig']['S3Prefix'].rstrip('/')}/{job_id}/"


                self.db_manager.create_textract_job_entry(
                    source_document_id=source_doc_id,
                    document_uuid=document_uuid_from_db,
                    job_id=job_id,
                    s3_input_bucket=s3_bucket,
                    s3_input_key=s3_key,
                    job_type='DetectDocumentText',
                    s3_output_bucket=params.get('OutputConfig', {}).get('S3Bucket'),
                    s3_output_key=textract_job_output_key, 
                    confidence_threshold=TEXTRACT_CONFIDENCE_THRESHOLD, # From config
                    client_request_token=final_client_request_token,
                    job_tag=job_tag_param,
                    sns_topic_arn_param=params.get('NotificationChannel', {}).get('SNSTopicArn')
                )
                # Update source_documents with 'submitted' status
                self.db_manager.update_source_document_with_textract_outcome(
                    source_doc_sql_id=source_doc_id,
                    textract_job_id_val=job_id,
                    textract_job_status_val='submitted', # Matches ENUM 'submitted'
                    job_started_at_val=job_submission_time
                )
            return job_id
        except ClientError as e:
            error_msg = e.response.get('Error', {}).get('Message', str(e))
            logger.error(f"ClientError starting Textract job for s3://{s3_bucket}/{s3_key} (source_id: {source_doc_id}): {error_msg}")
            # Update source_documents with 'failed' status
            self.db_manager.update_source_document_with_textract_outcome(
                source_doc_sql_id=source_doc_id,
                textract_job_id_val="N/A_JOB_START_FAILURE",
                textract_job_status_val='failed' # Matches ENUM 'failed'
            )
            # No job_id, so cannot update textract_jobs table here directly without one.
            # Consider creating a textract_jobs entry with a placeholder job_id and 'FAILED' status if needed.
            raise # Re-raise to be handled by the caller

    def get_text_detection_results(self, job_id: str, source_doc_id: int) -> Tuple[Optional[List[Dict[str, Any]]], Optional[Dict[str, Any]]]:
        logger.info(f"Polling for Textract results. JobId: {job_id}, SourceDocId: {source_doc_id}")
        polling_start_time = time.time()
        
        # Fetch initial job start time from DB for accurate duration calculation
        job_entry_from_db = self.db_manager.get_textract_job_by_job_id(job_id)
        db_recorded_job_start_time_str = job_entry_from_db.get('started_at') if job_entry_from_db else None
        # Convert ISO string to datetime object carefully
        actual_job_start_time = None
        if db_recorded_job_start_time_str:
            try:
                # Handle potential timezone info (e.g., +00:00 or Z) if present
                if '+' in db_recorded_job_start_time_str:
                    actual_job_start_time = datetime.fromisoformat(db_recorded_job_start_time_str)
                else: # If no explicit timezone, assume UTC or parse without forcing tz
                    actual_job_start_time = datetime.fromisoformat(db_recorded_job_start_time_str.replace("Z", ""))
            except ValueError:
                 logger.warning(f"Could not parse job start time from DB: {db_recorded_job_start_time_str}")
                 actual_job_start_time = datetime.now() # Fallback
        else:
            actual_job_start_time = datetime.now() # Fallback if not found

        time.sleep(TEXTRACT_ASYNC_INITIAL_DELAY_SECONDS)

        while True:
            elapsed_polling_time = time.time() - polling_start_time
            if elapsed_polling_time > TEXTRACT_ASYNC_MAX_POLLING_TIME_SECONDS:
                logger.error(f"Textract job {job_id} polling timed out after {elapsed_polling_time:.2f} seconds.")
                self.db_manager.update_textract_job_status(job_id, 'FAILED', error_message='Polling Timeout', completed_at_override=datetime.now())
                self.db_manager.update_source_document_with_textract_outcome(source_doc_sql_id=source_doc_id, textract_job_id_val=job_id, textract_job_status_val='failed', job_completed_at_val=datetime.now(), job_started_at_val=actual_job_start_time)
                return None, None

            try:
                api_response = self.client.get_document_text_detection(JobId=job_id, MaxResults=TEXTRACT_MAX_RESULTS_PER_PAGE)
                job_status_from_api = api_response.get('JobStatus') # e.g. IN_PROGRESS, SUCCEEDED
                logger.debug(f"Textract job {job_id} API status: {job_status_from_api}. Elapsed polling: {elapsed_polling_time:.2f}s")

                # Map API status to DB enum values for textract_jobs.job_status
                # And source_documents.textract_job_status
                db_compliant_job_status = 'in_progress' # Default for ongoing
                if job_status_from_api == 'SUCCEEDED': db_compliant_job_status = 'succeeded'
                elif job_status_from_api == 'FAILED': db_compliant_job_status = 'failed'
                elif job_status_from_api == 'PARTIAL_SUCCESS': db_compliant_job_status = 'partial_success'
                elif job_status_from_api == 'IN_PROGRESS': db_compliant_job_status = 'in_progress'
                else: db_compliant_job_status = 'in_progress' # Or handle unknown statuses

                # Update DB with current status
                self.db_manager.update_textract_job_status(job_id, db_compliant_job_status) # Updates textract_jobs table
                self.db_manager.update_source_document_with_textract_outcome(
                    source_doc_sql_id=source_doc_id, textract_job_id_val=job_id, 
                    textract_job_status_val=db_compliant_job_status, # This status for source_documents.textract_job_status
                    job_started_at_val=actual_job_start_time
                )


                if job_status_from_api in ['SUCCEEDED', 'PARTIAL_SUCCESS']:
                    all_blocks = api_response.get('Blocks', [])
                    document_api_metadata = api_response.get('DocumentMetadata', {})
                    api_warnings_list = api_response.get('Warnings') # This is a list
                    next_token = api_response.get('NextToken')

                    while next_token:
                        time.sleep(0.5)
                        page_response = self.client.get_document_text_detection(JobId=job_id, MaxResults=TEXTRACT_MAX_RESULTS_PER_PAGE, NextToken=next_token)
                        all_blocks.extend(page_response.get('Blocks', []))
                        page_api_warnings = page_response.get('Warnings')
                        if page_api_warnings:
                            if api_warnings_list is None: api_warnings_list = []
                            api_warnings_list.extend(page_api_warnings)
                        next_token = page_response.get('NextToken')
                    
                    avg_confidence_val = None
                    if all_blocks: # Calculate average confidence from blocks that have it
                        confidences = [b.get('Confidence',0) for b in all_blocks if 'Confidence' in b and isinstance(b.get('Confidence'), (int, float))]
                        if confidences: avg_confidence_val = round(sum(confidences) / len(confidences), 2)
                    
                    job_completion_time = datetime.now()
                    self.db_manager.update_textract_job_status(
                        job_id, db_compliant_job_status,
                        page_count=document_api_metadata.get('Pages'),
                        processed_pages=document_api_metadata.get('Pages'), # Assuming all processed
                        avg_confidence=avg_confidence_val,
                        warnings_json=api_warnings_list, # Pass as list for JSONB
                        completed_at_override=job_completion_time
                    )
                    # Final update to source_documents, including raw_text if successful
                    # The raw_text is derived from blocks by the caller of this function.
                    # This function returns blocks; the caller (ocr_extraction) processes them to text.
                    # Then ocr_extraction updates source_documents with the text.
                    # Here, we just update the status and metadata related to the job completion.
                    self.db_manager.update_source_document_with_textract_outcome(
                        source_doc_sql_id=source_doc_id, textract_job_id_val=job_id, textract_job_status_val=db_compliant_job_status,
                        # ocr_metadata_json_val will be set by caller after processing blocks
                        textract_warnings_json_val=api_warnings_list,
                        textract_confidence_val=avg_confidence_val,
                        job_completed_at_val=job_completion_time,
                        job_started_at_val=actual_job_start_time
                        # textract_output_s3_key is logged at job creation if OutputConfig is used
                    )
                    logger.info(f"Textract job {job_id} {job_status_from_api}. Retrieved {len(all_blocks)} blocks. Pages: {document_api_metadata.get('Pages')}")
                    return all_blocks, document_api_metadata
                
                elif job_status_from_api == 'FAILED':
                    error_msg_from_api = api_response.get('StatusMessage', 'Unknown Textract job failure')
                    api_warnings_list = api_response.get('Warnings')
                    logger.error(f"Textract job {job_id} FAILED. StatusMessage: {error_msg_from_api}, Warnings: {api_warnings_list}")
                    job_fail_time = datetime.now()
                    self.db_manager.update_textract_job_status(job_id, 'failed', error_message=error_msg_from_api, warnings_json=api_warnings_list, completed_at_override=job_fail_time)
                    self.db_manager.update_source_document_with_textract_outcome(source_doc_sql_id=source_doc_id, textract_job_id_val=job_id, textract_job_status_val='failed', job_completed_at_val=job_fail_time, job_started_at_val=actual_job_start_time, textract_warnings_json_val=api_warnings_list)
                    return None, None
                
                time.sleep(TEXTRACT_ASYNC_POLLING_INTERVAL_SECONDS)

            except ClientError as e:
                error_message_poll = e.response.get('Error',{}).get('Message', str(e))
                logger.error(f"ClientError while polling job {job_id}: {error_message_poll}")
                self.db_manager.update_textract_job_status(job_id, 'failed', error_message=f"Polling ClientError: {error_message_poll[:240]}") # Truncate if needed
                self.db_manager.update_source_document_with_textract_outcome(source_doc_sql_id=source_doc_id, textract_job_id_val=job_id, textract_job_status_val='failed')
                time.sleep(TEXTRACT_ASYNC_POLLING_INTERVAL_SECONDS * 2) # Longer sleep on polling error
            except Exception as e_poll: # Catch other non-ClientError exceptions during polling
                logger.error(f"Unexpected error while polling job {job_id}: {e_poll}", exc_info=True)
                self.db_manager.update_textract_job_status(job_id, 'failed', error_message=f"Polling Exception: {str(e_poll)[:240]}")
                self.db_manager.update_source_document_with_textract_outcome(source_doc_sql_id=source_doc_id, textract_job_id_val=job_id, textract_job_status_val='failed')
                return None, None # Critical error during polling

    def process_textract_blocks_to_text(self, blocks: List[Dict[str, Any]], doc_api_metadata: Dict[str, Any]) -> str:
        if not blocks: return ""
        page_texts = defaultdict(list)
        # Ensure LINE blocks are processed
        line_blocks_from_api = [block for block in blocks if block['BlockType'] == 'LINE']
        
        for line in line_blocks_from_api:
            page_number = line.get('Page', 1)
            # Use global TEXTRACT_CONFIDENCE_THRESHOLD for filtering
            if line.get('Confidence', 0.0) < TEXTRACT_CONFIDENCE_THRESHOLD:
                logger.debug(f"Skipping LINE block (Page {page_number}, Confidence {line.get('Confidence')}) Text: '{line.get('Text', '')[:50]}...'")
                continue
            
            geometry = line.get('Geometry', {}).get('BoundingBox', {})
            if not geometry: # Handle missing geometry
                logger.warning(f"LINE block (Page {page_number}) missing BoundingBox. Text: '{line.get('Text', '')[:50]}...'")
                # Add with placeholder sort keys or append directly
                page_texts[page_number].append({'text': line.get('Text', ''), 'top': float('inf'), 'left': float('inf')})
                continue

            page_texts[page_number].append({
                'text': line.get('Text', ''),
                'top': geometry.get('Top', 0.0),
                'left': geometry.get('Left', 0.0)
            })

        full_text_parts = []
        # Use page count from Textract's DocumentMetadata if available
        num_pages_from_api = doc_api_metadata.get('Pages', 0) if doc_api_metadata else 0
        # If no pages in API metadata, infer from processed blocks
        max_page_from_blocks = max(page_texts.keys() or [0])
        total_pages_to_render = max(num_pages_from_api, max_page_from_blocks)

        for page_num_iter in range(1, total_pages_to_render + 1):
            if page_num_iter in page_texts and page_texts[page_num_iter]:
                # Sort lines by 'top', then 'left' for reading order
                sorted_lines = sorted(page_texts[page_num_iter], key=lambda item: (item['top'], item['left']))
                page_content_str = "\n".join([item['text'] for item in sorted_lines])
                full_text_parts.append(page_content_str)
            else:
                # Represent empty or un-processable pages clearly
                full_text_parts.append(f"[Page {page_num_iter} - No text meeting confidence threshold or page not processed]")
        
        return "\n\n<END_OF_PAGE>\n\n".join(full_text_parts).strip()

    # Placeholder for extract_tables_from_blocks - keep as is or enhance if table data is crucial
    # def extract_tables_from_blocks(...):
```

## 5. OCR Extraction Logic Update (`ocr_extraction.py`)

### 5.1. Remove Mistral-related Functions and Imports
**Action:** Delete `extract_text_from_pdf_mistral_ocr()`. Remove imports for `mistral_utils` and `generate_document_url` (if solely for Mistral).

### 5.2. Update `extract_text_from_pdf_textract()`
**Action:** This function is the core PDF processor. It needs to:
    1. Accept `db_manager` and `source_doc_sql_id`.
    2. Get `document_uuid` from the DB using `source_doc_sql_id`.
    3. Handle local paths by uploading to S3 (using `document_uuid` for S3 key).
    4. Handle Supabase storage URLs by downloading, then uploading to S3.
    5. Call `textract_processor.start_document_text_detection` and `get_text_detection_results`.
    6. Process returned blocks into text.
    7. Populate `page_level_metadata` for `ocr_metadata_json`.
    8. Update `source_documents` table with the final extracted text, `ocr_metadata_json`, and status via `db_manager.update_source_document_with_textract_outcome`.

**File:** `ocr_extraction.py`
```python
# ocr_extraction.py
import os
import logging
# import fitz # PyMuPDF - only if render_pdf_page_to_image is still used (e.g., for Qwen)
# import torch # Only if Qwen or other local models are used
import time
# import boto3 # boto3 is used within TextractProcessor
import uuid # Keep for fallback UUIDs if needed
import json # Keep
import tempfile # For downloading from Supabase storage
import requests # For downloading from Supabase storage

# Config imports
from config import (
    # QWEN2_VL_OCR_PROMPT, QWEN2_VL_OCR_MAX_NEW_TOKENS, # Keep if Qwen is a fallback
    DEPLOYMENT_STAGE, STAGE_CLOUD_ONLY, S3_PRIMARY_DOCUMENT_BUCKET, TEXTRACT_USE_ASYNC_FOR_PDF,
    AWS_DEFAULT_REGION, # Needed by S3StorageManager if not passed
    # TEXTRACT_CONFIDENCE_THRESHOLD # Used within TextractProcessor
)
# Model init imports (keep if Qwen or other local models are fallbacks for non-PDFs)
# from models_init import (
#     get_qwen2_vl_ocr_model, get_qwen2_vl_ocr_processor, 
#     get_qwen2_vl_ocr_device, get_process_vision_info,
#     get_whisper_model, should_load_local_models
# )

# Service specific utils
from textract_utils import TextractProcessor
from s3_storage import S3StorageManager
from supabase_utils import SupabaseManager # For DB interaction

from typing import List, Dict, Tuple, Optional, Any # Keep for type hints

logger = logging.getLogger(__name__)

# _download_supabase_file_to_temp (keep as defined in previous iteration)
def _download_supabase_file_to_temp(supabase_url: str) -> Optional[str]:
    try:
        logger.info(f"Downloading from Supabase storage URL: {supabase_url}")
        response = requests.get(supabase_url, stream=True)
        response.raise_for_status()
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        with open(temp_file.name, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192): f.write(chunk)
        logger.info(f"Successfully downloaded to temporary file: {temp_file.name}")
        return temp_file.name
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to download from Supabase URL {supabase_url}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error downloading from Supabase URL {supabase_url}: {e}", exc_info=True)
        return None

# render_pdf_page_to_image, extract_text_from_pdf_qwen_vl_ocr:
# Keep these if Qwen-VL remains a fallback for images or other specific scenarios,
# but not as a primary PDF OCR method. For this refactor, focus is on Textract for PDFs.

def extract_text_from_pdf_textract(db_manager: SupabaseManager,
                                   source_doc_sql_id: int,
                                   # pdf_path_or_s3_uri is the initial path from queue/direct intake
                                   pdf_path_or_s3_uri: str 
                                   ) -> tuple[Optional[str], Optional[List[Dict[str, Any]]]]:
    
    # Fetch document_uuid from DB using source_doc_sql_id
    source_doc_details_for_uuid = db_manager.get_document_by_id(source_doc_sql_id)
    if not source_doc_details_for_uuid or not source_doc_details_for_uuid.get('document_uuid'):
        logger.error(f"Cannot process with Textract: document_uuid not found for source_doc_sql_id {source_doc_sql_id}.")
        # Update DB to reflect this critical error
        db_manager.update_source_document_with_textract_outcome(source_doc_sql_id, "N/A_UUID_MISSING", 'failed')
        return None, [{"status": "error", "error_message": "Document UUID missing from database."}]
    document_uuid_from_db = source_doc_details_for_uuid['document_uuid']
    original_filename_from_db = source_doc_details_for_uuid.get('original_file_name', f"{document_uuid_from_db}.pdf")

    logger.info(f"Starting PDF Textract for source_id: {source_doc_sql_id}, doc_uuid: {document_uuid_from_db}, path: {pdf_path_or_s3_uri}")
    
    s3_manager = S3StorageManager()
    textract_processor = TextractProcessor(db_manager=db_manager) # Pass db_manager

    target_s3_bucket_name = S3_PRIMARY_DOCUMENT_BUCKET # All inputs for Textract must be in S3
    s3_object_key_for_textract: Optional[str] = None
    local_temp_file_path_to_clean: Optional[str] = None # For files downloaded from Supabase Storage

    try:
        # 1. Ensure the PDF is in S3 and get its s3_key
        if pdf_path_or_s3_uri.startswith('s3://'):
            parts = pdf_path_or_s3_uri.replace('s3://', '').split('/', 1)
            if len(parts) == 2:
                target_s3_bucket_name = parts[0] # Could be a different bucket if file already existed in S3
                s3_object_key_for_textract = parts[1]
                logger.info(f"Using existing S3 object: s3://{target_s3_bucket_name}/{s3_object_key_for_textract}")
            else: # Invalid S3 URI
                err_msg = f"Invalid S3 URI: {pdf_path_or_s3_uri}"
                logger.error(err_msg)
                db_manager.update_source_document_with_textract_outcome(source_doc_sql_id, "N/A_S3_URI_INVALID", 'failed')
                return None, [{"status": "error", "error_message": err_msg}]
        
        elif pdf_path_or_s3_uri.startswith(('http://', 'https://')): # Assumed Supabase Storage URL or other HTTP URL
            logger.info(f"HTTP(S) URL detected: {pdf_path_or_s3_uri}. Downloading temporarily.")
            local_temp_file_path_to_clean = _download_supabase_file_to_temp(pdf_path_or_s3_uri)
            if not local_temp_file_path_to_clean:
                err_msg = f"Failed to download from URL: {pdf_path_or_s3_uri}"
                db_manager.update_source_document_with_textract_outcome(source_doc_sql_id, "N/A_HTTP_DOWNLOAD_FAIL", 'failed')
                return None, [{"status": "error", "error_message": err_msg}]
            
            # Upload downloaded file to S3
            upload_info = s3_manager.upload_document_with_uuid_naming(
                local_file_path=local_temp_file_path_to_clean,
                document_uuid=document_uuid_from_db, # Use the DB UUID for naming
                original_filename=original_filename_from_db # Use original name from DB for extension
            )
            s3_object_key_for_textract = upload_info['s3_key']
            target_s3_bucket_name = upload_info['s3_bucket'] # This will be S3_PRIMARY_DOCUMENT_BUCKET
            logger.info(f"Uploaded downloaded file to s3://{target_s3_bucket_name}/{s3_object_key_for_textract}")
            # Update source_documents with the new S3 location
            db_manager.client.table('source_documents').update({
                's3_key': s3_object_key_for_textract, 's3_bucket': target_s3_bucket_name, 's3_region': AWS_DEFAULT_REGION
            }).eq('id', source_doc_sql_id).execute()
            logger.info(f"Updated source_document {source_doc_sql_id} with new S3 location from HTTP download.")

        elif os.path.exists(pdf_path_or_s3_uri): # Local file path
            logger.info(f"Local file detected: {pdf_path_or_s3_uri}. Uploading to S3.")
            # original_filename here is from the local path
            original_filename_local = os.path.basename(pdf_path_or_s3_uri) 
            upload_info = s3_manager.upload_document_with_uuid_naming(
                local_file_path=pdf_path_or_s3_uri,
                document_uuid=document_uuid_from_db,
                original_filename=original_filename_local # Use local name for extension
            )
            s3_object_key_for_textract = upload_info['s3_key']
            target_s3_bucket_name = upload_info['s3_bucket']
            logger.info(f"Uploaded local file to s3://{target_s3_bucket_name}/{s3_object_key_for_textract}")
            # Update source_documents with S3 location
            db_manager.client.table('source_documents').update({
                's3_key': s3_object_key_for_textract, 's3_bucket': target_s3_bucket_name, 's3_region': AWS_DEFAULT_REGION
            }).eq('id', source_doc_sql_id).execute()
            logger.info(f"Updated source_document {source_doc_sql_id} with S3 location from local upload.")
        else: # Path is not S3, not HTTP, not local existing file
            err_msg = f"File/S3 URI not found or invalid: {pdf_path_or_s3_uri}"
            logger.error(err_msg)
            db_manager.update_source_document_with_textract_outcome(source_doc_sql_id, "N/A_PATH_INVALID", 'failed')
            return None, [{"status": "error", "error_message": err_msg}]

        if not s3_object_key_for_textract: # Should be set if logic above is correct
            err_msg = f"S3 object key could not be determined for input: {pdf_path_or_s3_uri}"
            logger.error(err_msg)
            db_manager.update_source_document_with_textract_outcome(source_doc_sql_id, "N/A_S3_KEY_UNDETERMINED", 'failed')
            return None, [{"status": "error", "error_message": err_msg}]

        # Verify S3 object existence before calling Textract
        if not s3_manager.check_s3_object_exists(s3_key=s3_object_key_for_textract, s3_bucket=target_s3_bucket_name):
            err_msg = f"S3 object s3://{target_s3_bucket_name}/{s3_object_key_for_textract} not found or not accessible after upload/check."
            logger.error(err_msg)
            db_manager.update_source_document_with_textract_outcome(source_doc_sql_id, "N/A_S3_OBJECT_NOT_FOUND", 'failed')
            return None, [{"status": "error", "error_message": err_msg}]

        # 2. Call Textract (Async is preferred for PDFs)
        extracted_text: Optional[str] = None
        textract_api_doc_metadata: Optional[Dict[str, Any]] = None # Textract's DocumentMetadata
        custom_page_level_metadata_for_db: List[Dict[str, Any]] = [] # For ocr_metadata_json
        textract_job_id_final : Optional[str] = None


        if TEXTRACT_USE_ASYNC_FOR_PDF:
            # start_document_text_detection now takes source_doc_id and document_uuid_from_db
            textract_job_id_final = textract_processor.start_document_text_detection(
                s3_bucket=target_s3_bucket_name,
                s3_key=s3_object_key_for_textract,
                source_doc_id=source_doc_sql_id,
                document_uuid_from_db=document_uuid_from_db
            )

            if not textract_job_id_final: # Failure to start, DB already updated by start_document_text_detection
                return None, [{"status": "error", "error_message": "Failed to start Textract job."}] # Generic message

            # get_text_detection_results now takes source_doc_id for intermediate updates
            blocks, textract_api_doc_metadata = textract_processor.get_text_detection_results(textract_job_id_final, source_doc_sql_id)
            
            if blocks and textract_api_doc_metadata: # Job succeeded or partial success with blocks
                extracted_text = textract_processor.process_textract_blocks_to_text(blocks, textract_api_doc_metadata)
            # If blocks is None or empty, get_text_detection_results handled DB updates for job failure.
            
        else: # Synchronous path (generally not recommended for multi-page PDFs)
            logger.error("Synchronous PDF processing (TEXTRACT_USE_ASYNC_FOR_PDF=false) is limited and not fully implemented. Please use async.")
            db_manager.update_source_document_with_textract_outcome(source_doc_sql_id, "N/A_SYNC_PDF_UNSUPPORTED", 'failed')
            return None, [{"status": "error", "error_message": "Sync PDF Textract not supported for multi-page via DetectDocumentText."}]

        # 3. Process results and prepare metadata for ocr_metadata_json
        if extracted_text is not None and textract_api_doc_metadata:
            num_pages = textract_api_doc_metadata.get('Pages', 1)
            # Fetch job duration from textract_jobs table for more accuracy
            textract_job_details = db_manager.get_textract_job_by_job_id(textract_job_id_final) if textract_job_id_final else None
            processing_duration_sec = textract_job_details.get('processing_duration_seconds') if textract_job_details else 0.0
            
            custom_page_level_metadata_for_db = [{
                "page_number": i + 1, "method": "AWS Textract", "engine": "DetectDocumentText",
                "processing_time_seconds_approx_per_page": round(processing_duration_sec / num_pages, 2) if num_pages > 0 and processing_duration_sec is not None else None,
            } for i in range(num_pages)]
            
            summary_meta = {
                "document_level_summary": True,
                "total_pages_processed": num_pages, "total_chars_extracted": len(extracted_text),
                "total_processing_time_seconds": processing_duration_sec,
                "textract_job_id": textract_job_id_final,
                "textract_api_document_metadata": textract_api_doc_metadata # Store raw Textract doc metadata
            }
            custom_page_level_metadata_for_db.insert(0, summary_meta)
            
            # Final update to source_documents with extracted text and our custom ocr_metadata_json
            # Other Textract fields on source_documents (like textract_job_status, warnings, confidence)
            # were already updated by TextractProcessor during polling.
            db_manager.update_source_document_with_textract_outcome(
                source_doc_sql_id=source_doc_sql_id,
                textract_job_id_val=textract_job_id_final if textract_job_id_final else "N/A",
                textract_job_status_val='succeeded' if extracted_text else 'failed', # Simplified status for this call
                raw_text_val=extracted_text,
                ocr_metadata_json_val=custom_page_level_metadata_for_db
            )
            return extracted_text, custom_page_level_metadata_for_db
        
        else: # Text extraction failed or no blocks returned
            logger.info(f"Textract extraction yielded no text for source_id: {source_doc_sql_id}, job_id: {textract_job_id_final}.")
            # DB status should have been set to 'failed' by get_text_detection_results.
            # Return a failure indicator.
            failure_metadata = [{"status": "error", "error_message": f"Textract job {textract_job_id_final} completed but no text extracted or job failed."}]
            if textract_api_doc_metadata: # Add API metadata if available even on failure
                 failure_metadata[0]["textract_api_document_metadata"] = textract_api_doc_metadata
            return None, failure_metadata

    except Exception as e: # Catch-all for unexpected errors in this function's orchestration
        logger.error(f"Outer exception in extract_text_from_pdf_textract for source_id {source_doc_sql_id}: {e}", exc_info=True)
        try: # Attempt to mark failure in DB
            db_manager.update_source_document_with_textract_outcome(source_doc_sql_id, "N/A_OUTER_EXCEPTION", 'failed')
        except Exception as db_err:
            logger.error(f"Failed to update DB on outer exception for source_id {source_doc_sql_id}: {db_err}")
        return None, [{"status": "exception", "error_message": str(e)}]
    finally: # Cleanup temporary local file if one was created
        if local_temp_file_path_to_clean and os.path.exists(local_temp_file_path_to_clean):
            try:
                os.unlink(local_temp_file_path_to_clean)
                logger.info(f"Cleaned up temporary local PDF: {local_temp_file_path_to_clean}")
            except OSError as e_clean: # More specific exception
                logger.warning(f"Failed to clean up temporary PDF {local_temp_file_path_to_clean}: {e_clean}")

# ... (extract_text_from_docx, _txt, _eml, transcribe_audio_whisper should be reviewed
#      to ensure they correctly update the new ocr_provider fields in source_documents if they succeed/fail)
```

## 6. Main Pipeline Logic (`main_pipeline.py`)

### 6.1. Update Imports
**Action:** Ensure `extract_text_from_pdf_textract` is imported. Remove `USE_MISTRAL_FOR_OCR` from config imports if present.

### 6.2. Modify PDF Processing Logic in `process_single_document()`
**Action:** Call `extract_text_from_pdf_textract` correctly, passing `db_manager`, `source_doc_sql_id`. `source_doc_uuid` is now fetched *inside* `extract_text_from_pdf_textract` using `source_doc_sql_id`. The `file_name` parameter for `create_neo4j_document_entry` should remain the original file name for user-friendliness, while S3 storage uses the UUID.

**File:** `main_pipeline.py`, within `process_single_document` function.
```python
# main_pipeline.py
# ... (imports)
from ocr_extraction import (
    extract_text_from_pdf_qwen_vl_ocr, # Keep if Qwen is a fallback for other types or future use
    extract_text_from_pdf_textract,   # Primary PDF OCR
    # ... other extractors ...
)
# ...

def process_single_document(db_manager: SupabaseManager, source_doc_sql_id: int, 
                            file_path: str, # This is the initial path (local, s3://, or http://)
                            file_name: str, # This is the original_file_name
                            detected_file_type: str, project_sql_id: int):
    logger.info(f"Processing document: {file_name} (Source SQL ID: {source_doc_sql_id})")
    
    raw_text: Optional[str] = None
    # This is the custom metadata list prepared by ocr_extraction functions
    ocr_metadata_for_db_json: Optional[List[Dict[str, Any]]] = None 

    # Fetch source_document details once, including document_uuid
    source_doc_info = db_manager.get_document_by_id(source_doc_sql_id)
    if not source_doc_info:
        logger.error(f"CRITICAL: Source document with SQL ID {source_doc_sql_id} not found. Aborting."); return
    
    source_doc_uuid = source_doc_info.get('document_uuid')
    if not source_doc_uuid:
        logger.error(f"CRITICAL: Source document SQL ID {source_doc_sql_id} is missing 'document_uuid'. Aborting.")
        db_manager.update_source_document_text(source_doc_sql_id, None, status="error_missing_uuid") # Old status update
        # New comprehensive update:
        db_manager.update_source_document_with_textract_outcome(source_doc_sql_id, "N/A_UUID_MISSING_MAIN", 'failed', ocr_provider_enum_val=None)
        return

    # Set initial ocr_provider for this processing attempt (if PDF, it's Textract)
    # This will be further updated by the extraction function upon completion/failure.
    if detected_file_type == '.pdf':
        db_manager.client.table('source_documents').update({
            'ocr_provider': 'textract', 
            'textract_job_status': 'not_started', # Set to 'not_started' before calling Textract
            'updated_at': datetime.now().isoformat()
        }).eq('id', source_doc_sql_id).execute()
        
        raw_text, ocr_metadata_for_db_json = extract_text_from_pdf_textract(
            db_manager=db_manager,
            source_doc_sql_id=source_doc_sql_id,
            pdf_path_or_s3_uri=file_path # Pass the initial path
            # document_uuid_from_db is now fetched inside extract_text_from_pdf_textract
        )
        # DB updates for job status and outcome are now handled within extract_text_from_pdf_textract
        # and its calls to TextractProcessor / SupabaseManager.

    elif detected_file_type == '.docx':
        raw_text = extract_text_from_docx(file_path)
        ocr_metadata_for_db_json = [{"method": "docx_parser", "status": "succeeded" if raw_text else "failed"}]
        db_manager.client.table('source_documents').update({
            'ocr_provider': 'docx_parser', # Custom ENUM value
            'ocr_completed_at': datetime.now().isoformat(),
            'raw_extracted_text': raw_text, # Directly update text here
            'ocr_metadata_json': json.dumps(ocr_metadata_for_db_json),
            'initial_processing_status': 'ocr_complete_pending_doc_node' if raw_text else 'extraction_failed'
        }).eq('id', source_doc_sql_id).execute()
    
    # ... similar explicit updates for .txt, .eml, .wav, .mp3 ...
    # For example, for .txt:
    elif detected_file_type == '.txt':
        raw_text = extract_text_from_txt(file_path)
        ocr_metadata_for_db_json = [{"method": "txt_parser", "status": "succeeded" if raw_text else "failed"}]
        db_manager.client.table('source_documents').update({
            'ocr_provider': 'txt_parser', # Custom ENUM value
            'ocr_completed_at': datetime.now().isoformat(),
            'raw_extracted_text': raw_text,
            'ocr_metadata_json': json.dumps(ocr_metadata_for_db_json),
            'initial_processing_status': 'ocr_complete_pending_doc_node' if raw_text else 'extraction_failed'
        }).eq('id', source_doc_sql_id).execute()

    elif detected_file_type in ['.wav', '.mp3']: # Example for audio
        raw_text = transcribe_audio_whisper(file_path) # This might use OpenAI or local
        ocr_metadata_for_db_json = [{"method": "whisper_transcription", "status": "succeeded" if raw_text else "failed"}]
        # Determine provider based on whisper implementation (e.g., 'openai_whisper' or 'local_whisper')
        whisper_provider = 'openai' if (DEPLOYMENT_STAGE == STAGE_CLOUD_ONLY or USE_OPENAI_FOR_AUDIO_TRANSCRIPTION) else 'local_whisper'
        db_manager.client.table('source_documents').update({
            'ocr_provider': whisper_provider, # Custom ENUM value
            'ocr_completed_at': datetime.now().isoformat(),
            'raw_extracted_text': raw_text,
            'ocr_metadata_json': json.dumps(ocr_metadata_for_db_json),
            'initial_processing_status': 'ocr_complete_pending_doc_node' if raw_text else 'extraction_failed'
        }).eq('id', source_doc_sql_id).execute()
        
    else: # Unsupported
        logger.warning(f"Unsupported file type: {detected_file_type} for {file_name}")
        db_manager.client.table('source_documents').update({
            'ocr_provider': None, # Or an 'unsupported' enum value
            'initial_processing_status': 'extraction_unsupported',
            'error_message': f"Unsupported file type: {detected_file_type}"
        }).eq('id', source_doc_sql_id).execute()
        return # Exit processing

    # Check raw_text after all extraction attempts
    if raw_text is None:
        logger.error(f"Text extraction failed for {file_name} (Source SQL ID: {source_doc_sql_id}).")
        # The specific extraction functions should have updated DB statuses.
        # No further general status update needed here if specific extractors handle their failures.
        return # Exit processing

    # If raw_text is NOT None, it means extraction was successful for some method.
    # The main 'initial_processing_status' should be 'ocr_complete_pending_doc_node'.
    # Text and ocr_metadata_json specific to the successful method should already be in the DB.
    # This explicit update here is a safety net if individual extractors don't set it.
    # However, with Textract, this is handled by update_source_document_with_textract_outcome.
    # For non-PDFs, it's handled in their respective elif blocks above.
    # So, this explicit `update_source_document_text` might be redundant now.
    # Let's remove it, assuming specific extractors correctly update upon success.
    # db_manager.update_source_document_text(
    #     source_doc_sql_id, raw_text,
    #     ocr_meta_json=json.dumps(ocr_metadata_for_db_json) if ocr_metadata_for_db_json else None,
    #     status="ocr_complete_pending_doc_node"
    # )

    # --- Phase 1.5: Neo4j Document Node Creation, Cleaning & Categorization ---
    # Get project_uuid for neo4j_document_entry
    project_details = db_manager.get_project_by_sql_id_or_global_project_id(project_sql_id, PROJECT_ID_GLOBAL)
    # get_project_by_sql_id_or_global_project_id needs to return a dict or the UUID string directly.
    # Assuming it might return a dict like {'projectId': 'uuid-string'} or just 'uuid-string'
    _project_uuid_for_neo4j: Optional[str] = None
    if isinstance(project_details, dict):
        _project_uuid_for_neo4j = project_details.get('projectId')
    elif isinstance(project_details, str):
        _project_uuid_for_neo4j = project_details
    
    if not _project_uuid_for_neo4j:
        logger.error(f"Critical: Could not determine project_uuid for project_sql_id {project_sql_id}. Aborting {file_name}.")
        # Update source_documents to reflect this critical error
        db_manager.client.table('source_documents').update({
            'initial_processing_status': 'error_project_uuid_lookup',
            'error_message': 'Failed to lookup project_uuid for Neo4j document creation.'
        }).eq('id', source_doc_sql_id).execute()
        return

    neo4j_doc_sql_id, neo4j_doc_uuid = db_manager.create_neo4j_document_entry(
        source_doc_fk_id=source_doc_sql_id,
        source_doc_uuid=source_doc_uuid, # From fetched source_doc_info
        project_fk_id=project_sql_id,
        project_uuid=_project_uuid_for_neo4j, # Use resolved project_uuid
        file_name=file_name # Original file_name for display
    )
    # ... (Rest of the pipeline: cleaning, categorization, chunking, NER, canonicalization, relationships)
    # Ensure all subsequent calls use neo4j_doc_sql_id and neo4j_doc_uuid correctly.
    # The `file_name` passed to `create_neo4j_document_entry` is the original human-readable name.
    # The actual file in S3 is named using `document_uuid`.
```

## 7. Queue Processor Adjustments (`queue_processor.py`)

### 7.1. Update File Path Handling and `ocr_provider`
**Action:** `_process_claimed_documents` should correctly form `file_path_for_pipeline` and update `ocr_provider` on the queue item if it's a PDF.
**File:** `queue_processor.py`
```python
# queue_processor.py
# ... (imports)
from config import PROJECT_ID_GLOBAL #, S3_PRIMARY_DOCUMENT_BUCKET (if needed for S3FileManager direct uploads)
from datetime import datetime # Ensure datetime is imported
# ...

class QueueProcessor:
    # ... (__init__) ...

    def _process_claimed_documents(self, claimed_items_from_rpc: List[Dict], project_sql_id: int) -> List[Dict]:
        documents_to_process_list = []
        for item_claimed in claimed_items_from_rpc: # Renamed for clarity
            source_doc_details = self.db_manager.get_document_by_id(item_claimed['source_document_id'])
            if not source_doc_details:
                logger.warning(f"Queue: Source document ID {item_claimed['source_document_id']} not found. Queue ID: {item_claimed['queue_id']}")
                self.mark_queue_item_failed(item_claimed['queue_id'], f"Source document ID {item_claimed['source_document_id']} not found.", item_claimed['source_document_id'])
                continue

            path_for_pipeline: str
            db_s3_key = source_doc_details.get('s3_key')
            db_s3_bucket = source_doc_details.get('s3_bucket')

            if db_s3_key and db_s3_bucket: # File is already in S3
                path_for_pipeline = f"s3://{db_s3_bucket}/{db_s3_key}"
                logger.info(f"Queue: Doc ID {item_claimed['source_document_id']} is in S3: {path_for_pipeline}")
            elif source_doc_details.get('original_file_path'): # Not in S3, use original path
                path_for_pipeline = source_doc_details['original_file_path']
                logger.info(f"Queue: Doc ID {item_claimed['source_document_id']} using original_file_path: {path_for_pipeline}. OCR function will handle S3 upload if needed.")
            else: # No valid path
                logger.error(f"Queue: No S3 key or original_file_path for doc ID {item_claimed['source_document_id']}. Queue ID: {item_claimed['queue_id']}")
                self.mark_queue_item_failed(item_claimed['queue_id'], "Missing S3 key or original_file_path.", item_claimed['source_document_id'])
                continue
            
            # Update ocr_provider on the queue item if it's a PDF, so it's known it'll go to Textract
            if source_doc_details.get('detected_file_type') == '.pdf':
                 self.db_manager.client.table('document_processing_queue').update(
                     {'ocr_provider': 'textract', 'updated_at': datetime.now().isoformat()} # DDL added ocr_provider
                 ).eq('id', item_claimed['queue_id']).execute()

            documents_to_process_list.append({
                'queue_id': item_claimed['queue_id'],
                'source_doc_sql_id': item_claimed['source_document_id'],
                # 'source_doc_uuid' is fetched within process_single_document now
                'attempts': item_claimed['attempts'],
                'file_path': path_for_pipeline,
                'file_name': source_doc_details['original_file_name'], # Original name for display
                'detected_file_type': source_doc_details['detected_file_type'],
                'project_sql_id': project_sql_id,
                # 'existing_textract_job_id': item_claimed.get('existing_textract_job_id') # If passed from claim_pending_documents
            })
        return documents_to_process_list

    def mark_queue_item_failed(self, queue_id: int, error_message: str, source_doc_sql_id: Optional[int] = None):
        logger.error(f"Marking queue item {queue_id} as failed. Error: {error_message}")
        try:
            # Fetch the queue item to get its associated textract_job_id if any
            queue_item_details_resp = self.db_manager.client.table('document_processing_queue')\
                .select('textract_job_id, source_document_id')\
                .eq('id', queue_id)\
                .maybe_single().execute()
            
            associated_textract_job_id: Optional[str] = None
            if queue_item_details_resp.data:
                associated_textract_job_id = queue_item_details_resp.data.get('textract_job_id')
                # Ensure source_doc_sql_id is correctly obtained if not passed
                if source_doc_sql_id is None:
                    source_doc_sql_id = queue_item_details_resp.data.get('source_document_id')

            update_payload_queue = {
                'status': 'failed',
                'error_message': str(error_message)[:2000], # Max length for TEXT
                'completed_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat()
            }
            self.db_manager.client.table('document_processing_queue').update(update_payload_queue).eq('id', queue_id).execute()

            # If a Textract job was associated and failed at queue level, update its status
            if associated_textract_job_id and associated_textract_job_id not in ["N/A_QUEUE_FAIL", "N/A_S3_URI_INVALID"]: # Avoid updating placeholder job IDs
                self.db_manager.update_textract_job_status(associated_textract_job_id, 'FAILED', error_message=f"Queue Processing Error: {error_message[:240]}")

            # Update source_documents table too
            if source_doc_sql_id:
                self.db_manager.update_source_document_with_textract_outcome(
                    source_doc_sql_id=source_doc_sql_id,
                    textract_job_id_val=associated_textract_job_id or "N/A_QUEUE_PROCESSING_FAIL",
                    textract_job_status_val='failed', # source_documents.textract_job_status enum
                    # ocr_provider might already be set, or can be 'unknown_failure'
                )
                # Explicitly set main initial_processing_status to 'error'
                self.db_manager.client.table('source_documents').update({
                    'initial_processing_status': 'error',
                    'error_message': f"Queue processing error for item {queue_id}: {error_message[:250]}"
                }).eq('id', source_doc_sql_id).execute()

        except Exception as e_mark_fail:
            logger.error(f"CRITICAL: Error while marking queue item {queue_id} as failed in DB: {e_mark_fail}", exc_info=True)
    
    def claim_pending_documents(self) -> List[Dict]:
        logger.debug(f"Attempting to claim up to {self.batch_size} documents.")
        project_sql_id: Optional[int] = None
        try:
            response_project = self.db_manager.client.table('projects').select('id').eq('projectId', PROJECT_ID_GLOBAL).maybe_single().execute()
            if not response_project.data:
                logger.error(f"Project with projectId {PROJECT_ID_GLOBAL} not found. Cannot claim documents."); return []
            project_sql_id = response_project.data['id']
        except Exception as e_proj:
            logger.error(f"Failed to get project {PROJECT_ID_GLOBAL}: {e_proj}"); return []

        try:
            # Claim documents using direct Supabase queries (as per previous working iteration)
            # This assumes the document_processing_queue table has source_document_uuid and textract_job_id columns.
            response_queue_items = self.db_manager.client.table('document_processing_queue')\
                .select('id, source_document_id, source_document_uuid, retry_count, textract_job_id')\
                .eq('status', 'pending')\
                .lt('retry_count', 3) \
                .order('priority', desc=False)\
                .order('created_at', desc=False)\
                .limit(self.batch_size)\
                .execute()
            
            claimed_items_list = []
            for item_data in response_queue_items.data:
                try:
                    # Attempt to claim (optimistic lock)
                    update_claim_response = self.db_manager.client.table('document_processing_queue')\
                        .update({
                            'status': 'processing',
                            'retry_count': item_data['retry_count'] + 1,
                            'started_at': datetime.now().isoformat(),
                            'processor_metadata': {'processor_id': self.processor_id, 'claimed_at': datetime.now().isoformat()}, # Use 'claimed_at'
                            'updated_at': datetime.now().isoformat()
                            # textract_job_id is NOT set here; it's set when TextractProcessor starts a job.
                        })\
                        .eq('id', item_data['id'])\
                        .eq('status', 'pending')\
                        .execute()
                    
                    if update_claim_response.data: # Successfully claimed
                        claimed_items_list.append({
                            'queue_id': item_data['id'],
                            'source_document_id': item_data['source_document_id'],
                            'source_document_uuid': item_data.get('source_document_uuid'), # If present on queue table
                            'attempts': item_data['retry_count'] + 1,
                            'existing_textract_job_id': item_data.get('textract_job_id') # Pass this along
                        })
                        logger.debug(f"Successfully claimed document queue ID: {item_data['id']}")
                    else: # Failed to claim (race condition)
                        logger.debug(f"Could not claim document {item_data['id']} - likely claimed by another processor or status changed.")
                except Exception as e_claim_item:
                    logger.warning(f"Error trying to claim document {item_data['id']} individually: {e_claim_item}")
                    continue # Try next item
            
            logger.info(f"Claimed {len(claimed_items_list)} documents from queue.")
            if project_sql_id is None: # Should not happen if project check passed
                logger.error("Project SQL ID is None after successful project fetch. This is unexpected."); return []
            return self._process_claimed_documents(claimed_items_list, project_sql_id)
            
        except Exception as e_claim_batch:
            logger.error(f"Error during batch claiming of documents from queue: {e_claim_batch}", exc_info=True)
            return []


    # check_for_stalled_documents needs to be updated to reflect the new textract_jobs table
    # and the textract_job_id on document_processing_queue.
    # If a queue item is 'processing' but its associated Textract job in textract_jobs is 'FAILED' or 'SUCCEEDED',
    # the queue item should be reconciled.
    # This is more complex than the original stalled check. For now, keep the original logic,
    # but acknowledge this area might need future enhancement.
    def check_for_stalled_documents(self):
        # ... (Original logic for checking based on queue item's started_at vs max_processing_time) ...
        # Consider adding checks against textract_jobs table if a textract_job_id is on the queue item.
        logger.debug("Checking for stalled documents (basic time-based check).")
        stalled_threshold_time = (datetime.now() - self.max_processing_time).isoformat()
        
        try:
            stalled_queue_items_resp = self.db_manager.client.table('document_processing_queue')\
                .select('id, source_document_id, retry_count, processor_metadata, textract_job_id, max_retries')\
                .eq('status', 'processing')\
                .lt('started_at', stalled_threshold_time)\
                .order('started_at', desc=False)\
                .limit(10)\
                .execute()
            
            # ... (rest of the original stalled document handling logic, ensuring `mark_queue_item_failed` is called correctly) ...
            # This logic resets to 'pending' or marks 'failed' based on retry_count.
            # It should also potentially update any associated textract_jobs entry to 'FAILED' if the queue item is marked failed due to timeout.
            stalled_docs_reset_count = 0
            stalled_docs_failed_count = 0
            for doc_item in stalled_queue_items_resp.data:
                max_r = doc_item.get('max_retries', 3) # Default to 3 if not on table
                proc_meta = doc_item.get('processor_metadata', {})
                proc_id = proc_meta.get('processor_id', 'unknown') if isinstance(proc_meta, dict) else 'unknown'

                if doc_item['retry_count'] < max_r:
                    # Reset to pending
                    try:
                        self.db_manager.client.table('document_processing_queue').update({
                            'status': 'pending',
                            'error_message': f'Stalled: Timed out (processor: {proc_id}). Resetting.',
                            'started_at': None, 'processor_metadata': None, 'updated_at': datetime.now().isoformat()
                        }).eq('id', doc_item['id']).eq('status', 'processing').execute()
                        stalled_docs_reset_count += 1
                        logger.info(f"Reset stalled queue item {doc_item['id']} to pending.")
                    except Exception as e_reset_stalled:
                        logger.warning(f"Could not reset stalled queue item {doc_item['id']}: {e_reset_stalled}")
                else:
                    # Mark as failed (max attempts)
                    err_stalled_max = f'Stalled: Timed out (processor: {proc_id}). Max attempts reached.'
                    self.mark_queue_item_failed(doc_item['id'], err_stalled_max, doc_item.get('source_document_id'))
                    stalled_docs_failed_count +=1
                    logger.warning(f"Marked stalled queue item {doc_item['id']} as failed (max retries).")
            
            if stalled_docs_reset_count > 0: logger.info(f"Reset {stalled_docs_reset_count} stalled queue items.")
            if stalled_docs_failed_count > 0: logger.warning(f"Marked {stalled_docs_failed_count} stalled queue items as failed.")

        except Exception as e_stalled_check:
            logger.error(f"Error during stalled document check: {e_stalled_check}", exc_info=True)

    # process_queue - No major changes other than ensuring arguments passed to process_single_document are correct.
    # Cleanup of S3 temp files from queue processor is no longer relevant as Textract function handles its own temps if any.
```

## 8. Final Checks and Considerations

-   **IAM Role/User Permissions:** Verify as per previous guide.
-   **Error Handling in `TextractProcessor`:** Ensure robust error catching and DB status updates.
-   **Existing S3 File Migration:** The solution now standardizes on `documents/{document_uuid}{file_ext}` for *new* uploads via `s3_storage.upload_document_with_uuid_naming`. A separate migration script (SQL or Python) is needed to bring existing S3 objects (e.g., `uploads/[timestamp]-[random].[ext]`) to this new pattern if full consistency is desired. This involves S3 object renaming and `source_documents.s3_key` updates.
-   **`original_file_name` in `source_documents`:** This field should store the actual user-uploaded file name. The S3 key is now `documents/{document_uuid}.ext`.
-   **`file_name` in `neo4j_documents`:** This should also be the `original_file_name` for user display, not the S3 key.
-   **Long-Running Jobs:** The current implementation uses a blocking poll. Monitor job durations. If Textract jobs are very long, transition to an SNS-based asynchronous completion notification pattern.
-   **Idempotency with `ClientRequestToken`**: `TextractProcessor.start_document_text_detection` now uses `document_uuid_from_db` to construct a deterministic `ClientRequestToken`, which helps Textract avoid starting duplicate jobs for the same document if the start request is retried.
-   **Review `transcribe_audio_whisper` and other non-PDF extractors:** Ensure they are correctly updating `ocr_provider`, `ocr_completed_at`, `ocr_processing_seconds`, and `initial_processing_status` in the `source_documents` table upon their success or failure, similar to how PDF/Textract and DOCX/TXT examples were updated in `main_pipeline.py`.

This comprehensive guide should provide the necessary detail for an agentic coding tool to implement the Textract refactor aligned with Claude's schema recommendations and operational logic.

```