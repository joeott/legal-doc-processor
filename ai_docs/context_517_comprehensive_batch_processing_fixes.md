# Context 517: Comprehensive Batch Processing Fixes

## Date: 2025-06-12

### Executive Summary
Based on error analysis from the Paul Michael Acuity batch processing failure (0/10 documents completed), this document provides specific code modifications needed to fix three critical issues: function signature mismatches, memory overflow with large files, and circuit breaker blocking. All fixes have been identified with exact line numbers and code changes.

### Issue 1: Function Signature Mismatch in Cached Path

**Problem**: When using cached canonical entities, `build_document_relationships` is called with only 1 argument instead of required 6.

**Location**: `scripts/pdf_tasks.py`, lines 1784-1789

**Current Code** (BROKEN):
```python
# Lines 1784-1789
if cached_canonical:
    self.logger.info(f"Found {len(cached_canonical)} cached canonical entities")
    build_document_relationships.apply_async(
        args=[document_uuid],  # MISSING 5 ARGUMENTS!
        queue='graph'
    )
```

**Fixed Code** (CORRECTED):
```python
# Lines 1784-1820 (expanded)
if cached_canonical:
    self.logger.info(f"Found {len(cached_canonical)} cached canonical entities")
    
    # Retrieve all required data for relationship building
    # Get document data and project UUID from metadata
    metadata = self.redis_manager.get_document_metadata(document_uuid)
    if not metadata or 'project_uuid' not in metadata:
        self.logger.error(f"Missing metadata for document {document_uuid}")
        raise ValueError(f"Cannot proceed without project_uuid for document {document_uuid}")
    
    project_uuid = metadata['project_uuid']
    document_data = {
        'document_uuid': document_uuid,
        'file_name': metadata.get('file_name', ''),
        'project_uuid': project_uuid
    }
    
    # Get chunks from cache
    chunks = self.redis_manager.get_chunks(document_uuid)
    if not chunks:
        # Fallback to database
        chunks = self.db_manager.get_chunks_by_document(document_uuid)
        chunks = [chunk.dict() for chunk in chunks]
    
    # Get entity mentions
    entity_mentions = self.redis_manager.get_entity_mentions(document_uuid)
    if not entity_mentions:
        # Fallback to database
        mentions = self.db_manager.get_entity_mentions_by_document(document_uuid)
        entity_mentions = [mention.dict() for mention in mentions]
    
    # Ensure we have all required data
    if not chunks:
        raise ValueError(f"No chunks found for document {document_uuid}")
    if not entity_mentions:
        self.logger.warning(f"No entity mentions found for document {document_uuid}")
        entity_mentions = []
    
    # Trigger next stage with ALL required arguments
    build_document_relationships.apply_async(
        args=[document_uuid, document_data, project_uuid, chunks, entity_mentions, cached_canonical],
        queue='graph'
    )
```

### Issue 2: Memory Overflow with Large PDFs

**Problem**: Loading entire 584MB file into memory exceeds 512MB worker limit.

**Location**: Multiple locations in `scripts/pdf_tasks.py`

**Fix 1 - check_file_size()** (lines 664-684):
```python
# BEFORE (loads entire file):
response = s3_client.get_object(Bucket=bucket, Key=key)
pdf_bytes = response['Body'].read()  # MEMORY ERROR!

# AFTER (streaming):
from scripts.utils.s3_streaming import S3StreamingDownloader

downloader = S3StreamingDownloader()
file_size = downloader.get_file_size(bucket, key)
self.logger.info(f"S3 file size: {file_size:,} bytes ({file_size/(1024*1024):.1f} MB)")
return file_size
```

**Fix 2 - split_large_pdf()** (lines 705-845):
```python
# BEFORE (lines 788-791):
response = s3_client.get_object(Bucket=bucket, Key=key) 
pdf_bytes = response['Body'].read()  # MEMORY ERROR!
pdf_doc = fitz.open(stream=pdf_bytes, filetype="pdf")

# AFTER:
from scripts.utils.s3_streaming import S3StreamingDownloader

downloader = S3StreamingDownloader()
with downloader.download_to_temp(bucket, key) as temp_pdf_path:
    pdf_doc = fitz.open(temp_pdf_path)  # Opens from disk, not memory
    # ... rest of the function
```

**Fix 3 - Create s3_streaming.py**:
```python
# New file: scripts/utils/s3_streaming.py
import boto3
import tempfile
import os
from pathlib import Path
from typing import Optional, Generator
import logging

class S3StreamingDownloader:
    """Download large S3 files without loading into memory."""
    
    def __init__(self, chunk_size: int = 8 * 1024 * 1024):  # 8MB chunks
        self.chunk_size = chunk_size
        self.s3_client = boto3.client('s3')
        self.logger = logging.getLogger(__name__)
    
    def download_to_temp(self, bucket: str, key: str) -> Generator[str, None, None]:
        """Download S3 object to temporary file using streaming."""
        temp_file = None
        try:
            # Create temporary file
            temp_file = tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.pdf')
            temp_path = temp_file.name
            
            # Stream download
            response = self.s3_client.get_object(Bucket=bucket, Key=key)
            total_size = response['ContentLength']
            downloaded = 0
            
            # Download in chunks
            for chunk in response['Body'].iter_chunks(chunk_size=self.chunk_size):
                temp_file.write(chunk)
                downloaded += len(chunk)
                if downloaded % (50 * self.chunk_size) == 0:  # Log every 400MB
                    progress = (downloaded / total_size) * 100
                    self.logger.info(f"Download progress: {progress:.1f}% ({downloaded/(1024*1024):.1f}MB/{total_size/(1024*1024):.1f}MB)")
            
            temp_file.close()
            yield temp_path
            
        finally:
            # Cleanup
            if temp_file and not temp_file.closed:
                temp_file.close()
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)
    
    def get_file_size(self, bucket: str, key: str) -> int:
        """Get S3 object size without downloading."""
        response = self.s3_client.head_object(Bucket=bucket, Key=key)
        return response['ContentLength']
```

