# entity_extraction.py
import re
import dateparser # For date parsing
import json
import hashlib
import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional

# Import centralized Pydantic models
from scripts.core.processing_models import (
    EntityExtractionResultModel, ExtractedEntity,
    ProcessingResultStatus
)
from scripts.core.schemas import EntityMentionModel

from scripts.config import (NER_GENERAL_MODEL, ENTITY_TYPE_SCHEMA_MAP, 
                    USE_OPENAI_FOR_ENTITY_EXTRACTION, DEPLOYMENT_STAGE,
                    OPENAI_API_KEY, LLM_MODEL_FOR_RESOLUTION,
                    REDIS_LLM_CACHE_TTL, REDIS_ENTITY_CACHE_TTL) # Add domain-specific models if configured
from scripts.models_init import get_ner_pipeline # Import the getter function instead
from openai import OpenAI
from scripts.cache import redis_cache, get_redis_manager, rate_limit

import logging
logger = logging.getLogger(__name__)

def extract_entities_from_chunk(chunk_text: str, chunk_id: Optional[uuid.UUID] = None, 
                               db_manager=None, use_openai: bool = None) -> EntityExtractionResultModel:
    """Stage-aware entity extraction with OpenAI fallback.
    
    Args:
        chunk_text: Text to extract entities from
        chunk_id: UUID of the chunk (optional)
        db_manager: Database manager (optional, for compatibility)
        use_openai: Force OpenAI usage (defaults to config setting)
    
    Returns:
        EntityExtractionResultModel with validated entities
    """
    if not chunk_text:
        return EntityExtractionResultModel(
            document_uuid=uuid.uuid4(),  # Will be set by caller
            chunk_id=chunk_id,
            text_length=0,
            status=ProcessingResultStatus.SKIPPED
        )
    
    # Create result model
    result = EntityExtractionResultModel(
        document_uuid=uuid.uuid4(),  # Will be set by caller
        chunk_id=chunk_id,
        text_length=len(chunk_text),
        status=ProcessingResultStatus.SUCCESS
    )
    
    # Determine whether to use OpenAI
    if use_openai is None:
        use_openai = USE_OPENAI_FOR_ENTITY_EXTRACTION or DEPLOYMENT_STAGE == "1"
    
    try:
        # Stage 1 or forced OpenAI: Use OpenAI exclusively
        if use_openai:
            entities = extract_entities_openai(chunk_text, chunk_id)
            result.model_used = "gpt-4o-mini"
        else:
            # Stages 2-3: Try local NER first, fall back to OpenAI
            try:
                entities = extract_entities_local_ner(chunk_text, chunk_id)
                result.model_used = NER_GENERAL_MODEL
            except Exception as e:
                logger.warning(f"Local NER failed for chunk {chunk_id}: {e}")
                entities = extract_entities_openai(chunk_text, chunk_id)
                result.model_used = "gpt-4o-mini"
        
        # Convert to ExtractedEntity models
        extracted_entities = []
        for entity_data in entities:
            try:
                extracted_entity = ExtractedEntity(
                    text=entity_data.get("value", ""),
                    type=entity_data.get("entity_type", "Miscellaneous"),
                    start_offset=entity_data.get("offsetStart"),
                    end_offset=entity_data.get("offsetEnd"),
                    confidence=entity_data.get("confidence", 0.8),
                    context=entity_data.get("leadingText", "") + entity_data.get("trailingText", ""),
                    attributes=entity_data.get("attributes_json", {})
                )
                extracted_entities.append(extracted_entity)
            except Exception as e:
                logger.warning(f"Failed to create ExtractedEntity from data: {e}")
                continue
        
        # Update result with entities
        result.entities = extracted_entities
        
        logger.info(f"Extracted {len(extracted_entities)} entities from chunk {chunk_id}")
        return result
        
    except Exception as e:
        logger.error(f"Entity extraction failed for chunk {chunk_id}: {e}", exc_info=True)
        result.status = ProcessingResultStatus.FAILED
        result.error_message = str(e)
        return result

