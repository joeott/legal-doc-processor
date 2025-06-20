"""
Consolidated minimal models for legal document processing.

This module serves as the single source of truth for all Pydantic models used
in the legal document processing pipeline. Models are organized as follows:

1. DATABASE MODELS (Minimal Models)
   - Match the actual database schema (see /monitoring/reports/*/schema_export_database_schema.json)
   - Include only fields that exist in the database
   - Provide backward compatibility properties where needed
   - Used for CRUD operations and data persistence
   
2. PROCESSING MODELS (In scripts.core.processing_models)
   - Used for pipeline data transfer between stages
   - Include processing metadata and validation logic
   - Not directly persisted to database
   - Should remain separate due to different purpose

3. MODEL ORGANIZATION PRINCIPLES
   - All database models end with "Minimal" suffix
   - Backward compatibility via @property decorators
   - Field names match exact database column names
   - Type annotations match database types (e.g., UUID not int for IDs)

4. BACKWARD COMPATIBILITY
   Many models provide properties to support legacy code:
   - chunk.text_content → chunk.text
   - chunk.start_char → chunk.char_start_index
   - entity.entity_name → entity.canonical_name
   - task.document_uuid → task.document_id
   - task.stage → task.task_type

See context_487, context_488, and context_489 for consolidation history.
Last verified against database schema: January 10, 2025
"""

from datetime import datetime
from typing import Optional, Dict, Any, List
from uuid import UUID
from enum import Enum
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
    FAILURE = "failure"  # Keep for backward compatibility
    FAILED = "failed"    # Used by entity_service.py
    PARTIAL = "partial"
    SKIPPED = "skipped"  # Used by entity_service.py

# ================================================================================
# MINIMAL MODELS - Based on actual usage analysis
# ================================================================================

class SourceDocumentMinimal(BaseModel):
    """Minimal source document model - only fields actually used in production"""
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    
    # Primary identifiers (always required)
    document_uuid: UUID
    id: Optional[int] = None
    
    # Project association (always used)
    project_fk_id: int
    project_uuid: Optional[UUID] = None  # Sometimes needed for cache
    
    # File information (always used)
    file_name: str
    original_file_name: str
    
    # S3 storage (always used)
    s3_key: str
    s3_bucket: str
    s3_region: Optional[str] = "us-east-1"
    
    # Processing state (always used)
    status: str = ProcessingStatus.PENDING.value
    error_message: Optional[str] = None
    
    # Task tracking (used when processing)
    celery_task_id: Optional[str] = None
    
    # OCR results (populated after OCR)
    raw_extracted_text: Optional[str] = None
    textract_job_id: Optional[str] = None
    ocr_completed_at: Optional[datetime] = None
    ocr_provider: Optional[str] = None
    
    # Timestamps (always used)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    # Additional fields that some code expects
    file_size_bytes: Optional[int] = None
    processing_completed_at: Optional[datetime] = None

class DocumentChunkMinimal(BaseModel):
    """Minimal document chunk model - matches database exactly"""
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    
    # Primary identifiers
    chunk_uuid: UUID
    id: Optional[int] = None
    
    # Document association
    document_uuid: UUID
    document_fk_id: Optional[int] = None
    
    # Chunk data
    chunk_index: int
    text: str  # Main content field in database
    
    # Position tracking - MUST match database column names
    char_start_index: int  # Database column name
    char_end_index: int    # Database column name
    
    # Timestamps
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    # Backward compatibility properties for code expecting old names
    @property
    def start_char(self) -> int:
        """Backward compatibility for code expecting start_char"""
        return self.char_start_index
    
    @property
    def end_char(self) -> int:
        """Backward compatibility for code expecting end_char"""
        return self.char_end_index
    
    @property
    def text_content(self) -> str:
        """Backward compatibility for code expecting text_content"""
        return self.text

class EntityMentionMinimal(BaseModel):
    """Minimal entity mention model - matches database exactly"""
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    
    # Primary identifiers
    mention_uuid: UUID
    id: Optional[int] = None
    
    # Associations
    document_uuid: UUID
    chunk_uuid: UUID
    chunk_fk_id: Optional[int] = None
    
    # Entity data
    entity_text: str
    entity_type: str
    
    # Position in chunk - matches database columns
    start_char: int
    end_char: int
    
    # Confidence and linking
    confidence_score: float = 0.9
    canonical_entity_uuid: Optional[UUID] = None
    
    # Timestamps
    created_at: Optional[datetime] = None

