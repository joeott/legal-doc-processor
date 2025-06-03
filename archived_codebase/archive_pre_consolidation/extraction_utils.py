# extraction_utils.py
import os
import logging
import re
from typing import Tuple

logger = logging.getLogger(__name__)

# === Solution 5: Document Validation ===
def validate_extraction(text: str | None, file_name: str, page_count: int) -> Tuple[bool, str]:
    """Validate extraction quality"""
    if not text:
        return False, "No text extracted"
    
    # Remove artifacts for validation
    clean_text = text.replace('<|im_end|>', '').strip()
    
    # Check minimum length based on document type
    min_chars_per_page = {
        'tax': 500,
        'legal': 300,
        'email': 200,
        'death': 800,
        'default': 100
    }
    
    doc_type = detect_document_type(file_name)
    expected_min = min_chars_per_page.get(doc_type, min_chars_per_page['default'])
    expected_total = expected_min * page_count
    
    if len(clean_text) < expected_total * 0.5:  # Allow 50% threshold
        return False, f"Extracted only {len(clean_text)} chars, expected ~{expected_total}"
    
    # Check for common extraction failures
    if clean_text.strip() in ['y', 'EXHIBIT V', '']:
        return False, "Extraction appears incomplete"
    
    # Check for excessive artifacts
    if clean_text.count('<|im_end|>') > page_count * 2:  # Arbitrary threshold
        return False, "Too many OCR artifacts detected"
    
    return True, "Valid extraction"

# === Solution 6: File Validation ===
VALID_EXTENSIONS = {'.pdf', '.docx', '.txt', '.eml', '.msg'}
SKIP_FILES = {'.DS_Store', 'Thumbs.db', '.gitignore', 'desktop.ini'}

def should_process_file(file_path: str) -> bool:
    """Determine if file should be processed"""
    file_name = os.path.basename(file_path)
    
    # Skip system files
    if file_name in SKIP_FILES:
        logger.info(f"Skipping system file: {file_name}")
        return False
    
    # Check extension
    ext = os.path.splitext(file_name)[1].lower()
    if ext not in VALID_EXTENSIONS:
        logger.info(f"Skipping unsupported file type: {file_name} (extension: {ext})")
        return False
    
    # Check file size (skip empty files)
    try:
        if os.path.getsize(file_path) < 100:  # bytes
            logger.info(f"Skipping empty file: {file_name} (size: {os.path.getsize(file_path)} bytes)")
            return False
    except OSError:
        logger.warning(f"Cannot access file size: {file_name}")
        return False
    
    return True

def detect_document_type(file_name: str) -> str:
    """Detect document type from filename"""
    if not file_name:
        return 'default'
    
    name_lower = file_name.lower()
    
    if any(term in name_lower for term in ['tax', '1040', '1065', 'w2', 'form', 'schedule']):
        return 'tax'
    elif any(term in name_lower for term in ['death', 'certificate', 'birth', 'marriage']):
        return 'certificate'
    elif any(term in name_lower for term in ['email', 'eml', 'msg', 'gmail', 'yahoo']):
        return 'email'
    elif any(term in name_lower for term in ['affidavit', 'complaint', 'motion', 'order', 'judgment', 'plea']):
        return 'legal'
    elif any(term in name_lower for term in ['receipt', 'payment', 'invoice', 'bill']):
        return 'financial'
    elif any(term in name_lower for term in ['deed', 'title', 'mortgage']):
        return 'property'
    else:
        return 'default'
    
# === Processing Monitor ===
import time

class ProcessingMonitor:
    def __init__(self, timeout_minutes=10):
        self.timeout = timeout_minutes * 60
        self.start_time = None
        self.page_times = []
        self.document_name = None
        
    def start_document(self, document_name: str, page_count: int):
        self.start_time = time.time()
        self.page_times = []
        self.document_name = document_name
        self.page_count = page_count
        logger.info(f"Starting processing of {document_name} ({page_count} pages)")
        
    def complete_page(self, page_num: int):
        elapsed = time.time() - self.start_time
        self.page_times.append(elapsed)
        
        # Estimate remaining time
        avg_page_time = elapsed / page_num if page_num > 0 else elapsed
        estimated_total = avg_page_time * self.page_count
        remaining_time = estimated_total - elapsed
        
        logger.info(f"Page {page_num}/{self.page_count} completed. "
                   f"Estimated remaining time: {remaining_time:.1f}s")
        
        if estimated_total > self.timeout:
            raise TimeoutError(f"Document processing estimated to take {estimated_total}s, "
                             f"exceeding timeout of {self.timeout}s")
        
    def should_continue(self) -> bool:
        if time.time() - self.start_time > self.timeout:
            logger.error(f"Timeout exceeded for {self.document_name}")
            return False
        return True
    
    def get_processing_time(self) -> float:
        if self.start_time:
            return time.time() - self.start_time
        return 0.0