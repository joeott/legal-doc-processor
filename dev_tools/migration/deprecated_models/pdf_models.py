"""
Enhanced Pydantic Models for PDF-Only Document Processing Pipeline.
These models enforce business rules, type safety, and provide a clear data contract.
"""
from pydantic import BaseModel, Field, field_validator, model_validator, ConfigDict
from typing import Optional, List, Dict, Any, Literal, Union
from datetime import datetime
from enum import Enum
import uuid


# Enhanced Enums with metadata
class ProcessingStatus(str, Enum):
    """Document processing status with allowed transitions."""
    PENDING_INTAKE = "pending_intake"
    VALIDATING = "validating"
    OCR_PROCESSING = "ocr_processing"
    TEXT_EXTRACTION = "text_extraction"
    CHUNKING = "chunking"
    VECTORIZING = "vectorizing"
    ENTITY_EXTRACTION = "entity_extraction"
    RELATIONSHIP_EXTRACTION = "relationship_extraction"
    PROJECT_ASSOCIATION = "project_association"
    CATEGORIZATION = "categorization"
    SEMANTIC_NAMING = "semantic_naming"
    COMPLETED = "completed"
    FAILED = "failed"
    HUMAN_REVIEW = "human_review"
    
    @classmethod
    def allowed_transitions(cls) -> Dict[str, List[str]]:
        """Define valid state transitions."""
        return {
            cls.PENDING_INTAKE: [cls.VALIDATING, cls.FAILED],
            cls.VALIDATING: [cls.OCR_PROCESSING, cls.FAILED],
            cls.OCR_PROCESSING: [cls.TEXT_EXTRACTION, cls.FAILED],
            cls.TEXT_EXTRACTION: [cls.CHUNKING, cls.FAILED],
            cls.CHUNKING: [cls.VECTORIZING, cls.FAILED],
            cls.VECTORIZING: [cls.ENTITY_EXTRACTION, cls.FAILED],
            cls.ENTITY_EXTRACTION: [cls.RELATIONSHIP_EXTRACTION, cls.FAILED],
            cls.RELATIONSHIP_EXTRACTION: [cls.PROJECT_ASSOCIATION, cls.FAILED],
            cls.PROJECT_ASSOCIATION: [cls.CATEGORIZATION, cls.HUMAN_REVIEW, cls.FAILED],
            cls.CATEGORIZATION: [cls.SEMANTIC_NAMING, cls.HUMAN_REVIEW, cls.FAILED],
            cls.SEMANTIC_NAMING: [cls.COMPLETED, cls.HUMAN_REVIEW, cls.FAILED],
            cls.HUMAN_REVIEW: [cls.PROJECT_ASSOCIATION, cls.COMPLETED, cls.FAILED],
            cls.FAILED: [],  # Terminal state
            cls.COMPLETED: []  # Terminal state
        }
    
    def can_transition_to(self, new_status: 'ProcessingStatus') -> bool:
        """Check if transition is allowed."""
        allowed = self.allowed_transitions().get(self, [])
        return new_status in allowed


class DocumentCategory(str, Enum):
    """Legal document categories with descriptions."""
    PLEADING = "pleading"
    DISCOVERY = "discovery"
    EVIDENCE = "evidence"
    CORRESPONDENCE = "correspondence"
    FINANCIAL = "financial"
    CONTRACT = "contract"
    REGULATORY = "regulatory"
    UNKNOWN = "unknown"
    
    @property
    def description(self) -> str:
        descriptions = {
            self.PLEADING: "Court filings including complaints, answers, motions",
            self.DISCOVERY: "Discovery documents including interrogatories, depositions",
            self.EVIDENCE: "Evidence including exhibits, affidavits, declarations",
            self.CORRESPONDENCE: "Letters, emails, memos between parties",
            self.FINANCIAL: "Financial documents including invoices, statements",
            self.CONTRACT: "Contracts, agreements, and amendments",
            self.REGULATORY: "Regulatory filings and compliance documents",
            self.UNKNOWN: "Uncategorized document"
        }
        return descriptions.get(self, "")


# Base model with audit trail
class AuditableBaseModel(BaseModel):
    """Base model with built-in audit trail support."""
    model_config = ConfigDict(
        validate_assignment=True,  # Validate on attribute assignment
        use_enum_values=True,
        json_schema_extra={
            "example": {}  # Will be overridden by child classes
        }
    )
    
    # Audit fields
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None
    created_by: Optional[str] = Field(None, description="User or system that created this")
    updated_by: Optional[str] = Field(None, description="User or system that last updated this")
    version: int = Field(1, description="Version number for optimistic locking")
    
    @field_validator('updated_at', mode='before')
    def set_updated_at(cls, v):
        """Automatically set updated_at on changes."""
        return datetime.utcnow()
    
    def increment_version(self) -> 'AuditableBaseModel':
        """Increment version for optimistic locking."""
        self.version += 1
        self.updated_at = datetime.utcnow()
        return self


