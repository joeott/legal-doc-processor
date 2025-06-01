Phase 4: Python Codebase Updates
4.1 Queue Processor Updates
File: queue_processor.py
Add S3 migration handling to the queue processor:
python# Add to imports
from migrate_document_to_s3 import migrate_supabase_to_s3

# Add to QueueProcessor class
def process_s3_migration_queue_items(self):
    """Process documents that need S3 migration"""
    try:
        # Get documents pending S3 migration
        response = self.db_manager.client.table('document_processing_queue')\
            .select('*, source_documents!inner(*)')\
            .eq('processing_step', 's3_migration')\
            .eq('status', 'pending')\
            .order('priority', desc=True)\
            .limit(self.batch_size)\
            .execute()
        
        for item in response.data:
            self.process_single_s3_migration(item)
            
    except Exception as e:
        logger.error(f"Error processing S3 migration queue: {e}")

def process_single_s3_migration(self, queue_item):
    """Migrate a single document from Supabase Storage to S3"""
    queue_id = queue_item['id']
    doc_data = queue_item['source_documents']
    
    try:
        # Update queue status to processing
        self.db_manager.client.table('document_processing_queue')\
            .update({'status': 'processing', 'started_at': datetime.now().isoformat()})\
            .eq('id', queue_id)\
            .execute()
        
        # Perform S3 migration
        success = migrate_supabase_to_s3(
            document_uuid=doc_data['document_uuid'],
            supabase_path=doc_data['original_file_path'].replace('storage:/', ''),
            original_filename=doc_data['original_file_name']
        )
        
        if success:
            # Mark as completed
            self.db_manager.client.table('document_processing_queue')\
                .update({
                    'status': 'completed',
                    'completed_at': datetime.now().isoformat()
                })\
                .eq('id', queue_id)\
                .execute()
        else:
            self.mark_queue_item_failed(queue_id, "S3 migration failed")
            
    except Exception as e:
        logger.error(f"S3 migration failed for queue item {queue_id}: {e}")
        self.mark_queue_item_failed(queue_id, str(e))
4.2 S3 Migration Utility
File: migrate_document_to_s3.py (New File)
pythonimport os
import logging
from supabase_utils import SupabaseManager
from s3_storage import S3StorageManager
import requests

logger = logging.getLogger(__name__)

