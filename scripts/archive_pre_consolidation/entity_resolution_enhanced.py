"""
Enhanced Entity Resolution with Semantic Similarity
Combines string matching with vector embeddings for improved accuracy
"""

import json
import hashlib
import logging
import uuid
import numpy as np
from typing import List, Dict, Tuple, Optional, Union
from openai import OpenAI

from scripts.config import LLM_API_KEY, LLM_MODEL_FOR_RESOLUTION, REDIS_ENTITY_CACHE_TTL
from scripts.cache import get_redis_manager, CacheKeys
from scripts.database import SupabaseManager
from scripts.core.processing_models import (
    EntityResolutionResultModel,
    CanonicalEntity,
    ProcessingResultStatus
)

logger = logging.getLogger(__name__)

# Initialize OpenAI client for embeddings
openai_client = OpenAI(api_key=LLM_API_KEY) if LLM_API_KEY else None

def get_entity_embedding(entity_text: str, entity_type: str) -> Optional[np.ndarray]:
    """
    Generate embedding for an entity mention.
    Uses a specialized prompt template for better entity representation.
    """
    if not openai_client:
        return None
    
    try:
        # Create a contextualized representation for better embeddings
        if entity_type == "Person":
            prompt = f"Person entity: {entity_text}"
        elif entity_type == "Organization":
            prompt = f"Organization/Company: {entity_text}"
        elif entity_type == "Location":
            prompt = f"Geographic location: {entity_text}"
        elif entity_type == "Date":
            prompt = f"Date/Time reference: {entity_text}"
        else:
            prompt = f"{entity_type}: {entity_text}"
        
        response = openai_client.embeddings.create(
            model="text-embedding-3-large",
            input=prompt
        )
        
        embedding = np.array(response.data[0].embedding, dtype=np.float32)
        return embedding
        
    except Exception as e:
        logger.warning(f"Error generating entity embedding: {e}")
        return None


def compute_semantic_similarity(emb1: np.ndarray, emb2: np.ndarray) -> float:
    """Compute cosine similarity between two embeddings"""
    if emb1 is None or emb2 is None:
        return 0.0
    
    similarity = np.dot(emb1, emb2) / (np.linalg.norm(emb1) * np.linalg.norm(emb2))
    return float(similarity)


def fuzzy_string_similarity(str1: str, str2: str) -> float:
    """
    Compute string similarity using multiple methods.
    Returns a score between 0 and 1.
    """
    from difflib import SequenceMatcher
    
    # Normalize strings
    s1 = str1.lower().strip()
    s2 = str2.lower().strip()
    
    # Exact match
    if s1 == s2:
        return 1.0
    
    # Substring match
    if s1 in s2 or s2 in s1:
        return 0.9
    
    # Sequence matching
    ratio = SequenceMatcher(None, s1, s2).ratio()
    
    # Token overlap (for multi-word entities)
    tokens1 = set(s1.split())
    tokens2 = set(s2.split())
    if tokens1 and tokens2:
        overlap = len(tokens1.intersection(tokens2)) / max(len(tokens1), len(tokens2))
        ratio = max(ratio, overlap * 0.8)
    
    return ratio


