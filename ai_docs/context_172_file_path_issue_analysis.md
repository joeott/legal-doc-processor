# Context 172: File Path Issue Root Cause Analysis & Solution

## Date: 2025-05-28

## Executive Summary

The file path issue causing "File not found" errors stems from inconsistent handling of S3 paths throughout the pipeline. Documents stored in S3 with UUID-based naming are failing OCR because the system passes S3 keys without proper prefixes, causing the OCR function to treat them as local paths.

## Root Cause Analysis

### The Issue Chain

1. **Document Upload & Storage**
   - Files are uploaded to S3 with UUID-based naming: `documents/{document_uuid}.{extension}`
   - The S3 key is stored in `source_documents.s3_key` field
   - Example: `documents/1d4282be-6a1a-4c03-829d-8dfdce34828a.pdf`

2. **Task Submission**
   - When submitting to Celery, the code uses: `file_path=doc.get('s3_key', doc['original_file_path'])`
   - This passes just the S3 key (e.g., `documents/uuid.pdf`) without the bucket prefix
   - The OCR task receives this bare key as the `file_path` parameter

3. **OCR Path Resolution**
   - `extract_text_from_pdf_textract()` checks for various path patterns:
     - `s3://` - Recognized as S3 URI
     - `supabase://` - Recognized as Supabase storage
     - `http://` or `https://` - Recognized as web URLs
     - Otherwise uses `os.path.exists()` for local files
   - The bare S3 key doesn't match any pattern, falls through to local file check
   - `os.path.exists('documents/uuid.pdf')` returns False
   - Results in "File not found" error

### Code Flow

```python
# In submit_documents_batch.py and similar:
file_path=doc.get('s3_key', doc['original_file_path'])  # Returns: "documents/uuid.pdf"

# In ocr_extraction.py:
if pdf_path_or_s3_uri.startswith('s3://'):  # False
    # Handle S3
elif pdf_path_or_s3_uri.startswith('supabase://'):  # False
    # Handle Supabase
elif pdf_path_or_s3_uri.startswith(('http://', 'https://')):  # False
    # Handle URLs
elif os.path.exists(pdf_path_or_s3_uri):  # False - not a local file!
    # Handle local files
else:
    # ERROR: "File not found: documents/uuid.pdf"
```

## Proposed Solution

### Option 1: Fix at Submission Point (Recommended)

Modify all task submission code to construct proper S3 URIs when S3 keys are present:

```python
# In submit_documents_batch.py and similar files:
if doc.get('s3_key'):
    # Construct full S3 URI
    file_path = f"s3://{S3_PRIMARY_DOCUMENT_BUCKET}/{doc['s3_key']}"
else:
    # Fall back to original file path for local files
    file_path = doc['original_file_path']

task = process_ocr.delay(
    document_uuid=doc['document_uuid'],
    source_doc_sql_id=doc['id'],
    file_path=file_path,  # Now includes s3:// prefix when appropriate
    file_name=doc['original_file_name'],
    detected_file_type=doc.get('detected_file_type', 'pdf'),
    project_sql_id=doc['project_fk_id']
)
```

### Option 2: Enhanced Path Detection in OCR

Add logic to detect S3 keys and construct URIs automatically:

```python
# In ocr_extraction.py, before the existing checks:
# Check if it looks like an S3 key (starts with known prefixes)
if (pdf_path_or_s3_uri.startswith('documents/') or 
    pdf_path_or_s3_uri.startswith('uploads/') or
    pdf_path_or_s3_uri.startswith('processed/')):
    # Likely an S3 key, construct full URI
    s3_bucket_name = S3_PRIMARY_DOCUMENT_BUCKET
    s3_object_key = pdf_path_or_s3_uri
    logger.info(f"Detected S3 key pattern, constructing URI: s3://{s3_bucket_name}/{s3_object_key}")
elif pdf_path_or_s3_uri.startswith('s3://'):
    # Already a full S3 URI
    ...
```

### Option 3: Database-Driven Path Resolution

Use the database to determine the correct path:

