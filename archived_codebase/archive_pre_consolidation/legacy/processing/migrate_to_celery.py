"""
Script to migrate existing documents from direct processing to Celery-based processing

This script:
1. Finds documents in various processing states
2. Enqueues them into Celery for processing
3. Updates their status to reflect Celery task assignment
"""
import sys
import logging
import argparse
from datetime import datetime, timedelta
from typing import List, Dict, Optional

from scripts.supabase_utils import SupabaseManager
from scripts.celery_tasks.ocr_tasks import process_ocr
from scripts.config import PROJECT_ID_GLOBAL

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class CeleryMigration:
    """Handles migration of existing documents to Celery processing"""
    
    def __init__(self, dry_run: bool = False):
        self.db = SupabaseManager()
        self.dry_run = dry_run
        self.stats = {
            'total_found': 0,
            'migrated': 0,
            'skipped': 0,
            'errors': 0
        }
        
    def find_documents_to_migrate(self, status_filter: Optional[List[str]] = None) -> List[Dict]:
        """Find documents that need to be migrated to Celery processing"""
        
        # Default statuses to migrate
        if status_filter is None:
            status_filter = [
                'pending',
                'ocr_processing',
                'ocr_failed',
                'error_textract',
                'extraction_failed',
                'processing',
                'textract_processing'
            ]
        
        logger.info(f"Searching for documents with status in: {status_filter}")
        
        try:
            # Query source_documents table
            response = self.db.client.table('source_documents').select(
                'id, document_uuid, file_name, file_path, original_file_path, '
                'detected_file_type, project_id, initial_processing_status, '
                's3_key, s3_bucket, celery_task_id, created_at'
            ).in_('initial_processing_status', status_filter).execute()
            
            documents = response.data
            self.stats['total_found'] = len(documents)
            
            logger.info(f"Found {len(documents)} documents to potentially migrate")
            
            # Filter out documents that already have Celery tasks
            documents_to_migrate = []
            for doc in documents:
                if doc.get('celery_task_id'):
                    logger.debug(f"Document {doc['id']} already has Celery task {doc['celery_task_id']}, skipping")
                    self.stats['skipped'] += 1
                else:
                    documents_to_migrate.append(doc)
            
            return documents_to_migrate
            
        except Exception as e:
            logger.error(f"Error finding documents to migrate: {e}")
            return []
    
    def find_stalled_documents(self, hours: int = 24) -> List[Dict]:
        """Find documents that have been processing for too long"""
        
        cutoff_time = datetime.now() - timedelta(hours=hours)
        logger.info(f"Looking for documents processing since before {cutoff_time}")
        
        try:
            response = self.db.client.table('source_documents').select(
                'id, document_uuid, file_name, initial_processing_status, '
                'last_modified_at, celery_task_id'
            ).in_('initial_processing_status', [
                'ocr_processing', 
                'textract_processing',
                'processing'
            ]).lt('last_modified_at', cutoff_time.isoformat()).execute()
            
            stalled_docs = response.data
            logger.info(f"Found {len(stalled_docs)} potentially stalled documents")
            
            return stalled_docs
            
        except Exception as e:
            logger.error(f"Error finding stalled documents: {e}")
            return []
    
    def migrate_document(self, doc: Dict) -> bool:
        """Migrate a single document to Celery processing"""
        
        doc_id = doc['id']
        doc_uuid = doc['document_uuid']
        file_name = doc['file_name']
        
        logger.info(f"Migrating document {doc_id}: {file_name}")
        
        if self.dry_run:
            logger.info(f"[DRY RUN] Would migrate document {doc_id}")
            return True
        
        try:
            # Determine file path
            if doc.get('s3_key') and doc.get('s3_bucket'):
                file_path = f"s3://{doc['s3_bucket']}/{doc['s3_key']}"
            elif doc.get('original_file_path'):
                file_path = doc['original_file_path']
            else:
                logger.error(f"No valid file path for document {doc_id}")
                self.stats['errors'] += 1
                return False
            
            # Get project ID
            project_id = doc.get('project_id')
            if not project_id:
                # Try to get default project
                project_sql_id, _ = self.db.get_or_create_project(PROJECT_ID_GLOBAL)
                project_id = project_sql_id
            
            # Enqueue Celery task
            result = process_ocr.delay(
                document_uuid=doc_uuid,
                source_doc_sql_id=doc_id,
                file_path=file_path,
                file_name=file_name,
                detected_file_type=doc.get('detected_file_type', '.pdf'),
                project_sql_id=project_id
            )
            
            # Update document with Celery task ID
            self.db.client.table('source_documents').update({
                'celery_task_id': result.id,
                'initial_processing_status': 'ocr_queued',
                'last_modified_at': datetime.now().isoformat()
            }).eq('id', doc_id).execute()
            
            logger.info(f"Successfully enqueued document {doc_id} with Celery task {result.id}")
            self.stats['migrated'] += 1
            return True
            
        except Exception as e:
            logger.error(f"Error migrating document {doc_id}: {e}")
            self.stats['errors'] += 1
            return False
    
    def migrate_queue_items(self) -> None:
        """Migrate items from document_processing_queue"""
        
        logger.info("Checking document_processing_queue for pending items...")
        
        try:
            # Find pending queue items
            response = self.db.client.table('document_processing_queue').select(
                'id, source_document_id, source_document_uuid, status, retry_count'
            ).eq('status', 'pending').execute()
            
            queue_items = response.data
            logger.info(f"Found {len(queue_items)} pending queue items")
            
            for item in queue_items:
                source_doc_id = item.get('source_document_id')
                source_doc_uuid = item.get('source_document_uuid')
                
                if not source_doc_id and source_doc_uuid:
                    # Try to find by UUID
                    doc_response = self.db.client.table('source_documents').select(
                        'id'
                    ).eq('document_uuid', source_doc_uuid).maybe_single().execute()
                    
                    if doc_response.data:
                        source_doc_id = doc_response.data['id']
                
                if source_doc_id:
                    # Get full document details
                    doc_response = self.db.client.table('source_documents').select(
                        '*'
                    ).eq('id', source_doc_id).maybe_single().execute()
                    
                    if doc_response.data:
                        self.migrate_document(doc_response.data)
                        
                        # Update queue item status
                        if not self.dry_run:
                            self.db.client.table('document_processing_queue').update({
                                'status': 'processing',
                                'updated_at': datetime.now().isoformat()
                            }).eq('id', item['id']).execute()
                
        except Exception as e:
            logger.error(f"Error migrating queue items: {e}")
    
    def run_migration(self, status_filter: Optional[List[str]] = None,
                     include_stalled: bool = False,
                     stalled_hours: int = 24) -> None:
        """Run the complete migration process"""
        
        logger.info("Starting Celery migration process...")
        if self.dry_run:
            logger.info("Running in DRY RUN mode - no changes will be made")
        
        # Find documents to migrate
        documents = self.find_documents_to_migrate(status_filter)
        
        # Add stalled documents if requested
        if include_stalled:
            stalled_docs = self.find_stalled_documents(stalled_hours)
            documents.extend(stalled_docs)
        
        # Remove duplicates
        seen_ids = set()
        unique_documents = []
        for doc in documents:
            if doc['id'] not in seen_ids:
                seen_ids.add(doc['id'])
                unique_documents.append(doc)
        
        logger.info(f"Total unique documents to migrate: {len(unique_documents)}")
        
        # Migrate each document
        for i, doc in enumerate(unique_documents, 1):
            logger.info(f"Processing document {i}/{len(unique_documents)}")
            self.migrate_document(doc)
        
        # Also migrate queue items
        self.migrate_queue_items()
        
        # Print summary
        logger.info("=" * 50)
        logger.info("Migration Summary:")
        logger.info(f"Total documents found: {self.stats['total_found']}")
        logger.info(f"Documents migrated: {self.stats['migrated']}")
        logger.info(f"Documents skipped: {self.stats['skipped']}")
        logger.info(f"Errors encountered: {self.stats['errors']}")
        logger.info("=" * 50)


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Migrate existing documents to Celery-based processing"
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be migrated without making changes'
    )
    parser.add_argument(
        '--include-stalled',
        action='store_true',
        help='Include documents that have been processing for too long'
    )
    parser.add_argument(
        '--stalled-hours',
        type=int,
        default=24,
        help='Hours to consider a document stalled (default: 24)'
    )
    parser.add_argument(
        '--status',
        nargs='+',
        help='Specific statuses to migrate (default: common error/pending states)'
    )
    
    args = parser.parse_args()
    
    # Create migration instance
    migration = CeleryMigration(dry_run=args.dry_run)
    
    # Run migration
    migration.run_migration(
        status_filter=args.status,
        include_stalled=args.include_stalled,
        stalled_hours=args.stalled_hours
    )


if __name__ == "__main__":
    main()