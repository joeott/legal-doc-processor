"""
Alternative schema reflection using Supabase REST API.
"""

from typing import Dict, List, Any, Optional
import os
from supabase import create_client, Client
from datetime import datetime
import json


class SupabaseSchemaReflector:
    """Reflects schema using Supabase REST API instead of direct database connection."""
    
    def __init__(self):
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
        
        if not url or not key:
            raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set")
            
        self.client: Client = create_client(url, key)
        self._table_cache = {}
    
    def get_table_names(self) -> List[str]:
        """Get all table names from the current schema mapping."""
        # Based on context_203 and actual implementation
        return [
            'projects',
            'documents', 
            'processing_pipeline',
            'processing_queue',
            'document_chunks',
            'entity_mentions',
            'canonical_entities',
            'relationship_staging',
            'processing_metrics',
            'import_sessions'
        ]
    
    def get_table_schema(self, table_name: str) -> Dict[str, Any]:
        """Get schema information for a specific table."""
        # Map of known tables to their schemas based on context_203
        schemas = {
            'projects': {
                'columns': [
                    {'name': 'project_uuid', 'type': 'UUID', 'nullable': False, 'primary': True},
                    {'name': 'project_name', 'type': 'TEXT', 'nullable': False},
                    {'name': 'created_at', 'type': 'TIMESTAMP', 'nullable': False},
                    {'name': 'updated_at', 'type': 'TIMESTAMP', 'nullable': True}
                ]
            },
            'documents': {
                'columns': [
                    {'name': 'document_uuid', 'type': 'UUID', 'nullable': False, 'primary': True},
                    {'name': 'project_uuid', 'type': 'UUID', 'nullable': False},
                    {'name': 'document_name', 'type': 'TEXT', 'nullable': False},
                    {'name': 'document_type', 'type': 'TEXT', 'nullable': True},
                    {'name': 's3_path', 'type': 'TEXT', 'nullable': True},
                    {'name': 'file_size', 'type': 'INTEGER', 'nullable': True},
                    {'name': 'import_session_uuid', 'type': 'UUID', 'nullable': True},
                    {'name': 'processing_status', 'type': 'TEXT', 'nullable': False},
                    {'name': 'celery_task_id', 'type': 'TEXT', 'nullable': True},
                    {'name': 'metadata', 'type': 'JSONB', 'nullable': True},
                    {'name': 'created_at', 'type': 'TIMESTAMP', 'nullable': False},
                    {'name': 'updated_at', 'type': 'TIMESTAMP', 'nullable': True}
                ]
            },
            'import_sessions': {
                'columns': [
                    {'name': 'session_uuid', 'type': 'UUID', 'nullable': False, 'primary': True},
                    {'name': 'project_uuid', 'type': 'UUID', 'nullable': False},
                    {'name': 'session_name', 'type': 'TEXT', 'nullable': False},
                    {'name': 'import_source', 'type': 'TEXT', 'nullable': True},
                    {'name': 'total_files', 'type': 'INTEGER', 'nullable': False},
                    {'name': 'files_uploaded', 'type': 'INTEGER', 'nullable': False, 'default': 0},
                    {'name': 'files_processing', 'type': 'INTEGER', 'nullable': False, 'default': 0},
                    {'name': 'files_completed', 'type': 'INTEGER', 'nullable': False, 'default': 0},
                    {'name': 'files_failed', 'type': 'INTEGER', 'nullable': False, 'default': 0},
                    {'name': 'started_at', 'type': 'TIMESTAMP', 'nullable': False},
                    {'name': 'completed_at', 'type': 'TIMESTAMP', 'nullable': True}
                ]
            },
            'processing_pipeline': {
                'columns': [
                    {'name': 'pipeline_uuid', 'type': 'UUID', 'nullable': False, 'primary': True},
                    {'name': 'document_uuid', 'type': 'UUID', 'nullable': False},
                    {'name': 'stage_name', 'type': 'TEXT', 'nullable': False},
                    {'name': 'stage_status', 'type': 'TEXT', 'nullable': False},
                    {'name': 'error_message', 'type': 'TEXT', 'nullable': True},
                    {'name': 'retry_count', 'type': 'INTEGER', 'nullable': False, 'default': 0},
                    {'name': 'started_at', 'type': 'TIMESTAMP', 'nullable': False},
                    {'name': 'completed_at', 'type': 'TIMESTAMP', 'nullable': True}
                ]
            },
            'processing_queue': {
                'columns': [
                    {'name': 'queue_uuid', 'type': 'UUID', 'nullable': False, 'primary': True},
                    {'name': 'document_uuid', 'type': 'UUID', 'nullable': False},
                    {'name': 'queue_type', 'type': 'TEXT', 'nullable': False},
                    {'name': 'priority', 'type': 'INTEGER', 'nullable': False, 'default': 50},
                    {'name': 'celery_task_id', 'type': 'TEXT', 'nullable': True},
                    {'name': 'enqueued_at', 'type': 'TIMESTAMP', 'nullable': False},
                    {'name': 'processing_started_at', 'type': 'TIMESTAMP', 'nullable': True}
                ]
            },
            'document_chunks': {
                'columns': [
                    {'name': 'chunk_uuid', 'type': 'UUID', 'nullable': False, 'primary': True},
                    {'name': 'document_uuid', 'type': 'UUID', 'nullable': False},
                    {'name': 'chunk_index', 'type': 'INTEGER', 'nullable': False},
                    {'name': 'chunk_text', 'type': 'TEXT', 'nullable': False},
                    {'name': 'chunk_metadata', 'type': 'JSONB', 'nullable': True},
                    {'name': 'embedding', 'type': 'JSONB', 'nullable': True},
                    {'name': 'created_at', 'type': 'TIMESTAMP', 'nullable': False}
                ]
            },
            'entity_mentions': {
                'columns': [
                    {'name': 'mention_uuid', 'type': 'UUID', 'nullable': False, 'primary': True},
                    {'name': 'document_uuid', 'type': 'UUID', 'nullable': False},
                    {'name': 'chunk_uuid', 'type': 'UUID', 'nullable': True},
                    {'name': 'entity_text', 'type': 'TEXT', 'nullable': False},
                    {'name': 'entity_type', 'type': 'TEXT', 'nullable': False},
                    {'name': 'confidence_score', 'type': 'FLOAT', 'nullable': True},
                    {'name': 'context', 'type': 'TEXT', 'nullable': True},
                    {'name': 'canonical_entity_uuid', 'type': 'UUID', 'nullable': True},
                    {'name': 'created_at', 'type': 'TIMESTAMP', 'nullable': False}
                ]
            },
            'canonical_entities': {
                'columns': [
                    {'name': 'entity_uuid', 'type': 'UUID', 'nullable': False, 'primary': True},
                    {'name': 'project_uuid', 'type': 'UUID', 'nullable': False},
                    {'name': 'entity_name', 'type': 'TEXT', 'nullable': False},
                    {'name': 'entity_type', 'type': 'TEXT', 'nullable': False},
                    {'name': 'aliases', 'type': 'JSONB', 'nullable': True},
                    {'name': 'metadata', 'type': 'JSONB', 'nullable': True},
                    {'name': 'embedding', 'type': 'JSONB', 'nullable': True},
                    {'name': 'created_at', 'type': 'TIMESTAMP', 'nullable': False},
                    {'name': 'updated_at', 'type': 'TIMESTAMP', 'nullable': True}
                ]
            },
            'relationship_staging': {
                'columns': [
                    {'name': 'relationship_uuid', 'type': 'UUID', 'nullable': False, 'primary': True},
                    {'name': 'source_entity_uuid', 'type': 'UUID', 'nullable': False},
                    {'name': 'target_entity_uuid', 'type': 'UUID', 'nullable': False},
                    {'name': 'relationship_type', 'type': 'TEXT', 'nullable': False},
                    {'name': 'confidence_score', 'type': 'FLOAT', 'nullable': True},
                    {'name': 'evidence', 'type': 'JSONB', 'nullable': True},
                    {'name': 'status', 'type': 'TEXT', 'nullable': False, 'default': 'pending'},
                    {'name': 'created_at', 'type': 'TIMESTAMP', 'nullable': False}
                ]
            },
            'processing_metrics': {
                'columns': [
                    {'name': 'metric_uuid', 'type': 'UUID', 'nullable': False, 'primary': True},
                    {'name': 'document_uuid', 'type': 'UUID', 'nullable': False},
                    {'name': 'stage_name', 'type': 'TEXT', 'nullable': False},
                    {'name': 'metric_name', 'type': 'TEXT', 'nullable': False},
                    {'name': 'metric_value', 'type': 'JSONB', 'nullable': False},
                    {'name': 'recorded_at', 'type': 'TIMESTAMP', 'nullable': False}
                ]
            }
        }
        
        return schemas.get(table_name, {'columns': []})
    
    def generate_pydantic_code(self, table_name: str) -> str:
        """Generate Pydantic model code for a table."""
        schema = self.get_table_schema(table_name)
        if not schema['columns']:
            return ""
        
        # Convert table name to model name
        model_name = ''.join(word.capitalize() for word in table_name.split('_'))
        
        lines = []
        lines.append(f"class {model_name}(BaseModel):")
        lines.append(f'    """Model for {table_name} table."""')
        
        # Type mapping
        type_map = {
            'UUID': 'str',
            'TEXT': 'str',
            'INTEGER': 'int',
            'FLOAT': 'float',
            'BOOLEAN': 'bool',
            'TIMESTAMP': 'datetime',
            'JSONB': 'Dict[str, Any]',
            'JSON': 'Dict[str, Any]'
        }
        
        for col in schema['columns']:
            py_type = type_map.get(col['type'], 'Any')
            
            if col['nullable']:
                py_type = f"Optional[{py_type}]"
                default = " = None"
            elif col.get('default') is not None:
                default = f" = {col['default']}"
            else:
                default = ""
            
            # Use alias for fields with underscores
            if '_' in col['name']:
                lines.append(f"    {col['name']}: {py_type}{default} = Field(alias='{col['name']}')")
            else:
                lines.append(f"    {col['name']}: {py_type}{default}")
        
        lines.append("")
        lines.append("    class Config:")
        lines.append("        from_attributes = True")
        lines.append("        populate_by_name = True")
        
        return '\n'.join(lines)