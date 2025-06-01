"""
Core processing modules and Pydantic models for the document pipeline.
"""

# Core modules
from .error_handler import ErrorHandler

# Database schema models
from .schemas import (
    # Base models
    BaseTimestampModel,
    
    # Enums
    ProcessingStatus,
    EntityType,
    RelationshipType,
    
    # Database models
    ProjectModel,
    SourceDocumentModel,
    Neo4jDocumentModel,
    ChunkModel,
    EntityMentionModel,
    CanonicalEntityModel,
    RelationshipStagingModel,
    TextractJobModel,
    ImportSessionModel,
    ChunkEmbeddingModel,
    CanonicalEntityEmbeddingModel,
    DocumentProcessingHistoryModel,
    
    # Utility functions
    create_model_from_db
)

# Processing result models
from .processing_models import (
    # Base models
    BaseProcessingResult,
    
    # Enums
    ProcessingResultStatus,
    ConfidenceLevel,
    
    # OCR models
    OCRPageResult,
    OCRResultModel,
    
    # Image processing models
    DetectedObject,
    ImageAnalysisResult,
    ImageProcessingResultModel,
    
    # Audio processing models
    TranscriptionSegment,
    AudioTranscriptionResultModel,
    
    # Entity extraction models
    ExtractedEntity,
    EntityExtractionResultModel,
    
    # Chunking models
    ChunkMetadata,
    ProcessedChunk,
    ChunkingResultModel,
    
    # Embedding models
    EmbeddingResultModel,
    
    # Batch processing models
    BatchProcessingResultModel,
    
    # Structured extraction models
    DocumentMetadata,
    KeyFact,
    ExtractedRelationship,
    StructuredExtractionResultModel
)

# Cache models
from .cache_models import (
    # Base cache models
    CacheStatus,
    CacheMetadataModel,
    BaseCacheModel,
    
    # Specific cache models
    CachedProjectModel,
    CachedProjectListModel,
    CachedDocumentModel,
    CachedChunkListModel,
    CachedEntityResolutionModel,
    CachedOCRResultModel,
    CachedProcessingStatusModel,
    CachedEmbeddingModel,
    CachedSearchResultModel,
    CachedBatchStatusModel,
    
    # Utility functions
    create_cache_key,
    get_cache_tags,
    CacheInvalidationModel
)

# Task models
from .task_models import (
    # Base task models
    TaskPriority,
    TaskStatus,
    BaseTaskPayload,
    BaseTaskResult,
    
    # OCR task models
    OCRTaskPayload,
    OCRTaskResult,
    
    # Text processing task models
    TextProcessingTaskPayload,
    TextProcessingTaskResult,
    
    # Entity extraction task models
    EntityExtractionTaskPayload,
    EntityExtractionTaskResult,
    
    # Entity resolution task models
    EntityResolutionTaskPayload,
    EntityResolutionTaskResult,
    
    # Graph building task models
    GraphBuildingTaskPayload,
    GraphBuildingTaskResult,
    
    # Embedding generation task models
    EmbeddingGenerationTaskPayload,
    EmbeddingGenerationTaskResult,
    
    # Image processing task models
    ImageProcessingTaskPayload,
    ImageProcessingTaskResult,
    
    # Audio processing task models
    AudioProcessingTaskPayload,
    AudioProcessingTaskResult,
    
    # Batch processing task models
    BatchProcessingTaskPayload,
    BatchProcessingTaskResult,
    
    # Monitoring models
    TaskProgressUpdate,
    TaskHealthCheck,
    TaskQueueStatus,
    
    # Utility functions
    create_task_payload,
    create_task_result
)

# Migration helper - moved to database.py
# Keeping imports for compatibility
try:
    from scripts.database import (
        DatabaseMigrationHelper,
        ValidationResult,
        MigrationReport,
        validate_single_table,
        quick_validation_check
    )
except ImportError:
    # If not available, set to None
    DatabaseMigrationHelper = None
    ValidationResult = None
    MigrationReport = None
    validate_single_table = None
    quick_validation_check = None

__all__ = [
    # Core modules
    'ErrorHandler',
    
    # Base models
    'BaseTimestampModel',
    'BaseProcessingResult',
    'BaseCacheModel',
    'BaseTaskPayload',
    'BaseTaskResult',
    
    # Enums
    'ProcessingStatus',
    'EntityType',
    'RelationshipType',
    'ProcessingResultStatus',
    'ConfidenceLevel',
    'CacheStatus',
    'TaskPriority',
    'TaskStatus',
    
    # Database models
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
    
    # Processing result models
    'OCRPageResult',
    'OCRResultModel',
    'DetectedObject',
    'ImageAnalysisResult',
    'ImageProcessingResultModel',
    'TranscriptionSegment',
    'AudioTranscriptionResultModel',
    'ExtractedEntity',
    'EntityExtractionResultModel',
    'ChunkMetadata',
    'ProcessedChunk',
    'ChunkingResultModel',
    'EmbeddingResultModel',
    'BatchProcessingResultModel',
    'DocumentMetadata',
    'KeyFact',
    'ExtractedRelationship',
    'StructuredExtractionResultModel',
    
    # Cache models
    'CacheMetadataModel',
    'CachedProjectModel',
    'CachedProjectListModel',
    'CachedDocumentModel',
    'CachedChunkListModel',
    'CachedEntityResolutionModel',
    'CachedOCRResultModel',
    'CachedProcessingStatusModel',
    'CachedEmbeddingModel',
    'CachedSearchResultModel',
    'CachedBatchStatusModel',
    'CacheInvalidationModel',
    
    # Task models
    'OCRTaskPayload',
    'OCRTaskResult',
    'TextProcessingTaskPayload',
    'TextProcessingTaskResult',
    'EntityExtractionTaskPayload',
    'EntityExtractionTaskResult',
    'EntityResolutionTaskPayload',
    'EntityResolutionTaskResult',
    'GraphBuildingTaskPayload',
    'GraphBuildingTaskResult',
    'EmbeddingGenerationTaskPayload',
    'EmbeddingGenerationTaskResult',
    'ImageProcessingTaskPayload',
    'ImageProcessingTaskResult',
    'AudioProcessingTaskPayload',
    'AudioProcessingTaskResult',
    'BatchProcessingTaskPayload',
    'BatchProcessingTaskResult',
    'TaskProgressUpdate',
    'TaskHealthCheck',
    'TaskQueueStatus',
    
    # Utility functions
    'create_model_from_db',
    'create_cache_key',
    'get_cache_tags',
    'create_task_payload',
    'create_task_result',
    
    # Migration helper
    'DatabaseMigrationHelper',
    'ValidationResult',
    'MigrationReport',
    'validate_single_table',
    'quick_validation_check'
]