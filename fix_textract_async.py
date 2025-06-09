#!/usr/bin/env python3
"""
Fix Textract to use async processing for all PDFs.
This bypasses the scanned detection and PDF conversion issues.
"""

import os
import sys
sys.path.insert(0, '/opt/legal-doc-processor')

# Force async processing for all PDFs
os.environ['TEXTRACT_FORCE_ASYNC'] = 'true'
os.environ['SKIP_SCANNED_DETECTION'] = 'true'

print("Configured environment for async Textract processing:")
print(f"  TEXTRACT_FORCE_ASYNC = {os.environ.get('TEXTRACT_FORCE_ASYNC')}")
print(f"  SKIP_SCANNED_DETECTION = {os.environ.get('SKIP_SCANNED_DETECTION')}")
print("\nRestart workers to apply changes.")