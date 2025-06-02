"""
Utilities for chunking document text into semantic chunks that align with the RDS schema.
"""
import logging
import re
import json
import uuid
from typing import Dict, Any, List

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def _basic_strip_markdown_for_search(md_text: str) -> str:
    """
    Strips common markdown syntax from a text segment to prepare it for searching
    in a plain text document.
    """
    # Skip processing if input is empty
    if not md_text or not md_text.strip():
        return ""
    
    # 1. Remove images entirely (often causes issues in OCR documents)
    text = re.sub(r'!\[.*?\]\(.*?\)', '', md_text)
    
    # 2. Remove headings (e.g. ### Title -> Title)
    text = re.sub(r'^\s*#{1,6}\s+', '', text, flags=re.MULTILINE)
    
    # 3. Handle regular links: [link text](url) -> link text
    text = re.sub(r'\[(.*?)\]\((.*?)\)', r'\1', text)
    
    # 4. Bold/italic formatting: **bold** -> bold, *italic* -> italic
    text = re.sub(r'(\*\*|__)(?=\S)(.+?)(?<=\S)\1', r'\2', text)
    text = re.sub(r'(\*|_)(?=\S)(.+?)(?<=\S)\1', r'\2', text)

    # 5. Horizontal rules (---, ***, ___) - remove the line
    text = re.sub(r'^\s*([-*_]){3,}\s*$', '', text, flags=re.MULTILINE)

    # 6. Fenced code blocks: ```lang\ncode\n``` -> code (keeps content)
    text = re.sub(r'^\s*```[^\n]*\n(.*?)\n\s*```\s*$', r'\1', text, flags=re.DOTALL | re.MULTILINE)
    
    # 7. Table formatting - transform to plain text
    # First replace table formatting lines like |---|---|
    text = re.sub(r'\|\s*:?-+:?\s*\|', '', text)
    # Then replace pipe characters with spaces to keep content
    text = re.sub(r'\|', ' ', text)
    
    # 8. LaTeX math formatting
    text = re.sub(r'\$\\(.*?)\\$', r'\1', text)
    text = re.sub(r'\$(.*?)\$', r'\1', text)

    # 9. Normalize whitespace
    # Normalize multiple newlines (3+ newlines become 2, like a paragraph break)
    text = re.sub(r'\n{3,}', '\n\n', text)
    # Normalize multiple spaces
    text = re.sub(r' {2,}', ' ', text)
    
    # 10. Final pass: strip whitespace from each line and remove empty lines.
    lines = text.split('\n')
    cleaned_lines = [line.strip() for line in lines if line.strip()] # Keep only non-empty stripped lines
            
    result_text = '\n'.join(cleaned_lines)
    
    # Return stripped text, ensuring it's not None
    return result_text.strip() if result_text else ""

