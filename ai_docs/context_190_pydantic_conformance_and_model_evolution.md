# Context 190: Pydantic Model Evolution for PDF-Only Pipeline

## Date: 2025-05-28
## Focus: Conforming Simplified Pipeline to Enhanced Pydantic Models with Downstream Foresight

### Executive Summary

This context refines the PDF-only simplification strategy by deeply considering how to evolve our Pydantic models to not only support the immediate changes but anticipate future needs. We'll enhance type safety, create clear data contracts, and build models that guide developers toward correct implementations while preventing common errors.

## Deep Analysis: Pydantic as the Architectural Foundation

### 1. Current Model Limitations and Opportunities

#### Existing Pain Points
1. **Loose Typing**: Many fields use `Optional[str]` when they could be more specific
2. **Validation Gaps**: Missing business logic validation (e.g., confidence scores should be 0-1)
3. **State Transitions**: No model-level enforcement of valid status progressions
4. **Relationship Integrity**: Models don't enforce referential integrity at the application layer
5. **Audit Trail**: No built-in change tracking in models

#### Opportunities for Enhancement
- Use Pydantic v2's advanced features (computed fields, model validators)
- Create model hierarchies that enforce business rules
- Build in audit trails and state management
- Design for extensibility without breaking changes

### 2. Enhanced Model Architecture

#### Core Design Principles
1. **Single Source of Truth**: Models define all validation rules
2. **Fail Fast**: Invalid data rejected at model boundaries
3. **Self-Documenting**: Field descriptions and examples built-in
4. **Evolution-Ready**: Designed for backward-compatible changes

#### Model Hierarchy for PDF-Only Processing

```python
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
    file_hash: str = Field(..., regex="^[a-f0-9]{64}$", description="SHA-256 hash of file content")
    pdf_version: Optional[str] = Field(None, regex="^\\d+\\.\\d+$", description="PDF version (e.g., '1.7')")
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
        if self.processing_status == ProcessingStatus.COMPLETED:
            if self.project_id and not self.project_association_confidence:
                raise ValueError("Project association requires confidence score")
            if self.category and not self.category_confidence:
                raise ValueError("Category assignment requires confidence score")
        
        return self
    
    def transition_to(self, new_status: ProcessingStatus, error: Optional[str] = None) -> 'PDFDocumentModel':
        """Safely transition to new status."""
        if not self.processing_status.can_transition_to(new_status):
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
    project_code: str = Field(..., regex="^[A-Z0-9_]{2,20}$", description="Project identifier")
    document_date: datetime = Field(..., description="Document date (extracted or created)")
    category: DocumentCategory
    description: str = Field(..., min_length=3, max_length=50, regex="^[A-Za-z0-9_\\-\\s]+$")
    
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


### 3. Migration Strategy for Existing Code

#### Phase 1: Model Migration Wrapper
```python
class ModelMigrationHelper:
    """Helper to migrate from old models to new PDF-only models."""
    
    @staticmethod
    def migrate_source_document(old_doc: Dict[str, Any]) -> PDFDocumentModel:
        """Migrate old source document to new model."""
        # Map old fields to new
        return PDFDocumentModel(
            document_uuid=old_doc.get('document_uuid'),
            original_filename=old_doc.get('filename', old_doc.get('original_file_name')),
            file_size_bytes=old_doc.get('file_size', 0),
            file_hash=old_doc.get('md5_hash', '0' * 64),  # Generate if missing
            s3_key=old_doc.get('s3_key'),
            processing_status=ProcessingStatus.PENDING_INTAKE,
            # Map old status to new
            created_at=old_doc.get('created_at', datetime.utcnow())
        )
    
    @staticmethod
    def validate_migration(old_data: List[Dict], new_models: List[BaseModel]) -> Dict[str, Any]:
        """Validate migration completeness."""
        return {
            "total_records": len(old_data),
            "successfully_migrated": len(new_models),
            "migration_errors": [],
            "data_loss_warnings": []
        }
```

#### Phase 2: Script Conformance Pattern
```python
# Standard pattern for all scripts
from scripts.core.schemas import PDFDocumentModel, PDFProcessingPipelineModel
from scripts.core.db_manager_v2 import DatabaseManagerV2

class PDFProcessor:
    """Base class for PDF processing with Pydantic models."""
    
    def __init__(self, db_manager: DatabaseManagerV2):
        self.db = db_manager
    
    async def process_document(self, file_path: str, original_name: str) -> PDFProcessingPipelineModel:
        """Process PDF with full model validation."""
        # Create document model
        doc = PDFDocumentModel(
            original_filename=original_name,
            file_size_bytes=os.path.getsize(file_path),
            file_hash=self._calculate_hash(file_path),
            s3_key=self._generate_s3_key()
        )
        
        # Initialize pipeline model
        pipeline = PDFProcessingPipelineModel(document=doc)
        
        try:
            # Each step updates the pipeline model
            pipeline = await self._extract_text(pipeline)
            pipeline = await self._chunk_document(pipeline)
            pipeline = await self._extract_entities(pipeline)
            pipeline = await self._associate_project(pipeline)
            pipeline = await self._generate_semantic_name(pipeline)
            
            # Final validation
            pipeline.document.transition_to(ProcessingStatus.COMPLETED)
            
        except Exception as e:
            pipeline.document.transition_to(ProcessingStatus.FAILED, str(e))
            raise
        
        return pipeline
