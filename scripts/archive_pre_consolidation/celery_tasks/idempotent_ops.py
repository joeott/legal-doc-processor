"""Idempotent database operations for reprocessing support"""
from typing import Tuple, Optional
import logging
import json
from datetime import datetime

logger = logging.getLogger(__name__)

class IdempotentDatabaseOps:
    """Database operations that handle duplicates gracefully"""
    
    def __init__(self, db_manager):
        self.db = db_manager
        
    def upsert_neo4j_document(self, source_doc_uuid: str, 
                             source_doc_id: int,
                             project_id: int,
                             project_uuid: str,
                             file_name: str) -> Tuple[int, str]:
        """Create or update neo4j_document entry"""
        try:
            # Check if document already exists
            existing = self.db.client.table('neo4j_documents').select(
                'id', 'documentId'
            ).eq('documentId', source_doc_uuid).maybe_single().execute()
            
            if existing and existing.data:
                # Update existing document
                doc_id = existing.data['id']
                doc_uuid = existing.data['documentId']
                
                self.db.client.table('neo4j_documents').update({
                    'updatedAt': datetime.now().isoformat(),
                    'processingStatus': 'reprocessing',
                    'name': file_name,  # Update name in case it changed
                    'project_id': project_id,
                    'project_uuid': project_uuid
                }).eq('id', doc_id).execute()
                
                logger.info(f"Updated existing neo4j_document {doc_id}")
                return doc_id, doc_uuid
            else:
                # Create new document using existing method
                return self.db.create_neo4j_document_entry(
                    source_doc_fk_id=source_doc_id,
                    source_doc_uuid=source_doc_uuid,
                    project_fk_id=project_id,
                    project_uuid=project_uuid,
                    file_name=file_name
                )
        except Exception as e:
            logger.error(f"Error in upsert_neo4j_document: {e}")
            raise
    
    def upsert_chunk(self, document_id: int, document_uuid: str,
                    chunk_index: int, chunk_text: str, 
                    chunk_metadata: dict) -> Tuple[int, str]:
        """Create or update chunk entry"""
        try:
            # Check for existing chunk
            existing = self.db.client.table('neo4j_chunks').select(
                'id', 'chunkId'
            ).eq('document_id', document_id).eq('chunkIndex', chunk_index).maybe_single().execute()
            
            if existing and existing.data:
                # Update existing chunk
                chunk_id = existing.data['id']
                chunk_uuid = existing.data['chunkId']
                
                self.db.client.table('neo4j_chunks').update({
                    'text': chunk_text,
                    'metadata_json': json.dumps(chunk_metadata) if isinstance(chunk_metadata, dict) else chunk_metadata,
                    'updatedAt': datetime.now().isoformat()
                }).eq('id', chunk_id).execute()
                
                logger.info(f"Updated existing chunk {chunk_id} (index {chunk_index})")
                return chunk_id, chunk_uuid
            else:
                # Create new chunk using existing method
                return self.db.create_chunk_entry(
                    document_fk_id=document_id,
                    document_uuid=document_uuid,
                    text_content=chunk_text,
                    chunk_index=chunk_index,
                    metadata_json=chunk_metadata
                )
        except Exception as e:
            logger.error(f"Error in upsert_chunk: {e}")
            raise
    
    def clear_chunks_for_document(self, neo4j_doc_id: int) -> int:
        """Clear all chunks for a document before reprocessing"""
        try:
            # Get chunk IDs first
            chunks = self.db.client.table('neo4j_chunks').select('id').eq('document_id', neo4j_doc_id).execute()
            chunk_ids = [c['id'] for c in chunks.data]
            
            if chunk_ids:
                # Delete entity mentions first
                self.db.client.table('neo4j_entity_mentions').delete().in_('chunk_fk_id', chunk_ids).execute()
                logger.info(f"Deleted entity mentions for {len(chunk_ids)} chunks")
                
                # Delete chunks
                self.db.client.table('neo4j_chunks').delete().eq('document_id', neo4j_doc_id).execute()
                logger.info(f"Deleted {len(chunk_ids)} chunks for document {neo4j_doc_id}")
                
            return len(chunk_ids)
        except Exception as e:
            logger.error(f"Error clearing chunks: {e}")
            raise
    
    def upsert_entity_mention(self, chunk_id: int, chunk_uuid: str,
                             entity_data: dict) -> Tuple[int, str]:
        """Create or update entity mention with duplicate handling"""
        try:
            # For entity mentions, we typically want to clear and recreate
            # rather than update, as the extraction logic may have changed
            return self.db.create_entity_mention_entry(
                chunk_sql_id=chunk_id,
                chunk_uuid=chunk_uuid,
                value=entity_data['value'],
                entity_type_label=entity_data['entity_type'],
                norm_value=entity_data.get('normalized_value'),
                display_value=entity_data.get('display_value'),
                rationale=entity_data.get('rationale'),
                attributes_json_str=entity_data.get('attributes_json'),
                phone=entity_data.get('phone'),
                email=entity_data.get('email'),
                start_offset=entity_data.get('start_offset'),
                end_offset=entity_data.get('end_offset')
            )
        except Exception as e:
            logger.error(f"Error in upsert_entity_mention: {e}")
            raise