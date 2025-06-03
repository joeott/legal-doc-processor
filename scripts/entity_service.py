"""
Unified Entity Service for the PDF processing pipeline.
Combines entity extraction, resolution, enhancement, and structured extraction.
"""

import os
import re
import json
import hashlib
import uuid
import logging
import numpy as np
import dateparser
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple, Union
from collections import defaultdict
from openai import OpenAI

# Import configuration
from scripts.config import (
    NER_GENERAL_MODEL, ENTITY_TYPE_SCHEMA_MAP,
    USE_OPENAI_FOR_ENTITY_EXTRACTION, DEPLOYMENT_STAGE,
    OPENAI_API_KEY, LLM_API_KEY, LLM_MODEL_FOR_RESOLUTION,
    REDIS_LLM_CACHE_TTL, REDIS_ENTITY_CACHE_TTL, REDIS_STRUCTURED_CACHE_TTL
)

# Import Pydantic models
from scripts.models import (
    EntityMentionMinimal as EntityMentionModel,
    CanonicalEntityMinimal as CanonicalEntity,
    ProcessingResultStatus,
    ProcessingResult
)

# Import processing models that don't exist in models.py yet
# TODO: These need to be migrated or removed
from scripts.core.processing_models import (
    EntityExtractionResultModel, ExtractedEntity,
    EntityResolutionResultModel,
    DocumentMetadata, KeyFact, EntitySet, ExtractedRelationship,
    StructuredChunkData, StructuredExtractionResultModel
)

# Import utilities
from scripts.cache import redis_cache, get_redis_manager, rate_limit, CacheKeys
from scripts.db import DatabaseManager

logger = logging.getLogger(__name__)


# ========== Entity Service ==========