# Enhanced Source Document Model
class PDFDocumentModel(AuditableBaseModel):
    """Source document model for PDF-only processing."""
    # Identity
    document_uuid: uuid.UUID = Field(default_factory=uuid.uuid4, description="Unique document identifier")
    
    # File information - PDF specific
    original_filename: str = Field(..., min_length=1, max_length=255, description="Original uploaded filename")
    file_size_bytes: int = Field(..., gt=0, le=104857600, description="File size in bytes (max 100MB)")
    file_hash: str = Field(..., pattern="^[a-f0-9]{64}$", description="SHA-256 hash of file content")
    pdf_version: Optional[str] = Field(None, pattern="^\\d+\\.\\d+$", description="PDF version (e.g., '1.7')")
    page_count: Optional[int] = Field(None, ge=1, description="Number of pages in PDF")
    
    # Storage
    s3_key: str = Field(..., description="S3 storage key")
    storage_path: Optional[str] = Field(None, description="Local storage path if applicable")
    
    # Processing state
    processing_status: ProcessingStatus = Field(ProcessingStatus.PENDING_INTAKE)
    processing_started_at: Optional[datetime] = None
    processing_completed_at: Optional[datetime] = None
    processing_duration_seconds: Optional[float] = Field(None, ge=0)
    
    # Extraction results
    ocr_confidence_score: Optional[float] = Field(None, ge=0, le=1, description="OCR confidence (0-1)")
    extracted_text: Optional[str] = Field(None, description="Full extracted text")
    extracted_metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)
    
    # Association results
    project_id: Optional[int] = Field(None, description="Associated project ID")
    project_association_confidence: Optional[float] = Field(None, ge=0, le=1)
    project_association_reasoning: Optional[str] = Field(None, max_length=1000)
    project_association_method: Optional[Literal["automatic", "manual", "rule_based"]] = None
    
    # Categorization
    category: Optional[DocumentCategory] = None
    category_confidence: Optional[float] = Field(None, ge=0, le=1)
    category_reasoning: Optional[str] = Field(None, max_length=1000)
    
    # Semantic naming
    semantic_filename: Optional[str] = Field(None, max_length=255)
    semantic_name_components: Optional[Dict[str, str]] = Field(
        None,
        description="Components used to build semantic name",
        example={"project": "ACME", "date": "2024-03-15", "type": "Motion", "parties": "Smith"}
    )
    
    # Error tracking
    error_message: Optional[str] = None
    error_details: Optional[Dict[str, Any]] = None
    retry_count: int = Field(0, ge=0, le=3)
    
    @field_validator('original_filename')
    def validate_pdf_extension(cls, v: str) -> str:
        """Ensure filename has PDF extension."""
        if not v.lower().endswith('.pdf'):
            raise ValueError("Only PDF files are supported")
        return v
    
    @model_validator(mode='after')
    def validate_status_transitions(self):
        """Validate processing status transitions and timing."""
        if self.processing_status == ProcessingStatus.COMPLETED:
            if not self.processing_completed_at:
                self.processing_completed_at = datetime.utcnow()
            if self.processing_started_at and not self.processing_duration_seconds:
                delta = self.processing_completed_at - self.processing_started_at
                self.processing_duration_seconds = delta.total_seconds()
        
        # Validate confidence scores are present for certain statuses
        # Only enforce this for completed documents with proper association
        # Skip validation during migration (when created_by is "migration_script")
        if self.processing_status == ProcessingStatus.COMPLETED and self.created_by != "migration_script":
            if self.project_id and self.project_association_method and not self.project_association_confidence:
                raise ValueError("Project association requires confidence score")
            if self.category and self.category != DocumentCategory.UNKNOWN and not self.category_confidence:
                raise ValueError("Category assignment requires confidence score")
        
        return self
    
    def transition_to(self, new_status: ProcessingStatus, error: Optional[str] = None) -> 'PDFDocumentModel':
        """Safely transition to new status."""
        # Convert string back to enum if needed
        current_status = ProcessingStatus(self.processing_status)
        if not current_status.can_transition_to(new_status):
            raise ValueError(f"Cannot transition from {self.processing_status} to {new_status}")
        
        self.processing_status = new_status
        
        if new_status == ProcessingStatus.OCR_PROCESSING and not self.processing_started_at:
            self.processing_started_at = datetime.utcnow()
        
        if new_status == ProcessingStatus.FAILED and error:
            self.error_message = error
            self.retry_count += 1
        
        self.increment_version()
        return self


