"""
Integrated PDF Processing Pipeline.
Single entry point for processing PDF documents through all stages.
"""
import os
import hashlib
import logging
from typing import Optional, Dict, Any, List
from pathlib import Path
import asyncio
from datetime import datetime

from scripts.core.pdf_models import (
    PDFDocumentModel, PDFChunkModel, PDFProcessingPipelineModel,
    ProcessingStatus, DocumentCategory
)
# from scripts.core.db_migration_helper import DatabaseType  # Not needed
from scripts.services.project_association import ProjectAssociationService
from scripts.services.document_categorization import DocumentCategorizationService
from scripts.services.semantic_naming import SemanticNamingService
from scripts.ocr_extraction import extract_text_from_pdf
from scripts.text_processing import chunk_text_with_overlap
from scripts.entity_service import extract_entities_from_chunk
from scripts.s3_storage import upload_to_s3, generate_s3_key
from scripts.db import DatabaseManager
from scripts.config import OPENAI_API_KEY
from scripts.cache import get_redis_manager

logger = logging.getLogger(__name__)


class PDFProcessingPipeline:
    """
    Integrated PDF processing pipeline.
    Coordinates all processing stages from intake to completion.
    """
    
    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        db_manager: Optional[DatabaseManager] = None,
        openai_api_key: Optional[str] = None
    ):
        """
        Initialize pipeline with services and configuration.
        
        Args:
            config: Optional configuration overrides
            db_manager: Database manager instance
            openai_api_key: OpenAI API key for LLM services
        """
        self.config = config or {}
        self.db = db_manager or DatabaseManager()
        self.api_key = openai_api_key or OPENAI_API_KEY
        
        # Initialize services
        self.project_service = ProjectAssociationService(self.api_key)
        self.category_service = DocumentCategorizationService(self.api_key)
        self.naming_service = SemanticNamingService(self.api_key)
        
        # Redis for caching
        self.redis_manager = get_redis_manager()
        
        # Processing options
        self.chunk_size = self.config.get('chunk_size', 1000)
        self.chunk_overlap = self.config.get('chunk_overlap', 200)
        self.confidence_threshold = self.config.get('confidence_threshold', 0.7)
    
    async def process_pdf(
        self,
        pdf_path: str,
        original_name: str,
        user_id: Optional[str] = None,
        project_hint: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> PDFProcessingPipelineModel:
        """
        Process PDF through entire pipeline.
        
        Args:
            pdf_path: Path to PDF file
            original_name: Original filename
            user_id: User initiating processing
            project_hint: Optional project hint for association
            metadata: Optional additional metadata
            
        Returns:
            Completed PDFProcessingPipelineModel
        """
        logger.info(f"Starting PDF pipeline for: {original_name}")
        
        # Validate PDF exists
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF not found: {pdf_path}")
        
        # Create document model
        doc = await self._create_document(pdf_path, original_name, user_id)
        
        # Create pipeline model
        pipeline = PDFProcessingPipelineModel(
            document=doc,
            processing_metadata={
                'start_time': datetime.utcnow().isoformat(),
                'original_path': pdf_path,
                'project_hint': project_hint
            }
        )
        
        try:
            # Stage 1: Upload to S3
            await self._upload_document(pipeline, pdf_path)
            
            # Stage 2: OCR Extraction
            await self._extract_text(pipeline, pdf_path)
            
            # Stage 3: Chunking
            await self._chunk_document(pipeline)
            
            # Stage 4: Entity Extraction
            await self._extract_entities(pipeline)
            
            # Stage 5: Document Categorization
            await self._categorize_document(pipeline)
            
            # Stage 6: Project Association
            await self._associate_project(pipeline, project_hint)
            
            # Stage 7: Semantic Naming
            await self._generate_semantic_name(pipeline)
            
            # Stage 8: Persist to Database
            await self._persist_pipeline(pipeline)
            
            # Mark as completed
            pipeline.document.transition_to(ProcessingStatus.COMPLETED)
            pipeline.processing_metadata['end_time'] = datetime.utcnow().isoformat()
            
            logger.info(
                f"Pipeline completed for {doc.document_uuid}: "
                f"Category={pipeline.document.category}, "
                f"Project={pipeline.document.project_id}, "
                f"Name={pipeline.semantic_naming.suggested_filename if pipeline.semantic_naming else 'N/A'}"
            )
            
        except Exception as e:
            logger.error(f"Pipeline failed for {doc.document_uuid}: {e}")
            pipeline.document.transition_to(ProcessingStatus.FAILED, str(e))
            pipeline.processing_metadata['error'] = str(e)
            pipeline.processing_metadata['failed_at'] = datetime.utcnow().isoformat()
            
            # Still try to persist partial results
            try:
                await self._persist_pipeline(pipeline)
            except Exception as persist_error:
                logger.error(f"Failed to persist error state: {persist_error}")
            
            raise
        
        return pipeline
    
    async def _create_document(
        self,
        pdf_path: str,
        original_name: str,
        user_id: Optional[str] = None
    ) -> PDFDocumentModel:
        """Create initial document model."""
        # Calculate file hash
        file_hash = self._calculate_file_hash(pdf_path)
        
        # Get file size
        file_size = os.path.getsize(pdf_path)
        
        # Create document
        doc = PDFDocumentModel(
            original_filename=original_name,
            file_size_bytes=file_size,
            file_hash=file_hash,
            s3_key="",  # Will be set after upload
            created_by=user_id or "system",
            processing_status=ProcessingStatus.PENDING_INTAKE
        )
        
        return doc
    
    def _calculate_file_hash(self, file_path: str) -> str:
        """Calculate SHA-256 hash of file."""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    
    async def _upload_document(self, pipeline: PDFProcessingPipelineModel, pdf_path: str):
        """Upload document to S3."""
        logger.debug("Uploading document to S3")
        
        # Generate S3 key
        s3_key = generate_s3_key(
            pipeline.document.original_filename,
            pipeline.document.created_by
        )
        
        # Upload
        s3_url = await upload_to_s3(pdf_path, s3_key)
        
        # Update document
        pipeline.document.s3_key = s3_key
        pipeline.document.s3_url = s3_url
        
        logger.debug(f"Document uploaded to: {s3_key}")
    
    async def _extract_text(self, pipeline: PDFProcessingPipelineModel, pdf_path: str):
        """Extract text using OCR."""
        logger.debug("Extracting text from PDF")
        
        # Transition to OCR processing
        pipeline.document.transition_to(ProcessingStatus.OCR_PROCESSING)
        
        # Extract text (this will use Textract)
        result = await extract_text_from_pdf(
            pdf_path,
            pipeline.document,
            self.db,
            0  # source_doc_sql_id - will be set later
        )
        
        # Update document with results
        pipeline.document.extracted_text = result.get('text', '')
        pipeline.document.ocr_confidence_score = result.get('confidence', 0.0)
        pipeline.document.page_count = result.get('page_count', 0)
        pipeline.document.extracted_metadata = result.get('metadata', {})
        
        # Transition to next stage
        pipeline.document.transition_to(ProcessingStatus.TEXT_EXTRACTION)
        
        logger.debug(f"Extracted {len(pipeline.document.extracted_text)} characters")
    
    async def _chunk_document(self, pipeline: PDFProcessingPipelineModel):
        """Chunk document text."""
        logger.debug("Chunking document")
        
        if not pipeline.document.extracted_text:
            logger.warning("No text to chunk")
            return
        
        # Transition to chunking
        pipeline.document.transition_to(ProcessingStatus.CHUNKING)
        
        # Chunk text
        chunks = await chunk_text_with_overlap(
            pipeline.document.extracted_text,
            chunk_size=self.chunk_size,
            overlap_size=self.chunk_overlap,
            document_uuid=pipeline.document.document_uuid
        )
        
        # Convert to PDFChunkModel
        pipeline.chunks = []
        for i, chunk_data in enumerate(chunks):
            chunk_model = PDFChunkModel(
                document_uuid=pipeline.document.document_uuid,
                chunk_index=i,
                start_position=chunk_data['start_position'],
                end_position=chunk_data['end_position'],
                content=chunk_data['text'],
                chunk_metadata={
                    'page_numbers': chunk_data.get('metadata', {}).get('page_numbers', []),
                    'semantic_type': chunk_data.get('metadata', {}).get('semantic_type', 'body')
                }
            )
            pipeline.chunks.append(chunk_model)
        
        logger.debug(f"Created {len(pipeline.chunks)} chunks")
    
    async def _extract_entities(self, pipeline: PDFProcessingPipelineModel):
        """Extract entities from chunks."""
        logger.debug("Extracting entities")
        
        if not pipeline.chunks:
            logger.warning("No chunks to process")
            return
        
        # Transition to entity extraction
        pipeline.document.transition_to(ProcessingStatus.ENTITY_EXTRACTION)
        
        # Extract entities from each chunk
        all_entities = []
        for chunk in pipeline.chunks[:10]:  # Process first 10 chunks for entities
            try:
                result = extract_entities_from_chunk(
                    chunk.content,
                    chunk_id=chunk.chunk_id,
                    use_openai=True  # Use OpenAI for Stage 1
                )
                
                if result.entities:
                    all_entities.extend(result.entities)
                    
            except Exception as e:
                logger.error(f"Entity extraction failed for chunk {chunk.chunk_index}: {e}")
        
        # Store entities
        pipeline.entities = all_entities
        
        # Store summary in document
        if all_entities:
            entity_summary = {}
            for entity in all_entities:
                entity_type = entity.entity_type
                if entity_type not in entity_summary:
                    entity_summary[entity_type] = []
                if entity.text not in entity_summary[entity_type]:
                    entity_summary[entity_type].append(entity.text)
            
            pipeline.document.entity_summary = {
                k: v[:10] for k, v in entity_summary.items()  # Top 10 per type
            }
        
        logger.debug(f"Extracted {len(all_entities)} entities")
    
    async def _categorize_document(self, pipeline: PDFProcessingPipelineModel):
        """Categorize document using LLM."""
        logger.debug("Categorizing document")
        
        # Get text sample (first 2000 chars)
        text_sample = pipeline.document.extracted_text[:2000]
        
        # Get entities for context
        entity_list = [
            {'text': e.text, 'type': e.entity_type}
            for e in pipeline.entities[:20]
        ] if pipeline.entities else None
        
        # Categorize
        category, confidence, reasoning = await self.category_service.categorize_document(
            pipeline.document,
            text_sample,
            additional_context={'entities': entity_list} if entity_list else None
        )
        
        # Update document
        pipeline.document.category = category
        pipeline.document.category_confidence = confidence
        pipeline.processing_metadata['category_reasoning'] = reasoning
        
        logger.debug(f"Categorized as: {category.value} (confidence: {confidence:.2f})")
    
    async def _associate_project(
        self,
        pipeline: PDFProcessingPipelineModel,
        project_hint: Optional[str] = None
    ):
        """Associate document with project."""
        logger.debug("Associating with project")
        
        # Get existing projects
        existing_projects = await self._get_existing_projects()
        
        # Associate
        association = await self.project_service.associate_document(
            pipeline.document,
            pipeline.chunks[:5],  # Use first 5 chunks
            existing_projects,
            project_hint
        )
        
        # Update document
        pipeline.document.project_id = association.assigned_project_id
        pipeline.document.project_association_confidence = association.confidence_score
        pipeline.document.project_association_method = association.association_method
        
        # Store association model
        pipeline.project_association = association
        
        logger.debug(
            f"Associated with project: {association.assigned_project_id} "
            f"(confidence: {association.confidence_score:.2f})"
        )
    
    async def _generate_semantic_name(self, pipeline: PDFProcessingPipelineModel):
        """Generate semantic filename."""
        logger.debug("Generating semantic name")
        
        # Get text sample
        text_sample = pipeline.document.extracted_text[:1500]
        
        # Get entity list for naming
        entities = [
            {'text': e.text, 'type': e.entity_type}
            for e in pipeline.entities[:10]
        ] if pipeline.entities else None
        
        # Generate name
        naming = await self.naming_service.generate_semantic_name(
            pipeline.document,
            pipeline.document.category or DocumentCategory.UNKNOWN,
            text_sample,
            entities,
            pipeline.document.extracted_metadata
        )
        
        # Store naming model
        pipeline.semantic_naming = naming
        
        # Optionally update document filename if high confidence
        if naming.naming_confidence >= self.confidence_threshold:
            pipeline.document.semantic_filename = naming.suggested_filename
        
        logger.debug(
            f"Generated name: {naming.suggested_filename} "
            f"(confidence: {naming.naming_confidence:.2f})"
        )
    
    async def _persist_pipeline(self, pipeline: PDFProcessingPipelineModel):
        """Persist pipeline results to database."""
        logger.debug("Persisting pipeline results")
        
        # Save document
        doc_data = pipeline.document.model_dump(mode='json')
        doc_result = await self.db.create_source_document_entry(doc_data)
        
        if doc_result and 'id' in doc_result:
            pipeline.document.sql_id = doc_result['id']
            
            # Save chunks
            for chunk in pipeline.chunks:
                chunk_data = chunk.model_dump(mode='json')
                chunk_data['source_document_id'] = pipeline.document.sql_id
                await self.db.client.table('document_chunks').insert(chunk_data).execute()
            
            # Save entities
            for entity in pipeline.entities:
                entity_data = {
                    'document_uuid': str(pipeline.document.document_uuid),
                    'chunk_id': str(entity.chunk_id) if hasattr(entity, 'chunk_id') else None,
                    'entity_type': entity.entity_type,
                    'text': entity.text,
                    'confidence': getattr(entity, 'confidence', 0.8),
                    'created_at': datetime.utcnow().isoformat()
                }
                await self.db.client.table('entity_mentions').insert(entity_data).execute()
        
        logger.debug("Pipeline results persisted")
    
    async def _get_existing_projects(self) -> List[Dict[str, Any]]:
        """Get list of existing projects."""
        try:
            result = await self.db.client.table('projects').select('*').execute()
            return result.data if result.data else []
        except Exception as e:
            logger.error(f"Failed to fetch projects: {e}")
            return []
    
    async def process_batch(
        self,
        pdf_files: List[Dict[str, str]],
        user_id: Optional[str] = None,
        max_concurrent: int = 3
    ) -> List[PDFProcessingPipelineModel]:
        """
        Process multiple PDFs concurrently.
        
        Args:
            pdf_files: List of dicts with 'path' and 'name' keys
            user_id: User initiating processing
            max_concurrent: Maximum concurrent processing
            
        Returns:
            List of pipeline results
        """
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def process_with_semaphore(pdf_info):
            async with semaphore:
                try:
                    return await self.process_pdf(
                        pdf_info['path'],
                        pdf_info['name'],
                        user_id
                    )
                except Exception as e:
                    logger.error(f"Failed to process {pdf_info['name']}: {e}")
                    return None
        
        tasks = [process_with_semaphore(pdf) for pdf in pdf_files]
        results = await asyncio.gather(*tasks)
        
        # Filter out None results
        return [r for r in results if r is not None]
    
    def get_pipeline_status(self, pipeline: PDFProcessingPipelineModel) -> Dict[str, Any]:
        """Get current status of pipeline processing."""
        return {
            'document_id': str(pipeline.document.document_uuid),
            'status': pipeline.document.processing_status.value,
            'stages_completed': {
                'upload': bool(pipeline.document.s3_key),
                'ocr': bool(pipeline.document.extracted_text),
                'chunking': len(pipeline.chunks) > 0,
                'entities': len(pipeline.entities) > 0,
                'categorization': pipeline.document.category is not None,
                'project_association': pipeline.document.project_id is not None,
                'semantic_naming': pipeline.semantic_naming is not None
            },
            'metrics': {
                'page_count': pipeline.document.page_count,
                'chunk_count': len(pipeline.chunks),
                'entity_count': len(pipeline.entities),
                'ocr_confidence': pipeline.document.ocr_confidence_score,
                'category': pipeline.document.category.value if pipeline.document.category else None,
                'category_confidence': pipeline.document.category_confidence,
                'project_confidence': pipeline.document.project_association_confidence
            }
        }