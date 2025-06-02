"""
Simple result wrapper for entity extraction to avoid model conflicts
"""
from typing import List, Dict, Any, Optional
from uuid import UUID
from dataclasses import dataclass
from scripts.core.processing_models import ProcessingResultStatus

@dataclass
class EntityExtractionResult:
    """Simple result wrapper for entity extraction"""
    status: ProcessingResultStatus
    document_uuid: str
    chunk_uuid: UUID
    entity_mentions: List[Any]  # List of EntityMentionModel
    canonical_entities: List[Any]  # List of CanonicalEntityModel
    extraction_metadata: Dict[str, Any]
    
    @property
    def entity_count(self) -> int:
        return len(self.entity_mentions)