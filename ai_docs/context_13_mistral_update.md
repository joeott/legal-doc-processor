# Mistral OCR Implementation Integration

## 1. Overview

This document outlines the specific steps required to integrate the Mistral OCR API implementation into the existing document processing pipeline. Our goal is to replace the current Qwen VL OCR method with the more robust Mistral OCR API for all PDF text extraction while maintaining backward compatibility.

## 2. Affected Files

Based on the document flow analysis in `context_11_document_flow_next_steps.md` and the implementation plan in `context_12_mistral_refactor_ocr.md`, the following files need to be modified:

1. `/scripts/ocr_extraction.py` - Contains the OCR implementation functions
2. `/scripts/main_pipeline.py` - Entry point for text extraction (Phase 3)
3. `/scripts/config.py` - Configuration parameters for OCR methods

## 3. Implementation Tasks

### 3.1. Configuration Updates (config.py)

The following configuration parameters need to be added to `config.py`:

```python
# Mistral OCR Configuration
MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY")
USE_MISTRAL_FOR_OCR = os.environ.get("USE_MISTRAL_FOR_OCR", "true").lower() in ("true", "1", "yes")  # Default to True
MISTRAL_OCR_MODEL = os.environ.get("MISTRAL_OCR_MODEL", "mistral-ocr-latest")
MISTRAL_OCR_TIMEOUT = int(os.environ.get("MISTRAL_OCR_TIMEOUT", "120"))  # Timeout in seconds
S3_OCR_TEMP_BUCKET = os.environ.get("S3_OCR_TEMP_BUCKET", S3_BUCKET_NAME)  # Use same bucket by default
```

This allows configuring the OCR method through environment variables and provides sensible defaults.

### 3.2. Create Utility Module (mistral_utils.py)

Create a new file `/scripts/mistral_utils.py` with the core Mistral OCR API functionality:

```python
"""
Utility functions for interacting with Mistral AI OCR API.
This module provides functions to extract text from documents using Mistral's dedicated OCR API.
"""

import os
import requests
import logging
from typing import Dict, Any, Optional

# Configure logging
logger = logging.getLogger(__name__)

def extract_text_from_url(url: str, document_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Extract text from a document URL using Mistral OCR API.
    
    Args:
        url: URL to the document to process
        document_name: Optional name for the document
        
    Returns:
        Dict containing the OCR results or error information
    """
    from config import MISTRAL_API_KEY, MISTRAL_OCR_TIMEOUT, MISTRAL_OCR_MODEL
    
    if not MISTRAL_API_KEY:
        logger.error("MISTRAL_API_KEY environment variable not set")
        return {"error": "API key not configured"}
    
    # Set headers
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {MISTRAL_API_KEY}"
    }
    
    # Prepare payload based on documented format
    payload = {
        "model": MISTRAL_OCR_MODEL,
        "document": {
            "document_url": url,
            "type": "document_url"
        }
    }
    
    # Add document name if provided
    if document_name:
        payload["document"]["document_name"] = document_name
    
    try:
        # Make the request with timeout
        logger.info(f"Sending OCR request to Mistral API for URL: {url}")
        response = requests.post(
            "https://api.mistral.ai/v1/ocr",
            headers=headers,
            json=payload,
            timeout=MISTRAL_OCR_TIMEOUT
        )
        
        # Check status code
        if response.status_code == 200:
            logger.info("OCR request successful")
            result = response.json()
            
            # Process the response to combine text from all pages
            if "pages" in result:
                combined_text = ""
                for page in result["pages"]:
                    if "markdown" in page:
                        combined_text += page["markdown"] + "\n\n"
                
                if combined_text:
                    # Add combined text to the result
                    result["combined_text"] = combined_text
                    
                    # Log a sample of the text
                    text_sample = combined_text[:300] + "..." if len(combined_text) > 300 else combined_text
                    logger.info(f"Extracted text sample: {text_sample}")
                    
                    # Log usage statistics if available
                    if "usage_info" in result:
                        usage = result["usage_info"]
                        logger.info(f"Pages processed: {usage.get('pages_processed', 'N/A')}, " 
                                   f"Document size: {usage.get('doc_size_bytes', 0) / 1024 / 1024:.2f} MB")
            
            return result
        else:
            logger.error(f"OCR request failed with status code {response.status_code}: {response.text}")
            return {
                "error": f"Status {response.status_code}",
                "details": response.text
            }
    except requests.exceptions.Timeout:
        logger.error(f"Timeout error when processing URL with Mistral OCR after {MISTRAL_OCR_TIMEOUT}s")
        return {"error": "Request timed out"}
    except Exception as e:
        logger.error(f"Error making OCR request: {e}")
        return {"error": str(e)}
```

### 3.3. Update OCR Extraction Module (ocr_extraction.py)

Add the new Mistral OCR function to `ocr_extraction.py`:

