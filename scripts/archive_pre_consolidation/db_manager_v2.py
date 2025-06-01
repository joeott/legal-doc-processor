"""
Enhanced database manager using PydanticDatabase.
"""
from typing import Optional, List, Dict, Any, Type, TypeVar
from pydantic import BaseModel, create_model
import logging

from scripts.core.pydantic_db import PydanticDatabase
from scripts.supabase_utils import get_supabase_client
from scripts.core.schemas import *
from scripts.core.processing_models import *

logger = logging.getLogger(__name__)

T = TypeVar('T', bound=BaseModel)


class DatabaseManagerV2:
    """Enhanced database manager with Pydantic support."""
    
    def __init__(self):
        self.client = get_supabase_client()
        self.db = PydanticDatabase(self.client)
    
    # Document operations
    def get_document_by_uuid(self, document_uuid: str) -> Optional[SourceDocumentModel]:
        """Get document by UUID."""
        return self.db.read(
            'source_documents',
            SourceDocumentModel,
            {'document_uuid': document_uuid}
        )
    
    def update_document_status(self, document_uuid: str, status: str, error_message: Optional[str] = None) -> bool:
        """Update document processing status."""
        # Create dynamic model for partial update
        fields = {
            'initial_processing_status': (str, status)
        }
        if error_message is not None:
            fields['error_message'] = (Optional[str], error_message)
        
        UpdateModel = create_model('DocumentStatusUpdate', **fields)
        update_model = UpdateModel()
        
        try:
            result = self.db.update(
                'source_documents',
                update_model,
                {'document_uuid': document_uuid}
            )
            return result is not None
        except Exception as e:
            logger.error(f"Failed to update document status: {e}")
            return False
    
    # Chunk operations
    def create_chunks(self, chunks: List[ChunkModel]) -> List[ChunkModel]:
        """Create multiple chunks."""
        created = []
        for chunk in chunks:
            try:
                result = self.db.create('neo4j_chunks', chunk)
                if result:
                    created.append(result)
            except Exception as e:
                logger.error(f"Failed to create chunk: {e}")
        return created
    
    def get_chunks_for_document(self, document_uuid: str) -> List[ChunkModel]:
        """Get all chunks for a document."""
        return self.db.list(
            'neo4j_chunks',
            ChunkModel,
            {'document_uuid': document_uuid},
            order_by='chunk_index'
        )
    
    # Entity operations
    def create_entity_mentions(self, mentions: List[EntityMentionModel]) -> List[EntityMentionModel]:
        """Create multiple entity mentions."""
        created = []
        for mention in mentions:
            try:
                result = self.db.create('neo4j_entity_mentions', mention)
                if result:
                    created.append(result)
            except Exception as e:
                logger.error(f"Failed to create entity mention: {e}")
        return created
    
    def get_entity_mentions_for_document(self, document_uuid: str) -> List[EntityMentionModel]:
        """Get all entity mentions for a document."""
        return self.db.list(
            'neo4j_entity_mentions',
            EntityMentionModel,
            {'source_document_uuid': document_uuid}
        )
    
    # Neo4j document operations
    def create_neo4j_document(self, doc_model: Neo4jDocumentModel) -> Optional[Neo4jDocumentModel]:
        """Create Neo4j document node."""
        return self.db.create('neo4j_documents', doc_model)
    
    def update_neo4j_document_metadata(self, neo4j_doc_id: int, metadata: Dict[str, Any]) -> bool:
        """Update Neo4j document metadata."""
        # Create dynamic model for metadata update
        UpdateModel = create_model(
            'Neo4jDocumentMetadataUpdate',
            doc_metadata=(Optional[Dict[str, Any]], metadata)
        )
        update_model = UpdateModel()
        
        try:
            result = self.db.update(
                'neo4j_documents',
                update_model,
                {'id': neo4j_doc_id}
            )
            return result is not None
        except Exception as e:
            logger.error(f"Failed to update neo4j document metadata: {e}")
            return False
    
    # Generic operations
    def insert_model(self, table: str, model: BaseModel) -> Optional[BaseModel]:
        """Insert any Pydantic model."""
        return self.db.create(table, model)
    
    def update_model(self, table: str, model: BaseModel, match_fields: Dict[str, Any]) -> Optional[BaseModel]:
        """Update using any Pydantic model."""
        return self.db.update(table, model, match_fields)
    
    def select_model(self, table: str, model_class: Type[T], match_fields: Dict[str, Any]) -> Optional[T]:
        """Select and return as Pydantic model."""
        return self.db.read(table, model_class, match_fields)
    
    def select_models(self, table: str, model_class: Type[T],
                     match_fields: Optional[Dict[str, Any]] = None,
                     order_by: Optional[str] = None,
                     limit: Optional[int] = None) -> List[T]:
        """Select multiple records as Pydantic models."""
        return self.db.list(table, model_class, match_fields, order_by, limit)
    
    # Add compatibility method for gradual migration
    def execute_raw_query(self, query):
        """Execute raw query for compatibility."""
        logger.warning("Using raw query - should be migrated to model-based operation")
        return query.execute()


# Singleton instance
_db_manager_v2: Optional[DatabaseManagerV2] = None


def get_db_manager_v2() -> DatabaseManagerV2:
    """Get enhanced database manager instance."""
    global _db_manager_v2
    if _db_manager_v2 is None:
        _db_manager_v2 = DatabaseManagerV2()
    return _db_manager_v2