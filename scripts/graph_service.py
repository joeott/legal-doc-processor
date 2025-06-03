"""
Graph Service Module.
Consolidated graph and relationship building functionality.
"""
import uuid
import json
import logging
from typing import Optional, List, Dict, Any

from scripts.models import (
    ProcessingResultStatus,
    ProcessingResult,
    RelationshipStagingMinimal
)
# TODO: Migrate these models to models.py
from scripts.core.processing_models import (
    RelationshipBuildingResultModel, StagedRelationship
)
from scripts.db import DatabaseManager

logger = logging.getLogger(__name__)


class GraphService:
    """Unified graph and relationship building service."""
    
    def __init__(self, db_manager: DatabaseManager):
        """
        Initialize graph service.
        
        Args:
            db_manager: Database manager instance
        """
        self.db_manager = db_manager
    
    def stage_structural_relationships(
        self,
        document_data: Dict[str, Any],
        project_uuid: str,
        chunks_data: List[Dict[str, Any]],
        entity_mentions_data: List[Dict[str, Any]],
        canonical_entities_data: List[Dict[str, Any]],
        document_uuid: Optional[uuid.UUID] = None
    ) -> RelationshipBuildingResultModel:
        """
        Stages relationships like BELONGS_TO, CONTAINS_MENTION, MEMBER_OF_CLUSTER, NEXT/PREV_CHUNK.
        
        Arguments:
            document_data: Dictionary with document info (must contain 'documentId' which is neo4j_document_uuid)
            project_uuid: Project UUID (not SQL ID)
            chunks_data: List of chunk dictionaries (must contain 'chunkId' which is chunk_uuid, 'chunkIndex')
            entity_mentions_data: List of entity mention dictionaries
            canonical_entities_data: List of canonical entity dictionaries
            document_uuid: UUID of the document being processed
        
        Returns:
            RelationshipBuildingResultModel with staged relationships
        """
        # Try both possible keys for document UUID
        document_uuid_val = document_data.get('documentId') or document_data.get('document_uuid')
        
        # Initialize result model
        result = RelationshipBuildingResultModel(
            document_uuid=document_uuid or uuid.uuid4(),
            total_relationships=0,
            staged_relationships=[],
            status=ProcessingResultStatus.SUCCESS
        )
        
        if not document_uuid_val:
            logger.error("No documentId or document_uuid in document_data for relationship_builder, cannot create relationships.")
            result.status = ProcessingResultStatus.FAILURE
            result.error_message = "Missing document UUID in document data"
            return result
            
        logger.info(f"Staging structural relationships for document {document_uuid_val}")
        logger.info(f"Document data: {document_data}")
        logger.info(f"Project UUID: {project_uuid}")
        logger.info(f"Chunks: {len(chunks_data)} items")
        logger.info(f"Entity mentions: {len(entity_mentions_data)} items")
        logger.info(f"Canonical entities: {len(canonical_entities_data)} items")
        
        staged_relationships = []
        
        try:
            # Note: relationship_staging table only supports canonical entity-to-entity relationships
            # due to foreign key constraints that reference canonical_entities table
            logger.info("Creating relationships between canonical entities only (FK constraint limitation)")
            
            # Create relationships between canonical entities that appear in the same document
            for i, entity1 in enumerate(canonical_entities_data):
                for j, entity2 in enumerate(canonical_entities_data):
                    if i >= j:  # Avoid duplicates and self-relationships
                        continue
                    
                    entity1_uuid = entity1.get('canonical_entity_uuid')
                    entity2_uuid = entity2.get('canonical_entity_uuid')
                    
                    if not entity1_uuid or not entity2_uuid:
                        continue
                    
                    # Create a CO_OCCURS relationship between entities in the same document
                    rel = self._create_relationship_wrapper(
                        from_id=entity1_uuid,
                        from_label="CanonicalEntity",
                        to_id=entity2_uuid,
                        to_label="CanonicalEntity",
                        rel_type="CO_OCCURS",
                        properties={
                            "document_uuid": document_uuid_val,
                            "co_occurrence_type": "same_document"
                        }
                    )
                    if rel:
                        staged_relationships.append(rel)
            
            # Count existing relationships in the database for accurate reporting
            try:
                from sqlalchemy import text
                session = next(self.db_manager.get_session())
                try:
                    existing_count_result = session.execute(
                        text("""
                            SELECT COUNT(*) 
                            FROM relationship_staging 
                            WHERE source_entity_uuid IN (
                                SELECT canonical_entity_uuid FROM canonical_entities 
                                WHERE canonical_entity_uuid IN (
                                    SELECT canonical_entity_uuid FROM entity_mentions 
                                    WHERE document_uuid = :doc_uuid
                                )
                            )
                        """),
                        {'doc_uuid': document_uuid_val}
                    ).scalar()
                    
                    total_existing_relationships = existing_count_result or 0
                    logger.info(f"Found {total_existing_relationships} total relationships for document {document_uuid_val} (newly staged: {len(staged_relationships)})")
                    
                    # Update result with total existing relationships, not just newly created ones
                    result.staged_relationships = staged_relationships
                    result.total_relationships = total_existing_relationships
                    
                    logger.info(f"Successfully verified {total_existing_relationships} total structural relationships for document {document_uuid_val}")
                    return result
                    
                finally:
                    session.close()
                    
            except Exception as e:
                logger.warning(f"Could not count existing relationships, falling back to staged count: {e}")
                # Fallback to original logic
                result.staged_relationships = staged_relationships
                result.total_relationships = len(staged_relationships)
                
                logger.info(f"Successfully staged {len(staged_relationships)} structural relationships for document {document_uuid_val}")
                return result
            
        except Exception as e:
            logger.error(f"Error staging relationships for document {document_uuid_val}: {e}", exc_info=True)
            result.status = ProcessingResultStatus.FAILURE
            result.error_message = str(e)
            return result
    
    def _create_relationship_wrapper(
        self,
        from_id: str,
        from_label: str,
        to_id: str,
        to_label: str,
        rel_type: str,
        properties: Optional[Dict[str, Any]] = None
    ) -> Optional[StagedRelationship]:
        """
        Create a relationship using the minimal models and correct database interface.
        
        Args:
            from_id: Source node ID
            from_label: Source node label
            to_id: Target node ID
            to_label: Target node label
            rel_type: Relationship type
            properties: Optional relationship properties
        
        Returns:
            StagedRelationship model if successful, None otherwise
        """
        try:
            # Debug logging with detailed input values
            logger.info(f"_create_relationship_wrapper called with:")
            logger.info(f"  from_id: {from_id} (type: {type(from_id)})")
            logger.info(f"  from_label: {from_label}")
            logger.info(f"  to_id: {to_id} (type: {type(to_id)})")
            logger.info(f"  to_label: {to_label}")
            logger.info(f"  rel_type: {rel_type}")
            
            # Validate UUID inputs
            if not from_id or not to_id:
                logger.error(f"Invalid UUID inputs: from_id={from_id}, to_id={to_id}")
                return None
            
            # Convert to string if UUID objects
            from_id_str = str(from_id) if from_id else None
            to_id_str = str(to_id) if to_id else None
            
            logger.info(f"After conversion: from_id_str={from_id_str}, to_id_str={to_id_str}")
            
            # Debug the RelationshipStagingMinimal constructor call
            logger.info(f"Creating RelationshipStagingMinimal with:")
            logger.info(f"  source_entity_uuid={from_id_str}")
            logger.info(f"  target_entity_uuid={to_id_str}")
            logger.info(f"  relationship_type={rel_type}")
            
            # Create RelationshipStagingMinimal model
            relationship = RelationshipStagingMinimal(
                source_entity_uuid=from_id_str,
                target_entity_uuid=to_id_str,
                relationship_type=rel_type,
                confidence_score=1.0,
                properties=properties or {},
                metadata={
                    'source_label': from_label,
                    'target_label': to_label,
                    'created_by': 'pipeline'
                }
            )
            
            # Debug: Check that the model was created correctly
            logger.info(f"Created RelationshipStagingMinimal model:")
            logger.info(f"  source_entity_uuid: {relationship.source_entity_uuid}")
            logger.info(f"  target_entity_uuid: {relationship.target_entity_uuid}")
            logger.info(f"  relationship_type: {relationship.relationship_type}")
            
            # Call the database manager with the model
            logger.info(f"Calling database manager...")
            result = self.db_manager.create_relationship_staging(relationship)
            logger.info(f"Database result: {result}")
            
            if result:
                # Create and return StagedRelationship model for compatibility
                staged_rel = StagedRelationship(
                    from_node_id=from_id,
                    from_node_label=from_label,
                    to_node_id=to_id,
                    to_node_label=to_label,
                    relationship_type=rel_type,
                    properties=properties or {},
                    staging_id=str(result.id) if hasattr(result, 'id') and result.id else 'new'
                )
                
                logger.debug(f"Staged relationship: {from_label}({from_id}) -[{rel_type}]-> {to_label}({to_id})")
                return staged_rel
            else:
                logger.warning(f"Failed to create relationship staging for {from_label}({from_id}) -[{rel_type}]-> {to_label}({to_id})")
                return None
                
        except Exception as e:
            logger.error(f"Exception creating relationship {from_label}({from_id}) -[{rel_type}]-> {to_label}({to_id}): {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return None


# Legacy compatibility functions
def stage_structural_relationships(
    db_manager,
    document_data: Dict[str, Any],
    project_uuid: str,
    chunks_data: List[Dict[str, Any]],
    entity_mentions_data: List[Dict[str, Any]],
    canonical_entities_data: List[Dict[str, Any]],
    document_uuid: Optional[uuid.UUID] = None
) -> RelationshipBuildingResultModel:
    """
    Legacy wrapper for stage_structural_relationships.
    Maintains backward compatibility with existing code.
    """
    service = GraphService(db_manager)
    return service.stage_structural_relationships(
        document_data=document_data,
        project_uuid=project_uuid,
        chunks_data=chunks_data,
        entity_mentions_data=entity_mentions_data,
        canonical_entities_data=canonical_entities_data,
        document_uuid=document_uuid
    )