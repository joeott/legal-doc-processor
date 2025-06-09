# Context 393: Textract Scanned PDF Issue and Solution

## Issue Discovered
Date: 2025-06-04
Time: 20:50 UTC

### Problem
Textract is returning empty text (0 characters) for PDF documents, even though jobs complete successfully. Investigation reveals:

1. **Root Cause**: The PDFs are scanned documents (images) without embedded text
2. **Textract Response**: Only returns PAGE and LAYOUT_FIGURE blocks, no LINE or WORD blocks
3. **Current Implementation Gap**: The code expects embedded text but these are image-based PDFs

### Evidence
```
Testing direct boto3 client...
   - detect_document_text blocks: 1
   - No LINE blocks found - trying analyze_document
   - analyze_document blocks: 1
   - Block types:
     PAGE: 1
     LAYOUT_FIGURE: 1
```

### Solution Options

#### Option 1: PDF to Image Conversion (Recommended)
Convert PDF pages to images first, then process with Textract:
```python
# 1. Convert PDF to images
images = convert_pdf_to_images(pdf_path)

# 2. Process each image with Textract
for image in images:
    result = textract.detect_document_text(image)
```

#### Option 2: Use Async Textract with Image Processing
Start async jobs that handle image extraction:
```python
# Use start_document_analysis instead of start_document_text_detection
response = textract.start_document_analysis(
    DocumentLocation={'S3Object': {'Bucket': bucket, 'Name': key}},
    FeatureTypes=['TABLES', 'FORMS'],  # Forces deeper analysis
)
```

#### Option 3: Fallback to Tesseract
Already implemented but needs S3 download capability.

### Implementation Plan

1. **Immediate Fix**: Update `textract_utils.py` to detect image-only PDFs and handle appropriately
2. **PDF Conversion**: Add PDF to image conversion before Textract processing
3. **Update Polling Logic**: Already fixed to handle empty text properly

### Code Changes Made
1. Fixed polling logic in `pdf_tasks.py` line 1998:
   ```python
   # Changed from: if extracted_text:
   # To: if extracted_text is not None:
   ```
   This prevents infinite polling when text is empty but job is complete.

### Next Steps
1. Implement PDF to image conversion in textract_utils.py
2. Update start_document_text_detection to handle scanned PDFs
3. Add logging to identify scanned vs text PDFs early

### Testing Command
```bash
# Test single document with scanned PDF
cd /opt/legal-doc-processor
source load_env.sh
python3 process_test_document.py /path/to/scanned.pdf
```