# cache_keys.py
"""Centralized cache key definitions for Redis optimization."""

from typing import Dict, Any


class CacheKeys:
    """Centralized cache key definitions and templates."""
    
    # Document processing keys
    DOC_STATE = "doc:state:{document_uuid}"
    DOC_OCR_RESULT = "doc:ocr:{document_uuid}"
    DOC_ENTITIES = "doc:entities:{document_uuid}:{chunk_id}"
    DOC_STRUCTURED = "doc:structured:{document_uuid}:{chunk_id}"
    DOC_CHUNKS = "doc:chunks:{document_uuid}"
    DOC_PROCESSING_LOCK = "doc:lock:{document_uuid}"
    
    # New cache keys for enhanced Redis optimization (from context_117)
    DOC_CHUNKS_LIST = "doc:chunks_list:{document_uuid}"  # List of chunk UUIDs/IDs
    DOC_CHUNK_TEXT = "doc:chunk_text:{chunk_uuid}"  # Raw text of a specific chunk
    DOC_ALL_EXTRACTED_MENTIONS = "doc:all_mentions:{document_uuid}"  # All entity mentions for document
    DOC_CANONICAL_ENTITIES = "doc:canonical_entities:{document_uuid}"  # Resolved canonical entities
    DOC_RESOLVED_MENTIONS = "doc:resolved_mentions:{document_uuid}"  # Entity mentions with resolved IDs
    DOC_CLEANED_TEXT = "doc:cleaned_text:{document_uuid}"  # Cleaned document text
    
    # Vector embedding cache keys (from context_130)
    EMB_CHUNK = "emb:chunk:{chunk_id}:v{version}"  # Individual chunk embedding
    EMB_DOC_CHUNKS = "emb:doc:{document_uuid}:chunks:v{version}"  # Set of chunk IDs with embeddings
    EMB_DOC_MEAN = "emb:doc:{document_uuid}:mean:v{version}"  # Document-level mean embedding
    EMB_SIMILARITY_CACHE = "emb:sim:{chunk_id1}:{chunk_id2}"  # Cached similarity scores
    EMB_ENTITY_VECTOR = "emb:entity:{entity_id}:v{version}"  # Entity embedding for resolution
    
    # Job tracking keys
    TEXTRACT_JOB_STATUS = "job:textract:status:{job_id}"
    TEXTRACT_JOB_RESULT = "job:textract:result:{document_uuid}"
    TEXTRACT_JOB_LOCK = "job:textract:lock:{job_id}"
    
    # Queue management keys
    QUEUE_LOCK = "queue:lock:{queue_id}"
    QUEUE_PROCESSOR = "queue:processor:{processor_id}"
    QUEUE_BATCH_LOCK = "queue:batch:lock:{batch_id}"
    
    # Rate limiting keys
    RATE_LIMIT_OPENAI = "rate:openai:{function_name}"
    RATE_LIMIT_TEXTRACT = "rate:textract:{operation}"
    RATE_LIMIT_MISTRAL = "rate:mistral:{endpoint}"
    RATE_LIMIT_GLOBAL = "rate:global:{service}"
    
    # Idempotency keys
    IDEMPOTENT_OCR = "idempotent:ocr:{document_uuid}"
    IDEMPOTENT_ENTITY = "idempotent:entity:{chunk_hash}"
    IDEMPOTENT_STRUCTURED = "idempotent:structured:{chunk_hash}"
    IDEMPOTENT_RESOLUTION = "idempotent:resolution:{entity_hash}"
    
    # Cache metrics keys
    CACHE_METRICS_HIT = "metrics:cache:hit:{cache_type}"
    CACHE_METRICS_MISS = "metrics:cache:miss:{cache_type}"
    CACHE_METRICS_TOTAL = "metrics:cache:total"
    
    # Worker coordination keys
    WORKER_REGISTRY = "workers:registry"
    WORKER_HEARTBEAT = "workers:heartbeat:{worker_id}"
    WORKER_TASKS = "workers:tasks:{worker_id}"
    
    # Stream keys (for future Redis Streams implementation)
    STREAM_OCR_PENDING = "stream:ocr:pending"
    STREAM_CLEAN_CAT_PENDING = "stream:clean-cat:pending"
    STREAM_CHUNK_PENDING = "stream:chunking:pending"
    STREAM_NER_PENDING = "stream:ner:pending"
    STREAM_RESOLUTION_PENDING = "stream:resolution:pending"
    STREAM_RELATIONSHIPS_PENDING = "stream:relationships:pending"
    STREAM_PROCESSING_COMPLETED = "stream:processing:completed"
    
    # Dead letter queue keys
    DLQ_OCR = "dlq:ocr"
    DLQ_ENTITY_EXTRACTION = "dlq:entity-extraction"
    DLQ_TEXTRACT = "dlq:textract"
    
    # Performance tracking keys
    PERF_OCR_TIME = "perf:ocr:time:{document_uuid}"
    PERF_ENTITY_TIME = "perf:entity:time:{document_uuid}"
    PERF_TOTAL_TIME = "perf:total:time:{document_uuid}"
    
    @staticmethod
    def format_key(template: str, version: int = None, **kwargs) -> str:
        """
        Format a cache key template with parameters and optional version.
        
        Args:
            template: Key template with placeholders
            version: Optional processing version number
            **kwargs: Key-value pairs to substitute
            
        Returns:
            Formatted cache key with optional version suffix
            
        Example:
            >>> CacheKeys.format_key(CacheKeys.DOC_STATE, document_uuid="123-456")
            'doc:state:123-456'
            >>> CacheKeys.format_key(CacheKeys.DOC_STATE, version=2, document_uuid="123-456")
            'doc:state:123-456:v2'
        """
        try:
            key = template.format(**kwargs)
            if version is not None:
                key = f"{key}:v{version}"
            return key
        except KeyError as e:
            raise ValueError(f"Missing required parameter for key template '{template}': {e}")
    
    @staticmethod
    def get_pattern(template: str, wildcard: str = "*") -> str:
        """
        Get a pattern for matching keys.
        
        Args:
            template: Key template
            wildcard: Wildcard character (default: *)
            
        Returns:
            Pattern for key matching
            
        Example:
            >>> CacheKeys.get_pattern(CacheKeys.DOC_STATE)
            'doc:state:*'
        """
        # Replace all placeholders with wildcard
        import re
        return re.sub(r'\{[^}]+\}', wildcard, template)
    
    @classmethod
    def get_all_document_patterns(cls, document_uuid: str, include_versioned: bool = False) -> list:
        """
        Get all cache key patterns for a specific document.
        
        Args:
            document_uuid: Document UUID
            include_versioned: If True, include wildcard patterns for versioned keys
            
        Returns:
            List of key patterns for the document
        """
        patterns = [
            cls.format_key(cls.DOC_STATE, document_uuid=document_uuid),
            cls.format_key(cls.DOC_OCR_RESULT, document_uuid=document_uuid),
            f"doc:entities:{document_uuid}:*",
            f"doc:structured:{document_uuid}:*",
            cls.format_key(cls.DOC_CHUNKS, document_uuid=document_uuid),
            cls.format_key(cls.DOC_PROCESSING_LOCK, document_uuid=document_uuid),
            cls.format_key(cls.TEXTRACT_JOB_RESULT, document_uuid=document_uuid),
            cls.format_key(cls.IDEMPOTENT_OCR, document_uuid=document_uuid),
            cls.format_key(cls.PERF_OCR_TIME, document_uuid=document_uuid),
            cls.format_key(cls.PERF_ENTITY_TIME, document_uuid=document_uuid),
            cls.format_key(cls.PERF_TOTAL_TIME, document_uuid=document_uuid),
            # New optimization cache keys
            cls.format_key(cls.DOC_CHUNKS_LIST, document_uuid=document_uuid),
            cls.format_key(cls.DOC_ALL_EXTRACTED_MENTIONS, document_uuid=document_uuid),
            cls.format_key(cls.DOC_CANONICAL_ENTITIES, document_uuid=document_uuid),
            cls.format_key(cls.DOC_RESOLVED_MENTIONS, document_uuid=document_uuid),
            cls.format_key(cls.DOC_CLEANED_TEXT, document_uuid=document_uuid),
            # Note: DOC_CHUNK_TEXT uses chunk_uuid, not document_uuid, so needs special handling
            # Embedding cache keys (will need version parameter)
            f"emb:doc:{document_uuid}:chunks:v*",
            f"emb:doc:{document_uuid}:mean:v*",
        ]
        
        # Add versioned patterns if requested
        if include_versioned:
            # Add wildcard patterns for versioned keys
            versioned_patterns = []
            for pattern in patterns:
                # Skip patterns that already have wildcards
                if '*' not in pattern:
                    versioned_patterns.append(f"{pattern}:v*")
            patterns.extend(versioned_patterns)
            
        return patterns
    
    @classmethod
    def get_chunk_cache_patterns(cls, chunk_uuids: list) -> list:
        """
        Get cache key patterns for specific chunks.
        
        Args:
            chunk_uuids: List of chunk UUIDs
            
        Returns:
            List of cache key patterns for the chunks
        """
        patterns = []
        for chunk_uuid in chunk_uuids:
            patterns.append(cls.format_key(cls.DOC_CHUNK_TEXT, chunk_uuid=chunk_uuid))
        return patterns
    
    @classmethod
    def get_cache_type_from_key(cls, key: str) -> str:
        """
        Extract cache type from a cache key.
        
        Args:
            key: Redis key
            
        Returns:
            Cache type identifier
        """
        if key.startswith("doc:state:"):
            return "document_state"
        elif key.startswith("doc:ocr:"):
            return "ocr_result"
        elif key.startswith("doc:entities:"):
            return "entity_extraction"
        elif key.startswith("doc:structured:"):
            return "structured_extraction"
        elif key.startswith("job:textract:"):
            return "textract_job"
        elif key.startswith("queue:"):
            return "queue_management"
        elif key.startswith("rate:"):
            return "rate_limiting"
        elif key.startswith("idempotent:"):
            return "idempotency"
        else:
            return "unknown"