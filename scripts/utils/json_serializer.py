"""
Centralized JSON serialization for all Pydantic models and special types.
"""
import json
from datetime import datetime, date
from decimal import Decimal
from uuid import UUID
from typing import Any
from pydantic import BaseModel


class PydanticJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder for Pydantic models and special types."""
    
    def default(self, obj: Any) -> Any:
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
        elif hasattr(obj, '__dict__'):
            return obj.__dict__
        return super().default(obj)


def safe_json_dumps(obj: Any, **kwargs) -> str:
    """Safely serialize any object to JSON."""
    return json.dumps(obj, cls=PydanticJSONEncoder, **kwargs)


def safe_json_loads(json_str: str) -> Any:
    """Safely deserialize JSON string."""
    return json.loads(json_str)