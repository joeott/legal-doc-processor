"""
Pydantic models for processing results and intermediate data structures.

These models represent the outputs of various processing stages and ensure
type safety throughout the pipeline. They are designed to be serializable
for Redis caching and Celery task passing.
"""

import uuid
from datetime import datetime
from typing import List, Optional, Dict, Any, Union
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field, field_validator, ConfigDict


class ProcessingResultStatus(str, Enum):
    """Status of a processing result"""
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"


class ConfidenceLevel(str, Enum):
    """Confidence levels for extracted data"""
    HIGH = "high"       # > 0.9
    MEDIUM = "medium"   # 0.7 - 0.9
    LOW = "low"         # < 0.7


# Base Processing Model
class BaseProcessingResult(BaseModel):
    """Base model for all processing results"""
    document_uuid: uuid.UUID = Field(..., description="Source document UUID")
    processing_timestamp: datetime = Field(default_factory=datetime.now)
    status: ProcessingResultStatus = Field(ProcessingResultStatus.SUCCESS)
    error_message: Optional[str] = Field(None)
    processing_time_seconds: Optional[float] = Field(None)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    model_config = ConfigDict(
        json_encoders={
            datetime: lambda v: v.isoformat(),
            uuid.UUID: lambda v: str(v)
        }
    )


# OCR Result Models
class OCRPageResult(BaseModel):
    """Result for a single page of OCR"""
    page_number: int = Field(..., ge=1)
    text: str = Field(...)
    confidence: float = Field(..., ge=0, le=1)
    word_count: int = Field(0)
    line_count: int = Field(0)
    warnings: List[str] = Field(default_factory=list)
    
    @field_validator('confidence')
    @classmethod
    def set_confidence_level(cls, v):
        """Validate confidence is between 0 and 1"""
        return max(0.0, min(1.0, v))


class OCRResultModel(BaseProcessingResult):
    """Complete OCR result for a document"""
    provider: str = Field(..., description="OCR provider (textract, vision, tesseract)")
    total_pages: int = Field(1)
    pages: List[OCRPageResult] = Field(default_factory=list)
    full_text: str = Field("")
    average_confidence: float = Field(0.0)
    
    # Provider-specific metadata
    textract_job_id: Optional[str] = Field(None)
    textract_warnings: List[str] = Field(default_factory=list)
    
    # File metadata
    file_type: str = Field(...)
    file_size_bytes: Optional[int] = Field(None)
    
    @field_validator('average_confidence', mode='after')
    @classmethod
    def calculate_average_confidence(cls, v, info):
        """Calculate average confidence from pages"""
        if hasattr(info, 'data') and 'pages' in info.data:
            pages = info.data['pages']
            if pages:
                total_conf = sum(p.confidence for p in pages)
                return total_conf / len(pages)
        return v
    
    @field_validator('full_text', mode='after')
    @classmethod
    def combine_page_text(cls, v, info):
        """Combine text from all pages if not provided"""
        if not v and hasattr(info, 'data') and 'pages' in info.data:
            return '\n\n'.join(p.text for p in info.data['pages'])
        return v


# Image Processing Result Models
class DetectedObject(BaseModel):
    """Object detected in an image"""
    label: str = Field(...)
    confidence: float = Field(..., ge=0, le=1)
    bounding_box: Optional[Dict[str, float]] = Field(None)  # {x, y, width, height}


class ImageAnalysisResult(BaseModel):
    """Analysis result for a single image"""
    image_index: int = Field(0)
    image_type: str = Field(...)  # photo, diagram, chart, document, etc.
    description: str = Field("")
    extracted_text: Optional[str] = Field(None)
    detected_objects: List[DetectedObject] = Field(default_factory=list)
    detected_faces: int = Field(0)
    dominant_colors: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    
    # Quality metrics
    resolution: Optional[Dict[str, int]] = Field(None)  # {width, height}
    is_blurry: bool = Field(False)
    is_dark: bool = Field(False)


