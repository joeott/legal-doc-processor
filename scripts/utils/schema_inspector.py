#!/usr/bin/env python3
"""
schema_inspector.py
Comprehensive export of RDS schema, Redis keys, and Pydantic models for legal-doc-processor.

This utility creates a complete snapshot of the system's data architecture including:
- PostgreSQL database schema (tables, triggers, functions, etc.) as JSON
- Redis cache keys and patterns as JSON  
- Pydantic model definitions as JSON
- Comprehensive analysis report as Markdown

Usage:
------
# Basic usage (outputs to stdout)
python scripts/utils/schema_inspector.py

# Full export to timestamped directory (creates organized reports)
python scripts/utils/schema_inspector.py -o export_name

# With validation and row counts
python scripts/utils/schema_inspector.py -o complete_export --validate --include-counts -v

# Custom database
python scripts/utils/schema_inspector.py --uri "postgresql://user:pass@host:5432/db" -o custom_export

Output Directory Structure:
/opt/legal-doc-processor/monitoring/reports/YYYY-MM-DD_HH-MM-SS_UTC/
├── {base_name}_database_schema.json   - Complete PostgreSQL schema
├── {base_name}_redis_keys.json        - Redis keys and patterns  
├── {base_name}_pydantic_models.json   - Model definitions and schemas
└── {base_name}_analysis_report.md     - Human-readable comprehensive analysis
"""

import argparse
import json
import os
import sys
import logging
from datetime import datetime
from collections import defaultdict
from pathlib import Path
import inspect as python_inspect
import redis

# Set up path for our modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import SQLAlchemyError


def setup_logging(verbose: bool = False) -> logging.Logger:
    """Set up logging for the schema inspector."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(levelname)s:%(name)s:%(message)s'
    )
    return logging.getLogger(__name__)


def get_database_url() -> str:
    """Get database URL from environment with fallback options."""
    # Try different environment variable names used in our system
    for var_name in ['DATABASE_URL', 'DATABASE_URL_DIRECT', 'DB_URI']:
        url = os.getenv(var_name)
        if url:
            return url
    
    raise ValueError(
        "No database URL found. Set DATABASE_URL, DATABASE_URL_DIRECT, or DB_URI environment variable, "
        "or provide --uri argument"
    )


def get_table_row_count(engine, table_name: str) -> int:
    """Get approximate row count for a table."""
    try:
        with engine.connect() as conn:
            result = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
            return result.scalar()
    except SQLAlchemyError as e:
        logging.warning(f"Could not get row count for {table_name}: {e}")
        return -1


def get_database_functions(engine) -> list:
    """Get all user-defined functions and stored procedures."""
    try:
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT 
                    routine_name,
                    routine_type,
                    routine_definition,
                    external_language,
                    is_deterministic,
                    data_type,
                    routine_schema
                FROM information_schema.routines 
                WHERE routine_schema NOT IN ('information_schema', 'pg_catalog')
                ORDER BY routine_name
            """))
            return [dict(row._mapping) for row in result.fetchall()]
    except Exception as e:
        logging.warning(f"Could not get database functions: {e}")
        return []


def get_database_triggers(engine) -> list:
    """Get all database triggers."""
    try:
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT 
                    t.trigger_name,
                    t.event_manipulation,
                    t.event_object_table,
                    t.action_timing,
                    t.action_statement,
                    t.action_orientation,
                    t.action_condition,
                    t.trigger_schema
                FROM information_schema.triggers t
                WHERE t.trigger_schema NOT IN ('information_schema', 'pg_catalog')
                ORDER BY t.event_object_table, t.trigger_name
            """))
            return [dict(row._mapping) for row in result.fetchall()]
    except Exception as e:
        logging.warning(f"Could not get database triggers: {e}")
        return []


def get_database_sequences(engine) -> list:
    """Get all database sequences."""
    try:
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT 
                    sequence_name,
                    sequence_schema,
                    data_type,
                    start_value,
                    minimum_value,
                    maximum_value,
                    increment,
                    cycle_option
                FROM information_schema.sequences
                WHERE sequence_schema NOT IN ('information_schema', 'pg_catalog')
                ORDER BY sequence_name
            """))
            return [dict(row._mapping) for row in result.fetchall()]
    except Exception as e:
        logging.warning(f"Could not get database sequences: {e}")
        return []


