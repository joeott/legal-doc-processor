"""
Minimal models for legal document processing pipeline.
These models are the single source of truth derived from working code.
All models here have been proven to work in production.
"""

from datetime import datetime
from typing import Optional, Dict, Any, List
from uuid import UUID
from enum import Enum
from dataclasses import dataclass
from pydantic import BaseModel, Field, ConfigDict

# ================================================================================
# ENUMS - From working pipeline
# ================================================================================

class ProcessingStatus(str, Enum):
    """Document processing status"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    
class EntityType(str, Enum):
    """Allowed entity types for extraction"""
    PERSON = "PERSON"
    ORG = "ORG"
    LOCATION = "LOCATION"
    DATE = "DATE"

class ProcessingResultStatus(str, Enum):
    """Result status for processing operations"""
    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"

# ================================================================================
# MINIMAL MODELS - Proven in production
# ================================================================================

class SourceDocumentMinimal(BaseModel):
    """Minimal source document model"""
    model_config = ConfigDict(from_attributes=True)
    
    document_uuid: UUID
    project_uuid: UUID
    file_name: str
    file_path: Optional[str] = None
    file_size: Optional[int] = None
    mime_type: Optional[str] = None
    status: str = ProcessingStatus.PENDING
    processing_queued_at: Optional[datetime] = None
    processing_started_at: Optional[datetime] = None
    processing_completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None
    
    # OCR specific fields
    raw_extracted_text: Optional[str] = None
    ocr_completed_at: Optional[datetime] = None
    ocr_provider: Optional[str] = None
    textract_job_id: Optional[str] = None
    celery_task_id: Optional[str] = None

class DocumentChunkMinimal(BaseModel):
    """Minimal document chunk model"""
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    
    chunk_uuid: UUID
    document_uuid: UUID
    chunk_index: int
    text: str  # Note: This is 'text' in the database, not 'text_content'
    start_char: int = Field(alias='char_start_index')
    end_char: int = Field(alias='char_end_index')
    created_at: datetime = Field(default_factory=datetime.utcnow)

class EntityMentionMinimal(BaseModel):
    """Minimal entity mention model"""
    model_config = ConfigDict(from_attributes=True)
    
    mention_uuid: UUID
    chunk_uuid: UUID
    document_uuid: UUID
    entity_text: str  # Note: This is 'entity_text', not 'text'
    entity_type: str
    start_char: int
    end_char: int
    confidence_score: Optional[float] = 0.9
    canonical_entity_uuid: Optional[UUID] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

class CanonicalEntityMinimal(BaseModel):
    """Minimal canonical entity model"""
    model_config = ConfigDict(from_attributes=True)
    
    canonical_entity_uuid: UUID
    entity_type: str
    canonical_name: str  # Primary name
    entity_names: List[str] = Field(default_factory=list)  # All variations
    first_seen_date: datetime = Field(default_factory=datetime.utcnow)
    last_seen_date: datetime = Field(default_factory=datetime.utcnow)
    document_count: int = 1
    mention_count: int = 1
    metadata: Dict[str, Any] = Field(default_factory=dict)

class RelationshipStagingMinimal(BaseModel):
    """Minimal relationship staging model - matches actual database schema"""
    model_config = ConfigDict(from_attributes=True)
    
    # Match the actual database columns
    id: Optional[int] = None
    source_entity_uuid: UUID
    target_entity_uuid: UUID
    relationship_type: str
    confidence_score: float = 1.0
    source_chunk_uuid: Optional[UUID] = None
    evidence_text: Optional[str] = None
    properties: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)

# ================================================================================
# RESULT MODELS - For pipeline operations
# ================================================================================

@dataclass
class ProcessingResult:
    """Standard result for processing operations"""
    status: ProcessingResultStatus
    message: str = ""
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    
    @property
    def is_success(self) -> bool:
        return self.status == ProcessingResultStatus.SUCCESS

# ================================================================================
# MODEL FACTORY - Single point of access
# ================================================================================

class ModelFactory:
    """Single factory for all model access"""
    
    @staticmethod
    def get_document_model():
        """Get the source document model"""
        return SourceDocumentMinimal
    
    @staticmethod
    def get_chunk_model():
        """Get the document chunk model"""
        return DocumentChunkMinimal
    
    @staticmethod
    def get_entity_mention_model():
        """Get the entity mention model"""
        return EntityMentionMinimal
    
    @staticmethod
    def get_canonical_entity_model():
        """Get the canonical entity model"""
        return CanonicalEntityMinimal
    
    @staticmethod
    def get_relationship_model():
        """Get the relationship staging model"""
        return RelationshipStagingMinimal
    
    @staticmethod
    def create_document(**kwargs) -> SourceDocumentMinimal:
        """Create a new document instance"""
        return SourceDocumentMinimal(**kwargs)
    
    @staticmethod
    def create_chunk(**kwargs) -> DocumentChunkMinimal:
        """Create a new chunk instance"""
        return DocumentChunkMinimal(**kwargs)
    
    @staticmethod
    def create_entity_mention(**kwargs) -> EntityMentionMinimal:
        """Create a new entity mention instance"""
        return EntityMentionMinimal(**kwargs)
    
    @staticmethod
    def create_canonical_entity(**kwargs) -> CanonicalEntityMinimal:
        """Create a new canonical entity instance"""
        return CanonicalEntityMinimal(**kwargs)
    
    @staticmethod
    def create_relationship(**kwargs) -> RelationshipStagingMinimal:
        """Create a new relationship instance"""
        return RelationshipStagingMinimal(**kwargs)

# ================================================================================
# EXPORTS - What the rest of the codebase should use
# ================================================================================

__all__ = [
    # Enums
    'ProcessingStatus',
    'EntityType', 
    'ProcessingResultStatus',
    
    # Models
    'SourceDocumentMinimal',
    'DocumentChunkMinimal',
    'EntityMentionMinimal',
    'CanonicalEntityMinimal',
    'RelationshipStagingMinimal',
    
    # Result
    'ProcessingResult',
    
    # Factory
    'ModelFactory'
]