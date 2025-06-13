# Mistral OCR Refactoring Plan

## 1. Overview

This document outlines the plan to refactor Phase 3 of the document processing pipeline, replacing the current Qwen VL OCR model with Mistral's OCR API. The goal is to create a more robust text extraction system that leverages Mistral's specialized OCR capabilities.

## 2. Current Implementation Analysis

The current OCR implementation in `extract_text_from_pdf_qwen_vl_ocr` has several limitations:

1. **Heavy GPU Dependency**: Requires loading the Qwen VL model, which needs significant GPU resources
2. **Complex Image Handling**: Requires rendering PDF pages to images and managing those in memory
3. **Token Limitations**: Limited by the Qwen model's context window for handling large documents
4. **Precision Issues**: May struggle with complex layouts, tables, and specialized formatting

## 3. Advantages of Mistral OCR

The Mistral OCR API offers several benefits:

1. **API-Based Architecture**: No local GPU requirements; processing happens in Mistral's cloud
2. **PDF Native Support**: Accepts PDF files directly without intermediate image conversion
3. **Higher Quality OCR**: Specialized in document text extraction with better formatting preservation
4. **Scalability**: Can handle larger documents more efficiently
5. **Simplicity**: Streamlined implementation with fewer dependencies
6. **Markdown Output**: Returns text in markdown format, preserving document structure

## 4. Implementation Strategy

### 4.1 Code Location

We need to modify the following files:

1. **New Utility File**: Create `/Users/josephott/Documents/phase_1_2_3_process_v5/scripts/mistral_utils.py`
2. **Primary Target**: `/Users/josephott/Documents/phase_1_2_3_process_v5/scripts/ocr_extraction.py`
3. **Configuration**: `/Users/josephott/Documents/phase_1_2_3_process_v5/scripts/config.py`
4. **Model Initialization**: `/Users/josephott/Documents/phase_1_2_3_process_v5/scripts/models_init.py` (optional)

### 4.2 New Function Implementation

Create a new utility function `extract_text_from_url` in `mistral_utils.py` that will:

1. Accept a document URL and optional document name
2. Send it to Mistral's dedicated OCR API endpoint
3. Process the response and return the extracted text with metadata

### 4.3 Detailed Implementation Steps

#### Step 1: Update Configuration (config.py)

Add the following to `config.py`:

```python
# Mistral OCR Configuration
MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY")
USE_MISTRAL_FOR_OCR = os.environ.get("USE_MISTRAL_FOR_OCR", "true").lower() == "true"  # Default to True
MISTRAL_OCR_TIMEOUT = int(os.environ.get("MISTRAL_OCR_TIMEOUT", "120"))  # Timeout in seconds
```

#### Step 2: Create Mistral Utils Module (mistral_utils.py)

Create a new file `mistral_utils.py` with the following function:

```python
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
    from config import MISTRAL_API_KEY, MISTRAL_OCR_TIMEOUT
    
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
        "model": "mistral-ocr-latest",
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

#### Step 3: Add New OCR Function (ocr_extraction.py)

Add the following new function to `ocr_extraction.py`:

```python
def extract_text_from_pdf_mistral_ocr(pdf_path: str) -> tuple[str | None, list | None]:
    """
    Process a PDF file using Mistral's dedicated OCR API endpoint.
    This function uploads the PDF to a temporary S3 location and uses
    the URL-based OCR processing approach.
    
    Args:
        pdf_path: Path to the PDF file
        
    Returns:
        tuple[str, list]: Extracted text and page-level metadata
    """
    import os
    import time
    import boto3
    import uuid
    from datetime import datetime
    from mistral_utils import extract_text_from_url
    from config import MISTRAL_OCR_TIMEOUT, USE_MISTRAL_FOR_OCR
    
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
        
        # Upload the file to S3 temporarily to get a URL
        s3_bucket = os.getenv("S3_BUCKET", "preprocessv2")
        s3_key = f"temp_ocr/{uuid.uuid4()}/{file_name}"
        
        # Create S3 client
        s3_client = boto3.client('s3')
        
        # Upload file to S3
        logger.info(f"Uploading {file_name} to S3 bucket {s3_bucket} at key {s3_key}")
        with open(pdf_path, 'rb') as file_data:
            s3_client.upload_fileobj(file_data, s3_bucket, s3_key)
        
        # Generate presigned URL (valid for 1 hour)
        url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': s3_bucket, 'Key': s3_key},
            ExpiresIn=3600
        )
        
        logger.info(f"Generated presigned URL for OCR processing")
        
        # Process with Mistral OCR API
        result = extract_text_from_url(url, file_name)
        
        # Clean up the temporary S3 file
        try:
            s3_client.delete_object(Bucket=s3_bucket, Key=s3_key)
            logger.info(f"Cleaned up temporary S3 file {s3_key}")
        except Exception as e:
            logger.warning(f"Could not delete temporary S3 file: {e}")
        
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