def enhanced_entity_resolution(
    entity_mentions_for_doc: List[Dict],
    document_text: str,
    document_uuid: Union[str, uuid.UUID],
    chunk_embeddings: Optional[Dict[str, np.ndarray]] = None,
    similarity_threshold: float = 0.75,
    semantic_weight: float = 0.7
) -> EntityResolutionResultModel:
    """
    Enhanced entity resolution using both string matching and semantic similarity.
    
    Args:
        entity_mentions_for_doc: List of entity mentions from the document
        document_text: Full document text for context
        document_uuid: UUID of the source document (string or UUID object)
        chunk_embeddings: Optional dict of chunk_id -> embedding for context
        similarity_threshold: Minimum combined similarity for grouping
        semantic_weight: Weight for semantic similarity (vs string similarity)
    
    Returns:
        EntityResolutionResultModel containing canonical entities and updated mentions
    """
    logger.info(f"Starting enhanced entity resolution for {len(entity_mentions_for_doc)} mentions")
    
    # Convert document_uuid to UUID object if it's a string
    if isinstance(document_uuid, str):
        document_uuid = uuid.UUID(document_uuid)
    
    if not entity_mentions_for_doc:
        return EntityResolutionResultModel(
            document_uuid=document_uuid,
            status=ProcessingResultStatus.SKIPPED,
            total_mentions=0,
            total_canonical_entities=0,
            canonical_entities=[],
            updated_mentions=[],
            model_used="enhanced_resolution"
        )
    
    # Try cache first
    cache_key = f"enhanced_resolution:{_generate_resolution_cache_key(entity_mentions_for_doc, document_text)}"
    redis_mgr = get_redis_manager()
    if redis_mgr and redis_mgr.is_available():
        cached_result = redis_mgr.get_cached(cache_key)
        if cached_result:
            logger.info("Enhanced entity resolution cache hit")
            # Convert cached canonical entities to Pydantic models
            canonical_entities = [
                CanonicalEntity(
                    name=ce.get('canonicalName'),
                    entity_type=ce.get('entity_type'),
                    aliases=json.loads(ce.get('allKnownAliasesInDoc_json', '[]')),
                    mention_count=ce.get('mention_count_in_doc', 0),
                    first_seen_chunk_index=ce.get('firstSeenAtChunkIndex_int', 0),
                    confidence=ce.get('confidence_score', 1.0),
                    attributes={'canonicalEntityId_temp': ce.get('canonicalEntityId_temp')}
                )
                for ce in cached_result['canonical_entities']
            ]
            return EntityResolutionResultModel(
                document_uuid=document_uuid,
                status=ProcessingResultStatus.SUCCESS,
                total_mentions=len(entity_mentions_for_doc),
                total_canonical_entities=len(canonical_entities),
                canonical_entities=canonical_entities,
                updated_mentions=cached_result['updated_mentions'],
                model_used="enhanced_resolution"
            )
    
    # Group mentions by entity type for more accurate resolution
    mentions_by_type = {}
    for mention in entity_mentions_for_doc:
        entity_type = mention.get('entity_type', 'Unknown')
        if entity_type not in mentions_by_type:
            mentions_by_type[entity_type] = []
        mentions_by_type[entity_type].append(mention)
    
    canonical_entities = []
    updated_mentions = []
    canon_id_counter = 0
    
    # Process each entity type separately
    for entity_type, type_mentions in mentions_by_type.items():
        logger.info(f"Processing {len(type_mentions)} {entity_type} entities")
        
        # Calculate embeddings for all mentions of this type
        mention_embeddings = {}
        for mention in type_mentions:
            if chunk_embeddings and mention.get('chunk_uuid') in chunk_embeddings:
                # Use chunk embedding as context
                chunk_emb = chunk_embeddings[mention['chunk_uuid']]
                entity_emb = get_entity_embedding(mention['value'], entity_type)
                if entity_emb is not None:
                    # Combine entity and context embeddings
                    mention_embeddings[mention['id']] = 0.7 * entity_emb + 0.3 * chunk_emb
                else:
                    mention_embeddings[mention['id']] = chunk_emb
            else:
                # Generate embedding for the entity
                emb = get_entity_embedding(mention['value'], entity_type)
                if emb is not None:
                    mention_embeddings[mention['id']] = emb
        
        # Group similar entities
        groups = []
        processed = set()
        
        for i, mention1 in enumerate(type_mentions):
            if mention1['id'] in processed:
                continue
            
            # Start a new group
            group = [mention1]
            processed.add(mention1['id'])
            
            # Find similar mentions
            for mention2 in type_mentions[i+1:]:
                if mention2['id'] in processed:
                    continue
                
                # Calculate string similarity
                string_sim = fuzzy_string_similarity(mention1['value'], mention2['value'])
                
                # Calculate semantic similarity if embeddings available
                semantic_sim = 0.0
                if mention1['id'] in mention_embeddings and mention2['id'] in mention_embeddings:
                    semantic_sim = compute_semantic_similarity(
                        mention_embeddings[mention1['id']],
                        mention_embeddings[mention2['id']]
                    )
                
                # Combine similarities
                if mention1['id'] in mention_embeddings and mention2['id'] in mention_embeddings:
                    # Both embeddings available - use weighted combination
                    combined_sim = (semantic_weight * semantic_sim + 
                                  (1 - semantic_weight) * string_sim)
                else:
                    # No embeddings - use string similarity only
                    combined_sim = string_sim
                
                # Group if similarity exceeds threshold
                if combined_sim >= similarity_threshold:
                    group.append(mention2)
                    processed.add(mention2['id'])
                    logger.debug(f"Grouping '{mention1['value']}' with '{mention2['value']}' "
                               f"(string: {string_sim:.2f}, semantic: {semantic_sim:.2f})")
            
            groups.append(group)
        
        # Create canonical entities from groups
        for group in groups:
            # Choose the most complete/official name as canonical
            canonical_name = max(group, key=lambda m: len(m['value']))['value']
            
            # For very similar names, prefer the longest or most formal version
            if entity_type == "Person":
                # Prefer full names over initials
                for mention in group:
                    if len(mention['value'].split()) > len(canonical_name.split()):
                        canonical_name = mention['value']
            
            canon_id = f"canon_{entity_type}_{canon_id_counter}"
            canon_id_counter += 1
            
            # Create canonical entity
            canonical_entity = {
                "canonicalEntityId_temp": canon_id,
                "canonicalName": canonical_name,
                "entity_type": entity_type,
                "allKnownAliasesInDoc_json": json.dumps(list(set(m['value'] for m in group))),
                "mention_count_in_doc": len(group),
                "firstSeenAtChunkIndex_int": min(m.get('chunk_index_int', 0) for m in group),
                "confidence_score": max(0.95 if len(group) > 1 else 0.8, 
                                      sum(fuzzy_string_similarity(m['value'], canonical_name) 
                                          for m in group) / len(group))
            }
            
            # Add average embedding if available
            if any(m['id'] in mention_embeddings for m in group):
                group_embeddings = [mention_embeddings[m['id']] 
                                  for m in group if m['id'] in mention_embeddings]
                if group_embeddings:
                    avg_embedding = np.mean(group_embeddings, axis=0)
                    canonical_entity['embedding'] = avg_embedding.tolist()
            
            canonical_entities.append(canonical_entity)
            
            # Update mentions with canonical ID
            for mention in group:
                updated_mention = mention.copy()
                updated_mention['resolved_canonical_id_temp'] = canon_id
                updated_mentions.append(updated_mention)
    
    # Cache the results
    if redis_mgr and redis_mgr.is_available():
        redis_mgr.set_cached(
            cache_key,
            {
                'canonical_entities': canonical_entities,
                'updated_mentions': updated_mentions
            },
            ttl=REDIS_ENTITY_CACHE_TTL
        )
    
    logger.info(f"Enhanced resolution complete: {len(canonical_entities)} canonical entities "
               f"from {len(entity_mentions_for_doc)} mentions")
    
    # Convert canonical entities to Pydantic models
    pydantic_canonical_entities = []
    for ce in canonical_entities:
        canonical_entity_model = CanonicalEntity(
            name=ce['canonicalName'],
            entity_type=ce['entity_type'],
            aliases=json.loads(ce['allKnownAliasesInDoc_json']),
            mention_count=ce['mention_count_in_doc'],
            first_seen_chunk_index=ce['firstSeenAtChunkIndex_int'],
            confidence=ce['confidence_score'],
            attributes={
                'canonicalEntityId_temp': ce['canonicalEntityId_temp'],
                'embedding': ce.get('embedding')  # Include embedding if available
            }
        )
        pydantic_canonical_entities.append(canonical_entity_model)
    
    return EntityResolutionResultModel(
        document_uuid=document_uuid,
        status=ProcessingResultStatus.SUCCESS,
        total_mentions=len(entity_mentions_for_doc),
        total_canonical_entities=len(pydantic_canonical_entities),
        canonical_entities=pydantic_canonical_entities,
        updated_mentions=updated_mentions,
        model_used="enhanced_resolution"
    )


