"""
Pydantic models for Celery task payloads and results.

These models ensure type safety for all Celery task inputs and outputs,
providing automatic validation and serialization for distributed processing.
All models are designed to be lightweight and JSON-serializable.
"""

import uuid
from datetime import datetime
from typing import List, Optional, Dict, Any, Union
from enum import Enum

from pydantic import BaseModel, Field, field_validator, ConfigDict


class TaskPriority(str, Enum):
    """Task priority levels"""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class TaskStatus(str, Enum):
    """Task execution status"""
    PENDING = "pending"
    STARTED = "started"
    RETRY = "retry"
    FAILURE = "failure"
    SUCCESS = "success"
    REVOKED = "revoked"


# Base Task Models
class BaseTaskPayload(BaseModel):
    """Base model for all task payloads"""
    task_id: Optional[str] = Field(None, description="Celery task ID")
    document_uuid: uuid.UUID = Field(..., description="Document being processed")
    priority: TaskPriority = Field(TaskPriority.NORMAL)
    retry_count: int = Field(0, ge=0)
    max_retries: int = Field(3, ge=0)
    timeout_seconds: Optional[int] = Field(None)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    model_config = ConfigDict(
        json_encoders={
            datetime: lambda v: v.isoformat(),
            uuid.UUID: lambda v: str(v)
        }
    )
    
    @field_validator('task_id', mode='before')
    @classmethod
    def ensure_task_id(cls, v):
        """Generate task ID if not provided"""
        if v is None:
            return str(uuid.uuid4())
        return v


class BaseTaskResult(BaseModel):
    """Base model for all task results"""
    task_id: str = Field(..., description="Celery task ID")
    document_uuid: uuid.UUID = Field(..., description="Document processed")
    status: TaskStatus = Field(TaskStatus.SUCCESS)
    started_at: datetime = Field(default_factory=datetime.now)
    completed_at: Optional[datetime] = Field(None)
    duration_seconds: Optional[float] = Field(None)
    error_message: Optional[str] = Field(None)
    retry_count: int = Field(0)
    result_data: Dict[str, Any] = Field(default_factory=dict)
    
    model_config = ConfigDict(
        json_encoders={
            datetime: lambda v: v.isoformat(),
            uuid.UUID: lambda v: str(v)
        }
    )
    
    @field_validator('completed_at')
    @classmethod
    def set_completion_time(cls, v, values):
        """Set completion time if status is final"""
        status = values.get('status')
        if status in [TaskStatus.SUCCESS, TaskStatus.FAILURE] and v is None:
            return datetime.now()
        return v
    
    @field_validator('duration_seconds')
    @classmethod
    def calculate_duration(cls, v, values):
        """Calculate duration if not provided"""
        if v is None and 'started_at' in values and 'completed_at' in values:
            started = values['started_at']
            completed = values.get('completed_at')
            if started and completed:
                return (completed - started).total_seconds()
        return v


# OCR Task Models
class OCRTaskPayload(BaseTaskPayload):
    """Payload for OCR processing tasks"""
    s3_bucket: str = Field(..., description="S3 bucket containing file")
    s3_key: str = Field(..., description="S3 key for file")
    file_type: str = Field(..., description="File type/extension")
    file_size_bytes: Optional[int] = Field(None)
    
    # OCR configuration
    ocr_provider: str = Field("textract", description="OCR provider to use")
    language: str = Field("en", description="Document language")
    enable_tables: bool = Field(True, description="Extract table data")
    enable_forms: bool = Field(True, description="Extract form data")
    
    # Processing options
    page_range: Optional[Dict[str, int]] = Field(None, description="Start/end pages")
    quality_threshold: float = Field(0.7, ge=0, le=1)
    
    @field_validator('ocr_provider')
    @classmethod
    def validate_provider(cls, v):
        """Validate OCR provider"""
        valid_providers = ["textract", "vision", "tesseract"]
        if v not in valid_providers:
            raise ValueError(f"OCR provider must be one of: {valid_providers}")
        return v


class OCRTaskResult(BaseTaskResult):
    """Result of OCR processing task"""
    ocr_provider: str = Field(...)
    total_pages: int = Field(0)
    extracted_text: str = Field("")
    confidence_score: float = Field(0.0, ge=0, le=1)
    
    # Provider-specific results
    textract_job_id: Optional[str] = Field(None)
    textract_warnings: List[str] = Field(default_factory=list)
    
    # Output locations
    output_s3_bucket: Optional[str] = Field(None)
    output_s3_key: Optional[str] = Field(None)
    
    # Processing stats
    pages_processed: int = Field(0)
    processing_time_per_page: Optional[float] = Field(None)


