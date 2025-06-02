"""
Simplified RDS utilities - direct database operations without column mapping
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


def insert_record(table_name: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Insert a record into a table - direct insert without mapping"""
    # Filter out null values and auto-incrementing primary keys
    filtered_data = {}
    for key, value in data.items():
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
            INSERT INTO {table_name} ({columns})
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
        logger.error(f"Insert failed for {table_name}: {e}")
        logger.error(f"Filtered data: {filtered_data}")
        raise
    finally:
        db.close()


def update_record(table_name: str, data: Dict[str, Any], where: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Update a record in a table - direct update without mapping"""
    # Serialize dict/list fields to JSON for PostgreSQL
    for key, value in data.items():
        if isinstance(value, (dict, list)):
            data[key] = json.dumps(value)
    
    db = DBSessionLocal()
    try:
        # Build update query
        set_clause = ', '.join([f"{k} = :{k}" for k in data.keys()])
        where_clause = ' AND '.join([f"{k} = :where_{k}" for k in where.keys()])
        
        # Prepare parameters
        params = data.copy()
        for k, v in where.items():
            params[f'where_{k}'] = v
        
        query = text(f"""
            UPDATE {table_name}
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
        logger.error(f"Update failed for {table_name}: {e}")
        raise
    finally:
        db.close()


def select_records(
    table_name: str, 
    where: Optional[Dict[str, Any]] = None,
    limit: Optional[int] = None,
    order_by: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Select records from a table - direct select without mapping"""
    db = DBSessionLocal()
    try:
        # Build select query
        query_str = f"SELECT * FROM {table_name}"
        
        if where:
            where_clause = ' AND '.join([f"{k} = :{k}" for k in where.keys()])
            query_str += f" WHERE {where_clause}"
        
        if order_by:
            query_str += f" ORDER BY {order_by}"
        
        if limit:
            query_str += f" LIMIT {limit}"
        
        logger.debug(f"select_records - query: {query_str}")
        query = text(query_str)
        result = db.execute(query, where or {})
        
        rows = []
        for row in result:
            if hasattr(row, '_mapping'):
                rows.append(dict(row._mapping))
            else:
                rows.append(dict(row))
        
        return rows
        
    except Exception as e:
        logger.error(f"Select failed for {table_name}: {e}")
        raise
    finally:
        db.close()


def delete_records(table_name: str, where: Dict[str, Any]) -> int:
    """Delete records from a table"""
    db = DBSessionLocal()
    try:
        where_clause = ' AND '.join([f"{k} = :{k}" for k in where.keys()])
        query = text(f"""
            DELETE FROM {table_name}
            WHERE {where_clause}
        """)
        
        result = db.execute(query, where)
        count = result.rowcount
        db.commit()
        
        return count
        
    except Exception as e:
        db.rollback()
        logger.error(f"Delete failed for {table_name}: {e}")
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
        tables = ['projects', 'source_documents', 'document_chunks', 'entity_mentions', 'canonical_entities', 'relationship_staging']
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