# Context 515: S3 Memory Management and Streaming Analysis

## Current Implementation Analysis

### 1. Memory Issues Identified

#### Current Download Method (line 675-678 in pdf_tasks.py)
```python
def download_from_s3():
    s3_client = boto3.client('s3')
    response = s3_client.get_object(Bucket=bucket, Key=key)
    return response['Body'].read()  # LOADS ENTIRE FILE INTO MEMORY
```

**Problems:**
- `response['Body'].read()` loads the entire file into memory at once
- No streaming or chunked reading
- For a 1GB file, this requires 1GB+ of memory instantly
- Worker memory limit is only 512MB (line 18 in celery_app.py)

#### Worker Memory Configuration
```python
WORKER_MAX_MEMORY_MB = 512  # 512MB per worker
WORKER_MEMORY_LIMIT = WORKER_MAX_MEMORY_MB * 1024 * 1024  # Convert to bytes
```

### 2. Large File Handling Strategy

The system currently has a large file handler that:
1. Checks file size using `head_object` (good - no download)
2. If > 500MB, splits PDF into parts
3. BUT the split still requires downloading the entire file first!

### 3. Missing Streaming Implementations

No streaming download implementations found in:
- `s3_storage.py` - Only has `put_object` operations
- `pdf_tasks.py` - Uses `get_object().read()` 
- `ocr_extraction.py` - Relies on pdf_tasks

## Proposed Solutions

### Solution 1: Streaming Download with Chunks

```python
def download_from_s3_streaming(bucket: str, key: str, local_path: str, chunk_size: int = 8 * 1024 * 1024):
    """Download S3 file in chunks to avoid memory overload."""
    s3_client = boto3.client('s3')
    
    # Get object size first
    response = s3_client.head_object(Bucket=bucket, Key=key)
    total_size = response['ContentLength']
    
    logger.info(f"Downloading {total_size / (1024*1024):.2f} MB in {chunk_size / (1024*1024):.0f} MB chunks")
    
    with open(local_path, 'wb') as f:
        # Stream download
        response = s3_client.get_object(Bucket=bucket, Key=key)
        stream = response['Body']
        
        downloaded = 0
        while True:
            chunk = stream.read(chunk_size)
            if not chunk:
                break
            f.write(chunk)
            downloaded += len(chunk)
            
            if downloaded % (50 * 1024 * 1024) == 0:  # Log every 50MB
                progress = (downloaded / total_size) * 100
                logger.info(f"Download progress: {progress:.1f}%")
    
    return local_path
```

### Solution 2: S3 Range Requests for Very Large Files

```python
def download_from_s3_multipart(bucket: str, key: str, local_path: str, 
                               part_size: int = 100 * 1024 * 1024):  # 100MB parts
    """Download large S3 files using range requests."""
    s3_client = boto3.client('s3')
    
    # Get object size
    response = s3_client.head_object(Bucket=bucket, Key=key)
    total_size = response['ContentLength']
    
    with open(local_path, 'wb') as f:
        for start in range(0, total_size, part_size):
            end = min(start + part_size - 1, total_size - 1)
            
            # Download specific byte range
            response = s3_client.get_object(
                Bucket=bucket, 
                Key=key,
                Range=f'bytes={start}-{end}'
            )
            
            f.write(response['Body'].read())
            logger.info(f"Downloaded bytes {start}-{end} of {total_size}")
    
    return local_path
```

### Solution 3: Direct S3 to Textract (No Download)

For files already in S3, we should avoid downloading altogether:

```python
def process_s3_pdf_directly(bucket: str, key: str, document_uuid: str):
    """Process S3 PDFs without downloading."""
    # Check size first
    s3_client = boto3.client('s3')
    response = s3_client.head_object(Bucket=bucket, Key=key)
    size_mb = response['ContentLength'] / (1024 * 1024)
    
    if size_mb <= 500:
        # Direct Textract processing
        textract = TextractProcessor(db_manager)
        return textract.start_document_text_detection({
            'S3Object': {
                'Bucket': bucket,
                'Name': key
            }
        })
    else:
        # Split using S3 Select or multipart copy
        return split_s3_pdf_serverside(bucket, key, document_uuid)
```

### Solution 4: Memory-Efficient PDF Splitting

```python
def split_large_pdf_streaming(file_path: str, document_uuid: str, max_size_mb: int = 400):
    """Split PDF without loading entire file into memory."""
    import fitz
    
    if file_path.startswith('s3://'):
        # Download to temp file with streaming
        temp_file = f"/tmp/{document_uuid}_temp.pdf"
        parsed = urlparse(file_path)
        download_from_s3_streaming(parsed.netloc, parsed.path.lstrip('/'), temp_file)
        file_path = temp_file
    
    # Use PyMuPDF's incremental loading
    pdf_doc = fitz.open(file_path)
    
    # Process in chunks without loading all pages
    # ... implementation ...
```

## Immediate Action Items

1. **Replace `get_object().read()` with streaming** in `download_from_s3()` function
2. **Add file size pre-check** before any download attempts
3. **Implement temporary file cleanup** to prevent disk space issues
4. **Add memory monitoring** to worker processes
5. **Consider using S3 Transfer Manager** for automatic multipart handling

## Memory Budget Analysis

Current constraints:
- Worker memory: 512MB
- After Python/libraries overhead: ~400MB available
- Safe file size for in-memory: ~300MB max
- Current threshold: 500MB (will cause OOM)

Recommended thresholds:
- In-memory processing: < 100MB
- Streaming required: 100MB - 1GB  
- Multipart required: > 1GB

## Testing Requirements

1. Test with files of various sizes:
   - Small: 10MB
   - Medium: 250MB
   - Large: 750MB
   - Very Large: 2GB

2. Monitor memory usage during processing
3. Verify cleanup of temporary files
4. Test concurrent processing of large files