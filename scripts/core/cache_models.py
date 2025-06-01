"""
Pydantic models for Redis cache data structures.

These models ensure type safety and validation for all data stored in Redis,
providing automatic serialization/deserialization and cache metadata tracking.
All models are designed to be lightweight and optimized for caching.
"""

import uuid
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Union
from enum import Enum

from pydantic import BaseModel, Field, field_validator, ConfigDict, ValidationInfo

from .schemas import (
    SourceDocumentModel, 
    ProjectModel, 
    ChunkModel, 
    EntityMentionModel,
    CanonicalEntityModel
)
from .processing_models import (
    OCRResultModel,
    EntityExtractionResultModel,
    ChunkingResultModel
)


class CacheStatus(str, Enum):
    """Cache entry status"""
    VALID = "valid"
    EXPIRED = "expired"
    STALE = "stale"
    INVALID = "invalid"


class CacheMetadataModel(BaseModel):
    """Metadata for cached entries"""
    cache_key: str = Field(..., description="Redis cache key")
    cached_at: datetime = Field(default_factory=datetime.now)
    expires_at: Optional[datetime] = Field(None)
    ttl_seconds: Optional[int] = Field(None)
    version: str = Field("1.0", description="Cache schema version")
    source: str = Field(..., description="Source system/process")
    tags: List[str] = Field(default_factory=list, description="Cache tags for invalidation")
    hit_count: int = Field(0, description="Number of cache hits")
    last_accessed: datetime = Field(default_factory=datetime.now)
    
    model_config = ConfigDict(
        json_encoders={
            datetime: lambda v: v.isoformat(),
            uuid.UUID: lambda v: str(v)
        }
    )
    
    @field_validator('expires_at', mode='after')
    @classmethod
    def set_expiration(cls, v, info: ValidationInfo):
        """Set expiration time based on TTL"""
        if v is None and 'ttl_seconds' in info.data and info.data['ttl_seconds']:
            cached_at = info.data.get('cached_at', datetime.now())
            return cached_at + timedelta(seconds=info.data['ttl_seconds'])
        return v
    
    @property
    def is_expired(self) -> bool:
        """Check if cache entry is expired"""
        if self.expires_at is None:
            return False
        return datetime.now() > self.expires_at
    
    @property
    def status(self) -> CacheStatus:
        """Get current cache status"""
        if self.is_expired:
            return CacheStatus.EXPIRED
        return CacheStatus.VALID
    
    def update_access(self):
        """Update access tracking"""
        self.hit_count += 1
        self.last_accessed = datetime.now()


class BaseCacheModel(BaseModel):
    """Base model for all cached data"""
    metadata: CacheMetadataModel = Field(...)
    data_hash: Optional[str] = Field(None, description="Hash of cached data for validation")
    
    model_config = ConfigDict(
        json_encoders={
            datetime: lambda v: v.isoformat(),
            uuid.UUID: lambda v: str(v)
        }
    )
    
    def is_valid(self) -> bool:
        """Check if cached data is still valid"""
        return not self.metadata.is_expired


# Project Cache Models
class CachedProjectModel(BaseCacheModel):
    """Cached project data"""
    project: ProjectModel = Field(...)
    document_count: int = Field(0)
    last_activity: Optional[datetime] = Field(None)
    processing_stats: Dict[str, int] = Field(default_factory=dict)
    
    @classmethod
    def create(cls, project: ProjectModel, ttl_seconds: int = 3600):
        """Create cached project with metadata"""
        cache_key = f"project:{project.project_id}"
        metadata = CacheMetadataModel(
            cache_key=cache_key,
            ttl_seconds=ttl_seconds,
            source="supabase",
            tags=["project", str(project.project_id)]
        )
        return cls(metadata=metadata, project=project)


class CachedProjectListModel(BaseCacheModel):
    """Cached list of projects"""
    projects: List[ProjectModel] = Field(default_factory=list)
    total_count: int = Field(0)
    filter_criteria: Dict[str, Any] = Field(default_factory=dict)
    
    @classmethod
    def create(cls, projects: List[ProjectModel], filter_criteria: Dict = None, ttl_seconds: int = 1800):
        """Create cached project list"""
        cache_key = f"projects:list:{hash(str(filter_criteria or {}))}"
        metadata = CacheMetadataModel(
            cache_key=cache_key,
            ttl_seconds=ttl_seconds,
            source="supabase",
            tags=["projects", "list"]
        )
        return cls(
            metadata=metadata,
            projects=projects,
            total_count=len(projects),
            filter_criteria=filter_criteria or {}
        )