def chunk_markdown_text(markdown_guide: str, raw_text_to_chunk: str) -> List[Dict[str, Any]]:
    """
    Split raw text into semantic chunks based on the structure of a markdown guide.
    
    Args:
        markdown_guide: The markdown text to use as a structural guide.
        raw_text_to_chunk: The raw text to split into chunks.
        
    Returns:
        List of dicts, each containing:
            - text: The chunk text (from raw_text_to_chunk)
            - char_start_index: Starting character index in raw_text_to_chunk
            - char_end_index: Ending character index in raw_text_to_chunk
            - metadata: Additional metadata about the chunk (e.g., heading level from markdown_guide)
    """
    logger.info("Starting chunking of raw text using markdown guide.")
    
    heading_pattern = r'^(#{1,6})\s+(.+)$'
    lines_md = markdown_guide.split('\n')
    
    proto_chunks = []
    current_chunk_lines_md = []
    current_chunk_start_md = 0
    current_heading_level = 0
    current_heading_text = ""
    
    # Phase 1: Parse markdown_guide to identify semantic segments
    logger.debug("Phase 1: Parsing markdown guide for semantic structure.")
    for i, line_md in enumerate(lines_md):
        line_start_char_in_md_guide = len('\n'.join(lines_md[:i]))
        if i > 0:
            line_start_char_in_md_guide += 1  # Account for the newline character
            
        heading_match_md = re.match(heading_pattern, line_md)
        is_heading_md = heading_match_md is not None
        is_paragraph_break_md = line_md.strip() == '' and i > 0 and lines_md[i-1].strip() == ''
        
        if is_heading_md or is_paragraph_break_md:
            if current_chunk_lines_md:
                segment_text_md = '\n'.join(current_chunk_lines_md)
                # End index is start of current line_start_char_in_md_guide, minus 1 for newline if applicable
                segment_end_md = line_start_char_in_md_guide
                if segment_end_md > 0 and markdown_guide[segment_end_md-1] == '\n':
                    segment_end_md -=1

                proto_chunks.append({
                    'markdown_segment_text': segment_text_md,
                    'original_md_char_start': current_chunk_start_md,
                    'original_md_char_end': segment_end_md,
                    'metadata': {
                        'heading_level': current_heading_level,
                        'heading_text': current_heading_text
                    }
                })
            
            current_chunk_lines_md = []
            current_chunk_start_md = line_start_char_in_md_guide
            
            if is_heading_md:
                current_heading_level = len(heading_match_md.group(1))
                current_heading_text = heading_match_md.group(2).strip()
        
        current_chunk_lines_md.append(line_md)
    
    if current_chunk_lines_md:
        segment_text_md = '\n'.join(current_chunk_lines_md)
        proto_chunks.append({
            'markdown_segment_text': segment_text_md,
            'original_md_char_start': current_chunk_start_md,
            'original_md_char_end': len(markdown_guide),
            'metadata': {
                'heading_level': current_heading_level,
                'heading_text': current_heading_text
            }
        })
    logger.debug(f"Identified {len(proto_chunks)} proto-chunks from markdown guide.")

    # Phase 2: Map proto_chunks to raw_text_to_chunk
    logger.debug("Phase 2: Mapping proto-chunks to raw text.")
    final_chunks = []
    current_search_offset_raw = 0
    
    for i, proto_chunk in enumerate(proto_chunks):
        md_segment = proto_chunk['markdown_segment_text']
        metadata = proto_chunk['metadata']
        
        searchable_text = _basic_strip_markdown_for_search(md_segment)
        
        if not searchable_text: # If segment is empty after cleaning
            logger.debug(f"Proto-chunk {i} (md_start={proto_chunk['original_md_char_start']}) is empty after stripping, skipping.")
            continue

        try:
            start_index_raw = raw_text_to_chunk.find(searchable_text, current_search_offset_raw)
            
            if start_index_raw != -1:
                end_index_raw = start_index_raw + len(searchable_text)
                chunk_text_raw = raw_text_to_chunk[start_index_raw:end_index_raw]
                
                final_chunks.append({
                    'text': chunk_text_raw,
                    'char_start_index': start_index_raw,
                    'char_end_index': end_index_raw,
                    'metadata': metadata
                })
                current_search_offset_raw = end_index_raw
                logger.debug(f"Proto-chunk {i} found in raw text at [{start_index_raw}:{end_index_raw}]. Advancing search offset to {current_search_offset_raw}.")
            else:
                logger.warning(
                    f"Proto-chunk {i} (md_start={proto_chunk['original_md_char_start']}) NOT FOUND in raw text. "
                    f"Search started at offset {current_search_offset_raw}. "
                    f"Cleaned search text (first 100 chars): '{searchable_text[:100]}...'"
                )
                # Optional: Implement a more sophisticated strategy for advancing current_search_offset_raw
                # For now, it remains, and the next search will start from the same position.
                # This might be an issue if a large chunk is missed and subsequent smaller chunks are contained within it.
                # A possible improvement: if not found, try finding the *next* proto_chunk's text.

        except Exception as e:
            logger.error(
                f"Error processing proto-chunk {i} (md_start={proto_chunk['original_md_char_start']}): {e}. "
                f"Cleaned search text (first 100 chars): '{searchable_text[:100]}...'"
            )

    logger.info(f"Created {len(final_chunks)} chunks from raw text using markdown guide.")
    return final_chunks

