"""
Minimal RDS utilities to replace Supabase-specific functions
Direct drop-in replacement maintaining the same interface
"""

import os
import logging
from typing import Dict, List, Optional, Any, Union
from datetime import datetime
import json
import uuid
from pathlib import Path

from sqlalchemy import text, Table, MetaData
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Import global engine and session factory from config
from scripts.config import db_engine, DBSessionLocal

# DATABASE_URL, engine, SessionLocal, and DB_POOL_CONFIG are now sourced from scripts.config
# The engine is db_engine from scripts.config
# SessionLocal is DBSessionLocal from scripts.config

logger = logging.getLogger(__name__)


def test_connection() -> bool:
    """Test database connection"""
    try:
        db = DBSessionLocal()
        result = db.execute(text("SELECT 1"))
        db.close()
        return bool(result.scalar())
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return False


def execute_query(query: str, params: dict = None) -> List[Dict[str, Any]]:
    """Execute a query - direct replacement for supabase.rpc()"""
    db = DBSessionLocal()
    try:
        # Serialize dict/list parameters to JSON
        if params:
            serialized_params = {}
            for key, value in params.items():
                if isinstance(value, (dict, list)):
                    serialized_params[key] = json.dumps(value)
                else:
                    serialized_params[key] = value
            params = serialized_params
            
        result = db.execute(text(query), params or {})
        # Convert rows to dicts
        rows = []
        for row in result:
            if hasattr(row, '_mapping'):
                rows.append(dict(row._mapping))
            else:
                rows.append(dict(row))
        db.commit()
        return rows
    except Exception as e:
        db.rollback()
        logger.error(f"Query execution failed: {e}")
        raise
    finally:
        db.close()


# Import enhanced mappings
try:
    from scripts.enhanced_column_mappings import (
        TABLE_MAPPINGS, COLUMN_MAPPINGS, STATUS_MAPPINGS,
        get_mapped_column, get_mapped_status, should_store_in_metadata
    )
except ImportError:
    # Fallback to basic mappings if enhanced not available
    TABLE_MAPPINGS = {
        "source_documents": "documents",
        "document_chunks": "chunks",
        "entity_mentions": "entities",
        "canonical_entities": "canonical_entities",
        "relationship_staging": "entity_relationships",
        "neo4j_documents": "documents",
        "processing_tasks": "processing_tasks",
        "textract_jobs": "processing_tasks",
    }
    
    COLUMN_MAPPINGS = {
        "documents": {
            "document_uuid": "id",
            "original_file_name": "file_name",
            "detected_file_type": "mime_type",
            "project_uuid": "project_id",
            "s3_key": "file_path",
            "file_size_bytes": "file_size",
            "celery_status": "status",
            "processing_status": "status",
            "error_message": "error_message",
        },
        "chunks": {
            "chunk_id": "id",
            "chunk_uuid": "id",
            "document_uuid": "document_id",
            "text": "content",
            "text_content": "content",
        },
        "entities": {
            "entity_mention_uuid": "id",
            "value": "name",
            "text": "name",
            "entity_type": "entity_type",
            "confidence": "confidence_score",
        },
    }
    
    def get_mapped_status(status):
        if "failed" in status or status == "error":
            return "failed"
        elif status == "completed":
            return "completed"
        elif status in ["pending", "pending_intake"]:
            return "pending"
        else:
            return "processing"

def map_table_name(table: str) -> str:
    """Map expected table name to actual simplified schema table."""
    return TABLE_MAPPINGS.get(table, table)

