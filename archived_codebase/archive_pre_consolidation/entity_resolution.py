# entity_resolution.py
import uuid
from datetime import datetime
from typing import List, Dict, Any, Tuple, Optional
from openai import OpenAI
import json
import re
import hashlib

# Import centralized Pydantic models
from scripts.core.processing_models import (
    EntityResolutionResultModel, CanonicalEntity, 
    ProcessingResultStatus
)

from scripts.config import LLM_API_KEY, LLM_MODEL_FOR_RESOLUTION, REDIS_ENTITY_CACHE_TTL
from scripts.cache import redis_cache, rate_limit, get_redis_manager

import logging
logger = logging.getLogger(__name__)

def _generate_resolution_cache_key(entity_mentions: List[Dict[str, Any]], doc_text_snippet: str) -> str:
    """Generate cache key for entity resolution"""
    # Create a deterministic representation of the mentions
    mentions_str = json.dumps([{
        'value': em['value'],
        'type': em['entity_type']
    } for em in entity_mentions], sort_keys=True)
    
    combined = mentions_str + doc_text_snippet[:500]  # Include first 500 chars of doc
    return hashlib.md5(combined.encode()).hexdigest()

def resolve_document_entities(entity_mentions_for_doc: List[Dict[str, Any]], 
                            document_text: str, 
                            document_uuid: Optional[uuid.UUID] = None) -> EntityResolutionResultModel:
    """
    Groups entity mentions using an LLM with Redis caching.
    
    Args:
        entity_mentions_for_doc: List of entity mention dictionaries
        document_text: Full document text for context
        document_uuid: UUID of the document being processed
    
    Returns:
        EntityResolutionResultModel with canonical entities and updated mentions
    """
    logger.info(f"Starting LLM-based entity resolution for {len(entity_mentions_for_doc)} mentions.")
    
    # Initialize result model
    result = EntityResolutionResultModel(
        document_uuid=document_uuid or uuid.uuid4(),
        total_mentions=len(entity_mentions_for_doc),
        canonical_entities=[],
        updated_mentions=entity_mentions_for_doc.copy(),
        status=ProcessingResultStatus.SUCCESS,
        model_used="fallback"
    )
    
    if not entity_mentions_for_doc:
        result.status = ProcessingResultStatus.SKIPPED
        result.message = "No entity mentions to resolve"
        return result
    
    if not LLM_API_KEY or LLM_API_KEY == "your_openai_api_key_if_not_in_env":
        logger.warning("OpenAI API key not configured. Using fallback resolution.")
        return _fallback_resolution(entity_mentions_for_doc, result)

    # Prepare context for LLM
    prompt_context = "Document Text Snip (first 1000 chars for context):\n" + document_text[:1000] + "\n\n"
    prompt_context += "Entity Mentions (Value, Type, Original Index):\n"
    for idx, em in enumerate(entity_mentions_for_doc):
        prompt_context += f"{idx}. \"{em['value']}\" ({em['entity_type']})\n"

    prompt = f"""{prompt_context}
    Task: Analyze the entity mentions above from the provided document snip.
    Group mentions that refer to the same real-world entity.
    For each group, choose the most complete or official name as the 'canonicalName'.
    List all unique mention values for that group as 'aliases'.
    Output a JSON list, where each item represents one canonical entity group:
    {{
      "canonicalName": "Canonical Name",
      "entity_type": "Entity Type (e.g., Person, Organization, Location, Date)",
      "aliases": ["mention1_value", "mention2_value", ...],
      "original_indices": [index_of_mention1, index_of_mention2, ...]
    }}
    Example for Person: [{{"canonicalName": "Johnathan Doe", "entity_type": "Person", "aliases": ["John Doe", "Mr. Doe", "J. Doe"], "original_indices": [0, 5, 12]}}]
    Ensure 'entity_type' is one of: Person, Organization, Location, Date. Normalize dates to YYYY-MM-DD if possible.
    """
    
    logger.debug(f"Sending prompt to LLM for entity resolution. Prompt length: {len(prompt)}")
    
    # Check cache first
    cache_key = f"resolution:{_generate_resolution_cache_key(entity_mentions_for_doc, document_text)}"
    try:
        redis_mgr = get_redis_manager()
        if redis_mgr and redis_mgr.is_available():
            cached_result = redis_mgr.get_cached(cache_key)
            if cached_result:
                logger.info("Entity resolution cache hit")
                # Reconstruct the expected return format from cached data
                result.canonical_entities = [CanonicalEntity(**ce) for ce in cached_result['canonical_entities']]
                result.updated_mentions = cached_result['updated_mentions']
                result.model_used = cached_result.get('model_used', 'cached')
                result.total_canonical_entities = len(result.canonical_entities)
                return result
    except Exception as e:
        logger.debug(f"Cache check error: {e}")

    try:
        # Initialize OpenAI client
        client = OpenAI(api_key=LLM_API_KEY)
        
        # Use gpt-4o-mini explicitly for entity resolution to avoid o4 model issues
        model_to_use = "gpt-4o-mini" if "o4" in LLM_MODEL_FOR_RESOLUTION else LLM_MODEL_FOR_RESOLUTION
        result.model_used = model_to_use

        # Apply rate limiting decorator manually since we can't decorate the inline function
        @rate_limit(key="openai", limit=50, window=60, wait=True, max_wait=300)
        def _make_api_call():
            return client.chat.completions.create(
                model=model_to_use,
                messages=[{"role": "user", "content": prompt}],
                temperature=1.0,
                max_completion_tokens=1024
            )
        
        response = _make_api_call()
        llm_output_str = response.choices[0].message.content
        logger.debug(f"LLM raw output for resolution: {llm_output_str}")
        
        # Extract JSON part from LLM response (it might add preamble/postamble)
        json_match = re.search(r'\[\s*\{.*\}\s*\]', llm_output_str, re.DOTALL)
        if not json_match:
            logger.error(f"Could not parse JSON from LLM response for entity resolution: {llm_output_str}")
            return _fallback_resolution(entity_mentions_for_doc, result)

        llm_resolved_groups = json.loads(json_match.group(0))
        
        canonical_entities_final = []
        updated_entity_mentions_final = list(entity_mentions_for_doc)  # Make a mutable copy

        temp_id_counter = 0
        for group in llm_resolved_groups:
            temp_canonical_id = f"temp_canon_{group['entity_type']}_{temp_id_counter}"
            temp_id_counter += 1

            # Find minimum chunk index for firstSeenAtChunkIndex_int
            min_chunk_index = float('inf')
            for original_idx in group["original_indices"]:
                if 0 <= original_idx < len(entity_mentions_for_doc):
                    chunk_idx = entity_mentions_for_doc[original_idx].get("chunk_index_int", 0)
                    min_chunk_index = min(min_chunk_index, chunk_idx)
            
            # Create canonical entity using Pydantic model
            try:
                canonical_entity = CanonicalEntity(
                    name=group["canonicalName"],
                    entity_type=group["entity_type"],
                    aliases=list(set(group["aliases"])),
                    mention_count=len(group["original_indices"]),
                    first_seen_chunk_index=min_chunk_index if min_chunk_index != float('inf') else 0,
                    confidence=0.9,  # High confidence for LLM resolution
                    attributes={}
                )
                canonical_entities_final.append(canonical_entity)
                
                # Update mentions with canonical entity reference
                for original_idx in group["original_indices"]:
                    if 0 <= original_idx < len(updated_entity_mentions_final):
                        updated_entity_mentions_final[original_idx]["resolved_canonical_id_temp"] = temp_canonical_id
                    else:
                        logger.warning(f"Original index {original_idx} from LLM out of bounds for entity mentions.")
                        
            except Exception as e:
                logger.warning(f"Failed to create CanonicalEntity from group data: {e}")
                continue
        
        # Update result
        result.canonical_entities = canonical_entities_final
        result.updated_mentions = updated_entity_mentions_final
        result.total_canonical_entities = len(canonical_entities_final)
        
        logger.info(f"LLM resolved {len(entity_mentions_for_doc)} mentions into {len(canonical_entities_final)} canonical entities.")
        
        # Cache the result
        try:
            if redis_mgr and redis_mgr.is_available():
                cache_data = {
                    'canonical_entities': [ce.model_dump() for ce in canonical_entities_final],
                    'updated_mentions': updated_entity_mentions_final,
                    'model_used': model_to_use
                }
                redis_mgr.set_cached(cache_key, cache_data, REDIS_ENTITY_CACHE_TTL)
                logger.debug(f"Cached entity resolution result")
        except Exception as e:
            logger.debug(f"Cache set error: {e}")
        
        return result

    except Exception as e:
        logger.error(f"Error during LLM entity resolution: {e}", exc_info=True)
        result.status = ProcessingResultStatus.FAILED
        result.error_message = str(e)
        return _fallback_resolution(entity_mentions_for_doc, result)