# Document Cache Models
class CachedDocumentModel(BaseCacheModel):
    """Cached source document data"""
    document: SourceDocumentModel = Field(...)
    chunks_count: int = Field(0)
    entities_count: int = Field(0)
    processing_progress: Dict[str, str] = Field(default_factory=dict)
    
    @classmethod
    def create(cls, document: SourceDocumentModel, ttl_seconds: int = 7200):
        """Create cached document with metadata"""
        cache_key = f"document:{document.document_uuid}"
        metadata = CacheMetadataModel(
            cache_key=cache_key,
            ttl_seconds=ttl_seconds,
            source="supabase",
            tags=["document", str(document.document_uuid)]
        )
        return cls(metadata=metadata, document=document)


# Chunk Cache Models
class CachedChunkListModel(BaseCacheModel):
    """Cached list of chunks for a document"""
    document_uuid: uuid.UUID = Field(...)
    chunks: List[ChunkModel] = Field(default_factory=list)
    total_chunks: int = Field(0)
    chunk_strategy: str = Field("semantic")
    
    @classmethod
    def create(cls, document_uuid: uuid.UUID, chunks: List[ChunkModel], strategy: str = "semantic", ttl_seconds: int = 3600):
        """Create cached chunk list"""
        cache_key = f"chunks:{document_uuid}:{strategy}"
        metadata = CacheMetadataModel(
            cache_key=cache_key,
            ttl_seconds=ttl_seconds,
            source="chunking_service",
            tags=["chunks", str(document_uuid), strategy]
        )
        return cls(
            metadata=metadata,
            document_uuid=document_uuid,
            chunks=chunks,
            total_chunks=len(chunks),
            chunk_strategy=strategy
        )


# Entity Cache Models
class CachedEntityResolutionModel(BaseCacheModel):
    """Cached entity resolution results"""
    document_uuid: uuid.UUID = Field(...)
    entity_mentions: List[EntityMentionModel] = Field(default_factory=list)
    canonical_entities: List[CanonicalEntityModel] = Field(default_factory=list)
    resolution_stats: Dict[str, int] = Field(default_factory=dict)
    model_version: str = Field("1.0")
    
    @classmethod
    def create(cls, document_uuid: uuid.UUID, mentions: List[EntityMentionModel], 
               canonical: List[CanonicalEntityModel], model_version: str = "1.0", ttl_seconds: int = 7200):
        """Create cached entity resolution"""
        cache_key = f"entities:{document_uuid}:{model_version}"
        metadata = CacheMetadataModel(
            cache_key=cache_key,
            ttl_seconds=ttl_seconds,
            source="entity_resolution",
            tags=["entities", str(document_uuid), model_version]
        )
        
        # Calculate resolution stats
        stats = {
            "total_mentions": len(mentions),
            "total_canonical": len(canonical),
            "resolved_mentions": len([m for m in mentions if m.resolved_canonical_id]),
            "entity_types": len(set(m.entity_type for m in mentions))
        }
        
        return cls(
            metadata=metadata,
            document_uuid=document_uuid,
            entity_mentions=mentions,
            canonical_entities=canonical,
            resolution_stats=stats,
            model_version=model_version
        )


# OCR Cache Models
class CachedOCRResultModel(BaseCacheModel):
    """Cached OCR processing results"""
    document_uuid: uuid.UUID = Field(...)
    ocr_result: OCRResultModel = Field(...)
    file_hash: str = Field(..., description="Hash of source file")
    ocr_provider: str = Field(...)
    
    @classmethod
    def create(cls, document_uuid: uuid.UUID, ocr_result: OCRResultModel, 
               file_hash: str, provider: str, ttl_seconds: int = 86400):  # 24 hours
        """Create cached OCR result"""
        cache_key = f"ocr:{document_uuid}:{provider}:{file_hash[:8]}"
        metadata = CacheMetadataModel(
            cache_key=cache_key,
            ttl_seconds=ttl_seconds,
            source=f"ocr_{provider}",
            tags=["ocr", str(document_uuid), provider]
        )
        return cls(
            metadata=metadata,
            document_uuid=document_uuid,
            ocr_result=ocr_result,
            file_hash=file_hash,
            ocr_provider=provider
        )


# Processing Cache Models
class CachedProcessingStatusModel(BaseCacheModel):
    """Cached processing status for documents"""
    document_uuid: uuid.UUID = Field(...)
    processing_stages: Dict[str, str] = Field(default_factory=dict)  # stage -> status
    current_stage: str = Field("pending")
    progress_percentage: float = Field(0.0, ge=0, le=100)
    estimated_completion: Optional[datetime] = Field(None)
    error_messages: List[str] = Field(default_factory=list)
    
    @classmethod
    def create(cls, document_uuid: uuid.UUID, stages: Dict[str, str], 
               current_stage: str = "pending", ttl_seconds: int = 1800):
        """Create cached processing status"""
        cache_key = f"processing:{document_uuid}"
        metadata = CacheMetadataModel(
            cache_key=cache_key,
            ttl_seconds=ttl_seconds,
            source="processing_pipeline",
            tags=["processing", str(document_uuid)]
        )
        
        # Calculate progress
        total_stages = len(stages)
        completed_stages = len([s for s in stages.values() if s == "completed"])
        progress = (completed_stages / total_stages * 100) if total_stages > 0 else 0
        
        return cls(
            metadata=metadata,
            document_uuid=document_uuid,
            processing_stages=stages,
            current_stage=current_stage,
            progress_percentage=progress
        )


