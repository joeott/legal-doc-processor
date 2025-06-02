"""
Enhanced column mappings for complete pipeline-RDS conformance
This file contains ALL the mappings needed for the pipeline to work
"""

from typing import Dict, Any
import json
import uuid

# Complete table mappings
TABLE_MAPPINGS = {
    # Simplified/Expected name -> Actual RDS table name
    "documents": "source_documents",
    "chunks": "document_chunks",
    "entities": "entity_mentions",
    "entity_relationships": "relationship_staging",
    "canonical_entities": "canonical_entities",
    "processing_tasks": "processing_tasks",
    "projects": "projects",
    "import_sessions": "import_sessions",
    # Also support Neo4j-specific names
    "neo4j_chunks": "document_chunks",
    "neo4j_entity_mentions": "entity_mentions",
    "neo4j_canonical_entities": "canonical_entities",
    "neo4j_relationships_staging": "relationship_staging",
    "neo4j_documents": "source_documents",
    "textract_jobs": "textract_jobs"
}

# Complete column mappings for each table (keyed by actual RDS table names)
COLUMN_MAPPINGS = {
    "source_documents": {
        # Core identification - map directly to actual RDS columns
        "document_uuid": "document_uuid",  # Direct mapping to UUID field
        "project_uuid": "project_uuid",
        "project_fk_id": "project_fk_id",
        
        # File information - use actual column names
        "original_file_name": "original_file_name",  # Direct mapping after rename
        "filename": "file_name",  # Map to renamed column
        "file_name": "file_name",  # Direct mapping for new name
        "file_size_bytes": "file_size_bytes",
        "detected_file_type": "detected_file_type", 
        "file_type": "file_type",
        
        # S3 storage - direct mappings
        "s3_key": "s3_key",
        "s3_bucket": "s3_bucket",
        "s3_region": "s3_region",
        "original_file_path": "original_file_path",
        "file_path": "file_path",
        
        # Processing status - map to specific status fields
        "processing_status": "status",  # Map to renamed column
        "status": "status",  # Direct mapping for new name
        "initial_processing_status": "initial_processing_status", 
        "celery_status": "celery_status",
        "celery_task_id": "celery_task_id",
        
        # Content - direct mappings to text fields
        "raw_extracted_text": "raw_extracted_text",
        "markdown_text": "markdown_text",
        "cleaned_text": "cleaned_text",
        
        # OCR metadata - use actual JSONB fields
        "ocr_metadata_json": "ocr_metadata_json",
        "transcription_metadata_json": "transcription_metadata_json",
        "ocr_provider": "ocr_provider",
        "ocr_processing_seconds": "ocr_processing_seconds",
        "ocr_confidence_score": "ocr_confidence_score",
        
        # Textract fields - direct mappings
        "textract_job_id": "textract_job_id",
        "textract_job_status": "textract_job_status",
        "textract_start_time": "textract_start_time",
        "textract_end_time": "textract_end_time",
        "textract_page_count": "textract_page_count",
        "textract_error_message": "textract_error_message",
        
        # Timestamps - direct mappings
        "created_at": "created_at",
        "updated_at": "updated_at",
        "ocr_completed_at": "ocr_completed_at",
        
        # Import tracking
        "import_session_id": "import_session_id",
        
        # Computed/extra fields that don't have direct columns (store in ocr_metadata_json)
        "page_count": "ocr_metadata_json",
        "chunk_count": "ocr_metadata_json", 
        "entity_count": "ocr_metadata_json",
        "md5_hash": "ocr_metadata_json",
        "content_type": "ocr_metadata_json",
        "mime_type": "ocr_metadata_json"
    },
    
    "document_chunks": {
        # ChunkModel fields -> chunks table columns
        "chunk_id": "chunk_uuid",
        "chunk_uuid": "chunk_uuid",
        "document_id": "document_fk_id",  # Map to FK field
        "document_uuid": "document_uuid",
        "chunk_index": "chunk_index",
        "text": "text_content",  # Map to actual column name
        "text_content": "text_content",
        
        # Character positions - direct mappings
        "char_start_index": "char_start_index",
        "char_end_index": "char_end_index",
        "charStartIndex": "char_start_index",
        "charEndIndex": "char_end_index",
        
        # Page info
        "page_number": "start_page",
        "start_page": "start_page",
        "end_page": "end_page",
        
        # Metadata
        "metadata_json": "metadata_json",
        "metadataJson": "metadata_json",
        "metadata": "metadata_json",  # Also map plain metadata
        
        # Embeddings
        "embedding": "embedding_vector",
        "embedding_model": "embedding_model",
        
        # Chunk relationships - these are stored within metadata_json, not as direct mappings
        # We'll handle these in the reverse mapping logic
        # "previous_chunk_id": "metadata_json",
        # "next_chunk_id": "metadata_json",
        # "previousChunkId": "metadata_json",
        # "nextChunkId": "metadata_json"
    },
    
    "entity_mentions": {
        # EntityMentionModel fields -> entities table columns
        "entity_mention_id": "id",
        "entity_mention_uuid": "id",
        "document_id": "document_id",
        "document_uuid": "document_id",
        "chunk_id": "metadata",  # Store chunk reference in metadata
        "chunk_uuid": "metadata",
        
        # Entity data
        "text": "name",
        "value": "name",
        "entity_text": "name",
        "entity_type": "entity_type",
        "confidence": "confidence_score",
        "confidence_score": "confidence_score",
        
        # Canonical reference
        "canonical_entity_id": "canonical_entity_id",
        "canonical_entity_uuid": "canonical_entity_id",
        
        # Position info
        "offset_start": "metadata",
        "offset_end": "metadata",
        "start_offset": "metadata",
        "end_offset": "metadata",
        
        # Context
        "context": "context",
        "page_number": "page_number",
        
        # Attributes
        "attributes_json": "metadata",
        "metadata_json": "metadata"
    },
    
    "canonical_entities": {
        # CanonicalEntityModel fields -> canonical_entities table columns  
        "canonical_entity_id": "id",
        "canonical_entity_uuid": "id",
        "name": "name",
        "canonical_name": "name",
        "normalized_value": "name",
        "entity_type": "entity_type",
        
        # Aliases and metadata
        "aliases": "aliases",
        "alias_list": "aliases",
        "metadata_json": "metadata",
        "attributes_json": "metadata",
        
        # Counts
        "mention_count": "metadata",
        "document_count": "metadata"
    },
    
    "relationship_staging": {
        # RelationshipModel fields -> entity_relationships table columns
        "relationship_id": "id",
        "from_node_id": "source_entity_id",
        "to_node_id": "target_entity_id",
        "source_id": "source_entity_id",
        "target_id": "target_entity_id",
        
        # Relationship data
        "relationship_type": "relationship_type",
        "confidence": "confidence_score",
        "confidence_score": "confidence_score",
        
        # Metadata
        "properties": "metadata",
        "metadata_json": "metadata",
        "document_uuid": "metadata"  # Store document reference in metadata
    },
    
    "processing_tasks": {
        # ProcessingTaskModel fields -> processing_tasks table columns
        "task_id": "id",
        "document_id": "document_id",
        "document_uuid": "document_id",
        
        # Task info
        "task_type": "task_type",
        "task_status": "task_status",
        "celery_task_id": "celery_task_id",
        
        # Retry info
        "retry_count": "retry_count",
        "max_retries": "max_retries",
        
        # Results
        "error_message": "error_message",
        "result": "result",
        "result_json": "result",
        
        # Timestamps
        "started_at": "started_at",
        "completed_at": "completed_at"
    },
    
    "projects": {
        # ProjectModel fields -> projects table columns
        "project_id": "id",
        "projectId": "id",
        "supabase_project_id": "id",
        "supabaseProjectId": "id",
        
        # Project data
        "name": "name",
        "description": "description",
        "client_name": "client_name",
        "matter_number": "matter_number",
        
        # Script tracking
        "script_run_count": "metadata",
        "scriptRunCount": "metadata",
        "processed_by_scripts": "metadata",
        "processedByScripts": "metadata",
        
        # Airtable integration
        "airtable_id": "metadata",
        "last_synced_at": "metadata",
        
        # Metadata
        "data_layer": "metadata",
        "metadata": "metadata",
        "active": "metadata"
    }
}

