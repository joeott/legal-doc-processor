"""
Model Migration Helper for PDF-Only Pipeline.
Migrates existing schema models to new PDF-only models.
"""
from typing import Dict, Any, Optional, List
from datetime import datetime
import logging
import uuid

# Import consolidated models
from scripts.models import (
    SourceDocumentMinimal as SourceDocumentModel,
    DocumentChunkMinimal as ChunkModel,
    ProcessingStatus
)
# PDFDocumentModel and PDFChunkModel not in consolidated models
# This migration file appears unused

logger = logging.getLogger(__name__)


class ModelMigrator:
    """Migrate existing models to PDF-only models."""
    
    # Status mapping from old to new
    STATUS_MAP = {
        'pending_intake': NewStatus.PENDING_INTAKE,
        'validating': NewStatus.VALIDATING,
        'ocr_processing': NewStatus.OCR_PROCESSING,
        'ocr_in_progress': NewStatus.OCR_PROCESSING,
        'text_extraction': NewStatus.TEXT_EXTRACTION,
        'chunking': NewStatus.CHUNKING,
        'embedding_processing': NewStatus.VECTORIZING,
        'entity_extraction': NewStatus.ENTITY_EXTRACTION,
        'relationship_extraction': NewStatus.RELATIONSHIP_EXTRACTION,
        'neo4j_processing': NewStatus.PROJECT_ASSOCIATION,
        'completed': NewStatus.COMPLETED,
        'failed': NewStatus.FAILED,
        'ocr_failed': NewStatus.FAILED,
        'processing_failed': NewStatus.FAILED
    }
    
    @staticmethod
    def migrate_source_to_pdf(old_doc: SourceDocumentModel) -> PDFDocumentModel:
        """
        Convert old source document to new PDF model.
        
        Args:
            old_doc: Existing SourceDocumentModel instance
            
        Returns:
            New PDFDocumentModel with migrated data
        """
        # Only process PDF files
        if not old_doc.original_file_name.lower().endswith('.pdf'):
            raise ValueError(f"Cannot migrate non-PDF file: {old_doc.original_file_name}")
        
        # Map status - use celery_status field
        old_status = old_doc.celery_status or old_doc.initial_processing_status or 'pending_intake'
        new_status = ModelMigrator.STATUS_MAP.get(
            old_status.lower() if isinstance(old_status, str) else old_status,
            NewStatus.PENDING_INTAKE
        )
        
        # Create new model
        pdf_doc = PDFDocumentModel(
            # Identity
            document_uuid=old_doc.document_uuid,
            
            # File info
            original_filename=old_doc.original_file_name,
            file_size_bytes=old_doc.file_size_bytes or 0,
            file_hash=old_doc.md5_hash or ("0" * 64),  # Use existing hash or placeholder
            pdf_version=old_doc.ocr_metadata_json.get('pdf_version') if old_doc.ocr_metadata_json else None,
            page_count=old_doc.ocr_metadata_json.get('page_count') if old_doc.ocr_metadata_json else None,
            
            # Storage
            s3_key=old_doc.s3_key,
            storage_path=old_doc.original_file_path,
            
            # Processing state
            processing_status=new_status,
            processing_started_at=old_doc.intake_timestamp,
            processing_completed_at=old_doc.ocr_completed_at,
            
            # Extraction results
            ocr_confidence_score=old_doc.textract_confidence_avg,
            extracted_text=old_doc.raw_extracted_text,
            extracted_metadata=old_doc.ocr_metadata_json or {},
            
            # Project info (if available)
            project_id=old_doc.project_fk_id,
            
            # Error tracking
            error_message=old_doc.error_message,
            retry_count=0,  # Reset retry count
            
            # Audit fields
            created_at=old_doc.created_at or datetime.utcnow(),
            created_by="migration_script"
        )
        
        # Calculate processing duration if possible
        if pdf_doc.processing_started_at and pdf_doc.processing_completed_at:
            delta = pdf_doc.processing_completed_at - pdf_doc.processing_started_at
            pdf_doc.processing_duration_seconds = delta.total_seconds()
        
        return pdf_doc
    
    @staticmethod
    def migrate_chunk(old_chunk: ChunkModel, document_uuid: uuid.UUID) -> PDFChunkModel:
        """
        Convert old chunk model to new PDF chunk model.
        
        Args:
            old_chunk: Existing ChunkModel instance
            document_uuid: UUID of parent document
            
        Returns:
            New PDFChunkModel with migrated data
        """
        # Extract page numbers from metadata if available
        page_numbers = [1]  # Default to page 1
        if old_chunk.metadata_json:
            if 'page_number' in old_chunk.metadata_json:
                page_numbers = [old_chunk.metadata_json['page_number']]
            elif 'page_numbers' in old_chunk.metadata_json:
                page_numbers = old_chunk.metadata_json['page_numbers']
        
        pdf_chunk = PDFChunkModel(
            # Identity
            chunk_id=uuid.UUID(old_chunk.chunk_id) if isinstance(old_chunk.chunk_id, str) else old_chunk.chunk_id,
            document_uuid=document_uuid,
            
            # Position
            chunk_index=old_chunk.chunk_index,
            page_numbers=page_numbers,
            char_start=old_chunk.char_start_index,
            char_end=old_chunk.char_end_index,
            
            # Content
            text=old_chunk.text,
            chunk_type="semantic",  # Assume semantic chunking
            
            # Embeddings (if available)
            embedding_vector=old_chunk.embedding if hasattr(old_chunk, 'embedding') else None,
            embedding_model=old_chunk.embedding_model if hasattr(old_chunk, 'embedding_model') else None,
            
            # Relationships
            previous_chunk_id=uuid.UUID(old_chunk.previous_chunk_id) if old_chunk.previous_chunk_id else None,
            next_chunk_id=uuid.UUID(old_chunk.next_chunk_id) if old_chunk.next_chunk_id else None,
            
            # Metadata
            metadata=old_chunk.metadata_json or {},
            
            # Audit
            created_at=old_chunk.created_at or datetime.utcnow(),
            created_by="migration_script"
        )
        
        return pdf_chunk
    
    @staticmethod
    def validate_migration(
        old_docs: List[SourceDocumentModel], 
        new_docs: List[PDFDocumentModel]
    ) -> Dict[str, Any]:
        """
        Validate migration completeness and accuracy.
        
        Args:
            old_docs: List of original documents
            new_docs: List of migrated documents
            
        Returns:
            Validation report dictionary
        """
        # Filter to only PDF documents in old list
        old_pdfs = [d for d in old_docs if d.original_file_name.lower().endswith('.pdf')]
        
        validation = {
            "total_old_documents": len(old_docs),
            "pdf_documents": len(old_pdfs),
            "successfully_migrated": len(new_docs),
            "migration_rate": len(new_docs) / len(old_pdfs) if old_pdfs else 0,
            "non_pdf_skipped": len(old_docs) - len(old_pdfs),
            "validation_errors": [],
            "data_preserved": []
        }
        
        # Check each migrated document
        old_uuid_map = {str(d.document_uuid): d for d in old_pdfs}
        
        for new_doc in new_docs:
            uuid_str = str(new_doc.document_uuid)
            if uuid_str in old_uuid_map:
                old_doc = old_uuid_map[uuid_str]
                
                # Verify critical fields preserved
                if new_doc.original_filename != old_doc.original_file_name:
                    validation["validation_errors"].append(
                        f"Filename mismatch for {uuid_str}"
                    )
                
                if new_doc.s3_key != old_doc.s3_key:
                    validation["validation_errors"].append(
                        f"S3 key mismatch for {uuid_str}"
                    )
                
                # Track what was preserved
                if old_doc.raw_extracted_text and new_doc.extracted_text:
                    validation["data_preserved"].append("extracted_text")
                if old_doc.textract_confidence_avg and new_doc.ocr_confidence_score:
                    validation["data_preserved"].append("ocr_confidence")
            else:
                validation["validation_errors"].append(
                    f"New document {uuid_str} not found in old documents"
                )
        
        # Deduplicate preserved fields
        validation["data_preserved"] = list(set(validation["data_preserved"]))
        
        return validation
    
    @staticmethod
    def suggest_category(document: PDFDocumentModel) -> DocumentCategory:
        """
        Suggest a document category based on filename and content.
        This is a simple rule-based approach for migration.
        """
        filename_lower = document.original_filename.lower()
        
        # Simple keyword matching
        if any(word in filename_lower for word in ['complaint', 'answer', 'motion', 'brief']):
            return DocumentCategory.PLEADING
        elif any(word in filename_lower for word in ['discovery', 'interrogator', 'deposition']):
            return DocumentCategory.DISCOVERY  
        elif any(word in filename_lower for word in ['exhibit', 'affidavit', 'declaration']):
            return DocumentCategory.EVIDENCE
        elif any(word in filename_lower for word in ['letter', 'email', 'correspondence']):
            return DocumentCategory.CORRESPONDENCE
        elif any(word in filename_lower for word in ['invoice', 'receipt', 'statement']):
            return DocumentCategory.FINANCIAL
        elif any(word in filename_lower for word in ['contract', 'agreement', 'amendment']):
            return DocumentCategory.CONTRACT
        elif any(word in filename_lower for word in ['filing', 'regulatory', 'compliance']):
            return DocumentCategory.REGULATORY
        else:
            return DocumentCategory.UNKNOWN


