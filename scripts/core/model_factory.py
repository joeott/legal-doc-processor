"""
Model factory to select between full and minimal models based on configuration.
"""
from scripts.config import USE_MINIMAL_MODELS
import logging

logger = logging.getLogger(__name__)

# Import minimal models
from scripts.core.models_minimal import (
    SourceDocumentMinimal,
    DocumentChunkMinimal,
    EntityMentionMinimal,
    CanonicalEntityMinimal,
    RelationshipStagingMinimal
)

# Import full models
from scripts.core.schemas import (
    SourceDocumentModel,
    ChunkModel,
    EntityMentionModel,
    CanonicalEntityModel
)


def get_source_document_model():
    """Get appropriate source document model based on configuration"""
    if USE_MINIMAL_MODELS:
        logger.debug("Using SourceDocumentMinimal")
        return SourceDocumentMinimal
    logger.debug("Using SourceDocumentModel (full)")
    return SourceDocumentModel


def get_chunk_model():
    """Get appropriate chunk model based on configuration"""
    if USE_MINIMAL_MODELS:
        logger.debug("Using DocumentChunkMinimal")
        return DocumentChunkMinimal
    logger.debug("Using ChunkModel (full)")
    return ChunkModel


def get_entity_mention_model():
    """Get appropriate entity mention model based on configuration"""
    if USE_MINIMAL_MODELS:
        logger.debug("Using EntityMentionMinimal")
        return EntityMentionMinimal
    logger.debug("Using EntityMentionModel (full)")
    return EntityMentionModel


def get_canonical_entity_model():
    """Get appropriate canonical entity model based on configuration"""
    if USE_MINIMAL_MODELS:
        logger.debug("Using CanonicalEntityMinimal")
        return CanonicalEntityMinimal
    logger.debug("Using CanonicalEntityModel (full)")
    return CanonicalEntityModel


def get_relationship_model():
    """Get appropriate relationship model based on configuration"""
    if USE_MINIMAL_MODELS:
        logger.debug("Using RelationshipStagingMinimal")
        return RelationshipStagingMinimal
    # No full relationship model defined in schemas, return minimal
    return RelationshipStagingMinimal


# Helper function to adapt between models if needed
def adapt_to_minimal(full_model_instance):
    """Convert a full model instance to minimal model"""
    if USE_MINIMAL_MODELS:
        return full_model_instance  # Already minimal
    
    # Get the type of the full model
    model_type = type(full_model_instance).__name__
    
    if model_type == 'SourceDocumentModel':
        return SourceDocumentMinimal(
            id=getattr(full_model_instance, 'id', None),
            document_uuid=full_model_instance.document_uuid,
            original_file_name=full_model_instance.original_file_name,
            file_name=getattr(full_model_instance, 'file_name', None),
            s3_key=getattr(full_model_instance, 's3_key', None),
            s3_bucket=getattr(full_model_instance, 's3_bucket', None),
            project_uuid=getattr(full_model_instance, 'project_uuid', None),
            project_fk_id=getattr(full_model_instance, 'project_fk_id', None),
            status=getattr(full_model_instance, 'status', 'pending'),
            celery_status=getattr(full_model_instance, 'celery_status', 'pending'),
            error_message=getattr(full_model_instance, 'error_message', None),
            textract_job_id=getattr(full_model_instance, 'textract_job_id', None),
            textract_job_status=getattr(full_model_instance, 'textract_job_status', None),
            raw_extracted_text=getattr(full_model_instance, 'raw_extracted_text', None),
            created_at=full_model_instance.created_at,
            updated_at=getattr(full_model_instance, 'updated_at', None)
        )
    
    # Add other model conversions as needed
    return full_model_instance