class EntityService:
    """
    Unified entity extraction, resolution, and enhancement service with conformance validation.
    Combines all entity-related operations into a single, cohesive service.
    """
    
    def __init__(self, db_manager: DatabaseManager, openai_api_key: Optional[str] = None, use_openai: Optional[bool] = None):
        """
        Initialize entity service with database manager and validation.
        
        Args:
            db_manager: Database manager with conformance validation
            openai_api_key: OpenAI API key (defaults to config)
            use_openai: Force OpenAI usage (defaults to config setting)
            
        Raises:
            ConformanceError: If schema validation fails
            ValueError: If database manager is invalid
        """
        # Validate inputs
        if not isinstance(db_manager, DatabaseManager):
            raise ValueError("Valid DatabaseManager instance required")
        
        self.db = db_manager
        
        # Validate conformance on initialization
        try:
            self.db.validate_conformance()
            logger.info("Entity service initialized with validated database conformance")
        except Exception as e:
            logger.error(f"Database conformance validation failed: {e}")
            raise ConformanceError(f"Entity service initialization failed: {str(e)}")
        self.api_key = openai_api_key or OPENAI_API_KEY or LLM_API_KEY
        self.use_openai = use_openai if use_openai is not None else USE_OPENAI_FOR_ENTITY_EXTRACTION
        
        # Stage 1: Force OpenAI usage
        if DEPLOYMENT_STAGE == "1":  # Stage 1 always uses cloud services
            logger.info("Stage 1 deployment: Using OpenAI for entity operations")
            self.use_openai = True
        
        # Initialize clients
        self.openai_client = None
        if self.api_key:
            try:
                self.openai_client = OpenAI(api_key=self.api_key)
                logger.info("OpenAI client initialized for entity service")
            except Exception as e:
                logger.error(f"Failed to initialize OpenAI client: {e}")
        
        # Initialize local NER pipeline if not using OpenAI
        self.ner_pipeline = None
        if not self.use_openai and DEPLOYMENT_STAGE != "1":
            # Local models only available in Stage 2 and 3
            logger.warning("Local NER pipeline not available in Stage 1 deployment")
            self.ner_pipeline = None
        
        # Initialize Redis
        self.redis_manager = get_redis_manager()
    
    # ========== Entity Extraction ==========
    
    def extract_entities_from_chunk(
        self,
        chunk_text: str,
        chunk_uuid: uuid.UUID,
        document_uuid: str,
        use_openai: Optional[bool] = None
    ):
        """
        Extract entities from a text chunk with full validation.
        
        Args:
            chunk_text: Text to extract entities from
            chunk_uuid: UUID of the chunk
            document_uuid: UUID of the document
            use_openai: Override OpenAI usage
            
        Returns:
            EntityExtractionResult with status and extracted entities
            
        Raises:
            ConformanceError: If schema validation fails
            ValueError: If input validation fails
        """
        logger.info(f"Extracting entities from chunk {chunk_uuid}")
        
        try:
            # 1. Validate conformance (skip if configured)
            if os.getenv('SKIP_CONFORMANCE_CHECK', '').lower() != 'true':
                validate_before_operation("entity extraction")
            else:
                logger.debug("Skipping conformance validation for entity extraction")
            
            # 2. Validate inputs
            self._validate_extraction_inputs(chunk_text, chunk_uuid, document_uuid)
            
            # 3. Check cache first
            cache_key = f"entity:chunk:{chunk_uuid}:{hashlib.md5(chunk_text.encode()).hexdigest()[:8]}"
            cached_entities = self.redis_manager.get_cached(cache_key)
            
            if cached_entities:
                logger.info(f"Using cached entities for chunk {chunk_uuid}")
                # Deserialize and return result object
                from scripts.entity_result_wrapper import EntityExtractionResult
                entities = self._deserialize_entity_mentions(cached_entities, chunk_uuid, document_uuid)
                return EntityExtractionResult(
                    status=ProcessingResultStatus.SUCCESS,
                    document_uuid=document_uuid,
                    chunk_uuid=chunk_uuid,
                    entity_mentions=entities,
                    canonical_entities=[],
                    extraction_metadata={
                        "method": "cached",
                        "entity_count": len(entities),
                        "chunk_size": len(chunk_text)
                    }
                )
            
            # 4. Extract entities
            entity_mentions = self._perform_entity_extraction(
                chunk_text, chunk_uuid, document_uuid, use_openai
            )
            
            # 5. Validate extracted entities
            validated_entities = self._validate_extracted_entities(entity_mentions)
            
            # 6. Cache results
            serialized_entities = [entity.model_dump() for entity in validated_entities]
            self.redis_manager.set_cached(cache_key, serialized_entities, ttl=REDIS_ENTITY_CACHE_TTL)
            
            logger.info(f"Successfully extracted {len(validated_entities)} entities from chunk {chunk_uuid}")
            
            # Return result object
            from scripts.entity_result_wrapper import EntityExtractionResult
            return EntityExtractionResult(
                status=ProcessingResultStatus.SUCCESS,
                document_uuid=document_uuid,
                chunk_uuid=chunk_uuid,
                entity_mentions=validated_entities,
                canonical_entities=[],  # Will be populated during entity resolution
                extraction_metadata={
                    "method": "openai" if use_openai else "local",
                    "entity_count": len(validated_entities),
                    "chunk_size": len(chunk_text)
                }
            )
            
        except ConformanceError:
            raise
        except Exception as e:
            logger.error(f"Entity extraction failed for chunk {chunk_uuid}: {e}")
            # Return failure result instead of raising
            from scripts.entity_result_wrapper import EntityExtractionResult
            return EntityExtractionResult(
                status=ProcessingResultStatus.FAILED,
                document_uuid=document_uuid,
                chunk_uuid=chunk_uuid,
                entity_mentions=[],
                canonical_entities=[],
                extraction_metadata={
                    "error": str(e),
                    "method": "openai" if use_openai else "local"
                }
            )
    
    def _validate_extraction_inputs(self, chunk_text: str, chunk_uuid: uuid.UUID, document_uuid: str):
        """Validate inputs for entity extraction."""
        if not isinstance(chunk_text, str):
            raise ValueError(f"chunk_text must be a string, got {type(chunk_text)}")
        
        if not chunk_text.strip():
            raise ValueError("chunk_text cannot be empty")
        
        if not isinstance(chunk_uuid, uuid.UUID):
            raise ValueError(f"chunk_uuid must be a UUID, got {type(chunk_uuid)}")
        
        if not isinstance(document_uuid, str):
            raise ValueError(f"document_uuid must be a string, got {type(document_uuid)}")
        
        try:
            uuid.UUID(document_uuid)
        except ValueError:
            raise ValueError(f"Invalid document_uuid format: {document_uuid}")
        
        # Validate text length
        if len(chunk_text) > 10000:
            logger.warning(f"Large chunk text: {len(chunk_text)} characters")
    
    def _perform_entity_extraction(
        self, 
        chunk_text: str, 
        chunk_uuid: uuid.UUID, 
        document_uuid: str,
        use_openai: Optional[bool] = None
    ) -> List[EntityMentionModel]:
        """Perform the actual entity extraction."""
        use_openai = use_openai if use_openai is not None else self.use_openai
        
        if use_openai and self.openai_client:
            raw_entities = self._extract_entities_openai_validated(chunk_text)
        else:
            raw_entities = self._extract_entities_local_ner_validated(chunk_text)
        
        # Convert to EntityMentionModel instances
        entity_mentions = []
        for i, entity_data in enumerate(raw_entities):
            try:
                # Create entity with minimal model fields
                entity_data_minimal = {
                    'mention_uuid': uuid.uuid4(),
                    'document_uuid': document_uuid,
                    'chunk_uuid': chunk_uuid,
                    'entity_text': entity_data['text'],
                    'entity_type': entity_data['type'],
                    'confidence_score': entity_data.get('confidence', 0.8),
                    'start_char': entity_data.get('start_char', 0),
                    'end_char': entity_data.get('end_char', len(entity_data['text'])),
                    'created_at': datetime.utcnow()
                }
                
                # Add optional fields only if not using minimal models
                if not os.getenv('USE_MINIMAL_MODELS', '').lower() == 'true':
                    entity_data_minimal['processing_metadata'] = {
                        "extraction_method": "openai" if use_openai else "local_ner",
                        "chunk_position": i,
                        "extracted_at": datetime.utcnow().isoformat()
                    }
                
                entity_mention = EntityMentionModel(**entity_data_minimal)
                
                # Model is validated on creation
                entity_mentions.append(entity_mention)
                
            except Exception as e:
                logger.warning(f"Failed to create entity mention {i}: {e}")
                continue
        
        return entity_mentions
    
    def _validate_extracted_entities(self, entities: List[EntityMentionModel]) -> List[EntityMentionModel]:
        """Validate extracted entity mentions."""
        validated_entities = []
        
        for entity in entities:
            try:
                # Validate entity text is not empty
                if not entity.entity_text.strip():
                    logger.warning("Skipping entity with empty text")
                    continue
                
                # Validate confidence score
                if entity.confidence_score < 0 or entity.confidence_score > 1:
                    logger.warning(f"Invalid confidence score: {entity.confidence_score}")
                    entity.confidence_score = max(0, min(1, entity.confidence_score))
                
                # Validate character positions
                if entity.start_char < 0 or entity.end_char <= entity.start_char:
                    logger.warning(f"Invalid character positions for entity: {entity.start_char}-{entity.end_char}")
                    entity.start_char = 0
                    entity.end_char = len(entity.entity_text)
                
                # Model is already validated
                validated_entities.append(entity)
                
            except Exception as e:
                logger.warning(f"Failed to validate entity {entity.entity_text}: {e}")
                continue
        
        return validated_entities
    
    def _deserialize_entity_mentions(
        self, 
        cached_data: List[Dict], 
        chunk_uuid: uuid.UUID, 
        document_uuid: str
    ) -> List[EntityMentionModel]:
        """Deserialize cached entity mentions."""
        entities = []
        
        for data in cached_data:
            try:
                # Update UUIDs for current context
                data['chunk_uuid'] = chunk_uuid
                data['document_uuid'] = document_uuid
                
                entity = EntityMentionModel.model_validate(data)
                entities.append(entity)
                
            except Exception as e:
                logger.warning(f"Failed to deserialize cached entity: {e}")
                continue
        
        return entities
    
    @rate_limit(key="openai", limit=50, window=60, wait=True, max_wait=300)
    def _extract_entities_openai_validated(self, chunk_text: str) -> List[Dict[str, Any]]:
        """Extract entities using OpenAI API with validation."""
        if not self.openai_client:
            raise ValueError("OpenAI client not initialized")
        
        try:
            # Import the limited entity prompt
            from scripts.entity_extraction_fixes import create_openai_prompt_for_limited_entities
            
            prompt = create_openai_prompt_for_limited_entities() + f"\n\nText to analyze:\n{chunk_text}"
            
            response = self.openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a legal document entity extraction specialist. Return only valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=2000
            )
            
            response_text = response.choices[0].message.content.strip()
            
            # Parse JSON response
            try:
                entities_data = json.loads(response_text)
                if not isinstance(entities_data, list):
                    raise ValueError("Response is not a list")
                
                # Filter and validate entities
                from scripts.entity_extraction_fixes import filter_and_fix_entities
                
                # First filter to only allowed entity types
                filtered_entities = filter_and_fix_entities(entities_data)
                
                # Then validate each entity
                validated_entities = []
                for entity_data in filtered_entities:
                    if self._validate_entity_data(entity_data):
                        validated_entities.append(entity_data)
                
                return validated_entities
                
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse OpenAI response as JSON: {e}")
                logger.debug(f"Response text: {response_text}")
                return []
            
        except Exception as e:
            logger.error(f"OpenAI entity extraction failed: {e}")
            return []
    
    def _validate_entity_data(self, entity_data: Dict[str, Any]) -> bool:
        """Validate entity data from OpenAI response."""
        required_fields = ['text', 'type', 'confidence']
        
        # Check required fields
        for field in required_fields:
            if field not in entity_data:
                logger.warning(f"Missing required field: {field}")
                return False
        
        # Validate text
        if not isinstance(entity_data['text'], str) or not entity_data['text'].strip():
            return False
        
        # Validate type - only allow our limited set
        valid_types = ['PERSON', 'ORG', 'LOCATION', 'DATE']
        if entity_data['type'] not in valid_types:
            logger.warning(f"Invalid entity type: {entity_data['type']}")
            return False  # Don't include invalid types
        
        # Validate confidence
        try:
            confidence = float(entity_data['confidence'])
            if confidence < 0 or confidence > 1:
                confidence = max(0, min(1, confidence))
            entity_data['confidence'] = confidence
        except (ValueError, TypeError):
            entity_data['confidence'] = 0.7  # Default confidence
        
        # Set default character positions if missing
        if 'start_char' not in entity_data:
            entity_data['start_char'] = 0
        if 'end_char' not in entity_data:
            entity_data['end_char'] = len(entity_data['text'])
        
        return True
    
    def _extract_entities_local_ner_validated(self, chunk_text: str) -> List[Dict[str, Any]]:
        """Extract entities using local NER (fallback method)."""
        logger.warning("Local NER not implemented, using rule-based extraction")
        
        # Simple rule-based extraction as fallback
        entities = []
        
        # Extract dates
        date_pattern = r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b'
        for match in re.finditer(date_pattern, chunk_text, re.IGNORECASE):
            entities.append({
                'text': match.group(),
                'type': 'DATE',
                'confidence': 0.8,
                'start_char': match.start(),
                'end_char': match.end()
            })
        
        # Extract money amounts
        money_pattern = r'\$[\d,]+(?:\.\d{2})?'
        for match in re.finditer(money_pattern, chunk_text):
            entities.append({
                'text': match.group(),
                'type': 'MONEY',
                'confidence': 0.9,
                'start_char': match.start(),
                'end_char': match.end()
            })
        
        # Extract basic statute references
        statute_pattern = r'\b\d+\s+U\.S\.C\.\s*§\s*\d+\b'
        for match in re.finditer(statute_pattern, chunk_text):
            entities.append({
                'text': match.group(),
                'type': 'STATUTE',
                'confidence': 0.95,
                'start_char': match.start(),
                'end_char': match.end()
            })
        
        return entities
        """Extract entities using local NER pipeline."""
        if not self.ner_pipeline:
            logger.warning("Local NER pipeline not available")
            return []
        
        try:
            # Run NER pipeline
            ner_results = self.ner_pipeline(chunk_text)
            
            entities = []
            for entity_dict in ner_results:
                entity_type = entity_dict['entity'].replace('B-', '').replace('I-', '')
                
                entity = ExtractedEntity(
                    type=entity_type,
                    text=entity_dict['word'],
                    confidence=entity_dict['score'],
                    start_offset=entity_dict.get('start'),
                    end_offset=entity_dict.get('end'),
                    attributes={
                        'source': 'local_ner',
                        'chunk_id': str(chunk_id) if chunk_id else None,
                        'model': NER_GENERAL_MODEL
                    }
                )
                entities.append(entity)
            
            return entities
            
        except Exception as e:
            logger.error(f"Local NER extraction failed: {e}")
            return []
    
    # ========== Entity Resolution ==========
    
    def resolve_document_entities(
        self,
        entity_mentions: List[EntityMentionModel],
        document_uuid: Optional[uuid.UUID] = None,
        use_llm: bool = True,
        fuzzy_threshold: float = 0.8
    ) -> EntityResolutionResultModel:
        """
        Resolve entity mentions to canonical entities.
        
        Args:
            entity_mentions: List of entity mentions to resolve
            document_uuid: UUID of the document
            use_llm: Whether to use LLM for complex resolution
            fuzzy_threshold: Threshold for fuzzy matching
            
        Returns:
            EntityResolutionResultModel with resolution results
        """
        # Initialize result
        result = EntityResolutionResultModel(
            document_uuid=document_uuid or uuid.uuid4(),
            total_mentions=len(entity_mentions)
        )
        
        if not entity_mentions:
            result.status = ProcessingResultStatus.SKIPPED
            return result
        
        try:
            # Group mentions by type for efficient processing
            mentions_by_type = defaultdict(list)
            for mention in entity_mentions:
                mentions_by_type[mention.entity_type].append(mention)
            
            # Process each entity type
            for entity_type, mentions in mentions_by_type.items():
                if use_llm and self.openai_client:
                    canonical_entities = self._resolve_entities_with_llm(mentions, entity_type)
                else:
                    canonical_entities = self._resolve_entities_fuzzy(mentions, entity_type, fuzzy_threshold)
                
                result.canonical_entities.extend(canonical_entities)
            
            # Calculate resolution statistics
            result.total_canonical_entities = len(result.canonical_entities)
            result.status = ProcessingResultStatus.SUCCESS
            
            # Create resolution mapping
            # TODO: Update this when CanonicalEntity model includes mention tracking
            # for canonical in result.canonical_entities:
            #     for mention_id in canonical.mention_ids:
            #         result.resolution_mapping[mention_id] = canonical.canonical_id
            
        except Exception as e:
            logger.error(f"Entity resolution failed: {e}")
            result.status = ProcessingResultStatus.FAILED
            result.error_message = str(e)
        
        return result
    
    @redis_cache(
        prefix="entity:resolution",
        ttl=REDIS_ENTITY_CACHE_TTL,
        key_func=lambda self, mentions, entity_type: f"entity:resolution:{entity_type}:{hashlib.md5(json.dumps([getattr(m, 'entity_text', m.get('entity_text', '')) for m in mentions], sort_keys=True).encode()).hexdigest()}"
    )
    @rate_limit(key="openai", limit=10, window=60, wait=True, max_wait=300)
    def _resolve_entities_with_llm(
        self,
        mentions: List[EntityMentionModel],
        entity_type: str
    ) -> List[CanonicalEntity]:
        """Resolve entities using LLM for complex matching."""
        if not mentions:
            return []
        
        try:
            # Create prompt with all mentions
            mention_texts = [getattr(m, 'entity_text', m.get('entity_text', '')) for m in mentions]
            unique_texts = list(set(mention_texts))
            
            prompt = f"""You are an expert at entity resolution for legal documents.
Given the following {entity_type} entity mentions, group them by the actual entity they refer to.

Entity mentions:
{json.dumps(unique_texts, indent=2)}

Instructions:
1. Group mentions that refer to the same real-world entity
2. Consider variations like:
   - Full name vs abbreviated name (e.g., "ABC Corporation" vs "ABC Corp.")
   - Name with/without middle initials
   - Common misspellings or OCR errors
   - Different forms of the same entity

Respond with a JSON object where:
- Keys are canonical/standard names for the entities
- Values are arrays of all mentions that refer to that entity

Example:
{{
  "ABC Corporation": ["ABC Corp.", "ABC Corporation", "ABC Corp"],
  "John Smith": ["John Smith", "J. Smith", "Smith, John"]
}}
"""

            response = self.openai_client.chat.completions.create(
                model=LLM_MODEL_FOR_RESOLUTION or "gpt-4",
                messages=[
                    {"role": "system", "content": "You are an entity resolution expert. Be precise in grouping entities."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1
            )
            
            content = response.choices[0].message.content
            
            # Parse response
            try:
                groupings = json.loads(content)
            except json.JSONDecodeError:
                # Try to extract JSON from response
                json_match = re.search(r'\{[^{}]*\}', content, re.DOTALL)
                if json_match:
                    groupings = json.loads(json_match.group())
                else:
                    logger.error(f"Failed to parse LLM response: {content}")
                    return self._resolve_entities_fuzzy(mentions, entity_type)
            
            # Convert groupings to CanonicalEntity objects
            canonical_entities = []
            for canonical_name, mention_texts in groupings.items():
                # Find all mentions with these texts
                matched_mentions = [m for m in mentions if getattr(m, 'entity_text', m.get('entity_text', '')) in mention_texts]
                
                if matched_mentions:
                    canonical = CanonicalEntity(
                        canonical_id=str(uuid.uuid4()),
                        entity_type=entity_type,
                        canonical_name=canonical_name,
                        mention_ids=[m.id for m in matched_mentions if m.id],
                        mention_count=len(matched_mentions),
                        confidence=0.9,  # High confidence for LLM resolution
                        resolution_method='llm',
                        metadata={
                            'model': LLM_MODEL_FOR_RESOLUTION or 'gpt-4',
                            'mention_variations': list(set(getattr(m, 'entity_text', m.get('entity_text', '')) for m in matched_mentions))
                        }
                    )
                    canonical_entities.append(canonical)
            
            return canonical_entities
            
        except Exception as e:
            logger.error(f"LLM entity resolution failed: {e}")
            # Fallback to fuzzy matching
            return self._resolve_entities_fuzzy(mentions, entity_type)
    
    def _resolve_entities_fuzzy(
        self,
        mentions: List[EntityMentionModel],
        entity_type: str,
        threshold: float = 0.8
    ) -> List[CanonicalEntity]:
        """Resolve entities using fuzzy string matching."""
        from difflib import SequenceMatcher
        
        if not mentions:
            return []
        
        # Group similar mentions
        groups = []
        processed = set()
        
        for i, mention1 in enumerate(mentions):
            if i in processed:
                continue
            
            group = [mention1]
            processed.add(i)
            
            for j, mention2 in enumerate(mentions[i+1:], i+1):
                if j in processed:
                    continue
                
                # Calculate similarity
                text1 = getattr(mention1, 'entity_text', mention1.get('entity_text', ''))
                text2 = getattr(mention2, 'entity_text', mention2.get('entity_text', ''))
                similarity = SequenceMatcher(None, text1.lower(), text2.lower()).ratio()
                
                if similarity >= threshold:
                    group.append(mention2)
                    processed.add(j)
            
            groups.append(group)
        
        # Convert groups to canonical entities
        canonical_entities = []
        for group in groups:
            # Choose the longest mention as canonical name
            canonical_name = max(group, key=lambda m: len(m.text)).text
            
            canonical = CanonicalEntity(
                canonical_id=str(uuid.uuid4()),
                entity_type=entity_type,
                canonical_name=canonical_name,
                mention_ids=[m.id for m in group if m.id],
                mention_count=len(group),
                confidence=0.7,  # Lower confidence for fuzzy matching
                resolution_method='fuzzy',
                metadata={
                    'threshold': threshold,
                    'mention_variations': list(set(getattr(m, 'entity_text', m.get('entity_text', '')) for m in group))
                }
            )
            canonical_entities.append(canonical)
        
        return canonical_entities
    
    # ========== Entity Enhancement ==========
    
    def enhance_entities(
        self,
        entities: List[Union[ExtractedEntity, CanonicalEntity]],
        use_embeddings: bool = True
    ) -> List[Union[ExtractedEntity, CanonicalEntity]]:
        """
        Enhance entities with additional metadata and embeddings.
        
        Args:
            entities: List of entities to enhance
            use_embeddings: Whether to generate embeddings
            
        Returns:
            Enhanced entities
        """
        enhanced = []
        
        for entity in entities:
            try:
                # Add embedding if requested
                if use_embeddings and self.openai_client:
                    embedding = self._get_entity_embedding(entity.text, entity.type)
                    if embedding is not None:
                        entity.metadata = entity.metadata or {}
                        entity.metadata['embedding'] = embedding.tolist()
                
                # Add additional metadata based on entity type
                if entity.type == "Date":
                    parsed_date = dateparser.parse(entity.text)
                    if parsed_date:
                        entity.metadata = entity.metadata or {}
                        entity.metadata['parsed_date'] = parsed_date.isoformat()
                        entity.metadata['year'] = parsed_date.year
                        entity.metadata['month'] = parsed_date.month
                        entity.metadata['day'] = parsed_date.day
                
                elif entity.type == "Money":
                    # Extract numeric value
                    amount_match = re.search(r'[\d,]+\.?\d*', entity.text)
                    if amount_match:
                        amount_str = amount_match.group().replace(',', '')
                        entity.metadata = entity.metadata or {}
                        entity.metadata['amount'] = float(amount_str)
                
                enhanced.append(entity)
                
            except Exception as e:
                logger.warning(f"Failed to enhance entity {entity.text}: {e}")
                enhanced.append(entity)  # Add unenhanced
        
        return enhanced
    
    def _get_entity_embedding(self, entity_text: str, entity_type: str) -> Optional[np.ndarray]:
        """Generate embedding for an entity."""
        if not self.openai_client:
            return None
        
        try:
            # Create contextualized representation
            contexts = {
                "Person": f"Person entity: {entity_text}",
                "Organization": f"Organization/Company: {entity_text}",
                "Location": f"Geographic location: {entity_text}",
                "Date": f"Date/Time reference: {entity_text}",
                "Money": f"Monetary amount: {entity_text}",
                "Legal_Entity": f"Legal entity: {entity_text}",
                "Case_Citation": f"Legal case citation: {entity_text}"
            }
            
            prompt = contexts.get(entity_type, f"{entity_type}: {entity_text}")
            
            response = self.openai_client.embeddings.create(
                model="text-embedding-3-small",
                input=prompt
            )
            
            embedding = np.array(response.data[0].embedding)
            return embedding
            
        except Exception as e:
            logger.error(f"Failed to get embedding for {entity_text}: {e}")
            return None
    
    # ========== Structured Extraction ==========
    
    def extract_structured_data(
        self,
        chunk_text: str,
        chunk_id: Optional[uuid.UUID] = None,
        entities: Optional[List[ExtractedEntity]] = None
    ) -> StructuredExtractionResultModel:
        """
        Extract structured data from chunk including metadata, facts, and relationships.
        
        Args:
            chunk_text: Text to extract from
            chunk_id: Chunk UUID
            entities: Pre-extracted entities (optional)
            
        Returns:
            StructuredExtractionResultModel with all structured data
        """
        result = StructuredExtractionResultModel(
            document_uuid=uuid.uuid4(),  # Will be set by caller
            chunk_id=chunk_id
        )
        
        if not chunk_text:
            result.status = ProcessingResultStatus.SKIPPED
            return result
        
        try:
            # Extract entities if not provided
            if entities is None:
                entity_result = self.extract_entities_from_chunk(chunk_text, chunk_id)
                entities = entity_result.entities
            
            # Extract different types of structured data
            metadata = self._extract_metadata(chunk_text)
            key_facts = self._extract_key_facts(chunk_text, entities)
            relationships = self._extract_relationships(chunk_text, entities)
            
            # Build structured chunk data
            entity_set = EntitySet(
                persons=[e for e in entities if e.entity_type == "Person"],
                organizations=[e for e in entities if e.entity_type == "Organization"],
                locations=[e for e in entities if e.entity_type == "Location"],
                dates=[e for e in entities if e.entity_type == "Date"],
                amounts=[e for e in entities if e.entity_type == "Money"],
                legal_entities=[e for e in entities if e.entity_type in ["Legal_Entity", "Case_Citation", "Court"]]
            )
            
            result.structured_data = StructuredChunkData(
                metadata=metadata,
                entities=entity_set,
                key_facts=key_facts,
                relationships=relationships
            )
            
            result.status = ProcessingResultStatus.SUCCESS
            
        except Exception as e:
            logger.error(f"Structured extraction failed: {e}")
            result.status = ProcessingResultStatus.FAILED
            result.error_message = str(e)
        
        return result
    
    @redis_cache(
        prefix="structured:metadata",
        ttl=REDIS_STRUCTURED_CACHE_TTL,
        key_func=lambda self, chunk_text: f"structured:metadata:{hashlib.md5(chunk_text[:500].encode()).hexdigest()}"
    )
    def _extract_metadata(self, chunk_text: str) -> DocumentMetadata:
        """Extract document metadata from text."""
        metadata = DocumentMetadata()
        
        # Extract dates
        date_patterns = [
            r'dated?\s+(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})',
            r'(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})',
            r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}'
        ]
        
        for pattern in date_patterns:
            matches = re.findall(pattern, chunk_text, re.IGNORECASE)
            for match in matches:
                parsed_date = dateparser.parse(match)
                if parsed_date:
                    metadata.dates.append(parsed_date.strftime('%Y-%m-%d'))
        
        # Extract document type hints
        doc_type_keywords = {
            'contract': ['agreement', 'contract', 'terms', 'conditions'],
            'complaint': ['complaint', 'plaintiff', 'defendant', 'alleges'],
            'motion': ['motion', 'move', 'request', 'order'],
            'letter': ['dear', 'sincerely', 'regards', 'letter']
        }
        
        chunk_lower = chunk_text.lower()
        for doc_type, keywords in doc_type_keywords.items():
            if any(keyword in chunk_lower for keyword in keywords):
                metadata.document_type = doc_type
                break
        
        # Extract jurisdiction
        jurisdiction_patterns = [
            r'(United States District Court)',
            r'(State of \w+)',
            r'(County of \w+)',
            r'(\w+ Circuit)'
        ]
        
        for pattern in jurisdiction_patterns:
            match = re.search(pattern, chunk_text, re.IGNORECASE)
            if match:
                metadata.jurisdiction = match.group(1)
                break
        
        return metadata
    
    def _extract_key_facts(
        self,
        chunk_text: str,
        entities: List[ExtractedEntity]
    ) -> List[KeyFact]:
        """Extract key facts from text."""
        facts = []
        
        # Look for fact patterns
        fact_patterns = [
            # Claims/allegations
            (r'(plaintiff|petitioner)\s+alleges?\s+that\s+(.+?)(?:\.|;|,\s+and)', 'allegation'),
            # Amounts
            (r'amount\s+of\s+\$?([\d,]+\.?\d*)', 'amount'),
            # Dates of events
            (r'on\s+or\s+about\s+(.+?),?\s+(.+?)(?:\.|;|,)', 'event'),
            # Legal standards
            (r'pursuant\s+to\s+(.+?)(?:\.|;|,)', 'legal_basis'),
        ]
        
        for pattern, fact_type in fact_patterns:
            matches = re.findall(pattern, chunk_text, re.IGNORECASE | re.DOTALL)
            for match in matches:
                if isinstance(match, tuple):
                    fact_text = ' '.join(match).strip()
                else:
                    fact_text = match.strip()
                
                # Find related entities
                related_entities = []
                for entity in entities:
                    if entity.text.lower() in fact_text.lower():
                        related_entities.append(entity.text)
                
                fact = KeyFact(
                    fact_type=fact_type,
                    text=fact_text[:500],  # Limit length
                    confidence=0.7,
                    entities=related_entities[:5]  # Limit related entities
                )
                facts.append(fact)
        
        return facts[:10]  # Limit total facts
    
    def _extract_relationships(
        self,
        chunk_text: str,
        entities: List[ExtractedEntity]
    ) -> List[ExtractedRelationship]:
        """Extract relationships between entities."""
        relationships = []
        
        # Relationship patterns
        rel_patterns = [
            # Party relationships
            (r'(\w+)\s+v\.?\s+(\w+)', 'opposing_party'),
            # Employment
            (r'(\w+)\s+(?:is|was)\s+(?:an?\s+)?employee\s+of\s+(\w+)', 'employment'),
            # Representation
            (r'(\w+)\s+represent(?:s|ed|ing)\s+(\w+)', 'represents'),
            # Corporate relationships
            (r'(\w+)\s+(?:is|was)\s+a\s+subsidiary\s+of\s+(\w+)', 'subsidiary'),
        ]
        
        # Build entity lookup for efficiency
        entity_texts = {e.text.lower(): e for e in entities}
        
        for pattern, rel_type in rel_patterns:
            matches = re.findall(pattern, chunk_text, re.IGNORECASE)
            for match in matches:
                entity1_text = match[0].strip()
                entity2_text = match[1].strip()
                
                # Try to find matching entities
                entity1 = entity_texts.get(entity1_text.lower())
                entity2 = entity_texts.get(entity2_text.lower())
                
                if entity1 and entity2:
                    relationship = ExtractedRelationship(
                        source_entity=entity1.text,
                        relationship_type=rel_type,
                        target_entity=entity2.text,
                        confidence=0.8,
                        context=chunk_text[max(0, chunk_text.find(match[0])-20):chunk_text.find(match[1])+20]
                    )
                    relationships.append(relationship)
        
        return relationships[:10]  # Limit relationships
    
    # ========== Utility Methods ==========
    
    def calculate_entity_similarity(
        self,
        entity1: Union[str, ExtractedEntity],
        entity2: Union[str, ExtractedEntity]
    ) -> float:
        """
        Calculate similarity between two entities.
        
        Returns:
            Similarity score between 0 and 1
        """
        # Extract text if entity objects
        # EntityMentionMinimal uses entity_text, not text
        if hasattr(entity1, 'entity_text'):
            text1 = entity1.entity_text
        elif hasattr(entity1, 'canonical_name'):
            text1 = entity1.canonical_name
        else:
            text1 = str(entity1)
            
        if hasattr(entity2, 'entity_text'):
            text2 = entity2.entity_text
        elif hasattr(entity2, 'canonical_name'):
            text2 = entity2.canonical_name
        else:
            text2 = str(entity2)
        
        # Simple similarity using SequenceMatcher
        from difflib import SequenceMatcher
        similarity = SequenceMatcher(None, text1.lower(), text2.lower()).ratio()
        
        # If we have embeddings, use cosine similarity
        if (hasattr(entity1, 'metadata') and 'embedding' in entity1.metadata and
            hasattr(entity2, 'metadata') and 'embedding' in entity2.metadata):
            
            emb1 = np.array(entity1.metadata['embedding'])
            emb2 = np.array(entity2.metadata['embedding'])
            
            # Cosine similarity
            cos_sim = np.dot(emb1, emb2) / (np.linalg.norm(emb1) * np.linalg.norm(emb2))
            
            # Average text and embedding similarity
            similarity = (similarity + cos_sim) / 2
        
        return similarity
    
    def get_entity_statistics(
        self,
        entities: List[Union[ExtractedEntity, CanonicalEntity]]
    ) -> Dict[str, Any]:
        """Get statistics about entities."""
        stats = {
            'total_count': len(entities),
            'by_type': defaultdict(int),
            'by_source': defaultdict(int),
            'confidence_distribution': {
                'high': 0,  # > 0.8
                'medium': 0,  # 0.5 - 0.8
                'low': 0  # < 0.5
            },
            'unique_texts': len(set(e.text if hasattr(e, 'text') else e.canonical_name for e in entities))
        }
        
        for entity in entities:
            # Count by type
            stats['by_type'][entity.type] += 1
            
            # Count by source
            if hasattr(entity, 'source'):
                stats['by_source'][entity.source] += 1
            elif hasattr(entity, 'resolution_method'):
                stats['by_source'][entity.resolution_method] += 1
            
            # Confidence distribution
            confidence = entity.confidence if hasattr(entity, 'confidence') else 1.0
            if confidence > 0.8:
                stats['confidence_distribution']['high'] += 1
            elif confidence > 0.5:
                stats['confidence_distribution']['medium'] += 1
            else:
                stats['confidence_distribution']['low'] += 1
        
        return dict(stats)


# ========== Factory Functions ==========

def get_entity_service(openai_api_key: Optional[str] = None) -> EntityService:
    """Get entity service instance."""
    return EntityService(openai_api_key)


# ========== Legacy Compatibility ==========

# These functions maintain compatibility with existing code

def extract_entities_from_chunk(
    chunk_text: str,
    chunk_id: Optional[uuid.UUID] = None,
    db_manager: Optional[DatabaseManager] = None,
    use_openai: Optional[bool] = None
) -> EntityExtractionResultModel:
    """Legacy function - use EntityService instead."""
    service = get_entity_service()
    return service.extract_entities_from_chunk(chunk_text, chunk_id, db_manager, use_openai)


def resolve_document_entities(
    entity_mentions: List[EntityMentionModel],
    document_uuid: Optional[uuid.UUID] = None,
    use_llm: bool = True,
    fuzzy_threshold: float = 0.8
) -> EntityResolutionResultModel:
    """Legacy function - use EntityService instead."""
    service = get_entity_service()
    return service.resolve_document_entities(entity_mentions, document_uuid, use_llm, fuzzy_threshold)


# ========== Export All ==========

__all__ = [
    # Main class
    'EntityService',
    
    # Factory function
    'get_entity_service',
    
    # Legacy compatibility
    'extract_entities_from_chunk',
    'resolve_document_entities'
]