```python
def extract_text_from_pdf_mistral_ocr(pdf_path: str) -> tuple[str | None, list | None]:
    """
    Process a PDF file using Mistral's dedicated OCR API endpoint.
    This function gets a URL for the PDF and uses the Mistral OCR API for extraction.
    
    Args:
        pdf_path: Path to the PDF file
        
    Returns:
        tuple[str, list]: Extracted text and page-level metadata
    """
    import time
    import uuid
    from datetime import datetime
    from mistral_utils import extract_text_from_url
    from config import MISTRAL_OCR_TIMEOUT, USE_MISTRAL_FOR_OCR
    from supabase_utils import get_supabase_client, generate_temp_url
    
    start_time = time.time()
    file_name = os.path.basename(pdf_path)
    file_size = os.path.getsize(pdf_path) / (1024 * 1024)  # Size in MB
    
    logger.info(f"Processing PDF with Mistral OCR API: {file_name} ({file_size:.2f} MB)")
    
    try:
        # Get page count for metadata
        try:
            doc = fitz.open(pdf_path)
            num_pages = len(doc)
            doc.close()
            logger.info(f"PDF has {num_pages} pages")
        except Exception as e:
            logger.error(f"Could not read PDF or get page count: {e}")
            num_pages = 1  # Default to 1 if we can't determine
        
        # Generate a URL for the PDF
        # If the file is already in Supabase Storage, get its URL
        # Otherwise, upload it temporarily
        try:
            # Try to detect if file is already in Supabase storage
            if "/var/uploads/" in pdf_path or pdf_path.startswith("uploads/"):
                # Extract the path relative to the storage bucket
                storage_path = pdf_path.split("/uploads/")[-1] if "/uploads/" in pdf_path else pdf_path
                # Get Supabase client
                supabase_client = get_supabase_client()
                # Generate URL for the file
                url = generate_temp_url(supabase_client, "uploads", storage_path)
                logger.info(f"Using existing Supabase Storage URL for {file_name}")
            else:
                # For local files, we'll need to upload to Supabase Storage temporarily
                temp_path = f"temp_ocr/{uuid.uuid4()}/{file_name}"
                supabase_client = get_supabase_client()
                # Upload the file to Supabase Storage
                with open(pdf_path, 'rb') as file_data:
                    supabase_client.storage.from_("uploads").upload(temp_path, file_data)
                # Generate URL for the temporary file
                url = generate_temp_url(supabase_client, "uploads", temp_path)
                logger.info(f"Uploaded {file_name} to Supabase Storage at {temp_path}")
        except Exception as e:
            logger.error(f"Failed to generate URL for PDF: {e}")
            return None, None
            
        # Process with Mistral OCR API
        result = extract_text_from_url(url, file_name)
        
        # Clean up temporary file if we created one
        if 'temp_path' in locals():
            try:
                supabase_client.storage.from_("uploads").remove([temp_path])
                logger.info(f"Cleaned up temporary Supabase Storage file {temp_path}")
            except Exception as e:
                logger.warning(f"Could not delete temporary Supabase Storage file: {e}")
        
        # Check for errors
        if "error" in result:
            logger.error(f"Mistral OCR failed: {result['error']}")
            return None, None
        
        # Extract text and return
        if "combined_text" in result:
            extracted_text = result["combined_text"]
            processing_time = time.time() - start_time
            
            # Get usage info if available
            pages_processed = result.get("usage_info", {}).get("pages_processed", num_pages)
            doc_size_bytes = result.get("usage_info", {}).get("doc_size_bytes", os.path.getsize(pdf_path))
            
            # Create comprehensive metadata
            page_level_metadata = [{
                "page_number": i+1,
                "method": "MistralOCR",
                "model": result.get("model", "mistral-ocr-latest"),
                "timestamp": datetime.now().isoformat(),
                "processing_time_seconds": processing_time,
                "file_size_bytes": doc_size_bytes,
                "char_count": len(extracted_text),
                "num_pages_in_doc": num_pages,
                "pages_processed": pages_processed
            } for i in range(num_pages)]
            
            # Sample the extracted text for logging (first 300 chars)
            text_sample = extracted_text[:300] + "..." if len(extracted_text) > 300 else extracted_text
            logger.info(f"Text sample: {text_sample}")
            
            return extracted_text, page_level_metadata
        else:
            logger.error("No text was extracted from the document")
            return None, None
            
    except Exception as e:
        logger.error(f"Error processing PDF with Mistral OCR: {e}", exc_info=True)
        return None, None
```

### 3.4. Update Imports in ocr_extraction.py

Update the imports at the top of `ocr_extraction.py`:

```python
import os
import logging
from PIL import Image
import fitz  # PyMuPDF
import torch
import time
import uuid
from datetime import datetime

from config import (
    QWEN2_VL_OCR_PROMPT, QWEN2_VL_OCR_MAX_NEW_TOKENS,  # Qwen2-VL-OCR configs
    USE_MISTRAL_FOR_OCR, MISTRAL_OCR_TIMEOUT, MISTRAL_OCR_MODEL
)
from models_init import (
    get_qwen2_vl_ocr_model, get_qwen2_vl_ocr_processor, 
    get_qwen2_vl_ocr_device, get_process_vision_info,
    WHISPER_MODEL
)
from mistral_utils import extract_text_from_url

logger = logging.getLogger(__name__)
```

### 3.5. Update Main Pipeline (main_pipeline.py)

Update the imports at the top of `main_pipeline.py`:

```python
from ocr_extraction import (
    extract_text_from_pdf_qwen_vl_ocr, extract_text_from_pdf_mistral_ocr,
    extract_text_from_docx, extract_text_from_txt, extract_text_from_eml,
    transcribe_audio_whisper
)
from config import USE_MISTRAL_FOR_OCR
```

Modify the text extraction logic in `main_pipeline.py` around line 52-57:

```python
if detected_file_type == '.pdf':
    # Choose OCR method based on configuration
    if USE_MISTRAL_FOR_OCR:
        logger.info(f"Using Mistral OCR API for text extraction from PDF: {file_name}")
        raw_text, ocr_meta = extract_text_from_pdf_mistral_ocr(file_path)
        # Fallback to Qwen VL if Mistral fails and Qwen is available
        if raw_text is None:
            logger.warning(f"Mistral OCR failed for {file_name}, attempting fallback to Qwen VL OCR")
            raw_text, ocr_meta = extract_text_from_pdf_qwen_vl_ocr(file_path)
    else:
        logger.info(f"Using Qwen VL OCR for text extraction from PDF: {file_name}")
        raw_text, ocr_meta = extract_text_from_pdf_qwen_vl_ocr(file_path)
elif detected_file_type == '.docx':
    raw_text = extract_text_from_docx(file_path)
# ... other file types remain the same
```

### 3.6. Create/Update Supabase Utilities

If they don't already exist, create or update functions in `supabase_utils.py` to handle Supabase Storage URLs:

```python
def get_supabase_client():
    """
    Get a properly configured Supabase client.
    
    Returns:
        Supabase client instance
    """
    from supabase import create_client
    from config import SUPABASE_URL, SUPABASE_ANON_KEY
    
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        raise ValueError("SUPABASE_URL and SUPABASE_ANON_KEY must be set")
    
    return create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

def generate_temp_url(supabase_client, bucket, path, expiry_seconds=3600):
    """
    Generate a temporary URL for a file in Supabase Storage.
    
    Args:
        supabase_client: Supabase client instance
        bucket: Storage bucket name
        path: Path to the file in the bucket
        expiry_seconds: URL expiry time in seconds (default: 1 hour)
        
    Returns:
        Temporary public URL for the file
    """
    # Get signed URL from Supabase
    result = supabase_client.storage.from_(bucket).create_signed_url(path, expiry_seconds)
    
    # Return the signed URL
    return result.get("signedURL")
```

## 4. Summary of Changes

1. **New Files to Create**:
   - `/scripts/mistral_utils.py` - Core Mistral OCR API functionality

2. **Existing Files to Modify**:
   - `/scripts/config.py` - Add Mistral OCR configuration parameters
   - `/scripts/ocr_extraction.py` - Add Mistral OCR implementation
   - `/scripts/main_pipeline.py` - Update document flow to use Mistral OCR
   - `/scripts/supabase_utils.py` - Enhance or create for URL generation

## 5. Implementation Benefits

This implementation provides several advantages:

1. **Improved Extraction Quality**: Mistral OCR delivers better formatting and structure
2. **Markdown Preservation**: Maintains document formatting through markdown output
3. **Fallback Mechanism**: Falls back to Qwen VL OCR if Mistral fails
4. **Configuration Flexibility**: Can be disabled via environment variables
5. **Detailed Metadata**: Provides comprehensive processing information

## 6. Testing Procedure

After implementing these changes, test the integration using:

1. **Single Document Test**:
   - Set environment variable `MISTRAL_API_KEY=your_api_key`
   - Upload a PDF through the frontend
   - Verify extraction quality and correctness in database

2. **Fallback Test**:
   - Temporarily set an invalid API key
   - Verify system falls back to Qwen VL OCR

3. **Configuration Test**:
   - Set `USE_MISTRAL_FOR_OCR=false`
   - Verify system uses only Qwen VL OCR

4. **Multi-Document Test**:
   - Process multiple documents in parallel
   - Verify all complete successfully

## 7. Rollback Plan

If issues arise with the Mistral OCR implementation:

1. Set environment variable `USE_MISTRAL_FOR_OCR=false`
2. The system will automatically fall back to using the Qwen VL implementation
3. No code changes will be required for rollback