"""
PDF validation utilities for OCR processing.
"""
import os
import logging
from typing import Dict, Any, Tuple
from pathlib import Path
import PyPDF2

logger = logging.getLogger(__name__)


def validate_pdf_for_processing(pdf_path: str) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Validate PDF file for processing.
    
    Args:
        pdf_path: Path to PDF file
        
    Returns:
        Tuple of (is_valid, error_message, metadata)
    """
    try:
        if not os.path.exists(pdf_path):
            return False, f"File not found: {pdf_path}", {}
        
        # Check file size
        file_size = os.path.getsize(pdf_path)
        if file_size == 0:
            return False, "PDF file is empty", {}
        
        if file_size > 500 * 1024 * 1024:  # 500MB limit
            return False, f"PDF file too large: {file_size} bytes", {}
        
        # Check file extension
        if not pdf_path.lower().endswith('.pdf'):
            return False, "File is not a PDF", {}
        
        # Try to read PDF
        try:
            with open(pdf_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                page_count = len(pdf_reader.pages)
                
                if page_count == 0:
                    return False, "PDF has no pages", {}
                
                if page_count > 3000:  # AWS Textract limit
                    return False, f"PDF has too many pages: {page_count}", {}
                
                # Try to read first page
                first_page = pdf_reader.pages[0]
                _ = first_page.extract_text()
                
                metadata = {
                    'page_count': page_count,
                    'file_size_bytes': file_size,
                    'pdf_version': getattr(pdf_reader, 'pdf_header', 'unknown')
                }
                
                return True, "", metadata
                
        except Exception as e:
            return False, f"Invalid PDF format: {str(e)}", {}
            
    except Exception as e:
        logger.error(f"PDF validation error: {e}")
        return False, f"Validation error: {str(e)}", {}


def validate_ocr_result(result: Dict[str, Any]) -> bool:
    """
    Validate OCR extraction result.
    
    Args:
        result: OCR result dictionary
        
    Returns:
        True if valid
    """
    if not isinstance(result, dict):
        return False
    
    # Required fields
    if 'text' not in result:
        return False
    
    if not isinstance(result['text'], str):
        return False
    
    # Text should not be empty after stripping
    if not result['text'].strip():
        return False
    
    # Check confidence if present
    if 'confidence' in result:
        confidence = result['confidence']
        if not isinstance(confidence, (int, float)):
            return False
        if confidence < 0 or confidence > 1:
            return False
    
    # Check page count if present
    if 'page_count' in result:
        page_count = result['page_count']
        if not isinstance(page_count, int):
            return False
        if page_count <= 0:
            return False
    
    return True