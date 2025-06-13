"""
Plain text semantic chunking for legal documents.
Designed to work with Textract's plain text output without markdown conversion.
"""
import re
import logging
from typing import List, Dict, Any, Tuple
import uuid

logger = logging.getLogger(__name__)


def detect_legal_citation(text: str) -> bool:
    """
    Detect if text contains a legal citation that should not be split.
    
    Examples:
    - Smith v. Jones, 123 F.3d 456 (9th Cir. 2023)
    - 42 U.S.C. § 1983
    - Fed. R. Civ. P. 12(b)(6)
    """
    citation_patterns = [
        r'\d+\s+[A-Z][a-z]+\.?\s*\d+d?\s+\d+',  # 123 F.3d 456
        r'\d+\s+U\.S\.C\.\s*§\s*\d+',  # 42 U.S.C. § 1983
        r'Fed\.\s*R\.\s*[A-Z][a-z]+\.\s*P\.\s*\d+',  # Fed. R. Civ. P. 12
        r'[A-Z][a-z]+\s+v\.\s+[A-Z][a-z]+',  # Smith v. Jones
        r'\d+\s+[A-Z]\.\s*Supp\.\s*\d+d?\s+\d+',  # 123 F. Supp. 2d 456
    ]
    
    for pattern in citation_patterns:
        if re.search(pattern, text):
            return True
    return False


def detect_numbered_list_continuation(prev_line: str, curr_line: str) -> bool:
    """
    Detect if current line continues a numbered list from previous line.
    """
    # Check if previous line was a numbered item
    prev_match = re.match(r'^(\d+)\.\s+', prev_line.strip())
    if not prev_match:
        return False
    
    prev_num = int(prev_match.group(1))
    
    # Check if current line is the next number
    curr_match = re.match(r'^(\d+)\.\s+', curr_line.strip())
    if curr_match:
        curr_num = int(curr_match.group(1))
        return curr_num == prev_num + 1
    
    # Check for sub-items
    if re.match(r'^\s+[a-z]\.\s+', curr_line) or re.match(r'^\s+\(\d+\)\s+', curr_line):
        return True
    
    return False


def is_signature_block_line(line: str) -> bool:
    """
    Detect if a line is part of a signature block.
    """
    sig_patterns = [
        r'^_{10,}',  # Signature line
        r'^By:\s*_{5,}',  # By: _____
        r'^Name:\s*',  # Name:
        r'^Title:\s*',  # Title:
        r'^Date:\s*',  # Date:
        r'^WITNESS',  # WITNESS
        r'^NOTARY',  # NOTARY
        r'^Respectfully submitted',  # Legal closing
        r'^Sincerely',  # Letter closing
        r'^\s*/s/',  # Electronic signature
    ]
    
    stripped = line.strip()
    for pattern in sig_patterns:
        if re.match(pattern, stripped, re.IGNORECASE):
            return True
    return False