# Status mapping - simplify complex statuses for RDS
STATUS_MAPPINGS = {
    # Complex status -> Simple status
    "pending": "pending",
    "pending_intake": "pending",
    "ocr_processing": "processing",
    "ocr_complete": "processing",
    "ocr_completed": "processing",
    "ocr_failed": "failed",
    "text_processing": "processing",
    "text_completed": "processing",
    "text_failed": "failed",
    "entity_processing": "processing",
    "entity_completed": "processing",
    "entity_failed": "failed",
    "graph_processing": "processing",
    "graph_completed": "processing",
    "graph_failed": "failed",
    "completed": "completed",
    "failed": "failed",
    "error": "failed",
    "reprocessing": "processing"
}

# Type conversions for special cases
TYPE_CONVERSIONS = {
    "uuid_to_string": lambda v: str(v) if hasattr(v, 'hex') else v,
    "string_to_uuid": lambda v: v if hasattr(v, 'hex') else (uuid.UUID(v) if v else None),
    "json_to_string": lambda v: json.dumps(v) if isinstance(v, (dict, list)) else v,
    "string_to_json": lambda v: json.loads(v) if isinstance(v, str) else v
}

def get_mapped_column(table: str, column: str) -> str:
    """Get the mapped column name for a table"""
    actual_table = TABLE_MAPPINGS.get(table, table)
    mappings = COLUMN_MAPPINGS.get(actual_table, {})
    return mappings.get(column, column)

