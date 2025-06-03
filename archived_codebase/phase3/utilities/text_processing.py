"""
Utilities for text processing, cleaning, and document categorization for legal documents.
"""
import logging
import uuid
from typing import List, Dict, Any, Tuple, Optional
import re
import json

# Import Pydantic models
from scripts.core.processing_models import (
    ChunkingResultModel, ProcessedChunk, ChunkMetadata,
    StructuredExtractionResultModel, DocumentMetadata,
    ProcessingResultStatus
)
from scripts.core.schemas import ChunkModel
from scripts.core.conformance_validator import validate_before_operation, ConformanceError
from scripts.db import DatabaseManager

# Structured extraction currently disabled - module moved to archive
# from scripts.structured_extraction import StructuredExtractor, format_chunk_level_for_supabase

logger = logging.getLogger(__name__)

def clean_extracted_text(raw_text: str, validate: bool = True) -> str:
    """
    Clean the extracted text by removing artifacts and normalizing with validation.
    
    Args:
        raw_text: Raw text to clean
        validate: Whether to perform input validation
        
    Returns:
        Cleaned text
        
    Raises:
        ValueError: If input validation fails
    """
    if validate:
        if not isinstance(raw_text, str):
            raise ValueError(f"raw_text must be a string, got {type(raw_text)}")
    
    if not raw_text:
        return ""
    
    # Remove OCR artifacts and normalize
    cleaned_text = re.sub(r'<\|im_end\|>', '', raw_text)
    cleaned_text = re.sub(r'\s{3,}', '\n\n', cleaned_text)  # Normalize excessive whitespace
    cleaned_text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', cleaned_text)  # Remove control characters
    
    result = cleaned_text.strip()
    
    if validate and not result:
        logger.warning("Text cleaning resulted in empty string")
    
    return result

def categorize_document_text(text: str, metadata: Optional[Dict] = None, validate: bool = True) -> str:
    """
    Categorize the document based on its content and metadata with validation.
    
    Args:
        text: The document text
        metadata: Additional metadata about the document (e.g., OCR results)
        validate: Whether to perform input validation
        
    Returns:
        Category string (e.g., 'contract', 'affidavit', 'correspondence')
        
    Raises:
        ValueError: If input validation fails
    """
    if validate:
        if not isinstance(text, str):
            raise ValueError(f"text must be a string, got {type(text)}")
        
        if not text.strip():
            raise ValueError("text cannot be empty")
        
        if metadata is not None and not isinstance(metadata, dict):
            raise ValueError(f"metadata must be a dict or None, got {type(metadata)}")
    # Simple categorization rules
    text_lower = text.lower()
    
    # Check for specific document types
    if re.search(r'\bagreement\b|\bcontract\b|\bparties\b.*\bagree\b', text_lower):
        return 'contract'
    elif re.search(r'\baffidavit\b|\bsworn\b.*\bstatement\b|\bnotary\b', text_lower):
        return 'affidavit'
    elif re.search(r'\bletter\b|\bcorrespondence\b|\bear\s+sir\b|\bdear\s+madam\b', text_lower):
        return 'correspondence'
    elif re.search(r'\bexhibit\b|\bannex\b|\battachment\b', text_lower):
        return 'exhibit'
    elif re.search(r'\bdeposition\b|\btestimony\b|\bwitness\b', text_lower):
        return 'deposition'
    elif re.search(r'\bmotion\b|\bplaintiff\b|\bdefendant\b|\bcourt\b', text_lower):
        return 'legal_filing'
    elif re.search(r'\binvoice\b|\bpayment\b|\bamount\b|\btotal\b', text_lower):
        return 'financial'
    
    # Default category
    return 'document'

