"""
Document Categorization Service for PDF-only pipeline.
Uses LLM with few-shot examples to categorize legal documents.
"""
import logging
from typing import Tuple, Optional, Dict, Any
from scripts.core.pdf_models import PDFDocumentModel, DocumentCategory
from scripts.config import OPENAI_API_KEY, LLM_MODEL_FOR_RESOLUTION
from scripts.cache import get_redis_manager
from openai import OpenAI
import json
import re

logger = logging.getLogger(__name__)


class DocumentCategorizationService:
    """Service for categorizing legal documents using LLM."""
    
    # Category examples for few-shot learning
    CATEGORY_EXAMPLES = {
        DocumentCategory.PLEADING: [
            "complaint", "answer", "motion", "brief", "petition",
            "counterclaim", "cross-claim", "third-party complaint",
            "motion to dismiss", "motion for summary judgment"
        ],
        DocumentCategory.DISCOVERY: [
            "interrogatories", "deposition", "request for production",
            "request for admission", "subpoena", "notice of deposition",
            "discovery responses", "privilege log", "protective order"
        ],
        DocumentCategory.EVIDENCE: [
            "exhibit", "affidavit", "declaration", "witness statement",
            "expert report", "deposition transcript", "trial exhibit",
            "demonstrative evidence", "chain of custody"
        ],
        DocumentCategory.CORRESPONDENCE: [
            "letter", "email", "memorandum", "notice", "demand letter",
            "settlement communication", "meet and confer", "status update",
            "client communication", "opposing counsel letter"
        ],
        DocumentCategory.FINANCIAL: [
            "invoice", "receipt", "statement", "tax return", "budget",
            "financial report", "expense report", "billing statement",
            "cost analysis", "damages calculation"
        ],
        DocumentCategory.CONTRACT: [
            "agreement", "contract", "amendment", "addendum", "lease",
            "purchase agreement", "service agreement", "nda",
            "licensing agreement", "settlement agreement"
        ],
        DocumentCategory.REGULATORY: [
            "regulatory filing", "compliance report", "permit",
            "license application", "regulatory notice", "inspection report",
            "administrative order", "agency correspondence"
        ]
    }
    
    def __init__(self, openai_api_key: Optional[str] = None):
        """Initialize with OpenAI client."""
        self.api_key = openai_api_key or OPENAI_API_KEY
        if not self.api_key:
            raise ValueError("OpenAI API key required for document categorization")
        self.client = OpenAI(api_key=self.api_key)
        self.model = LLM_MODEL_FOR_RESOLUTION or "gpt-4"
        self.redis_manager = get_redis_manager()
    
    async def categorize_document(
        self,
        document: PDFDocumentModel,
        text_sample: str,
        additional_context: Optional[Dict[str, Any]] = None
    ) -> Tuple[DocumentCategory, float, str]:
        """
        Categorize document using LLM with caching.
        
        Args:
            document: PDF document model
            text_sample: Sample text from document (first ~2000 chars recommended)
            additional_context: Optional additional context (entities, metadata)
            
        Returns:
            Tuple of (category, confidence, reasoning)
        """
        try:
            # Generate cache key
            cache_key = f"categorization:{document.document_uuid}:{hash(text_sample[:500])}"
            
            # Check cache
            if self.redis_manager and self.redis_manager.is_available():
                cached_result = self.redis_manager.get_cached(cache_key)
                if cached_result:
                    logger.debug(f"Cache hit for document categorization: {document.document_uuid}")
                    return (
                        DocumentCategory(cached_result['category']),
                        cached_result['confidence'],
                        cached_result['reasoning']
                    )
            
            # Build prompt
            prompt = self._build_categorization_prompt(
                document.original_filename,
                text_sample,
                additional_context
            )
            
            # Call OpenAI
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self._get_system_prompt()},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,  # Lower temperature for consistency
                max_tokens=500
            )
            
            # Parse response
            category, confidence, reasoning = self._parse_response(
                response.choices[0].message.content
            )
            
            # Cache result
            if self.redis_manager and self.redis_manager.is_available():
                cache_data = {
                    'category': category.value,
                    'confidence': confidence,
                    'reasoning': reasoning
                }
                self.redis_manager.set_cached(cache_key, cache_data, ttl=86400)  # 24 hours
            
            # Log categorization
            logger.info(
                f"Categorized document {document.document_uuid}: "
                f"{category.value} (confidence: {confidence:.2f})"
            )
            
            return category, confidence, reasoning
            
        except Exception as e:
            logger.error(f"Categorization failed: {e}")
            # Return unknown with low confidence on error
            return DocumentCategory.UNKNOWN, 0.0, f"Categorization error: {str(e)}"
    
    def _get_system_prompt(self) -> str:
        """Get system prompt for categorization."""
        return """You are an expert legal document categorization AI. 
        Your task is to accurately categorize legal documents based on their content, 
        filename, and context. You must respond in a specific format.
        
        You are precise, consistent, and provide clear reasoning for your categorizations.
        When uncertain, you indicate lower confidence rather than guessing."""
    
    def _build_categorization_prompt(
        self, 
        filename: str, 
        text: str,
        additional_context: Optional[Dict[str, Any]] = None
    ) -> str:
        """Build categorization prompt with examples."""
        # Format category examples
        examples = []
        for cat, example_list in self.CATEGORY_EXAMPLES.items():
            examples.append(f"\n{cat.value.upper()}:")
            examples.append(f"  Examples: {', '.join(example_list[:5])}")
            examples.append(f"  Description: {cat.description}")
        
        examples_text = "\n".join(examples)
        
        # Truncate text sample if too long
        text_sample = text[:2000] if len(text) > 2000 else text
        
        # Build context section
        context_parts = [f"Filename: {filename}"]
        if additional_context:
            if "entities" in additional_context:
                entities = additional_context["entities"]
                if entities:
                    context_parts.append(f"Entities found: {', '.join(entities[:10])}")
            if "metadata" in additional_context:
                metadata = additional_context["metadata"]
                if "date" in metadata:
                    context_parts.append(f"Document date: {metadata['date']}")
                if "parties" in metadata:
                    context_parts.append(f"Parties: {', '.join(metadata['parties'][:3])}")
        
        context_text = "\n".join(context_parts)
        
        return f"""Categorize this legal document into one of these categories:

{examples_text}

DOCUMENT INFORMATION:
{context_text}

TEXT SAMPLE:
{text_sample}

INSTRUCTIONS:
1. Analyze the document content, filename, and any entities/metadata
2. Select the most appropriate category from the list above
3. Provide a confidence score (0.00-1.00)
4. Give a brief reasoning for your choice

Respond in EXACTLY this format:
CATEGORY: [exact category name from the list]
CONFIDENCE: [0.00-1.00]
REASONING: [1-2 sentences explaining your choice]

Example response:
CATEGORY: pleading
CONFIDENCE: 0.95
REASONING: This is clearly a complaint filed in federal court, containing allegations, claims for relief, and a prayer for damages."""
    
    def _parse_response(self, response_text: str) -> Tuple[DocumentCategory, float, str]:
        """Parse LLM response into structured output."""
        try:
            # Extract components using regex
            category_match = re.search(r'CATEGORY:\s*(\w+)', response_text, re.IGNORECASE)
            confidence_match = re.search(r'CONFIDENCE:\s*([\d.]+)', response_text, re.IGNORECASE)
            reasoning_match = re.search(r'REASONING:\s*(.+?)(?:\n|$)', response_text, re.IGNORECASE | re.DOTALL)
            
            if not all([category_match, confidence_match, reasoning_match]):
                raise ValueError("Failed to parse response format")
            
            # Extract values
            category_str = category_match.group(1).lower()
            confidence = float(confidence_match.group(1))
            reasoning = reasoning_match.group(1).strip()
            
            # Validate category
            try:
                category = DocumentCategory(category_str)
            except ValueError:
                # Try to match partial category names
                for cat in DocumentCategory:
                    if category_str in cat.value or cat.value in category_str:
                        category = cat
                        break
                else:
                    logger.warning(f"Unknown category '{category_str}', defaulting to UNKNOWN")
                    category = DocumentCategory.UNKNOWN
                    confidence = min(confidence, 0.5)  # Reduce confidence for unknown
            
            # Validate confidence
            confidence = max(0.0, min(1.0, confidence))
            
            return category, confidence, reasoning
            
        except Exception as e:
            logger.error(f"Failed to parse LLM response: {e}\nResponse: {response_text}")
            return DocumentCategory.UNKNOWN, 0.0, "Failed to parse categorization response"
    
    async def categorize_with_context(
        self,
        document: PDFDocumentModel,
        chunks: list,
        entities: Optional[list] = None
    ) -> Tuple[DocumentCategory, float, str]:
        """
        Categorize document with additional context from chunks and entities.
        
        Args:
            document: PDF document model
            chunks: List of document chunks
            entities: Optional list of extracted entities
            
        Returns:
            Tuple of (category, confidence, reasoning)
        """
        # Get text sample from first few chunks
        text_parts = []
        for i, chunk in enumerate(chunks[:3]):  # First 3 chunks
            if hasattr(chunk, 'content'):
                text_parts.append(chunk.content)
            elif isinstance(chunk, dict) and 'content' in chunk:
                text_parts.append(chunk['content'])
        
        text_sample = "\n\n".join(text_parts)
        
        # Build additional context
        additional_context = {}
        if entities:
            # Extract entity names
            entity_names = []
            for entity in entities[:20]:  # Limit to first 20
                if hasattr(entity, 'text'):
                    entity_names.append(entity.text)
                elif isinstance(entity, dict) and 'text' in entity:
                    entity_names.append(entity['text'])
            additional_context['entities'] = entity_names
        
        # Extract metadata if available
        if hasattr(document, 'extracted_metadata') and document.extracted_metadata:
            additional_context['metadata'] = document.extracted_metadata
        
        return await self.categorize_document(
            document,
            text_sample,
            additional_context
        )
    
    def get_category_keywords(self, category: DocumentCategory) -> list:
        """Get keywords associated with a category."""
        return self.CATEGORY_EXAMPLES.get(category, [])
    
    def suggest_category_refinement(
        self,
        category: DocumentCategory,
        confidence: float,
        text_sample: str
    ) -> Optional[Dict[str, Any]]:
        """
        Suggest category refinement if confidence is low.
        
        Returns:
            Dict with refinement suggestions or None
        """
        if confidence >= 0.8:
            return None
        
        suggestions = {
            "current_category": category.value,
            "confidence": confidence,
            "refinement_needed": True,
            "suggestions": []
        }
        
        # Check for keywords from other categories
        text_lower = text_sample.lower()
        for cat, keywords in self.CATEGORY_EXAMPLES.items():
            if cat == category:
                continue
            
            matches = [kw for kw in keywords if kw in text_lower]
            if matches:
                suggestions["suggestions"].append({
                    "category": cat.value,
                    "matched_keywords": matches[:5],
                    "description": cat.description
                })
        
        # Sort suggestions by number of matches
        suggestions["suggestions"].sort(
            key=lambda x: len(x["matched_keywords"]),
            reverse=True
        )
        
        return suggestions if suggestions["suggestions"] else None