def chunk_plain_text_semantically(
    text: str,
    min_chunk_size: int = 300,
    max_chunk_size: int = 1500,
    overlap_size: int = 50,
    enhance_metadata: bool = True,
    document_uuid: str = None
) -> List[Dict[str, Any]]:
    """
    Chunk plain text based on semantic boundaries without markdown conversion.
    
    This function is designed to work with Textract output which is plain text
    with pages separated by <END_OF_PAGE> markers.
    
    Args:
        text: Plain text to chunk (from Textract or similar)
        min_chunk_size: Minimum characters per chunk
        max_chunk_size: Maximum characters per chunk
        overlap_size: Characters to overlap between chunks for context
        enhance_metadata: Whether to enhance chunks with rich metadata
        document_uuid: Optional document UUID for unique chunk IDs
        
    Returns:
        List of chunk dictionaries with text, indices, and metadata
    """
    logger.info(f"Starting semantic chunking of {len(text)} characters")
    
    # Pre-process: handle page markers
    text = text.replace('<END_OF_PAGE>', '\n\n[PAGE BREAK]\n\n')
    
    chunks = []
    current_pos = 0
    
    # Define patterns that indicate section boundaries
    section_patterns = [
        # Legal document sections
        (r'^[IVX]+\.\s+[A-Z][A-Z\s]+$', 'roman_section'),  # I. INTRODUCTION
        (r'^\d+\.\s+[A-Z][A-Z\s]+$', 'numbered_section'),  # 1. BACKGROUND
        (r'^[A-Z][A-Z\s]+:$', 'colon_section'),  # PARTIES:
        (r'^[A-Z][A-Z\s]{10,}$', 'caps_heading'),  # MEMORANDUM IN SUPPORT
        (r'^\s*\[PAGE BREAK\]\s*$', 'page_break'),  # Page boundaries
        # Legal subsections
        (r'^[a-z]\.\s+', 'letter_subsection'),  # a. First point
        (r'^\(\d+\)\s+', 'paren_subsection'),  # (1) Sub-point
        (r'^-\s+', 'bullet_point'),  # - List item
        # Contract sections
        (r'^(Section|Article|Clause)\s+\d+(\.\d+)*', 'contract_section'),  # Section 3.1
        (r'^(SECTION|ARTICLE|CLAUSE)\s+\d+(\.\d+)*', 'contract_section_caps'),  # SECTION 3.1
        # Signature blocks
        (r'^(SIGNED|EXECUTED|WITNESS)', 'signature_block'),  # Signature indicators
        (r'^_{10,}', 'signature_line'),  # ______________
        (r'^By:\s*_{5,}', 'signature_by'),  # By: _________
        (r'^(Date|Dated):\s*_{5,}', 'signature_date'),  # Date: _______
    ]
    
    # Split text into lines for analysis
    lines = text.split('\n')
    line_boundaries = []  # (line_index, char_pos, is_section_start, section_type)
    
    # Build line boundary map
    char_pos = 0
    for i, line in enumerate(lines):
        is_section = False
        section_type = None
        
        # Check if line matches any section pattern
        stripped_line = line.strip()
        for pattern, ptype in section_patterns:
            if re.match(pattern, stripped_line):
                is_section = True
                section_type = ptype
                break
        
        # Also check for paragraph boundaries (empty lines)
        if i > 0 and not stripped_line and lines[i-1].strip():
            is_section = True
            section_type = 'paragraph_break'
            
        line_boundaries.append((i, char_pos, is_section, section_type))
        char_pos += len(line) + 1  # +1 for newline
    
    # Build chunks based on semantic boundaries
    current_chunk_start = 0
    current_chunk_lines = []
    current_chunk_type = 'content'
    in_signature_block = False
    in_numbered_list = False
    
    for i, (line_idx, char_pos, is_section, section_type) in enumerate(line_boundaries):
        line = lines[line_idx]
        stripped_line = line.strip()
        
        # Check if we're entering a signature block
        if is_signature_block_line(line):
            in_signature_block = True
        
        # Check if we're in a numbered list
        if line_idx > 0 and detect_numbered_list_continuation(lines[line_idx - 1], line):
            in_numbered_list = True
        elif not re.match(r'^\s*\d+\.', stripped_line) and not re.match(r'^\s+[a-z]\.', stripped_line):
            in_numbered_list = False
        
        # Decide if we should start a new chunk
        should_split = False
        current_size = char_pos - current_chunk_start
        
        # Special handling for signature blocks - always isolate them
        if in_signature_block and not should_split and current_chunk_lines:
            should_split = True
            current_chunk_type = 'signature_block'
        
        # Split if we hit a major section and have enough content
        if is_section and section_type in ['roman_section', 'numbered_section', 
                                          'caps_heading', 'page_break',
                                          'contract_section', 'contract_section_caps']:
            if current_size >= min_chunk_size:
                # Don't split if we're in the middle of a numbered list
                if not in_numbered_list:
                    should_split = True
        
        # Check if current text contains a legal citation that shouldn't be split
        current_text = '\n'.join(current_chunk_lines[-3:] + [line]) if current_chunk_lines else line
        has_citation = detect_legal_citation(current_text)
        
        # Split if we're getting too large
        if current_size >= max_chunk_size:
            # Try to find a good break point
            if is_section or section_type == 'paragraph_break':
                # Don't split if we have an active citation or are in a list
                if not has_citation and not in_numbered_list:
                    should_split = True
            elif i < len(line_boundaries) - 1:
                # Look ahead for a good break within next 200 chars
                for j in range(i + 1, min(i + 10, len(line_boundaries))):
                    future_line_idx, future_char_pos, future_is_section, future_section_type = line_boundaries[j]
                    if future_is_section and (future_char_pos - current_chunk_start) <= max_chunk_size + 200:
                        # Don't split yet if we're in a list or have a citation
                        if not in_numbered_list and not has_citation:
                            break
                else:
                    # No good break found soon, split here unless we're protecting content
                    if not has_citation and not in_numbered_list:
                        should_split = True
        
        if should_split and current_chunk_lines:
            # Create chunk from accumulated lines
            chunk_text = '\n'.join(current_chunk_lines)
            chunk_end = char_pos - 1  # Before current line
            
            # Add overlap from next content if available
            overlap_text = ""
            if i < len(line_boundaries) - 1:
                overlap_lines = []
                overlap_chars = 0
                for j in range(line_idx, min(line_idx + 5, len(lines))):
                    overlap_lines.append(lines[j])
                    overlap_chars += len(lines[j]) + 1
                    if overlap_chars >= overlap_size:
                        break
                overlap_text = '\n'.join(overlap_lines)[:overlap_size]
            
            # Detect special content in chunk
            chunk_has_citations = detect_legal_citation(chunk_text)
            chunk_has_list = any(re.match(r'^\s*\d+\.', l.strip()) for l in current_chunk_lines)
            chunk_is_signature = in_signature_block or any(is_signature_block_line(l) for l in current_chunk_lines)
            
            chunks.append({
                'text': chunk_text,
                'char_start_index': current_chunk_start,
                'char_end_index': chunk_end,
                'metadata': {
                    'chunk_type': current_chunk_type,
                    'starts_with_section': current_chunk_lines[0].strip() if current_chunk_lines else '',
                    'has_overlap': bool(overlap_text),
                    'line_count': len(current_chunk_lines),
                    'has_citations': chunk_has_citations,
                    'has_numbered_list': chunk_has_list,
                    'is_signature_block': chunk_is_signature
                },
                'overlap_text': overlap_text
            })
            
            # Start new chunk
            current_chunk_start = char_pos
            current_chunk_lines = [line]
            current_chunk_type = section_type if is_section else 'content'
            
            # Reset signature block flag if we're starting a new chunk after it
            if in_signature_block and not is_signature_block_line(line):
                in_signature_block = False
        else:
            # Add line to current chunk
            current_chunk_lines.append(line)
    
    # Don't forget the last chunk
    if current_chunk_lines:
        chunk_text = '\n'.join(current_chunk_lines)
        
        # Detect special content in final chunk
        chunk_has_citations = detect_legal_citation(chunk_text)
        chunk_has_list = any(re.match(r'^\s*\d+\.', l.strip()) for l in current_chunk_lines)
        chunk_is_signature = in_signature_block or any(is_signature_block_line(l) for l in current_chunk_lines)
        
        chunks.append({
            'text': chunk_text,
            'char_start_index': current_chunk_start,
            'char_end_index': len(text),
            'metadata': {
                'chunk_type': current_chunk_type,
                'starts_with_section': current_chunk_lines[0].strip() if current_chunk_lines else '',
                'has_overlap': False,
                'line_count': len(current_chunk_lines),
                'has_citations': chunk_has_citations,
                'has_numbered_list': chunk_has_list,
                'is_signature_block': chunk_is_signature
            },
            'overlap_text': ''
        })
    
    # Post-process: ensure minimum sizes by merging small chunks
    final_chunks = []
    i = 0
    while i < len(chunks):
        chunk = chunks[i]
        chunk_size = len(chunk['text'])
        
        # If chunk is too small and not the last one, try to merge with next
        if chunk_size < min_chunk_size and i < len(chunks) - 1:
            next_chunk = chunks[i + 1]
            combined_text = chunk['text'] + '\n' + next_chunk['text']
            
            # Only merge if combined size is reasonable
            if len(combined_text) <= max_chunk_size * 1.5:
                merged_chunk = {
                    'text': combined_text,
                    'char_start_index': chunk['char_start_index'],
                    'char_end_index': next_chunk['char_end_index'],
                    'metadata': {
                        'chunk_type': 'merged',
                        'original_types': [chunk['metadata']['chunk_type'], 
                                         next_chunk['metadata']['chunk_type']],
                        'line_count': chunk['metadata']['line_count'] + next_chunk['metadata']['line_count']
                    }
                }
                final_chunks.append(merged_chunk)
                i += 2  # Skip both chunks
                continue
        
        final_chunks.append(chunk)
        i += 1
    
    logger.info(f"Created {len(final_chunks)} semantic chunks from plain text")
    
    # Add chunk indices
    for i, chunk in enumerate(final_chunks):
        chunk['chunk_index'] = i
        chunk['chunk_uuid'] = str(uuid.uuid4())
    
    # Enhance metadata if requested
    if enhance_metadata:
        logger.info("Enhancing chunk metadata with legal elements and density scores")
        for i, chunk in enumerate(final_chunks):
            enhance_chunk_metadata(chunk, i, len(final_chunks), document_uuid)
    
    return final_chunks


