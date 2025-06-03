#!/usr/bin/env python3
"""Simple fallback chunking for when markdown-based chunking fails"""

def simple_chunk_text(text: str, max_chunk_size: int = 1000, overlap: int = 100):
    """
    Simple chunking that splits text into fixed-size chunks with overlap.
    Used as fallback when semantic chunking fails.
    
    Args:
        text: Text to chunk
        max_chunk_size: Maximum size of each chunk
        overlap: Number of characters to overlap between chunks
        
    Returns:
        List of chunk dictionaries
    """
    if not text or not text.strip():
        return []
    
    chunks = []
    text_length = len(text)
    
    # If text is smaller than max chunk size, return as single chunk
    if text_length <= max_chunk_size:
        chunks.append({
            'text': text,
            'char_start_index': 0,
            'char_end_index': text_length,
            'metadata': {
                'heading_level': 0,
                'heading_text': '',
                'is_fallback': True
            }
        })
        return chunks
    
    # Split into chunks with overlap
    start = 0
    while start < text_length:
        # Calculate end position
        end = min(start + max_chunk_size, text_length)
        
        # Try to find a good break point (paragraph or sentence end)
        if end < text_length:
            # Look for paragraph break
            para_break = text.rfind('\n\n', start, end)
            if para_break > start + (max_chunk_size // 2):
                end = para_break
            else:
                # Look for sentence end
                for punct in ['. ', '.\n', '! ', '!\n', '? ', '?\n']:
                    sent_end = text.rfind(punct, start, end)
                    if sent_end > start + (max_chunk_size // 2):
                        end = sent_end + 1
                        break
        
        # Create chunk
        chunk_text = text[start:end].strip()
        if chunk_text:  # Only add non-empty chunks
            chunks.append({
                'text': chunk_text,
                'char_start_index': start,
                'char_end_index': end,
                'metadata': {
                    'heading_level': 0,
                    'heading_text': '',
                    'is_fallback': True,
                    'chunk_method': 'simple_fixed_size'
                }
            })
        
        # Move to next chunk with overlap
        if end >= text_length:
            break
        start = end - overlap if end > overlap else end
    
    return chunks