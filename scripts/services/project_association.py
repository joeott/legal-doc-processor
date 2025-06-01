"""
Project Association Service for PDF Documents.
Uses LLM and vector similarity to intelligently associate documents with projects.
"""
import logging
import numpy as np
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime
import json

from scripts.core.pdf_models import (
    PDFDocumentModel, PDFChunkModel, 
    ProjectAssociationModel, ProcessingStatus
)
from scripts.core.schemas import Neo4jDocumentModel
from scripts.db import DatabaseManager
from scripts.cache import get_redis_manager, CacheKeys

logger = logging.getLogger(__name__)


class ProjectAssociationService:
    """Service for associating documents with projects using LLM and embeddings."""
    
    def __init__(self, db_manager: DatabaseManager, llm_client=None, embedding_service=None):
        """
        Initialize the project association service.
        
        Args:
            db_manager: Database manager for project data
            llm_client: LLM client for intelligent association
            embedding_service: Service for generating embeddings
        """
        self.db = db_manager
        self.llm = llm_client
        self.embeddings = embedding_service
        self.redis = get_redis_manager()
        
        # Cache for project data
        self._project_cache = {}
        self._project_embedding_cache = {}
    
    async def associate_document(
        self,
        document: PDFDocumentModel,
        chunks: List[PDFChunkModel],
        existing_projects: Optional[List[dict]] = None
    ) -> ProjectAssociationModel:
        """
        Associate document with a project using LLM analysis and vector similarity.
        
        Args:
            document: PDF document to associate
            chunks: Document chunks with text
            existing_projects: Optional list of projects (will fetch if not provided)
            
        Returns:
            ProjectAssociationModel with association details
        """
        logger.info(f"Starting project association for document {document.document_uuid}")
        
        # Get existing projects if not provided
        if existing_projects is None:
            existing_projects = await self._get_active_projects()
        
        if not existing_projects:
            logger.warning("No active projects found for association")
            return self._create_no_project_association(document)
        
        # Extract key information from document
        entities = await self._extract_key_entities(chunks)
        summary = await self._generate_document_summary(chunks)
        
        # Get embeddings for similarity matching
        doc_embedding = await self._get_document_embedding(summary, chunks)
        project_embeddings = await self._get_project_embeddings(existing_projects)
        
        # Calculate similarity scores
        similarities = self._calculate_similarities(doc_embedding, project_embeddings)
        
        # Prepare context for LLM
        context = self._build_llm_context(
            document, entities, summary, existing_projects, similarities
        )
        
        # Get LLM recommendation
        llm_response = await self._get_llm_recommendation(context)
        
        # Parse and validate response
        association = self._parse_llm_response(llm_response, existing_projects)
        
        # Create association model
        return ProjectAssociationModel(
            document_uuid=document.document_uuid,
            project_id=association['project_id'],
            confidence_score=association['confidence'],
            reasoning=association['reasoning'],
            evidence_chunks=[c.chunk_id for c in chunks[:5]],  # Top 5 most relevant
            association_method='llm',
            llm_model=self.llm.model_name if self.llm else 'gpt-4',
            requires_review=association['confidence'] < 0.85
        )
    
    async def _get_active_projects(self) -> List[Dict[str, Any]]:
        """Fetch active projects from database."""
        cache_key = CacheKeys.active_projects()
        
        # Check cache first
        cached = self.redis.get_cached(cache_key)
        if cached:
            return cached
        
        # Fetch from database
        try:
            result = self.db.client.table('projects').select(
                'id', 'name', 'description', 'client_name', 
                'project_code', 'status', 'created_at'
            ).eq('status', 'active').execute()
            
            projects = result.data if result.data else []
            
            # Cache for 1 hour
            self.redis.set_cached(cache_key, projects, ttl=3600)
            
            return projects
            
        except Exception as e:
            logger.error(f"Failed to fetch projects: {e}")
            return []
    
    async def _extract_key_entities(self, chunks: List[PDFChunkModel]) -> List[str]:
        """Extract key entities from chunks."""
        entities = []
        
        # Simple extraction - in production, use NER model
        for chunk in chunks[:10]:  # First 10 chunks
            # Extract capitalized words as potential entities
            words = chunk.text.split()
            for i, word in enumerate(words):
                if word[0].isupper() and len(word) > 2:
                    # Check if it's part of a multi-word entity
                    if i > 0 and words[i-1][0].isupper():
                        entities[-1] = f"{entities[-1]} {word}"
                    else:
                        entities.append(word)
        
        # Deduplicate and return top entities
        unique_entities = list(dict.fromkeys(entities))
        return unique_entities[:20]
    
    async def _generate_document_summary(self, chunks: List[PDFChunkModel]) -> str:
        """Generate a summary of the document."""
        # Combine first few chunks
        text_sample = " ".join([c.text for c in chunks[:5]])
        
        # Truncate to reasonable length
        if len(text_sample) > 2000:
            text_sample = text_sample[:2000] + "..."
        
        return text_sample
    
    async def _get_document_embedding(self, summary: str, chunks: List[PDFChunkModel]) -> np.ndarray:
        """Generate embedding for document."""
        # In production, use actual embedding service
        # For now, return mock embedding
        logger.info("Generating document embedding")
        
        # Combine summary with key chunk text
        text_for_embedding = summary
        if chunks:
            text_for_embedding += " " + " ".join([c.text[:100] for c in chunks[:3]])
        
        # Mock embedding - in production use OpenAI/other service
        embedding = np.random.rand(1536)  # Standard embedding size
        return embedding / np.linalg.norm(embedding)  # Normalize
    
    async def _get_project_embeddings(self, projects: List[Dict[str, Any]]) -> Dict[int, np.ndarray]:
        """Get embeddings for all projects."""
        embeddings = {}
        
        for project in projects:
            # Check cache first
            cache_key = f"project_embedding:{project['id']}"
            cached = self.redis.get_cached(cache_key)
            
            if cached:
                embeddings[project['id']] = np.array(cached)
            else:
                # Generate embedding from project data
                project_text = f"{project['name']} {project.get('description', '')} {project.get('client_name', '')}"
                
                # Mock embedding - in production use actual service
                embedding = np.random.rand(1536)
                embedding = embedding / np.linalg.norm(embedding)
                
                embeddings[project['id']] = embedding
                
                # Cache for 24 hours
                self.redis.set_cached(cache_key, embedding.tolist(), ttl=86400)
        
        return embeddings
    
    def _calculate_similarities(
        self, 
        doc_embedding: np.ndarray, 
        project_embeddings: Dict[int, np.ndarray]
    ) -> Dict[int, float]:
        """Calculate cosine similarity between document and projects."""
        similarities = {}
        
        for project_id, proj_embedding in project_embeddings.items():
            # Cosine similarity
            similarity = np.dot(doc_embedding, proj_embedding)
            similarities[project_id] = float(similarity)
        
        return similarities
    
    def _build_llm_context(
        self,
        document: PDFDocumentModel,
        entities: List[str],
        summary: str,
        projects: List[Dict[str, Any]],
        similarities: Dict[int, float]
    ) -> str:
        """Build context for LLM analysis."""
        # Sort projects by similarity
        sorted_projects = sorted(
            projects,
            key=lambda p: similarities.get(p['id'], 0),
            reverse=True
        )
        
        context = f"""
Analyze this legal document and determine which project it belongs to.

Document Information:
- Original Filename: {document.original_filename}
- Page Count: {document.page_count or 'Unknown'}
- Key Entities Found: {', '.join(entities[:10])}

Document Summary (first 500 chars):
{summary[:500]}

Available Projects (sorted by relevance):
"""
        
        for i, project in enumerate(sorted_projects[:5], 1):
            similarity = similarities.get(project['id'], 0)
            context += f"""
{i}. Project: {project['name']} (ID: {project['id']})
   Client: {project.get('client_name', 'N/A')}
   Description: {project.get('description', 'No description')[:200]}
   Similarity Score: {similarity:.3f}
"""
        
        context += """

Based on the document content, entities, and similarity scores:
1. Which project does this document most likely belong to? (provide project ID)
2. What is your confidence level (0.0-1.0)?
3. Provide a brief reasoning (2-3 sentences) for your choice.

Respond in JSON format:
{
    "project_id": <number>,
    "confidence": <float between 0 and 1>,
    "reasoning": "<explanation>"
}
"""
        
        return context
    
    async def _get_llm_recommendation(self, context: str) -> str:
        """Get project recommendation from LLM."""
        if not self.llm:
            # Fallback logic when no LLM available
            logger.warning("No LLM client available, using fallback logic")
            return json.dumps({
                "project_id": 1,
                "confidence": 0.5,
                "reasoning": "No LLM available - using fallback assignment"
            })
        
        try:
            response = await self.llm.complete(
                context,
                temperature=0.3,  # Low temperature for consistency
                max_tokens=200
            )
            return response
            
        except Exception as e:
            logger.error(f"LLM request failed: {e}")
            return json.dumps({
                "project_id": 1,
                "confidence": 0.3,
                "reasoning": f"LLM error: {str(e)}"
            })
    
    def _parse_llm_response(
        self, 
        response: str, 
        valid_projects: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Parse and validate LLM response."""
        try:
            # Extract JSON from response
            # Handle case where LLM adds explanation before/after JSON
            start_idx = response.find('{')
            end_idx = response.rfind('}') + 1
            
            if start_idx >= 0 and end_idx > start_idx:
                json_str = response[start_idx:end_idx]
                parsed = json.loads(json_str)
            else:
                raise ValueError("No JSON found in response")
            
            # Validate project ID
            project_id = int(parsed.get('project_id', 0))
            valid_ids = [p['id'] for p in valid_projects]
            
            if project_id not in valid_ids:
                # Use first project as fallback
                project_id = valid_ids[0] if valid_ids else 1
                parsed['confidence'] = min(parsed.get('confidence', 0.5), 0.5)
                parsed['reasoning'] = f"Invalid project ID suggested. {parsed.get('reasoning', '')}"
            
            # Ensure confidence is in valid range
            confidence = float(parsed.get('confidence', 0.5))
            confidence = max(0.0, min(1.0, confidence))
            
            return {
                'project_id': project_id,
                'confidence': confidence,
                'reasoning': parsed.get('reasoning', 'No reasoning provided')[:1000]
            }
            
        except Exception as e:
            logger.error(f"Failed to parse LLM response: {e}")
            logger.debug(f"Response was: {response}")
            
            # Fallback
            return {
                'project_id': valid_projects[0]['id'] if valid_projects else 1,
                'confidence': 0.3,
                'reasoning': f"Failed to parse LLM response: {str(e)}"
            }
    
    def _create_no_project_association(self, document: PDFDocumentModel) -> ProjectAssociationModel:
        """Create association when no projects are available."""
        return ProjectAssociationModel(
            document_uuid=document.document_uuid,
            project_id=0,  # Special ID for no project
            confidence_score=1.0,
            reasoning="No active projects available for association",
            evidence_chunks=[],
            association_method='rule_based',
            requires_review=True
        )
    
    async def get_project_details(self, project_id: int) -> Optional[Dict[str, Any]]:
        """Get detailed information about a project."""
        cache_key = f"project_details:{project_id}"
        
        # Check cache
        cached = self.redis.get_cached(cache_key)
        if cached:
            return cached
        
        try:
            result = self.db.client.table('projects').select('*').eq('id', project_id).single().execute()
            if result.data:
                # Cache for 1 hour
                self.redis.set_cached(cache_key, result.data, ttl=3600)
                return result.data
        except Exception as e:
            logger.error(f"Failed to fetch project {project_id}: {e}")
        
        return None