#### Step 4: Modify Main Processing Function (main_pipeline.py)

Update the file type detection in `main_pipeline.py` at line 47-57:

```python
if detected_file_type == '.pdf':
    # Choose OCR method based on configuration
    if config.USE_MISTRAL_FOR_OCR:
        raw_text, ocr_meta = extract_text_from_pdf_mistral_ocr(file_path)
    else:
        raw_text, ocr_meta = extract_text_from_pdf_qwen_vl_ocr(file_path)
elif detected_file_type == '.docx':
    raw_text = extract_text_from_docx(file_path)
# ... other file types ...
```

#### Step 5 (Optional): Adjust Model Initialization

If we want to avoid loading the Qwen VL model when using Mistral OCR, we can modify the model initialization logic in `models_init.py` to conditionally load models.

```python
def initialize_all_models():
    # ... existing code ...
    
    # Only initialize Qwen VL if not using Mistral OCR
    if not config.USE_MISTRAL_FOR_OCR:
        initialize_qwen2_vl_ocr_model()
    
    # ... existing code ...
```

## 5. API Specification

The Mistral OCR API endpoint is designed for document processing with high-quality text extraction.

### Endpoint
```
POST https://api.mistral.ai/v1/ocr
```

### Authentication
All requests require a Bearer token:
```
Authorization: Bearer {MISTRAL_API_KEY}
```

### Request Format
Our implementation uses the document_url approach with this exact payload structure:

```json
{
  "model": "mistral-ocr-latest",
  "document": {
    "document_url": "https://example.com/path/to/document.pdf",
    "document_name": "Example Document Name",
    "type": "document_url"
  }
}
```

Key parameters:
- `model`: Always "mistral-ocr-latest" to use the latest available OCR model
- `document`: Contains document details with three required sub-fields:
  - `document_url`: The publicly accessible URL to the PDF document
  - `document_name`: Optional identifier for the document (we include the filename)
  - `type`: Must be "document_url" for URL-based processing

### Response Structure

The successful response includes:

```json
{
  "pages": [
    {
      "index": 0,
      "markdown": "Extracted text in markdown format...",
      "images": [...],
      "dimensions": {...}
    },
    ...more pages...
  ],
  "model": "mistral-ocr-2503-completion",
  "usage_info": {
    "pages_processed": 6,
    "doc_size_bytes": 1935326
  }
}
```

Our implementation processes this response by:
1. Checking for the `pages` array
2. Extracting the `markdown` text from each page
3. Combining all page text into a single `combined_text` field
4. Preserving the original response structure for reference

## 6. Testing Strategy

Testing the new OCR implementation should follow these steps:

### 6.1 Unit Testing

1. **Function Test**: Test the `extract_text_from_url` function with a variety of PDFs:
   - Simple text documents
   - Documents with tables
   - Documents with images and text
   - Multi-page documents
   - Documents in different languages

2. **Error Handling Test**: Verify the function handles errors gracefully:
   - Invalid API key
   - Network failures
   - Invalid file formats
   - API rate limiting

### 6.2 Integration Testing

1. **Pipeline Test**: Test the entire document processing pipeline with Mistral OCR:
   - Upload a document through the frontend
   - Verify it's processed correctly through all stages
   - Compare the results with the Qwen VL implementation

2. **Performance Comparison**:
   - Document processing time
   - Text extraction quality
   - Memory usage

### 6.3 Batch Processing Test

Create a test script to process multiple documents concurrently:

```python
from concurrent.futures import ThreadPoolExecutor, as_completed
from mistral_utils import extract_text_from_url

def test_batch_processing(pdf_files, max_workers=5):
    results = []
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_file = {executor.submit(process_file, file_name): file_name for file_name in pdf_files}
        
        for future in as_completed(future_to_file):
            file_name = future_to_file[future]
            try:
                file_name, success, result = future.result()
                results.append({
                    "file_name": file_name,
                    "success": success,
                    "result": result
                })
            except Exception as e:
                print(f"Error processing {file_name}: {e}")
    
    return results
```

## 7. Rollback Plan

If issues arise with the Mistral OCR implementation, we can:

1. Set `USE_MISTRAL_FOR_OCR = False` in the environment variables
2. The system will automatically fall back to the Qwen VL implementation
3. No code changes will be required for rollback

## 8. Future Enhancements

After successfully implementing the Mistral OCR, consider these enhancements:

1. **Hybrid Approach**: Implement a fallback mechanism that tries Mistral first, then Qwen VL if Mistral fails
2. **Caching**: Cache API responses to avoid redundant processing of the same documents
3. **Streaming**: For large documents, implement a streaming approach to process pages in batches
4. **Error Recovery**: Implement more sophisticated error recovery to handle API timeouts or failures
5. **Advanced OCR Options**: Explore additional Mistral parameters for specialized document types

## 9. Key Insights

1. **Request Structure**: The exact payload structure is critical - the document must be nested under a "document" key with "type": "document_url" specified
2. **Response Handling**: The API returns page-by-page content rather than a single text field
3. **Markdown Format**: The extracted text comes in markdown format, preserving document structure
4. **Image Handling**: The API identifies images but does not return base64 content by default
5. **Concurrency**: The API handles concurrent requests well within reasonable rate limits

## 10. Implementation Verification

The implementation methodology outlined in this document has been tested and verified to work successfully with the Mistral OCR API. The key findings from our implementation testing are as follows:

### 10.1 API Response Structure

The Mistral OCR API returns a structured JSON response with the following key components:

```json
{
  "pages": [
    {
      "index": 0,
      "markdown": "# Document Title...",
      "images": [],
      "dimensions": {
        "dpi": 200,
        "height": 2339,
        "width": 1653
      }
    }
    // Additional pages...
  ],
  "model": "mistral-ocr-2503-completion",
  "document_annotation": null,
  "usage_info": {
    "pages_processed": 1,
    "doc_size_bytes": 13264
  },
  "combined_text": "# Document Title...\n\n"
}
```

Key components in the response:

1. **pages**: An array containing each page's content
   - **index**: Zero-based page number
   - **markdown**: The extracted text in markdown format, preserving structure
   - **images**: Array of any extracted images (often empty)
   - **dimensions**: Page dimensions and DPI information

2. **model**: The specific Mistral OCR model version used

3. **usage_info**: Processing statistics
   - **pages_processed**: Number of pages in the document
   - **doc_size_bytes**: Size of the document in bytes

4. **combined_text**: Our custom added field that combines all pages into a single text string

### 10.2 Testing Results

The implementation was tested with publicly available PDFs and successfully:

1. Connected to the Mistral OCR API using the correct API endpoint format
2. Processed both simple and complex documents with high accuracy
3. Preserved formatting through markdown-based output
4. Properly handled multi-page documents
5. Returned comprehensive metadata about the processing

The key success factors in the implementation were:

1. Using the exact document_url payload structure as required by the API
2. Properly handling the page-by-page response format
3. Implementing robust error handling for API failures
4. Adding the combined_text field for easier processing in our pipeline

### 10.3 Integration Notes

For production implementation, the system uses a URL-based approach where:

1. For documents in Supabase Storage, we generate a public URL and pass directly to the API
2. For local files, we temporarily upload to S3 to generate a URL, then remove after processing
3. All communication with the API is handled through the extract_text_from_url function

## 11. Conclusion

Refactoring the OCR component to use Mistral's API offers significant advantages in terms of reliability, quality, and system resource usage. The implementation plan outlined above provides a clear path to integrate this improvement while maintaining backward compatibility and ensuring a smooth transition.

By following this plan, we can enhance the document processing pipeline with minimal disruption to the existing workflow, while providing a better experience for users uploading documents to the system. The verified implementation ensures high-quality text extraction with proper formatting preservation and robust error handling.