class CanonicalEntityMinimal(BaseModel):
    """Minimal canonical entity model - matches database exactly"""
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    
    # Primary identifiers
    canonical_entity_uuid: UUID
    id: Optional[int] = None
    
    # Entity data - MUST use canonical_name to match database
    canonical_name: str  # Database column name
    entity_type: str
    
    # Aggregation data
    mention_count: int = 1
    confidence_score: Optional[float] = None
    
    # JSON fields (kept for compatibility but often empty)
    aliases: Optional[List[str]] = Field(default_factory=list)
    properties: Optional[Dict[str, Any]] = Field(default_factory=dict)
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)
    
    # Resolution tracking
    resolution_method: Optional[str] = None
    
    # Timestamps
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    # Backward compatibility for code expecting entity_name
    @property
    def entity_name(self) -> str:
        """Backward compatibility for code expecting entity_name"""
        return self.canonical_name

class RelationshipStagingMinimal(BaseModel):
    """Minimal relationship staging model - matches database exactly"""
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    
    # Primary identifier - NO relationship_uuid in database!
    id: Optional[int] = None
    
    # Relationship data
    source_entity_uuid: UUID
    target_entity_uuid: UUID
    relationship_type: str
    confidence_score: float = 1.0
    
    # Evidence tracking
    source_chunk_uuid: Optional[UUID] = None
    evidence_text: Optional[str] = None
    
    # JSON fields
    properties: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    # Timestamp
    created_at: Optional[datetime] = None

# ================================================================================
# ADDITIONAL MODELS - Used in specific contexts
# ================================================================================

class ProcessingTaskMinimal(BaseModel):
    """Minimal processing task model for Celery tracking
    
    Note: This model matches the actual database schema for processing_tasks table.
    Field mappings:
    - document_id (not document_uuid) in database
    - task_type (not stage) in database
    - No task_uuid column exists in database
    """
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    
    id: Optional[UUID] = None  # Primary key, auto-generated UUID
    document_id: UUID  # Foreign key to source_documents (named document_id in DB)
    task_type: str  # 'ocr', 'chunking', 'entity_extraction', etc.
    status: str = ProcessingStatus.PENDING.value
    celery_task_id: Optional[str] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    retry_count: Optional[int] = 0
    
    # Backward compatibility properties
    @property
    def document_uuid(self) -> UUID:
        """Backward compatibility: code expects document_uuid"""
        return self.document_id
    
    @property
    def stage(self) -> str:
        """Backward compatibility: code expects stage instead of task_type"""
        return self.task_type

class ProjectMinimal(BaseModel):
    """Minimal project model"""
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    
    id: int
    project_id: UUID
    name: str
    active: bool = True
    created_at: Optional[datetime] = None

class TextractJobMinimal(BaseModel):
    """Minimal Textract job tracking model
    
    Tracks AWS Textract OCR jobs for documents.
    Note: id is INTEGER (not UUID) in this table.
    """
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    
    id: Optional[int] = None  # Primary key, auto-increment INTEGER
    job_id: str  # AWS Textract job ID
    document_uuid: UUID  # Foreign key to source_documents
    job_type: str  # Type of Textract operation
    status: str  # Job status (matches Textract status values)
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    page_count: Optional[int] = None
    result_s3_key: Optional[str] = None
    error_message: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

# ================================================================================
# RESULT MODELS - For pipeline operations
# ================================================================================

from dataclasses import dataclass

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
    def get_processing_task_model():
        """Get the processing task model"""
        return ProcessingTaskMinimal
    
    @staticmethod
    def get_project_model():
        """Get the project model"""
        return ProjectMinimal
    
    @staticmethod
    def get_textract_job_model():
        """Get the Textract job model"""
        return TextractJobMinimal
    
    # Creation methods
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
    
    # Core Models
    'SourceDocumentMinimal',
    'DocumentChunkMinimal',
    'EntityMentionMinimal',
    'CanonicalEntityMinimal',
    'RelationshipStagingMinimal',
    
    # Additional Models
    'ProcessingTaskMinimal',
    'ProjectMinimal',
    
    # Result
    'ProcessingResult',
    
    # Factory
    'ModelFactory',
    
    # Aliases for compatibility
    'SourceDocumentModel',
    'DocumentChunkModel',
    'EntityMentionModel',
    'CanonicalEntityModel',
    'RelationshipStagingModel',
]

# ================================================================================
# COMPATIBILITY ALIASES - For gradual migration
# ================================================================================

# These aliases allow existing code to work during migration
SourceDocumentModel = SourceDocumentMinimal
DocumentChunkModel = DocumentChunkMinimal
EntityMentionModel = EntityMentionMinimal
CanonicalEntityModel = CanonicalEntityMinimal
RelationshipStagingModel = RelationshipStagingMinimal

# Also provide shorter aliases
ChunkModel = DocumentChunkMinimal
ChunkModelMinimal = DocumentChunkMinimal
EntityMentionModelMinimal = EntityMentionMinimal
CanonicalEntityModelMinimal = CanonicalEntityMinimal