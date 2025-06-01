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