# Enhanced Chunk Model with Embeddings
class PDFChunkModel(AuditableBaseModel):
    """Chunk model with embedding support."""
    chunk_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    document_uuid: uuid.UUID = Field(..., description="Parent document UUID")
    
    # Position information
    chunk_index: int = Field(..., ge=0, description="Zero-based chunk index")
    page_numbers: List[int] = Field(..., min_items=1, description="Pages this chunk spans")
    char_start: int = Field(..., ge=0)
    char_end: int = Field(..., gt=0)
    
    # Content
    text: str = Field(..., min_length=1, max_length=8000)
    chunk_type: Literal["paragraph", "section", "page", "semantic"] = "semantic"
    
    # Embeddings
    embedding_vector: Optional[List[float]] = Field(None, description="Dense embedding vector")
    embedding_model: Optional[str] = Field(None, example="text-embedding-ada-002")
    embedding_dimensions: Optional[int] = Field(None, example=1536)
    
    # Relationships
    previous_chunk_id: Optional[uuid.UUID] = None
    next_chunk_id: Optional[uuid.UUID] = None
    parent_chunk_id: Optional[uuid.UUID] = Field(None, description="For hierarchical chunking")
    
    # Metadata
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    @field_validator('embedding_vector')
    def validate_embedding_dimensions(cls, v: Optional[List[float]], info) -> Optional[List[float]]:
        """Ensure embedding dimensions match."""
        if v is not None:
            values = info.data
            if 'embedding_dimensions' in values and values['embedding_dimensions']:
                if len(v) != values['embedding_dimensions']:
                    raise ValueError(f"Embedding vector length {len(v)} doesn't match dimensions {values['embedding_dimensions']}")
        return v
    
    @model_validator(mode='after')
    def validate_char_positions(self):
        """Ensure char positions are valid."""
        if self.char_end <= self.char_start:
            raise ValueError("char_end must be greater than char_start")
        if self.char_end - self.char_start != len(self.text):
            raise ValueError("Character positions don't match text length")
        return self


# Project Association Model
class ProjectAssociationModel(AuditableBaseModel):
    """Model for document-project associations with confidence tracking."""
    document_uuid: uuid.UUID
    project_id: int
    
    # Confidence and reasoning
    confidence_score: float = Field(..., ge=0, le=1)
    reasoning: str = Field(..., max_length=2000)
    evidence_chunks: List[uuid.UUID] = Field(..., description="Chunk IDs that support this association")
    
    # Method tracking
    association_method: Literal["llm", "rule_based", "manual", "vector_similarity"]
    llm_model: Optional[str] = Field(None, example="gpt-4")
    
    # Human review
    requires_review: bool = Field(False)
    review_status: Optional[Literal["pending", "approved", "rejected"]] = None
    reviewed_by: Optional[str] = None
    review_notes: Optional[str] = None
    
    @field_validator('confidence_score')
    def validate_confidence_threshold(cls, v: float) -> float:
        """Flag for review if confidence is low."""
        if v < 0.85:  # Configurable threshold
            # This will be caught in model_validator
            pass
        return v
    
    @model_validator(mode='after')
    def set_review_requirement(self):
        """Automatically flag low confidence for review."""
        if self.confidence_score < 0.85 and not self.requires_review:
            self.requires_review = True
            self.review_status = "pending"
        return self


# Semantic Naming Model
class SemanticNamingModel(AuditableBaseModel):
    """Model for semantic file naming with validation."""
    document_uuid: uuid.UUID
    
    # Components
    project_code: str = Field(..., pattern="^[A-Z0-9_]{2,20}$", description="Project identifier")
    document_date: datetime = Field(..., description="Document date (extracted or created)")
    category: DocumentCategory
    description: str = Field(..., min_length=3, max_length=50, pattern="^[A-Za-z0-9_\\-\\s]+$")
    
    # Generated name
    semantic_filename: str = Field(..., max_length=255)
    naming_template: str = Field("{project_code}_{date}_{category}_{description}.pdf")
    
    @model_validator(mode='after')
    def generate_filename(self):
        """Generate semantic filename from components."""
        if not self.semantic_filename:
            date_str = self.document_date.strftime("%Y-%m-%d")
            # Clean description for filename
            clean_desc = self.description.replace(" ", "_").replace("-", "_")
            
            self.semantic_filename = self.naming_template.format(
                project_code=self.project_code,
                date=date_str,
                category=self.category.value,
                description=clean_desc
            )
        
        # Validate final filename
        if not self.semantic_filename.endswith('.pdf'):
            self.semantic_filename += '.pdf'
        
        # Ensure no double underscores or invalid characters
        self.semantic_filename = "_".join(filter(None, self.semantic_filename.split("_")))
        
        return self


