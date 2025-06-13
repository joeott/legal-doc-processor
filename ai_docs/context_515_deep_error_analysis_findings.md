# Deep Error Analysis Findings

**Date**: 2025-06-12
**Analysis Type**: Deep investigation of circuit breaker triggers and pipeline failures

## Executive Summary

Found critical errors in the document processing pipeline affecting large files and relationship extraction. The circuit breaker is triggering due to memory errors when processing large PDFs, and there's a function signature mismatch in the relationship building stage.

## 1. Memory Error with Large PDFs

### Error Details
```
File: WOMBAT 000454-000784.pdf
Size: 584MB (611,565,056 bytes)
Error Type: MemoryError
Location: scripts/pdf_tasks.py, line 678 in download_from_s3
```

### Stack Trace
```python
File "/opt/legal-doc-processor/scripts/pdf_tasks.py", line 678, in download_from_s3
    return response['Body'].read()
File "/opt/legal-doc-processor/venv/lib/python3.10/site-packages/botocore/response.py", line 99, in read
    chunk = self._raw_stream.read(amt)
...
MemoryError
```

### Root Cause
The system is attempting to read the entire 584MB PDF file into memory at once using `response['Body'].read()`. This exceeds the worker memory limit configured in Celery.

### Worker Memory Configuration
- `WORKER_MAX_MEMORY_MB = 512` (512MB per worker)
- `worker_max_memory_per_child = 200000` (200MB in KB)
- The 584MB file exceeds both limits

## 2. Circuit Breaker Activation

### Configuration
```python
class DocumentCircuitBreaker:
    def __init__(self, failure_threshold=3, reset_timeout=300, memory_threshold_mb=400):
```

### Trigger Sequence
1. First attempt: MemoryError when downloading 584MB file
2. Second attempt: Same MemoryError
3. Third attempt: Same MemoryError
4. Circuit breaker opens: "Circuit breaker OPEN: 3 failures"
5. Subsequent attempts blocked for 300 seconds (5 minutes)

### Circuit Breaker Log
```
WARNING:scripts.pdf_tasks:Circuit breaker: d261a4c6-aa80-4281-b50e-5b71df8afa37 failure #3: 
ERROR:scripts.pdf_tasks:Circuit breaker prevented processing: Circuit breaker OPEN: 3 failures
```

## 3. Relationship Building Function Signature Mismatch

### Error
```
TypeError: build_document_relationships() missing 5 required positional arguments: 
'document_data', 'project_uuid', 'chunks', 'entity_mentions', and 'canonical_entities'
```

### Function Definition
```python
def build_document_relationships(self, document_uuid: str, document_data: Dict[str, Any],
                               project_uuid: str, chunks: List[Dict[str, Any]],
                               entity_mentions: List[Dict[str, Any]],
                               canonical_entities: List[Dict[str, Any]]) -> Dict[str, Any]:
```

### Problematic Call (Line 1786-1788)
```python
build_document_relationships.apply_async(
    args=[document_uuid],  # Only passing 1 argument!
    queue='graph'
)
```

### Correct Call (Line 2291-2299)
```python
build_document_relationships.apply_async(
    args=[
        document_uuid,
        document_metadata,
        project_uuid,
        chunks,
        entity_mentions_list,
        resolution_result['canonical_entities']
    ]
)
```

## 4. File Size Analysis

From production test logs:
- WOMBAT 000454-000784.pdf: 597,231.5 KB (584MB)
- WOMBAT 000001-000356.pdf: 11,407.2 KB (11.1MB)
- Most other files: < 1MB

## 5. S3 Storage Issues

From production_test_20250611_201640.log:
```
AttributeError: 'S3StorageManager' object has no attribute 'upload_document'
```

This appears to be resolved in later runs, but indicates API inconsistencies.

## Recommendations

### Immediate Fixes

1. **Memory Management for Large Files**
   - Implement streaming download instead of loading entire file into memory
   - Use chunked reading with boto3's streaming response
   - Increase worker memory limit for OCR queue specifically

2. **Fix Relationship Building Call**
   - Update line 1786-1788 to pass all required arguments
   - Ensure all cached paths also provide complete arguments

3. **Circuit Breaker Tuning**
   - Add file size check before processing
   - Implement different thresholds for large files
   - Add memory usage monitoring before downloads

### Code Fixes Needed

1. **scripts/pdf_tasks.py, line 678**:
   ```python
   # Current (problematic):
   return response['Body'].read()
   
   # Suggested fix:
   # Stream to temporary file
   with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
       for chunk in response['Body'].iter_chunks(chunk_size=1024*1024):  # 1MB chunks
           tmp_file.write(chunk)
       return tmp_file.name
   ```

2. **scripts/pdf_tasks.py, line 1786-1788**:
   ```python
   # Need to gather required data before calling
   document_data = get_document_metadata(document_uuid)
   project_uuid = document_data.get('project_uuid')
   chunks = get_chunks_for_document(document_uuid)
   entity_mentions = get_entity_mentions_for_document(document_uuid)
   
   build_document_relationships.apply_async(
       args=[document_uuid, document_data, project_uuid, chunks, entity_mentions, cached_entities],
       queue='graph'
   )
   ```

## Impact Assessment

1. **Large PDF Processing**: Currently failing for files > 512MB
2. **Relationship Building**: Failing when triggered from cached entity resolution path
3. **Circuit Breaker**: Blocking retries for 5 minutes after 3 failures
4. **Worker Stability**: Memory errors may cause worker crashes and restarts

## Testing Requirements

1. Test with streaming download implementation
2. Verify relationship building with both cached and non-cached paths
3. Process test files of various sizes (1MB, 10MB, 100MB, 500MB+)
4. Monitor memory usage during large file processing
5. Verify circuit breaker reset after successful processing