def detect_legal_document_structure(text: str) -> Dict[str, Any]:
    """
    Analyze text to detect legal document structure and patterns.
    
    Returns:
        Dictionary with detected patterns and statistics
    """
    structure = {
        'has_numbered_sections': False,
        'has_roman_sections': False,
        'has_lettered_sections': False,
        'page_count': text.count('<END_OF_PAGE>') + 1,
        'likely_document_type': 'unknown',
        'detected_sections': []
    }
    
    # Check for common legal document patterns
    lines = text.split('\n')
    
    for line in lines[:100]:  # Check first 100 lines
        stripped = line.strip()
        
        # Roman numeral sections
        if re.match(r'^[IVX]+\.\s+', stripped):
            structure['has_roman_sections'] = True
            structure['detected_sections'].append(('roman', stripped))
            
        # Numbered sections
        elif re.match(r'^\d+\.\s+', stripped):
            structure['has_numbered_sections'] = True
            structure['detected_sections'].append(('numbered', stripped))
            
        # Lettered sections
        elif re.match(r'^[a-z]\.\s+', stripped):
            structure['has_lettered_sections'] = True
            
        # Try to detect document type
        stripped_upper = stripped.upper()
        if 'MOTION' in stripped_upper:
            structure['likely_document_type'] = 'motion'
        elif 'COMPLAINT' in stripped_upper:
            structure['likely_document_type'] = 'complaint'
        elif 'MEMORANDUM' in stripped_upper:
            structure['likely_document_type'] = 'memorandum'
        elif 'AFFIDAVIT' in stripped_upper:
            structure['likely_document_type'] = 'affidavit'
        elif 'CONTRACT' in stripped_upper or 'AGREEMENT' in stripped_upper:
            structure['likely_document_type'] = 'contract'
    
    return structure


