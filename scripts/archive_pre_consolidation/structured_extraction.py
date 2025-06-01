import json
import logging
from typing import Dict, List, Any, Optional
import re
import hashlib
from datetime import datetime
from transformers import AutoModelForCausalLM, AutoTokenizer
import torch

# Import config settings
from scripts.config import (OPENAI_API_KEY, LLM_MODEL_FOR_RESOLUTION, DEPLOYMENT_STAGE,
                   REDIS_STRUCTURED_CACHE_TTL)
from scripts.models_init import should_load_local_models
from scripts.cache import redis_cache, rate_limit

# Import centralized Pydantic models
from scripts.core.processing_models import (
    DocumentMetadata, KeyFact, EntitySet, ExtractedRelationship,
    StructuredChunkData, StructuredExtractionResultModel,
    ProcessingResultStatus
)

# OpenAI import for Stage 1
try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

logger = logging.getLogger(__name__)

class StructuredExtractor:
    """Extract structured data from document chunks using LLMs"""
    
    def __init__(self, use_qwen=False):
        # Stage 1: Force OpenAI usage, bypass local models
        if DEPLOYMENT_STAGE == "1" or not should_load_local_models():
            logger.info("Stage 1 deployment detected. Using OpenAI API for structured extraction.")
            self.use_qwen = False
            use_qwen = False
        else:
            self.use_qwen = use_qwen
        
        # Initialize OpenAI client
        self.openai_client = None
        if OpenAI and OPENAI_API_KEY:
            try:
                self.openai_client = OpenAI(api_key=OPENAI_API_KEY)
                logger.info("OpenAI client initialized for structured extraction")
            except Exception as e:
                logger.error(f"Failed to initialize OpenAI client: {e}")
        
        if use_qwen and should_load_local_models():
            # Initialize Qwen model (Stage 2+ only)
            self.model_name = "Qwen/Qwen2.5-7B-Instruct"
            try:
                self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
                self.model = AutoModelForCausalLM.from_pretrained(
                    self.model_name,
                    torch_dtype=torch.float16,
                    device_map="auto"
                )
                logger.info(f"Loaded Qwen model: {self.model_name}")
            except Exception as e:
                logger.error(f"Failed to load Qwen model: {e}")
                logger.info("Falling back to OpenAI API")
                self.use_qwen = False
        
        if not self.use_qwen:
            # Use OpenAI API
            if not self.openai_client:
                if not OPENAI_API_KEY:
                    logger.error("No OpenAI API key configured")
                    raise ValueError("OpenAI API key required for structured extraction")
                logger.error("OpenAI client not available")
                raise ValueError("OpenAI client initialization failed")
            logger.info("Using OpenAI API for structured extraction")
    
    def extract_structured_data_from_chunk(
        self, 
        chunk_text: str, 
        chunk_metadata: Dict[str, Any]
    ) -> Optional[StructuredChunkData]:
        """Extract structured data from a chunk"""
        
        prompt = self._create_extraction_prompt(chunk_text, chunk_metadata)
        
        try:
            if self.use_qwen:
                response = self._extract_with_qwen(prompt)
            else:
                response = self._extract_with_openai(prompt)
            
            # Parse JSON response
            structured_data = self._parse_extraction_response(response, chunk_metadata)
            return structured_data
            
        except Exception as e:
            logger.error(f"Error extracting structured data: {e}")
            # Return a basic structure with extracted entities
            return self._fallback_extraction(chunk_text, chunk_metadata)
    
    def _create_extraction_prompt(self, chunk_text: str, chunk_metadata: Dict) -> str:
        """Create the prompt for structured extraction"""
        
        return f"""
Analyze this legal document chunk and extract structured information:

Document Type: {chunk_metadata.get('doc_category', 'Unknown')}
Page Numbers: {chunk_metadata.get('page_range', 'Unknown')}

Text:
{chunk_text}

Extract the following information in JSON format:
{{
    "document_metadata": {{
        "type": "string (e.g., contract, affidavit, exhibit, correspondence)",
        "date": "ISO date if found",
        "parties": ["list of parties/entities mentioned"],
        "case_number": "if applicable",
        "title": "document title if identifiable"
    }},
    "key_facts": [
        {{
            "fact": "extracted fact",
            "confidence": 0.0-1.0,
            "page": number,
            "context": "surrounding text"
        }}
    ],
    "entities": {{
        "persons": ["list of person names"],
        "organizations": ["list of organizations"],
        "locations": ["list of locations"],
        "dates": ["list of dates mentioned"]
    }},
    "relationships": [
        {{
            "entity1": "name",
            "relationship": "type",
            "entity2": "name",
            "context": "supporting text"
        }}
    ]
}}

IMPORTANT: Return ONLY valid JSON that can be parsed by json.loads(). No markdown, no explanations, just the JSON object.
"""
    
    def _extract_with_qwen(self, prompt: str) -> str:
        """Extract using Qwen model"""
        messages = [
            {"role": "system", "content": "You are a legal document analyzer. Extract structured information from text."},
            {"role": "user", "content": prompt}
        ]
        
        text = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True
        )
        
        model_inputs = self.tokenizer([text], return_tensors="pt").to(self.model.device)
        
        generated_ids = self.model.generate(
            **model_inputs,
            max_new_tokens=1000,
            temperature=1.0,
            do_sample=True
        )
        
        generated_ids = [
            output_ids[len(input_ids):] 
            for input_ids, output_ids in zip(model_inputs.input_ids, generated_ids)
        ]
        
        response = self.tokenizer.batch_decode(generated_ids, skip_special_tokens=True)[0]
        return response
    
    @rate_limit(key="openai", limit=50, window=60, wait=True, max_wait=300)
    def _extract_with_openai(self, prompt: str) -> str:
        """Extract using OpenAI API with rate limiting"""
        if not self.openai_client:
            raise ValueError("OpenAI client not initialized")
        
        # Generate cache key
        prompt_hash = hashlib.md5(prompt.encode()).hexdigest()
        cache_key = f"structured:openai:{LLM_MODEL_FOR_RESOLUTION}:{prompt_hash}"
        
        # Try to get from cache
        try:
            from scripts.redis_utils import get_redis_manager
            redis_mgr = get_redis_manager()
            if redis_mgr.is_available():
                cached = redis_mgr.get_cached(cache_key)
                if cached:
                    logger.debug(f"Structured extraction cache hit for prompt hash {prompt_hash}")
                    return cached
        except Exception as e:
            logger.debug(f"Cache check error: {e}")
            
        try:
            response = self.openai_client.chat.completions.create(
                model=LLM_MODEL_FOR_RESOLUTION,
                messages=[
                    {"role": "system", "content": "You are a JSON API that analyzes legal documents. You must return ONLY valid JSON with no additional text, no markdown formatting, and no explanations. Your entire response must be parseable by json.loads()."},
                    {"role": "user", "content": prompt}
                ],
                temperature=1.0,
                max_completion_tokens=1000,
                response_format={"type": "json_object"}
            )
            result = response.choices[0].message.content
            
            # Cache the result
            try:
                if redis_mgr and redis_mgr.is_available():
                    redis_mgr.set_cached(cache_key, result, REDIS_STRUCTURED_CACHE_TTL)
                    logger.debug(f"Cached structured extraction result")
            except Exception as e:
                logger.debug(f"Cache set error: {e}")
            
            return result
        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            raise
    
    def _parse_extraction_response(self, response: str, chunk_metadata: Dict) -> StructuredChunkData:
        """Parse the JSON response into structured data"""
        
        # Clean response (remove markdown code blocks if present)
        cleaned_response = response.strip()
        if cleaned_response.startswith("```json"):
            cleaned_response = cleaned_response[7:]
        if cleaned_response.startswith("```"):
            cleaned_response = cleaned_response[3:]
        if cleaned_response.endswith("```"):
            cleaned_response = cleaned_response[:-3]
        
        try:
            data = json.loads(cleaned_response)
            
            # Create structured objects
            doc_metadata = DocumentMetadata(
                document_type=data['document_metadata'].get('type', 'Unknown'),
                date=data['document_metadata'].get('date'),
                parties=data['document_metadata'].get('parties', []),
                case_number=data['document_metadata'].get('case_number'),
                title=data['document_metadata'].get('title')
            )
            
            key_facts = [
                KeyFact(
                    fact=fact['fact'],
                    confidence=fact.get('confidence', 0.5),
                    source_chunk_id=chunk_metadata.get('chunk_id', ''),
                    page_number=fact.get('page', 0),
                    context=fact.get('context', ''),
                    fact_type='extracted'
                )
                for fact in data.get('key_facts', [])
            ]
            
            entities = EntitySet(
                persons=data['entities'].get('persons', []),
                organizations=data['entities'].get('organizations', []),
                locations=data['entities'].get('locations', []),
                dates=data['entities'].get('dates', []),
                monetary_amounts=data['entities'].get('monetary_amounts', []),
                legal_references=data['entities'].get('legal_references', [])
            )
            
            relationships = [
                ExtractedRelationship(
                    subject=rel['entity1'],
                    subject_type='entity',
                    predicate=rel['relationship'],
                    object=rel['entity2'],
                    object_type='entity',
                    confidence=0.8,
                    context=rel.get('context', ''),
                    source_chunk_id=chunk_metadata.get('chunk_id', '')
                )
                for rel in data.get('relationships', [])
            ]
            
            return StructuredChunkData(
                chunk_id=chunk_metadata.get('chunk_id', ''),
                document_metadata=doc_metadata,
                key_facts=key_facts,
                entities=entities,
                relationships=relationships,
                extraction_timestamp=datetime.now(),
                extraction_method='llm'
            )
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            logger.error(f"Response was: {response[:500]}...")
            
            # Try to extract JSON from markdown code blocks
            json_match = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', response)
            if json_match:
                try:
                    data = json.loads(json_match.group(1))
                    logger.info("Successfully extracted JSON from code block")
                    # Recursively call the same parsing logic
                    return self._parse_extraction_response(json.dumps(data), chunk_metadata)
                except:
                    pass
            
            # Return empty structure instead of raising
            return StructuredChunkData(
                chunk_id=chunk_metadata.get('chunk_id', ''),
                document_metadata=DocumentMetadata(document_type="Unknown"),
                key_facts=[],
                entities=EntitySet(),
                relationships=[],
                extraction_timestamp=datetime.now(),
                extraction_method='fallback'
            )
    
    def _fallback_extraction(self, chunk_text: str, chunk_metadata: Dict) -> StructuredChunkData:
        """Fallback extraction using regex and basic NLP"""
        
        # Extract dates
        date_pattern = r'\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b'
        dates = re.findall(date_pattern, chunk_text)
        
        # Extract monetary amounts
        money_pattern = r'\$[\d,]+\.?\d*'
        amounts = re.findall(money_pattern, chunk_text)
        
        # Extract case numbers
        case_pattern = r'\b\d{2,}-\w+-\d{4,}\b|\bCase No\.\s*\d+\b'
        case_numbers = re.findall(case_pattern, chunk_text)
        
        # Basic entity extraction (capitalized words)
        words = chunk_text.split()
        potential_entities = [
            word for word in words 
            if word[0].isupper() and len(word) > 2
        ]
        
        return StructuredChunkData(
            chunk_id=chunk_metadata.get('chunk_id', ''),
            document_metadata=DocumentMetadata(
                document_type=chunk_metadata.get('doc_category', 'Unknown'),
                date=dates[0] if dates else None,
                parties=[],
                case_number=case_numbers[0] if case_numbers else None,
                title=None
            ),
            key_facts=[],
            entities=EntitySet(
                persons=[],
                organizations=[],
                locations=[],
                dates=dates,
                monetary_amounts=amounts,
                legal_references=case_numbers
            ),
            relationships=[],
            extraction_timestamp=datetime.now(),
            extraction_method='fallback'
        )

