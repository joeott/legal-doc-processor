"""
Simplified Database Manager using minimal models as source of truth.
No conformance validation - models define the schema.
"""
import json
import logging
import os
from datetime import datetime
from typing import TypeVar, Optional, Dict, Any, List, Union, Type
from uuid import UUID
from decimal import Decimal

from pydantic import BaseModel
from sqlalchemy import func, text
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError

# Import minimal models - the source of truth
from scripts.models import (
    SourceDocumentMinimal,
    DocumentChunkMinimal,
    EntityMentionMinimal,
    CanonicalEntityMinimal,
    RelationshipStagingMinimal,
    ModelFactory
)

from scripts.core.json_serializer import PydanticJSONEncoder

logger = logging.getLogger(__name__)

T = TypeVar('T', bound=BaseModel)

# Import global engine and session factory from config
from scripts.config import db_engine, DBSessionLocal

# The engine is now db_engine from scripts.config
engine = db_engine  # For backward compatibility
# SessionLocal is now DBSessionLocal from scripts.config

def get_db():
    """Get database session with automatic cleanup."""
    db = DBSessionLocal()
    try:
        yield db
        db.commit()
    except:
        db.rollback()
        raise
    finally:
        db.close()


class PydanticSerializer:
    """Enhanced serializer for Pydantic models with type preservation."""
    
    @staticmethod
    def serialize_for_db(obj: Any) -> Any:
        """Serialize object for database storage."""
        if isinstance(obj, BaseModel):
            return obj.model_dump(mode='json')
        elif isinstance(obj, dict):
            return {k: PydanticSerializer.serialize_for_db(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [PydanticSerializer.serialize_for_db(item) for item in obj]
        elif isinstance(obj, UUID):
            return str(obj)
        elif isinstance(obj, datetime):
            return obj.isoformat()
        elif isinstance(obj, Decimal):
            return float(obj)
        else:
            return obj
    
    @staticmethod
    def deserialize_from_db(data: Any, model_class: Optional[Type[T]] = None) -> Any:
        """Deserialize data from database."""
        if model_class and isinstance(data, dict):
            return model_class(**data)
        return data


class PydanticDatabase:
    """Database operations with Pydantic model support."""
    
    def __init__(self):
        self.serializer = PydanticSerializer()
    
    def insert_model(self, session: Session, model: BaseModel, table_name: str) -> Dict[str, Any]:
        """Insert a Pydantic model into the database."""
        try:
            data = self.serializer.serialize_for_db(model)
            
            stmt = insert(text(f'"{table_name}"')).values(**data)
            result = session.execute(stmt)
            session.commit()
            
            return {"success": True, "data": data}
        except IntegrityError as e:
            session.rollback()
            logger.error(f"Integrity error inserting into {table_name}: {e}")
            return {"success": False, "error": str(e)}
        except Exception as e:
            session.rollback()
            logger.error(f"Error inserting into {table_name}: {e}")
            raise
    
    def query_models(
        self,
        session: Session,
        model_class: Type[T],
        table_name: str,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[T]:
        """Query database and return Pydantic models."""
        try:
            query = f'SELECT * FROM "{table_name}"'
            params = {}
            
            if filters:
                conditions = []
                for key, value in filters.items():
                    param_name = f"param_{key}"
                    conditions.append(f"{key} = :{param_name}")
                    params[param_name] = value
                query += " WHERE " + " AND ".join(conditions)
            
            if limit:
                query += f" LIMIT {limit}"
            
            result = session.execute(text(query), params)
            rows = result.fetchall()
            
            models = []
            for row in rows:
                row_dict = dict(row._mapping)
                model = self.serializer.deserialize_from_db(row_dict, model_class)
                models.append(model)
            
            return models
        except Exception as e:
            logger.error(f"Error querying {table_name}: {e}")
            raise


class DatabaseManager:
    """
    Simplified database operations manager.
    Uses minimal models as the source of truth.
    """
    
    def __init__(self):
        """Initialize database manager."""
        self.pydantic_db = PydanticDatabase()
        self.serializer = PydanticSerializer()
        self._request_count = 0
        self._error_count = 0
        self._last_request_time = None
    
    def get_session(self):
        """Get database session."""
        return get_db()
    
    def update_metrics(self, success: bool = True):
        """Update request metrics."""
        self._request_count += 1
        if not success:
            self._error_count += 1
        self._last_request_time = datetime.utcnow()
    
    # ========== Document Operations ==========
    
    def create_source_document(self, document: SourceDocumentMinimal) -> bool:
        """Create a new source document."""
        session = next(self.get_session())
        try:
            result = self.pydantic_db.insert_model(session, document, "source_documents")
            self.update_metrics(success=result["success"])
            return result["success"]
        finally:
            session.close()
    
    def get_source_document(self, document_uuid: Union[str, UUID]) -> Optional[SourceDocumentMinimal]:
        """Get source document by UUID."""
        session = next(self.get_session())
        try:
            documents = self.pydantic_db.query_models(
                session,
                SourceDocumentMinimal,
                "source_documents",
                filters={"document_uuid": str(document_uuid)},
                limit=1
            )
            self.update_metrics()
            return documents[0] if documents else None
        except Exception as e:
            self.update_metrics(success=False)
            logger.error(f"Error getting document {document_uuid}: {e}")
            return None
        finally:
            session.close()
    
    def update_document_status(
        self,
        document_uuid: Union[str, UUID],
        status: str,
        error_message: Optional[str] = None
    ) -> bool:
        """Update document processing status."""
        session = next(self.get_session())
        try:
            query = text("""
                UPDATE source_documents 
                SET status = :status, 
                    updated_at = NOW(),
                    error_message = :error_message,
                    processing_completed_at = CASE 
                        WHEN :status IN ('completed', 'failed') THEN NOW() 
                        ELSE processing_completed_at 
                    END
                WHERE document_uuid = :document_uuid
            """)
            
            result = session.execute(query, {
                'status': status,
                'error_message': error_message,
                'document_uuid': str(document_uuid)
            })
            session.commit()
            
            self.update_metrics()
            return result.rowcount > 0
        except Exception as e:
            session.rollback()
            self.update_metrics(success=False)
            logger.error(f"Error updating document status: {e}")
            return False
        finally:
            session.close()
    
    # ========== Chunk Operations ==========
    
    def create_chunks(self, chunks: List[DocumentChunkMinimal]) -> int:
        """Create multiple document chunks."""
        if not chunks:
            return 0
        
        session = next(self.get_session())
        created_count = 0
        
        try:
            for chunk in chunks:
                result = self.pydantic_db.insert_model(session, chunk, "document_chunks")
                if result["success"]:
                    created_count += 1
            
            self.update_metrics()
            return created_count
        except Exception as e:
            session.rollback()
            self.update_metrics(success=False)
            logger.error(f"Error creating chunks: {e}")
            raise
        finally:
            session.close()
    
    def get_document_chunks(self, document_uuid: Union[str, UUID]) -> List[DocumentChunkMinimal]:
        """Get all chunks for a document."""
        session = next(self.get_session())
        try:
            chunks = self.pydantic_db.query_models(
                session,
                DocumentChunkMinimal,
                "document_chunks",
                filters={"document_uuid": str(document_uuid)}
            )
            self.update_metrics()
            return chunks
        except Exception as e:
            self.update_metrics(success=False)
            logger.error(f"Error getting chunks: {e}")
            return []
        finally:
            session.close()
    
    # ========== Entity Operations ==========
    
    def create_entity_mentions(self, mentions: List[EntityMentionMinimal]) -> int:
        """Create multiple entity mentions."""
        if not mentions:
            return 0
        
        session = next(self.get_session())
        created_count = 0
        
        try:
            for mention in mentions:
                result = self.pydantic_db.insert_model(session, mention, "entity_mentions")
                if result["success"]:
                    created_count += 1
            
            self.update_metrics()
            return created_count
        except Exception as e:
            session.rollback()
            self.update_metrics(success=False)
            logger.error(f"Error creating entity mentions: {e}")
            raise
        finally:
            session.close()
    
    def create_canonical_entities(self, entities: List[CanonicalEntityMinimal]) -> int:
        """Create multiple canonical entities."""
        if not entities:
            return 0
        
        session = next(self.get_session())
        created_count = 0
        
        try:
            for entity in entities:
                result = self.pydantic_db.insert_model(session, entity, "canonical_entities")
                if result["success"]:
                    created_count += 1
            
            self.update_metrics()
            return created_count
        except Exception as e:
            session.rollback()
            self.update_metrics(success=False)
            logger.error(f"Error creating canonical entities: {e}")
            raise
        finally:
            session.close()
    
    # ========== Relationship Operations ==========
    
    def create_relationships(self, relationships: List[RelationshipStagingMinimal]) -> int:
        """Create multiple relationships."""
        if not relationships:
            return 0
        
        session = next(self.get_session())
        created_count = 0
        
        try:
            for rel in relationships:
                result = self.pydantic_db.insert_model(session, rel, "relationship_staging")
                if result["success"]:
                    created_count += 1
            
            self.update_metrics()
            return created_count
        except Exception as e:
            session.rollback()
            self.update_metrics(success=False)
            logger.error(f"Error creating relationships: {e}")
            raise
        finally:
            session.close()
    
    # ========== Metrics ==========
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get database operation metrics."""
        return {
            "total_requests": self._request_count,
            "error_count": self._error_count,
            "error_rate": self._error_count / self._request_count if self._request_count > 0 else 0,
            "last_request": self._last_request_time.isoformat() if self._last_request_time else None
        }


# Create a singleton instance for backward compatibility
_db_manager = None

def get_db_manager() -> DatabaseManager:
    """Get or create database manager instance."""
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager()
    return _db_manager