def refine_chunks(chunks: List[Dict[str, Any]], min_chunk_size: int = 100) -> List[Dict[str, Any]]:
    """
    Refine the initial chunks to ensure they meet minimum size requirements.
    
    Args:
        chunks: List of chunk dictionaries (text and indices refer to raw_text_to_chunk)
        min_chunk_size: Minimum character count for a chunk
        
    Returns:
        List of refined chunk dictionaries
    """
    logger.info(f"Refining chunks with minimum size of {min_chunk_size} characters.")
    
    refined_chunks = []
    current_combined_chunk = None # Stores a chunk being built up by combining small ones
    
    for i, chunk in enumerate(chunks):
        # If current_combined_chunk is None, this is the first chunk or follows a large enough chunk
        if current_combined_chunk is None:
            if len(chunk['text']) < min_chunk_size:
                current_combined_chunk = chunk.copy() # Start a new combined chunk
                current_combined_chunk['metadata']['is_combined'] = False # Initial state
                current_combined_chunk['metadata']['combined_headings'] = [{
                    'heading_level': chunk['metadata'].get('heading_level', 0),
                    'heading_text': chunk['metadata'].get('heading_text', '')
                }]
            else:
                refined_chunks.append(chunk) # Chunk is large enough, add as is
        else:
            # We have a current_combined_chunk we are trying to build
            # Try to merge the current chunk into current_combined_chunk
            # Check if text lengths are an issue before concatenation
            if not chunk['text'].strip() and not current_combined_chunk['text'].strip():
                # Both are effectively empty or whitespace, avoid double newlines if not meaningful
                separator = "" if not chunk['text'] else "\n" # Minimal separator if chunk has some whitespace
            elif not chunk['text'].strip(): # Current chunk is empty/whitespace
                separator = ""
            elif not current_combined_chunk['text'].strip(): # Combined chunk is empty/whitespace
                 separator = ""
            else: # Both have content
                separator = "\n\n"

            potential_new_text = current_combined_chunk['text'] + separator + chunk['text']
            
            # Merge current chunk into current_combined_chunk
            current_combined_chunk['text'] = potential_new_text
            current_combined_chunk['char_end_index'] = chunk['char_end_index'] # Extends to the end of the merged chunk
            current_combined_chunk['metadata']['is_combined'] = True
            
            # Add heading info of the merged chunk
            current_combined_chunk['metadata']['combined_headings'].append({
                'heading_level': chunk['metadata'].get('heading_level', 0),
                'heading_text': chunk['metadata'].get('heading_text', '')
            })

            # If the combined chunk is now large enough, add it and reset
            if len(current_combined_chunk['text']) >= min_chunk_size:
                refined_chunks.append(current_combined_chunk)
                current_combined_chunk = None
            # If it's the last chunk and still too small, it will be handled after the loop
    
    # Add any remaining combined chunk if it exists (e.g., if the loop ended while building it)
    if current_combined_chunk is not None:
        refined_chunks.append(current_combined_chunk)
    
    logger.info(f"Refined to {len(refined_chunks)} chunks after size adjustment.")
    return refined_chunks

