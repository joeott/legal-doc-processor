"""
Core processing modules and Pydantic models for the document pipeline.
"""

# Core modules
# ErrorHandler removed - deprecated file deleted

# Import models from consolidated location
from scripts.models import (
    # Enums
    ProcessingStatus,
    EntityType,
    
    # Database models (using aliases for compatibility)
    ProjectMinimal as ProjectModel,
    SourceDocumentMinimal as SourceDocumentModel,
    DocumentChunkMinimal as ChunkModel,
    EntityMentionMinimal as EntityMentionModel,
    CanonicalEntityMinimal as CanonicalEntityModel,
    RelationshipStagingMinimal as RelationshipStagingModel,
)

# Models that don't exist in consolidated file - create stubs
class BaseTimestampModel:
    pass

class RelationshipType:
    RELATED_TO = "RELATED_TO"

class Neo4jDocumentModel:
    pass

class TextractJobModel:
    pass

class ImportSessionModel:
    pass

class ChunkEmbeddingModel:
    pass

class CanonicalEntityEmbeddingModel:
    pass

class DocumentProcessingHistoryModel:
    pass

def create_model_from_db(*args, **kwargs):
    raise NotImplementedError("create_model_from_db is deprecated")

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

# Cache models - commented out to avoid circular import
# The cache_models.py file needs to be refactored to not import from schemas
# from .cache_models import (
#     # Base cache models
#     CacheStatus,
#     CacheMetadataModel,
#     BaseCacheModel,
#     
#     # Specific cache models
#     CachedProjectModel,
#     CachedProjectListModel,
#     CachedDocumentModel,
#     CachedChunkListModel,
#     CachedEntityResolutionModel,
#     CachedOCRResultModel,
#     CachedProcessingStatusModel,
#     CachedEmbeddingModel,
#     CachedSearchResultModel,
#     CachedBatchStatusModel,
#     
#     # Utility functions
#     create_cache_key,
#     get_cache_tags,
#     CacheInvalidationModel
# )

# Create stub classes for now
class CacheStatus:
    pass

class CacheMetadataModel:
    pass

class BaseCacheModel:
    pass

# Add other stubs as needed

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
    # Core modules removed - deprecated files deleted
    
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