# Embedding Cache Models
class CachedEmbeddingModel(BaseCacheModel):
    """Cached embedding vectors"""
    entity_id: uuid.UUID = Field(..., description="Chunk or entity UUID")
    entity_type: str = Field(..., description="chunk or canonical_entity")
    embedding: List[float] = Field(...)
    model_name: str = Field(...)
    model_version: Optional[str] = Field(None)
    text_hash: str = Field(..., description="Hash of source text")
    
    @classmethod
    def create(cls, entity_id: uuid.UUID, entity_type: str, embedding: List[float],
               model_name: str, text_hash: str, model_version: str = None, ttl_seconds: int = 604800):  # 7 days
        """Create cached embedding"""
        cache_key = f"embedding:{entity_type}:{entity_id}:{model_name}"
        metadata = CacheMetadataModel(
            cache_key=cache_key,
            ttl_seconds=ttl_seconds,
            source="embedding_service",
            tags=["embedding", entity_type, model_name]
        )
        return cls(
            metadata=metadata,
            entity_id=entity_id,
            entity_type=entity_type,
            embedding=embedding,
            model_name=model_name,
            model_version=model_version,
            text_hash=text_hash
        )


# Search Cache Models
class CachedSearchResultModel(BaseCacheModel):
    """Cached search results"""
    query_hash: str = Field(..., description="Hash of search query")
    query_text: str = Field(...)
    results: List[Dict[str, Any]] = Field(default_factory=list)
    total_results: int = Field(0)
    search_type: str = Field("semantic")  # semantic, keyword, hybrid
    filters_applied: Dict[str, Any] = Field(default_factory=dict)
    
    @classmethod
    def create(cls, query_text: str, results: List[Dict], search_type: str = "semantic",
               filters: Dict = None, ttl_seconds: int = 3600):
        """Create cached search results"""
        import hashlib
        query_hash = hashlib.md5(f"{query_text}:{search_type}:{filters}".encode()).hexdigest()
        cache_key = f"search:{search_type}:{query_hash}"
        
        metadata = CacheMetadataModel(
            cache_key=cache_key,
            ttl_seconds=ttl_seconds,
            source="search_service",
            tags=["search", search_type]
        )
        
        return cls(
            metadata=metadata,
            query_hash=query_hash,
            query_text=query_text,
            results=results,
            total_results=len(results),
            search_type=search_type,
            filters_applied=filters or {}
        )


# Batch Cache Models
class CachedBatchStatusModel(BaseCacheModel):
    """Cached batch processing status"""
    batch_id: str = Field(...)
    batch_type: str = Field(...)
    total_items: int = Field(...)
    processed_items: int = Field(0)
    failed_items: int = Field(0)
    current_item: Optional[str] = Field(None)
    estimated_completion: Optional[datetime] = Field(None)
    
    @classmethod
    def create(cls, batch_id: str, batch_type: str, total_items: int, ttl_seconds: int = 7200):
        """Create cached batch status"""
        cache_key = f"batch:{batch_type}:{batch_id}"
        metadata = CacheMetadataModel(
            cache_key=cache_key,
            ttl_seconds=ttl_seconds,
            source="batch_processor",
            tags=["batch", batch_type, batch_id]
        )
        return cls(
            metadata=metadata,
            batch_id=batch_id,
            batch_type=batch_type,
            total_items=total_items
        )
    
    @property
    def progress_percentage(self) -> float:
        """Calculate processing progress"""
        if self.total_items == 0:
            return 0.0
        return (self.processed_items / self.total_items) * 100


# Cache Utility Functions
def create_cache_key(prefix: str, *args) -> str:
    """Create standardized cache key"""
    parts = [prefix] + [str(arg) for arg in args]
    return ":".join(parts)


def get_cache_tags(model_type: str, entity_id: str = None, **kwargs) -> List[str]:
    """Generate cache tags for invalidation"""
    tags = [model_type]
    if entity_id:
        tags.append(entity_id)
    tags.extend(str(v) for v in kwargs.values())
    return tags


# Cache invalidation helpers
class CacheInvalidationModel(BaseModel):
    """Model for cache invalidation requests"""
    tags: List[str] = Field(..., description="Tags to invalidate")
    pattern: Optional[str] = Field(None, description="Key pattern to match")
    reason: str = Field(..., description="Reason for invalidation")
    requested_by: str = Field(..., description="System/user requesting invalidation")
    timestamp: datetime = Field(default_factory=datetime.now)
    
    model_config = ConfigDict(
        json_encoders={
            datetime: lambda v: v.isoformat()
        }
    ) 