# Text Processing Task Models
class TextProcessingTaskPayload(BaseTaskPayload):
    """Payload for text processing tasks"""
    raw_text: str = Field(..., description="Raw text to process")
    processing_type: str = Field("chunking", description="Type of processing")
    
    # Chunking configuration
    chunk_size: int = Field(1000, ge=100, le=10000)
    chunk_overlap: int = Field(100, ge=0)
    chunking_strategy: str = Field("semantic", description="Chunking strategy")
    
    # Language processing
    language: str = Field("en")
    normalize_text: bool = Field(True)
    remove_headers_footers: bool = Field(True)
    
    @field_validator('processing_type')
    @classmethod
    def validate_processing_type(cls, v):
        """Validate processing type"""
        valid_types = ["chunking", "cleaning", "normalization", "extraction"]
        if v not in valid_types:
            raise ValueError(f"Processing type must be one of: {valid_types}")
        return v


class TextProcessingTaskResult(BaseTaskResult):
    """Result of text processing task"""
    processing_type: str = Field(...)
    input_length: int = Field(0)
    output_length: int = Field(0)
    
    # Chunking results
    chunks_created: int = Field(0)
    average_chunk_size: float = Field(0.0)
    
    # Processing stats
    text_quality_score: float = Field(0.0, ge=0, le=1)
    language_detected: str = Field("en")
    
    # Output data
    processed_chunks: List[Dict[str, Any]] = Field(default_factory=list)


# Entity Extraction Task Models
class EntityExtractionTaskPayload(BaseTaskPayload):
    """Payload for entity extraction tasks"""
    chunk_id: uuid.UUID = Field(..., description="Chunk to process")
    text: str = Field(..., description="Text content")
    chunk_index: int = Field(..., ge=0)
    
    # Extraction configuration
    entity_types: List[str] = Field(default_factory=list, description="Entity types to extract")
    model_name: str = Field("gpt-4", description="LLM model to use")
    confidence_threshold: float = Field(0.7, ge=0, le=1)
    
    # Context
    document_type: Optional[str] = Field(None)
    previous_entities: List[Dict[str, Any]] = Field(default_factory=list)
    
    @field_validator('entity_types', mode='before')
    @classmethod
    def set_default_entity_types(cls, v):
        """Set default entity types if empty"""
        if not v:
            return ["PERSON", "ORG", "LOCATION", "DATE", "MONEY", "CASE_NUMBER"]
        return v


class EntityExtractionTaskResult(BaseTaskResult):
    """Result of entity extraction task"""
    chunk_id: uuid.UUID = Field(...)
    chunk_index: int = Field(...)
    
    # Extraction results
    entities_found: int = Field(0)
    entity_types_found: List[str] = Field(default_factory=list)
    high_confidence_entities: int = Field(0)
    
    # LLM usage
    model_used: str = Field(...)
    prompt_tokens: Optional[int] = Field(None)
    completion_tokens: Optional[int] = Field(None)
    
    # Extracted entities
    entities: List[Dict[str, Any]] = Field(default_factory=list)


# Entity Resolution Task Models
class EntityResolutionTaskPayload(BaseTaskPayload):
    """Payload for entity resolution tasks"""
    entity_mentions: List[Dict[str, Any]] = Field(..., description="Entity mentions to resolve")
    resolution_strategy: str = Field("embedding", description="Resolution strategy")
    
    # Resolution configuration
    similarity_threshold: float = Field(0.8, ge=0, le=1)
    max_candidates: int = Field(10, ge=1)
    use_context: bool = Field(True)
    
    # Model configuration
    embedding_model: str = Field("text-embedding-3-small")
    clustering_algorithm: str = Field("hierarchical")


class EntityResolutionTaskResult(BaseTaskResult):
    """Result of entity resolution task"""
    mentions_processed: int = Field(0)
    canonical_entities_created: int = Field(0)
    resolution_rate: float = Field(0.0, ge=0, le=1)
    
    # Resolution results
    resolved_entities: List[Dict[str, Any]] = Field(default_factory=list)
    canonical_entities: List[Dict[str, Any]] = Field(default_factory=list)
    
    # Quality metrics
    average_confidence: float = Field(0.0, ge=0, le=1)
    clusters_formed: int = Field(0)


# Graph Building Task Models
class GraphBuildingTaskPayload(BaseTaskPayload):
    """Payload for graph building tasks"""
    entities: List[Dict[str, Any]] = Field(..., description="Entities to add to graph")
    chunks: List[Dict[str, Any]] = Field(..., description="Chunks to add to graph")
    
    # Graph configuration
    create_relationships: bool = Field(True)
    relationship_types: List[str] = Field(default_factory=list)
    max_relationship_distance: int = Field(3, ge=1)
    
    # Neo4j configuration
    batch_size: int = Field(100, ge=1, le=1000)
    use_transactions: bool = Field(True)