class ImageProcessingResultModel(BaseProcessingResult):
    """Complete image processing result"""
    provider: str = Field("openai_vision", description="Vision API provider")
    images_analyzed: int = Field(0)
    analyses: List[ImageAnalysisResult] = Field(default_factory=list)
    combined_text: str = Field("")
    overall_confidence: float = Field(0.0)
    
    # Extracted entities from images
    entities_detected: List[str] = Field(default_factory=list)
    key_information: Dict[str, Any] = Field(default_factory=dict)
    
    @field_validator('combined_text', mode='after')
    @classmethod
    def combine_extracted_text(cls, v, info):
        """Combine text from all image analyses"""
        if not v and hasattr(info, 'data') and 'analyses' in info.data:
            texts = [a.extracted_text for a in info.data['analyses'] if a.extracted_text]
            return '\n\n'.join(texts)
        return v


# Audio Transcription Result Models
class TranscriptionSegment(BaseModel):
    """A segment of transcribed audio"""
    start_time: float = Field(..., ge=0)
    end_time: float = Field(..., ge=0)
    text: str = Field(...)
    speaker: Optional[str] = Field(None)
    confidence: float = Field(1.0, ge=0, le=1)


class AudioTranscriptionResultModel(BaseProcessingResult):
    """Audio/video transcription result"""
    provider: str = Field("whisper", description="Transcription provider")
    duration_seconds: float = Field(..., ge=0)
    language: str = Field("en")
    segments: List[TranscriptionSegment] = Field(default_factory=list)
    full_transcript: str = Field("")
    
    # Audio metadata
    audio_format: str = Field(...)
    sample_rate: Optional[int] = Field(None)
    channels: Optional[int] = Field(None)
    
    # Speaker diarization
    speakers_detected: int = Field(1)
    speaker_labels: List[str] = Field(default_factory=list)
    
    @field_validator('full_transcript', mode='after')
    @classmethod
    def combine_segments(cls, v, info):
        """Combine transcript from segments"""
        if not v and hasattr(info, 'data') and 'segments' in info.data:
            return ' '.join(s.text for s in info.data['segments'])
        return v


# Entity Extraction Result Models
class ExtractedEntity(BaseModel):
    """A single extracted entity"""
    text: str = Field(..., description="Entity text")
    type: str = Field(..., description="Entity type")
    start_offset: Optional[int] = Field(None)
    end_offset: Optional[int] = Field(None)
    confidence: float = Field(1.0, ge=0, le=1)
    context: Optional[str] = Field(None, description="Surrounding context")
    attributes: Dict[str, Any] = Field(default_factory=dict)
    
    @property
    def confidence_level(self) -> ConfidenceLevel:
        """Get confidence level category"""
        if self.confidence > 0.9:
            return ConfidenceLevel.HIGH
        elif self.confidence > 0.7:
            return ConfidenceLevel.MEDIUM
        return ConfidenceLevel.LOW


class EntityExtractionResultModel(BaseProcessingResult):
    """Entity extraction result for a chunk or document"""
    chunk_id: Optional[uuid.UUID] = Field(None, description="Source chunk UUID")
    text_length: int = Field(0)
    entities: List[ExtractedEntity] = Field(default_factory=list)
    
    # Extraction metadata
    model_used: str = Field("gpt-4")
    prompt_tokens: Optional[int] = Field(None)
    completion_tokens: Optional[int] = Field(None)
    
    # Statistics
    total_entities: int = Field(0)
    entity_types_found: List[str] = Field(default_factory=list)
    high_confidence_count: int = Field(0)
    
    @field_validator('total_entities', mode='after')
    @classmethod
    def count_entities(cls, v, info):
        """Count total entities"""
        if hasattr(info, 'data') and 'entities' in info.data:
            return len(info.data['entities'])
        return v
    
    @field_validator('entity_types_found', mode='after')
    @classmethod
    def collect_entity_types(cls, v, info):
        """Collect unique entity types"""
        if hasattr(info, 'data') and 'entities' in info.data:
            return list(set(e.type for e in info.data['entities']))
        return v
    
    @field_validator('high_confidence_count', mode='after')
    @classmethod
    def count_high_confidence(cls, v, info):
        """Count high confidence entities"""
        if hasattr(info, 'data') and 'entities' in info.data:
            return sum(1 for e in info.data['entities'] if e.confidence > 0.9)
        return v


# Chunking Result Models
class ChunkMetadata(BaseModel):
    """Metadata for a text chunk"""
    section_title: Optional[str] = Field(None)
    section_number: Optional[str] = Field(None)
    page_numbers: List[int] = Field(default_factory=list)
    is_continuation: bool = Field(False)
    chunk_type: str = Field("paragraph")  # paragraph, list, table, etc.
    language: str = Field("en")