def enhance_chunk_metadata(chunk: Dict[str, Any], position: int, total: int, document_uuid: str = None) -> Dict[str, Any]:
    """
    Add rich metadata to chunks for better downstream processing.
    
    Args:
        chunk: The chunk dictionary to enhance
        position: Position of chunk in document (0-based)
        total: Total number of chunks in document
        document_uuid: Optional document UUID for unique chunk IDs
        
    Returns:
        Enhanced chunk with additional metadata
    """
    text = chunk['text']
    
    # Positional context
    if position == 0:
        position_context = 'beginning'
    elif position >= total - 1:
        position_context = 'end'
    elif position < total * 0.2:
        position_context = 'early'
    elif position > total * 0.8:
        position_context = 'late'
    else:
        position_context = 'middle'
    
    # Legal element detection
    legal_elements = {
        'citations': [],
        'dates': [],
        'monetary_amounts': [],
        'section_references': [],
        'party_names': []
    }
    
    # Find citations
    citation_patterns = [
        (r'(\d+\s+[A-Z][a-z]+\.?\s*\d+d?\s+\d+(?:\s*\([^)]+\))?)', 'case_reporter'),  # 123 F.3d 456 (9th Cir. 2023)
        (r'(\d+\s+U\.S\.C\.\s*§\s*\d+\w*)', 'statute'),  # 42 U.S.C. § 1983
        (r'(Fed\.\s*R\.\s*[A-Z][a-z]+\.\s*P\.\s*\d+(?:\([a-z]\))?)', 'rule'),  # Fed. R. Civ. P. 12(b)(6)
        (r'([A-Z][a-z]+\s+v\.\s+[A-Z][a-z]+(?:,\s*\d+\s+[A-Z][a-z]+\.?\s*\d+)?)', 'case_name'),  # Smith v. Jones
    ]
    
    for pattern, cite_type in citation_patterns:
        matches = re.findall(pattern, text)
        for match in matches:
            legal_elements['citations'].append({
                'text': match,
                'type': cite_type
            })
    
    # Find dates
    date_patterns = [
        r'\b\d{1,2}/\d{1,2}/\d{2,4}\b',  # 12/31/2023
        r'\b\d{1,2}-\d{1,2}-\d{2,4}\b',  # 12-31-2023
        r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b',  # December 31, 2023
        r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s+\d{1,2},?\s+\d{4}\b',  # Dec. 31, 2023
    ]
    
    for pattern in date_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        legal_elements['dates'].extend(matches)
    
    # Find monetary amounts
    money_patterns = [
        r'\$[\d,]+(?:\.\d{2})?',  # $1,234.56
        r'\b\d+(?:,\d{3})*(?:\.\d{2})?\s*(?:dollars?|USD)\b',  # 1,234.56 dollars
    ]
    
    for pattern in money_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        legal_elements['monetary_amounts'].extend(matches)
    
    # Find section references
    section_patterns = [
        r'(?:Section|Sec\.|§)\s*\d+(?:\.\d+)*',  # Section 3.1
        r'(?:Article|Art\.)\s*\d+',  # Article 5
        r'(?:Paragraph|Para\.)\s*\d+',  # Paragraph 12
        r'(?:Clause)\s*\d+(?:\.\d+)*',  # Clause 2.3
    ]
    
    for pattern in section_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        legal_elements['section_references'].extend(matches)
    
    # Find party names (simplified - looks for Plaintiff/Defendant patterns)
    party_patterns = [
        r'(?:Plaintiff|Defendant|Petitioner|Respondent|Appellant|Appellee),?\s+([A-Z][a-zA-Z\s]+?)(?:,|\s+(?:moves|respectfully|hereby))',
    ]
    
    for pattern in party_patterns:
        matches = re.findall(pattern, text)
        legal_elements['party_names'].extend(matches)
    
    # Calculate density score
    word_count = len(text.split())
    sentence_count = text.count('.') + text.count('!') + text.count('?')
    
    # Information density factors
    density_factors = {
        'citations_per_100_words': len(legal_elements['citations']) * 100 / word_count if word_count > 0 else 0,
        'dates_per_100_words': len(legal_elements['dates']) * 100 / word_count if word_count > 0 else 0,
        'avg_sentence_length': word_count / sentence_count if sentence_count > 0 else word_count,
        'legal_term_density': sum(1 for word in text.split() if word.lower() in 
                                ['whereas', 'therefore', 'hereby', 'pursuant', 'notwithstanding', 
                                 'herein', 'thereof', 'hereunder', 'foregoing']) / word_count if word_count > 0 else 0
    }
    
    # Calculate overall density score (0-1)
    density_score = min(1.0, (
        density_factors['citations_per_100_words'] * 0.3 +
        density_factors['dates_per_100_words'] * 0.1 +
        (1.0 if density_factors['avg_sentence_length'] > 15 else 0.5) * 0.3 +
        density_factors['legal_term_density'] * 0.3
    ))
    
    # Create unique chunk ID
    if document_uuid:
        chunk_id = f"{document_uuid}_chunk_{position:04d}"
    else:
        chunk_id = f"chunk_{position:04d}"
    
    # Update metadata - ensure all values are JSON-serializable
    chunk['metadata'].update({
        'position': position,
        'total_chunks': total,
        'position_context': position_context,
        'legal_elements': {
            'citations': [{'text': c['text'], 'type': c['type']} for c in legal_elements['citations']],
            'dates': list(legal_elements['dates']),
            'monetary_amounts': list(legal_elements['monetary_amounts']),
            'section_references': list(legal_elements['section_references']),
            'party_names': list(legal_elements['party_names'])
        },
        'density_score': round(density_score, 3),
        'density_factors': {
            'citations_per_100_words': round(density_factors['citations_per_100_words'], 3),
            'dates_per_100_words': round(density_factors['dates_per_100_words'], 3),
            'avg_sentence_length': round(density_factors['avg_sentence_length'], 1),
            'legal_term_density': round(density_factors['legal_term_density'], 4)
        },
        'word_count': word_count,
        'sentence_count': sentence_count,
        'chunk_id': chunk_id,
        'enhanced': True
    })
    
    return chunk


