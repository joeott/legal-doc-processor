# Context 358: Textract Job Manager Import Fix

## Issue
The error "No module named 'scripts.textract_job_manager'" was occurring in `pdf_tasks.py` because the code was trying to import a non-existent module.

## Root Cause
In the `poll_textract_job` function (around line 1100), the code was attempting to:
```python
from scripts.textract_job_manager import get_job_manager
job_manager = get_job_manager()
```

However, this module doesn't exist in the codebase.

## Solution
Replaced the non-existent `textract_job_manager` with the actual `TextractProcessor` from `textract_utils.py`:

1. **Import changes**: Changed from importing non-existent module to:
   ```python
   from scripts.textract_utils import TextractProcessor
   ```

2. **Logic changes**:
   - Get source document ID from database first
   - Initialize TextractProcessor with database manager
   - Use `get_text_detection_results()` method which handles polling internally
   - Use `process_textract_blocks_to_text()` to convert blocks to text
   - Fixed all references to use the actual extracted text and metadata

3. **Error handling**: Updated to check job status from database when no blocks are returned

## Files Modified
- `/opt/legal-doc-processor/scripts/pdf_tasks.py` - Fixed import and logic in `poll_textract_job` function

## Verification
- Syntax check passed
- No remaining references to `textract_job_manager` in the codebase
- The function now properly uses the existing TextractProcessor class

## Status
✅ Import error fixed - the code now uses the correct existing modules instead of trying to import a non-existent one.