class ProcessedChunk(BaseModel):
    """A processed text chunk"""
    chunk_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    chunk_index: int = Field(...)
    text: str = Field(...)
    char_start: int = Field(...)
    char_end: int = Field(...)
    token_count: int = Field(0)
    metadata: ChunkMetadata = Field(default_factory=ChunkMetadata)
    
    # Links
    previous_chunk_id: Optional[uuid.UUID] = Field(None)
    next_chunk_id: Optional[uuid.UUID] = Field(None)
    
    @field_validator('token_count', mode='after')
    @classmethod
    def estimate_tokens(cls, v, info):
        """Estimate token count if not provided"""
        if v == 0 and hasattr(info, 'data') and 'text' in info.data:
            # Rough estimate: 1 token ≈ 4 characters
            return len(info.data['text']) // 4
        return v


class ChunkingResultModel(BaseProcessingResult):
    """Result of text chunking operation"""
    document_id: int = Field(..., description="Neo4j document SQL ID")
    chunks: List[ProcessedChunk] = Field(default_factory=list)
    total_chunks: int = Field(0)
    
    # Chunking strategy
    strategy: str = Field("semantic", description="Chunking strategy used")
    max_chunk_size: int = Field(1000)
    chunk_overlap: int = Field(100)
    
    # Statistics
    average_chunk_size: float = Field(0.0)
    total_characters: int = Field(0)
    chunks_with_entities: int = Field(0)
    
    @field_validator('total_chunks', mode='after')
    @classmethod
    def count_chunks(cls, v, info):
        """Count total chunks"""
        if hasattr(info, 'data') and 'chunks' in info.data:
            return len(info.data['chunks'])
        return v
    
    @field_validator('average_chunk_size', mode='after')
    @classmethod
    def calculate_average_size(cls, v, info):
        """Calculate average chunk size"""
        if hasattr(info, 'data') and 'chunks' in info.data and info.data['chunks']:
            total_size = sum(c.char_end - c.char_start for c in info.data['chunks'])
            return total_size / len(info.data['chunks'])
        return v


# Embedding Result Models
class EmbeddingResultModel(BaseProcessingResult):
    """Result of embedding generation"""
    entity_type: str = Field(..., description="Type: chunk or entity")
    entity_id: uuid.UUID = Field(..., description="UUID of embedded entity")
    embedding: List[float] = Field(...)
    model_name: str = Field("text-embedding-3-small")
    model_version: Optional[str] = Field(None)
    dimensions: int = Field(...)
    
    # Batch information
    batch_id: Optional[str] = Field(None)
    batch_size: Optional[int] = Field(None)
    
    @field_validator('dimensions', mode='after')
    @classmethod
    def set_dimensions(cls, v, info):
        """Set dimensions from embedding length"""
        if hasattr(info, 'data') and 'embedding' in info.data:
            return len(info.data['embedding'])
        return v
    
    @field_validator('embedding')
    @classmethod
    def validate_embedding(cls, v):
        """Validate embedding is normalized"""
        if v:
            # Check if embedding is roughly normalized (magnitude ≈ 1)
            magnitude = sum(x**2 for x in v) ** 0.5
            if abs(magnitude - 1.0) > 0.1:
                # Normalize if needed
                return [x / magnitude for x in v]
        return v


