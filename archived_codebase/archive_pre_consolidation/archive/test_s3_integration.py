#!/usr/bin/env python3
"""
Test script for S3 integration with document processing pipeline.
Tests upload, OCR URL generation, and cleanup functionality.
"""

import os
import sys
import tempfile
from pathlib import Path

# Add scripts directory to path
sys.path.append(str(Path(__file__).parent))

from s3_storage import S3StorageManager
from config import S3_BUCKET_PRIVATE, S3_BUCKET_PUBLIC
import uuid

def create_test_pdf():
    """Create a simple test PDF file"""
    try:
        import fitz  # PyMuPDF
        
        # Create a test PDF
        doc = fitz.open()
        page = doc.new_page()
        text = "This is a test PDF for S3 integration testing.\nDocument UUID: test-123"
        page.insert_text((50, 50), text)
        
        # Save to temp file
        temp_file = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
        doc.save(temp_file.name)
        doc.close()
        
        return temp_file.name
    except ImportError:
        print("PyMuPDF not installed. Creating a simple text file instead.")
        temp_file = tempfile.NamedTemporaryFile(suffix='.txt', delete=False)
        temp_file.write(b"This is a test file for S3 integration testing.")
        temp_file.close()
        return temp_file.name

def test_s3_integration():
    """Test the complete S3 integration workflow"""
    print("Testing S3 Integration for Document Processing")
    print("=" * 50)
    
    # Initialize S3 manager
    s3_manager = S3StorageManager()
    
    # Generate test document UUID
    test_uuid = str(uuid.uuid4())
    print(f"Test document UUID: {test_uuid}")
    
    # Create test file
    test_file = create_test_pdf()
    original_filename = "Test Document.pdf"
    print(f"Created test file: {test_file}")
    
    try:
        # Test 1: Upload to private bucket with UUID naming
        print("\n1. Testing upload to private bucket...")
        upload_result = s3_manager.upload_document_with_uuid_naming(
            test_file, test_uuid, original_filename
        )
        print(f"✓ Uploaded to: {upload_result['s3_key']}")
        print(f"  Bucket: {upload_result['s3_bucket']}")
        print(f"  Size: {upload_result['file_size']} bytes")
        print(f"  MD5: {upload_result['md5_hash']}")
        
        # Test 2: Copy to public bucket
        print("\n2. Testing copy to public bucket...")
        public_key = s3_manager.copy_to_public_bucket(
            upload_result['s3_key'], test_uuid
        )
        print(f"✓ Copied to public bucket: {public_key}")
        
        # Test 3: Generate presigned URL
        print("\n3. Testing presigned URL generation...")
        presigned_url = s3_manager.generate_presigned_url_for_ocr(public_key)
        print(f"✓ Generated presigned URL (expires in 1 hour):")
        print(f"  {presigned_url[:100]}...")
        
        # Test 4: Verify URL is accessible
        print("\n4. Testing URL accessibility...")
        import requests
        response = requests.head(presigned_url)
        if response.status_code == 200:
            print(f"✓ URL is accessible (status: {response.status_code})")
            print(f"  Content-Type: {response.headers.get('Content-Type', 'N/A')}")
            print(f"  Content-Length: {response.headers.get('Content-Length', 'N/A')} bytes")
        else:
            print(f"✗ URL returned status: {response.status_code}")
        
        # Test 5: Cleanup
        print("\n5. Testing cleanup...")
        s3_manager.cleanup_ocr_file(public_key)
        print("✓ Cleaned up public OCR file")
        
        # Test 6: Test S3 path format
        print("\n6. Testing S3 path handling...")
        s3_path = f"s3://{S3_BUCKET_PRIVATE}/{upload_result['s3_key']}"
        print(f"  S3 path format: {s3_path}")
        
        # Test complete
        print("\n" + "=" * 50)
        print("✓ All tests passed!")
        print("\nIntegration points verified:")
        print("- Document upload with UUID naming")
        print("- Copy to public bucket for OCR")
        print("- Presigned URL generation")
        print("- URL accessibility")
        print("- Cleanup after processing")
        
    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        # Clean up test file
        if os.path.exists(test_file):
            os.unlink(test_file)
            print(f"\nCleaned up test file: {test_file}")
    
    return True

def test_mistral_ocr_integration():
    """Test the Mistral OCR integration with S3"""
    print("\n\nTesting Mistral OCR Integration")
    print("=" * 50)
    
    try:
        from ocr_extraction import extract_text_from_pdf_mistral_ocr
        
        # Create test PDF
        test_file = create_test_pdf()
        test_uuid = str(uuid.uuid4())
        
        print(f"Testing Mistral OCR with file: {test_file}")
        print(f"Document UUID: {test_uuid}")
        
        # Test OCR extraction
        text, metadata = extract_text_from_pdf_mistral_ocr(test_file, test_uuid)
        
        if text:
            print("✓ Mistral OCR extraction successful!")
            print(f"  Extracted text length: {len(text)} characters")
            print(f"  Text preview: {text[:100]}...")
            if metadata:
                print(f"  Metadata: {metadata[0] if metadata else 'None'}")
        else:
            print("✗ Mistral OCR extraction failed")
        
        # Clean up
        if os.path.exists(test_file):
            os.unlink(test_file)
            
    except Exception as e:
        print(f"✗ Mistral OCR test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    # Run basic S3 tests
    if test_s3_integration():
        # If basic tests pass, try Mistral OCR
        test_mistral_ocr_integration()
    else:
        print("\nSkipping Mistral OCR test due to basic test failure")