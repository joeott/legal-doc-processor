"""
Pydantic models for database schema validation and type safety.

This module defines the single source of truth for all data structures
in the legal document processing pipeline. All models are designed to
match the Supabase database schema exactly while providing automatic
validation, serialization, and type safety.
"""

import json
import uuid
from datetime import datetime
from typing import List, Optional, Dict, Any, Union
from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator, ConfigDict
from pydantic.json_schema import JsonSchemaValue
from pydantic.types import constr


# Enums for constrained fields
class ProcessingStatus(str, Enum):
    """Processing status values for documents"""
    PENDING = "pending"
    PENDING_INTAKE = "pending_intake"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    ERROR = "error"
    
    # Celery-specific statuses
    OCR_PROCESSING = "ocr_processing"
    OCR_COMPLETED = "ocr_completed"
    OCR_FAILED = "ocr_failed"
    TEXT_PROCESSING = "text_processing"
    TEXT_COMPLETED = "text_completed"
    TEXT_FAILED = "text_failed"
    ENTITY_PROCESSING = "entity_processing"
    ENTITY_COMPLETED = "entity_completed"
    ENTITY_FAILED = "entity_failed"
    GRAPH_PROCESSING = "graph_processing"
    GRAPH_COMPLETED = "graph_completed"
    GRAPH_FAILED = "graph_failed"


class EntityType(str, Enum):
    """Standard entity types for extraction"""
    PERSON = "PERSON"
    ORGANIZATION = "ORG"
    LOCATION = "LOCATION"
    DATE = "DATE"
    MONEY = "MONEY"
    CASE_NUMBER = "CASE_NUMBER"
    STATUTE = "STATUTE"
    COURT = "COURT"
    JUDGE = "JUDGE"
    ATTORNEY = "ATTORNEY"
    OTHER = "OTHER"


class RelationshipType(str, Enum):
    """Graph relationship types"""
    BELONGS_TO = "BELONGS_TO"
    CONTAINS_MENTION = "CONTAINS_MENTION"
    MEMBER_OF_CLUSTER = "MEMBER_OF_CLUSTER"
    RELATED_TO = "RELATED_TO"
    NEXT_CHUNK = "NEXT_CHUNK"
    PREVIOUS_CHUNK = "PREVIOUS_CHUNK"
    REFERENCES = "REFERENCES"
    AUTHORED_BY = "AUTHORED_BY"
    FILED_BY = "FILED_BY"
    OPPOSING_PARTY = "OPPOSING_PARTY"


# Base Models
class BaseTimestampModel(BaseModel):
    """Base model with common timestamp fields"""
    id: Optional[int] = Field(None, description="Database primary key")
    created_at: Optional[datetime] = Field(None, alias="createdAt")
    updated_at: Optional[datetime] = Field(None, alias="updatedAt")
    
    model_config = ConfigDict(
        populate_by_name=True,  # Allow both field name and alias
        use_enum_values=True,   # Use enum values instead of enum objects
        json_encoders={
            datetime: lambda v: v.isoformat() if v else None,
            uuid.UUID: lambda v: str(v) if v else None
        }
    )
    
    @field_validator('created_at', 'updated_at', mode='before')
    @classmethod
    def parse_datetime(cls, v):
        """Parse datetime from string if needed"""
        if isinstance(v, str):
            try:
                return datetime.fromisoformat(v.replace('Z', '+00:00'))
            except:
                return None
        return v
    
    def to_db_dict(self, exclude_none: bool = True, by_alias: bool = True) -> dict:
        """Convert model to dictionary for database operations"""
        return self.model_dump(
            exclude_none=exclude_none,
            by_alias=by_alias,
            mode='json'
        )


# Project Models
class ProjectModel(BaseTimestampModel):
    """Model for projects table"""
    # Required fields
    name: str = Field(..., description="Project name")
    
    # Optional fields with database defaults
    project_id: Optional[uuid.UUID] = Field(None, alias="projectId")
    supabase_project_id: Optional[uuid.UUID] = Field(None, alias="supabaseProjectId")
    script_run_count: Optional[int] = Field(0, alias="scriptRunCount")
    processed_by_scripts: Optional[bool] = Field(False, alias="processedByScripts")
    data_layer: Optional[Dict[str, Any]] = Field(None, alias="data_layer")
    
    # Airtable integration
    airtable_id: Optional[str] = Field(None, alias="airtable_id", max_length=255)
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)
    active: Optional[bool] = Field(True)
    last_synced_at: Optional[datetime] = Field(None, alias="last_synced_at")
    
    @field_validator('project_id', mode='before')
    @classmethod
    def ensure_project_id(cls, v):
        """Generate project_id if not provided"""
        if v is None:
            return uuid.uuid4()
        if isinstance(v, str):
            return uuid.UUID(v)
        return v
    
    @field_validator('metadata', mode='before')
    @classmethod
    def parse_metadata(cls, v):
        """Parse metadata from JSON string if needed"""
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return {}
        return v or {}


