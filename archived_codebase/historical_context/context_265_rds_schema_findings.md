# Context 265: RDS Schema Findings and Column Mapping Corrections

## Date: May 31, 2025
## Issue: Column mapping corrections needed based on actual RDS schema

## Actual RDS Schema Analysis

### source_documents table structure:
- **Primary Key**: `id` (integer, auto-incrementing)
- **UUID Field**: `document_uuid` (uuid) - this is NOT the primary key
- **File Info**: `original_filename`, `file_path`, `file_size_bytes`, `detected_file_type`
- **S3 Info**: `s3_bucket`, `s3_key`, `s3_region`
- **Status Fields**: `processing_status`, `initial_processing_status`, `celery_status`
- **Content**: `raw_extracted_text`, `markdown_text`, `cleaned_text`
- **Metadata**: `ocr_metadata_json`, `transcription_metadata_json` (JSONB)
- **Timestamps**: `created_at`, `updated_at`, `ocr_completed_at`

## Key Corrections Needed

### 1. Primary Key Mapping Issue
**WRONG**: 
```python
"document_uuid": "source_document_id"  # This column doesn't exist!
```

**CORRECT**:
```python
"document_uuid": "document_uuid"  # Map to actual UUID field
# Primary key (id) should be auto-generated, don't map it
```

### 2. File Size Field
**WRONG**: `file_size_bytes` → `file_size`
**CORRECT**: `file_size_bytes` → `file_size_bytes`

### 3. Metadata Structure
The RDS has separate JSONB fields:
- `ocr_metadata_json` - for OCR-specific metadata
- `transcription_metadata_json` - for transcription metadata

Our code tries to map everything to `metadata` and `processing_metadata` which don't exist.

### 4. Missing Required Fields
The Pydantic models expect some fields that map to multiple RDS columns or don't exist:
- `mime_type` doesn't exist (should use `detected_file_type`)
- `status` is ambiguous (could be `processing_status`, `initial_processing_status`, or `celery_status`)

## Solution Strategy

### Phase 1: Fix Core Mappings
Update `enhanced_column_mappings.py` to use actual RDS column names:

```python
"source_documents": {
    # Core identification
    "document_uuid": "document_uuid",  # Keep UUID mapping direct
    # Don't map primary key - let it auto-generate
    
    # File information
    "original_file_name": "original_filename",
    "file_size_bytes": "file_size_bytes", 
    "detected_file_type": "detected_file_type",
    
    # S3 storage
    "s3_key": "s3_key",
    "s3_bucket": "s3_bucket", 
    "s3_region": "s3_region",
    
    # Status (choose one primary mapping)
    "processing_status": "processing_status",
    "initial_processing_status": "initial_processing_status", 
    "celery_status": "celery_status",
    
    # Content
    "raw_extracted_text": "raw_extracted_text",
    "markdown_text": "markdown_text",
    
    # Metadata - use actual JSONB fields
    "ocr_metadata_json": "ocr_metadata_json",
    "transcription_metadata_json": "transcription_metadata_json",
    
    # Timestamps
    "created_at": "created_at",
    "updated_at": "updated_at",
    "ocr_completed_at": "ocr_completed_at"
}
```

### Phase 2: Handle Complex Mappings
For fields that don't have direct mappings, we need to:
1. Update Pydantic models to match RDS schema
2. Or create computed/derived mappings
3. Handle the metadata consolidation properly

## Implementation Plan

1. **Fix column mappings** - Use actual RDS column names
2. **Test schema alignment** - Ensure basic CRUD works
3. **Update Pydantic models** - Align with RDS reality
4. **Re-run tests** - Verify end-to-end functionality

This will resolve the "column does not exist" errors and get us closer to a working pipeline.