if __name__ == "__main__":
    # Test the chunker
    sample_text = """
UNITED STATES DISTRICT COURT
EASTERN DISTRICT OF MISSOURI

JOHN DOE,
    Plaintiff,
v.
JANE ROE,
    Defendant.

MOTION TO DISMISS

I. INTRODUCTION

Defendant Jane Roe respectfully moves this Court to dismiss the complaint.

II. STATEMENT OF FACTS

The facts of this case are as follows:

1. On January 1, 2024, the parties entered into a contract.

2. The contract specified certain obligations.

<END_OF_PAGE>

III. LEGAL STANDARD

A motion to dismiss should be granted when...

IV. ARGUMENT

A. The Complaint Fails to State a Claim

The plaintiff has not adequately alleged...

B. Lack of Jurisdiction

This court lacks jurisdiction because...

V. CONCLUSION

For the foregoing reasons, Defendant respectfully requests that this Court grant the motion to dismiss.
"""
    
    # Test chunking
    chunks = chunk_plain_text_semantically(sample_text, min_chunk_size=100, max_chunk_size=500)
    
    print(f"Created {len(chunks)} chunks:")
    for i, chunk in enumerate(chunks):
        print(f"\nChunk {i + 1}:")
        print(f"  Type: {chunk['metadata']['chunk_type']}")
        print(f"  Size: {len(chunk['text'])} chars")
        print(f"  Text preview: {chunk['text'][:100]}...")
    
    # Test structure detection
    structure = detect_legal_document_structure(sample_text)
    print(f"\nDetected structure: {structure}")