def _fallback_resolution(entity_mentions_for_doc: List[Dict[str, Any]], 
                        result: EntityResolutionResultModel) -> EntityResolutionResultModel:
    """
    Fallback resolution where each mention becomes its own canonical entity.
    
    Args:
        entity_mentions_for_doc: List of entity mention dictionaries
        result: Existing result model to update
    
    Returns:
        Updated EntityResolutionResultModel
    """
    logger.info("Using fallback resolution: each mention becomes its own canonical entity")
    
    canonical_entities = []
    updated_mentions = []
    
    for idx, em in enumerate(entity_mentions_for_doc):
        temp_canonical_id = f"temp_canon_{em['entity_type']}_{idx}"
        
        try:
            canonical_entity = CanonicalEntity(
                name=em["value"],
                entity_type=em["entity_type"],
                aliases=[em["value"]],
                mention_count=1,
                first_seen_chunk_index=em.get("chunk_index_int", 0),
                confidence=0.7,  # Lower confidence for fallback
                attributes=em.get("attributes_json", {})
            )
            canonical_entities.append(canonical_entity)
            
            em_updated = em.copy()
            em_updated["resolved_canonical_id_temp"] = temp_canonical_id
            updated_mentions.append(em_updated)
            
        except Exception as e:
            logger.warning(f"Failed to create fallback CanonicalEntity for mention: {e}")
            continue
    
    result.canonical_entities = canonical_entities
    result.updated_mentions = updated_mentions
    result.total_canonical_entities = len(canonical_entities)
    result.model_used = "fallback"
    result.status = ProcessingResultStatus.SUCCESS
    result.message = "Used fallback resolution due to API unavailability"
    
    return result