def format_document_level_for_supabase(structured_data: dict) -> dict:
    """
    Convert structured document data into a format suitable for Supabase JSONB storage.
    This function prepares document-level structured data to be stored in the metadata_json field.
    """
    # Start with the document level metadata
    formatted_data = {
        "document_metadata": structured_data.get('document_metadata', {}),
        "key_facts": structured_data.get('key_facts', []),
        "primary_entities": {
            "persons": list(set(structured_data.get('entities', {}).get('persons', []))),
            "organizations": list(set(structured_data.get('entities', {}).get('organizations', []))),
            "locations": list(set(structured_data.get('entities', {}).get('locations', []))),
        },
        "extracted_dates": list(set(structured_data.get('entities', {}).get('dates', []))),
        "extracted_amounts": list(set(structured_data.get('entities', {}).get('monetary_amounts', []))),
        "legal_references": list(set(structured_data.get('entities', {}).get('legal_references', []))),
        "key_relationships": structured_data.get('relationships', []),
        "extraction_timestamp": datetime.now().isoformat()
    }
    
    return formatted_data

def format_chunk_level_for_supabase(structured_data: StructuredChunkData) -> dict:
    """
    Convert structured chunk data into a format suitable for Supabase JSONB storage.
    This function prepares chunk-level structured data to be stored in the metadata_json field.
    """
    # Convert the Pydantic model to a dictionary
    data_dict = structured_data.model_dump()
    
    # Add an extraction timestamp
    formatted_data = {
        **data_dict,
        "extraction_timestamp": datetime.now().isoformat()
    }
    
    return formatted_data

