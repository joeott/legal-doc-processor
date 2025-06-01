#!/usr/bin/env python3
"""Test document processing with Airtable project matching."""

import os
import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.supabase_utils import SupabaseManager
from scripts.s3_storage import S3StorageManager
from scripts.celery_submission import submit_document_to_celery
from airtable.fuzzy_matcher import FuzzyMatcher
import logging

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_document_with_matching(file_path):
    """Test document processing with Airtable fuzzy matching."""
    try:
        # Initialize components
        logger.info("Initializing components...")
        db_manager = SupabaseManager()
        s3_manager = S3StorageManager()
        matcher = FuzzyMatcher()
        
        # Convert to Path object
        file_path = Path(file_path)
        if not file_path.exists():
            logger.error(f"File not found: {file_path}")
            return
        
        logger.info(f"Processing document: {file_path.name}")
        logger.info(f"Full path: {file_path}")
        
        # Try to match with existing project
        logger.info("Attempting to match with existing project...")
        matched_project = matcher.find_matching_project(
            file_name=file_path.name,
            file_path=str(file_path)
        )
        
        if matched_project:
            logger.info(f"✅ Matched to project: {matched_project['project_name']} (UUID: {matched_project['project_id']})")
            # Look up the SQL ID from Supabase
            result = db_manager.client.table('projects').select('id').eq('projectId', matched_project['project_id']).execute()
            if result.data:
                project_id = result.data[0]['id']
                project_uuid = matched_project['project_id']
            else:
                logger.error(f"Project UUID {matched_project['project_id']} not found in Supabase")
                return
        else:
            logger.warning("❌ No matching project found")
            # For testing, don't create a new project
            logger.error("Stopping - no project match found")
            return
        
        # Upload to S3
        logger.info("Uploading to S3...")
        with open(file_path, 'rb') as f:
            file_content = f.read()
        
        # Create a temporary file for S3 upload
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_path.suffix) as tmp:
            tmp.write(file_content)
            tmp_path = tmp.name
        
        # Generate a document UUID for S3 naming
        import uuid
        doc_uuid_temp = str(uuid.uuid4())
        
        result = s3_manager.upload_document_with_uuid_naming(
            local_file_path=tmp_path,
            document_uuid=doc_uuid_temp,
            original_filename=file_path.name
        )
        # The result contains the S3 key
        s3_key = result['s3_key']
        
        # Clean up temp file
        os.unlink(tmp_path)
        logger.info(f"✅ Uploaded to S3: {s3_key}")
        
        # Create document entry
        logger.info("Creating document entry...")
        doc_id, doc_uuid = db_manager.create_document_entry(
            project_id=project_id,
            file_name=file_path.name,
            file_type=file_path.suffix.lower()[1:],  # Remove the dot
            s3_url=s3_key,
            status='pending'
        )
        logger.info(f"✅ Document created: ID={doc_id}, UUID={doc_uuid}")
        
        # Submit to Celery
        logger.info("Submitting to Celery...")
        task_id = submit_document_to_celery(doc_uuid)
        logger.info(f"✅ Submitted to Celery: Task ID={task_id}")
        
        # Monitor status
        logger.info("\n⏳ Monitoring processing status...")
        start_time = time.time()
        last_status = None
        
        while True:
            # Get current status
            result = db_manager.client.table('source_documents').select(
                'status, celery_status, error_message, processed_at'
            ).eq('id', doc_id).execute()
            
            if result.data:
                doc = result.data[0]
                current_status = doc.get('celery_status') or doc.get('status')
                
                if current_status != last_status:
                    elapsed = int(time.time() - start_time)
                    logger.info(f"  [{elapsed}s] Status: {current_status}")
                    last_status = current_status
                
                # Check if processing is complete
                if current_status == 'completed':
                    logger.info(f"\n✅ Processing completed successfully!")
                    break
                elif current_status == 'failed' or doc.get('error_message'):
                    logger.error(f"\n❌ Processing failed!")
                    if doc.get('error_message'):
                        logger.error(f"Error: {doc['error_message']}")
                    break
            
            # Timeout after 5 minutes
            if time.time() - start_time > 300:
                logger.error("\n❌ Processing timed out after 5 minutes")
                break
            
            time.sleep(2)
        
    except Exception as e:
        logger.error(f"Error during test: {str(e)}", exc_info=True)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_airtable_document_matching.py <document_path>")
        sys.exit(1)
    
    test_document_with_matching(sys.argv[1])