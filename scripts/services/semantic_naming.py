"""
Semantic Naming Service for PDF documents.
Generates human-readable, searchable filenames based on document content and metadata.
"""
import logging
import re
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple
# PDFDocumentModel, DocumentCategory, SemanticNamingModel not in consolidated models
# Will need to use dict and string enum values instead
from scripts.config import OPENAI_API_KEY, LLM_MODEL_FOR_RESOLUTION
from scripts.cache import get_redis_manager
from openai import OpenAI
import uuid

logger = logging.getLogger(__name__)


class SemanticNamingService:
    """Service for generating semantic, human-readable filenames for legal documents."""
    
    # Naming templates by category
    NAMING_TEMPLATES = {
        DocumentCategory.PLEADING: "{date}_{party1}_v_{party2}_{doc_type}",
        DocumentCategory.DISCOVERY: "{date}_{requesting_party}_{discovery_type}_{responding_party}",
        DocumentCategory.EVIDENCE: "{date}_{exhibit_type}_{party}_{description}",
        DocumentCategory.CORRESPONDENCE: "{date}_{from_party}_to_{to_party}_{subject}",
        DocumentCategory.FINANCIAL: "{date}_{doc_type}_{party}_{period}",
        DocumentCategory.CONTRACT: "{date}_{contract_type}_{party1}_{party2}",
        DocumentCategory.REGULATORY: "{date}_{agency}_{filing_type}_{party}",
        DocumentCategory.UNKNOWN: "{date}_{original_name}_processed"
    }
    
    # Common document type patterns
    DOC_TYPE_PATTERNS = {
        "complaint": ["complaint", "petition", "claim"],
        "answer": ["answer", "response", "reply"],
        "motion": ["motion", "move", "request"],
        "brief": ["brief", "memorandum", "memo"],
        "order": ["order", "ruling", "decision"],
        "notice": ["notice", "notification"],
        "subpoena": ["subpoena", "summons"],
        "deposition": ["deposition", "depo", "testimony"],
        "interrogatory": ["interrogatory", "interrogatories", "questions"],
        "agreement": ["agreement", "contract", "deal"],
        "amendment": ["amendment", "modification", "addendum"],
        "invoice": ["invoice", "bill", "statement"],
        "letter": ["letter", "correspondence", "communication"]
    }
    
    def __init__(self, openai_api_key: Optional[str] = None):
        """Initialize with OpenAI client."""
        self.api_key = openai_api_key or OPENAI_API_KEY
        if not self.api_key:
            raise ValueError("OpenAI API key required for semantic naming")
        self.client = OpenAI(api_key=self.api_key)
        self.model = LLM_MODEL_FOR_RESOLUTION or "gpt-4"
        self.redis_manager = get_redis_manager()
    
    async def generate_semantic_name(
        self,
        document: PDFDocumentModel,
        category: DocumentCategory,
        text_sample: str,
        entities: Optional[List[Dict[str, Any]]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> SemanticNamingModel:
        """
        Generate semantic filename for document.
        
        Args:
            document: PDF document model
            category: Document category from categorization
            text_sample: Sample text from document
            entities: Extracted entities (parties, dates, etc.)
            metadata: Additional metadata
            
        Returns:
            SemanticNamingModel with suggested name and metadata
        """
        try:
            # Generate cache key
            cache_key = f"semantic_name:{document.document_uuid}:{category.value}"
            
            # Check cache
            if self.redis_manager and self.redis_manager.is_available():
                cached_result = self.redis_manager.get_cached(cache_key)
                if cached_result:
                    logger.debug(f"Cache hit for semantic naming: {document.document_uuid}")
                    return SemanticNamingModel(**cached_result)
            
            # Extract naming components
            components = await self._extract_naming_components(
                category, text_sample, entities, metadata
            )
            
            # Generate name using template
            template = self.NAMING_TEMPLATES.get(category, self.NAMING_TEMPLATES[DocumentCategory.UNKNOWN])
            suggested_name = self._apply_template(template, components)
            
            # Sanitize filename
            suggested_name = self._sanitize_filename(suggested_name)
            
            # Add .pdf extension if not present
            if not suggested_name.lower().endswith('.pdf'):
                suggested_name += '.pdf'
            
            # Create naming model
            naming_model = SemanticNamingModel(
                original_filename=document.original_filename,
                suggested_filename=suggested_name,
                naming_confidence=components.get('confidence', 0.8),
                naming_template_used=template,
                extracted_components=components,
                naming_timestamp=datetime.utcnow()
            )
            
            # Validate the name isn't too generic
            if self._is_name_too_generic(suggested_name):
                naming_model.naming_confidence *= 0.5
                naming_model.requires_human_review = True
            
            # Cache result
            if self.redis_manager and self.redis_manager.is_available():
                self.redis_manager.set_cached(
                    cache_key, 
                    naming_model.model_dump(mode='json'),
                    ttl=86400  # 24 hours
                )
            
            logger.info(
                f"Generated semantic name for {document.document_uuid}: "
                f"{suggested_name} (confidence: {naming_model.naming_confidence:.2f})"
            )
            
            return naming_model
            
        except Exception as e:
            logger.error(f"Semantic naming failed: {e}")
            # Return fallback naming
            return self._create_fallback_naming(document, str(e))
    
    async def _extract_naming_components(
        self,
        category: DocumentCategory,
        text_sample: str,
        entities: Optional[List[Dict[str, Any]]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Extract components needed for naming based on category."""
        
        # Build prompt for component extraction
        prompt = self._build_extraction_prompt(category, text_sample, entities)
        
        try:
            # Call OpenAI
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self._get_extraction_system_prompt()},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=500
            )
            
            # Parse response
            components = self._parse_extraction_response(
                response.choices[0].message.content,
                category
            )
            
            # Add metadata components
            if metadata:
                if 'date' in metadata and 'date' not in components:
                    components['date'] = metadata['date']
                if 'case_number' in metadata:
                    components['case_number'] = metadata['case_number']
            
            # Ensure we have a date
            if 'date' not in components or not components['date']:
                components['date'] = datetime.utcnow().strftime('%Y%m%d')
            
            return components
            
        except Exception as e:
            logger.error(f"Failed to extract naming components: {e}")
            # Return basic components
            return {
                'date': datetime.utcnow().strftime('%Y%m%d'),
                'doc_type': self._guess_doc_type(text_sample),
                'confidence': 0.3
            }
    
    def _get_extraction_system_prompt(self) -> str:
        """Get system prompt for component extraction."""
        return """You are an expert at extracting key information from legal documents for creating descriptive filenames.
        Extract the most important identifiable information that would help someone find this document later.
        Focus on: parties involved, document type, dates, subject matter, case numbers.
        Be concise and accurate. Use standardized terms where possible."""
    
    def _build_extraction_prompt(
        self,
        category: DocumentCategory,
        text_sample: str,
        entities: Optional[List[Dict[str, Any]]] = None
    ) -> str:
        """Build prompt for extracting naming components."""
        
        # Get category-specific requirements
        requirements = self._get_category_requirements(category)
        
        # Format entities if provided
        entity_info = ""
        if entities:
            party_entities = [e for e in entities if e.get('type') in ['person', 'organization', 'party']]
            date_entities = [e for e in entities if e.get('type') == 'date']
            
            if party_entities:
                entity_info += f"\nParties found: {', '.join([e.get('text', '') for e in party_entities[:5]])}"
            if date_entities:
                entity_info += f"\nDates found: {', '.join([e.get('text', '') for e in date_entities[:3]])}"
        
        # Truncate text sample
        text_sample = text_sample[:1500] if len(text_sample) > 1500 else text_sample
        
        return f"""Extract key information for creating a filename for this {category.value} document.

Required information:
{requirements}

{entity_info}

Document text sample:
{text_sample}

Instructions:
1. Extract the required information as accurately as possible
2. Use standardized abbreviations (v. for versus, Corp for Corporation, etc.)
3. For dates, use YYYYMMDD format
4. For names, use last names for individuals, short names for organizations
5. Identify the specific document type (e.g., "complaint", "motion_dismiss", "interrogatories")

Respond in this exact format:
DATE: [YYYYMMDD or unknown]
PARTY1: [first party name or unknown]
PARTY2: [second party name if applicable or unknown]
DOC_TYPE: [specific document type]
SUBJECT: [brief subject if applicable]
FROM_PARTY: [sender if correspondence]
TO_PARTY: [recipient if correspondence]
CONFIDENCE: [0.0-1.0]

Additional fields as needed based on category."""
    
    def _get_category_requirements(self, category: DocumentCategory) -> str:
        """Get extraction requirements for each category."""
        requirements = {
            DocumentCategory.PLEADING: "- Date filed\n- Plaintiff name\n- Defendant name\n- Document type (complaint, answer, motion, etc.)",
            DocumentCategory.DISCOVERY: "- Date\n- Requesting party\n- Responding party\n- Discovery type (interrogatories, deposition, etc.)",
            DocumentCategory.EVIDENCE: "- Date\n- Exhibit type/number\n- Submitting party\n- Brief description",
            DocumentCategory.CORRESPONDENCE: "- Date\n- From party\n- To party\n- Subject or purpose",
            DocumentCategory.FINANCIAL: "- Date\n- Document type (invoice, statement, etc.)\n- Party\n- Period covered",
            DocumentCategory.CONTRACT: "- Date\n- Contract type\n- First party\n- Second party",
            DocumentCategory.REGULATORY: "- Date\n- Agency name\n- Filing type\n- Filing party"
        }
        return requirements.get(category, "- Date\n- Document type\n- Main party")
    
    def _parse_extraction_response(self, response_text: str, category: DocumentCategory) -> Dict[str, Any]:
        """Parse extraction response into components dict."""
        components = {}
        
        # Extract standard fields
        patterns = {
            'date': r'DATE:\s*(\d{8}|[\w\s]+)',
            'party1': r'PARTY1:\s*([^\n]+)',
            'party2': r'PARTY2:\s*([^\n]+)',
            'doc_type': r'DOC_TYPE:\s*([^\n]+)',
            'subject': r'SUBJECT:\s*([^\n]+)',
            'from_party': r'FROM_PARTY:\s*([^\n]+)',
            'to_party': r'TO_PARTY:\s*([^\n]+)',
            'confidence': r'CONFIDENCE:\s*([\d.]+)'
        }
        
        for field, pattern in patterns.items():
            match = re.search(pattern, response_text, re.IGNORECASE)
            if match:
                value = match.group(1).strip()
                if value.lower() not in ['unknown', 'n/a', '']:
                    if field == 'confidence':
                        components[field] = float(value)
                    elif field == 'date' and not value.isdigit():
                        # Try to parse date
                        try:
                            parsed_date = datetime.strptime(value, '%Y-%m-%d')
                            components[field] = parsed_date.strftime('%Y%m%d')
                        except:
                            components[field] = datetime.utcnow().strftime('%Y%m%d')
                    else:
                        components[field] = self._clean_component(value)
        
        # Extract additional fields based on category
        if category == DocumentCategory.DISCOVERY:
            components['discovery_type'] = components.get('doc_type', 'discovery')
            components['requesting_party'] = components.get('party1', 'party')
            components['responding_party'] = components.get('party2', 'party')
        
        return components
    
    def _apply_template(self, template: str, components: Dict[str, Any]) -> str:
        """Apply naming template with components."""
        # Create a copy of components with fallback values
        safe_components = {}
        
        # Extract all placeholders from template
        placeholders = re.findall(r'{(\w+)}', template)
        
        for placeholder in placeholders:
            if placeholder in components:
                safe_components[placeholder] = components[placeholder]
            else:
                # Provide sensible defaults
                if placeholder == 'date':
                    safe_components[placeholder] = datetime.utcnow().strftime('%Y%m%d')
                elif 'party' in placeholder:
                    safe_components[placeholder] = 'party'
                elif 'type' in placeholder:
                    safe_components[placeholder] = 'document'
                else:
                    safe_components[placeholder] = 'unknown'
        
        # Format the template
        try:
            return template.format(**safe_components)
        except KeyError as e:
            logger.error(f"Missing template key: {e}")
            return f"{safe_components.get('date', 'undated')}_{safe_components.get('doc_type', 'document')}"
    
    def _sanitize_filename(self, filename: str) -> str:
        """Sanitize filename for filesystem compatibility."""
        # Remove or replace invalid characters
        filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
        
        # Replace multiple underscores with single
        filename = re.sub(r'_{2,}', '_', filename)
        
        # Remove leading/trailing underscores
        filename = filename.strip('_')
        
        # Limit length (leave room for .pdf extension)
        if len(filename) > 200:
            filename = filename[:200]
        
        # Ensure it's not empty
        if not filename:
            filename = f"document_{uuid.uuid4().hex[:8]}"
        
        return filename
    
    def _clean_component(self, value: str) -> str:
        """Clean component value for use in filename."""
        # Remove special characters
        value = re.sub(r'[^\w\s-]', '', value)
        
        # Replace spaces with underscores
        value = value.replace(' ', '_')
        
        # Remove multiple underscores
        value = re.sub(r'_{2,}', '_', value)
        
        # Convert to lowercase
        value = value.lower()
        
        # Truncate if too long
        if len(value) > 50:
            value = value[:50]
        
        return value.strip('_')
    
    def _guess_doc_type(self, text_sample: str) -> str:
        """Guess document type from text sample."""
        text_lower = text_sample.lower()
        
        for doc_type, patterns in self.DOC_TYPE_PATTERNS.items():
            for pattern in patterns:
                if pattern in text_lower:
                    return doc_type
        
        return "document"
    
    def _is_name_too_generic(self, filename: str) -> bool:
        """Check if generated name is too generic."""
        generic_terms = [
            'unknown', 'document', 'party', 'undated',
            'processed', 'file', 'pdf'
        ]
        
        # Count generic terms
        generic_count = sum(1 for term in generic_terms if term in filename.lower())
        
        # If more than 2 generic terms, it's too generic
        return generic_count > 2
    
    def _create_fallback_naming(self, document: PDFDocumentModel, error: str) -> SemanticNamingModel:
        """Create fallback naming when generation fails."""
        # Use timestamp and part of original filename
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        
        # Clean original filename
        base_name = document.original_filename.replace('.pdf', '')
        base_name = self._sanitize_filename(base_name)
        
        # Truncate if needed
        if len(base_name) > 100:
            base_name = base_name[:100]
        
        suggested_name = f"{timestamp}_{base_name}.pdf"
        
        return SemanticNamingModel(
            original_filename=document.original_filename,
            suggested_filename=suggested_name,
            naming_confidence=0.1,
            naming_template_used="fallback",
            extracted_components={'error': error},
            naming_timestamp=datetime.utcnow(),
            requires_human_review=True
        )
    
    def validate_naming(self, naming_model: SemanticNamingModel) -> Tuple[bool, List[str]]:
        """
        Validate a semantic naming model.
        
        Returns:
            Tuple of (is_valid, list_of_issues)
        """
        issues = []
        
        # Check confidence
        if naming_model.naming_confidence < 0.5:
            issues.append(f"Low confidence: {naming_model.naming_confidence:.2f}")
        
        # Check filename length
        if len(naming_model.suggested_filename) > 255:
            issues.append("Filename too long")
        
        # Check for required components
        if not naming_model.suggested_filename.endswith('.pdf'):
            issues.append("Missing .pdf extension")
        
        # Check for generic naming
        if self._is_name_too_generic(naming_model.suggested_filename):
            issues.append("Filename too generic")
        
        # Check for invalid characters (shouldn't happen but double-check)
        if re.search(r'[<>:"/\\|?*]', naming_model.suggested_filename):
            issues.append("Contains invalid characters")
        
        is_valid = len(issues) == 0
        return is_valid, issues
    
    async def generate_batch_names(
        self,
        documents: List[Tuple[PDFDocumentModel, DocumentCategory, str]],
        entities_map: Optional[Dict[str, List[Dict[str, Any]]]] = None
    ) -> List[SemanticNamingModel]:
        """
        Generate semantic names for multiple documents.
        
        Args:
            documents: List of (document, category, text_sample) tuples
            entities_map: Optional map of document_uuid to entities
            
        Returns:
            List of SemanticNamingModel instances
        """
        results = []
        
        for document, category, text_sample in documents:
            entities = None
            if entities_map and str(document.document_uuid) in entities_map:
                entities = entities_map[str(document.document_uuid)]
            
            naming_model = await self.generate_semantic_name(
                document, category, text_sample, entities
            )
            results.append(naming_model)
        
        return results