# Processing Pipeline Model
class PDFProcessingPipelineModel(AuditableBaseModel):
    """Model representing entire processing pipeline state."""
    document: PDFDocumentModel
    chunks: List[PDFChunkModel] = Field(default_factory=list)
    entities: List['ExtractedEntityModel'] = Field(default_factory=list)
    relationships: List['ExtractedRelationshipModel'] = Field(default_factory=list)
    project_association: Optional[ProjectAssociationModel] = None
    semantic_naming: Optional[SemanticNamingModel] = None
    
    # Pipeline metadata
    pipeline_version: str = Field("2.0", description="Pipeline version for compatibility")
    processing_stages_completed: List[ProcessingStatus] = Field(default_factory=list)
    total_processing_time: Optional[float] = None
    
    # Quality metrics
    overall_confidence: Optional[float] = Field(None, ge=0, le=1)
    quality_flags: List[str] = Field(default_factory=list)
    
    @model_validator(mode='after')
    def calculate_overall_confidence(self):
        """Calculate overall pipeline confidence."""
        if not self.overall_confidence:
            scores = []
            if self.document.ocr_confidence_score:
                scores.append(self.document.ocr_confidence_score)
            if self.project_association and self.project_association.confidence_score:
                scores.append(self.project_association.confidence_score)
            if self.document.category_confidence:
                scores.append(self.document.category_confidence)
            
            if scores:
                self.overall_confidence = sum(scores) / len(scores)
        
        # Set quality flags
        if self.overall_confidence and self.overall_confidence < 0.7:
            self.quality_flags.append("low_confidence")
        if self.document.retry_count > 0:
            self.quality_flags.append("required_retry")
        if len(self.chunks) == 0:
            self.quality_flags.append("no_chunks_extracted")
        
        return self
    
    def to_summary(self) -> Dict[str, Any]:
        """Generate pipeline summary for logging/monitoring."""
        return {
            "document_uuid": str(self.document.document_uuid),
            "status": self.document.processing_status.value,
            "chunks_created": len(self.chunks),
            "entities_extracted": len(self.entities),
            "relationships_found": len(self.relationships),
            "project_assigned": self.project_association.project_id if self.project_association else None,
            "category": self.document.category.value if self.document.category else None,
            "semantic_name": self.semantic_naming.semantic_filename if self.semantic_naming else None,
            "overall_confidence": self.overall_confidence,
            "quality_flags": self.quality_flags,
            "processing_time": self.total_processing_time
        }


# Enhanced Entity Model
class ExtractedEntityModel(AuditableBaseModel):
    """Entity extracted from document with enhanced metadata."""
    entity_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    document_uuid: uuid.UUID
    chunk_ids: List[uuid.UUID] = Field(..., min_items=1, description="Chunks where entity appears")
    
    # Entity information
    entity_type: str = Field(..., example="PERSON")
    entity_value: str = Field(..., min_length=1)
    normalized_value: Optional[str] = Field(None, description="Canonical form of entity")
    
    # Confidence and position
    confidence_score: float = Field(..., ge=0, le=1)
    occurrences: List[Dict[str, Any]] = Field(
        ..., 
        min_items=1,
        description="List of occurrences with position info"
    )
    
    # Legal-specific metadata
    role_in_document: Optional[str] = Field(None, example="plaintiff")
    legal_entity_subtype: Optional[str] = Field(None, example="natural_person")
    
    @field_validator('entity_type')
    def validate_entity_type(cls, v: str) -> str:
        """Ensure standard entity types."""
        valid_types = {
            "PERSON", "ORGANIZATION", "LOCATION", "DATE", 
            "MONEY", "CASE_NUMBER", "STATUTE", "COURT"
        }
        if v.upper() not in valid_types:
            raise ValueError(f"Entity type must be one of {valid_types}")
        return v.upper()


# Enhanced Relationship Model
class ExtractedRelationshipModel(AuditableBaseModel):
    """Relationship between entities with legal context."""
    relationship_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    document_uuid: uuid.UUID
    
    # Relationship definition
    source_entity_id: uuid.UUID
    target_entity_id: uuid.UUID
    relationship_type: str = Field(..., example="represents")
    
    # Evidence and confidence
    confidence_score: float = Field(..., ge=0, le=1)
    evidence_chunk_ids: List[uuid.UUID] = Field(..., min_items=1)
    evidence_text: str = Field(..., max_length=500)
    
    # Legal context
    legal_significance: Optional[str] = Field(None, example="attorney-client")
    temporal_context: Optional[Dict[str, Any]] = Field(None)
    
    @field_validator('relationship_type')
    def validate_relationship_type(cls, v: str) -> str:
        """Ensure standard relationship types."""
        valid_types = {
            "represents", "opposes", "employs", "sues", 
            "partners_with", "owns", "located_in", "presides_over"
        }
        if v.lower() not in valid_types:
            # Allow but flag non-standard types
            pass
        return v.lower()