def prepare_chunks_for_database(
    chunks: List[Dict[str, Any]], 
    document_id: int,
    document_uuid: str
) -> List[Dict[str, Any]]:
    """
    Transform chunk data to match the Supabase schema structure.
    
    Args:
        chunks: List of chunks from chunk_markdown_text or refine_chunks
        document_id: ID of the neo4j_document in the database
        document_uuid: UUID of the document (documentId)
        
    Returns:
        List of chunk objects ready for database insertion
    """
    logger.info(f"Preparing {len(chunks)} chunks for database insertion.")
    
    prepared_chunks = []
    
    for i, chunk in enumerate(chunks):
        # Generate UUID for the chunk
        chunk_uuid = str(uuid.uuid4())
        
        # Convert metadata to JSON string
        metadata_json = json.dumps(chunk['metadata'])
        
        # Create the chunk object with keys matching the database schema
        db_chunk = {
            'chunkId': chunk_uuid,  # Match field name in schema
            'document_id': document_id,  # Reference to parent document SQL ID
            'document_uuid': document_uuid,  # Reference to parent document UUID
            'chunkIndex': i,  # Sequential index starting from 0
            'text': chunk['text'],  # Original text
            'cleanedText': chunk['text'],  # Same as text initially, can be cleaned later
            'processingStatus': 'pending_ner',  # Default status
            'char_start_index': chunk['char_start_index'],
            'char_end_index': chunk['char_end_index'],
            'metadata_json': metadata_json,  # Store metadata as JSON string
            'createdAt': 'CURRENT_TIMESTAMP',  # Will be replaced by DB default
            'updatedAt': 'CURRENT_TIMESTAMP'   # Will be replaced by DB default
        }
        
        prepared_chunks.append(db_chunk)
    
    logger.info(f"Prepared {len(prepared_chunks)} chunks for database insertion.")
    return prepared_chunks

def simple_chunk_text(text: str, chunk_size: int = 1000, overlap: int = 200) -> List[Dict[str, Any]]:
    """
    Simple fallback chunking strategy that splits text into fixed-size chunks with overlap.
    
    Args:
        text: Text to chunk
        chunk_size: Target size for each chunk
        overlap: Number of characters to overlap between chunks
        
    Returns:
        List of chunk dictionaries
    """
    logger.info(f"Using simple chunking fallback with chunk_size={chunk_size}, overlap={overlap}")
    
    chunks = []
    start = 0
    text_length = len(text)
    
    while start < text_length:
        # Calculate end position
        end = min(start + chunk_size, text_length)
        
        # Extract chunk text
        chunk_text = text[start:end]
        
        # Create chunk dictionary
        chunks.append({
            'text': chunk_text,
            'char_start_index': start,
            'char_end_index': end,
            'metadata': {
                'heading_level': 0,
                'heading_text': 'Simple Chunk',
                'chunk_method': 'simple_fallback'
            }
        })
        
        # Move to next chunk with overlap
        start = end - overlap if end < text_length else text_length
        
        # Prevent infinite loop
        if start >= text_length - 1:
            break
    
    logger.info(f"Created {len(chunks)} chunks using simple fallback method")
    return chunks