# Source Document Models
class SourceDocumentModel(BaseTimestampModel):
    """Model for source_documents table - the primary document record"""
    # Required fields
    document_uuid: uuid.UUID = Field(..., description="Unique document identifier")
    original_file_name: str = Field(..., description="Original filename")
    detected_file_type: str = Field(..., description="Detected MIME type or extension")
    
    # Foreign keys
    project_fk_id: Optional[int] = Field(None, description="Project SQL ID")
    project_uuid: Optional[uuid.UUID] = Field(None, description="Project UUID")
    
    # File paths and storage
    original_file_path: Optional[str] = Field(None, description="Original file path")
    s3_key: Optional[str] = Field(None, description="S3 storage key")
    s3_bucket: Optional[str] = Field(None, description="S3 bucket name")
    s3_region: Optional[str] = Field(None, description="AWS region")
    s3_key_public: Optional[str] = Field(None, description="Public S3 key")
    s3_bucket_public: Optional[str] = Field(None, description="Public S3 bucket")
    
    # File metadata
    file_size_bytes: Optional[int] = Field(None, description="File size in bytes")
    md5_hash: Optional[str] = Field(None, description="MD5 hash of file")
    content_type: Optional[str] = Field(None, description="Content-Type header")
    user_defined_name: Optional[str] = Field(None, description="User-provided name")
    
    # Processing status
    initial_processing_status: Optional[str] = Field("pending_intake")
    celery_status: Optional[str] = Field("pending_intake", description="Celery task status")
    celery_task_id: Optional[str] = Field(None, description="Celery task ID")
    error_message: Optional[str] = Field(None, description="Error message if failed")
    
    # Timestamps
    intake_timestamp: Optional[datetime] = Field(None, description="When document was uploaded")
    last_modified_at: Optional[datetime] = Field(None, description="Last modification time")
    
    # Extracted content
    raw_extracted_text: Optional[str] = Field(None, description="Raw OCR text")
    markdown_text: Optional[str] = Field(None, description="Markdown formatted text")
    
    # OCR metadata
    ocr_metadata_json: Optional[Dict[str, Any]] = Field(None, alias="ocr_metadata_json")
    transcription_metadata_json: Optional[Dict[str, Any]] = Field(None, alias="transcription_metadata_json")
    ocr_provider: Optional[str] = Field(None, description="OCR service used")
    ocr_completed_at: Optional[datetime] = Field(None)
    ocr_processing_seconds: Optional[float] = Field(None)
    
    # Textract specific fields
    textract_job_id: Optional[str] = Field(None, description="AWS Textract job ID")
    textract_job_status: Optional[str] = Field(None, description="Textract job status")
    textract_job_started_at: Optional[datetime] = Field(None)
    textract_job_completed_at: Optional[datetime] = Field(None)
    textract_confidence_avg: Optional[float] = Field(None)
    textract_warnings: Optional[List[str]] = Field(None)
    textract_output_s3_key: Optional[str] = Field(None)
    
    # Import session tracking
    import_session_id: Optional[int] = Field(None, description="Import batch ID")
    
    @field_validator('document_uuid', mode='before')
    @classmethod
    def ensure_document_uuid(cls, v):
        """Generate document_uuid if not provided"""
        if v is None:
            return uuid.uuid4()
        if isinstance(v, str):
            return uuid.UUID(v)
        return v
    
    @field_validator('ocr_metadata_json', 'transcription_metadata_json', mode='before')
    @classmethod
    def parse_json_metadata(cls, v):
        """Parse JSON metadata from string if needed"""
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return {}
        return v or {}
    
    @model_validator(mode='after')
    def validate_processing_status(self):
        """Ensure processing status is consistent"""
        if self.celery_status and self.celery_status.endswith('_failed'):
            if not self.error_message:
                self.error_message = f"Process failed with status: {self.celery_status}"
        return self