class GraphBuildingTaskResult(BaseTaskResult):
    """Result of graph building task"""
    nodes_created: int = Field(0)
    relationships_created: int = Field(0)
    
    # Node types
    document_nodes: int = Field(0)
    chunk_nodes: int = Field(0)
    entity_nodes: int = Field(0)
    
    # Relationship types
    containment_relationships: int = Field(0)
    entity_relationships: int = Field(0)
    sequence_relationships: int = Field(0)
    
    # Performance metrics
    neo4j_write_time: Optional[float] = Field(None)
    batch_operations: int = Field(0)


# Embedding Generation Task Models
class EmbeddingGenerationTaskPayload(BaseTaskPayload):
    """Payload for embedding generation tasks"""
    entity_type: str = Field(..., description="Type: chunk or entity")
    entity_id: uuid.UUID = Field(..., description="Entity UUID")
    text: str = Field(..., description="Text to embed")
    
    # Embedding configuration
    model_name: str = Field("text-embedding-3-small")
    model_version: Optional[str] = Field(None)
    dimensions: Optional[int] = Field(None)
    
    # Batch configuration
    batch_id: Optional[str] = Field(None)
    batch_size: Optional[int] = Field(None)
    
    @field_validator('entity_type')
    @classmethod
    def validate_entity_type(cls, v):
        """Validate entity type"""
        valid_types = ["chunk", "canonical_entity"]
        if v not in valid_types:
            raise ValueError(f"Entity type must be one of: {valid_types}")
        return v


class EmbeddingGenerationTaskResult(BaseTaskResult):
    """Result of embedding generation task"""
    entity_type: str = Field(...)
    entity_id: uuid.UUID = Field(...)
    
    # Embedding results
    embedding_dimensions: int = Field(0)
    model_used: str = Field(...)
    model_version: Optional[str] = Field(None)
    
    # API usage
    tokens_used: Optional[int] = Field(None)
    api_cost: Optional[float] = Field(None)
    
    # Generated embedding
    embedding: List[float] = Field(default_factory=list)
    
    @field_validator('embedding_dimensions')
    @classmethod
    def set_dimensions(cls, v, values):
        """Set dimensions from embedding length"""
        embedding = values.get('embedding', [])
        return len(embedding) if embedding else v


# Image Processing Task Models
class ImageProcessingTaskPayload(BaseTaskPayload):
    """Payload for image processing tasks"""
    image_s3_bucket: str = Field(..., description="S3 bucket for image")
    image_s3_key: str = Field(..., description="S3 key for image")
    image_type: str = Field(..., description="Image type/format")
    
    # Processing configuration
    extract_text: bool = Field(True)
    detect_objects: bool = Field(True)
    analyze_content: bool = Field(True)
    
    # Vision API configuration
    vision_provider: str = Field("openai", description="Vision API provider")
    max_tokens: int = Field(1000, ge=100)
    detail_level: str = Field("high", description="Image detail level")


class ImageProcessingTaskResult(BaseTaskResult):
    """Result of image processing task"""
    image_analyzed: bool = Field(False)
    vision_provider: str = Field(...)
    
    # Extraction results
    text_extracted: str = Field("")
    objects_detected: List[Dict[str, Any]] = Field(default_factory=list)
    image_description: str = Field("")
    
    # Quality metrics
    image_quality_score: float = Field(0.0, ge=0, le=1)
    text_confidence: float = Field(0.0, ge=0, le=1)
    
    # API usage
    tokens_used: Optional[int] = Field(None)
    api_cost: Optional[float] = Field(None)


# Audio Processing Task Models
class AudioProcessingTaskPayload(BaseTaskPayload):
    """Payload for audio/video processing tasks"""
    audio_s3_bucket: str = Field(..., description="S3 bucket for audio")
    audio_s3_key: str = Field(..., description="S3 key for audio")
    audio_format: str = Field(..., description="Audio format")
    
    # Transcription configuration
    language: str = Field("en")
    enable_speaker_diarization: bool = Field(False)
    enable_punctuation: bool = Field(True)
    
    # Whisper configuration
    model_size: str = Field("base", description="Whisper model size")
    temperature: float = Field(0.0, ge=0, le=1)


class AudioProcessingTaskResult(BaseTaskResult):
    """Result of audio processing task"""
    transcription_completed: bool = Field(False)
    audio_duration_seconds: float = Field(0.0)
    
    # Transcription results
    full_transcript: str = Field("")
    segments: List[Dict[str, Any]] = Field(default_factory=list)
    language_detected: str = Field("en")
    
    # Speaker diarization
    speakers_detected: int = Field(1)
    speaker_labels: List[str] = Field(default_factory=list)
    
    # Quality metrics
    transcription_confidence: float = Field(0.0, ge=0, le=1)
    audio_quality_score: float = Field(0.0, ge=0, le=1)