def get_mapped_status(status: str) -> str:
    """Map complex status to simple status"""
    return STATUS_MAPPINGS.get(status, status)

def should_store_in_metadata(table: str, column: str) -> bool:
    """Check if a column should be stored in metadata JSON"""
    actual_table = TABLE_MAPPINGS.get(table, table)
    mappings = COLUMN_MAPPINGS.get(actual_table, {})
    mapped = mappings.get(column)
    return mapped in ["metadata", "processing_metadata", "ocr_metadata_json", "transcription_metadata_json"]

def get_reverse_column_mappings(table: str) -> Dict[str, str]:
    """Get reverse mappings from RDS columns to Pydantic fields"""
    actual_table = TABLE_MAPPINGS.get(table, table)
    mappings = COLUMN_MAPPINGS.get(actual_table, {})
    
    # Create reverse mappings, excluding metadata fields
    reverse = {}
    for pydantic_field, rds_column in mappings.items():
        if rds_column not in ["metadata", "processing_metadata", "ocr_metadata_json", "transcription_metadata_json"]:
            reverse[rds_column] = pydantic_field
    
    return reverse

def reverse_map_from_db(table: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Map RDS column names back to Pydantic field names"""
    actual_table = TABLE_MAPPINGS.get(table, table)
    reverse_mappings = get_reverse_column_mappings(table)
    
    result = {}
    metadata_fields = {}
    
    # Debug logging
    import logging
    logger = logging.getLogger(__name__)
    if actual_table == "document_chunks":
        logger.debug(f"Reverse mapping for chunks - input data: {data}")
    
    for rds_column, value in data.items():
        # Check if this RDS column maps to a Pydantic field
        pydantic_field = reverse_mappings.get(rds_column)
        
        if pydantic_field:
            # Special handling for fields that map to metadata columns
            if rds_column in ["metadata_json", "ocr_metadata_json", "transcription_metadata_json"]:
                # Don't directly map the metadata column to fields that expect specific values
                # This will be handled in the metadata extraction logic below
                pass
            else:
                result[pydantic_field] = value
        elif rds_column in ["id", "created_at", "updated_at"]:
            # Keep these common fields as-is
            result[rds_column] = value
        elif rds_column == "ocr_metadata_json" and isinstance(value, dict):
            # Extract fields that were stored in ocr_metadata_json
            for field in ["page_count", "chunk_count", "entity_count", "md5_hash", "content_type", "mime_type"]:
                if field in value:
                    result[field] = value[field]
        elif rds_column == "transcription_metadata_json" and isinstance(value, dict):
            # Extract fields from transcription metadata if needed
            pass
        elif rds_column == "metadata_json":
            if isinstance(value, dict) and value:  # Only process non-empty dicts
                # Extract fields from metadata_json for chunks
                for field in ["previous_chunk_id", "next_chunk_id", "previousChunkId", "nextChunkId"]:
                    if field in value:
                        # Handle empty dict case - convert to None for UUID fields
                        if value[field] == {} or value[field] == "" or not value[field]:
                            result[field] = None
                        else:
                            result[field] = value[field]
                # Also include the metadata itself
                result["metadata_json"] = value
            elif value == {}:
                # Empty metadata - just include it but don't extract fields
                result["metadata_json"] = value
        else:
            # Unknown column, include as-is
            result[rds_column] = value
    
    # Handle special aliases for chunks table
    if actual_table == "document_chunks":
        # Map chunk_uuid to chunkId alias
        if "chunk_uuid" in result and "chunk_id" not in result:
            result["chunk_id"] = result["chunk_uuid"]
        # Map text_content to text
        if "text_content" in result and "text" not in result:
            result["text"] = result["text_content"]
        
        # Debug final result
        logger.debug(f"Reverse mapping result: {result}")
    
    return result