# Neo4j Document Models
class Neo4jDocumentModel(BaseTimestampModel):
    """Model for neo4j_documents table - processed document node"""
    # Required fields
    document_id: uuid.UUID = Field(..., alias="documentId", description="Document UUID")
    source_document_fk_id: int = Field(..., description="Source document SQL ID")
    project_id: int = Field(..., description="Project SQL ID")
    project_uuid: uuid.UUID = Field(..., description="Project UUID")
    name: str = Field(..., description="Document name")
    
    # Optional fields
    storage_path: Optional[str] = Field(None, alias="storagePath")
    processing_status: ProcessingStatus = Field(ProcessingStatus.PENDING, alias="processingStatus")
    metadata_json: Optional[Dict[str, Any]] = Field(None, alias="metadataJson")
    md5_hash: Optional[str] = Field(None, alias="md5Hash")
    processed_timestamp: Optional[datetime] = Field(None, alias="processedTimestamp")
    
    @field_validator('metadata_json', mode='before')
    @classmethod
    def parse_metadata_json(cls, v):
        """Parse metadata JSON"""
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return {}
        return v or {}


# Chunk Models
class ChunkModel(BaseTimestampModel):
    """Model for neo4j_chunks table - semantic text chunks"""
    # Required fields
    chunk_id: uuid.UUID = Field(..., alias="chunkId", description="Chunk UUID")
    document_id: int = Field(..., description="Document SQL ID")
    document_uuid: uuid.UUID = Field(..., description="Document UUID")
    chunk_index: int = Field(..., alias="chunkIndex", description="Order in document")
    text: str = Field(..., description="Chunk text content")
    
    # Character positions
    char_start_index: int = Field(..., alias="charStartIndex")
    char_end_index: int = Field(..., alias="charEndIndex")
    
    # Optional fields
    metadata_json: Optional[Dict[str, Any]] = Field(None, alias="metadataJson")
    embedding: Optional[List[float]] = Field(None, description="Vector embedding")
    embedding_model: Optional[str] = Field(None, description="Model used for embedding")
    
    # Relationships
    previous_chunk_id: Optional[uuid.UUID] = Field(None, alias="previousChunkId")
    next_chunk_id: Optional[uuid.UUID] = Field(None, alias="nextChunkId")
    
    @field_validator('chunk_id', mode='before')
    @classmethod
    def ensure_chunk_id(cls, v):
        """Generate chunk_id if not provided"""
        if v is None:
            return uuid.uuid4()
        if isinstance(v, str):
            return uuid.UUID(v)
        return v
    
    @field_validator('embedding', mode='before')
    @classmethod
    def validate_embedding(cls, v):
        """Validate embedding dimensions"""
        if v is not None:
            if not isinstance(v, list):
                raise ValueError("Embedding must be a list of floats")
            if len(v) not in [384, 768, 1536, 3072]:  # Common embedding sizes
                raise ValueError(f"Unexpected embedding dimension: {len(v)}")
        return v
    
    @model_validator(mode='after')
    def validate_indices(self):
        """Ensure char indices are valid"""
        if self.char_end_index < self.char_start_index:
            raise ValueError(f"Invalid char indices: start={self.char_start_index}, end={self.char_end_index}")
        return self


# Entity Models
class EntityMentionModel(BaseTimestampModel):
    """Model for neo4j_entity_mentions table"""
    # Required fields
    entity_mention_id: uuid.UUID = Field(..., alias="entityMentionId")
    chunk_fk_id: int = Field(..., description="Chunk SQL ID")
    chunk_uuid: uuid.UUID = Field(..., description="Chunk UUID")
    value: str = Field(..., description="Entity text value")
    entity_type: EntityType = Field(..., description="Entity type")
    
    # Optional fields
    normalized_value: Optional[str] = Field(None, alias="normalizedValue")
    offset_start: Optional[int] = Field(None, alias="offsetStart")
    offset_end: Optional[int] = Field(None, alias="offsetEnd")
    resolved_canonical_id: Optional[uuid.UUID] = Field(None, alias="resolvedCanonicalId")
    attributes_json: Optional[Dict[str, Any]] = Field(None, alias="attributesJson")
    confidence_score: Optional[float] = Field(None, alias="confidenceScore")
    
    @field_validator('entity_mention_id', mode='before')
    @classmethod
    def ensure_entity_mention_id(cls, v):
        """Generate ID if not provided"""
        if v is None:
            return uuid.uuid4()
        if isinstance(v, str):
            return uuid.UUID(v)
        return v
    
    @field_validator('confidence_score')
    @classmethod
    def validate_confidence(cls, v):
        """Ensure confidence is between 0 and 1"""
        if v is not None and not 0 <= v <= 1:
            raise ValueError(f"Confidence score must be between 0 and 1, got {v}")
        return v