def _generate_resolution_cache_key(entity_mentions: List[Dict], doc_text_snippet: str) -> str:
    """Generate cache key for entity resolution"""
    mentions_str = json.dumps([{
        'value': em['value'],
        'type': em['entity_type']
    } for em in entity_mentions], sort_keys=True)
    
    combined = mentions_str + doc_text_snippet[:500]
    return hashlib.md5(combined.encode()).hexdigest()


def cross_document_entity_linking(
    canonical_entities: List[Dict],
    db_manager: SupabaseManager,
    similarity_threshold: float = 0.85
) -> Dict[str, str]:
    """
    Link canonical entities across documents using embeddings.
    Returns mapping of temporary canonical IDs to global canonical IDs.
    """
    logger.info(f"Starting cross-document entity linking for {len(canonical_entities)} entities")
    
    id_mapping = {}
    
    for entity in canonical_entities:
        if 'embedding' not in entity:
            # No embedding - use string matching only
            continue
        
        entity_embedding = np.array(entity['embedding'])
        
        # Search for similar entities in the database
        try:
            # Use the database function to find similar entities
            similar_entities = db_manager.service_client.rpc(
                'find_similar_canonical_entities',
                {
                    'query_embedding': entity_embedding.tolist(),
                    'entity_type': entity['entity_type'],
                    'similarity_threshold': similarity_threshold,
                    'max_results': 5
                }
            ).execute()
            
            if similar_entities.data:
                # Found similar entity - use its ID
                best_match = similar_entities.data[0]
                logger.info(f"Linked '{entity['canonicalName']}' to existing entity "
                          f"'{best_match['canonicalName']}' (similarity: {best_match['similarity']:.3f})")
                id_mapping[entity['canonicalEntityId_temp']] = best_match['canonicalEntityId']
            
        except Exception as e:
            logger.warning(f"Error in cross-document linking: {e}")
    
    return id_mapping