### Issue 3: Circuit Breaker Blocking Recovery

**Problem**: Circuit breaker blocks document for 5 minutes after 3 failures, preventing retry.

**Location**: `scripts/pdf_tasks.py`, lines 39-115 (DocumentCircuitBreaker class)

**Fix 1 - Add Manual Reset**:
```python
# Add to DocumentCircuitBreaker class (after line 115):
def reset(self, document_uuid: str):
    """Manually reset circuit breaker for a document."""
    with self.lock:
        if document_uuid in self.failure_counts:
            del self.failure_counts[document_uuid]
        if document_uuid in self.last_failure_times:
            del self.last_failure_times[document_uuid]
        if document_uuid in self.circuit_states:
            del self.circuit_states[document_uuid]
        self.logger.info(f"Circuit breaker reset for document {document_uuid}")

def get_state(self, document_uuid: str) -> dict:
    """Get current state for debugging."""
    with self.lock:
        return {
            'failures': self.failure_counts.get(document_uuid, 0),
            'state': self.circuit_states.get(document_uuid, 'CLOSED'),
            'last_failure': self.last_failure_times.get(document_uuid)
        }
```

**Fix 2 - Add File Size Check Before Processing**:
```python
# In extract_text_from_document, after line 985:
# Add size check before circuit breaker check
if 's3://' in file_path:
    bucket_name, key = file_path.replace('s3://', '').split('/', 1)
    file_size_mb = check_file_size(document_uuid, file_path) / (1024 * 1024)
    
    # Route large files differently
    if file_size_mb > 400:  # 400MB threshold
        self.logger.warning(f"Large file detected: {file_size_mb:.1f}MB. Using streaming approach.")
        # Set a flag for streaming processing
        document_data['large_file'] = True
        document_data['file_size_mb'] = file_size_mb
```

### Issue 4: Missing OCR Tasks for Some Documents

**Problem**: 13/20 documents never had OCR tasks created.

**Root Cause**: When batch submission fails partway through (due to memory/circuit breaker), remaining documents aren't queued.

**Fix - Add Batch Recovery** in `scripts/batch_tasks.py`:
```python
# Add after line 500 in process_batch_high/normal/low:
except Exception as e:
    self.logger.error(f"Batch processing error: {str(e)}")
    # Don't fail entire batch - continue with remaining documents
    failed_docs.append({
        'document_uuid': doc_uuid,
        'error': str(e),
        'stage': 'submission'
    })
    
    # Reset circuit breaker if it's blocking
    if "Circuit breaker OPEN" in str(e):
        from scripts.pdf_tasks import circuit_breaker
        circuit_breaker.reset(doc_uuid)
        self.logger.info(f"Reset circuit breaker for {doc_uuid}")
    
    continue  # Process next document
```

### Additional Improvements

1. **Add Worker Memory Monitoring** in `scripts/celery_app.py`:
```python
# After line 130:
# Configure different worker pools for different file sizes
app.conf.task_routes = {
    'scripts.pdf_tasks.process_large_pdf': {'queue': 'large_files'},
    'scripts.pdf_tasks.extract_text_from_document': {
        'queue': 'large_files' if 'large_file' in kwargs else 'ocr'
    }
}

# Add large file worker configuration
app.conf.worker_prefetch_multiplier = 1  # Prevent memory buildup
```

2. **Add Retry with Circuit Breaker Reset**:
```python
# In pdf_tasks.py, modify retry logic (line 1250):
except Exception as exc:
    # Record failure
    circuit_breaker.record_failure(document_uuid)
    
    # Check if we should retry
    if self.request.retries < self.max_retries:
        # If it's a memory error, reset circuit breaker and retry with streaming
        if isinstance(exc, MemoryError) or "MemoryError" in str(exc):
            circuit_breaker.reset(document_uuid)
            self.logger.info("Memory error detected - will retry with streaming")
            # Add streaming flag for retry
            kwargs['use_streaming'] = True
        
        raise self.retry(exc=exc, countdown=60)
```

### Testing the Fixes

1. **Test Function Signature Fix**:
```bash
# Process a document that has cached entities
python process_test_document.py "input_docs/Paul, Michael (Acuity)/Paul, Michael - Initial Disclosures - FINAL 1.27.25.pdf"
```

2. **Test Large File Handling**:
```bash
# Process the large WOMBAT file
python process_test_document.py "input_docs/Paul, Michael (Acuity)/WOMBAT 000454-000784.pdf"
```

3. **Test Circuit Breaker Reset**:
```python
# Reset circuit breaker for blocked document
from scripts.pdf_tasks import circuit_breaker
circuit_breaker.reset('d261a4c6-aa80-4281-b50e-5b71df8afa37')
```

### Summary of Changes

1. **pdf_tasks.py**:
   - Fix function call at lines 1784-1789 (add all 6 arguments)
   - Update check_file_size() to use streaming
   - Update split_large_pdf() to use streaming
   - Add reset() method to DocumentCircuitBreaker
   - Add file size routing logic

2. **Create scripts/utils/s3_streaming.py**:
   - Complete S3 streaming implementation
   - Chunk-based downloading
   - Automatic cleanup

3. **batch_tasks.py**:
   - Add error recovery to continue processing on failures
   - Reset circuit breaker when detected

4. **celery_app.py**:
   - Add task routing for large files
   - Configure worker prefetch multiplier

These fixes address all critical issues found in the error logs and will allow the Paul Michael Acuity batch to complete processing successfully.