def get_database_views(engine) -> list:
    """Get all database views."""
    try:
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT 
                    table_name as view_name,
                    view_definition,
                    check_option,
                    is_updatable,
                    table_schema as view_schema
                FROM information_schema.views
                WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
                ORDER BY table_name
            """))
            return [dict(row._mapping) for row in result.fetchall()]
    except Exception as e:
        logging.warning(f"Could not get database views: {e}")
        return []


def get_database_schemas(engine) -> list:
    """Get all database schemas."""
    try:
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT 
                    schema_name,
                    schema_owner
                FROM information_schema.schemata
                WHERE schema_name NOT IN ('information_schema', 'pg_catalog', 'pg_toast')
                ORDER BY schema_name
            """))
            return [dict(row._mapping) for row in result.fetchall()]
    except Exception as e:
        logging.warning(f"Could not get database schemas: {e}")
        return []


def get_database_extensions(engine) -> list:
    """Get installed PostgreSQL extensions."""
    try:
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT 
                    extname as extension_name,
                    extversion as version,
                    nspname as schema_name
                FROM pg_extension e
                JOIN pg_namespace n ON e.extnamespace = n.oid
                ORDER BY extname
            """))
            return [dict(row._mapping) for row in result.fetchall()]
    except Exception as e:
        logging.warning(f"Could not get database extensions: {e}")
        return []


def export_redis_keys() -> dict:
    """Export Redis keys and basic information."""
    redis_data = {
        "metadata": {
            "exported_at": datetime.utcnow().isoformat() + "Z",
            "connection_status": "unknown"
        },
        "keys": [],
        "summary": {
            "total_keys": 0,
            "key_patterns": {},
            "memory_usage": 0
        },
        "errors": []
    }
    
    try:
        # Get Redis connection info from environment
        redis_host = os.getenv('REDIS_HOST') or os.getenv('REDIS_PUBLIC_ENDPOINT', '').split(':')[0]
        redis_port = int(os.getenv('REDIS_PORT', '6379'))
        redis_password = os.getenv('REDIS_PASSWORD') or os.getenv('REDIS_PW', '')
        
        if not redis_host:
            redis_data["errors"].append("No Redis host found in environment")
            return redis_data
            
        # Create Redis connection
        r = redis.Redis(
            host=redis_host,
            port=redis_port,
            password=redis_password,
            decode_responses=True,
            socket_timeout=5
        )
        
        # Test connection
        r.ping()
        redis_data["metadata"]["connection_status"] = "connected"
        redis_data["metadata"]["redis_host"] = f"{redis_host}:{redis_port}"
        
        # Get all keys
        all_keys = r.keys('*')
        redis_data["summary"]["total_keys"] = len(all_keys)
        
        # Analyze key patterns
        patterns = defaultdict(int)
        for key in all_keys:
            # Extract pattern (first part before colon)
            pattern = key.split(':')[0] if ':' in key else 'no_pattern'
            patterns[pattern] += 1
            
            # Get key info
            key_type = r.type(key)
            try:
                ttl = r.ttl(key)
                size = r.memory_usage(key) if hasattr(r, 'memory_usage') else 0
            except:
                ttl = -1
                size = 0
                
            key_info = {
                "key": key,
                "type": key_type,
                "ttl": ttl,
                "size_bytes": size
            }
            
            # Get sample of value based on type
            try:
                if key_type == 'string':
                    value = r.get(key)
                    key_info["sample_value"] = value[:100] + "..." if len(str(value)) > 100 else str(value)
                elif key_type == 'hash':
                    hash_keys = r.hkeys(key)
                    key_info["hash_fields"] = len(hash_keys)
                    key_info["sample_fields"] = hash_keys[:5]
                elif key_type == 'list':
                    list_len = r.llen(key)
                    key_info["list_length"] = list_len
                    if list_len > 0:
                        key_info["sample_value"] = r.lrange(key, 0, 2)
                elif key_type == 'set':
                    set_size = r.scard(key)
                    key_info["set_size"] = set_size
                    if set_size > 0:
                        key_info["sample_members"] = list(r.sscan(key, count=3)[1])
                elif key_type == 'zset':
                    zset_size = r.zcard(key)
                    key_info["zset_size"] = zset_size
                    if zset_size > 0:
                        key_info["sample_members"] = r.zrange(key, 0, 2, withscores=True)
            except Exception as e:
                key_info["value_error"] = str(e)
                
            redis_data["keys"].append(key_info)
        
        redis_data["summary"]["key_patterns"] = dict(patterns)
        redis_data["summary"]["memory_usage"] = sum(k.get("size_bytes", 0) for k in redis_data["keys"])
        
    except redis.ConnectionError as e:
        redis_data["errors"].append(f"Redis connection failed: {str(e)}")
        redis_data["metadata"]["connection_status"] = "failed"
    except Exception as e:
        redis_data["errors"].append(f"Redis export error: {str(e)}")
        
    return redis_data


def export_pydantic_models() -> dict:
    """Export Pydantic model definitions and schema information."""
    models_data = {
        "metadata": {
            "exported_at": datetime.utcnow().isoformat() + "Z",
            "source_file": "scripts/models.py"
        },
        "models": {},
        "summary": {
            "total_models": 0,
            "total_fields": 0,
            "model_inheritance": {}
        },
        "errors": []
    }
    
    try:
        # Import our models
        from scripts.models import (
            SourceDocumentMinimal,
            DocumentChunkMinimal,
            EntityMentionMinimal,
            CanonicalEntityMinimal,
            RelationshipStagingMinimal
        )
        
        models = {
            "SourceDocumentMinimal": SourceDocumentMinimal,
            "DocumentChunkMinimal": DocumentChunkMinimal,
            "EntityMentionMinimal": EntityMentionMinimal,
            "CanonicalEntityMinimal": CanonicalEntityMinimal,
            "RelationshipStagingMinimal": RelationshipStagingMinimal
        }
        
        for model_name, model_class in models.items():
            try:
                # Get model schema
                schema = model_class.model_json_schema()
                
                # Get field information
                fields_info = {}
                if hasattr(model_class, 'model_fields'):
                    for field_name, field_info in model_class.model_fields.items():
                        fields_info[field_name] = {
                            "type": str(field_info.annotation) if hasattr(field_info, 'annotation') else "unknown",
                            "required": field_info.is_required() if hasattr(field_info, 'is_required') else True,
                            "default": str(field_info.default) if hasattr(field_info, 'default') and field_info.default is not None else None,
                            "description": field_info.description if hasattr(field_info, 'description') else None
                        }
                
                model_info = {
                    "schema": schema,
                    "fields": fields_info,
                    "field_count": len(fields_info),
                    "base_classes": [base.__name__ for base in model_class.__bases__],
                    "model_config": getattr(model_class, 'model_config', {})
                }
                
                models_data["models"][model_name] = model_info
                models_data["summary"]["total_fields"] += len(fields_info)
                
            except Exception as e:
                models_data["errors"].append(f"Error processing model {model_name}: {str(e)}")
        
        models_data["summary"]["total_models"] = len(models_data["models"])
        
        # Get inheritance information
        for model_name, model_info in models_data["models"].items():
            models_data["summary"]["model_inheritance"][model_name] = model_info["base_classes"]
            
    except ImportError as e:
        models_data["errors"].append(f"Could not import models: {str(e)}")
    except Exception as e:
        models_data["errors"].append(f"Pydantic models export error: {str(e)}")
        
    return models_data


def generate_analysis_markdown(schema_data: dict, redis_data: dict, models_data: dict) -> str:
    """Generate comprehensive markdown analysis report."""
    
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    
    md_content = f"""# Database Schema Analysis Report

