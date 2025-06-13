# Context 358: Textract Database Methods Fix

## Date: 2025-01-06

## Issue Identified
The `DatabaseManager` class was missing several methods that the `TextractProcessor` class was trying to call:
- `create_textract_job_entry()`
- `get_textract_job_by_job_id()`
- `update_textract_job_status()`
- `update_source_document_with_textract_outcome()`

## Root Cause
The Textract functionality was added to the system but the corresponding database methods were not implemented in the `DatabaseManager` class. This caused AttributeError when TextractProcessor tried to interact with the database.

## Solution Implemented

### 1. Added Missing Methods to DatabaseManager

Added the following methods to `/opt/legal-doc-processor/scripts/db.py`:

#### create_textract_job_entry()
```python
def create_textract_job_entry(
    self,
    source_document_id: int,
    document_uuid: uuid.UUID,
    job_id: str,
    s3_input_bucket: str,
    s3_input_key: str,
    job_type: str = 'DetectDocumentText',
    s3_output_bucket: Optional[str] = None,
    s3_output_key: Optional[str] = None,
    client_request_token: Optional[str] = None,
    job_tag: Optional[str] = None,
    job_status: str = 'IN_PROGRESS'
) -> Optional[TextractJobModel]:
    """Create a Textract job entry in the database."""
```

#### get_textract_job_by_job_id()
```python
def get_textract_job_by_job_id(self, job_id: str) -> Optional[Dict[str, Any]]:
    """Get Textract job by job ID."""
```

#### update_textract_job_status()
```python
def update_textract_job_status(
    self,
    job_id: str,
    status: str,
    error_message: Optional[str] = None,
    completed_at: Optional[datetime] = None,
    pages_processed: Optional[int] = None
) -> bool:
    """Update Textract job status."""
```

#### update_source_document_with_textract_outcome()
```python
def update_source_document_with_textract_outcome(
    self,
    source_doc_sql_id: int,
    textract_job_id: str,
    textract_job_status: str,
    raw_text: Optional[str] = None,
    markdown_text: Optional[str] = None,
    ocr_metadata: Optional[Dict[str, Any]] = None
) -> bool:
    """Update source document with Textract processing results."""
```

## Implementation Details

1. **create_textract_job_entry**: Creates a new TextractJobModel instance and inserts it into the textract_jobs table
2. **get_textract_job_by_job_id**: Retrieves a Textract job record by its AWS job ID
3. **update_textract_job_status**: Updates the status and metadata of an existing Textract job
4. **update_source_document_with_textract_outcome**: Updates the source document record with OCR results from Textract

All methods follow the existing pattern in DatabaseManager:
- Use the pydantic_db interface for model-based operations
- Use rds_utils for direct database updates
- Proper error handling with logging
- Return appropriate types (models, dictionaries, or booleans)

## Testing Required

After implementing these methods, the following should be tested:
1. Document upload and OCR processing flow
2. Textract job creation and tracking
3. Status updates during processing
4. Final result storage in source_documents table

## Next Steps

1. Test the complete OCR pipeline with a real document
2. Verify that Textract jobs are properly tracked in the database
3. Ensure status updates propagate correctly
4. Check that OCR results are stored in source documents