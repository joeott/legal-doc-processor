# Context 233: Textract Async API and Database Operations Clarification

## Overview
This document clarifies the relationship between AWS Textract's asynchronous API for PDF processing and our synchronous database operations.

## Textract's Two Processing Models

### 1. Synchronous API (NOT used for PDFs)
- `analyze_document()` - For single-page images only
- Returns results immediately
- Not applicable to our PDF-only system

### 2. Asynchronous API (Used for PDFs)
- `start_document_text_detection()` - Submits PDF for processing
- Returns job ID immediately
- `get_document_text_detection()` - Polls for results

## How It Works in Our System

### The Async Part (Textract API)
```python
# Step 1: Submit PDF to Textract (returns immediately with job ID)
response = self.client.start_document_text_detection(
    DocumentLocation={'S3Object': {'Bucket': bucket, 'Name': key}}
)
job_id = response['JobId']

# Step 2: Poll for results (async operation)
while True:
    response = self.client.get_document_text_detection(JobId=job_id)
    if response['JobStatus'] in ['SUCCEEDED', 'FAILED']:
        break
    time.sleep(polling_interval)
```

### The Sync Part (Database Operations)
```python
# These database operations are SYNCHRONOUS
# They happen within the Textract processing flow

# When submitting job
self.db_manager.create_textract_job_entry(
    job_id=job_id,
    source_document_id=source_doc_id,
    # ... other fields
)

# When polling/updating status
self.db_manager.update_textract_job_status(job_id, 'in_progress')

# When complete
self.db_manager.update_source_document_with_textract_outcome(
    source_doc_sql_id=source_doc_id,
    textract_job_status='succeeded'
)
```

## Key Understanding

1. **Textract API Calls**: Asynchronous for PDFs (submit job, poll for results)
2. **Database Operations**: Synchronous SQLAlchemy calls
3. **Celery Task Context**: The entire flow runs within a Celery task

## The Complete Flow

```python
@celery.task
def process_pdf_with_textract(document_uuid: str, s3_path: str):
    """This is a Celery task (async at scheduling level)"""
    
    # Initialize synchronous database manager
    db = DatabaseManager()
    textract = TextractProcessor(db)
    
    # Step 1: Submit to Textract (async API, but synchronous Python call)
    job_id = textract.start_document_text_detection(
        s3_bucket=bucket,
        s3_key=key,
        source_doc_id=doc_id,
        document_uuid_from_db=document_uuid
    )
    # This includes SYNCHRONOUS database writes
    
    # Step 2: Poll for results (async API, synchronous polling loop)
    blocks, metadata = textract.get_text_detection_results(
        job_id=job_id,
        source_doc_id=doc_id
    )
    # This includes SYNCHRONOUS database updates during polling
    
    # Step 3: Process results with SYNCHRONOUS database operations
    db.update_document_status(document_uuid, ProcessingStatus.COMPLETED)
```

## Why Synchronous Database Operations Are Correct

1. **Boto3 Client**: The AWS SDK (boto3) handles the async API synchronously from Python's perspective
2. **Polling Pattern**: We use a synchronous polling loop with `time.sleep()`
3. **Database Writes**: All database operations are point-in-time updates, not long-running operations
4. **Celery Context**: The task itself provides the concurrency layer

## Common Misconception

**Incorrect assumption**: "Textract is async, so database operations must be async"

**Reality**: 
- Textract API is asynchronous (job-based)
- Python/boto3 interaction is synchronous (we wait for responses)
- Database operations are synchronous (quick writes/updates)
- Celery provides the concurrency (multiple tasks running in parallel)

## Benefits of This Approach

1. **Simplicity**: No async/await complexity in database or business logic
2. **Reliability**: Synchronous code is easier to debug and reason about
3. **Performance**: SQLAlchemy connection pooling handles concurrent access
4. **Compatibility**: Works perfectly with Celery's execution model

## Conclusion

The fact that Textract uses an asynchronous job-based API for PDFs does not require our database operations to be asynchronous. The synchronous approach we're using is the standard and correct pattern for Celery applications interacting with both async APIs and databases.