```python
# In ocr_extraction.py:
# If path doesn't match any pattern, check database for S3 info
if not any_pattern_matched:
    # Query source_documents for S3 details
    doc_info = db_manager.client.table('source_documents').select(
        's3_key', 's3_bucket', 'original_file_path'
    ).eq('id', source_doc_sql_id).execute()
    
    if doc_info.data and doc_info.data[0].get('s3_key'):
        s3_bucket = doc_info.data[0].get('s3_bucket', S3_PRIMARY_DOCUMENT_BUCKET)
        s3_key = doc_info.data[0]['s3_key']
        pdf_path_or_s3_uri = f"s3://{s3_bucket}/{s3_key}"
        logger.info(f"Resolved path from database: {pdf_path_or_s3_uri}")
```

## Recommended Implementation Plan

### Phase 1: Immediate Fix (Option 1)
1. Update `submit_documents_batch.py` to construct S3 URIs
2. Update any other task submission code similarly
3. Search for all `process_ocr.delay` calls and fix path construction

### Phase 2: Robust Path Handling (Option 2)
1. Add S3 key pattern detection in `ocr_extraction.py`
2. Log warnings when bare S3 keys are detected
3. Gradually migrate to always using full URIs

### Phase 3: Long-term Architecture
1. Standardize on always storing full S3 URIs in database
2. Create a centralized `FilePathResolver` class
3. Implement consistent path handling across all modules

## File Organization Strategy

### Current State
- Files uploaded with UUID names: `documents/{uuid}.{ext}`
- Original names preserved in `original_file_name` field
- No case association at upload time

### Future State (Post-Processing)
1. **Initial Storage**: `staging/{uuid}.{ext}`
2. **After OCR/Classification**: `cases/{case_id}/{doc_type}/{date}_{name}.{ext}`
3. **Unclassified**: `unclassified/{date}/{uuid}.{ext}`

### Migration Workflow
```python
async def post_process_document(document_uuid: str):
    """Move document to appropriate location after processing"""
    # Get processing results
    doc = get_document_with_entities(document_uuid)
    
    # Determine case association
    case = determine_case_association(doc.entities, doc.extracted_text)
    
    if case:
        # Move to case folder
        new_key = f"cases/{case.id}/{doc.type}/{doc.date}_{doc.name}"
        s3_client.copy_object(
            CopySource={'Bucket': bucket, 'Key': doc.s3_key},
            Bucket=bucket,
            Key=new_key
        )
        # Update database with new location
        update_document_location(document_uuid, new_key)
        # Delete old object
        s3_client.delete_object(Bucket=bucket, Key=doc.s3_key)
    else:
        # Queue for manual review
        queue_for_manual_classification(document_uuid)
```

## Benefits of UUID-Based Initial Storage

1. **Fast Upload**: No need to determine case at upload time
2. **Unique Names**: Prevents overwrites and conflicts
3. **Easy Search**: Can find any document by UUID instantly
4. **Batch Processing**: Can process documents asynchronously
5. **Audit Trail**: Original upload location preserved

## Implementation Checklist

- [ ] Fix path construction in `submit_documents_batch.py`
- [ ] Fix path construction in monitor retry functionality
- [ ] Fix path construction in test scripts
- [ ] Add S3 key pattern detection to `ocr_extraction.py`
- [ ] Update documentation with path handling guidelines
- [ ] Create unit tests for path resolution
- [ ] Implement post-processing document organization
- [ ] Create manual classification queue/interface

## Testing Strategy

1. **Unit Tests**: Test path resolution with various inputs
2. **Integration Tests**: Test full OCR flow with S3 documents
3. **Edge Cases**: Test mixed paths, missing S3 keys, etc.

## Monitoring & Debugging

Add detailed logging at each path resolution point:
```python
logger.info(f"Path resolution: input='{file_path}', type=detected_type, resolved='{resolved_path}'")
```

## Success Criteria

1. All documents with S3 keys process successfully
2. No "File not found" errors for existing S3 documents
3. Clear audit trail of path resolution decisions
4. Smooth migration to organized folder structure

This comprehensive solution addresses both the immediate issue and provides a path forward for the intelligent document organization system requested.