# Auto-generated models from database schema
# Generated at: 2025-05-29T21:59:07.491045
# DO NOT EDIT MANUALLY - Use 'python -m scripts.database.generate_from_known_schema' to regenerate

from typing import Optional, Dict, Any, List, Union
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, Field

class Projects(BaseModel):
    """Model for projects table."""
    project_uuid: str = Field(alias='project_uuid')
    project_name: str = Field(alias='project_name')
    created_at: datetime = Field(alias='created_at')
    updated_at: Optional[datetime] = None = Field(alias='updated_at')

    class Config:
        from_attributes = True
        populate_by_name = True

class Documents(BaseModel):
    """Model for documents table."""
    document_uuid: str = Field(alias='document_uuid')
    project_uuid: str = Field(alias='project_uuid')
    document_name: str = Field(alias='document_name')
    document_type: Optional[str] = None = Field(alias='document_type')
    s3_path: Optional[str] = None = Field(alias='s3_path')
    file_size: Optional[int] = None = Field(alias='file_size')
    import_session_uuid: Optional[str] = None = Field(alias='import_session_uuid')
    processing_status: str = Field(alias='processing_status')
    celery_task_id: Optional[str] = None = Field(alias='celery_task_id')
    metadata: Optional[Dict[str, Any]] = None
    created_at: datetime = Field(alias='created_at')
    updated_at: Optional[datetime] = None = Field(alias='updated_at')

    class Config:
        from_attributes = True
        populate_by_name = True

class ProcessingPipeline(BaseModel):
    """Model for processing_pipeline table."""
    pipeline_uuid: str = Field(alias='pipeline_uuid')
    document_uuid: str = Field(alias='document_uuid')
    stage_name: str = Field(alias='stage_name')
    stage_status: str = Field(alias='stage_status')
    error_message: Optional[str] = None = Field(alias='error_message')
    retry_count: int = 0 = Field(alias='retry_count')
    started_at: datetime = Field(alias='started_at')
    completed_at: Optional[datetime] = None = Field(alias='completed_at')

    class Config:
        from_attributes = True
        populate_by_name = True

class ProcessingQueue(BaseModel):
    """Model for processing_queue table."""
    queue_uuid: str = Field(alias='queue_uuid')
    document_uuid: str = Field(alias='document_uuid')
    queue_type: str = Field(alias='queue_type')
    priority: int = 50
    celery_task_id: Optional[str] = None = Field(alias='celery_task_id')
    enqueued_at: datetime = Field(alias='enqueued_at')
    processing_started_at: Optional[datetime] = None = Field(alias='processing_started_at')

    class Config:
        from_attributes = True
        populate_by_name = True

class DocumentChunks(BaseModel):
    """Model for document_chunks table."""
    chunk_uuid: str = Field(alias='chunk_uuid')
    document_uuid: str = Field(alias='document_uuid')
    chunk_index: int = Field(alias='chunk_index')
    chunk_text: str = Field(alias='chunk_text')
    chunk_metadata: Optional[Dict[str, Any]] = None = Field(alias='chunk_metadata')
    embedding: Optional[Dict[str, Any]] = None
    created_at: datetime = Field(alias='created_at')

    class Config:
        from_attributes = True
        populate_by_name = True

class EntityMentions(BaseModel):
    """Model for entity_mentions table."""
    mention_uuid: str = Field(alias='mention_uuid')
    document_uuid: str = Field(alias='document_uuid')
    chunk_uuid: Optional[str] = None = Field(alias='chunk_uuid')
    entity_text: str = Field(alias='entity_text')
    entity_type: str = Field(alias='entity_type')
    confidence_score: Optional[float] = None = Field(alias='confidence_score')
    context: Optional[str] = None
    canonical_entity_uuid: Optional[str] = None = Field(alias='canonical_entity_uuid')
    created_at: datetime = Field(alias='created_at')

    class Config:
        from_attributes = True
        populate_by_name = True

class CanonicalEntities(BaseModel):
    """Model for canonical_entities table."""
    entity_uuid: str = Field(alias='entity_uuid')
    project_uuid: str = Field(alias='project_uuid')
    entity_name: str = Field(alias='entity_name')
    entity_type: str = Field(alias='entity_type')
    aliases: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    embedding: Optional[Dict[str, Any]] = None
    created_at: datetime = Field(alias='created_at')
    updated_at: Optional[datetime] = None = Field(alias='updated_at')

    class Config:
        from_attributes = True
        populate_by_name = True

class RelationshipStaging(BaseModel):
    """Model for relationship_staging table."""
    relationship_uuid: str = Field(alias='relationship_uuid')
    source_entity_uuid: str = Field(alias='source_entity_uuid')
    target_entity_uuid: str = Field(alias='target_entity_uuid')
    relationship_type: str = Field(alias='relationship_type')
    confidence_score: Optional[float] = None = Field(alias='confidence_score')
    evidence: Optional[Dict[str, Any]] = None
    status: str = pending
    created_at: datetime = Field(alias='created_at')

    class Config:
        from_attributes = True
        populate_by_name = True

class ProcessingMetrics(BaseModel):
    """Model for processing_metrics table."""
    metric_uuid: str = Field(alias='metric_uuid')
    document_uuid: str = Field(alias='document_uuid')
    stage_name: str = Field(alias='stage_name')
    metric_name: str = Field(alias='metric_name')
    metric_value: Dict[str, Any] = Field(alias='metric_value')
    recorded_at: datetime = Field(alias='recorded_at')

    class Config:
        from_attributes = True
        populate_by_name = True

class ImportSessions(BaseModel):
    """Model for import_sessions table."""
    session_uuid: str = Field(alias='session_uuid')
    project_uuid: str = Field(alias='project_uuid')
    session_name: str = Field(alias='session_name')
    import_source: Optional[str] = None = Field(alias='import_source')
    total_files: int = Field(alias='total_files')
    files_uploaded: int = 0 = Field(alias='files_uploaded')
    files_processing: int = 0 = Field(alias='files_processing')
    files_completed: int = 0 = Field(alias='files_completed')
    files_failed: int = 0 = Field(alias='files_failed')
    started_at: datetime = Field(alias='started_at')
    completed_at: Optional[datetime] = None = Field(alias='completed_at')

    class Config:
        from_attributes = True
        populate_by_name = True
