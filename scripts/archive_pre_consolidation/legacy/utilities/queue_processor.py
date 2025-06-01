#!/usr/bin/env python3
"""
Refactored Queue Processor - Now a document intake handler, not a queue poller
"""
import os
import sys
import time
import logging
from typing import Optional, Tuple
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import PROJECT_ID_GLOBAL, S3_PRIMARY_DOCUMENT_BUCKET
from supabase_utils import SupabaseManager
from celery_submission import submit_document_to_celery
from s3_storage import S3Storage

# Setup logger
try:
    from logging_config import get_logger
    logger = get_logger(__name__)
except ImportError:
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO)

# Add new config for document intake directory
DOCUMENT_INTAKE_DIR = os.getenv('DOCUMENT_INTAKE_DIR', '/tmp/document_intake')

class DocumentIntakeHandler(FileSystemEventHandler):
    """Handles new document arrivals from filesystem"""
    
    def __init__(self):
        self.db_manager = SupabaseManager()
        self.s3_storage = S3Storage(bucket_name=S3_PRIMARY_DOCUMENT_BUCKET)
        logger.info("Initialized DocumentIntakeHandler")
        
    def on_created(self, event):
        """Handle new file creation events"""
        if event.is_directory:
            return
            
        # Check if it's a document file
        file_ext = os.path.splitext(event.src_path)[1].lower()
        if file_ext in ['.pdf', '.docx', '.doc', '.txt', '.rtf', '.eml']:
            logger.info(f"New document detected: {event.src_path}")
            self.process_new_document(event.src_path)
    
    def process_new_document(self, file_path: str):
        """Process a newly detected document"""
        try:
            # Extract file info
            file_name = os.path.basename(file_path)
            file_ext = os.path.splitext(file_path)[1][1:].lower()  # Remove the dot
            
            # Upload to S3 first if file exists locally
            if os.path.exists(file_path):
                logger.info(f"Uploading {file_name} to S3...")
                s3_key = self.s3_storage.upload_document(
                    file_path=file_path,
                    original_filename=file_name
                )
                logger.info(f"Uploaded to S3: {s3_key}")
            else:
                logger.error(f"File not found: {file_path}")
                return
            
            # Get or create project
            project_sql_id, project_uuid = self.db_manager.get_or_create_project(PROJECT_ID_GLOBAL)
            
            # Register in source_documents
            doc_id, doc_uuid = self.db_manager.create_source_document_entry(
                project_sql_id=project_sql_id,
                original_file_path=s3_key,
                original_file_name=file_name,
                detected_file_type=file_ext,
                file_size_bytes=os.path.getsize(file_path) if os.path.exists(file_path) else None
            )
            
            logger.info(f"Created source document: ID={doc_id}, UUID={doc_uuid}")
            
            # Submit directly to Celery
            task_id, success = submit_document_to_celery(
                document_id=doc_id,
                document_uuid=doc_uuid,
                file_path=s3_key,
                file_type=file_ext,
                project_id=PROJECT_ID_GLOBAL
            )
            
            if success:
                logger.info(f"✅ Document {file_name} submitted to Celery successfully. Task ID: {task_id}")
                
                # Optionally move processed file to archive directory
                archive_dir = os.path.join(os.path.dirname(file_path), "processed")
                if not os.path.exists(archive_dir):
                    os.makedirs(archive_dir)
                
                archive_path = os.path.join(archive_dir, file_name)
                os.rename(file_path, archive_path)
                logger.info(f"Moved file to: {archive_path}")
            else:
                logger.error(f"❌ Failed to submit document {file_name} to Celery")
                
        except Exception as e:
            logger.error(f"Error processing document {file_path}: {e}", exc_info=True)

class DirectCelerySubmitter:
    """Alternative class for direct submission without file watching"""
    
    def __init__(self):
        self.db_manager = SupabaseManager()
        self.s3_storage = S3Storage(bucket_name=S3_PRIMARY_DOCUMENT_BUCKET)
        
    def submit_existing_document(self, s3_path: str, file_type: str) -> Tuple[str, bool]:
        """Submit an existing S3 document to Celery"""
        try:
            # Get or create project
            project_sql_id, project_uuid = self.db_manager.get_or_create_project(PROJECT_ID_GLOBAL)
            
            # Register in source_documents
            doc_id, doc_uuid = self.db_manager.create_source_document_entry(
                project_sql_id=project_sql_id,
                original_file_path=s3_path,
                original_file_name=os.path.basename(s3_path),
                detected_file_type=file_type
            )
            
            # Submit to Celery
            task_id, success = submit_document_to_celery(
                document_id=doc_id,
                document_uuid=doc_uuid,
                file_path=s3_path,
                file_type=file_type,
                project_id=PROJECT_ID_GLOBAL
            )
            
            return task_id, success
            
        except Exception as e:
            logger.error(f"Error submitting document: {e}")
            return None, False

def main():
    """Main entry point - now watches for new documents instead of polling queue"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Document Intake Handler for Celery Processing')
    parser.add_argument('--mode', choices=['watch', 'submit'], default='watch',
                       help='Mode: watch for new files or submit specific file')
    parser.add_argument('--file', help='S3 path for submit mode')
    parser.add_argument('--type', help='File type for submit mode')
    parser.add_argument('--watch-dir', default=DOCUMENT_INTAKE_DIR,
                       help='Directory to watch for new documents')
    
    args = parser.parse_args()
    
    if args.mode == 'submit':
        # Direct submission mode
        if not args.file or not args.type:
            print("Error: --file and --type required for submit mode")
            sys.exit(1)
            
        submitter = DirectCelerySubmitter()
        task_id, success = submitter.submit_existing_document(args.file, args.type)
        
        if success:
            print(f"✅ Document submitted successfully. Celery task ID: {task_id}")
        else:
            print("❌ Failed to submit document")
            sys.exit(1)
    
    else:
        # File watching mode
        watch_dir = args.watch_dir
        
        if not os.path.exists(watch_dir):
            os.makedirs(watch_dir)
            logger.info(f"Created watch directory: {watch_dir}")
        
        event_handler = DocumentIntakeHandler()
        observer = Observer()
        observer.schedule(event_handler, watch_dir, recursive=False)
        
        print(f"🔍 Watching for new documents in: {watch_dir}")
        print(f"📋 Supported formats: PDF, DOCX, DOC, TXT, RTF, EML")
        print(f"🚀 Documents will be submitted directly to Celery")
        print("Press Ctrl+C to stop")
        
        observer.start()
        
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            observer.stop()
            print("\n👋 Stopping document intake handler")
        
        observer.join()

if __name__ == "__main__":
    # IMPORTANT: This script no longer polls document_processing_queue!
    # It watches for new files and submits them directly to Celery
    print("=" * 60)
    print("🔄 REFACTORED: Queue Processor → Document Intake Handler")
    print("📌 No longer polls Supabase queue - submits directly to Celery")
    print("=" * 60)
    main()