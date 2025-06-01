"""
SQLAlchemy-based schema reflection and Pydantic model generation.
"""

from typing import Dict, List, Optional, Any, Type, Union
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path

from sqlalchemy import create_engine, MetaData, inspect
from sqlalchemy.engine import Engine, Inspector
from sqlalchemy.sql.sqltypes import (
    String, Integer, BigInteger, Boolean, DateTime, 
    Date, Time, Float, Numeric, JSON, UUID, Text,
    TIMESTAMP, VARCHAR, CHAR, BOOLEAN
)
try:
    from sqlalchemy.dialects.postgresql import JSONB
except ImportError:
    JSONB = JSON  # Fallback to regular JSON if JSONB not available
from pydantic import BaseModel, Field, create_model
from pydantic.fields import FieldInfo


class SchemaReflector:
    """Reflects database schema using SQLAlchemy and generates Pydantic models."""
    
    def __init__(self, database_url: str):
        self.engine = create_engine(database_url)
        self.metadata = MetaData()
        self.inspector: Inspector = inspect(self.engine)
        self._type_mapping = self._initialize_type_mapping()
        
    def _initialize_type_mapping(self) -> Dict[Type, Type]:
        """Map SQLAlchemy types to Python/Pydantic types."""
        return {
            String: str,
            VARCHAR: str,
            CHAR: str,
            Text: str,
            Integer: int,
            BigInteger: int,
            Boolean: bool,
            BOOLEAN: bool,
            DateTime: datetime,
            TIMESTAMP: datetime,
            Date: datetime,
            Time: datetime,
            Float: float,
            Numeric: Decimal,
            JSON: Dict[str, Any],
            JSONB: Dict[str, Any],
            UUID: str,  # Pydantic handles UUID strings
        }
    
    def reflect_table(self, table_name: str) -> Dict[str, Any]:
        """Reflect a single table's structure."""
        columns = self.inspector.get_columns(table_name)
        pk_constraint = self.inspector.get_pk_constraint(table_name)
        foreign_keys = self.inspector.get_foreign_keys(table_name)
        indexes = self.inspector.get_indexes(table_name)
        unique_constraints = self.inspector.get_unique_constraints(table_name)
        
        # Get table comment if available
        try:
            comment = self.inspector.get_table_comment(table_name)
        except NotImplementedError:
            comment = None
        
        return {
            'name': table_name,
            'columns': columns,
            'primary_key': pk_constraint,
            'foreign_keys': foreign_keys,
            'indexes': indexes,
            'unique_constraints': unique_constraints,
            'comment': comment
        }
    
    def generate_pydantic_model(self, table_name: str) -> Type[BaseModel]:
        """Generate a Pydantic model from table reflection."""
        table_info = self.reflect_table(table_name)
        
        # Build field definitions
        fields = {}
        for column in table_info['columns']:
            field_type = self._get_python_type(column['type'])
            field_default = ... if not column['nullable'] else None
            
            # Handle defaults
            if column.get('default'):
                # SQLAlchemy returns defaults as strings, need parsing
                field_default = self._parse_default(column['default'])
            
            # Create field with proper annotation
            if column['nullable']:
                field_type = Optional[field_type]
            
            fields[column['name']] = (
                field_type,
                Field(
                    default=field_default,
                    description=column.get('comment'),
                    alias=column['name']  # Preserve exact DB names
                )
            )
        
        # Create model class
        model_name = self._table_to_model_name(table_name)
        model = create_model(
            model_name,
            **fields,
            __module__='generated.models'
        )
        
        # Add configuration
        model.__config__ = type('Config', (), {
            'from_attributes': True,
            'populate_by_name': True,
            'json_encoders': {
                datetime: lambda v: v.isoformat(),
                Decimal: lambda v: float(v)
            }
        })
        
        return model
    
    def _get_python_type(self, sql_type: Any) -> Type:
        """Convert SQLAlchemy type to Python type."""
        # Check exact type matches first
        type_class = type(sql_type)
        if type_class in self._type_mapping:
            return self._type_mapping[type_class]
            
        # Check instance matches
        for sql_class, py_type in self._type_mapping.items():
            if isinstance(sql_type, sql_class):
                return py_type
                
        # Check string representation for custom types
        type_str = str(sql_type).upper()
        if 'UUID' in type_str:
            return str
        elif 'JSON' in type_str:
            return Dict[str, Any]
        elif 'BOOL' in type_str:
            return bool
        elif 'INT' in type_str:
            return int
        elif 'FLOAT' in type_str or 'NUMERIC' in type_str or 'DECIMAL' in type_str:
            return float
        elif 'TIME' in type_str or 'DATE' in type_str:
            return datetime
            
        # Default to Any for unknown types
        return Any
    
    def _parse_default(self, default_str: str) -> Any:
        """Parse SQLAlchemy default value strings."""
        if isinstance(default_str, str):
            # Handle boolean strings
            if default_str.lower() in ('true', 'false'):
                return default_str.lower() == 'true'
            # Handle numeric strings
            elif default_str.replace('-', '').replace('.', '').isdigit():
                if '.' in default_str:
                    return float(default_str)
                else:
                    return int(default_str)
            # Handle quoted strings
            elif default_str.startswith("'") and default_str.endswith("'"):
                return default_str[1:-1]
            # Handle PostgreSQL specific defaults
            elif default_str.startswith('nextval('):
                return None  # Auto-increment
            elif default_str in ('now()', 'CURRENT_TIMESTAMP'):
                return None  # Will be set by database
        return default_str
    
    def _table_to_model_name(self, table_name: str) -> str:
        """Convert table_name to ModelName."""
        # Handle special cases
        if table_name == 'import_sessions':
            return 'ImportSession'
        elif table_name == 'processing_pipeline':
            return 'ProcessingPipeline'
        elif table_name == 'processing_queue':
            return 'ProcessingQueue'
        elif table_name == 'document_chunks':
            return 'DocumentChunk'
        elif table_name == 'entity_mentions':
            return 'EntityMention'
        elif table_name == 'canonical_entities':
            return 'CanonicalEntity'
        elif table_name == 'relationship_staging':
            return 'RelationshipStaging'
        elif table_name == 'processing_metrics':
            return 'ProcessingMetrics'
        
        # Default conversion
        return ''.join(word.capitalize() for word in table_name.split('_'))
    
    def get_table_names(self) -> List[str]:
        """Get all table names from the database."""
        return self.inspector.get_table_names()
    
    def _model_to_code(self, model: Type[BaseModel], table_name: str) -> str:
        """Convert a Pydantic model to Python code."""
        lines = []
        model_name = self._table_to_model_name(table_name)
        
        lines.append(f"class {model_name}(BaseModel):")
        lines.append(f'    """Model for {table_name} table."""')
        
        # Get model fields
        for field_name, field_info in model.__fields__.items():
            # Get field type
            field_type = field_info.annotation
            
            # Format type annotation
            if hasattr(field_type, '__origin__'):
                if field_type.__origin__ is Union:
                    # Handle Optional types
                    args = [arg.__name__ if hasattr(arg, '__name__') else str(arg) 
                            for arg in field_type.__args__ if arg is not type(None)]
                    if len(args) == 1:
                        type_str = f"Optional[{args[0]}]"
                    else:
                        type_str = f"Union[{', '.join(args)}]"
                elif field_type.__origin__ is dict:
                    type_str = "Dict[str, Any]"
                elif field_type.__origin__ is list:
                    type_str = "List[Any]"
                else:
                    type_str = str(field_type)
            else:
                type_str = field_type.__name__ if hasattr(field_type, '__name__') else str(field_type)
            
            # Get default value
            if field_info.default is ...:
                default_str = ""
            elif field_info.default is None:
                default_str = " = None"
            elif isinstance(field_info.default, str):
                default_str = f' = "{field_info.default}"'
            else:
                default_str = f" = {field_info.default}"
            
            # Add field line
            if field_info.alias and field_info.alias != field_name:
                lines.append(f'    {field_name}: {type_str}{default_str} = Field(alias="{field_info.alias}")')
            else:
                lines.append(f'    {field_name}: {type_str}{default_str}')
        
        lines.append("")
        lines.append("    class Config:")
        lines.append("        from_attributes = True")
        lines.append("        populate_by_name = True")
        
        return '\n'.join(lines)