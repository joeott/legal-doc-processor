# Context 516: Batch Processing Error Analysis - Paul Michael Acuity Documents

## Date: 2025-06-12

### Executive Summary
The batch processing of 10 legal documents from Paul, Michael (Acuity) failed to complete successfully. Analysis reveals **0 of 10 documents (0%)** fully completed the pipeline, with critical failures in memory management for large files and function signature mismatches preventing pipeline completion.

### Batch Status Overview

#### Documents Submitted: 10 (appears as 20 due to duplicate entries)
- **Fully Completed**: 0 (0%)
- **Partially Processed**: 7 (35%)
- **Not Started**: 13 (65%)

#### Pipeline Stage Completion
```
OCR:                      0/20 documents (0%)
Chunking:                 7/20 documents (35%)
Entity Extraction:        7/20 documents (35%)
Entity Resolution:        7/20 documents (35%)
Relationship Extraction:  0/20 documents (0%)
Finalization:            0/20 documents (0%)
```

### Critical Issues Identified

#### 1. Memory Error with Large PDF Files

**Error Location**: `scripts/pdf_tasks.py`, line 678
```python
def download_from_s3():
    s3_client = boto3.client('s3')
    response = s3_client.get_object(Bucket=bucket, Key=key)
    return response['Body'].read()  # <-- MemoryError here

pdf_bytes = retry_with_backoff(download_from_s3, max_attempts=3)
```

**Affected Document**: WOMBAT 000454-000784.pdf (584MB)

**Error Message**:
```
MemoryError
```

**Root Cause**: The code attempts to load the entire 584MB PDF into memory using `.read()`, but Celery workers are configured with only 512MB memory limit:
- `WORKER_MAX_MEMORY_MB = 512`
- `worker_max_memory_per_child = 200000` (200MB soft limit)

#### 2. Circuit Breaker Activation

**Error Log Evidence**:
```
ERROR: Circuit breaker prevented processing: Circuit breaker OPEN: 3 failures
Circuit breaker: d261a4c6-aa80-4281-b50e-5b71df8afa37 failure #3
```

**Configuration** (from log analysis):
- `failure_threshold=3`
- `reset_timeout=300` (5 minutes)
- `memory_threshold_mb=400`

**Impact**: After 3 consecutive MemoryErrors, the circuit breaker opened, blocking all subsequent processing attempts for the affected document.

#### 3. Function Signature Mismatch in Relationship Building

**Error Location**: `scripts/pdf_tasks.py`, lines 1786-1788
```python
build_document_relationships.apply_async(
    args=[document_uuid],  # Only passing 1 argument
    queue='graph'
)
```

**Expected Function Signature** (lines 2320-2326):
```python
def build_document_relationships(self, document_uuid: str, document_data: Dict[str, Any],
                               project_uuid: str, chunks: List[Dict[str, Any]],
                               entity_mentions: List[Dict[str, Any]],
                               canonical_entities: List[Dict[str, Any]]) -> Dict[str, Any]:
```

**Error Message**:
```
TypeError: build_document_relationships() missing 5 required positional arguments: 
'document_data', 'project_uuid', 'chunks', 'entity_mentions', and 'canonical_entities'
```

**Root Cause**: The cached entity resolution path (lines 1786-1788) only passes `document_uuid`, but the function requires 6 arguments total.

### Document-Specific Analysis

#### Successfully Processed (Partial):
1. **Paul, Michael - Initial Disclosures - FINAL 1.27.25.pdf**
   - Entities extracted: 114
   - Canonical entities: 61
   - Chunks: 23
   - **Stuck at**: Entity Resolution → Relationship Extraction transition

2. **Paul, Michael - Plaintiff Acuity Disclosure Stmt 9-20-24.pdf**
   - Entities extracted: 27
   - Canonical entities: 23
   - Chunks: 4
   - **Stuck at**: Entity Resolution → Relationship Extraction transition

#### Failed to Start Processing (13 documents):
- No OCR tasks were initiated for 13 documents
- Likely blocked by circuit breaker or worker memory issues

### Worker Configuration Analysis

From `scripts/celery_app.py`:
```python
# Task execution limits
task_soft_time_limit=240,      # 4 minute soft limit
task_time_limit=300,           # 5 minute hard limit

# Worker configuration
worker_max_memory_per_child=200000,  # 200MB - restart worker after this
```

### Root Cause Analysis

1. **Large File Handling**: The system cannot handle files >512MB due to:
   - Loading entire file into memory
   - Worker memory limits
   - No streaming implementation for large files

2. **Function Call Mismatch**: Two different code paths for calling `build_document_relationships`:
   - Normal path: Passes all required arguments
   - Cached path (lines 1786-1788): Only passes `document_uuid`

3. **Pipeline Fragility**: Once a large file triggers the circuit breaker, it can block processing for other documents in the same batch.

### Recommendations

1. **Immediate Fixes**:
   - Fix the function call at lines 1786-1788 to pass all required arguments
   - Implement streaming for large PDF downloads
   - Increase memory limits for workers handling large files

2. **Long-term Improvements**:
   - Implement file size checks before processing
   - Create dedicated high-memory workers for large files
   - Add chunked upload/download for S3 operations
   - Improve circuit breaker logic to not block entire batches

3. **Monitoring**:
   - Add memory usage monitoring
   - Alert on circuit breaker activations
   - Track file sizes in processing metadata

### Conclusion

The batch processing failed due to a combination of memory limitations with large files and a code bug in the cached entity resolution path. The 584MB WOMBAT document triggered memory errors that activated the circuit breaker, while the function signature mismatch prevented any documents from completing the relationship extraction stage. These issues must be addressed before the batch can be successfully processed.