# Context 358: Making original_file_name Optional Fix

## Issue
Validation error occurred because `original_file_name` field in SourceDocumentMinimal model was defined as required (non-Optional) but the data being processed had None/null values for this field.

## Solution Applied
Updated the `SourceDocumentMinimal` model in `/opt/legal-doc-processor/scripts/core/models_minimal.py`:

### Before:
```python
# Essential file info
original_file_name: str
file_name: Optional[str] = None  # Some code expects this
```

### After:
```python
# Essential file info
original_file_name: Optional[str] = None
file_name: Optional[str] = None  # Some code expects this
```

## Note on Full Schema Model
The full schema model in `/opt/legal-doc-processor/scripts/core/schemas.py` still has `original_file_name` as a required field (line 157):
```python
original_file_name: str = Field(..., description="Original filename")
```

This was NOT changed because:
1. The minimal models are specifically designed to bypass conformance issues
2. The full schema represents the ideal/complete data model
3. When using minimal models (USE_MINIMAL_MODELS=true), the system uses the relaxed validation

## Verification
The fix allows documents without original_file_name to be processed when using minimal models, preventing validation errors during document processing.