def migrate_documents_batch(
    documents: List[Dict[str, Any]], 
    skip_non_pdf: bool = True
) -> tuple[List[PDFDocumentModel], Dict[str, Any]]:
    """
    Migrate a batch of documents from old schema to new.
    
    Args:
        documents: List of document dictionaries from database
        skip_non_pdf: Whether to skip non-PDF files
        
    Returns:
        Tuple of (migrated_documents, migration_report)
    """
    migrated = []
    report = {
        "total_processed": 0,
        "successfully_migrated": 0,
        "skipped_non_pdf": 0,
        "failed": 0,
        "errors": []
    }
    
    for doc_data in documents:
        report["total_processed"] += 1
        
        try:
            # Create old model from dict
            old_doc = SourceDocumentModel(**doc_data)
            
            # Check if PDF
            if not old_doc.original_file_name.lower().endswith('.pdf'):
                if skip_non_pdf:
                    report["skipped_non_pdf"] += 1
                    logger.info(f"Skipping non-PDF file: {old_doc.original_file_name}")
                    continue
                else:
                    raise ValueError(f"Non-PDF file: {old_doc.original_file_name}")
            
            # Migrate
            new_doc = ModelMigrator.migrate_source_to_pdf(old_doc)
            
            # Suggest category only if we can set confidence
            suggested_category = ModelMigrator.suggest_category(new_doc)
            if suggested_category != DocumentCategory.UNKNOWN:
                new_doc.category = suggested_category
                new_doc.category_confidence = 0.8  # Default confidence for rule-based
            
            migrated.append(new_doc)
            report["successfully_migrated"] += 1
            
        except Exception as e:
            report["failed"] += 1
            report["errors"].append({
                "document_id": doc_data.get('id'),
                "filename": doc_data.get('original_file_name'),
                "error": str(e)
            })
            logger.error(f"Failed to migrate document {doc_data.get('id')}: {e}")
    
    return migrated, report