def generate_simple_markdown(text: str, validate: bool = True) -> str:
    """
    Generate simplified markdown structure from text for chunking guidance with validation.
    
    Args:
        text: The text to convert to markdown
        validate: Whether to perform input validation
        
    Returns:
        Markdown-formatted text
        
    Raises:
        ValueError: If input validation fails
    """
    if validate:
        if not isinstance(text, str):
            raise ValueError(f"text must be a string, got {type(text)}")
        
        if not text.strip():
            raise ValueError("text cannot be empty")
    # Split text into paragraphs
    paragraphs = re.split(r'\n{2,}', text)
    
    # Build markdown
    markdown_lines = []
    
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
            
        # Check if paragraph looks like a heading
        if len(para) < 100 and para.isupper():
            # All caps, short text - likely a heading
            markdown_lines.append(f"## {para}")
        elif re.match(r'^[\d\.]+\s+\w', para) and len(para.split('\n')[0]) < 80:
            # Numbered item that's short - likely a section heading
            markdown_lines.append(f"### {para}")
        else:
            # Regular paragraph
            markdown_lines.append(para)
    
    result = "\n\n".join(markdown_lines)
    
    if validate and not result.strip():
        logger.warning("Markdown generation resulted in empty output")
    
    return result

def process_document_with_semantic_chunking(
    db_manager,
    document_sql_id: int,
    document_uuid: str,
    raw_text: str,
    ocr_metadata: Optional[Dict] = None,
    doc_category: str = 'document',
    use_structured_extraction: bool = True
) -> Tuple[ChunkingResultModel, Optional[StructuredExtractionResultModel]]:
    """
    Process a document with semantic chunking and optional structured extraction
    
    Args:
        db_manager: SupabaseManager instance
        document_sql_id: SQL ID of the document
        document_uuid: UUID of the document
        raw_text: Raw text of the document
        ocr_metadata: OCR metadata (if available)
        doc_category: Document category
        use_structured_extraction: Whether to use structured extraction
        
    Returns:
        Tuple of (ChunkingResultModel, StructuredExtractionResultModel or None)
    """
    logger.info(f"Processing document {document_uuid} with semantic chunking")
    
    # Log initial document characteristics
    logger.info(f"Document {document_uuid}: Starting chunking with {len(raw_text)} raw characters")
    logger.info(f"Document {document_uuid}: Category: {doc_category}")
    
    # Create chunking result model
    chunking_result = ChunkingResultModel(
        document_uuid=uuid.UUID(document_uuid),
        document_id=document_sql_id,
        strategy="semantic_markdown",
        status=ProcessingResultStatus.SUCCESS
    )
    
    try:
        # Clean the text
        cleaned_text = clean_extracted_text(raw_text)
        logger.info(f"Document {document_uuid}: Cleaned text has {len(cleaned_text)} characters (reduced by {len(raw_text) - len(cleaned_text)})")
        
        # Log text characteristics
        word_count = len(cleaned_text.split())
        line_count = cleaned_text.count('\n')
        page_breaks = cleaned_text.count('<END_OF_PAGE>')
        logger.info(f"Document {document_uuid}: Text stats - {word_count} words, {line_count} lines, {page_breaks} page breaks")
        
        # Use plain text semantic chunking instead of markdown-based approach
        # This works better with Textract's plain text output
        from scripts.plain_text_chunker import chunk_plain_text_semantically
        
        # Get semantic chunks with enhanced metadata
        semantic_chunks = chunk_plain_text_semantically(
            cleaned_text,
            min_chunk_size=300,
            max_chunk_size=1500,
            enhance_metadata=True,
            document_uuid=document_uuid
        )
        
        # Log chunking results
        logger.info(f"Document {document_uuid}: Created {len(semantic_chunks)} semantic chunks")
        
        # Log details about first few chunks
        for i, chunk in enumerate(semantic_chunks[:3]):
            chunk_type = chunk.get('metadata', {}).get('type', 'unknown')
            chunk_size = len(chunk.get('text', ''))
            logger.info(f"  Chunk {i}: {chunk_size} chars, type: {chunk_type}, starts with: {chunk.get('text', '')[:50]}...")
        
        if len(semantic_chunks) > 3:
            logger.info(f"  ... and {len(semantic_chunks) - 3} more chunks")
        
        # Insert chunks into database
        raw_chunks = []
        chunk_insertion_errors = []
        
        for chunk_data in semantic_chunks:
            try:
                # Create chunk in database
                chunk_sql_id, chunk_uuid = db_manager.create_chunk_entry(
                    document_fk_id=document_sql_id,
                    document_uuid=document_uuid,
                    chunk_index=chunk_data['chunk_index'],
                    text_content=chunk_data['text'],
                    cleaned_text=chunk_data['text'],  # Already cleaned
                    char_start_index=chunk_data['char_start_index'],
                    char_end_index=chunk_data['char_end_index'],
                    metadata_json=chunk_data['metadata']
                )
                
                if chunk_sql_id and chunk_uuid:
                    chunk_data['sql_id'] = chunk_sql_id
                    chunk_data['chunk_uuid'] = chunk_uuid
                    chunk_data['chunkIndex'] = chunk_data['chunk_index']  # Add for compatibility
                    raw_chunks.append(chunk_data)
                    logger.debug(f"Created chunk {chunk_data['chunk_index']} (SQL ID: {chunk_sql_id})")
                else:
                    error_msg = f"Failed to get SQL ID or UUID for chunk {chunk_data['chunk_index']}"
                    logger.error(error_msg)
                    chunk_insertion_errors.append(error_msg)
                    
            except Exception as e:
                error_msg = f"Error inserting chunk {chunk_data.get('chunk_index', 'unknown')}: {e}"
                logger.error(error_msg)
                chunk_insertion_errors.append(error_msg)
        
        # Log chunk insertion summary
        logger.info(f"Document {document_uuid}: Successfully inserted {len(raw_chunks)}/{len(semantic_chunks)} chunks")
        if chunk_insertion_errors:
            logger.warning(f"Document {document_uuid}: {len(chunk_insertion_errors)} chunk insertion errors occurred")
        
        # Convert raw chunks to ProcessedChunk models
        processed_chunks = []
        for i, chunk in enumerate(raw_chunks):
            # Create chunk metadata
            chunk_metadata = ChunkMetadata(
                chunk_type="paragraph",
                language="en",
                page_numbers=chunk.get("page_numbers", [])
            )
            
            # Create processed chunk model
            processed_chunk = ProcessedChunk(
                chunk_id=uuid.UUID(chunk.get("chunk_uuid", str(uuid.uuid4()))),
                chunk_index=chunk.get("chunkIndex", i),
                text=chunk["text"],
                char_start=chunk.get("char_start_index", 0),
                char_end=chunk.get("char_end_index", len(chunk["text"])),
                token_count=len(chunk["text"].split()),  # Simple token estimation
                metadata=chunk_metadata
            )
            
            # Set up chunk linking
            if i > 0:
                processed_chunk.previous_chunk_id = processed_chunks[i-1].chunk_id
            if i < len(raw_chunks) - 1:
                # We'll set this in the next iteration
                pass
                
            processed_chunks.append(processed_chunk)
        
        # Set next_chunk_id for all chunks except the last
        for i in range(len(processed_chunks) - 1):
            processed_chunks[i].next_chunk_id = processed_chunks[i + 1].chunk_id
        
        # Update chunking result model
        chunking_result.chunks = processed_chunks
        chunking_result.total_chunks = len(processed_chunks)
        chunking_result.total_characters = len(cleaned_text)
        
        # Calculate average chunk size
        if processed_chunks:
            total_chars = sum(len(chunk.text) for chunk in processed_chunks)
            chunking_result.average_chunk_size = total_chars / len(processed_chunks)
        
        # Perform structured extraction if enabled
        structured_extraction_result = None
        if use_structured_extraction:
            logger.warning("Structured extraction requested but module is disabled")
            # structured_extractor = StructuredExtractor()
            # 
            # # Create document metadata
            # doc_metadata = DocumentMetadata(
            #     document_type=doc_category,
            #     title=None  # Will be extracted if found
            # )
            # 
            # # Create structured extraction result
            # structured_extraction_result = StructuredExtractionResultModel(
            #     document_uuid=uuid.UUID(document_uuid),
            #     metadata=doc_metadata,
            #     status=ProcessingResultStatus.SUCCESS
            # )
            # 
            # entities_with_chunks = 0
            # 
            # for chunk in processed_chunks:
            #     chunk_metadata_dict = {
            #         "doc_category": doc_category,
            #         "chunk_index": chunk.chunk_index,
            #         "char_range": f"{chunk.char_start}-{chunk.char_end}"
            #     }
            #     
            #     # Extract structured data from chunk
            #     structured_data = structured_extractor.extract_structured_data_from_chunk(
            #         chunk_text=chunk.text,
            #         chunk_metadata=chunk_metadata_dict
            #     )
            #     
            #     if structured_data:
            #         # Format for Supabase storage
            #         formatted_data = format_chunk_level_for_supabase(structured_data)
            #             
            #         # Update chunk with structured data in database
            #         db_manager.update_chunk_metadata(
            #             chunk_sql_id=raw_chunks[chunk.chunk_index].get("sql_id"),
            #             metadata_json=formatted_data
            #         )
            #         
            #         # Add entities to structured extraction result
            #         if hasattr(structured_data, 'entities') and structured_data.entities:
            #             structured_extraction_result.entities.extend(structured_data.entities)
            #             entities_with_chunks += 1
            #         
            #         # Add key facts to structured extraction result
            #         if hasattr(structured_data, 'key_facts') and structured_data.key_facts:
            #             structured_extraction_result.key_facts.extend(structured_data.key_facts)
            #         
            #         # Add relationships to structured extraction result
            #         if hasattr(structured_data, 'relationships') and structured_data.relationships:
            #             structured_extraction_result.relationships.extend(structured_data.relationships)
            #         
            #         # Update document metadata if found
            #         if structured_data.document_metadata.document_type != "Unknown":
            #             structured_extraction_result.metadata.document_type = structured_data.document_metadata.document_type
            #         
            #         if structured_data.document_metadata.title:
            #             structured_extraction_result.metadata.title = structured_data.document_metadata.title
            # 
            # # Update chunks with entities count
            # chunking_result.chunks_with_entities = entities_with_chunks
            # 
            # # Calculate extraction completeness and confidence
            # if structured_extraction_result.entities:
            #     structured_extraction_result.extraction_completeness = min(1.0, len(structured_extraction_result.entities) / 10.0)  # Assume 10 entities is "complete"
            #     avg_confidence = sum(e.confidence for e in structured_extraction_result.entities) / len(structured_extraction_result.entities)
            #     structured_extraction_result.confidence_score = avg_confidence
        
        # Log final processing summary
        logger.info(f"Document {document_uuid}: Processing complete")
        logger.info(f"  Total chunks: {len(processed_chunks)}")
        logger.info(f"  Average chunk size: {chunking_result.average_chunk_size:.1f} chars")
        logger.info(f"  Coverage: {(chunking_result.total_characters / len(raw_text) * 100):.1f}% of original text")
        
        if structured_extraction_result:
            logger.info("  Structured extraction was requested but is currently disabled")
        
        return chunking_result, structured_extraction_result
        
    except Exception as e:
        logger.error(f"Error processing document {document_uuid}: {e}", exc_info=True)
        
        # Update chunking result with error
        chunking_result.status = ProcessingResultStatus.FAILED
        chunking_result.error_message = str(e)
        
        return chunking_result, None


