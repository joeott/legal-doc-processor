# Context 391: Confidence Score API Mismatch Analysis

## Date: 2025-01-06

## Issue Identified

There is an API mismatch in the `textract_utils.py` file where the `update_textract_job_status` method is being called with a `confidence_score` parameter that doesn't exist in the method signature.

### Location of Error
- **File**: `/opt/legal-doc-processor/scripts/textract_utils.py`
- **Line**: 596
- **Method Call**: 
```python
self.db_manager.update_textract_job_status(
    job_id, 
    'SUCCEEDED', 
    confidence_score=confidence,  # <-- INCORRECT PARAMETER NAME
    pages_processed=metadata['pages']
)
```

### Actual Method Signature
From `/opt/legal-doc-processor/scripts/db.py` (lines 688-700):
```python
def update_textract_job_status(
    self,
    job_id: str,
    status: str,
    error_message: Optional[str] = None,
    completed_at: Optional[datetime] = None,
    pages_processed: Optional[int] = None,
    page_count: Optional[int] = None,
    processed_pages: Optional[int] = None,
    avg_confidence: Optional[float] = None,  # <-- CORRECT PARAMETER NAME
    warnings_json: Optional[List[Any]] = None,
    completed_at_override: Optional[datetime] = None
) -> bool:
```

## Root Cause Analysis

1. **Historical Context**: The archived code in `supabase_utils.py` shows that the method originally used `avg_confidence` as the parameter name
2. **Inconsistent Refactoring**: When the textract functionality was updated or refactored, the parameter name was not consistently updated across all calling locations
3. **Database Schema**: The database likely has a column named `confidence_score` in the `textract_jobs` table, but the method parameter is `avg_confidence`

## Additional Instances to Check

There may be other locations with similar mismatches:

1. Line 596 in `textract_utils.py` (confirmed)
2. Potentially other calls to `update_textract_job_status` throughout the codebase
3. Any references to confidence scoring in the Textract workflow

## Solution

### Immediate Fix
Change line 596 in `textract_utils.py` from:
```python
confidence_score=confidence,
```
to:
```python
avg_confidence=confidence,
```

### Additional Verification Needed
1. Check if there are other calls to `update_textract_job_status` with incorrect parameter names
2. Verify that the database column name matches what's expected
3. Ensure consistency across the entire Textract processing pipeline

## Impact Assessment

- **Severity**: Medium - This prevents proper recording of OCR confidence scores
- **Scope**: Affects all Textract OCR processing
- **Data Loss**: Confidence scores are not being saved to the database
- **User Impact**: Unable to assess OCR quality metrics

## Testing After Fix

1. Process a document through Textract
2. Verify that confidence scores are properly saved to the database
3. Check that the `textract_jobs` table has confidence data
4. Ensure no other API mismatches exist in the pipeline

## Additional Findings

### Database Storage
The confidence value is stored in the `metadata` JSON field of the `textract_jobs` table as `avg_confidence`, not as a direct column. This is handled in the `update_textract_job_status` method (lines 727-743 in db.py).

### Other Calls Verified
I checked all other calls to `update_textract_job_status` in the codebase:
- Line 662: Only passes error_message ✓
- Line 673: Only passes error_message ✓
- Line 702: Only passes error_message ✓
- Line 740: Only passes status ✓
- Line 775: Correctly uses `avg_confidence` ✓
- Line 800: Passes multiple params including error_message and warnings_json ✓
- Lines 821, 833: Pass error_message ✓

### Conclusion
Only line 596 has the incorrect parameter name. All other calls are correct.