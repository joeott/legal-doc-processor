#!/usr/bin/env python3
"""Test PDF to image conversion with Textract for scanned documents."""

import os
import sys
import boto3
import tempfile
from pdf2image import convert_from_path
from PIL import Image
import io

# Load environment
if os.path.exists('.env'):
    from dotenv import load_dotenv
    load_dotenv()

# Test parameters
TEST_S3_BUCKET = "samu-docs-private-upload"
TEST_S3_KEY = "documents/1d9e1752-942c-4505-a1f9-3ee28f52a2a1/IMG_0791.pdf"
S3_BUCKET_REGION = os.getenv('S3_BUCKET_REGION', 'us-east-2')

def test_pdf_to_image_textract():
    """Test converting PDF to images and then using Textract."""
    print(f"Testing PDF to image conversion for s3://{TEST_S3_BUCKET}/{TEST_S3_KEY}")
    
    try:
        # 1. Download PDF from S3
        print("\n1. Downloading PDF from S3...")
        s3 = boto3.client('s3', region_name=S3_BUCKET_REGION)
        
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_file:
            s3.download_file(TEST_S3_BUCKET, TEST_S3_KEY, tmp_file.name)
            pdf_path = tmp_file.name
            print(f"   Downloaded to: {pdf_path}")
        
        # 2. Convert PDF to images
        print("\n2. Converting PDF to images...")
        images = convert_from_path(pdf_path, dpi=300)  # Higher DPI for better OCR
        print(f"   Converted to {len(images)} images")
        
        # 3. Process each image with Textract
        textract = boto3.client('textract', region_name=S3_BUCKET_REGION)
        all_text = []
        
        for i, image in enumerate(images):
            print(f"\n3. Processing page {i+1} with Textract...")
            
            # Convert PIL image to bytes
            img_byte_arr = io.BytesIO()
            image.save(img_byte_arr, format='PNG')
            img_byte_arr = img_byte_arr.getvalue()
            
            # Call Textract
            response = textract.detect_document_text(
                Document={'Bytes': img_byte_arr}
            )
            
            # Extract text
            blocks = response.get('Blocks', [])
            print(f"   - Got {len(blocks)} blocks")
            
            # Count block types
            block_types = {}
            for block in blocks:
                block_type = block.get('BlockType', 'UNKNOWN')
                block_types[block_type] = block_types.get(block_type, 0) + 1
            
            print(f"   - Block types: {block_types}")
            
            # Extract text from LINE blocks
            page_lines = []
            line_blocks = [b for b in blocks if b.get('BlockType') == 'LINE']
            
            if line_blocks:
                print(f"   - Found {len(line_blocks)} lines of text")
                for block in line_blocks:
                    text = block.get('Text', '')
                    if text:
                        page_lines.append(text)
                
                # Show first few lines
                print(f"   - First 5 lines:")
                for j, line in enumerate(page_lines[:5]):
                    print(f"     {j+1}: {line}")
            
            page_text = '\n'.join(page_lines)
            all_text.append(f"=== Page {i+1} ===\n{page_text}")
        
        # 4. Combine all text
        full_text = '\n\n'.join(all_text)
        print(f"\n4. Total extracted text: {len(full_text)} characters")
        
        # Clean up
        os.unlink(pdf_path)
        
        return full_text
        
    except Exception as e:
        print(f"\nERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return None

if __name__ == "__main__":
    print("=== PDF to Image Textract Test ===")
    text = test_pdf_to_image_textract()
    
    if text:
        print("\n=== EXTRACTED TEXT PREVIEW ===")
        print(text[:500] + "..." if len(text) > 500 else text)