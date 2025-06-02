"""
Minimal Pydantic models for core document processing.
These models contain only essential fields to bypass conformance issues.
"""
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field


class SourceDocumentMinimal(BaseModel):
    """Minimal source document model with only essential fields"""
    # Primary identifiers
    id: Optional[int] = None
    document_uuid: UUID
    
    # Essential file info
    original_file_name: str
    file_name: Optional[str] = None  # Some code expects this
    s3_key: Optional[str] = None
    s3_bucket: Optional[str] = None
    
    # Organization
    project_uuid: Optional[UUID] = None
    project_fk_id: Optional[int] = None
    
    # Processing state
    status: str = "pending"  # Simplified from enum
    celery_status: Optional[str] = "pending"
    error_message: Optional[str] = None
    
    # OCR/Textract tracking
    textract_job_id: Optional[str] = None
    textract_job_status: Optional[str] = None
    raw_extracted_text: Optional[str] = None
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None
    ocr_completed_at: Optional[datetime] = None
    processing_completed_at: Optional[datetime] = None
    
    class Config:
        orm_mode = True


class DocumentChunkMinimal(BaseModel):
    """Minimal document chunk model"""
    # Identifiers
    id: Optional[int] = None
    chunk_uuid: UUID
    document_uuid: UUID
    
    # Essential content
    chunk_index: int
    text_content: str
    start_char: int
    end_char: int
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        orm_mode = True


class EntityMentionMinimal(BaseModel):
    """Minimal entity mention model"""
    # Identifiers
    id: Optional[int] = None
    mention_uuid: UUID
    chunk_uuid: UUID
    document_uuid: UUID
    
    # Essential entity info
    entity_text: str
    entity_type: str
    start_char: int
    end_char: int
    confidence_score: float = 0.0
    
    # Linking
    canonical_entity_uuid: Optional[UUID] = None
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        orm_mode = True


class CanonicalEntityMinimal(BaseModel):
    """Minimal canonical entity model"""
    # Identifiers
    id: Optional[int] = None
    canonical_entity_uuid: UUID
    
    # Essential info
    entity_name: str
    entity_type: str
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None
    
    class Config:
        orm_mode = True


class RelationshipStagingMinimal(BaseModel):
    """Minimal relationship staging model"""
    # Identifiers
    id: Optional[int] = None
    relationship_uuid: UUID
    
    # Essential relationship info
    source_entity_uuid: UUID
    target_entity_uuid: UUID
    relationship_type: str
    confidence_score: float = 0.0
    
    # Source tracking
    document_uuid: Optional[UUID] = None
    chunk_uuid: Optional[UUID] = None
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        orm_mode = True


# Aliases for compatibility
ChunkModelMinimal = DocumentChunkMinimal
EntityMentionModelMinimal = EntityMentionMinimal
CanonicalEntityModelMinimal = CanonicalEntityMinimal