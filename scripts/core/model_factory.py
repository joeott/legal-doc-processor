"""
Model factory - simplified to use only consolidated models.
All models now come from the single consolidated file.
"""
import logging

logger = logging.getLogger(__name__)

# Import all models from the consolidated location
from scripts.models import (
    SourceDocumentMinimal,
    DocumentChunkMinimal,
    EntityMentionMinimal,
    CanonicalEntityMinimal,
    RelationshipStagingMinimal,
    ProcessingTaskMinimal,
    ProjectMinimal
)


def get_source_document_model():
    """Get source document model - always returns consolidated minimal model"""
    logger.debug("Using SourceDocumentMinimal (consolidated)")
    return SourceDocumentMinimal


def get_chunk_model():
    """Get chunk model - always returns consolidated minimal model"""
    logger.debug("Using DocumentChunkMinimal (consolidated)")
    return DocumentChunkMinimal


def get_entity_mention_model():
    """Get entity mention model - always returns consolidated minimal model"""
    logger.debug("Using EntityMentionMinimal (consolidated)")
    return EntityMentionMinimal


def get_canonical_entity_model():
    """Get canonical entity model - always returns consolidated minimal model"""
    logger.debug("Using CanonicalEntityMinimal (consolidated)")
    return CanonicalEntityMinimal


def get_relationship_model():
    """Get relationship model - always returns consolidated minimal model"""
    logger.debug("Using RelationshipStagingMinimal (consolidated)")
    return RelationshipStagingMinimal


def get_processing_task_model():
    """Get processing task model"""
    logger.debug("Using ProcessingTaskMinimal (consolidated)")
    return ProcessingTaskMinimal


def get_project_model():
    """Get project model"""
    logger.debug("Using ProjectMinimal (consolidated)")
    return ProjectMinimal


# No adaptation needed - all models are consolidated minimal models