def process_and_insert_chunks(
    db_manager,  # SupabaseManager instance
    markdown_guide: str,
    raw_text: str,
    document_id: int,
    document_uuid: str,
    min_chunk_size: int = 100,
    use_idempotent_ops: bool = True
) -> List[Dict[str, Any]]:
    """
    Process a document's text into chunks and insert them into the database.
    
    Args:
        db_manager: Instance of SupabaseManager for database operations
        markdown_guide: Markdown text to use as structural guide
        raw_text: Raw text to chunk
        document_id: SQL ID of the document in neo4j_documents
        document_uuid: UUID of the document (documentId field)
        min_chunk_size: Minimum size for chunks after refinement
        use_idempotent_ops: Whether to use idempotent operations for upsert behavior
    
    Returns:
        List of chunk database objects that were inserted
    """
    logger.info(f"Processing document {document_uuid} into chunks and inserting into database.")
    
    # 1. Generate initial chunks based on markdown structure
    initial_chunks = chunk_markdown_text(markdown_guide, raw_text)
    
    # 1.5 If markdown chunking failed (no chunks), use simple fallback
    if not initial_chunks:
        logger.warning(f"Markdown-based chunking produced 0 chunks for document {document_uuid}, using simple fallback")
        initial_chunks = simple_chunk_text(raw_text, chunk_size=1000, overlap=200)
    
    # 2. Refine chunks to ensure minimum size
    refined_chunks = refine_chunks(initial_chunks, min_chunk_size)
    
    # 3. Prepare chunks for database insertion
    db_chunks = prepare_chunks_for_database(refined_chunks, document_id, document_uuid)
    
    # 4. Insert chunks into database
    inserted_chunks = []
    
    # Import IdempotentDatabaseOps if needed
    if use_idempotent_ops:
        try:
            from scripts.celery_tasks.idempotent_ops import IdempotentDatabaseOps
            idempotent_ops = IdempotentDatabaseOps(db_manager)
        except ImportError:
            logger.warning("Could not import IdempotentDatabaseOps, falling back to regular operations")
            use_idempotent_ops = False
    
    for chunk in db_chunks:
        try:
            if use_idempotent_ops:
                # Use idempotent upsert operation
                chunk_sql_id, chunk_uuid = idempotent_ops.upsert_chunk(
                    document_id=document_id,
                    document_uuid=document_uuid,
                    chunk_index=chunk['chunkIndex'],
                    chunk_text=chunk['text'],
                    chunk_metadata={
                        'cleaned_text': chunk['cleanedText'],
                        'char_start_index': chunk['char_start_index'],
                        'char_end_index': chunk['char_end_index'],
                        **json.loads(chunk['metadata_json'])
                    }
                )
            else:
                # Use regular create operation
                chunk_sql_id, chunk_uuid = db_manager.create_chunk_entry(
                    document_fk_id=document_id,
                    document_uuid=document_uuid,
                    chunk_index=chunk['chunkIndex'],
                    text_content=chunk['text'],
                    cleaned_text=chunk['cleanedText'],
                    char_start_index=chunk['char_start_index'],
                    char_end_index=chunk['char_end_index'],
                    metadata_json=chunk['metadata_json']
                )
            
            if chunk_sql_id and chunk_uuid:
                logger.info(f"{'Upserted' if use_idempotent_ops else 'Inserted'} chunk {chunk['chunkIndex']} (SQL ID: {chunk_sql_id}, UUID: {chunk_uuid})")
                chunk['sql_id'] = chunk_sql_id
                chunk['chunk_uuid'] = chunk_uuid
                inserted_chunks.append(chunk)
            else:
                logger.error(f"Failed to insert chunk {chunk['chunkIndex']}")
        except Exception as e:
            logger.error(f"Error inserting chunk {chunk['chunkIndex']}: {e}")
    
    logger.info(f"{'Upserted' if use_idempotent_ops else 'Inserted'} {len(inserted_chunks)} chunks for document {document_uuid}")
    return inserted_chunks

def generate_simple_markdown(text: str) -> str:
    """
    Generate simplified markdown structure from text for chunking guidance
    
    Args:
        text: The text to convert to markdown
        
    Returns:
        Markdown-formatted text
    """
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
    
    return "\n\n".join(markdown_lines)

