#!/usr/bin/env python3
"""
Execute document UUID migration step by step
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scripts.supabase_utils import SupabaseManager
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def execute_migration():
    """Execute the migration step by step using API calls"""
    db = SupabaseManager()
    
    logger.info("Starting Document UUID Migration...")
    
    # Step 1: Identify non-conforming documents
    logger.info("\nStep 1: Identifying non-conforming documents...")
    neo4j_docs = db.client.table('neo4j_documents').select(
        'id, documentId, name, source_documents!neo4j_documents_source_document_fk_id_fkey(document_uuid)'
    ).execute()
    
    non_conforming_ids = []
    for doc in neo4j_docs.data:
        if doc['documentId'] != doc['source_documents']['document_uuid']:
            non_conforming_ids.append(doc['id'])
            logger.info(f"  - {doc['name']} (ID: {doc['id']})")
    
    if not non_conforming_ids:
        logger.info("No non-conforming documents found!")
        return True
    
    logger.info(f"Found {len(non_conforming_ids)} non-conforming documents")
    
    # Step 2: Delete entity mentions
    logger.info("\nStep 2: Deleting entity mentions...")
    # First get chunk IDs
    chunks = db.client.table('neo4j_chunks').select('id').in_('document_id', non_conforming_ids).execute()
    chunk_ids = [c['id'] for c in chunks.data]
    
    if chunk_ids:
        mentions = db.client.table('neo4j_entity_mentions').delete().in_('chunk_fk_id', chunk_ids).execute()
        logger.info(f"  Deleted {len(mentions.data)} entity mentions")
    
    # Step 3: Delete chunks
    logger.info("\nStep 3: Deleting chunks...")
    if non_conforming_ids:
        chunks_del = db.client.table('neo4j_chunks').delete().in_('document_id', non_conforming_ids).execute()
        logger.info(f"  Deleted {len(chunks_del.data)} chunks")
    
    # Step 4: Get documentIds for canonical entities and relationships
    logger.info("\nStep 4: Getting documentIds for cleanup...")
    doc_uuids = []
    for doc in neo4j_docs.data:
        if doc['id'] in non_conforming_ids:
            doc_uuids.append(doc['documentId'])
    
    # Step 5: Delete canonical entities
    logger.info("\nStep 5: Deleting canonical entities...")
    if doc_uuids:
        canonical = db.client.table('neo4j_canonical_entities').delete().in_('document_uuid', doc_uuids).execute()
        logger.info(f"  Deleted {len(canonical.data)} canonical entities")
    
    # Step 6: Delete relationships
    logger.info("\nStep 6: Deleting relationships...")
    if doc_uuids:
        # Delete relationships where the document is either from or to
        rel_from = db.client.table('neo4j_relationships_staging').delete().eq('fromNodeLabel', 'Document').in_('fromNodeId', doc_uuids).execute()
        rel_to = db.client.table('neo4j_relationships_staging').delete().eq('toNodeLabel', 'Document').in_('toNodeId', doc_uuids).execute()
        total_deleted = len(rel_from.data) + len(rel_to.data)
        logger.info(f"  Deleted {total_deleted} relationships")
    
    # Step 7: Delete neo4j_documents
    logger.info("\nStep 7: Deleting non-conforming neo4j_documents...")
    for doc_id in non_conforming_ids:
        try:
            result = db.client.table('neo4j_documents').delete().eq('id', doc_id).execute()
            logger.info(f"  Deleted document {doc_id}")
        except Exception as e:
            logger.error(f"  Failed to delete document {doc_id}: {e}")
    
    logger.info("\nMigration data cleanup complete!")
    
    # Note about manual steps
    logger.info("\n" + "="*60)
    logger.info("MANUAL STEPS REQUIRED:")
    logger.info("Please execute the following SQL in Supabase SQL Editor:")
    logger.info("")
    logger.info("-- Add NOT NULL constraint")
    logger.info("ALTER TABLE public.neo4j_documents")
    logger.info("ALTER COLUMN documentId SET NOT NULL;")
    logger.info("")
    logger.info("-- Drop redundant column")
    logger.info("ALTER TABLE public.neo4j_documents")
    logger.info("DROP COLUMN IF EXISTS source_document_uuid;")
    logger.info("="*60)
    
    return True


if __name__ == "__main__":
    success = execute_migration()
    if success:
        logger.info("\n✅ Migration executed successfully!")
        logger.info("Please complete the manual SQL steps above.")
    else:
        logger.error("\n❌ Migration failed!")
        sys.exit(1)