class CanonicalEntityModel(BaseTimestampModel):
    """Model for neo4j_canonical_entities table"""
    # Required fields
    canonical_entity_id: uuid.UUID = Field(..., alias="canonicalEntityId")
    canonical_name: str = Field(..., alias="canonicalName")
    entity_type: EntityType = Field(..., description="Entity type")
    
    # Optional fields
    document_id: Optional[int] = Field(None, alias="documentId")
    document_uuid: Optional[uuid.UUID] = Field(None, alias="documentUuid")
    all_known_aliases_in_doc: Optional[List[str]] = Field(None, alias="allKnownAliasesInDoc")
    mention_count: Optional[int] = Field(0, alias="mentionCount")
    embedding: Optional[List[float]] = Field(None, description="Entity embedding")
    attributes_json: Optional[Dict[str, Any]] = Field(None, alias="attributesJson")
    
    @field_validator('canonical_entity_id', mode='before')
    @classmethod
    def ensure_canonical_entity_id(cls, v):
        """Generate ID if not provided"""
        if v is None:
            return uuid.uuid4()
        if isinstance(v, str):
            return uuid.UUID(v)
        return v
    
    @field_validator('all_known_aliases_in_doc', mode='before')
    @classmethod
    def parse_aliases(cls, v):
        """Parse aliases from JSON string if needed"""
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return [v]  # Single alias
        return v or []


# Relationship Models
class RelationshipStagingModel(BaseTimestampModel):
    """Model for neo4j_relationships_staging table"""
    # Required fields
    from_node_id: str = Field(..., alias="fromNodeId")
    from_node_label: str = Field(..., alias="fromNodeLabel")
    to_node_id: str = Field(..., alias="toNodeId")
    to_node_label: str = Field(..., alias="toNodeLabel")
    relationship_type: RelationshipType = Field(..., alias="relationshipType")
    
    # Optional fields
    properties: Optional[Dict[str, Any]] = Field(default_factory=dict)
    confidence_score: Optional[float] = Field(None, alias="confidenceScore")
    source_chunk_id: Optional[uuid.UUID] = Field(None, alias="sourceChunkId")
    
    @field_validator('properties', mode='before')
    @classmethod
    def ensure_properties_dict(cls, v):
        """Ensure properties is a dict"""
        if v is None:
            return {}
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return {}
        return v


# Textract Job Models
class TextractJobModel(BaseTimestampModel):
    """Model for textract_jobs table"""
    # Required fields
    job_id: str = Field(..., description="AWS Textract job ID")
    source_document_id: int = Field(..., description="Source document SQL ID")
    document_uuid: uuid.UUID = Field(..., description="Document UUID")
    job_status: str = Field(..., description="Job status")
    
    # S3 references
    s3_input_bucket: str = Field(..., description="Input S3 bucket")
    s3_input_key: str = Field(..., description="Input S3 key")
    s3_output_bucket: Optional[str] = Field(None, description="Output S3 bucket")
    s3_output_prefix: Optional[str] = Field(None, description="Output S3 prefix")
    
    # Job metadata
    job_tag: Optional[str] = Field(None, description="Job tag for tracking")
    notification_channel_sns_topic_arn: Optional[str] = Field(None, description="SNS topic ARN")
    notification_channel_role_arn: Optional[str] = Field(None, description="IAM role ARN")
    
    # Timing
    started_at: datetime = Field(..., description="Job start time")
    completed_at: Optional[datetime] = Field(None, description="Job completion time")
    
    # Results
    pages_processed: Optional[int] = Field(None, description="Number of pages")
    warnings: Optional[List[str]] = Field(None, description="Processing warnings")
    status_message: Optional[str] = Field(None, description="Status message")
    
    @field_validator('warnings', mode='before')
    @classmethod
    def parse_warnings(cls, v):
        """Parse warnings from JSON"""
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return [v]
        return v or []


