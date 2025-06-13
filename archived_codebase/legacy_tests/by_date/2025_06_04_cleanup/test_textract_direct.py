#!/usr/bin/env python3
"""Test Textract directly to diagnose empty text issue."""

import os
import sys
import boto3
from textractor import Textractor
from textractor.data.constants import TextractAPI

# Load environment
if os.path.exists('.env'):
    from dotenv import load_dotenv
    load_dotenv()

# Test parameters
TEST_S3_BUCKET = "samu-docs-private-upload"
TEST_S3_KEY = "documents/1d9e1752-942c-4505-a1f9-3ee28f52a2a1/IMG_0791.pdf"
S3_BUCKET_REGION = os.getenv('S3_BUCKET_REGION', 'us-east-2')

def test_textract_sync():
    """Test Textract synchronously to see what's happening."""
    print(f"Testing Textract on s3://{TEST_S3_BUCKET}/{TEST_S3_KEY}")
    print(f"Using region: {S3_BUCKET_REGION}")
    
    try:
        # Initialize Textractor
        textractor = Textractor(region_name=S3_BUCKET_REGION)
        
        # Try synchronous extraction first
        print("\n1. Testing synchronous extraction...")
        s3_path = f"s3://{TEST_S3_BUCKET}/{TEST_S3_KEY}"
        
        document = textractor.detect_document_text(
            file_source=s3_path,
            save_image=False
        )
        
        # Extract text various ways
        print("\n2. Extracting text...")
        
        # Method 1: Direct text property
        text1 = document.text
        print(f"   - document.text: {len(text1)} chars")
        if text1:
            print(f"     First 100 chars: {text1[:100]}...")
        
        # Method 2: Lines
        lines = list(document.lines)
        text2 = '\n'.join([line.text for line in lines])
        print(f"   - from lines: {len(text2)} chars, {len(lines)} lines")
        if lines:
            print(f"     First line: {lines[0].text}")
        
        # Method 3: Words
        words = list(document.words)
        text3 = ' '.join([word.text for word in words])
        print(f"   - from words: {len(text3)} chars, {len(words)} words")
        if words:
            print(f"     First 5 words: {' '.join([w.text for w in words[:5]])}")
        
        # Method 4: Pages
        pages = list(document.pages)
        print(f"   - Pages: {len(pages)}")
        for i, page in enumerate(pages):
            page_text = page.text
            print(f"     Page {i+1}: {len(page_text)} chars")
            if page_text:
                print(f"     First 100 chars: {page_text[:100]}...")
        
        # Check raw response
        print("\n3. Checking raw response...")
        if hasattr(document, 'response') and document.response:
            blocks = document.response.get('Blocks', [])
            print(f"   - Total blocks: {len(blocks)}")
            
            # Count block types
            block_types = {}
            for block in blocks:
                block_type = block.get('BlockType', 'UNKNOWN')
                block_types[block_type] = block_types.get(block_type, 0) + 1
            
            print("   - Block types:")
            for block_type, count in block_types.items():
                print(f"     {block_type}: {count}")
            
            # Show some LINE blocks
            line_blocks = [b for b in blocks if b.get('BlockType') == 'LINE']
            if line_blocks:
                print(f"\n   - First 3 LINE blocks:")
                for block in line_blocks[:3]:
                    print(f"     Text: '{block.get('Text', 'NO TEXT')}'")
                    print(f"     Confidence: {block.get('Confidence', 0)}")
        
        return document
        
    except Exception as e:
        print(f"\nERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return None

def test_s3_access():
    """Test if we can access the S3 file."""
    print(f"\n4. Testing S3 access...")
    try:
        s3 = boto3.client('s3', region_name=S3_BUCKET_REGION)
        
        # Check if object exists
        response = s3.head_object(Bucket=TEST_S3_BUCKET, Key=TEST_S3_KEY)
        print(f"   - Object exists: {TEST_S3_KEY}")
        print(f"   - Size: {response['ContentLength']:,} bytes")
        print(f"   - Content-Type: {response.get('ContentType', 'unknown')}")
        
        # Try to download first few bytes
        response = s3.get_object(Bucket=TEST_S3_BUCKET, Key=TEST_S3_KEY, Range='bytes=0-1023')
        data = response['Body'].read()
        print(f"   - Can read file: Yes")
        print(f"   - PDF header: {data[:10]}")  # Should be %PDF-...
        
        return True
        
    except Exception as e:
        print(f"   - ERROR accessing S3: {e}")
        return False

if __name__ == "__main__":
    print("=== Textract Direct Test ===")
    print(f"AWS_DEFAULT_REGION: {os.getenv('AWS_DEFAULT_REGION', 'not set')}")
    print(f"S3_BUCKET_REGION: {S3_BUCKET_REGION}")
    
    # Test S3 access first
    if test_s3_access():
        # Test Textract
        test_textract_sync()
    else:
        print("\nCannot proceed without S3 access")