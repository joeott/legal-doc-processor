#!/usr/bin/env python3
"""
Quick fix to force Textract async-only processing.
Disables scanned PDF detection and fallbacks.
"""

import os
import sys
sys.path.insert(0, '/opt/legal-doc-processor')

def apply_textract_fixes():
    """Apply immediate fixes to textract_utils.py"""
    
    # Read the current file
    with open('/opt/legal-doc-processor/scripts/textract_utils.py', 'r') as f:
        content = f.read()
    
    # Fix 1: Make _is_scanned_pdf always return False
    fix1 = """    def _is_scanned_pdf(self, s3_bucket: str, s3_key: str) -> bool:
        \"\"\"
        Detect if a PDF is scanned (image-only) by analyzing its content.
        Returns True if the PDF appears to be scanned/image-only.
        \"\"\"
        # PRODUCTION FIX: Always return False to force async processing
        return False
        
        if not ENABLE_SCANNED_PDF_DETECTION:
            return False"""
    
    # Fix 2: Disable Tesseract fallback in extract_with_fallback
    fix2_marker = "logger.warning(f\"Textract failed for {file_path}: {textract_error}, trying Tesseract\")"
    fix2_replacement = """logger.error(f"Textract failed for {file_path}: {textract_error}")
            # PRODUCTION FIX: Disabled Tesseract fallback
            raise RuntimeError(f"Textract processing failed: {textract_error}")
            """
    
    # Apply fixes
    if "# PRODUCTION FIX: Always return False" not in content:
        # Apply fix 1
        original = """    def _is_scanned_pdf(self, s3_bucket: str, s3_key: str) -> bool:
        \"\"\"
        Detect if a PDF is scanned (image-only) by analyzing its content.
        Returns True if the PDF appears to be scanned/image-only.
        \"\"\"
        if not ENABLE_SCANNED_PDF_DETECTION:
            return False"""
        
        content = content.replace(original, fix1)
        print("✅ Applied Fix 1: _is_scanned_pdf always returns False")
    
    if "# PRODUCTION FIX: Disabled Tesseract fallback" not in content and fix2_marker in content:
        # Find the try/except block for Tesseract
        start_idx = content.find(fix2_marker)
        if start_idx > 0:
            # Replace just the warning line with error + raise
            content = content.replace(
                fix2_marker,
                """logger.error(f"Textract failed for {file_path}: {textract_error}")
            # PRODUCTION FIX: Disabled Tesseract fallback
            raise RuntimeError(f"Textract processing failed: {textract_error}")
            # DISABLED: """ + fix2_marker
            )
        print("✅ Applied Fix 2: Disabled Tesseract fallback")
    
    # Write the fixed content
    with open('/opt/legal-doc-processor/scripts/textract_utils.py', 'w') as f:
        f.write(content)
    
    print("\n✅ Textract fixes applied successfully!")
    print("\nNext steps:")
    print("1. Set environment: export ENABLE_SCANNED_PDF_DETECTION=false")
    print("2. Restart Celery workers")
    print("3. Run batch performance test")

if __name__ == "__main__":
    apply_textract_fixes()