def migrate_supabase_to_s3(document_uuid: str, supabase_path: str, original_filename: str) -> bool:
    """
    Migrate document from Supabase Storage to S3 with UUID naming
    
    Args:
        document_uuid: Document UUID for naming
        supabase_path: Path in Supabase Storage
        original_filename: Original filename for extension
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        db_manager = SupabaseManager()
        s3_manager = S3StorageManager()
        
        # Get signed URL from Supabase Storage
        signed_url_response = db_manager.client.storage.from_('documents').create_signed_url(supabase_path, 3600)
        if not signed_url_response.get('signedURL'):
            logger.error(f"Failed to get signed URL for {supabase_path}")
            return False
        
        signed_url = signed_url_response['signedURL']
        
        # Download file from Supabase Storage
        response = requests.get(signed_url)
        response.raise_for_status()
        
        # Generate S3 key with UUID naming
        file_extension = original_filename.split('.')[-1]
        s3_key = f"documents/{document_uuid}.{file_extension}"
        
        # Upload to S3
        upload_result = s3_manager.upload_file_content(
            file_content=response.content,
            s3_key=s3_key,
            content_type=response.headers.get('content-type', 'application/octet-stream')
        )
        
        if upload_result['success']:
            # Update source_documents with S3 information
            db_manager.client.table('source_documents').update({
                's3_key': s3_key,
                's3_bucket': upload_result['s3_bucket'],
                's3_region': upload_result['s3_region'],
                'initial_processing_status': 'pending_ocr',
                'md5_hash': upload_result.get('md5_hash')
            }).eq('document_uuid', document_uuid).execute()
            
            # Record migration
            db_manager.client.table('s3_file_migrations').insert({
                'source_document_id': None,  # Will be updated by trigger
                'original_s3_key': supabase_path,
                'original_s3_bucket': 'supabase-storage',
                'new_s3_key': s3_key,
                'new_s3_bucket': upload_result['s3_bucket'],
                'migration_reason': 'uuid_rename_for_textract',
                'success': True
            }).execute()
            
            return True
        else:
            logger.error(f"S3 upload failed for {document_uuid}")
            return False
            
    except Exception as e:
        logger.error(f"Migration failed for {document_uuid}: {e}")
        return False
4.3 S3 Storage Manager Updates
File: s3_storage.py
Add method for uploading file content directly:
pythondef upload_file_content(self, file_content: bytes, s3_key: str, content_type: str) -> Dict[str, any]:
    """Upload file content directly to S3"""
    try:
        import hashlib
        md5_hash = hashlib.md5(file_content).hexdigest()
        
        self.s3_client.put_object(
            Bucket=self.private_bucket_name,
            Key=s3_key,
            Body=file_content,
            ContentType=content_type,
            Metadata={
                'upload-method': 'migration',
                'upload-timestamp': datetime.now().isoformat()
            }
        )
        
        return {
            'success': True,
            's3_key': s3_key,
            's3_bucket': self.private_bucket_name,
            's3_region': AWS_DEFAULT_REGION,
            'md5_hash': md5_hash,
            'file_size': len(file_content)
        }
    except Exception as e:
        logger.error(f"S3 upload failed: {e}")
        return {'success': False, 'error': str(e)}
4.4 OCR Extraction Updates
File: ocr_extraction.py
Remove all Mistral OCR references and ensure Textract is used:
python# Remove mistral_utils import
# from mistral_utils import extract_text_from_url

# Update main extraction function to only use Textract for PDFs
def extract_text_from_pdf(pdf_path_or_s3_uri: str, document_uuid: str, db_manager: SupabaseManager) -> tuple[str | None, list | None]:
    """Extract text from PDF using AWS Textract only"""
    if DEPLOYMENT_STAGE == "1" or detected_file_type == '.pdf':
        return extract_text_from_pdf_textract(
            db_manager=db_manager,
            source_doc_sql_id=source_doc_id,
            pdf_path_or_s3_uri=pdf_path_or_s3_uri,
            document_uuid_from_db=document_uuid
        )
    else:
        logger.error(f"PDF OCR only supported via Textract. File: {pdf_path_or_s3_uri}")
        return None, None
4.5 Configuration Updates
File: config.py
Add S3 migration settings:
python# S3 Migration Settings
S3_MIGRATION_BATCH_SIZE = int(os.getenv('S3_MIGRATION_BATCH_SIZE', '10'))
S3_MIGRATION_TIMEOUT_SECONDS = int(os.getenv('S3_MIGRATION_TIMEOUT_SECONDS', '300'))
AUTO_MIGRATE_TO_S3 = os.getenv('AUTO_MIGRATE_TO_S3', 'true').lower() in ('true', '1', 'yes')

# Remove Mistral configuration
# MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")  # Remove this line
# MISTRAL_OCR_MODEL = os.getenv("MISTRAL_OCR_MODEL", "pixtral-12b-2409")  # Remove this line
Phase 5: File Reference Updates
5.1 Update Pipeline References
Files to check for hardcoded paths:

main_pipeline.py: Update file path handling
textract_utils.py: Ensure S3 paths are used
chunking_utils.py: Update any file references

Key changes needed:

In main_pipeline.py:

Update process_single_document() to handle S3 paths
Remove Mistral OCR calls
Ensure UUID-based file naming


In textract_utils.py:

Verify S3 path handling
Update file validation logic


In queue processing:

Add S3 migration step before OCR
Update status transitions



Phase 6: Testing and Validation
6.1 Migration Testing
Create test scripts to validate:

Upload Flow:
bash# Test document upload triggers S3 migration
curl -X POST [SUPABASE_URL]/functions/v1/create-document-entry \
  -H "Content-Type: application/json" \
  -d '{"userDefinedName":"test.pdf","projectId":1,...}'

S3 Migration:
bash# Test S3 migration function
curl -X POST [SUPABASE_URL]/functions/v1/migrate-document-to-s3 \
  -H "Content-Type: application/json" \
  -d '{"documentUuid":"...","supabaseStoragePath":"..."}'

Queue Processing:
python# Test queue processor handles S3 migration
python -c "from queue_processor import QueueProcessor; QueueProcessor().process_s3_migration_queue_items()"


6.2 Validation Checklist

 Documents upload to Supabase Storage
 S3 migration triggers automatically
 Files renamed with UUID in S3
 OCR processing uses Textract only
 Queue processing handles all steps
 Database entries are properly updated
 Error handling works correctly
 Performance indexes are effective