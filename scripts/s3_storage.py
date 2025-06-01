import boto3
import logging
import os
import hashlib
from typing import Dict, Optional
from datetime import datetime
from botocore.exceptions import ClientError, NoCredentialsError, PartialCredentialsError
from scripts.config import AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_DEFAULT_REGION, S3_PRIMARY_DOCUMENT_BUCKET

logger = logging.getLogger(__name__)

class S3StorageManager:
    """Manages S3 operations for document storage"""
    
    def __init__(self):
        self.s3_client = boto3.client(
            's3',
            region_name=AWS_DEFAULT_REGION,
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY
        )
        self.private_bucket_name = S3_PRIMARY_DOCUMENT_BUCKET
    
    def _get_content_type(self, filename: str) -> str:
        """Get content type based on file extension"""
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
            '.tif': 'image/tiff'
        }
        return content_types.get(ext, 'application/octet-stream')
        
    def upload_document_with_uuid_naming(self, local_file_path: str, document_uuid: str,
                                       original_filename: str) -> Dict[str, any]:
        """Upload document with UUID-based naming to the primary private S3 bucket."""
        file_ext = os.path.splitext(original_filename)[1].lower()
        # S3 key will be based on document_uuid, e.g., "documents/your-document-uuid.pdf"
        s3_key = f"documents/{document_uuid}{file_ext}" 

        with open(local_file_path, 'rb') as f:
            file_content = f.read()
            md5_hash = hashlib.md5(file_content).hexdigest()

        content_type = self._get_content_type(original_filename)
        metadata = {
            'original-filename': original_filename,  # Keep original filename in S3 metadata
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
                'metadata': metadata  # S3 metadata, not to be confused with document's JSONB metadata
            }
        except Exception as error:
            self.handle_s3_errors(error)
            raise
    
    def get_s3_document_location(self, s3_key: str, s3_bucket: Optional[str] = None, version_id: Optional[str] = None) -> Dict[str, any]:
        """Get S3 document location dictionary for Textract API"""
        bucket_name = s3_bucket or self.private_bucket_name
        s3_object_loc = {'S3Object': {'Bucket': bucket_name, 'Name': s3_key}}
        if version_id:
            s3_object_loc['S3Object']['Version'] = version_id
        return s3_object_loc

    def check_s3_object_exists(self, s3_key: str, s3_bucket: Optional[str] = None) -> bool:
        """Check if an S3 object exists"""
        bucket_name = s3_bucket or self.private_bucket_name
        try:
            self.s3_client.head_object(Bucket=bucket_name, Key=s3_key)
            return True
        except ClientError as e:
            if e.response['Error']['Code'] == '404':
                return False
            else:
                logger.error(f"Error checking S3 object s3://{bucket_name}/{s3_key}: {e}")
                raise
        except Exception as e:
            logger.error(f"Unexpected error checking S3 object s3://{bucket_name}/{s3_key}: {e}")
            raise
    
    def handle_s3_errors(self, error):
        """Standardized S3 error handling"""
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
                raise ValueError(f"S3 bucket does not exist: {self.private_bucket_name}")
            elif error_code == 'AccessDenied':
                raise ValueError(f"S3 access denied for bucket: {self.private_bucket_name}")
            elif error_code == 'InvalidObjectState':
                raise ValueError(f"S3 object state error (likely archived): {error_message}")
            else:
                raise ValueError(f"S3 operation failed: {error_code} - {error_message}")
        else:
            logger.error(f"Unknown S3 error: {error}")
            raise