# Import Session Models
class ImportSessionModel(BaseTimestampModel):
    """Model for import_sessions table"""
    # Required fields
    session_name: str = Field(..., description="Import session name")
    manifest_path: str = Field(..., description="Path to manifest file")
    
    # Statistics
    total_files: int = Field(0, description="Total files to import")
    processed_files: int = Field(0, description="Files processed")
    failed_files: int = Field(0, description="Files failed")
    
    # Status
    status: str = Field("pending", description="Session status")
    error_log: Optional[List[Dict[str, Any]]] = Field(None, description="Error log")
    
    # Timing
    started_at: Optional[datetime] = Field(None, description="Start time")
    completed_at: Optional[datetime] = Field(None, description="Completion time")
    
    @field_validator('error_log', mode='before')
    @classmethod
    def parse_error_log(cls, v):
        """Parse error log from JSON"""
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return []
        return v or []


# Embedding Models
class ChunkEmbeddingModel(BaseTimestampModel):
    """Model for chunk_embeddings table"""
    chunk_id: uuid.UUID = Field(..., description="Chunk UUID")
    embedding: List[float] = Field(..., description="Vector embedding")
    model_name: str = Field(..., description="Embedding model name")
    model_version: Optional[str] = Field(None, description="Model version")
    dimensions: int = Field(..., description="Embedding dimensions")
    
    @field_validator('embedding')
    @classmethod
    def validate_embedding_dimensions(cls, v, info):
        """Validate embedding matches declared dimensions"""
        if 'dimensions' in info.data and len(v) != info.data['dimensions']:
            raise ValueError(f"Embedding has {len(v)} dimensions but declared {info.data['dimensions']}")
        return v


class CanonicalEntityEmbeddingModel(BaseTimestampModel):
    """Model for canonical_entity_embeddings table"""
    canonical_entity_id: uuid.UUID = Field(..., description="Entity UUID")
    embedding: List[float] = Field(..., description="Vector embedding")
    model_name: str = Field(..., description="Embedding model name")
    model_version: Optional[str] = Field(None, description="Model version")
    dimensions: int = Field(..., description="Embedding dimensions")
    
    @field_validator('embedding')
    @classmethod
    def validate_embedding_dimensions(cls, v, info):
        """Validate embedding matches declared dimensions"""
        if 'dimensions' in info.data and len(v) != info.data['dimensions']:
            raise ValueError(f"Embedding has {len(v)} dimensions but declared {info.data['dimensions']}")
        return v


# Document Processing History Model
class DocumentProcessingHistoryModel(BaseTimestampModel):
    """Model for document_processing_history table"""
    source_document_id: int = Field(..., description="Source document SQL ID")
    document_uuid: uuid.UUID = Field(..., description="Document UUID")
    action: str = Field(..., description="Action performed")
    status: str = Field(..., description="Action status")
    details: Optional[Dict[str, Any]] = Field(None, description="Action details")
    error_message: Optional[str] = Field(None, description="Error if failed")
    performed_by: Optional[str] = Field(None, description="User or system")
    celery_task_id: Optional[str] = Field(None, description="Associated Celery task")
    duration_seconds: Optional[float] = Field(None, description="Processing duration")
    
    @field_validator('details', mode='before')
    @classmethod
    def parse_details(cls, v):
        """Parse details from JSON"""
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return {"raw": v}
        return v or {}


# Helper function to create model from database row
def create_model_from_db(model_class: type[BaseModel], data: dict) -> BaseModel:
    """
    Create a Pydantic model instance from database row data.
    Handles None values and type conversions gracefully.
    """
    if not data:
        return None
    
    # Remove None values to use model defaults
    cleaned_data = {k: v for k, v in data.items() if v is not None}
    
    try:
        return model_class.model_validate(cleaned_data)
    except Exception as e:
        # Log error and return partial model if possible
        print(f"Error creating {model_class.__name__} from data: {e}")
        # Try with minimal required fields only
        required_fields = {
            k: v for k, v in cleaned_data.items() 
            if k in model_class.model_fields and model_class.model_fields[k].is_required
        }
        return model_class.model_validate(required_fields)


# Export all models
__all__ = [
    # Enums
    'ProcessingStatus',
    'EntityType',
    'RelationshipType',
    
    # Base
    'BaseTimestampModel',
    
    # Models
    'ProjectModel',
    'SourceDocumentModel',
    'Neo4jDocumentModel',
    'ChunkModel',
    'EntityMentionModel',
    'CanonicalEntityModel',
    'RelationshipStagingModel',
    'TextractJobModel',
    'ImportSessionModel',
    'ChunkEmbeddingModel',
    'CanonicalEntityEmbeddingModel',
    'DocumentProcessingHistoryModel',
    
    # Helpers
    'create_model_from_db'
]