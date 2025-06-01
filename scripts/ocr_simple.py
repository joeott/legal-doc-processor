"""
Simple OCR extraction wrapper for PDF files.
"""

import logging
from typing import Dict, Any
from pathlib import Path
import tempfile
import os

from scripts.s3_storage import S3StorageManager
from scripts.textract_utils import TextractProcessor

logger = logging.getLogger(__name__)

def extract_text_from_pdf(file_path: str) -> Dict[str, Any]:
    """
    Simple wrapper to extract text from PDF file (local or S3).
    
    Args:
        file_path: Path to PDF file (local path or s3:// URI)
        
    Returns:
        Dict with status, text, metadata, and error if any
    """
    try:
        # Handle S3 paths
        if file_path.startswith('s3://'):
            # Parse S3 URI
            s3_parts = file_path.replace('s3://', '').split('/', 1)
            if len(s3_parts) != 2:
                return {
                    'status': 'error',
                    'error': f'Invalid S3 URI: {file_path}'
                }
            
            bucket_name, s3_key = s3_parts
            
            # Use Textract directly for S3 files
            textract = TextractProcessor()
            
            # Process with Textract
            result = textract.process_document_s3(
                s3_bucket=bucket_name,
                s3_key=s3_key
            )
            
            if result and result.get('text'):
                return {
                    'status': 'success',
                    'text': result['text'],
                    'metadata': result.get('metadata', {}),
                    'method': 'textract',
                    'page_count': result.get('metadata', {}).get('page_count', 1)
                }
            else:
                return {
                    'status': 'error',
                    'error': 'Textract processing failed'
                }
        
        # Handle local files
        else:
            if not Path(file_path).exists():
                return {
                    'status': 'error',
                    'error': f'File not found: {file_path}'
                }
            
            # Process local file with Textract
            textract = TextractProcessor()
            
            # Upload to S3 temporarily for Textract
            s3_manager = S3StorageManager()
            import uuid
            temp_key = f"temp-ocr/{uuid.uuid4()}.pdf"
            
            try:
                with open(file_path, 'rb') as f:
                    s3_manager.s3_client.put_object(
                        Bucket=s3_manager.bucket_name,
                        Key=temp_key,
                        Body=f
                    )
                
                # Process with Textract
                result = textract.process_document_s3(
                    s3_bucket=s3_manager.bucket_name,
                    s3_key=temp_key
                )
                
                if result and result.get('text'):
                    return {
                        'status': 'success',
                        'text': result['text'],
                        'metadata': result.get('metadata', {}),
                        'method': 'textract',
                        'page_count': result.get('metadata', {}).get('page_count', 1)
                    }
                else:
                    return {
                        'status': 'error',
                        'error': 'Textract processing failed'
                    }
                    
            finally:
                # Clean up temp file
                try:
                    s3_manager.s3_client.delete_object(
                        Bucket=s3_manager.bucket_name,
                        Key=temp_key
                    )
                except:
                    pass
    
    except Exception as e:
        logger.error(f"OCR extraction failed: {e}")
        return {
            'status': 'error',
            'error': str(e)
        }