# Context 403: Production Pipeline Fix Plan

**Date**: June 5, 2025  
**Time**: 01:45 AM UTC  
**Status**: CRITICAL FIX REQUIRED  
**Issue**: Production pipeline uploads documents to S3 but fails to create database records or trigger processing

## Root Cause Analysis

The production pipeline is failing because of a critical architectural mismatch:

1. **Current Flow (Broken)**:
   - `production_processor.py` discovers documents
   - Documents are uploaded to S3 via `intake_service.py`
   - `batch_processor.py` generates NEW UUIDs for documents (line 195)
   - Celery tasks are submitted with these new UUIDs
   - **PROBLEM**: No database records exist for these UUIDs
   - OCR task fails validation check: "Document not found in database"

2. **Expected Flow**:
   - Documents should be created in the database FIRST
   - Database assigns the document UUID
   - S3 upload uses the database UUID in the path
   - Celery tasks use the existing database UUID

## Evidence Found

### 1. Batch Processor Issue
```python
# scripts/batch_processor.py:195
document_uuid = str(uuid.uuid4())  # Generate new UUID for processing
```
This generates a UUID without creating a database record.

### 2. OCR Task Validation
```python
# scripts/pdf_tasks.py:781-782
if not validate_document_exists(self.db_manager, document_uuid):
    raise ValueError(f"Document {document_uuid} not found in database")
```
The OCR task requires the document to exist in the database.

### 3. Current State
- 406 documents uploaded to S3 (path: `documents/2025/06/05/`)
- 0 documents created in database on June 5
- All June 4 documents show "N/A_START_FAILURE" for Textract

## Proposed Solution

### Phase 1: Fix the Batch Processor

Modify `batch_processor.py` to create database records before submitting tasks:

```python
def submit_batch_for_processing(self, batch: BatchManifest) -> BatchJobId:
    """Submit a batch for processing via Celery."""
    logger.info(f"Submitting batch {batch.batch_id} for processing")
    
    # Create database manager
    db_manager = DatabaseManager(validate_conformance=False)
    
    # Create Celery task chains for each document
    task_chains = []
    celery_task_ids = []
    
    for doc in batch.documents:
        # CREATE DATABASE RECORD FIRST
        with db_manager.get_session() as session:
            # Create document in database
            document_uuid = create_document_record(
                session,
                original_filename=doc.get('filename'),
                s3_bucket=doc.get('s3_bucket'),
                s3_key=doc.get('s3_key'),
                file_size_mb=doc.get('file_size_mb'),
                mime_type=doc.get('mime_type')
            )
            
        # Now use the database UUID for tasks
        s3_url = f"s3://{doc.get('s3_bucket')}/{doc.get('s3_key')}"
        
        # Create processing chain with EXISTING document UUID
        processing_chain = chain(
            app.signature('scripts.pdf_tasks.extract_text_from_document', 
                         args=[document_uuid, s3_url]),
            # ... rest of chain
        )
```

### Phase 2: Create Helper Function

Add a database record creation function:

```python
def create_document_record(session, original_filename, s3_bucket, s3_key, 
                          file_size_mb, mime_type):
    """Create a source_documents record and return the UUID."""
    from scripts.models import SourceDocumentMinimal
    from sqlalchemy import text
    
    # Generate UUID
    document_uuid = str(uuid.uuid4())
    
    # Create record using direct SQL (to avoid model issues)
    session.execute(text("""
        INSERT INTO source_documents (
            document_uuid, original_file_name, s3_bucket, s3_key,
            file_size_mb, mime_type, upload_timestamp, created_at
        ) VALUES (
            :uuid, :filename, :bucket, :key, :size, :mime, NOW(), NOW()
        )
    """), {
        'uuid': document_uuid,
        'filename': original_filename,
        'bucket': s3_bucket,
        'key': s3_key,
        'size': file_size_mb,
        'mime': mime_type
    })
    session.commit()
    
    return document_uuid
```

### Phase 3: Update Document Tracking

Ensure documents are tracked properly in the batch:

```python
# Store the database UUID back in the document dict
doc['document_uuid'] = document_uuid

# Update Redis tracking to use the correct UUID
self._initialize_batch_progress_tracking(batch)
```

### Phase 4: Fix S3 Key Structure

The S3 keys should include the document UUID for consistency:

```python
# In intake_service.py upload method
def generate_s3_key(self, filename: str, document_uuid: str = None) -> str:
    """Generate S3 key with proper structure."""
    date_path = datetime.now().strftime('%Y/%m/%d')
    file_hash = hashlib.md5(filename.encode()).hexdigest()[:8]
    
    if document_uuid:
        # Use document UUID in path
        return f"documents/{document_uuid}/{filename}"
    else:
        # Fallback to date-based path
        return f"documents/{date_path}/{file_hash}_{filename}"
```

## Implementation Steps

1. **Backup Current Code**
   ```bash
   cp scripts/batch_processor.py scripts/batch_processor.py.backup
   ```

2. **Implement Database Record Creation**
   - Add `create_document_record` function to batch_processor.py
   - Modify `submit_batch_for_processing` to create records first

3. **Test with Single Document**
   - Process one document through the fixed pipeline
   - Verify database record creation
   - Verify OCR task starts successfully

4. **Process Full Directory**
   - Run the production processor on the full input directory
   - Monitor database record creation
   - Track processing through all stages

## Alternative Quick Fix (Not Recommended)

If we need a quick workaround without modifying code:

1. Create a script to manually create database records for uploaded S3 files
2. Map S3 keys to document UUIDs
3. Submit processing tasks manually

However, this is error-prone and doesn't fix the root issue.

## Verification Checklist

After implementing the fix:

- [ ] Database records created for each document
- [ ] Document UUIDs match between database and Celery tasks
- [ ] OCR tasks start without "document not found" errors
- [ ] Redis tracking uses correct document UUIDs
- [ ] Processing progresses through all pipeline stages
- [ ] No orphaned S3 files without database records

## Risk Assessment

- **Low Risk**: Changes are localized to batch_processor.py
- **High Impact**: Fixes critical pipeline blocking issue
- **Testing Required**: Must test with small batch first

## Conclusion

The production pipeline architecture assumes documents exist in the database before processing begins. The current implementation skips this crucial step. By ensuring database records are created before submitting Celery tasks, we can restore the pipeline to working order.

This is a **CRITICAL** fix that must be implemented before any further production processing attempts.