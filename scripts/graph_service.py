"""
Graph Service Module.
Consolidated graph and relationship building functionality.
"""
import uuid
import json
import logging
from typing import Optional, List, Dict, Any

from scripts.core.processing_models import (
    RelationshipBuildingResultModel, StagedRelationship,
    ProcessingResultStatus
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
        document_uuid_val = document_data.get('documentId')  # This is the neo4j_document_uuid
        
        # Initialize result model
        result = RelationshipBuildingResultModel(
            document_uuid=document_uuid or uuid.uuid4(),
            total_relationships=0,
            staged_relationships=[],
            status=ProcessingResultStatus.SUCCESS
        )
        
        if not document_uuid_val:
            logger.error("No documentId (neo4j_document_uuid) in document_data for relationship_builder, cannot create relationships.")
            result.status = ProcessingResultStatus.FAILED
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
            # 1. (Document)-[:BELONGS_TO]->(Project)
            if not project_uuid or not isinstance(project_uuid, str):
                logger.error(f"Invalid project_uuid: {project_uuid} for document {document_uuid_val}. Skipping Document-Project relationship.")
            else:
                rel = self._create_relationship_wrapper(
                    from_id=document_uuid_val,
                    from_label="Document",
                    to_id=project_uuid,
                    to_label="Project",
                    rel_type="BELONGS_TO"
                )
                if rel:
                    staged_relationships.append(rel)
    
            # 2. (Chunk)-[:BELONGS_TO]->(Document)
            for chunk in chunks_data:
                chunk_uuid_val = chunk.get('chunkId')  # This is chunk_uuid
                if not chunk_uuid_val:
                    logger.warning(f"Chunk data item {chunk} has no chunkId (chunk_uuid), skipping BELONGS_TO Document relationship.")
                    continue
                rel = self._create_relationship_wrapper(
                    from_id=chunk_uuid_val,
                    from_label="Chunk",
                    to_id=document_uuid_val,
                    to_label="Document",
                    rel_type="BELONGS_TO"
                )
                if rel:
                    staged_relationships.append(rel)
    
            # 3. (Chunk)-[:CONTAINS_MENTION]->(EntityMention)
            for em in entity_mentions_data:
                em_uuid_val = em.get('entityMentionId')  # This is entity_mention_uuid
                chunk_uuid_for_em = em.get('chunk_uuid')  # The chunk this EM belongs to
                
                if not em_uuid_val or not chunk_uuid_for_em:
                    logger.warning(f"Entity mention {em} or its chunk_uuid missing, skipping CONTAINS_MENTION relationship.")
                    continue
                rel = self._create_relationship_wrapper(
                    from_id=chunk_uuid_for_em,
                    from_label="Chunk",
                    to_id=em_uuid_val,
                    to_label="EntityMention",
                    rel_type="CONTAINS_MENTION"
                )
                if rel:
                    staged_relationships.append(rel)
    
            # 4. (EntityMention)-[:MEMBER_OF_CLUSTER]->(CanonicalEntity)
            for em in entity_mentions_data:
                em_uuid_val = em.get('entityMentionId')
                canon_uuid_val = em.get('resolved_canonical_id_neo4j')  # This is canonical_entity_uuid
                
                if not em_uuid_val or not canon_uuid_val:
                    logger.debug(f"Entity mention {em_uuid_val} has no resolved_canonical_id_neo4j or is self-canonical. Skipping MEMBER_OF_CLUSTER.")
                    continue
                rel = self._create_relationship_wrapper(
                    from_id=em_uuid_val,
                    from_label="EntityMention",
                    to_id=canon_uuid_val,
                    to_label="CanonicalEntity",
                    rel_type="MEMBER_OF_CLUSTER"
                )
                if rel:
                    staged_relationships.append(rel)
    
            # 5. (Chunk)-[:NEXT_CHUNK/PREVIOUS_CHUNK]->(Chunk)
            sorted_chunks = sorted(chunks_data, key=lambda c: c.get('chunkIndex', 0))
            
            for i in range(len(sorted_chunks) - 1):
                chunk_curr = sorted_chunks[i]
                chunk_next = sorted_chunks[i + 1]
                
                curr_uuid = chunk_curr.get('chunkId')
                next_uuid = chunk_next.get('chunkId')
                
                if not curr_uuid or not next_uuid:
                    logger.warning(f"Chunk UUID missing in sorted chunk list. Curr: {curr_uuid}, Next: {next_uuid}. Skipping NEXT_CHUNK/PREVIOUS_CHUNK.")
                    continue
                
                # Add a unique id property to the NEXT_CHUNK relationship
                next_rel_props = {"id": str(uuid.uuid4())}
    
                next_rel = self._create_relationship_wrapper(
                    from_id=curr_uuid,
                    from_label="Chunk",
                    to_id=next_uuid,
                    to_label="Chunk",
                    rel_type="NEXT_CHUNK",
                    properties=next_rel_props
                )
                if next_rel:
                    staged_relationships.append(next_rel)
                
                prev_rel = self._create_relationship_wrapper(
                    from_id=next_uuid,
                    from_label="Chunk",
                    to_id=curr_uuid,
                    to_label="Chunk",
                    rel_type="PREVIOUS_CHUNK"
                )
                if prev_rel:
                    staged_relationships.append(prev_rel)
            
            # Update result
            result.staged_relationships = staged_relationships
            result.total_relationships = len(staged_relationships)
            
            logger.info(f"Successfully staged {len(staged_relationships)} structural relationships for document {document_uuid_val}")
            return result
            
        except Exception as e:
            logger.error(f"Error staging relationships for document {document_uuid_val}: {e}", exc_info=True)
            result.status = ProcessingResultStatus.FAILED
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
        Wrapper to call db_manager.create_relationship_staging and return a StagedRelationship model.
        
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
            # Call the database manager to stage the relationship
            rel_id = self.db_manager.create_relationship_staging(
                from_node_id=from_id,
                from_node_label=from_label,
                to_node_id=to_id,
                to_node_label=to_label,
                relationship_type=rel_type,
                properties=properties
            )
            
            if rel_id:
                # Create and return StagedRelationship model
                staged_rel = StagedRelationship(
                    from_node_id=from_id,
                    from_node_label=from_label,
                    to_node_id=to_id,
                    to_node_label=to_label,
                    relationship_type=rel_type,
                    properties=properties or {},
                    staging_id=str(rel_id)
                )
                
                logger.debug(f"Staged relationship: {from_label}({from_id}) -[{rel_type}]-> {to_label}({to_id}), Staging ID: {rel_id}")
                return staged_rel
            else:
                logger.error(f"Failed to stage relationship: {from_label}({from_id}) -[{rel_type}]-> {to_label}({to_id}) via DatabaseManager.")
                return None
            
        except Exception as e:
            logger.error(f"Exception calling db_manager.create_relationship_staging for {from_label}({from_id}) -[{rel_type}]-> {to_label}({to_id}): {str(e)}", exc_info=True)
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