#!/usr/bin/env python3
"""Test Textract with analyze_document for scanned PDFs."""

import os
import sys
import boto3
from textractor import Textractor
from textractor.data.constants import TextractAPI, TextractFeatures

# Load environment
if os.path.exists('.env'):
    from dotenv import load_dotenv
    load_dotenv()

# Test parameters
TEST_S3_BUCKET = "samu-docs-private-upload"
TEST_S3_KEY = "documents/1d9e1752-942c-4505-a1f9-3ee28f52a2a1/IMG_0791.pdf"
S3_BUCKET_REGION = os.getenv('S3_BUCKET_REGION', 'us-east-2')

def test_textract_analyze():
    """Test Textract with analyze_document for better OCR."""
    print(f"Testing Textract analyze_document on s3://{TEST_S3_BUCKET}/{TEST_S3_KEY}")
    print(f"Using region: {S3_BUCKET_REGION}")
    
    try:
        # Initialize Textractor
        textractor = Textractor(region_name=S3_BUCKET_REGION)
        
        # Try analyze_document with TEXT feature
        print("\n1. Testing analyze_document...")
        s3_path = f"s3://{TEST_S3_BUCKET}/{TEST_S3_KEY}"
        
        # Method 1: analyze_document
        document = textractor.analyze_document(
            file_source=s3_path,
            features=[TextractFeatures.LAYOUT],  # LAYOUT includes text extraction
            save_image=False
        )
        
        # Extract text various ways
        print("\n2. Extracting text from analyze_document...")
        
        # Method 1: Direct text property
        text1 = document.text
        print(f"   - document.text: {len(text1)} chars")
        if text1:
            print(f"     First 200 chars: {text1[:200]}...")
        
        # Method 2: Lines
        lines = list(document.lines)
        text2 = '\n'.join([line.text for line in lines])
        print(f"   - from lines: {len(text2)} chars, {len(lines)} lines")
        if lines and len(lines) > 0:
            for i, line in enumerate(lines[:5]):
                print(f"     Line {i+1}: {line.text}")
        
        # Check raw response
        print("\n3. Checking raw response...")
        if hasattr(document, 'response'):
            if isinstance(document.response, dict):
                blocks = document.response.get('Blocks', [])
            elif isinstance(document.response, list) and len(document.response) > 0:
                blocks = document.response[0].get('Blocks', [])
            else:
                blocks = []
                
            print(f"   - Total blocks: {len(blocks)}")
            
            # Count block types
            block_types = {}
            for block in blocks:
                block_type = block.get('BlockType', 'UNKNOWN')
                block_types[block_type] = block_types.get(block_type, 0) + 1
            
            print("   - Block types:")
            for block_type, count in block_types.items():
                print(f"     {block_type}: {count}")
        
        # Try direct boto3 client
        print("\n4. Testing direct boto3 client...")
        client = boto3.client('textract', region_name=S3_BUCKET_REGION)
        
        # First, try detect_document_text
        response = client.detect_document_text(
            Document={'S3Object': {'Bucket': TEST_S3_BUCKET, 'Name': TEST_S3_KEY}}
        )
        
        blocks = response.get('Blocks', [])
        print(f"   - detect_document_text blocks: {len(blocks)}")
        
        # Extract text from LINE blocks
        line_blocks = [b for b in blocks if b.get('BlockType') == 'LINE']
        if line_blocks:
            print(f"   - Found {len(line_blocks)} LINE blocks")
            for i, block in enumerate(line_blocks[:5]):
                print(f"     Line {i+1}: '{block.get('Text', '')}'")
        else:
            print("   - No LINE blocks found - trying analyze_document")
            
            # Try analyze_document
            response = client.analyze_document(
                Document={'S3Object': {'Bucket': TEST_S3_BUCKET, 'Name': TEST_S3_KEY}},
                FeatureTypes=['TABLES', 'FORMS']  # These often help with OCR
            )
            
            blocks = response.get('Blocks', [])
            print(f"   - analyze_document blocks: {len(blocks)}")
            
            line_blocks = [b for b in blocks if b.get('BlockType') == 'LINE']
            if line_blocks:
                print(f"   - Found {len(line_blocks)} LINE blocks")
                for i, block in enumerate(line_blocks[:5]):
                    print(f"     Line {i+1}: '{block.get('Text', '')}'")
        
        return document
        
    except Exception as e:
        print(f"\nERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return None

if __name__ == "__main__":
    print("=== Textract Analyze Document Test ===")
    test_textract_analyze()