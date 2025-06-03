#!/usr/bin/env python3
"""
Minimal schema mapping fix to make the pipeline work.
Maps between expected table/column names and actual simplified schema.
"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Table name mappings
TABLE_MAPPINGS = {
    "source_documents": "documents",
    "document_chunks": "chunks",
    "entity_mentions": "entities",
    "canonical_entities": "entities",  # Simplified: no separate canonical table
    "relationship_staging": "relationships",
    "neo4j_documents": "documents",  # Map to documents
    "textract_jobs": "processing_logs",  # Use logs table for OCR tracking
}

# Column name mappings per table
COLUMN_MAPPINGS = {
    "documents": {
        # source_documents -> documents mappings
        "document_uuid": "document_uuid",
        "original_file_name": "original_filename",
        "detected_file_type": "mime_type",
        "project_fk_id": None,  # Not used in simple schema
        "project_uuid": "project_uuid",
        "original_file_path": None,  # Not stored
        "s3_key": "s3_key",
        "s3_bucket": "s3_bucket",
        "s3_region": None,  # Not stored
        "file_size_bytes": "file_size_bytes",
        "md5_hash": "file_hash",
        "initial_processing_status": "processing_status",
        "celery_status": "processing_status",
        "celery_task_id": "celery_task_id",
        "error_message": "processing_error",
        "raw_extracted_text": None,  # Not stored in documents table
        "markdown_text": None,  # Not stored in documents table
        "ocr_metadata_json": "metadata",  # Store in general metadata
        "ocr_provider": None,  # Not tracked separately
        "page_count": "page_count",
        # Add reverse mappings
        "processing_status": "processing_status",
        "processing_error": "processing_error",
    },
    "chunks": {
        # document_chunks -> chunks mappings
        "chunk_id": "chunk_id",
        "chunk_uuid": "chunk_id",  # Map UUID fields
        "document_id": None,  # Not used, we use document_uuid
        "document_uuid": "document_uuid",
        "chunk_index": "chunk_index",
        "text": "content",
        "text_content": "content",  # Alternative name
        "char_start_index": None,  # Not tracked in simple schema
        "char_end_index": None,  # Not tracked in simple schema
        "start_char": None,  # Alternative name
        "end_char": None,  # Alternative name
        "metadata_json": "metadata",
        "page_number": "page_number",
        "word_count": "token_count",  # Map to token_count
    },
    "entities": {
        # entity_mentions -> entities mappings
        "entity_mention_id": "entity_id",
        "entity_mention_uuid": "entity_id",
        "chunk_fk_id": None,  # Not used
        "chunk_uuid": "chunk_id",
        "value": "entity_text",
        "text": "entity_text",  # Alternative name
        "entity_type": "entity_type",
        "normalized_value": "canonical_name",
        "offset_start": "start_offset",
        "offset_end": "end_offset",
        "confidence_score": "confidence_score",
        "confidence": "confidence_score",  # Alternative name
        "attributes_json": "attributes",
        # For canonical entities
        "canonical_entity_id": "entity_id",
        "canonical_entity_uuid": "entity_id",
        "canonical_name": "canonical_name",
        "all_known_aliases_in_doc": None,  # Not tracked
        "mention_count": None,  # Not tracked
    },
    "relationships": {
        # relationship_staging -> relationships mappings
        "from_node_id": "from_entity_id",
        "from_node_label": None,  # Not used
        "to_node_id": "to_entity_id",
        "to_node_label": None,  # Not used
        "relationship_type": "relationship_type",
        "properties": "metadata",
        "confidence_score": "confidence_score",
        "source_chunk_id": None,  # Not tracked
        "source_id": "document_uuid",  # Map to document
    },
    "processing_logs": {
        # textract_jobs -> processing_logs mappings
        "job_id": "event_data",  # Store in JSON
        "source_document_id": None,  # Not used
        "document_uuid": "document_uuid",
        "job_status": "event_status",
        "started_at": "created_at",
    }
}


def map_table_name(table: str) -> str:
    """Map Pydantic model table name to actual database table."""
    return TABLE_MAPPINGS.get(table, table)


def map_column_names(table: str, data: Dict[str, Any], reverse: bool = False) -> Dict[str, Any]:
    """Map column names between Pydantic models and actual schema.
    
    Args:
        table: Original table name (before mapping)
        data: Dictionary of column->value pairs
        reverse: If True, map from DB to Pydantic names
    """
    # Get the actual table name
    actual_table = map_table_name(table)
    
    # Get column mappings for this table
    mappings = COLUMN_MAPPINGS.get(actual_table, {})
    
    if not mappings:
        return data
    
    # If reverse mapping, create inverse dictionary
    if reverse:
        mappings = {v: k for k, v in mappings.items() if v is not None}
    
    # Map the data
    mapped_data = {}
    for key, value in data.items():
        mapped_key = mappings.get(key, key)
        if mapped_key is not None:  # Skip columns that don't exist
            mapped_data[mapped_key] = value
    
    return mapped_data


def adapt_processing_status(status: str) -> str:
    """Adapt complex processing statuses to simple schema."""
    # Map complex statuses to simple ones
    status_map = {
        "pending_intake": "pending",
        "ocr_processing": "processing",
        "ocr_completed": "processing",
        "ocr_failed": "failed",
        "text_processing": "processing",
        "text_completed": "processing",
        "text_failed": "failed",
        "entity_processing": "processing",
        "entity_completed": "processing",
        "entity_failed": "failed",
        "graph_processing": "processing",
        "graph_completed": "completed",
        "graph_failed": "failed",
        "error": "failed",
        "reprocessing": "processing",
    }
    return status_map.get(status, status)


def patch_database_manager():
    """Monkey patch the DatabaseManager to use schema mappings."""
    try:
        from scripts.db import DatabaseManager, PydanticDatabase
        
        # Store original methods
        original_create = PydanticDatabase.create
        original_update = PydanticDatabase.update
        original_get = PydanticDatabase.get
        original_list = PydanticDatabase.list
        
        def patched_create(self, table: str, model, returning: bool = True):
            # Map table name
            actual_table = map_table_name(table)
            
            # Get model data and map columns
            data = model.model_dump(mode='json')
            mapped_data = map_column_names(table, data)
            
            # Handle special cases
            if 'processing_status' in mapped_data:
                mapped_data['processing_status'] = adapt_processing_status(
                    mapped_data['processing_status']
                )
            
            # Create new model with mapped data
            from pydantic import create_model
            MappedModel = create_model('MappedModel', **{k: (type(v), v) for k, v in mapped_data.items()})
            mapped_model = MappedModel()
            
            # Use original method with mapped table and model
            result = original_create(self, actual_table, mapped_model, returning)
            
            # Map result back if needed
            if result and returning:
                reverse_data = map_column_names(table, result.model_dump(), reverse=True)
                return type(model)(**reverse_data)
            
            return result
        
        def patched_get(self, table: str, model_class, match_fields: Dict[str, Any]):
            # Map table and fields
            actual_table = map_table_name(table)
            mapped_fields = map_column_names(table, match_fields)
            
            # Get with mapped values
            result = original_get(self, actual_table, model_class, mapped_fields)
            
            # Map result back if found
            if result:
                reverse_data = map_column_names(table, result.model_dump(), reverse=True)
                return model_class(**reverse_data)
            
            return result
        
        # Apply patches
        PydanticDatabase.create = patched_create
        PydanticDatabase.get = patched_get
        
        logger.info("Schema mapping patches applied successfully")
        
    except Exception as e:
        logger.error(f"Failed to apply schema mapping patches: {e}")
        raise


if __name__ == "__main__":
    # Test the mappings
    print("Table mappings:")
    for old, new in TABLE_MAPPINGS.items():
        print(f"  {old} -> {new}")
    
    print("\nTesting column mappings:")
    test_data = {
        "document_uuid": "123",
        "original_file_name": "test.pdf",
        "celery_status": "ocr_processing"
    }
    mapped = map_column_names("source_documents", test_data)
    print(f"  Input: {test_data}")
    print(f"  Mapped: {mapped}")