def validate_chunks(chunks: List[Dict[str, Any]], original_text: str) -> Dict[str, Any]:
    """
    Validate chunk quality and coverage
    
    Args:
        chunks: List of chunk dictionaries with at least 'text' field
        original_text: The original text that was chunked
        
    Returns:
        Dictionary containing validation metrics
    """
    from collections import Counter
    
    if not chunks:
        return {
            'total_chunks': 0,
            'avg_chunk_size': 0,
            'min_chunk_size': 0,
            'max_chunk_size': 0,
            'coverage': 0.0,
            'empty_chunks': 0,
            'chunk_types': {},
            'validation_errors': ['No chunks provided'],
            'quality_issues': ['No chunks to validate']
        }
    
    # Calculate basic metrics
    chunk_sizes = [len(chunk.get('text', '')) for chunk in chunks]
    total_chunk_chars = sum(chunk_sizes)
    
    # Count chunk types
    chunk_types = Counter(
        chunk.get('metadata', {}).get('type', 'unknown') 
        for chunk in chunks
    )
    
    # Find empty or very short chunks
    empty_chunks = sum(1 for size in chunk_sizes if size == 0)
    very_short_chunks = sum(1 for size in chunk_sizes if 0 < size < 50)
    
    # Check for chunks that end mid-sentence
    incomplete_chunks = 0
    for chunk in chunks:
        text = chunk.get('text', '').strip()
        if text and not text.endswith(('.', '!', '?', ':', ';', '"', "'")):
            # Check if it's not a heading or list item
            if not (text.isupper() or re.match(r'^\d+\.?\s', text)):
                incomplete_chunks += 1
    
    # Calculate coverage
    coverage = total_chunk_chars / len(original_text) if original_text else 0.0
    
    # Check for overlapping chunks
    overlapping_chunks = 0
    for i in range(len(chunks) - 1):
        curr_end = chunks[i].get('char_end_index', 0)
        next_start = chunks[i + 1].get('char_start_index', 0)
        if curr_end > next_start:
            overlapping_chunks += 1
    
    # Identify quality issues
    quality_issues = []
    validation_errors = []
    
    if empty_chunks > 0:
        quality_issues.append(f"{empty_chunks} empty chunks found")
    
    if very_short_chunks > 0:
        quality_issues.append(f"{very_short_chunks} very short chunks (<50 chars)")
    
    if incomplete_chunks > len(chunks) * 0.2:  # More than 20% incomplete
        quality_issues.append(f"{incomplete_chunks} chunks may end mid-sentence")
    
    if coverage < 0.95:
        quality_issues.append(f"Low coverage: {coverage:.1%} of original text")
    elif coverage > 1.05:
        quality_issues.append(f"Excessive coverage: {coverage:.1%} (possible duplication)")
    
    if overlapping_chunks > 0:
        validation_errors.append(f"{overlapping_chunks} overlapping chunks detected")
    
    # Check chunk size distribution
    if chunk_sizes:
        avg_size = sum(chunk_sizes) / len(chunk_sizes)
        std_dev = (sum((x - avg_size) ** 2 for x in chunk_sizes) / len(chunk_sizes)) ** 0.5
        
        if std_dev > avg_size * 0.5:  # High variation
            quality_issues.append("High variation in chunk sizes")
    
    return {
        'total_chunks': len(chunks),
        'avg_chunk_size': sum(chunk_sizes) / len(chunk_sizes) if chunks else 0,
        'min_chunk_size': min(chunk_sizes) if chunk_sizes else 0,
        'max_chunk_size': max(chunk_sizes) if chunk_sizes else 0,
        'coverage': coverage,
        'empty_chunks': empty_chunks,
        'very_short_chunks': very_short_chunks,
        'incomplete_chunks': incomplete_chunks,
        'overlapping_chunks': overlapping_chunks,
        'chunk_types': dict(chunk_types),
        'validation_errors': validation_errors,
        'quality_issues': quality_issues,
        'quality_score': calculate_chunk_quality_score(
            chunks, coverage, empty_chunks, incomplete_chunks
        )
    }

def calculate_chunk_quality_score(
    chunks: List[Dict[str, Any]], 
    coverage: float, 
    empty_chunks: int,
    incomplete_chunks: int
) -> float:
    """
    Calculate a quality score for the chunking result
    
    Returns:
        Float between 0 and 1 representing chunk quality
    """
    if not chunks:
        return 0.0
    
    score = 1.0
    
    # Penalize for poor coverage
    if coverage < 0.95:
        score *= coverage
    elif coverage > 1.05:
        score *= (2.0 - coverage)  # Penalize over-coverage
    
    # Penalize for empty chunks
    if empty_chunks > 0:
        score *= (1.0 - empty_chunks / len(chunks))
    
    # Penalize for incomplete chunks
    if incomplete_chunks > 0:
        score *= (1.0 - 0.5 * incomplete_chunks / len(chunks))
    
    # Ensure score is between 0 and 1
    return max(0.0, min(1.0, score))