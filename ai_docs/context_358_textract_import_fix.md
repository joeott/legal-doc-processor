# Context 358: Textract Import Fix

## Issue Found
The `manual_poll_textract.py` script had an incorrect import statement trying to import `process_textract_blocks_to_text` as a standalone function from `textract_utils`, when it's actually a method of the `TextractProcessor` class.

## Error
```python
ImportError: cannot import name 'process_textract_blocks_to_text' from 'scripts.textract_utils'
```

## Root Cause
The function `process_textract_blocks_to_text` is defined as a method of the `TextractProcessor` class (line 365 in `textract_utils.py`), not as a standalone function that can be imported directly.

## Fix Applied
Changed line 40-41 in `manual_poll_textract.py` from:
```python
from scripts.textract_utils import process_textract_blocks_to_text
extracted_text = process_textract_blocks_to_text(blocks, metadata)
```

To:
```python
extracted_text = textract_processor.process_textract_blocks_to_text(blocks, metadata)
```

## Verification
- Checked other files for similar issues:
  - `pdf_tasks.py` - Already using it correctly as `textract_processor.process_textract_blocks_to_text()`
  - `ocr_extraction.py` - Already using it correctly as `textract_processor.process_textract_blocks_to_text()`
  
## Status
✓ Fixed - The import error in `manual_poll_textract.py` has been resolved.