def aggregate_chunk_structures(structured_chunks: List[StructuredChunkData]) -> Dict:
    """Aggregate structured data from all chunks into document-level structure"""
    
    # Initialize aggregated structure
    aggregated = {
        'document_metadata': {
            'type': 'Unknown',
            'date': None,
            'parties': set(),
            'case_numbers': set(),
            'title': None
        },
        'key_facts': [],
        'entities': {
            'persons': set(),
            'organizations': set(),
            'locations': set(),
            'dates': set(),
            'monetary_amounts': set(),
            'legal_references': set()
        },
        'relationships': []
    }
    
    # Aggregate from each chunk
    for data in structured_chunks:
        # Update document metadata
        if isinstance(data.document_metadata.document_type, str) and data.document_metadata.document_type != 'Unknown':
            aggregated['document_metadata']['document_type'] = data.document_metadata.document_type
        
        if data.document_metadata.date:
            aggregated['document_metadata']['date'] = data.document_metadata.date
        
        if data.document_metadata.parties:
            aggregated['document_metadata']['parties'].update(data.document_metadata.parties)
        
        if data.document_metadata.case_number:
            aggregated['document_metadata']['case_numbers'].add(data.document_metadata.case_number)
        
        if data.document_metadata.title and not aggregated['document_metadata']['title']:
            aggregated['document_metadata']['title'] = data.document_metadata.title
        
        # Aggregate key facts
        aggregated['key_facts'].extend(data.key_facts)
        
        # Aggregate entities
        aggregated['entities']['persons'].update(data.entities.persons)
        aggregated['entities']['organizations'].update(data.entities.organizations)
        aggregated['entities']['locations'].update(data.entities.locations)
        aggregated['entities']['dates'].update(data.entities.dates)
        aggregated['entities']['monetary_amounts'].update(data.entities.monetary_amounts)
        aggregated['entities']['legal_references'].update(data.entities.legal_references)
        
        # Aggregate relationships
        aggregated['relationships'].extend(data.relationships)
    
    # Convert sets to lists for JSON serialization
    aggregated['document_metadata']['parties'] = list(aggregated['document_metadata']['parties'])
    aggregated['document_metadata']['case_numbers'] = list(aggregated['document_metadata']['case_numbers'])
    for entity_type in aggregated['entities']:
        aggregated['entities'][entity_type] = list(aggregated['entities'][entity_type])
    
    # Sort facts by confidence
    aggregated['key_facts'].sort(key=lambda x: x.confidence if hasattr(x, 'confidence') else 0, reverse=True)
    
    # Add timestamp for tracking
    aggregated['aggregation_timestamp'] = datetime.now().isoformat()
    
    return aggregated

