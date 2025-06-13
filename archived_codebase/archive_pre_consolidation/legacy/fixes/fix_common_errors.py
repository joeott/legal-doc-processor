#!/usr/bin/env python3
"""Quick fixes for common pipeline errors"""

import os
import sys
import logging
from datetime import datetime, timedelta

# Add scripts to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scripts.supabase_utils import SupabaseManager
from scripts.textract_utils import TextractProcessor
from scripts.entity_extraction import extract_entities_from_chunk
from scripts.config import DEPLOYMENT_STAGE

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class PipelineFixer:
    """Fixes common pipeline errors"""
    
    def __init__(self):
        self.db = SupabaseManager()
        
    def fix_stuck_processing(self):
        """Reset documents stuck in processing state"""
        logger.info("Fixing documents stuck in processing...")
        
        # Find documents processing for over 30 minutes
        time_threshold = (datetime.now() - timedelta(minutes=30)).isoformat()
        
        stuck_docs = self.db.client.table('document_processing_queue')\
            .select('*')\
            .eq('status', 'processing')\
            .lt('started_at', time_threshold)\
            .execute()
        
        count = 0
        for doc in stuck_docs.data:
            # Reset to pending
            self.db.client.table('document_processing_queue')\
                .update({
                    'status': 'pending',
                    'started_at': None,
                    'processor_metadata': None,
                    'retry_count': doc['retry_count'] + 1
                })\
                .eq('id', doc['id'])\
                .execute()
            count += 1
            
        logger.info(f"Reset {count} stuck documents to pending")
        return count
    
    def fix_missing_text(self):
        """Re-extract text for documents with empty raw_text"""
        logger.info("Fixing documents with missing text...")
        
        # Find documents without text
        docs_without_text = self.db.client.table('source_documents')\
            .select('*')\
            .or_('raw_text.is.null,raw_text.eq.')\
            .eq('status', 'completed')\
            .limit(10)\
            .execute()
        
        count = 0
        for doc in docs_without_text.data:
            logger.info(f"Re-extracting text for document {doc['id']}")
            
            # Create new queue entry
            try:
                self.db.create_queue_entry(doc['id'])
                count += 1
            except Exception as e:
                logger.error(f"Failed to queue document {doc['id']}: {e}")
        
        logger.info(f"Queued {count} documents for re-extraction")
        return count
    
    def fix_failed_textract(self):
        """Retry failed Textract jobs"""
        logger.info("Fixing failed Textract jobs...")
        
        # Find failed Textract jobs
        failed_jobs = self.db.client.table('textract_jobs')\
            .select('*')\
            .eq('status', 'FAILED')\
            .order('created_at', desc=True)\
            .limit(10)\
            .execute()
        
        processor = TextractProcessor(self.db)
        count = 0
        
        for job in failed_jobs.data:
            logger.info(f"Retrying Textract job for document {job['document_uuid']}")
            
            try:
                # Start new Textract job
                new_job_id = processor.start_document_text_detection(
                    s3_bucket=job['s3_bucket'],
                    s3_key=job['s3_key'],
                    document_uuid=job['document_uuid']
                )
                
                if new_job_id:
                    # Update old job status
                    self.db.client.table('textract_jobs')\
                        .update({'status': 'SUPERSEDED'})\
                        .eq('id', job['id'])\
                        .execute()
                    count += 1
                    
            except Exception as e:
                logger.error(f"Failed to retry Textract job {job['id']}: {e}")
        
        logger.info(f"Retried {count} Textract jobs")
        return count
    
    def fix_missing_entities(self):
        """Extract entities for documents that have none"""
        logger.info("Fixing documents with missing entities...")
        
        # Find documents without entities using raw SQL
        query = """
        SELECT DISTINCT d.id, d.uuid
        FROM neo4j_documents d
        LEFT JOIN neo4j_chunks c ON c.document_uuid = d.uuid
        LEFT JOIN neo4j_entity_mentions e ON e.chunk_uuid = c.uuid
        WHERE d.status = 'completed'
        AND c.id IS NOT NULL
        AND e.id IS NULL
        LIMIT 10
        """
        
        # Execute via RPC if available, otherwise use joins
        docs_without_entities = self.db.client.table('neo4j_documents')\
            .select('id, uuid, neo4j_chunks!inner(id, uuid, text)')\
            .eq('status', 'completed')\
            .execute()
        
        count = 0
        for doc in docs_without_entities.data:
            if 'neo4j_chunks' in doc:
                for chunk in doc['neo4j_chunks']:
                    # Check if chunk has entities
                    entities = self.db.client.table('neo4j_entity_mentions')\
                        .select('id')\
                        .eq('chunk_uuid', chunk['uuid'])\
                        .limit(1)\
                        .execute()
                    
                    if not entities.data:
                        # Extract entities
                        logger.info(f"Extracting entities for chunk {chunk['id']}")
                        try:
                            extracted = extract_entities_from_chunk(chunk['text'])
                            
                            for entity in extracted:
                                self.db.create_entity_mention_entry(
                                    chunk_uuid=chunk['uuid'],
                                    entity_value=entity.get('value'),
                                    entity_type=entity.get('entity_type'),
                                    confidence_score=entity.get('confidence', 0.8),
                                    char_start_index=entity.get('offsetStart', 0),
                                    char_end_index=entity.get('offsetEnd', 0),
                                    attributes_json=entity.get('attributes_json', {})
                                )
                            count += 1
                            
                        except Exception as e:
                            logger.error(f"Failed to extract entities for chunk {chunk['id']}: {e}")
        
        logger.info(f"Extracted entities for {count} chunks")
        return count
    
    def fix_orphaned_queue_entries(self):
        """Remove queue entries for deleted documents"""
        logger.info("Fixing orphaned queue entries...")
        
        # Find queue entries without matching source documents
        orphaned = self.db.client.table('document_processing_queue')\
            .select('id, source_document_id')\
            .execute()
        
        count = 0
        for entry in orphaned.data:
            # Check if source document exists
            doc = self.db.client.table('source_documents')\
                .select('id')\
                .eq('id', entry['source_document_id'])\
                .single()\
                .execute()
            
            if not doc.data:
                # Delete orphaned entry
                self.db.client.table('document_processing_queue')\
                    .delete()\
                    .eq('id', entry['id'])\
                    .execute()
                count += 1
        
        logger.info(f"Removed {count} orphaned queue entries")
        return count
    
    def run_all_fixes(self):
        """Run all fix procedures"""
        logger.info("Running all pipeline fixes...")
        
        results = {
            'stuck_processing': self.fix_stuck_processing(),
            'missing_text': self.fix_missing_text(),
            'failed_textract': self.fix_failed_textract(),
            'missing_entities': self.fix_missing_entities(),
            'orphaned_entries': self.fix_orphaned_queue_entries()
        }
        
        logger.info("Fix summary:")
        for fix_type, count in results.items():
            logger.info(f"  {fix_type}: {count} items fixed")
        
        return results


def main():
    """Main execution"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Fix common pipeline errors")
    parser.add_argument("--fix", choices=[
        'stuck', 'text', 'textract', 'entities', 'orphaned', 'all'
    ], default='all', help="Type of fix to run")
    
    args = parser.parse_args()
    
    fixer = PipelineFixer()
    
    if args.fix == 'stuck':
        fixer.fix_stuck_processing()
    elif args.fix == 'text':
        fixer.fix_missing_text()
    elif args.fix == 'textract':
        fixer.fix_failed_textract()
    elif args.fix == 'entities':
        fixer.fix_missing_entities()
    elif args.fix == 'orphaned':
        fixer.fix_orphaned_queue_entries()
    else:
        fixer.run_all_fixes()
    
    logger.info("Done!")


if __name__ == "__main__":
    main()