def map_columns(table: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Map column names to simplified schema."""
    actual_table = map_table_name(table)
    mappings = COLUMN_MAPPINGS.get(actual_table, {})
    
    if not mappings:
        return data
        
    mapped = {}
    metadata_fields = {}  # Collect fields that should go into metadata
    processing_metadata_fields = {}  # Fields for processing_metadata
    ocr_metadata_fields = {}  # Fields for ocr_metadata_json
    transcription_metadata_fields = {}  # Fields for transcription_metadata_json
    
    for key, value in data.items():
        mapped_key = mappings.get(key)
        
        if mapped_key == "metadata":
            # This field should be stored in metadata JSON
            metadata_fields[key] = value
        elif mapped_key == "processing_metadata":
            # This field should be stored in processing_metadata JSON
            processing_metadata_fields[key] = value
        elif mapped_key == "ocr_metadata_json":
            # This field should be stored in ocr_metadata_json
            ocr_metadata_fields[key] = value
        elif mapped_key == "transcription_metadata_json":
            # This field should be stored in transcription_metadata_json
            transcription_metadata_fields[key] = value
        elif mapped_key == "status":
            # Handle status mapping
            if hasattr(value, '__class__') and hasattr(value, 'value'):
                # Handle enum
                value = value.value
            mapped[mapped_key] = get_mapped_status(str(value)) if 'get_mapped_status' in globals() else value
        elif mapped_key:
            # Direct mapping
            mapped[mapped_key] = value
            
            # Special case: if we're mapping original_filename, also populate filename
            if mapped_key == "original_filename" and actual_table == "source_documents":
                mapped["filename"] = value
        elif key in ["created_at", "updated_at", "id"]:
            # Keep these common fields
            mapped[key] = value
    
    # Add collected metadata fields
    if metadata_fields:
        existing_metadata = mapped.get('metadata', {})
        if isinstance(existing_metadata, str):
            try:
                existing_metadata = json.loads(existing_metadata)
            except:
                existing_metadata = {}
        existing_metadata.update(metadata_fields)
        mapped['metadata'] = existing_metadata
        
    if processing_metadata_fields:
        existing_metadata = mapped.get('processing_metadata', {})
        if isinstance(existing_metadata, str):
            try:
                existing_metadata = json.loads(existing_metadata)
            except:
                existing_metadata = {}
        existing_metadata.update(processing_metadata_fields)
        mapped['processing_metadata'] = existing_metadata

    if ocr_metadata_fields:
        existing_metadata = mapped.get('ocr_metadata_json', {})
        if isinstance(existing_metadata, str):
            try:
                existing_metadata = json.loads(existing_metadata)
            except:
                existing_metadata = {}
        existing_metadata.update(ocr_metadata_fields)
        mapped['ocr_metadata_json'] = existing_metadata

    if transcription_metadata_fields:
        existing_metadata = mapped.get('transcription_metadata_json', {})
        if isinstance(existing_metadata, str):
            try:
                existing_metadata = json.loads(existing_metadata)
            except:
                existing_metadata = {}
        existing_metadata.update(transcription_metadata_fields)
        mapped['transcription_metadata_json'] = existing_metadata
            
    return mapped

def insert_record(table_name: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Insert a record into a table"""
    # Map table and columns
    actual_table = map_table_name(table_name)
    mapped_data = map_columns(table_name, data)
    
    # Filter out null values and auto-incrementing primary keys
    filtered_data = {}
    for key, value in mapped_data.items():
        # Skip null values and primary key columns that should auto-increment
        if value is not None and key != 'id':
            if isinstance(value, (dict, list)):
                filtered_data[key] = json.dumps(value)
            else:
                filtered_data[key] = value
    
    db = DBSessionLocal()
    try:
        # Build insert query with filtered data
        columns = ', '.join(filtered_data.keys())
        placeholders = ', '.join([f':{k}' for k in filtered_data.keys()])
        query = text(f"""
            INSERT INTO {actual_table} ({columns})
            VALUES ({placeholders})
            RETURNING *
        """)
        
        result = db.execute(query, filtered_data)
        row = result.fetchone()
        db.commit()
        
        if row:
            return dict(row._mapping) if hasattr(row, '_mapping') else dict(row)
        return None
        
    except Exception as e:
        db.rollback()
        logger.error(f"Insert failed for {actual_table}: {e}")
        logger.error(f"Filtered data: {filtered_data}")
        raise
    finally:
        db.close()


def update_record(table_name: str, data: Dict[str, Any], where: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Update a record in a table"""
    # Map table and columns
    actual_table = map_table_name(table_name)
    mapped_data = map_columns(table_name, data)
    mapped_where = map_columns(table_name, where)
    
    # Serialize dict/list fields to JSON for PostgreSQL
    for key, value in mapped_data.items():
        if isinstance(value, (dict, list)):
            mapped_data[key] = json.dumps(value)
    
    db = DBSessionLocal()
    try:
        # Build update query
        set_clause = ', '.join([f"{k} = :{k}" for k in mapped_data.keys()])
        where_clause = ' AND '.join([f"{k} = :where_{k}" for k in mapped_where.keys()])
        
        # Prepare parameters
        params = mapped_data.copy()
        for k, v in mapped_where.items():
            params[f'where_{k}'] = v
        
        query = text(f"""
            UPDATE {actual_table}
            SET {set_clause}
            WHERE {where_clause}
            RETURNING *
        """)
        
        result = db.execute(query, params)
        row = result.fetchone()
        db.commit()
        
        if row:
            return dict(row._mapping) if hasattr(row, '_mapping') else dict(row)
        return None
        
    except Exception as e:
        db.rollback()
        logger.error(f"Update failed for {actual_table}: {e}")
        raise
    finally:
        db.close()


def select_records(
    table_name: str, 
    where: Optional[Dict[str, Any]] = None,
    limit: Optional[int] = None,
    order_by: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Select records from a table"""
    # Map table and columns
    actual_table = map_table_name(table_name)
    mapped_where = map_columns(table_name, where) if where else None
    
    db = DBSessionLocal()
    try:
        # Build select query
        query_str = f"SELECT * FROM {actual_table}"
        
        if mapped_where:
            where_clause = ' AND '.join([f"{k} = :{k}" for k in mapped_where.keys()])
            query_str += f" WHERE {where_clause}"
        
        if order_by:
            # Map order_by column if needed
            mappings = COLUMN_MAPPINGS.get(actual_table, {})
            mapped_order = mappings.get(order_by, order_by)
            query_str += f" ORDER BY {mapped_order}"
        
        if limit:
            query_str += f" LIMIT {limit}"
        
        query = text(query_str)
        result = db.execute(query, mapped_where or {})
        
        rows = []
        for row in result:
            if hasattr(row, '_mapping'):
                rows.append(dict(row._mapping))
            else:
                rows.append(dict(row))
        
        return rows
        
    except Exception as e:
        logger.error(f"Select failed for {actual_table}: {e}")
        raise
    finally:
        db.close()


def delete_records(table_name: str, where: Dict[str, Any]) -> int:
    """Delete records from a table"""
    # Map table and columns
    actual_table = map_table_name(table_name)
    mapped_where = map_columns(table_name, where)
    
    db = DBSessionLocal()
    try:
        where_clause = ' AND '.join([f"{k} = :{k}" for k in mapped_where.keys()])
        query = text(f"""
            DELETE FROM {actual_table}
            WHERE {where_clause}
        """)
        
        result = db.execute(query, mapped_where)
        count = result.rowcount
        db.commit()
        
        return count
        
    except Exception as e:
        db.rollback()
        logger.error(f"Delete failed for {actual_table}: {e}")
        raise
    finally:
        db.close()


# Storage compatibility functions (for S3 URL generation)
def generate_document_url(file_path: str, use_signed_url: bool = True) -> str:
    """
    Generate a URL for a document.
    For S3 paths, generates presigned URLs.
    """
    # Check if file_path is already a URL
    if file_path.startswith("http://") or file_path.startswith("https://"):
        return file_path
    
    # Handle S3 paths
    if file_path.startswith('s3://'):
        from s3_storage import S3StorageManager
        s3_manager = S3StorageManager()
        
        # Extract bucket and key from s3://bucket/key format
        parts = file_path.replace('s3://', '').split('/', 1)
        bucket = parts[0]
        key = parts[1] if len(parts) > 1 else ""
        
        return s3_manager.generate_presigned_url_for_ocr(key, bucket)
    
    # For local paths, just return as is
    return file_path


# Batch operations for efficiency
def batch_insert(table_name: str, records: List[Dict[str, Any]]) -> int:
    """Insert multiple records efficiently"""
    if not records:
        return 0
    
    db = DBSessionLocal()
    try:
        # Use executemany for efficiency
        columns = list(records[0].keys())
        columns_str = ', '.join(columns)
        placeholders = ', '.join([f':{col}' for col in columns])
        
        query = text(f"""
            INSERT INTO {table_name} ({columns_str})
            VALUES ({placeholders})
        """)
        
        db.execute(query, records)
        db.commit()
        
        return len(records)
        
    except Exception as e:
        db.rollback()
        logger.error(f"Batch insert failed for {table_name}: {e}")
        raise
    finally:
        db.close()


# Health check
def health_check() -> Dict[str, Any]:
    """Check database health and return stats"""
    db = DBSessionLocal()
    try:
        # Check connection
        result = db.execute(text("SELECT version()"))
        version = result.scalar()
        
        # Get basic stats
        stats = {
            "status": "healthy",
            "version": version,
            "tables": {}
        }
        
        # Get row counts for main tables
        tables = ['projects', 'documents', 'chunks', 'entities', 'relationships']
        for table in tables:
            try:
                result = db.execute(text(f"SELECT COUNT(*) FROM {table}"))
                stats["tables"][table] = result.scalar()
            except:
                stats["tables"][table] = "error"
        
        return stats
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e)
        }
    finally:
        db.close()


# Utility function to check if table exists
def table_exists(table_name: str) -> bool:
    """Check if a table exists in the database"""
    db = DBSessionLocal()
    try:
        query = text("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = :table_name
            )
        """)
        result = db.execute(query, {"table_name": table_name})
        return result.scalar()
    except Exception as e:
        logger.error(f"Error checking table existence: {e}")
        return False
    finally:
        db.close()


# Export all functions that might be imported elsewhere
__all__ = [
    'test_connection',
    'execute_query',
    'insert_record',
    'update_record', 
    'select_records',
    'delete_records',
    'generate_document_url',
    'batch_insert',
    'health_check',
    'table_exists'
]