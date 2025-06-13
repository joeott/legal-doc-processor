"""
Unified entity processing logic.
Consolidates entity extraction, resolution, and management.
"""
import logging
from typing import Dict, Any, Optional, List
import json

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from supabase_utils import SupabaseManager
from redis_utils import get_redis_manager
from cache_keys import CacheKeys

logger = logging.getLogger(__name__)


class EntityProcessor:
    """Centralized entity processing functionality."""
    
    def __init__(self):
        self.db_manager = SupabaseManager()
        self.redis_manager = get_redis_manager()
        
    def get_entity_mentions_for_document(self, document_uuid: str, 
                                       use_cache: bool = True) -> List[Dict[str, Any]]:
        """Get all entity mentions for a document."""
        # Try cache first
        if use_cache and self.redis_manager and self.redis_manager.is_available():
            cache_key = CacheKeys.format_key(
                CacheKeys.DOC_ENTITY_MENTIONS,
                document_uuid=document_uuid
            )
            cached = self.redis_manager.get_cached(cache_key)
            if cached:
                logger.info(f"Retrieved {len(cached)} entity mentions from cache")
                return cached
        
        # Fetch from database
        try:
            # First get the neo4j document
            doc_response = self.db_manager.client.table('neo4j_documents').select(
                'id'
            ).eq('document_uuid', document_uuid).execute()
            
            if not doc_response.data:
                logger.warning(f"No neo4j document found for {document_uuid}")
                return []
                
            neo4j_doc_id = doc_response.data[0]['id']
            
            # Get chunks
            chunks_response = self.db_manager.client.table('neo4j_chunks').select(
                'id', 'chunkId'
            ).eq('document_id', neo4j_doc_id).execute()
            
            if not chunks_response.data:
                logger.warning(f"No chunks found for document {document_uuid}")
                return []
                
            chunk_ids = [c['id'] for c in chunks_response.data]
            
            # Get entity mentions
            mentions_response = self.db_manager.client.table('neo4j_entity_mentions').select(
                '*'
            ).in_('chunk_id', chunk_ids).execute()
            
            entity_mentions = mentions_response.data
            
            # Cache the result
            if use_cache and self.redis_manager and self.redis_manager.is_available():
                self.redis_manager.set_cached(cache_key, entity_mentions, ttl=3600)
                
            return entity_mentions
            
        except Exception as e:
            logger.error(f"Error fetching entity mentions: {e}")
            return []
    
    def get_canonical_entities(self, entity_ids: Optional[List[int]] = None,
                             project_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get canonical entities, optionally filtered by IDs or project."""
        try:
            query = self.db_manager.client.table('neo4j_canonical_entities').select('*')
            
            if entity_ids:
                query = query.in_('id', entity_ids)
            
            if project_id:
                query = query.eq('project_id', project_id)
                
            response = query.execute()
            return response.data
            
        except Exception as e:
            logger.error(f"Error fetching canonical entities: {e}")
            return []
    
    def get_entity_resolution_stats(self, document_uuid: str) -> Dict[str, Any]:
        """Get statistics about entity resolution for a document."""
        try:
            mentions = self.get_entity_mentions_for_document(document_uuid)
            
            if not mentions:
                return {
                    'total_mentions': 0,
                    'resolved_mentions': 0,
                    'unresolved_mentions': 0,
                    'unique_entities': 0,
                    'resolution_rate': 0.0
                }
            
            resolved = [m for m in mentions if m.get('resolved_canonical_id')]
            unique_entities = len(set(m['resolved_canonical_id'] for m in resolved))
            
            stats = {
                'total_mentions': len(mentions),
                'resolved_mentions': len(resolved),
                'unresolved_mentions': len(mentions) - len(resolved),
                'unique_entities': unique_entities,
                'resolution_rate': (len(resolved) / len(mentions) * 100) if mentions else 0
            }
            
            # Get entity type breakdown
            entity_types = {}
            for mention in mentions:
                entity_type = mention.get('entityType', 'unknown')
                entity_types[entity_type] = entity_types.get(entity_type, 0) + 1
                
            stats['entity_types'] = entity_types
            
            return stats
            
        except Exception as e:
            logger.error(f"Error getting entity resolution stats: {e}")
            return {}
    
    def find_duplicate_entities(self, project_id: int, 
                              similarity_threshold: float = 0.9) -> List[Dict[str, Any]]:
        """Find potential duplicate canonical entities within a project.
        
        Note: similarity_threshold parameter reserved for future fuzzy matching implementation.
        """
        try:
            # Get all canonical entities for the project
            entities = self.get_canonical_entities(project_id=project_id)
            
            if len(entities) < 2:
                return []
            
            duplicates = []
            
            # Compare each entity with others
            for i, entity1 in enumerate(entities):
                for entity2 in entities[i+1:]:
                    # Skip if same type
                    if entity1.get('entityType') != entity2.get('entityType'):
                        continue
                        
                    # Calculate similarity (simple string comparison for now)
                    name1 = entity1.get('canonicalName', '').lower()
                    name2 = entity2.get('canonicalName', '').lower()
                    
                    # Check for exact match or substring
                    if name1 == name2 or name1 in name2 or name2 in name1:
                        duplicates.append({
                            'entity1_id': entity1['id'],
                            'entity1_name': entity1.get('canonicalName'),
                            'entity2_id': entity2['id'], 
                            'entity2_name': entity2.get('canonicalName'),
                            'type': entity1.get('entityType'),
                            'similarity': 1.0 if name1 == name2 else 0.95
                        })
                        
            return duplicates
            
        except Exception as e:
            logger.error(f"Error finding duplicate entities: {e}")
            return []
    
    def merge_canonical_entities(self, keep_id: int, merge_ids: List[int]) -> bool:
        """Merge multiple canonical entities into one."""
        try:
            # Update all entity mentions to point to the keeper
            self.db_manager.client.table('neo4j_entity_mentions').update({
                'resolved_canonical_id': keep_id
            }).in_('resolved_canonical_id', merge_ids).execute()
            
            # Delete the merged entities
            self.db_manager.client.table('neo4j_canonical_entities').delete().in_(
                'id', merge_ids
            ).execute()
            
            # Clear cache for affected documents
            if self.redis_manager and self.redis_manager.is_available():
                # This would need to track which documents are affected
                # For now, we'll just log
                logger.info(f"Merged {len(merge_ids)} entities into entity {keep_id}")
                
            return True
            
        except Exception as e:
            logger.error(f"Error merging entities: {e}")
            return False
    
    def export_entities_for_project(self, project_id: int, 
                                  output_format: str = 'json') -> Optional[str]:
        """Export all entities for a project."""
        try:
            entities = self.get_canonical_entities(project_id=project_id)
            
            if output_format == 'json':
                return json.dumps(entities, indent=2, default=str)
            elif output_format == 'csv':
                import csv
                import io
                
                output = io.StringIO()
                if entities:
                    writer = csv.DictWriter(output, fieldnames=entities[0].keys())
                    writer.writeheader()
                    writer.writerows(entities)
                    
                return output.getvalue()
            else:
                raise ValueError(f"Unsupported format: {output_format}")
                
        except Exception as e:
            logger.error(f"Error exporting entities: {e}")
            return None