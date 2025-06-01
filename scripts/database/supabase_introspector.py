"""
Supabase REST API-based schema introspection for conformance checking.
"""

import os
import json
from typing import Dict, List, Any, Optional, Type
from datetime import datetime
from decimal import Decimal
import httpx
from supabase import create_client, Client
from pydantic import BaseModel, Field, create_model
import logging

logger = logging.getLogger(__name__)


class SupabaseIntrospector:
    """Introspects Supabase schema using REST API and known schema definitions."""
    
    # Known table structures based on context_203
    KNOWN_SCHEMA = {
        'projects': {
            'columns': [
                {'column_name': 'project_uuid', 'data_type': 'uuid', 'is_nullable': 'NO', 'is_primary': True},
                {'column_name': 'project_name', 'data_type': 'text', 'is_nullable': 'NO'},
                {'column_name': 'created_at', 'data_type': 'timestamp with time zone', 'is_nullable': 'NO'},
                {'column_name': 'updated_at', 'data_type': 'timestamp with time zone', 'is_nullable': 'YES'}
            ]
        },
        'documents': {
            'columns': [
                {'column_name': 'document_uuid', 'data_type': 'uuid', 'is_nullable': 'NO', 'is_primary': True},
                {'column_name': 'project_uuid', 'data_type': 'uuid', 'is_nullable': 'NO'},
                {'column_name': 'document_name', 'data_type': 'text', 'is_nullable': 'NO'},
                {'column_name': 'document_type', 'data_type': 'text', 'is_nullable': 'YES'},
                {'column_name': 's3_path', 'data_type': 'text', 'is_nullable': 'YES'},
                {'column_name': 'file_size', 'data_type': 'integer', 'is_nullable': 'YES'},
                {'column_name': 'import_session_uuid', 'data_type': 'uuid', 'is_nullable': 'YES'},
                {'column_name': 'processing_status', 'data_type': 'text', 'is_nullable': 'NO'},
                {'column_name': 'celery_task_id', 'data_type': 'text', 'is_nullable': 'YES'},
                {'column_name': 'metadata', 'data_type': 'jsonb', 'is_nullable': 'YES'},
                {'column_name': 'created_at', 'data_type': 'timestamp with time zone', 'is_nullable': 'NO'},
                {'column_name': 'updated_at', 'data_type': 'timestamp with time zone', 'is_nullable': 'YES'}
            ]
        },
        'import_sessions': {
            'columns': [
                {'column_name': 'session_uuid', 'data_type': 'uuid', 'is_nullable': 'NO', 'is_primary': True},
                {'column_name': 'project_uuid', 'data_type': 'uuid', 'is_nullable': 'NO'},
                {'column_name': 'session_name', 'data_type': 'text', 'is_nullable': 'NO'},
                {'column_name': 'import_source', 'data_type': 'text', 'is_nullable': 'YES'},
                {'column_name': 'total_files', 'data_type': 'integer', 'is_nullable': 'NO'},
                {'column_name': 'files_uploaded', 'data_type': 'integer', 'is_nullable': 'NO', 'column_default': '0'},
                {'column_name': 'files_processing', 'data_type': 'integer', 'is_nullable': 'NO', 'column_default': '0'},
                {'column_name': 'files_completed', 'data_type': 'integer', 'is_nullable': 'NO', 'column_default': '0'},
                {'column_name': 'files_failed', 'data_type': 'integer', 'is_nullable': 'NO', 'column_default': '0'},
                {'column_name': 'started_at', 'data_type': 'timestamp with time zone', 'is_nullable': 'NO'},
                {'column_name': 'completed_at', 'data_type': 'timestamp with time zone', 'is_nullable': 'YES'}
            ]
        },
        'processing_pipeline': {
            'columns': [
                {'column_name': 'pipeline_uuid', 'data_type': 'uuid', 'is_nullable': 'NO', 'is_primary': True},
                {'column_name': 'document_uuid', 'data_type': 'uuid', 'is_nullable': 'NO'},
                {'column_name': 'stage_name', 'data_type': 'text', 'is_nullable': 'NO'},
                {'column_name': 'stage_status', 'data_type': 'text', 'is_nullable': 'NO'},
                {'column_name': 'error_message', 'data_type': 'text', 'is_nullable': 'YES'},
                {'column_name': 'retry_count', 'data_type': 'integer', 'is_nullable': 'NO', 'column_default': '0'},
                {'column_name': 'started_at', 'data_type': 'timestamp with time zone', 'is_nullable': 'NO'},
                {'column_name': 'completed_at', 'data_type': 'timestamp with time zone', 'is_nullable': 'YES'}
            ]
        },
        'processing_queue': {
            'columns': [
                {'column_name': 'queue_uuid', 'data_type': 'uuid', 'is_nullable': 'NO', 'is_primary': True},
                {'column_name': 'document_uuid', 'data_type': 'uuid', 'is_nullable': 'NO'},
                {'column_name': 'queue_type', 'data_type': 'text', 'is_nullable': 'NO'},
                {'column_name': 'priority', 'data_type': 'integer', 'is_nullable': 'NO', 'column_default': '50'},
                {'column_name': 'celery_task_id', 'data_type': 'text', 'is_nullable': 'YES'},
                {'column_name': 'enqueued_at', 'data_type': 'timestamp with time zone', 'is_nullable': 'NO'},
                {'column_name': 'processing_started_at', 'data_type': 'timestamp with time zone', 'is_nullable': 'YES'}
            ]
        },
        'document_chunks': {
            'columns': [
                {'column_name': 'chunk_uuid', 'data_type': 'uuid', 'is_nullable': 'NO', 'is_primary': True},
                {'column_name': 'document_uuid', 'data_type': 'uuid', 'is_nullable': 'NO'},
                {'column_name': 'chunk_index', 'data_type': 'integer', 'is_nullable': 'NO'},
                {'column_name': 'chunk_text', 'data_type': 'text', 'is_nullable': 'NO'},
                {'column_name': 'chunk_metadata', 'data_type': 'jsonb', 'is_nullable': 'YES'},
                {'column_name': 'embedding', 'data_type': 'jsonb', 'is_nullable': 'YES'},
                {'column_name': 'created_at', 'data_type': 'timestamp with time zone', 'is_nullable': 'NO'}
            ]
        },
        'entity_mentions': {
            'columns': [
                {'column_name': 'mention_uuid', 'data_type': 'uuid', 'is_nullable': 'NO', 'is_primary': True},
                {'column_name': 'document_uuid', 'data_type': 'uuid', 'is_nullable': 'NO'},
                {'column_name': 'chunk_uuid', 'data_type': 'uuid', 'is_nullable': 'YES'},
                {'column_name': 'entity_text', 'data_type': 'text', 'is_nullable': 'NO'},
                {'column_name': 'entity_type', 'data_type': 'text', 'is_nullable': 'NO'},
                {'column_name': 'confidence_score', 'data_type': 'real', 'is_nullable': 'YES'},
                {'column_name': 'context', 'data_type': 'text', 'is_nullable': 'YES'},
                {'column_name': 'canonical_entity_uuid', 'data_type': 'uuid', 'is_nullable': 'YES'},
                {'column_name': 'created_at', 'data_type': 'timestamp with time zone', 'is_nullable': 'NO'}
            ]
        },
        'canonical_entities': {
            'columns': [
                {'column_name': 'entity_uuid', 'data_type': 'uuid', 'is_nullable': 'NO', 'is_primary': True},
                {'column_name': 'project_uuid', 'data_type': 'uuid', 'is_nullable': 'NO'},
                {'column_name': 'entity_name', 'data_type': 'text', 'is_nullable': 'NO'},
                {'column_name': 'entity_type', 'data_type': 'text', 'is_nullable': 'NO'},
                {'column_name': 'aliases', 'data_type': 'jsonb', 'is_nullable': 'YES'},
                {'column_name': 'metadata', 'data_type': 'jsonb', 'is_nullable': 'YES'},
                {'column_name': 'embedding', 'data_type': 'jsonb', 'is_nullable': 'YES'},
                {'column_name': 'created_at', 'data_type': 'timestamp with time zone', 'is_nullable': 'NO'},
                {'column_name': 'updated_at', 'data_type': 'timestamp with time zone', 'is_nullable': 'YES'}
            ]
        },
        'relationship_staging': {
            'columns': [
                {'column_name': 'relationship_uuid', 'data_type': 'uuid', 'is_nullable': 'NO', 'is_primary': True},
                {'column_name': 'source_entity_uuid', 'data_type': 'uuid', 'is_nullable': 'NO'},
                {'column_name': 'target_entity_uuid', 'data_type': 'uuid', 'is_nullable': 'NO'},
                {'column_name': 'relationship_type', 'data_type': 'text', 'is_nullable': 'NO'},
                {'column_name': 'confidence_score', 'data_type': 'real', 'is_nullable': 'YES'},
                {'column_name': 'evidence', 'data_type': 'jsonb', 'is_nullable': 'YES'},
                {'column_name': 'status', 'data_type': 'text', 'is_nullable': 'NO', 'column_default': "'pending'"},
                {'column_name': 'created_at', 'data_type': 'timestamp with time zone', 'is_nullable': 'NO'}
            ]
        },
        'processing_metrics': {
            'columns': [
                {'column_name': 'metric_uuid', 'data_type': 'uuid', 'is_nullable': 'NO', 'is_primary': True},
                {'column_name': 'document_uuid', 'data_type': 'uuid', 'is_nullable': 'NO'},
                {'column_name': 'stage_name', 'data_type': 'text', 'is_nullable': 'NO'},
                {'column_name': 'metric_name', 'data_type': 'text', 'is_nullable': 'NO'},
                {'column_name': 'metric_value', 'data_type': 'jsonb', 'is_nullable': 'NO'},
                {'column_name': 'recorded_at', 'data_type': 'timestamp with time zone', 'is_nullable': 'NO'}
            ]
        }
    }
    
    def __init__(self):
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
        
        if not url or not key:
            raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set")
            
        self.client: Client = create_client(url, key)
        self.url = url
        self._type_mapping = self._initialize_type_mapping()
    
    def _initialize_type_mapping(self) -> Dict[str, Type]:
        """Initialize PostgreSQL to Python type mapping."""
        return {
            'uuid': str,
            'text': str,
            'character varying': str,
            'varchar': str,
            'char': str,
            'integer': int,
            'bigint': int,
            'smallint': int,
            'boolean': bool,
            'bool': bool,
            'timestamp with time zone': datetime,
            'timestamp without time zone': datetime,
            'timestamptz': datetime,
            'timestamp': datetime,
            'date': datetime,
            'time': datetime,
            'jsonb': Dict[str, Any],
            'json': Dict[str, Any],
            'numeric': Decimal,
            'decimal': Decimal,
            'real': float,
            'double precision': float,
            'float': float
        }
    
    def get_table_names(self) -> List[str]:
        """Get list of all table names."""
        return list(self.KNOWN_SCHEMA.keys())
    
    def get_columns(self, table_name: str) -> List[Dict[str, Any]]:
        """Get column information for a specific table."""
        if table_name not in self.KNOWN_SCHEMA:
            # Try to query the table to see if it exists
            try:
                result = self.client.table(table_name).select('*').limit(0).execute()
                # If successful, return empty columns (table exists but schema unknown)
                return []
            except Exception:
                raise ValueError(f"Table '{table_name}' not found")
        
        return self.KNOWN_SCHEMA[table_name]['columns']
    
    def reflect_table(self, table_name: str) -> Dict[str, Any]:
        """Get complete table information including columns, keys, and constraints."""
        columns = self.get_columns(table_name)
        
        # Extract primary key columns
        pk_columns = [col['column_name'] for col in columns if col.get('is_primary')]
        
        # Extract foreign keys (would need to be added to KNOWN_SCHEMA)
        foreign_keys = []
        
        # Extract indexes (would need to be added to KNOWN_SCHEMA)
        indexes = []
        
        return {
            'name': table_name,
            'columns': columns,
            'primary_key': {
                'constrained_columns': pk_columns,
                'name': f'{table_name}_pkey' if pk_columns else None
            },
            'foreign_keys': foreign_keys,
            'indexes': indexes,
            'unique_constraints': []
        }
    
    def generate_pydantic_model(self, table_name: str) -> Type[BaseModel]:
        """Generate a Pydantic model from table information."""
        table_info = self.reflect_table(table_name)
        
        # Build field definitions
        fields = {}
        for column in table_info['columns']:
            field_type = self._get_python_type(column['data_type'])
            field_default = ... if column['is_nullable'] == 'NO' else None
            
            # Handle defaults
            if column.get('column_default'):
                default_str = str(column['column_default'])
                if 'nextval' in default_str:
                    field_default = None  # Auto-increment
                elif default_str in ('now()', 'CURRENT_TIMESTAMP'):
                    field_default = None  # Database will set
                elif default_str.startswith("'") and default_str.endswith("'"):
                    field_default = default_str[1:-1]  # String literal
                elif default_str.isdigit():
                    field_default = int(default_str)
            
            # Create field with proper annotation
            if column['is_nullable'] == 'YES':
                field_type = Optional[field_type]
            
            fields[column['column_name']] = (
                field_type,
                Field(
                    default=field_default,
                    description=f"{column['data_type']} column",
                    alias=column['column_name']
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
    
    def _get_python_type(self, sql_type: str) -> Type:
        """Convert PostgreSQL type to Python type."""
        sql_type_lower = sql_type.lower()
        
        # Direct match
        if sql_type_lower in self._type_mapping:
            return self._type_mapping[sql_type_lower]
        
        # Partial match
        for pg_type, py_type in self._type_mapping.items():
            if pg_type in sql_type_lower:
                return py_type
        
        # Default to Any for unknown types
        logger.warning(f"Unknown PostgreSQL type: {sql_type}, defaulting to Any")
        return Any
    
    def _table_to_model_name(self, table_name: str) -> str:
        """Convert table_name to ModelName."""
        # Handle special cases
        special_cases = {
            'import_sessions': 'ImportSession',
            'processing_pipeline': 'ProcessingPipeline',
            'processing_queue': 'ProcessingQueue',
            'document_chunks': 'DocumentChunk',
            'entity_mentions': 'EntityMention',
            'canonical_entities': 'CanonicalEntity',
            'relationship_staging': 'RelationshipStaging',
            'processing_metrics': 'ProcessingMetrics'
        }
        
        if table_name in special_cases:
            return special_cases[table_name]
        
        # Default conversion
        return ''.join(word.capitalize() for word in table_name.split('_'))
    
    def test_connection(self) -> bool:
        """Test if Supabase connection is working."""
        try:
            # Try to query any table with limit 0
            result = self.client.table('projects').select('*').limit(0).execute()
            return True
        except Exception as e:
            logger.error(f"Supabase connection test failed: {e}")
            return False
    
    def _model_to_code(self, model: Type[BaseModel], table_name: str) -> str:
        """Convert a Pydantic model to Python code string."""
        lines = []
        model_name = self._table_to_model_name(table_name)
        
        lines.append(f"class {model_name}(BaseModel):")
        lines.append(f'    """Model for {table_name} table."""')
        
        # Get model fields using model_fields for Pydantic v2
        model_fields = model.model_fields if hasattr(model, 'model_fields') else model.__fields__
        
        for field_name, field_info in model_fields.items():
            # Get field type
            field_type = field_info.annotation
            
            # Format type annotation
            type_str = self._format_type_annotation(field_type)
            
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
            if hasattr(field_info, 'alias') and field_info.alias and field_info.alias != field_name:
                lines.append(f'    {field_name}: {type_str}{default_str} = Field(alias="{field_info.alias}")')
            else:
                lines.append(f'    {field_name}: {type_str}{default_str}')
        
        lines.append("")
        lines.append("    class Config:")
        lines.append("        from_attributes = True")
        lines.append("        populate_by_name = True")
        
        return '\n'.join(lines)
    
    def _format_type_annotation(self, field_type: Any) -> str:
        """Format a type annotation for code generation."""
        if hasattr(field_type, '__origin__'):
            origin = field_type.__origin__
            args = field_type.__args__
            
            if origin is Union:
                # Handle Optional types
                non_none_args = [arg for arg in args if arg is not type(None)]
                if len(non_none_args) == 1 and type(None) in args:
                    return f"Optional[{self._format_type_annotation(non_none_args[0])}]"
                else:
                    arg_strs = [self._format_type_annotation(arg) for arg in args]
                    return f"Union[{', '.join(arg_strs)}]"
            elif origin is dict:
                if len(args) == 2:
                    return f"Dict[{self._format_type_annotation(args[0])}, {self._format_type_annotation(args[1])}]"
                return "Dict[str, Any]"
            elif origin is list:
                if args:
                    return f"List[{self._format_type_annotation(args[0])}]"
                return "List[Any]"
            else:
                return str(field_type)
        else:
            # Simple types
            if hasattr(field_type, '__name__'):
                return field_type.__name__
            return str(field_type)