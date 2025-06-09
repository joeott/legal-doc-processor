#!/usr/bin/env python3
"""Add Redis metadata for documents to pass validation"""

import os
import sys
sys.path.insert(0, '/opt/legal-doc-processor')

from datetime import datetime
from scripts.db import DatabaseManager
from scripts.cache import get_redis_manager
from sqlalchemy import text
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def add_metadata_for_documents():
    """Add Redis metadata for test documents"""
    
    db = DatabaseManager(validate_conformance=False)
    redis_mgr = get_redis_manager()
    session = next(db.get_session())
    
    try:
        # Get test documents with their project info
        query = text("""
            SELECT sd.document_uuid, sd.file_name, sd.s3_bucket, sd.s3_key,
                   p.id as project_id, p.project_id as project_uuid, p.name as project_name
            FROM source_documents sd
            JOIN projects p ON sd.project_fk_id = p.id
            WHERE p.name LIKE 'PIPELINE_TEST_%'
            AND sd.created_at::date = CURRENT_DATE
            ORDER BY sd.created_at DESC
        """)
        
        results = session.execute(query).fetchall()
        
        for row in results:
            document_uuid = str(row.document_uuid)
            
            # Create metadata
            metadata = {
                'document_uuid': document_uuid,
                'project_id': row.project_id,
                'project_uuid': str(row.project_uuid),
                'project_name': row.project_name,
                'filename': row.file_name,
                's3_bucket': row.s3_bucket,
                's3_key': row.s3_key,
                'created_at': datetime.now().isoformat(),
                'status': 'ready_for_processing'
            }
            
            # Store in Redis
            metadata_key = f"doc:metadata:{document_uuid}"
            redis_mgr.store_dict(metadata_key, metadata)
            
            logger.info(f"Added metadata for {row.file_name} (UUID: {document_uuid})")
            logger.info(f"  Project: {row.project_name} (ID: {row.project_id})")
        
        logger.info(f"\nAdded metadata for {len(results)} documents")
        
    finally:
        session.close()

if __name__ == "__main__":
    add_metadata_for_documents()