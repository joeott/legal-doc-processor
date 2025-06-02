"""
Entity extraction fixes for minimal models and limited entity types
"""

import os
import re
from typing import Dict, List, Any, Optional
from uuid import UUID
import logging

logger = logging.getLogger(__name__)

# Limited entity types we want to extract
ALLOWED_ENTITY_TYPES = {'PERSON', 'ORG', 'LOCATION', 'DATE'}

# Mapping from OpenAI entity types to our minimal model types
ENTITY_TYPE_MAPPING = {
    'PERSON': 'PERSON',
    'PEOPLE': 'PERSON',
    'NAME': 'PERSON',
    'ATTORNEY': 'PERSON',
    'JUDGE': 'PERSON',
    
    'ORG': 'ORG',
    'ORGANIZATION': 'ORG',
    'COMPANY': 'ORG',
    'CORPORATION': 'ORG',
    'COURT': 'ORG',
    'LAW_FIRM': 'ORG',
    
    'LOCATION': 'LOCATION',
    'PLACE': 'LOCATION',
    'ADDRESS': 'LOCATION',
    'CITY': 'LOCATION',
    'STATE': 'LOCATION',
    'COUNTRY': 'LOCATION',
    
    'DATE': 'DATE',
    'TIME': 'DATE',
    'DATETIME': 'DATE',
    'YEAR': 'DATE',
    
    # Map everything else to None (will be filtered out)
    'LEGAL_ENTITY': None,
    'CASE_NUMBER': None,
    'MONEY': None,
    'STATUTE': None,
    'OTHER': None
}


def fix_entity_type(entity_type: str) -> Optional[str]:
    """
    Map OpenAI entity types to our allowed types.
    Returns None if the entity type should be filtered out.
    """
    entity_type_upper = entity_type.upper()
    
    # Direct mapping
    if entity_type_upper in ENTITY_TYPE_MAPPING:
        return ENTITY_TYPE_MAPPING[entity_type_upper]
    
    # Check if it's already an allowed type
    if entity_type_upper in ALLOWED_ENTITY_TYPES:
        return entity_type_upper
    
    # Default to None (filter out)
    logger.debug(f"Filtering out entity type: {entity_type}")
    return None


def create_openai_prompt_for_limited_entities() -> str:
    """
    Create an OpenAI prompt that only extracts Person, Org, Location, and Date entities.
    """
    return """Extract entities from the following text. Only extract these entity types:
- PERSON: Names of people (including attorneys, judges, etc.)
- ORG: Organizations, companies, courts, law firms, etc.
- LOCATION: Places, addresses, cities, states, countries
- DATE: Dates, times, years

Return the entities as a JSON array with this format:
[
  {
    "text": "entity text",
    "type": "PERSON|ORG|LOCATION|DATE",
    "start": start_position,
    "end": end_position,
    "confidence": 0.0-1.0
  }
]

Do not include case numbers, money amounts, statutes, or other legal entities.
Only return the JSON array, no other text."""


def filter_and_fix_entities(entities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Filter entities to only include allowed types and fix type names.
    """
    fixed_entities = []
    
    for entity in entities:
        # Get entity type
        entity_type = entity.get('type') or entity.get('entity_type')
        if not entity_type:
            logger.debug(f"Skipping entity without type: {entity}")
            continue
        
        # Fix entity type
        fixed_type = fix_entity_type(entity_type)
        if not fixed_type:
            # Skip this entity
            continue
        
        # Create fixed entity
        fixed_entity = entity.copy()
        fixed_entity['type'] = fixed_type
        fixed_entity['entity_type'] = fixed_type
        
        fixed_entities.append(fixed_entity)
    
    logger.info(f"Filtered {len(entities)} entities to {len(fixed_entities)} allowed entities")
    return fixed_entities


def create_minimal_entity_mention(
    entity_data: Dict[str, Any],
    chunk_uuid: UUID,
    document_uuid: UUID,
    mention_uuid: UUID
) -> Dict[str, Any]:
    """
    Create entity mention data compatible with minimal model.
    """
    return {
        'mention_uuid': mention_uuid,
        'chunk_uuid': chunk_uuid,
        'document_uuid': document_uuid,
        'entity_text': entity_data.get('text', ''),
        'entity_type': entity_data.get('type', 'OTHER'),
        'start_char': int(entity_data.get('start', 0)),
        'end_char': int(entity_data.get('end', 0)),
        'confidence_score': float(entity_data.get('confidence', 0.8))
    }