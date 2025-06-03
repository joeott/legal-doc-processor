#!/usr/bin/env python3
"""
Recovery Script for Stuck Documents
Resets stuck documents and queue entries for reprocessing
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional
from scripts.supabase_utils import SupabaseManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DocumentRecovery:
    def __init__(self):
        self.db = SupabaseManager()
        self.recovered_count = 0
        
    def find_stuck_documents(self, hours_threshold: int = 1) -> List[Dict]:
        """Find documents stuck in processing"""
        try:
            cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours_threshold)
            
            stuck_docs = self.db.client.table('source_documents').select(
                'id', 'original_file_name', 'initial_processing_status', 
                'last_modified_at', 'textract_job_id'
            ).in_('initial_processing_status', [
                'pending_ocr', 'processing', 'pending_intake'
            ]).lt('last_modified_at', cutoff_time.isoformat()).execute()
            
            return stuck_docs.data if stuck_docs.data else []
        except Exception as e:
            logger.error(f"Error finding stuck documents: {e}")
            return []
    
    def reset_queue_entry(self, source_doc_id: int) -> bool:
        """Reset queue entry for a document"""
        try:
            # Find queue entries for this document
            queue_entries = self.db.client.table('document_processing_queue').select(
                'id', 'status', 'retry_count'
            ).eq('source_document_id', source_doc_id).execute()
            
            if not queue_entries.data:
                logger.warning(f"No queue entry found for document {source_doc_id}")
                return False
                
            for entry in queue_entries.data:
                # Reset the queue entry
                update_result = self.db.client.table('document_processing_queue').update({
                    'status': 'pending',
                    'retry_count': 0,
                    'started_at': None,
                    'completed_at': None,
                    'error_message': f'Reset by recovery script at {datetime.now(timezone.utc).isoformat()}',
                    'processor_metadata': None,
                    'updated_at': datetime.now(timezone.utc).isoformat()
                }).eq('id', entry['id']).execute()
                
                logger.info(f"Reset queue entry {entry['id']} for document {source_doc_id}")
                
            return True
        except Exception as e:
            logger.error(f"Error resetting queue entry for document {source_doc_id}: {e}")
            return False
    
    def clear_incomplete_textract_jobs(self, source_doc_id: int) -> bool:
        """Mark incomplete Textract jobs as failed"""
        try:
            # Find any submitted/in_progress jobs
            incomplete_jobs = self.db.client.table('textract_jobs').select(
                'id', 'job_id', 'job_status'
            ).eq('source_document_id', source_doc_id).in_('job_status', [
                'SUBMITTED', 'IN_PROGRESS', 'submitted', 'in_progress'
            ]).execute()
            
            if incomplete_jobs.data:
                for job in incomplete_jobs.data:
                    # Mark as failed
                    self.db.client.table('textract_jobs').update({
                        'job_status': 'failed',
                        'error_message': 'Marked failed by recovery script - timeout',
                        'completed_at': datetime.now(timezone.utc).isoformat()
                    }).eq('id', job['id']).execute()
                    
                    logger.info(f"Marked Textract job {job['job_id'][:20]}... as failed")
                    
            return True
        except Exception as e:
            logger.error(f"Error clearing Textract jobs for document {source_doc_id}: {e}")
            return False
    
    def reset_document_status(self, doc_id: int, status: str = 'pending_intake') -> bool:
        """Reset document status for reprocessing"""
        try:
            # Reset the document status
            self.db.client.table('source_documents').update({
                'initial_processing_status': status,
                'textract_job_id': None,
                'textract_job_status': 'not_started',
                'raw_extracted_text': None,
                'last_modified_at': datetime.now(timezone.utc).isoformat()
            }).eq('id', doc_id).execute()
            
            logger.info(f"Reset document {doc_id} status to {status}")
            return True
        except Exception as e:
            logger.error(f"Error resetting document {doc_id} status: {e}")
            return False
    
    def recover_document(self, doc: Dict, reset_status: bool = False) -> bool:
        """Recover a single stuck document"""
        doc_id = doc['id']
        file_name = doc['original_file_name']
        
        logger.info(f"\nRecovering document {doc_id}: {file_name}")
        logger.info(f"  Current status: {doc['initial_processing_status']}")
        logger.info(f"  Last modified: {doc['last_modified_at']}")
        
        success = True
        
        # Reset queue entry
        if not self.reset_queue_entry(doc_id):
            success = False
            
        # Clear incomplete Textract jobs
        if not self.clear_incomplete_textract_jobs(doc_id):
            success = False
            
        # Optionally reset document status
        if reset_status:
            if not self.reset_document_status(doc_id):
                success = False
                
        if success:
            self.recovered_count += 1
            logger.info(f"✓ Successfully recovered document {doc_id}")
        else:
            logger.error(f"✗ Failed to fully recover document {doc_id}")
            
        return success
    
    def recover_all_stuck_documents(self, hours_threshold: int = 1, 
                                   reset_status: bool = False,
                                   dry_run: bool = False) -> Dict:
        """Recover all stuck documents"""
        logger.info(f"\nSearching for documents stuck for more than {hours_threshold} hour(s)...")
        
        stuck_docs = self.find_stuck_documents(hours_threshold)
        
        if not stuck_docs:
            logger.info("No stuck documents found!")
            return {'total': 0, 'recovered': 0, 'failed': 0}
            
        logger.info(f"Found {len(stuck_docs)} stuck documents")
        
        if dry_run:
            logger.info("\nDRY RUN - No changes will be made:")
            for doc in stuck_docs:
                print(f"  - ID: {doc['id']}, File: {doc['original_file_name']}, "
                      f"Status: {doc['initial_processing_status']}")
            return {'total': len(stuck_docs), 'recovered': 0, 'failed': 0}
        
        # Recover each document
        failed_count = 0
        for doc in stuck_docs:
            if not self.recover_document(doc, reset_status):
                failed_count += 1
                
        return {
            'total': len(stuck_docs),
            'recovered': self.recovered_count,
            'failed': failed_count
        }
    
    def recover_specific_documents(self, doc_ids: List[int], reset_status: bool = False) -> Dict:
        """Recover specific documents by ID"""
        logger.info(f"\nRecovering specific documents: {doc_ids}")
        
        recovered = 0
        failed = 0
        
        for doc_id in doc_ids:
            # Get document info
            doc_result = self.db.client.table('source_documents').select(
                'id', 'original_file_name', 'initial_processing_status', 
                'last_modified_at', 'textract_job_id'
            ).eq('id', doc_id).execute()
            
            if not doc_result.data:
                logger.error(f"Document {doc_id} not found")
                failed += 1
                continue
                
            doc = doc_result.data[0]
            if self.recover_document(doc, reset_status):
                recovered += 1
            else:
                failed += 1
                
        return {
            'total': len(doc_ids),
            'recovered': recovered,
            'failed': failed
        }


def main():
    """Main recovery function"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Recover stuck documents in the processing pipeline')
    parser.add_argument('--hours', type=int, default=1, 
                       help='Hours threshold for considering a document stuck (default: 1)')
    parser.add_argument('--reset-status', action='store_true',
                       help='Reset document status to pending_intake')
    parser.add_argument('--dry-run', action='store_true',
                       help='Show what would be recovered without making changes')
    parser.add_argument('--doc-ids', type=int, nargs='+',
                       help='Specific document IDs to recover')
    
    args = parser.parse_args()
    
    recovery = DocumentRecovery()
    
    if args.doc_ids:
        # Recover specific documents
        results = recovery.recover_specific_documents(args.doc_ids, args.reset_status)
    else:
        # Recover all stuck documents
        results = recovery.recover_all_stuck_documents(
            hours_threshold=args.hours,
            reset_status=args.reset_status,
            dry_run=args.dry_run
        )
    
    # Print summary
    print("\n" + "="*60)
    print("RECOVERY SUMMARY")
    print("="*60)
    print(f"Total documents processed: {results['total']}")
    print(f"Successfully recovered: {results['recovered']}")
    print(f"Failed to recover: {results['failed']}")
    print("="*60)
    
    return 0 if results['failed'] == 0 else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())