def convert_chunks_to_models(raw_chunks: List[Dict[str, Any]], document_uuid: str) -> List[ChunkModel]:
    """
    Convert raw chunk dictionaries to validated ChunkModel instances
    
    Args:
        raw_chunks: List of raw chunk dictionaries
        document_uuid: UUID of the source document
        
    Returns:
        List of validated ChunkModel instances
    """
    chunk_models = []
    
    for chunk_data in raw_chunks:
        try:
            # Create ChunkModel with validation
            chunk_model = ChunkModel(
                chunk_uuid=uuid.UUID(chunk_data.get("chunk_uuid", str(uuid.uuid4()))),
                document_uuid=uuid.UUID(document_uuid),
                chunk_index=chunk_data.get("chunkIndex", 0),
                text=chunk_data["text"],
                char_start_index=chunk_data.get("char_start_index", 0),
                char_end_index=chunk_data.get("char_end_index", len(chunk_data["text"])),
                token_count=chunk_data.get("token_count", len(chunk_data["text"].split())),
                embedding_model=chunk_data.get("embedding_model"),
                embedding_dimensions=chunk_data.get("embedding_dimensions"),
                metadata_json=chunk_data.get("metadata_json", {}),
                processing_notes=chunk_data.get("processing_notes")
            )
            
            chunk_models.append(chunk_model)
            
        except Exception as e:
            logger.error(f"Failed to create ChunkModel from data: {e}")
            logger.error(f"Chunk data: {chunk_data}")
            continue
    
    return chunk_models