Generated: {timestamp}

## Executive Summary

This report provides a comprehensive analysis of the legal-doc-processor database schema, Redis cache state, and Pydantic model definitions.

### Quick Stats
- **Database Tables:** {schema_data.get('summary', {}).get('total_tables', 0)}
- **Total Columns:** {schema_data.get('summary', {}).get('total_columns', 0)}
- **Foreign Keys:** {schema_data.get('summary', {}).get('total_foreign_keys', 0)}
- **Triggers:** {schema_data.get('summary', {}).get('total_triggers', 0)}
- **Functions:** {schema_data.get('summary', {}).get('total_functions', 0)}
- **Redis Keys:** {redis_data.get('summary', {}).get('total_keys', 0)}
- **Pydantic Models:** {models_data.get('summary', {}).get('total_models', 0)}

## Database Schema Analysis

### Table Overview
"""
    
    # Add table analysis
    if 'tables' in schema_data:
        for table_name, table_info in sorted(schema_data['tables'].items()):
            md_content += f"\n#### {table_name}\n"
            md_content += f"- **Columns:** {len(table_info.get('columns', []))}\n"
            md_content += f"- **Primary Key:** {', '.join(table_info.get('primary_key', []))}\n"
            md_content += f"- **Foreign Keys:** {len(table_info.get('foreign_keys', []))}\n"
            md_content += f"- **Indexes:** {len(table_info.get('indexes', []))}\n"
            
            # Add row count if available
            if 'row_count' in table_info and table_info['row_count'] >= 0:
                md_content += f"- **Row Count:** {table_info['row_count']:,}\n"
            
            # Add foreign key details
            if table_info.get('foreign_keys'):
                md_content += "- **References:**\n"
                for fk in table_info['foreign_keys']:
                    md_content += f"  - {fk['constrained_columns']} → {fk['referred_table']}.{fk['referred_columns']}\n"
    
    # Add triggers analysis
    md_content += "\n### Triggers\n"
    if schema_data.get('triggers'):
        for trigger in schema_data['triggers']:
            md_content += f"- **{trigger['trigger_name']}**: {trigger['action_timing']} {trigger['event_manipulation']} on {trigger['event_object_table']}\n"
    else:
        md_content += "No triggers found.\n"
    
    # Add functions analysis
    md_content += "\n### Functions\n"
    if schema_data.get('functions'):
        for func in schema_data['functions']:
            md_content += f"- **{func['routine_name']}** ({func['routine_type']}): {func['external_language']}\n"
    else:
        md_content += "No functions found.\n"
    
    # Add Redis analysis
    md_content += "\n## Redis Cache Analysis\n"
    if redis_data.get('summary', {}).get('total_keys', 0) > 0:
        md_content += f"### Key Distribution\n"
        patterns = redis_data.get('summary', {}).get('key_patterns', {})
        for pattern, count in sorted(patterns.items(), key=lambda x: x[1], reverse=True):
            md_content += f"- **{pattern}**: {count} keys\n"
        
        md_content += f"\n### Memory Usage\n"
        memory_mb = redis_data.get('summary', {}).get('memory_usage', 0) / (1024 * 1024)
        md_content += f"- **Total Memory Usage:** {memory_mb:.2f} MB\n"
    else:
        md_content += "No Redis keys found or connection failed.\n"
    
    # Add Pydantic models analysis
    md_content += "\n## Pydantic Models Analysis\n"
    if models_data.get('models'):
        for model_name, model_info in models_data['models'].items():
            md_content += f"\n### {model_name}\n"
            md_content += f"- **Fields:** {model_info.get('field_count', 0)}\n"
            md_content += f"- **Base Classes:** {', '.join(model_info.get('base_classes', []))}\n"
            
            # List key fields
            fields = model_info.get('fields', {})
            if fields:
                md_content += "- **Key Fields:**\n"
                for field_name, field_info in list(fields.items())[:10]:  # First 10 fields
                    required = "required" if field_info.get('required', True) else "optional"
                    md_content += f"  - `{field_name}`: {field_info.get('type', 'unknown')} ({required})\n"
    else:
        md_content += "No Pydantic models found or import failed.\n"
    
    # Add validation section
    if 'validation' in schema_data:
        validation = schema_data['validation']
        md_content += "\n## Schema Validation\n"
        
        if validation.get('missing_tables'):
            md_content += f"### ⚠️ Missing Tables\n"
            for table in validation['missing_tables']:
                md_content += f"- {table}\n"
        
        if validation.get('extra_tables'):
            md_content += f"### ℹ️ Extra Tables\n"
            for table in validation['extra_tables']:
                md_content += f"- {table}\n"
    
    # Add errors section if any
    all_errors = []
    all_errors.extend(schema_data.get('errors', []))
    all_errors.extend(redis_data.get('errors', []))
    all_errors.extend(models_data.get('errors', []))
    
    if all_errors:
        md_content += "\n## Errors and Warnings\n"
        for error in all_errors:
            md_content += f"- {error}\n"
    
    md_content += f"\n---\n*Report generated by schema_inspector.py on {timestamp}*\n"
    
    return md_content


def reflect_schema(uri: str, include_counts: bool = False, verbose: bool = False) -> dict:
    """
    Reflect the complete database schema and return as structured dict.
    
    Args:
        uri: Database connection URI
        include_counts: Whether to include table row counts
        verbose: Enable verbose logging
        
    Returns:
        Dictionary containing complete schema information including tables, triggers, functions, etc.
    """
    logger = setup_logging(verbose)
    
    try:
        logger.info(f"Connecting to database...")
        engine = create_engine(uri)
        inspector = inspect(engine)
        
        schema_info = {
            "metadata": {
                "generated_at": datetime.utcnow().isoformat() + "Z",
                "database_url": uri.split('@')[1] if '@' in uri else "redacted",  # Hide credentials
                "engine_name": engine.name,
                "schema_version": "legal-doc-processor-v1.0"
            },
            "tables": {},
            "triggers": [],
            "functions": [],
            "sequences": [],
            "views": [],
            "schemas": [],
            "extensions": [],
            "summary": {
                "total_tables": 0,
                "total_columns": 0,
                "total_foreign_keys": 0,
                "total_indexes": 0,
                "total_triggers": 0,
                "total_functions": 0,
                "total_sequences": 0,
                "total_views": 0,
                "total_schemas": 0,
                "total_extensions": 0
            }
        }
        
        # Get all table names
        table_names = inspector.get_table_names()
        logger.info(f"Found {len(table_names)} tables: {', '.join(table_names)}")
        
        schema_info["summary"]["total_tables"] = len(table_names)
        
        # Get all database objects (with individual error handling)
        logger.info("Gathering database objects...")
        
        # Get triggers
        try:
            schema_info["triggers"] = get_database_triggers(engine)
            schema_info["summary"]["total_triggers"] = len(schema_info["triggers"])
            logger.info(f"Found {len(schema_info['triggers'])} triggers")
        except Exception as e:
            logger.error(f"Failed to get triggers: {e}")
            schema_info["triggers"] = []
            schema_info["errors"] = schema_info.get("errors", [])
            schema_info["errors"].append(f"Triggers: {str(e)}")
        
        # Get functions
        try:
            schema_info["functions"] = get_database_functions(engine)
            schema_info["summary"]["total_functions"] = len(schema_info["functions"])
            logger.info(f"Found {len(schema_info['functions'])} functions")
        except Exception as e:
            logger.error(f"Failed to get functions: {e}")
            schema_info["functions"] = []
            schema_info["errors"] = schema_info.get("errors", [])
            schema_info["errors"].append(f"Functions: {str(e)}")
        
        # Get sequences
        try:
            schema_info["sequences"] = get_database_sequences(engine)
            schema_info["summary"]["total_sequences"] = len(schema_info["sequences"])
            logger.info(f"Found {len(schema_info['sequences'])} sequences")
        except Exception as e:
            logger.error(f"Failed to get sequences: {e}")
            schema_info["sequences"] = []
            schema_info["errors"] = schema_info.get("errors", [])
            schema_info["errors"].append(f"Sequences: {str(e)}")
        
        # Get views
        try:
            schema_info["views"] = get_database_views(engine)
            schema_info["summary"]["total_views"] = len(schema_info["views"])
            logger.info(f"Found {len(schema_info['views'])} views")
        except Exception as e:
            logger.error(f"Failed to get views: {e}")
            schema_info["views"] = []
            schema_info["errors"] = schema_info.get("errors", [])
            schema_info["errors"].append(f"Views: {str(e)}")
        
        # Get schemas
        try:
            schema_info["schemas"] = get_database_schemas(engine)
            schema_info["summary"]["total_schemas"] = len(schema_info["schemas"])
            logger.info(f"Found {len(schema_info['schemas'])} schemas")
        except Exception as e:
            logger.error(f"Failed to get schemas: {e}")
            schema_info["schemas"] = []
            schema_info["errors"] = schema_info.get("errors", [])
            schema_info["errors"].append(f"Schemas: {str(e)}")
        
        # Get extensions
        try:
            schema_info["extensions"] = get_database_extensions(engine)
            schema_info["summary"]["total_extensions"] = len(schema_info["extensions"])
            logger.info(f"Found {len(schema_info['extensions'])} extensions")
        except Exception as e:
            logger.error(f"Failed to get extensions: {e}")
            schema_info["extensions"] = []
            schema_info["errors"] = schema_info.get("errors", [])
            schema_info["errors"].append(f"Extensions: {str(e)}")
        
        # Process each table with individual error handling
        for table_name in sorted(table_names):
            logger.debug(f"Processing table: {table_name}")
            
            table_info = {
                "columns": [],
                "primary_key": [],
                "foreign_keys": [],
                "indexes": [],
                "constraints": [],
                "errors": []
            }
            
            # Add row count if requested
            if include_counts:
                try:
                    table_info["row_count"] = get_table_row_count(engine, table_name)
                except Exception as e:
                    logger.warning(f"Could not get row count for {table_name}: {e}")
                    table_info["row_count"] = -1
                    table_info["errors"].append(f"Row count: {str(e)}")
            
            # Get columns
            try:
                columns = inspector.get_columns(table_name)
                for col in columns:
                    try:
                        column_info = {
                            "name": col["name"],
                            "type": str(col["type"]),
                            "nullable": col["nullable"],
                            "default": str(col.get("default")) if col.get("default") is not None else None,
                            "autoincrement": col.get("autoincrement", False),
                            "comment": col.get("comment")
                        }
                        
                        # Track primary key columns
                        if col.get("primary_key"):
                            table_info["primary_key"].append(col["name"])
                        
                        table_info["columns"].append(column_info)
                    except Exception as e:
                        logger.warning(f"Error processing column {col.get('name', 'unknown')} in {table_name}: {e}")
                        table_info["errors"].append(f"Column {col.get('name', 'unknown')}: {str(e)}")
                
                schema_info["summary"]["total_columns"] += len(columns)
            except Exception as e:
                logger.error(f"Could not get columns for {table_name}: {e}")
                table_info["errors"].append(f"Columns: {str(e)}")
            
            # Get foreign keys
            try:
                foreign_keys = inspector.get_foreign_keys(table_name)
                for fk in foreign_keys:
                    try:
                        fk_info = {
                            "name": fk.get("name"),
                            "constrained_columns": fk["constrained_columns"],
                            "referred_schema": fk.get("referred_schema"),
                            "referred_table": fk["referred_table"],
                            "referred_columns": fk["referred_columns"],
                            "options": fk.get("options", {})
                        }
                        table_info["foreign_keys"].append(fk_info)
                    except Exception as e:
                        logger.warning(f"Error processing foreign key in {table_name}: {e}")
                        table_info["errors"].append(f"Foreign key: {str(e)}")
                
                schema_info["summary"]["total_foreign_keys"] += len(foreign_keys)
            except Exception as e:
                logger.warning(f"Could not get foreign keys for {table_name}: {e}")
                table_info["errors"].append(f"Foreign keys: {str(e)}")
            
            # Get indexes
            try:
                indexes = inspector.get_indexes(table_name)
                for idx in indexes:
                    try:
                        idx_info = {
                            "name": idx["name"],
                            "unique": idx["unique"],
                            "column_names": idx["column_names"],
                            "type": idx.get("type")
                        }
                        table_info["indexes"].append(idx_info)
                    except Exception as e:
                        logger.warning(f"Error processing index {idx.get('name', 'unknown')} in {table_name}: {e}")
                        table_info["errors"].append(f"Index {idx.get('name', 'unknown')}: {str(e)}")
                
                schema_info["summary"]["total_indexes"] += len(indexes)
            except Exception as e:
                logger.warning(f"Could not get indexes for {table_name}: {e}")
                table_info["errors"].append(f"Indexes: {str(e)}")
            
            # Get unique constraints (separate from indexes)
            try:
                unique_constraints = inspector.get_unique_constraints(table_name)
                for uc in unique_constraints:
                    try:
                        constraint_info = {
                            "name": uc["name"],
                            "type": "unique",
                            "column_names": uc["column_names"]
                        }
                        table_info["constraints"].append(constraint_info)
                    except Exception as e:
                        logger.warning(f"Error processing unique constraint in {table_name}: {e}")
                        table_info["errors"].append(f"Unique constraint: {str(e)}")
            except Exception as e:
                logger.warning(f"Could not get unique constraints for {table_name}: {e}")
                table_info["errors"].append(f"Unique constraints: {str(e)}")
            
            # Get check constraints
            try:
                check_constraints = inspector.get_check_constraints(table_name)
                for cc in check_constraints:
                    try:
                        constraint_info = {
                            "name": cc["name"],
                            "type": "check",
                            "sqltext": cc.get("sqltext")
                        }
                        table_info["constraints"].append(constraint_info)
                    except Exception as e:
                        logger.warning(f"Error processing check constraint in {table_name}: {e}")
                        table_info["errors"].append(f"Check constraint: {str(e)}")
            except Exception as e:
                logger.warning(f"Could not get check constraints for {table_name}: {e}")
                table_info["errors"].append(f"Check constraints: {str(e)}")
            
            # Clean up empty errors list
            if not table_info["errors"]:
                del table_info["errors"]
            
            schema_info["tables"][table_name] = table_info
        
        logger.info(f"Schema reflection complete: {schema_info['summary']}")
        return schema_info
        
    except SQLAlchemyError as e:
        logger.error(f"Database error: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise


def validate_schema_against_models(schema_data: dict) -> dict:
    """
    Validate the current schema against our Pydantic models.
    Returns validation report.
    """
    validation_report = {
        "model_table_mapping": {
            "SourceDocumentMinimal": "source_documents",
            "DocumentChunkMinimal": "document_chunks", 
            "EntityMentionMinimal": "entity_mentions",
            "CanonicalEntityMinimal": "canonical_entities",
            "RelationshipStagingMinimal": "relationship_staging"
        },
        "validation_results": {},
        "missing_tables": [],
        "extra_tables": []
    }
    
    expected_tables = set(validation_report["model_table_mapping"].values())
    actual_tables = set(schema_data["tables"].keys())
    
    validation_report["missing_tables"] = list(expected_tables - actual_tables)
    validation_report["extra_tables"] = list(actual_tables - expected_tables)
    
    # Validate each expected table
    for model_name, table_name in validation_report["model_table_mapping"].items():
        if table_name in actual_tables:
            table_info = schema_data["tables"][table_name]
            validation_report["validation_results"][table_name] = {
                "exists": True,
                "column_count": len(table_info["columns"]),
                "has_primary_key": len(table_info["primary_key"]) > 0,
                "foreign_key_count": len(table_info["foreign_keys"]),
                "index_count": len(table_info["indexes"])
            }
        else:
            validation_report["validation_results"][table_name] = {
                "exists": False
            }
    
    return validation_report


def main() -> None:
    """Main entry point for schema inspector."""
    parser = argparse.ArgumentParser(
        description="Dump legal-doc-processor RDS schema to JSON",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument(
        "uri", 
        nargs="?", 
        help="Database URI (if not provided, uses DATABASE_URL from environment)"
    )
    
    parser.add_argument(
        "-o", "--output", 
        metavar="BASE_NAME",
        help="Base filename for exports (creates _schema.json, _redis.json, _models.json, _analysis.md)"
    )
    
    parser.add_argument(
        "--include-counts",
        action="store_true",
        help="Include table row counts (slower but more informative)"
    )
    
    parser.add_argument(
        "--validate",
        action="store_true", 
        help="Include validation against Pydantic models"
    )
    
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )
    
    args = parser.parse_args()
    
    # Get database URI
    try:
        if args.uri:
            db_uri = args.uri
        else:
            db_uri = get_database_url()
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    
    # Generate human-readable timestamp for directory
    timestamp = datetime.utcnow()
    human_timestamp = timestamp.strftime("%Y-%m-%d_%H-%M-%S_UTC")
    
    # Create monitoring reports directory structure
    reports_base_dir = Path("/opt/legal-doc-processor/monitoring/reports")
    
    if args.output:
        # If user specified output, use it as base but still create timestamped directory
        if args.output.startswith('/'):
            # Absolute path - use as-is but add timestamp
            output_dir = Path(args.output).parent / human_timestamp
            base_name = Path(args.output).stem
        else:
            # Relative path - create under reports with timestamp
            output_dir = reports_base_dir / human_timestamp
            base_name = args.output.replace('.json', '').replace('.md', '')
    else:
        # Default: create timestamped directory under reports
        output_dir = reports_base_dir / human_timestamp
        base_name = "schema_export"
    
    # Ensure directory exists
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Output file paths with consistent naming
    schema_json_file = output_dir / f"{base_name}_database_schema.json"
    redis_json_file = output_dir / f"{base_name}_redis_keys.json"
    models_json_file = output_dir / f"{base_name}_pydantic_models.json" 
    analysis_md_file = output_dir / f"{base_name}_analysis_report.md"
    
    # Export Redis data
    print("Exporting Redis keys...")
    redis_data = export_redis_keys()
    
    # Export Pydantic models
    print("Exporting Pydantic models...")
    models_data = export_pydantic_models()
    
    # Reflect schema with robust error handling
    print("Exporting database schema...")
    schema_data = None
    try:
        schema_data = reflect_schema(
            db_uri, 
            include_counts=args.include_counts,
            verbose=args.verbose
        )
        
        # Add validation if requested
        if args.validate:
            try:
                validation_report = validate_schema_against_models(schema_data)
                schema_data["validation"] = validation_report
            except Exception as e:
                print(f"Warning: Validation failed: {e}", file=sys.stderr)
                schema_data["validation_error"] = str(e)
        
    except Exception as e:
        print(f"Error during schema reflection: {e}", file=sys.stderr)
        # Create minimal schema with error information
        schema_data = {
            "metadata": {
                "generated_at": datetime.utcnow().isoformat() + "Z",
                "database_url": "connection_failed",
                "schema_version": "legal-doc-processor-v1.0",
                "error": str(e)
            },
            "tables": {},
            "triggers": [],
            "functions": [],
            "sequences": [],
            "views": [],
            "schemas": [],
            "extensions": [],
            "summary": {
                "total_tables": 0,
                "total_columns": 0,
                "total_foreign_keys": 0,
                "total_indexes": 0,
                "total_triggers": 0,
                "total_functions": 0,
                "total_sequences": 0,
                "total_views": 0,
                "total_schemas": 0,
                "total_extensions": 0
            },
            "critical_error": str(e)
        }
    
    # Generate analysis markdown
    print("Generating analysis report...")
    analysis_md = generate_analysis_markdown(schema_data, redis_data, models_data)
    
    # Always try to output all files, even if there were errors
    try:
        # Write all files to timestamped directory
        files_written = []
        
        # 1. Database Schema JSON
        try:
            schema_json = json.dumps(schema_data, indent=2, default=str)
            if output_dir:
                with open(schema_json_file, "w") as f:
                    f.write(schema_json + "\n")
                files_written.append(f"📊 Database Schema: {schema_json_file.name}")
            else:
                print("=== DATABASE SCHEMA JSON ===")
                print(schema_json)
        except Exception as e:
            print(f"Error writing database schema JSON: {e}", file=sys.stderr)
        
        # 2. Redis Keys JSON  
        try:
            redis_json = json.dumps(redis_data, indent=2, default=str)
            if output_dir:
                with open(redis_json_file, "w") as f:
                    f.write(redis_json + "\n")
                files_written.append(f"🔑 Redis Keys: {redis_json_file.name}")
            else:
                print("\n=== REDIS KEYS JSON ===")
                print(redis_json)
        except Exception as e:
            print(f"Error writing Redis keys JSON: {e}", file=sys.stderr)
        
        # 3. Pydantic Models JSON
        try:
            models_json = json.dumps(models_data, indent=2, default=str)
            if output_dir:
                with open(models_json_file, "w") as f:
                    f.write(models_json + "\n")
                files_written.append(f"🏗️  Pydantic Models: {models_json_file.name}")
            else:
                print("\n=== PYDANTIC MODELS JSON ===")
                print(models_json)
        except Exception as e:
            print(f"Error writing Pydantic models JSON: {e}", file=sys.stderr)
        
        # 4. Analysis Report Markdown
        try:
            if output_dir:
                with open(analysis_md_file, "w") as f:
                    f.write(analysis_md)
                files_written.append(f"📋 Analysis Report: {analysis_md_file.name}")
            else:
                print("\n=== ANALYSIS REPORT MARKDOWN ===")
                print(analysis_md)
        except Exception as e:
            print(f"Error writing analysis report markdown: {e}", file=sys.stderr)
        
        # Print summary
        if output_dir and files_written:
            print(f"\n📁 Export Directory: {output_dir}")
            print(f"📅 Timestamp: {human_timestamp}")
            print("\n📊 Files Created:")
            for file_msg in files_written:
                print(f"   {file_msg}")
            
            # Print summary statistics
            print(f"\n📈 Summary Statistics:")
            if "summary" in schema_data:
                summary = schema_data["summary"]
                print(f"   Database Tables: {summary.get('total_tables', 0)}")
                print(f"   Total Columns: {summary.get('total_columns', 0)}")
                print(f"   Foreign Keys: {summary.get('total_foreign_keys', 0)}")
                print(f"   Triggers: {summary.get('total_triggers', 0)}")
                print(f"   Functions: {summary.get('total_functions', 0)}")
            
            redis_summary = redis_data.get('summary', {})
            print(f"   Redis Keys: {redis_summary.get('total_keys', 0)}")
            
            models_summary = models_data.get('summary', {})
            print(f"   Pydantic Models: {models_summary.get('total_models', 0)}")
            
            # Print directory structure
            print(f"\n🗂️  Directory Structure:")
            print(f"   {output_dir}/")
            for file_path in [schema_json_file, redis_json_file, models_json_file, analysis_md_file]:
                if file_path.exists():
                    size_kb = file_path.stat().st_size / 1024
                    print(f"   ├── {file_path.name} ({size_kb:.1f} KB)")
            
            # Print validation warnings if available
            if args.validate and "validation" in schema_data:
                validation = schema_data["validation"]
                if validation.get("missing_tables"):
                    print(f"\n⚠️  Missing tables: {', '.join(validation['missing_tables'])}")
                if validation.get("extra_tables"):
                    print(f"ℹ️  Extra tables: {', '.join(validation['extra_tables'])}")
            
            # Print error warnings if any
            all_errors = []
            all_errors.extend(schema_data.get('errors', []))
            all_errors.extend(redis_data.get('errors', []))
            all_errors.extend(models_data.get('errors', []))
            
            if all_errors:
                print(f"\n⚠️  Warnings/Errors: {len(all_errors)} issues encountered")
            
            if "critical_error" in schema_data:
                print(f"❌ Critical error occurred: {schema_data['critical_error']}")
        
        elif not output_dir:
            print("\n=== END OF EXPORT ===")
            
    except Exception as output_error:
        print(f"Error during output: {output_error}", file=sys.stderr)
        # Last resort fallback
        if not args.output:
            print("FALLBACK - Schema JSON only:")
            try:
                print(json.dumps(schema_data, indent=2, default=str))
            except:
                print(f"Critical failure: {output_error}")


if __name__ == "__main__":
    main()