# Batch Processing Results
class BatchProcessingResultModel(BaseModel):
    """Result of batch processing multiple items"""
    batch_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    batch_type: str = Field(..., description="Type of batch processing")
    total_items: int = Field(...)
    successful_items: int = Field(0)
    failed_items: int = Field(0)
    skipped_items: int = Field(0)
    
    # Timing
    started_at: datetime = Field(default_factory=datetime.now)
    completed_at: Optional[datetime] = Field(None)
    total_duration_seconds: Optional[float] = Field(None)
    
    # Results
    results: List[Dict[str, Any]] = Field(default_factory=list)
    errors: List[Dict[str, Any]] = Field(default_factory=list)
    
    model_config = ConfigDict(
        json_encoders={
            datetime: lambda v: v.isoformat(),
            uuid.UUID: lambda v: str(v)
        }
    )
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate"""
        if self.total_items > 0:
            return self.successful_items / self.total_items
        return 0.0
    
    def add_result(self, item_id: str, status: str, data: Optional[Dict] = None, error: Optional[str] = None):
        """Add a result to the batch"""
        if status == "success":
            self.successful_items += 1
            self.results.append({"id": item_id, "status": status, "data": data})
        elif status == "failed":
            self.failed_items += 1
            self.errors.append({"id": item_id, "error": error})
        elif status == "skipped":
            self.skipped_items += 1
            self.results.append({"id": item_id, "status": status, "reason": error})


# Structured Extraction Models (replacing dataclasses)
class DocumentMetadata(BaseModel):
    """Structured document metadata"""
    document_type: str = Field(..., description="Type of document")
    title: Optional[str] = Field(None)
    date: Optional[datetime] = Field(None)
    parties: List[str] = Field(default_factory=list)
    case_number: Optional[str] = Field(None)
    court: Optional[str] = Field(None)
    jurisdiction: Optional[str] = Field(None)
    
    @field_validator('date', mode='before')
    @classmethod
    def parse_date(cls, v):
        """Parse date from various formats"""
        if isinstance(v, str):
            # Try common date formats
            from dateutil import parser
            try:
                return parser.parse(v)
            except:
                return None
        return v


class KeyFact(BaseModel):
    """A key fact extracted from document"""
    fact: str = Field(..., description="The fact statement")
    confidence: float = Field(1.0, ge=0, le=1)
    source_chunk_id: Optional[uuid.UUID] = Field(None)
    page_number: Optional[int] = Field(None)
    context: Optional[str] = Field(None, description="Surrounding context")
    fact_type: Optional[str] = Field(None)  # claim, finding, ruling, etc.


class EntitySet(BaseModel):
    """Set of entities extracted from a document chunk"""
    persons: List[str] = Field(default_factory=list, description="Person names")
    organizations: List[str] = Field(default_factory=list, description="Organization names")
    locations: List[str] = Field(default_factory=list, description="Location names")
    dates: List[str] = Field(default_factory=list, description="Date mentions")
    monetary_amounts: List[str] = Field(default_factory=list, description="Monetary amounts")
    legal_references: List[str] = Field(default_factory=list, description="Legal references")
    
    @property
    def total_entities(self) -> int:
        """Get total count of all entities"""
        return (len(self.persons) + len(self.organizations) + len(self.locations) + 
                len(self.dates) + len(self.monetary_amounts) + len(self.legal_references))
    
    @property
    def entity_types_present(self) -> List[str]:
        """Get list of entity types that have values"""
        types = []
        if self.persons: types.append("persons")
        if self.organizations: types.append("organizations")
        if self.locations: types.append("locations")
        if self.dates: types.append("dates")
        if self.monetary_amounts: types.append("monetary_amounts")
        if self.legal_references: types.append("legal_references")
        return types


class ExtractedRelationship(BaseModel):
    """A relationship between entities"""
    subject: str = Field(..., description="Subject entity")
    subject_type: str = Field(...)
    predicate: str = Field(..., description="Relationship type")
    object: str = Field(..., description="Object entity")
    object_type: str = Field(...)
    confidence: float = Field(1.0, ge=0, le=1)
    context: Optional[str] = Field(None)
    source_chunk_id: Optional[uuid.UUID] = Field(None)


class StructuredChunkData(BaseModel):
    """Complete structured data extracted from a document chunk"""
    document_metadata: DocumentMetadata = Field(..., description="Document-level metadata")
    key_facts: List[KeyFact] = Field(default_factory=list, description="Key facts extracted")
    entities: EntitySet = Field(default_factory=EntitySet, description="Entities extracted")
    relationships: List[ExtractedRelationship] = Field(default_factory=list, description="Relationships extracted")
    
    # Processing metadata
    extraction_timestamp: datetime = Field(default_factory=datetime.now)
    extraction_method: str = Field("llm", description="Method used for extraction")
    chunk_index: Optional[int] = Field(None, description="Index of source chunk")
    
    @property
    def has_content(self) -> bool:
        """Check if any structured content was extracted"""
        return (len(self.key_facts) > 0 or 
                self.entities.total_entities > 0 or 
                len(self.relationships) > 0)
    
    @property
    def extraction_summary(self) -> Dict[str, int]:
        """Get summary of extracted content"""
        return {
            "key_facts": len(self.key_facts),
            "total_entities": self.entities.total_entities,
            "relationships": len(self.relationships),
            "entity_types": len(self.entities.entity_types_present)
        }


class StructuredExtractionResultModel(BaseProcessingResult):
    """Result model for structured extraction operations"""
    chunk_id: Optional[uuid.UUID] = Field(None, description="Source chunk UUID")
    structured_data: Optional[StructuredChunkData] = Field(None, description="Extracted structured data")
    extraction_method: str = Field("llm", description="Method used for extraction")
    confidence_scores: Dict[str, float] = Field(default_factory=dict)
    
    # Aggregated fields for easy access
    entities: List[ExtractedEntity] = Field(default_factory=list, description="All extracted entities")
    key_facts: List[KeyFact] = Field(default_factory=list, description="All key facts")
    relationships: List[ExtractedRelationship] = Field(default_factory=list, description="All relationships")
    metadata: DocumentMetadata = Field(default_factory=lambda: DocumentMetadata(document_type="Unknown"))
    
    @property
    def has_structured_data(self) -> bool:
        """Check if structured data was extracted"""
        return self.structured_data is not None and self.structured_data.has_content
    
    @property
    def extraction_completeness(self) -> float:
        """Calculate extraction completeness score (0.0 to 1.0)"""
        if not self.structured_data:
            return 0.0
        
        # Score based on presence of different types of content
        score = 0.0
        if self.structured_data.key_facts:
            score += 0.3
        if self.structured_data.entities.total_entities > 0:
            score += 0.4
        if self.structured_data.relationships:
            score += 0.2
        if self.structured_data.document_metadata.document_type != "Unknown":
            score += 0.1
        
        return min(1.0, score)


# Entity Resolution Models
class CanonicalEntity(BaseModel):
    """A canonical entity representing a resolved entity cluster"""
    name: str = Field(..., description="Canonical name of the entity")
    entity_type: str = Field(..., description="Type of entity")
    aliases: List[str] = Field(default_factory=list, description="All known aliases")
    mention_count: int = Field(0, description="Number of mentions resolved to this entity")
    first_seen_chunk_index: int = Field(0, description="Index of first chunk where entity was seen")
    confidence: float = Field(1.0, ge=0, le=1, description="Confidence in resolution")
    attributes: Dict[str, Any] = Field(default_factory=dict, description="Additional entity attributes")
    
    @property
    def confidence_level(self) -> ConfidenceLevel:
        """Get confidence level category"""
        if self.confidence > 0.9:
            return ConfidenceLevel.HIGH
        elif self.confidence > 0.7:
            return ConfidenceLevel.MEDIUM
        return ConfidenceLevel.LOW


class EntityResolutionResultModel(BaseProcessingResult):
    """Result model for entity resolution operations"""
    total_mentions: int = Field(0, description="Total number of entity mentions processed")
    total_canonical_entities: int = Field(0, description="Number of canonical entities created")
    canonical_entities: List[CanonicalEntity] = Field(default_factory=list)
    updated_mentions: List[Dict[str, Any]] = Field(default_factory=list, description="Mentions with canonical entity references")
    model_used: str = Field("unknown", description="Model used for resolution")
    
    @property
    def resolution_ratio(self) -> float:
        """Calculate the resolution ratio (mentions per canonical entity)"""
        if self.total_canonical_entities == 0:
            return 0.0
        return self.total_mentions / self.total_canonical_entities


# Relationship Building Models
class StagedRelationship(BaseModel):
    """A staged relationship ready for Neo4j import"""
    from_node_id: str = Field(..., description="Source node ID")
    from_node_label: str = Field(..., description="Source node label")
    to_node_id: str = Field(..., description="Target node ID")
    to_node_label: str = Field(..., description="Target node label")
    relationship_type: str = Field(..., description="Type of relationship")
    properties: Dict[str, Any] = Field(default_factory=dict, description="Relationship properties")
    staging_id: str = Field(..., description="Staging table ID")
    
    @property
    def relationship_signature(self) -> str:
        """Get a unique signature for this relationship"""
        return f"{self.from_node_label}({self.from_node_id})-[{self.relationship_type}]->{self.to_node_label}({self.to_node_id})"


class RelationshipBuildingResultModel(BaseProcessingResult):
    """Result model for relationship building operations"""
    total_relationships: int = Field(0, description="Total number of relationships staged")
    staged_relationships: List[StagedRelationship] = Field(default_factory=list)
    
    @property
    def relationship_types(self) -> Dict[str, int]:
        """Get count of relationships by type"""
        type_counts = {}
        for rel in self.staged_relationships:
            type_counts[rel.relationship_type] = type_counts.get(rel.relationship_type, 0) + 1
        return type_counts


# Import Operation Models
class ImportMetadataModel(BaseModel):
    """Model for import manifest metadata"""
    case_name: str = Field(..., description="Case name for the import")
    base_path: str = Field(..., description="Base path for file resolution")
    created_at: datetime = Field(default_factory=datetime.now, description="Manifest creation time")
    description: Optional[str] = Field(None, description="Import description")
    client_name: Optional[str] = Field(None, description="Client name")
    matter_number: Optional[str] = Field(None, description="Matter number")
    
    @field_validator('base_path')
    @classmethod
    def validate_base_path(cls, v):
        """Validate base path exists"""
        path = Path(v)
        if not path.exists():
            raise ValueError(f"Base path does not exist: {v}")
        return str(path.absolute())

class ImportFileModel(BaseModel):
    """Model for individual file in import manifest"""
    name: str = Field(..., description="File name")
    path: str = Field(..., description="Relative path from base_path")
    size: Optional[int] = Field(None, description="File size in bytes")
    detected_type: str = Field(..., description="Detected file type")
    mime_type: str = Field(..., description="MIME type")
    folder_category: str = Field("documents", description="Folder category")
    file_hash: Optional[str] = Field(None, description="File hash for deduplication")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional file metadata")
    
    @field_validator('detected_type')
    @classmethod
    def validate_file_type(cls, v):
        """Validate supported file types"""
        supported_types = ['pdf', 'doc', 'docx', 'txt', 'jpg', 'jpeg', 'png', 'tiff', 'tif']
        if v.lower() not in supported_types:
            raise ValueError(f"Unsupported file type: {v}")
        return v.lower()

class ImportConfigModel(BaseModel):
    """Model for import configuration"""
    processing_order: List[str] = Field(default=["documents"], description="Processing order by category")
    batch_size: int = Field(50, description="Batch size for processing")
    max_workers: int = Field(4, description="Maximum concurrent workers")
    retry_attempts: int = Field(3, description="Retry attempts for failed files")
    delay_between_batches: float = Field(0.1, description="Delay between batch submissions")
    
    @field_validator('batch_size')
    @classmethod
    def validate_batch_size(cls, v):
        """Validate batch size is reasonable"""
        if v < 1 or v > 1000:
            raise ValueError("Batch size must be between 1 and 1000")
        return v

class ImportManifestModel(BaseModel):
    """Model for complete import manifest"""
    metadata: ImportMetadataModel = Field(..., description="Import metadata")
    files: List[ImportFileModel] = Field(..., description="List of files to import")
    import_config: ImportConfigModel = Field(default_factory=ImportConfigModel, description="Import configuration")
    
    @field_validator('files')
    @classmethod
    def validate_files_not_empty(cls, v):
        """Ensure files list is not empty"""
        if not v:
            raise ValueError("Files list cannot be empty")
        return v
    
    @property
    def total_size(self) -> int:
        """Calculate total size of all files"""
        return sum(f.size or 0 for f in self.files)
    
    @property
    def file_types_summary(self) -> Dict[str, int]:
        """Get summary of file types"""
        from collections import Counter
        return dict(Counter(f.detected_type for f in self.files))

class ImportValidationResultModel(BaseModel):
    """Model for import validation results"""
    is_valid: bool = Field(..., description="Whether validation passed")
    manifest: Optional[ImportManifestModel] = Field(None, description="Validated manifest")
    validation_errors: List[str] = Field(default_factory=list, description="Validation errors")
    validation_warnings: List[str] = Field(default_factory=list, description="Validation warnings")
    total_files: int = Field(0, description="Total number of files")
    total_size: int = Field(0, description="Total size in bytes")
    estimated_cost: float = Field(0.0, description="Estimated processing cost")
    
    @property
    def has_warnings(self) -> bool:
        """Check if there are validation warnings"""
        return len(self.validation_warnings) > 0
    
    @property
    def error_summary(self) -> str:
        """Get summary of validation errors"""
        if not self.validation_errors:
            return "No errors"
        return f"{len(self.validation_errors)} errors: {'; '.join(self.validation_errors[:3])}"

class ImportProgressModel(BaseModel):
    """Model for tracking import progress"""
    session_id: int = Field(..., description="Import session ID")
    total_files: int = Field(..., description="Total files to import")
    processed_files: int = Field(0, description="Files processed")
    successful_files: int = Field(0, description="Files successfully imported")
    failed_files: int = Field(0, description="Files that failed")
    current_batch: int = Field(1, description="Current batch number")
    total_batches: int = Field(1, description="Total number of batches")
    started_at: datetime = Field(default_factory=datetime.now, description="Import start time")
    estimated_completion: Optional[datetime] = Field(None, description="Estimated completion time")
    
    @property
    def progress_percentage(self) -> float:
        """Calculate progress percentage"""
        if self.total_files == 0:
            return 0.0
        return (self.processed_files / self.total_files) * 100
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate"""
        if self.processed_files == 0:
            return 0.0
        return (self.successful_files / self.processed_files) * 100
    
    @property
    def is_complete(self) -> bool:
        """Check if import is complete"""
        return self.processed_files >= self.total_files

