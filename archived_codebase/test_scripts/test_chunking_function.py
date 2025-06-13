#!/usr/bin/env python3
"""Test the simple_chunk_text function to see if it's working correctly"""

import sys
sys.path.append('/opt/legal-doc-processor')

from scripts.chunking_utils import simple_chunk_text

# Test with a text of 3278 characters (similar to the OCR output)
test_text = "a" * 3278

print(f"Testing simple_chunk_text with {len(test_text)} characters")
print(f"Parameters: chunk_size=1000, overlap=200")
print("-" * 80)

# Call the function
chunks = simple_chunk_text(test_text, chunk_size=1000, overlap=200)

print(f"\nGenerated {len(chunks)} chunks:")
for i, chunk in enumerate(chunks):
    print(f"\nChunk {i}:")
    print(f"  - Text length: {len(chunk['text'])}")
    print(f"  - Start index: {chunk['char_start_index']}")
    print(f"  - End index: {chunk['char_end_index']}")
    print(f"  - First 50 chars: {chunk['text'][:50]}...")
    print(f"  - Last 50 chars: ...{chunk['text'][-50:]}")

# Verify coverage
total_coverage = sum(len(chunk['text']) for chunk in chunks)
print(f"\nTotal characters in chunks: {total_coverage}")
print(f"Original text length: {len(test_text)}")

# Check for overlaps
print("\nOverlap verification:")
for i in range(len(chunks) - 1):
    overlap_start = chunks[i+1]['char_start_index']
    overlap_end = chunks[i]['char_end_index']
    overlap_size = overlap_end - overlap_start
    print(f"  - Between chunk {i} and {i+1}: {overlap_size} chars")