```

### 4. Downstream Implications and Benefits

#### Immediate Benefits
1. **Type Safety**: Impossible to pass wrong data types
2. **Validation**: Business rules enforced at model level
3. **State Management**: Valid transitions enforced
4. **Audit Trail**: Built into every model
5. **Self-Documentation**: Models describe themselves

#### Long-term Advantages
1. **API Generation**: Models can auto-generate OpenAPI schemas
2. **Database Migrations**: Models can generate migration scripts
3. **Testing**: Models provide test data generation
4. **Monitoring**: Models include metrics collection
5. **Versioning**: Built-in version management

#### Code Quality Improvements
```python
# Before: Loose, error-prone
def process_doc(doc_data):
    if doc_data.get('status') == 'complete':  # String comparison
        conf = float(doc_data.get('confidence', 0))  # Manual conversion
        if conf > 0.8:  # Magic number
            # Process...

# After: Type-safe, validated
def process_doc(doc: PDFDocumentModel):
    if doc.processing_status == ProcessingStatus.COMPLETED:  # Enum comparison
        if doc.project_association_confidence > 0.85:  # Validated float
            # Process...
```

### 5. Testing Strategy with Enhanced Models

```python
import pytest
from scripts.core.schemas import PDFDocumentModel, ProcessingStatus

class TestPDFDocumentModel:
    """Test enhanced model validation."""
    
    def test_invalid_file_type_rejected(self):
        """Non-PDF files should be rejected."""
        with pytest.raises(ValueError, match="Only PDF files"):
            PDFDocumentModel(
                original_filename="document.docx",
                file_size_bytes=1000,
                file_hash="a" * 64,
                s3_key="test/doc.docx"
            )
    
    def test_status_transition_validation(self):
        """Invalid transitions should be rejected."""
        doc = PDFDocumentModel(
            original_filename="test.pdf",
            file_size_bytes=1000,
            file_hash="a" * 64,
            s3_key="test/doc.pdf"
        )
        
        # Valid transition
        doc.transition_to(ProcessingStatus.VALIDATING)
        
        # Invalid transition
        with pytest.raises(ValueError):
            doc.transition_to(ProcessingStatus.COMPLETED)
    
    def test_confidence_validation(self):
        """Confidence scores must be 0-1."""
        doc = PDFDocumentModel(
            original_filename="test.pdf",
            file_size_bytes=1000,
            file_hash="a" * 64,
            s3_key="test/doc.pdf"
        )
        
        # Valid
        doc.ocr_confidence_score = 0.95
        
        # Invalid
        with pytest.raises(ValueError):
            doc.ocr_confidence_score = 1.5
```

### 6. Configuration Integration

```python
from pydantic_settings import BaseSettings
from scripts.core.schemas import ProcessingStatus

class PipelineSettings(BaseSettings):
    """Pipeline configuration with model integration."""
    
    # Confidence thresholds
    min_ocr_confidence: float = 0.8
    min_project_association_confidence: float = 0.85
    min_category_confidence: float = 0.8
    
    # Retry settings
    max_retry_count: int = 3
    retry_delay_seconds: int = 60
    
    # Human review triggers
    auto_review_on_low_confidence: bool = True
    review_threshold_multiplier: float = 0.9
    
    # Status monitoring
    alert_on_statuses: List[ProcessingStatus] = [
        ProcessingStatus.FAILED,
        ProcessingStatus.HUMAN_REVIEW
    ]
    
    class Config:
        env_prefix = "PIPELINE_"
```

### 7. Database Integration with Models

```python
class PydanticSQLSync:
    """Sync Pydantic models with database schema."""
    
    @staticmethod
    def generate_migration(model: Type[BaseModel]) -> str:
        """Generate SQL migration from Pydantic model."""
        sql = []
        table_name = model.__name__.lower().replace("model", "s")
        
        sql.append(f"CREATE TABLE IF NOT EXISTS {table_name} (")
        
        for field_name, field_info in model.model_fields.items():
            sql_type = PydanticSQLSync._python_to_sql_type(field_info.annotation)
            nullable = "NULL" if field_info.is_required() else "NOT NULL"
            sql.append(f"    {field_name} {sql_type} {nullable},")
        
        sql.append(");")
        return "\n".join(sql)
```

### 8. Monitoring and Observability

```python
class ModelMetricsCollector:
    """Collect metrics from model operations."""
    
    def __init__(self):
        self.metrics = {
            "validation_failures": 0,
            "state_transitions": {},
            "confidence_distribution": []
        }
    
    def track_model_operation(self, model: BaseModel, operation: str):
        """Track model operations for monitoring."""
        if isinstance(model, PDFDocumentModel):
            self.metrics["confidence_distribution"].append({
                "timestamp": datetime.utcnow(),
                "document_uuid": str(model.document_uuid),
                "ocr_confidence": model.ocr_confidence_score,
                "project_confidence": model.project_association_confidence,
                "category_confidence": model.category_confidence
            })
```

## Conclusion

By deeply integrating Pydantic models into the PDF-only pipeline, we achieve:

1. **Robustness**: Invalid data cannot enter the system
2. **Clarity**: Models serve as living documentation
3. **Maintainability**: Changes require model updates, ensuring consistency
4. **Extensibility**: New features require new models, maintaining structure
5. **Observability**: Models provide natural monitoring points

The enhanced models anticipate future needs while solving immediate problems, creating a foundation that guides developers toward correct implementations while preventing common errors. This approach transforms Pydantic from a validation library into the architectural backbone of the entire system.