class ImportResultModel(BaseModel):
    """Model for individual import result"""
    file_name: str = Field(..., description="Name of the imported file")
    document_uuid: Optional[str] = Field(None, description="Generated document UUID")
    success: bool = Field(..., description="Whether import was successful")
    error_message: Optional[str] = Field(None, description="Error message if failed")
    processing_time: Optional[float] = Field(None, description="Processing time in seconds")
    file_size: Optional[int] = Field(None, description="File size in bytes")
    s3_key: Optional[str] = Field(None, description="S3 storage key")
    task_id: Optional[str] = Field(None, description="Celery task ID")
    
    @property
    def status(self) -> str:
        """Get status string"""
        return "success" if self.success else "failed"

class ImportSummaryModel(BaseModel):
    """Model for import session summary"""
    session_id: int = Field(..., description="Import session ID")
    session_name: str = Field(..., description="Import session name")
    total_files: int = Field(..., description="Total files in import")
    successful_imports: int = Field(..., description="Number of successful imports")
    failed_imports: int = Field(..., description="Number of failed imports")
    total_size: int = Field(..., description="Total size of all files")
    processing_time: float = Field(..., description="Total processing time")
    estimated_cost: float = Field(..., description="Estimated processing cost")
    started_at: datetime = Field(..., description="Import start time")
    completed_at: Optional[datetime] = Field(None, description="Import completion time")
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate percentage"""
        if self.total_files == 0:
            return 0.0
        return (self.successful_imports / self.total_files) * 100
    
    @property
    def average_file_size(self) -> float:
        """Calculate average file size in MB"""
        if self.total_files == 0:
            return 0.0
        return (self.total_size / self.total_files) / (1024 * 1024)
    
    @property
    def throughput(self) -> float:
        """Calculate files per minute"""
        if self.processing_time == 0:
            return 0.0
        return (self.total_files / self.processing_time) * 60

# Export all models
__all__ = [
    # Enums
    'ProcessingResultStatus',
    'ConfidenceLevel',
    
    # Base
    'BaseProcessingResult',
    
    # OCR
    'OCRPageResult',
    'OCRResultModel',
    
    # Images
    'DetectedObject',
    'ImageAnalysisResult',
    'ImageProcessingResultModel',
    
    # Audio
    'TranscriptionSegment',
    'AudioTranscriptionResultModel',
    
    # Entities
    'ExtractedEntity',
    'EntityExtractionResultModel',
    
    # Chunking
    'ChunkMetadata',
    'ProcessedChunk',
    'ChunkingResultModel',
    
    # Embeddings
    'EmbeddingResultModel',
    
    # Batch
    'BatchProcessingResultModel',
    
    # Structured
    'DocumentMetadata',
    'KeyFact',
    'EntitySet',
    'ExtractedRelationship',
    'StructuredChunkData',
    'StructuredExtractionResultModel',
    
    # Entity Resolution
    'CanonicalEntity',
    'EntityResolutionResultModel',
    
    # Relationship Building
    'StagedRelationship',
    'RelationshipBuildingResultModel',
    
    # Import
    'ImportMetadataModel',
    'ImportFileModel',
    'ImportConfigModel',
    'ImportManifestModel',
    'ImportValidationResultModel',
    'ImportProgressModel',
    'ImportResultModel',
    'ImportSummaryModel'
]