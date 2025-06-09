"""Safe PDF operations with multiple fallbacks"""

import os
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

def safe_pdf_operation(file_path: str, operation: str = "check") -> Optional[Any]:
    """
    Safely perform PDF operations with multiple fallbacks.
    
    Args:
        file_path: Path to PDF file (local or S3)
        operation: Type of operation ('check', 'read', 'page_count')
        
    Returns:
        Result of operation or None if all methods fail
    """
    
    # For S3 files, skip local operations if configured
    if file_path.startswith('s3://') and os.getenv('SKIP_PDF_PREPROCESSING', '').lower() == 'true':
        logger.info("S3 file detected with SKIP_PDF_PREPROCESSING=true, skipping local PDF operations")
        return {
            "method": "textract_direct", 
            "preprocessing": "skipped",
            "s3_path": file_path
        }
    
    # Try PyMuPDF first
    try:
        import fitz
        logger.debug("Attempting PDF operation with PyMuPDF")
        
        if operation == "check":
            doc = fitz.open(file_path)
            result = {
                "exists": True,
                "page_count": doc.page_count,
                "method": "pymupdf"
            }
            doc.close()
            return result
        elif operation == "read":
            return fitz.open(file_path)
        elif operation == "page_count":
            doc = fitz.open(file_path)
            count = doc.page_count
            doc.close()
            return count
            
    except Exception as e:
        logger.warning(f"PyMuPDF failed for {file_path}: {e}, trying alternatives")
    
    # Fallback to PyPDF2 for basic operations
    try:
        import PyPDF2
        logger.debug("Attempting PDF operation with PyPDF2")
        
        if file_path.startswith('s3://'):
            # Download S3 file to temp location for PyPDF2
            import tempfile
            import boto3
            from urllib.parse import urlparse
            
            parsed = urlparse(file_path)
            bucket = parsed.netloc
            key = parsed.path.lstrip('/')
            
            s3 = boto3.client('s3')
            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
                s3.download_file(bucket, key, tmp.name)
                temp_path = tmp.name
            
            with open(temp_path, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                
                if operation == "check":
                    result = {
                        "exists": True,
                        "page_count": len(reader.pages),
                        "method": "pypdf2"
                    }
                    os.unlink(temp_path)
                    return result
                elif operation == "page_count":
                    count = len(reader.pages)
                    os.unlink(temp_path)
                    return count
                    
            os.unlink(temp_path)
            
        else:
            # Local file
            with open(file_path, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                
                if operation == "check":
                    return {
                        "exists": True,
                        "page_count": len(reader.pages),
                        "method": "pypdf2"
                    }
                elif operation == "page_count":
                    return len(reader.pages)
                    
    except Exception as e:
        logger.warning(f"PyPDF2 failed for {file_path}: {e}")
    
    # Final fallback - just check file exists and size
    logger.debug("Using basic file check as final fallback")
    
    if operation == "check":
        if file_path.startswith('s3://'):
            # Check S3 file exists
            try:
                import boto3
                from urllib.parse import urlparse
                
                parsed = urlparse(file_path)
                bucket = parsed.netloc
                key = parsed.path.lstrip('/')
                
                s3 = boto3.client('s3')
                response = s3.head_object(Bucket=bucket, Key=key)
                
                return {
                    "exists": True,
                    "size": response['ContentLength'],
                    "method": "s3_head",
                    "content_type": response.get('ContentType', 'unknown')
                }
            except Exception as e:
                logger.error(f"S3 file check failed: {e}")
                return {"exists": False, "error": str(e)}
        else:
            # Local file check
            exists = os.path.exists(file_path)
            return {
                "exists": exists,
                "size": os.path.getsize(file_path) if exists else 0,
                "method": "filesystem"
            }
    
    logger.warning(f"All PDF operation methods failed for {file_path}")
    return None