# Batch Processing Task Models
class BatchProcessingTaskPayload(BaseTaskPayload):
    """Payload for batch processing tasks"""
    batch_type: str = Field(..., description="Type of batch processing")
    item_ids: List[str] = Field(..., description="Items to process")
    batch_size: int = Field(10, ge=1, le=100)
    
    # Processing configuration
    parallel_workers: int = Field(1, ge=1, le=10)
    fail_fast: bool = Field(False)
    retry_failed: bool = Field(True)
    
    # Task-specific configuration
    task_config: Dict[str, Any] = Field(default_factory=dict)


class BatchProcessingTaskResult(BaseTaskResult):
    """Result of batch processing task"""
    batch_type: str = Field(...)
    total_items: int = Field(0)
    successful_items: int = Field(0)
    failed_items: int = Field(0)
    skipped_items: int = Field(0)
    
    # Processing results
    item_results: List[Dict[str, Any]] = Field(default_factory=list)
    error_summary: Dict[str, int] = Field(default_factory=dict)
    
    # Performance metrics
    items_per_second: float = Field(0.0)
    average_item_time: float = Field(0.0)
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate"""
        if self.total_items == 0:
            return 0.0
        return (self.successful_items / self.total_items) * 100


# Monitoring and Status Models
class TaskProgressUpdate(BaseModel):
    """Progress update for long-running tasks"""
    task_id: str = Field(...)
    document_uuid: uuid.UUID = Field(...)
    progress_percentage: float = Field(0.0, ge=0, le=100)
    current_step: str = Field(...)
    estimated_completion: Optional[datetime] = Field(None)
    message: Optional[str] = Field(None)
    
    model_config = ConfigDict(
        json_encoders={
            datetime: lambda v: v.isoformat(),
            uuid.UUID: lambda v: str(v)
        }
    )


class TaskHealthCheck(BaseModel):
    """Health check for task workers"""
    worker_id: str = Field(...)
    worker_type: str = Field(...)
    status: str = Field(...)
    active_tasks: int = Field(0)
    completed_tasks: int = Field(0)
    failed_tasks: int = Field(0)
    last_heartbeat: datetime = Field(default_factory=datetime.now)
    memory_usage_mb: Optional[float] = Field(None)
    cpu_usage_percent: Optional[float] = Field(None)
    
    model_config = ConfigDict(
        json_encoders={
            datetime: lambda v: v.isoformat()
        }
    )


# Task Queue Models
class TaskQueueStatus(BaseModel):
    """Status of task queues"""
    queue_name: str = Field(...)
    pending_tasks: int = Field(0)
    active_tasks: int = Field(0)
    failed_tasks: int = Field(0)
    completed_tasks: int = Field(0)
    average_wait_time: float = Field(0.0)
    average_processing_time: float = Field(0.0)
    last_updated: datetime = Field(default_factory=datetime.now)
    
    model_config = ConfigDict(
        json_encoders={
            datetime: lambda v: v.isoformat()
        }
    )


# Utility Functions
def create_task_payload(task_type: str, document_uuid: uuid.UUID, **kwargs) -> BaseTaskPayload:
    """Factory function to create task payloads"""
    payload_classes = {
        "ocr": OCRTaskPayload,
        "text_processing": TextProcessingTaskPayload,
        "entity_extraction": EntityExtractionTaskPayload,
        "entity_resolution": EntityResolutionTaskPayload,
        "graph_building": GraphBuildingTaskPayload,
        "embedding_generation": EmbeddingGenerationTaskPayload,
        "image_processing": ImageProcessingTaskPayload,
        "audio_processing": AudioProcessingTaskPayload,
        "batch_processing": BatchProcessingTaskPayload,
    }
    
    payload_class = payload_classes.get(task_type)
    if not payload_class:
        raise ValueError(f"Unknown task type: {task_type}")
    
    return payload_class(document_uuid=document_uuid, **kwargs)


def create_task_result(task_type: str, task_id: str, document_uuid: uuid.UUID, **kwargs) -> BaseTaskResult:
    """Factory function to create task results"""
    result_classes = {
        "ocr": OCRTaskResult,
        "text_processing": TextProcessingTaskResult,
        "entity_extraction": EntityExtractionTaskResult,
        "entity_resolution": EntityResolutionTaskResult,
        "graph_building": GraphBuildingTaskResult,
        "embedding_generation": EmbeddingGenerationTaskResult,
        "image_processing": ImageProcessingTaskResult,
        "audio_processing": AudioProcessingTaskResult,
        "batch_processing": BatchProcessingTaskResult,
    }
    
    result_class = result_classes.get(task_type)
    if not result_class:
        raise ValueError(f"Unknown task type: {task_type}")
    
    return result_class(task_id=task_id, document_uuid=document_uuid, **kwargs) 