def _generate_entity_cache_key(chunk_text: str, model: str) -> str:
    """Generate cache key for entity extraction results."""
    text_hash = hashlib.md5(chunk_text.encode()).hexdigest()
    return f"entity:openai:{model}:{text_hash}"

@redis_cache(prefix="entity:openai", ttl=REDIS_ENTITY_CACHE_TTL, key_func=lambda chunk_text, chunk_id=None: _generate_entity_cache_key(chunk_text[:1500], "gpt-4o-mini"))
@rate_limit(key="openai", limit=50, window=60, wait=True, max_wait=300)  # 50 requests per minute
def extract_entities_openai(chunk_text: str, chunk_id: Optional[uuid.UUID] = None) -> List[Dict[str, Any]]:
    """OpenAI-based entity extraction for Stage 1 with Redis caching and rate limiting."""
    if not OPENAI_API_KEY:
        logger.error("OPENAI_API_KEY not set. Cannot perform OpenAI entity extraction.")
        print("ERROR: OPENAI_API_KEY not set!")
        return []
    
    logger.info(f"Starting OpenAI entity extraction for chunk {chunk_id}")
    print(f"DEBUG: OPENAI_API_KEY exists: {bool(OPENAI_API_KEY)}")
    
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        
        prompt = f"""You are an expert Legal Document Entity Extraction Specialist AI.
Your primary goal is to meticulously analyze legal text and extract named entities, returning them as a valid JSON object.
ABSOLUTELY NO additional text, explanations, or markdown formatting outside the JSON is permitted.

Extract named entities from the provided legal document text. Return a JSON object with an "entities" array where each object strictly adheres to this structure:
{{
    "entities": [
        {{
            "entity": "exact_entity_text_from_document",
            "label": "CHOSEN_ENTITY_LABEL",
            "start": start_character_offset_0_indexed,
            "end": end_character_offset_0_indexed_exclusive,
            "confidence": 0.95
        }}
    ]
}}

Use ONLY the following entity labels and their definitions. Ensure the `label` value is one of these exact strings:
- PERSON: Names of individuals (e.g., judges, lawyers, parties, clerks). Example: "JOAN M. GILMER", "Meranda Ory".
- ORG: Organizations, companies, law firms, courts. Example: "ROESLEIN & ASSOCIATES", "CIRCUIT COURT OF ST. LOUIS COUNTY".
- GPE: Geopolitical Entities - cities, counties, states, countries. Example: "ST. LOUIS COUNTY, MO", "MISSOURI".
- DATE: Specific dates, months with years, or full date-times. Example: "04/11/2025", "March 11, 2025", "April 25, 2025".
- MONEY: Monetary amounts, financial figures. Example: "$10,000.00" or "five hundred dollars".
- LAW: Specific statutes, regulations, legal codes, or named legal document types/orders/motions. Example: "PROPOSED SCHEDULING ORDER", "Motions in Limine", "summary judgment".
- CASE: Case names, case numbers, or legal precedents. Example: "Case No: 22SL-CC02572".
- OTHER: Other legally relevant terms, roles, or specific identifiers not fitting the above categories. Example: "Plaintiff", "Defendant", "Parties", "CIRCUIT CLERK", "Division No. 15".

Key Instructions for Extraction:
1. **Accuracy**: The `entity` text MUST be an EXACT substring from the original document. Calculate accurate start/end character positions.
2. **Comprehensiveness**: Extract ALL relevant entities that match the provided definitions. Do not omit any.
3. **Specificity**: If an entity could fit multiple labels, choose the MOST specific and legally relevant one.
4. **Consistency**: Apply labels consistently based on their definitions.

Text to analyze:
{chunk_text[:1500]}

Return only valid JSON object with entities array:"""

        logger.info(f"Calling OpenAI API with model: {LLM_MODEL_FOR_RESOLUTION}")
        logger.debug(f"Prompt length: {len(prompt)} chars")
        print(f"DEBUG: Model={LLM_MODEL_FOR_RESOLUTION}, Prompt length={len(prompt)}")
        
        # Use gpt-4o-mini explicitly for entity extraction to avoid o4 model issues
        model_to_use = "gpt-4o-mini" if "o4" in LLM_MODEL_FOR_RESOLUTION else LLM_MODEL_FOR_RESOLUTION
        
        response = client.chat.completions.create(
            model=model_to_use,
            messages=[
                {"role": "system", "content": "You are a specialized JSON API for legal entity extraction. Your response must be a valid JSON object that can be parsed by json.loads(). Never include markdown formatting, code blocks, or any text outside the JSON structure. The response must start with '{' and end with '}'."},
                {"role": "user", "content": prompt}
            ],
            temperature=1.0,
            max_completion_tokens=2000,
            response_format={"type": "json_object"}
        )
        
        print(f"DEBUG: Response={response}")
        
        if not response.choices:
            logger.error("OpenAI returned no choices!")
            print("ERROR: No choices in response")
            return []
            
        if not response.choices[0].message:
            logger.error("OpenAI returned no message!")
            print("ERROR: No message in first choice")
            return []
            
        response_text = response.choices[0].message.content
        print(f"DEBUG: Raw content={repr(response_text)}")
        
        if response_text is None:
            logger.error("OpenAI message content is None!")
            print("ERROR: Message content is None")
            return []
            
        response_text = response_text.strip()
        
        # Log the raw response for debugging
        logger.info(f"OpenAI raw response length: {len(response_text)}")
        if response_text:
            logger.info(f"OpenAI raw response: {response_text[:500]}...")
        else:
            logger.error("OpenAI returned empty response after stripping!")
            return []
        
        # Parse JSON response
        try:
            response_json = json.loads(response_text)
            
            # Handle both array and object with entities key
            if isinstance(response_json, dict) and 'entities' in response_json:
                entities_raw = response_json['entities']
            elif isinstance(response_json, list):
                entities_raw = response_json
            else:
                logger.error("OpenAI entity extraction returned unexpected format")
                return []
            
            # Format entities to match expected structure
            formatted_entities = []
            for entity in entities_raw:
                if isinstance(entity, dict) and all(key in entity for key in ['entity', 'label']):
                    # Map OpenAI labels to schema entity types
                    schema_entity_type = ENTITY_TYPE_SCHEMA_MAP.get(entity['label'].upper(), "Miscellaneous")
                    
                    mention_data = {
                        "value": str(entity['entity']),
                        "normalizedValue": str(entity['entity']).lower().strip(" .,;:!?"),
                        "displayValue": str(entity['entity']),
                        "entity_type": schema_entity_type,
                        "rationale": f"OpenAI extraction confidence: high",
                        "offsetStart": entity.get('start', 0),
                        "offsetEnd": entity.get('end', len(str(entity['entity']))),
                        "isPartial": False,
                        "leadingText": "",
                        "trailingText": "",
                        "attributes_json": {},
                        "confidence": float(entity.get('confidence', 0.9))
                    }
                    
                    # Add basic attribute extraction
                    entity_text = str(entity['entity'])
                    
                    # Email extraction
                    email_match = re.search(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', entity_text)
                    if email_match:
                        mention_data["email"] = email_match.group(0)
                    
                    # Phone extraction (basic North American)
                    phone_match = re.search(r'(\b(?:(?:\+?1\s*(?:[.-]\s*)?)?(?:\(\s*([2-9]1[02-9]|[2-9][02-8]1|[2-9][02-8][02-9])\s*\)|([2-9]1[02-9]|[2-9][02-8]1|[2-9][02-8][02-9]))\s*(?:[.-]\s*)?)?([2-9]1[02-9]|[2-9][02-9]1|[2-9][02-9]{2})\s*(?:[.-]\s*)?([0-9]{4})(?:\s*(?:#|x\.?|ext\.?|extension)\s*(\d+))?\b)', entity_text)
                    if phone_match:
                        mention_data["phone"] = phone_match.group(0)
                    
                    # Date parsing for DATE entities
                    if entity['label'].upper() == 'DATE':
                        parsed_date = dateparser.parse(entity_text)
                        if parsed_date:
                            mention_data["normalizedValue"] = parsed_date.strftime('%Y-%m-%d')
                            mention_data["attributes_json"]["normalized_date_iso"] = parsed_date.strftime('%Y-%m-%d')
                    
                    formatted_entities.append(mention_data)
            
            logger.info(f"OpenAI extracted {len(formatted_entities)} entities from chunk {chunk_id}")
            return formatted_entities
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse OpenAI entity extraction JSON: {e}")
            logger.error(f"Response text was: {response_text[:500]}...")
            
            # Try to extract JSON from markdown code blocks
            json_match = re.search(r'```(?:json)?\s*(\[[\s\S]*?\])\s*```', response_text)
            if json_match:
                try:
                    entities_raw = json.loads(json_match.group(1))
                    logger.info("Successfully extracted JSON from code block")
                    # Continue processing with the same logic
                    formatted_entities = []
                    for entity in entities_raw:
                        if isinstance(entity, dict) and all(key in entity for key in ['entity', 'label']):
                            schema_entity_type = ENTITY_TYPE_SCHEMA_MAP.get(entity['label'].upper(), "Miscellaneous")
                            mention_data = {
                                "value": str(entity['entity']),
                                "entity_type": schema_entity_type,
                                "chunk_id": chunk_id,
                                "confidence": float(entity.get('confidence', 0.8)),
                                "leadingText": "",
                                "trailingText": "",
                                "attributes_json": {},
                                "offsetStart": entity.get('start', 0),
                                "offsetEnd": entity.get('end', len(str(entity['entity'])))
                            }
                            formatted_entities.append(mention_data)
                    return formatted_entities
                except:
                    pass
            return []
            
    except Exception as e:
        logger.error(f"OpenAI entity extraction failed for chunk {chunk_id}: {type(e).__name__}: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        # Print to console for debugging
        print(f"ERROR in extract_entities_openai: {type(e).__name__}: {e}")
        traceback.print_exc()
        return []

@redis_cache(prefix="entity:local", ttl=REDIS_ENTITY_CACHE_TTL, key_func=lambda chunk_text, chunk_id=None: f"entity:local:ner:{hashlib.md5(chunk_text.encode()).hexdigest()}")
def extract_entities_local_ner(chunk_text: str, chunk_id: Optional[uuid.UUID] = None) -> List[Dict[str, Any]]:
    """Original local NER pipeline extraction (for stages 2-3) with Redis caching."""
    NER_PIPELINE = get_ner_pipeline()
    if not NER_PIPELINE:
        raise ValueError("Local NER pipeline not available")
    
    extracted_mentions_data = []
    try:
        # NER_PIPELINE (with grouped_entities=True) returns list of dicts:
        # [{'entity_group': 'ORG', 'score': 0.99, 'word': 'Acme Corp', 'start': 10, 'end': 19}]
        ner_results = NER_PIPELINE(chunk_text)
    except Exception as e:
        logger.error(f"Error during local NER processing for chunk: {e}", exc_info=True)
        raise

    # Store existing entity positions to avoid overlap with date regex
    existing_entity_spans = set()
    for entity in ner_results:
        for i in range(entity['start'], entity['end']):
            existing_entity_spans.add(i)

    # Date Extraction using dateparser
    date_pattern = r'\b(?:\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|\d{4}[-/]\d{1,2}[-/]\d{1,2}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s\d{1,2},?\s\d{4}|\d{1,2}\s(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s\d{4})\b'
    for match in re.finditer(date_pattern, chunk_text):
        start, end = match.span()
        # Check for overlap
        is_overlapping = any(i in existing_entity_spans for i in range(start, end))
        if not is_overlapping:
            date_text = match.group(0)
            parsed_date = dateparser.parse(date_text)
            if parsed_date:
                # Add to ner_results
                ner_results.append({
                    'entity_group': 'DATE', # Special group for dates
                    'score': 0.95, # Placeholder confidence
                    'word': date_text,
                    'start': start,
                    'end': end,
                    'normalized_date': parsed_date.strftime('%Y-%m-%d') # Normalized form
                })
                for i in range(start, end): existing_entity_spans.add(i)

    for entity in ner_results:
        entity_group_from_model = entity["entity_group"]
        schema_entity_type = ENTITY_TYPE_SCHEMA_MAP.get(entity_group_from_model.upper(), "Miscellaneous") # Map and default

        # If 'MISC' from model and it looks like a date, try to parse it
        if entity_group_from_model.upper() == "MISC":
            parsed_date_misc = dateparser.parse(entity["word"])
            if parsed_date_misc:
                schema_entity_type = ENTITY_TYPE_SCHEMA_MAP.get("DATE")
                entity["normalized_date"] = parsed_date_misc.strftime('%Y-%m-%d')

        mention_data = {
            "value": entity["word"],
            "normalizedValue": entity["word"].lower().strip(" .,;:!?"),
            "displayValue": entity["word"],
            "entity_type": schema_entity_type, # Use mapped type
            "rationale": f"NER confidence: {entity['score']:.2f}", # Basic rationale
            "offsetStart": entity["start"],
            "offsetEnd": entity["end"],
            "isPartial": False, # Advanced logic could mark partial mentions
            "leadingText": chunk_text[:entity["start"]][-50:] if entity["start"] > 0 else "",
            "trailingText": chunk_text[entity["end"]:][:50] if entity["end"] < len(chunk_text) else "",
            "attributes_json": {}, # For additional attributes like normalized_date
            "confidence": float(entity["score"])
        }

        # --- Basic Attribute Extraction (can be significantly expanded) ---
        # Email
        email_match = re.search(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', entity["word"]) # If entity IS email
        if not email_match: # Search context if entity is not email itself
             context_window = chunk_text[max(0, entity["start"]-30):min(len(chunk_text), entity["end"]+30)]
             email_match = re.search(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', context_window)
        if email_match:
            mention_data["email"] = email_match.group(0)

        # Phone (very basic North American example)
        phone_match = re.search(r'(\b(?:(?:\+?1\s*(?:[.-]\s*)?)?(?:\(\s*([2-9]1[02-9]|[2-9][02-8]1|[2-9][02-8][02-9])\s*\)|([2-9]1[02-9]|[2-9][02-8]1|[2-9][02-8][02-9]))\s*(?:[.-]\s*)?)?([2-9]1[02-9]|[2-9][02-9]1|[2-9][02-9]{2})\s*(?:[.-]\s*)?([0-9]{4})(?:\s*(?:#|x\.?|ext\.?|extension)\s*(\d+))?\b)', entity["word"])
        if not phone_match:
            context_window = chunk_text[max(0, entity["start"]-30):min(len(chunk_text), entity["end"]+30)]
            phone_match = re.search(r'(\b(?:(?:\+?1\s*(?:[.-]\s*)?)?(?:\(\s*([2-9]1[02-9]|[2-9][02-8]1|[2-9][02-8][02-9])\s*\)|([2-9]1[02-9]|[2-9][02-8]1|[2-9][02-8][02-9]))\s*(?:[.-]\s*)?)?([2-9]1[02-9]|[2-9][02-9]1|[2-9][02-9]{2})\s*(?:[.-]\s*)?([0-9]{4})(?:\s*(?:#|x\.?|ext\.?|extension)\s*(\d+))?\b)', context_window)

        if phone_match:
            mention_data["phone"] = phone_match.group(0)

        # TODO: Add more sophisticated attribute extraction for websites, addresses (pyap)
        # TODO: LLM for complex attribute extraction or rationale enhancement if configured

        if "normalized_date" in entity: # If date was parsed
            mention_data["normalizedValue"] = entity["normalized_date"] # Override normalizedValue with ISO date
            mention_data["attributes_json"]["normalized_date_iso"] = entity["normalized_date"]
        
        extracted_mentions_data.append(mention_data)
        logger.debug(f"Extracted entity: {mention_data['value']} as {mention_data['entity_type']}")

    logger.info(f"Local NER extracted {len(extracted_mentions_data)} entities from chunk {chunk_id}")
    return extracted_mentions_data