"""
Pydantic-aware database manager for Supabase operations.
"""
import json
from typing import TypeVar, Type, List, Optional, Dict, Any, Union
from datetime import datetime, date
from decimal import Decimal
from uuid import UUID
from pydantic import BaseModel, ValidationError
from postgrest.exceptions import APIError
import logging

from scripts.core.json_serializer import PydanticJSONEncoder

logger = logging.getLogger(__name__)

T = TypeVar('T', bound=BaseModel)


class PydanticSerializer:
    """Handles all Pydantic model serialization consistently."""
    
    @staticmethod
    def serialize(obj: Any) -> Any:
        """Serialize any object to JSON-compatible format."""
        if isinstance(obj, BaseModel):
            return obj.model_dump(mode='json')
        elif isinstance(obj, (datetime, date)):
            return obj.isoformat()
        elif isinstance(obj, UUID):
            return str(obj)
        elif isinstance(obj, Decimal):
            return float(obj)
        elif isinstance(obj, bytes):
            return obj.decode('utf-8')
        elif hasattr(obj, 'model_dump'):
            return obj.model_dump(mode='json')
        return obj
    
    @staticmethod
    def deserialize(data: Dict[str, Any], model_class: Type[T]) -> T:
        """Deserialize data to Pydantic model with validation."""
        try:
            # Clean empty strings
            cleaned = {k: None if v == "" else v for k, v in data.items()}
            return model_class.model_validate(cleaned)
        except ValidationError as e:
            logger.error(f"Validation failed for {model_class.__name__}: {e}")
            raise


class PydanticDatabase:
    """Database operations with automatic Pydantic model handling."""
    
    def __init__(self, client):
        """Initialize with Supabase client."""
        self.client = client
        self.serializer = PydanticSerializer()
        self.encoder = PydanticJSONEncoder()
    
    def create(self, table: str, model: BaseModel, returning: bool = True) -> Optional[T]:
        """Create record from model, return validated model."""
        try:
            # Serialize model
            data = self._serialize_model(model)
            
            # Perform insert
            query = self.client.table(table).insert(data)
            if returning:
                query = query.select()
            
            result = query.execute()
            
            if returning and result.data:
                return self.serializer.deserialize(result.data[0], model.__class__)
            return None
            
        except APIError as e:
            logger.error(f"Failed to create in {table}: {e}")
            raise
    
    def read(self, table: str, model_class: Type[T], filters: Dict[str, Any]) -> Optional[T]:
        """Read record as validated model."""
        try:
            query = self.client.table(table).select("*")
            for key, value in filters.items():
                query = query.eq(key, value)
            
            result = query.single().execute()
            
            if result.data:
                return self.serializer.deserialize(result.data, model_class)
            return None
            
        except APIError as e:
            if "PGRST116" in str(e):  # No rows found
                return None
            logger.error(f"Failed to read from {table}: {e}")
            raise
    
    def update(self, table: str, model: BaseModel, filters: Dict[str, Any], returning: bool = True) -> Optional[T]:
        """Update record with model, return validated result."""
        try:
            # Serialize model (exclude unset to allow partial updates)
            data = self._serialize_model(model, exclude_unset=True)
            
            # Build query
            query = self.client.table(table).update(data)
            for key, value in filters.items():
                query = query.eq(key, value)
            
            if returning:
                query = query.select()
            
            result = query.execute()
            
            if returning and result.data:
                return self.serializer.deserialize(result.data[0], model.__class__)
            return None
            
        except APIError as e:
            logger.error(f"Failed to update {table}: {e}")
            raise
    
    def delete(self, table: str, filters: Dict[str, Any]) -> bool:
        """Delete records matching filters."""
        try:
            query = self.client.table(table).delete()
            for key, value in filters.items():
                query = query.eq(key, value)
            
            result = query.execute()
            return len(result.data) > 0 if result.data else False
            
        except APIError as e:
            logger.error(f"Failed to delete from {table}: {e}")
            raise
    
    def list(self, table: str, model_class: Type[T], 
             filters: Optional[Dict[str, Any]] = None,
             order_by: Optional[str] = None,
             limit: Optional[int] = None) -> List[T]:
        """List records as validated models."""
        try:
            query = self.client.table(table).select("*")
            
            if filters:
                for key, value in filters.items():
                    query = query.eq(key, value)
            
            if order_by:
                desc = order_by.startswith("-")
                field = order_by[1:] if desc else order_by
                query = query.order(field, desc=desc)
            
            if limit:
                query = query.limit(limit)
            
            result = query.execute()
            
            return [self.serializer.deserialize(item, model_class) for item in result.data]
            
        except APIError as e:
            logger.error(f"Failed to list from {table}: {e}")
            raise
    
    def upsert(self, table: str, model: BaseModel,
               on_conflict: Optional[str] = None,
               returning: bool = True) -> Optional[T]:
        """Insert or update a record."""
        try:
            data = self._serialize_model(model)
            
            query = self.client.table(table).upsert(
                data,
                on_conflict=on_conflict
            )
            
            if returning:
                query = query.select()
            
            result = query.execute()
            
            if returning and result.data:
                return self.serializer.deserialize(result.data[0], model.__class__)
            return None
            
        except APIError as e:
            logger.error(f"Failed to upsert into {table}: {e}")
            raise
    
    def _serialize_model(self, model: BaseModel, exclude_unset: bool = False) -> dict:
        """Serialize Pydantic model to JSON-compatible dict."""
        # Use model_dump to get dict representation
        data = model.model_dump(exclude_unset=exclude_unset, mode='json')
        
        # Ensure all special types are handled
        json_str = json.dumps(data, cls=PydanticJSONEncoder)
        return json.loads(json_str)