def extract_structured_data_from_document(
    document_uuid: str,
    chunks: List[Dict[str, Any]],
    use_qwen: bool = False
) -> StructuredExtractionResultModel:
    """
    Extract structured data from all chunks of a document
    
    Args:
        document_uuid: UUID of the document
        chunks: List of chunk dictionaries with text and metadata
        use_qwen: Whether to use Qwen model (Stage 2+) or OpenAI API
        
    Returns:
        StructuredExtractionResultModel with extraction results
    """
    logger.info(f"Starting structured extraction for document {document_uuid}")
    
    try:
        # Initialize extractor
        extractor = StructuredExtractor(use_qwen=use_qwen)
        
        # Extract from each chunk
        structured_chunks = []
        total_chunks = len(chunks)
        successful_extractions = 0
        
        for i, chunk in enumerate(chunks):
            try:
                chunk_text = chunk.get('content', '')
                chunk_metadata = {
                    'chunk_id': chunk.get('chunk_id', f"{document_uuid}_chunk_{i}"),
                    'doc_category': chunk.get('doc_category', 'Unknown'),
                    'page_range': chunk.get('page_range', 'Unknown'),
                    'chunk_index': i
                }
                
                structured_data = extractor.extract_structured_data_from_chunk(
                    chunk_text, chunk_metadata
                )
                
                if structured_data:
                    structured_chunks.append(structured_data)
                    successful_extractions += 1
                    logger.debug(f"Successfully extracted from chunk {i+1}/{total_chunks}")
                else:
                    logger.warning(f"Failed to extract from chunk {i+1}/{total_chunks}")
                    
            except Exception as e:
                logger.error(f"Error extracting from chunk {i+1}: {e}")
                continue
        
        # Aggregate results
        aggregated_data = aggregate_chunk_structures(structured_chunks)
        
        # Calculate confidence scores
        confidence_scores = {
            'overall_confidence': successful_extractions / total_chunks if total_chunks > 0 else 0.0,
            'extraction_success_rate': successful_extractions / total_chunks if total_chunks > 0 else 0.0,
            'total_entities': sum(len(getattr(chunk.entities, attr, [])) for chunk in structured_chunks for attr in ['persons', 'organizations', 'locations', 'dates', 'monetary_amounts', 'legal_references']),
            'total_facts': sum(len(chunk.key_facts) for chunk in structured_chunks),
            'total_relationships': sum(len(chunk.relationships) for chunk in structured_chunks)
        }
        
        # Create result model
        result = StructuredExtractionResultModel(
            chunk_id=document_uuid,
            structured_data=structured_chunks[0] if structured_chunks else None,
            extraction_method='llm' if not use_qwen else 'qwen',
            confidence_scores=confidence_scores,
            total_chunks_processed=total_chunks,
            successful_extractions=successful_extractions,
            aggregated_entities=aggregated_data.get('entities', {}),
            aggregated_facts=[fact.model_dump() if hasattr(fact, 'model_dump') else fact for fact in aggregated_data.get('key_facts', [])],
            aggregated_relationships=[rel.model_dump() if hasattr(rel, 'model_dump') else rel for rel in aggregated_data.get('relationships', [])]
        )
        
        logger.info(f"Completed structured extraction for document {document_uuid}: "
                   f"{successful_extractions}/{total_chunks} chunks processed successfully")
        
        return result
        
    except Exception as e:
        logger.error(f"Error in structured extraction for document {document_uuid}: {e}")
        
        # Return error result
        return StructuredExtractionResultModel(
            chunk_id=document_uuid,
            structured_data=None,
            extraction_method='error',
            confidence_scores={'overall_confidence': 0.0, 'error': str(e)},
            total_chunks_processed=len(chunks),
            successful_extractions=0,
            aggregated_entities={},
            aggregated_facts=[],
            aggregated_relationships=[]
        )