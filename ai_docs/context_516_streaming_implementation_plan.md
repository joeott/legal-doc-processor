# Context 516: S3 Streaming Download Implementation Plan

## Executive Summary

The current S3 download implementation loads entire files into memory, causing OOM errors for files > 512MB (worker memory limit). We need to implement streaming downloads immediately.

## Implementation Plan

### Phase 1: Create Streaming Utilities (Immediate)

#### 1. Create `scripts/utils/s3_streaming.py`

```python
"""S3 streaming utilities for memory-efficient file downloads."""
import os
import tempfile
import logging
from typing import Optional, Callable
from contextlib import contextmanager
import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

class S3StreamingDownloader:
    """Memory-efficient S3 file downloader with streaming support."""
    
    def __init__(self, chunk_size: int = 8 * 1024 * 1024):  # 8MB chunks
        self.chunk_size = chunk_size
        self.s3_client = boto3.client('s3')
    
    @contextmanager
    def download_to_temp(self, bucket: str, key: str, 
                        prefix: str = "pdf_download_") -> str:
        """Download S3 file to temporary location with automatic cleanup."""
        temp_fd, temp_path = tempfile.mkstemp(prefix=prefix, suffix='.pdf')
        try:
            os.close(temp_fd)  # Close descriptor, we'll write via path
            self.download_streaming(bucket, key, temp_path)
            yield temp_path
        finally:
            # Cleanup
            if os.path.exists(temp_path):
                os.unlink(temp_path)
                logger.debug(f"Cleaned up temporary file: {temp_path}")
    
    def download_streaming(self, bucket: str, key: str, local_path: str,
                          progress_callback: Optional[Callable] = None) -> str:
        """Stream download S3 object to local file."""
        # Get file size first
        try:
            response = self.s3_client.head_object(Bucket=bucket, Key=key)
            total_size = response['ContentLength']
            logger.info(f"Starting streaming download: {key} ({total_size / (1024*1024):.1f} MB)")
        except ClientError as e:
            logger.error(f"Failed to get object metadata: {e}")
            raise
        
        downloaded = 0
        with open(local_path, 'wb') as f:
            response = self.s3_client.get_object(Bucket=bucket, Key=key)
            stream = response['Body']
            
            while True:
                chunk = stream.read(self.chunk_size)
                if not chunk:
                    break
                
                f.write(chunk)
                downloaded += len(chunk)
                
                # Progress callback
                if progress_callback:
                    progress_callback(downloaded, total_size)
                
                # Log progress every 50MB
                if downloaded % (50 * 1024 * 1024) < self.chunk_size:
                    progress = (downloaded / total_size) * 100
                    logger.info(f"Download progress: {progress:.1f}% ({downloaded / (1024*1024):.1f} MB)")
        
        logger.info(f"Download complete: {local_path}")
        return local_path
    
    def get_file_size_mb(self, bucket: str, key: str) -> float:
        """Get S3 file size in MB without downloading."""
        try:
            response = self.s3_client.head_object(Bucket=bucket, Key=key)
            return response['ContentLength'] / (1024 * 1024)
        except ClientError as e:
            logger.error(f"Failed to get file size: {e}")
            return 0.0
```

### Phase 2: Update pdf_tasks.py

#### 2. Replace the problematic download_from_s3 function:

```python
# Around line 675, replace the entire download_from_s3 function with:

def download_from_s3():
    from scripts.utils.s3_streaming import S3StreamingDownloader
    downloader = S3StreamingDownloader()
    
    # Use temporary file with streaming
    with downloader.download_to_temp(bucket, key) as temp_path:
        # Read file from disk instead of memory
        with open(temp_path, 'rb') as f:
            return f.read()
```

Better yet, refactor to avoid reading entire file:

```python
# In split_large_pdf function, around line 668:
if file_path.startswith('s3://'):
    from scripts.utils.s3_streaming import S3StreamingDownloader
    downloader = S3StreamingDownloader()
    
    # Download to temporary file
    with downloader.download_to_temp(bucket, key) as temp_pdf_path:
        # Open PDF from temporary file
        pdf_doc = fitz.open(temp_pdf_path)
        # ... rest of processing
```

### Phase 3: Update check_file_size Function

```python
def check_file_size(file_path: str) -> float:
    """Check file size in MB without downloading."""
    if file_path.startswith('s3://'):
        from scripts.utils.s3_streaming import S3StreamingDownloader
        from urllib.parse import urlparse
        
        parsed = urlparse(file_path)
        bucket = parsed.netloc
        key = parsed.path.lstrip('/')
        
        downloader = S3StreamingDownloader()
        return downloader.get_file_size_mb(bucket, key)
    else:
        # Local file
        if os.path.exists(file_path):
            size_bytes = os.path.getsize(file_path)
            return size_bytes / (1024 * 1024)
        return 0
```

### Phase 4: Add S3 Transfer Manager Support

For very large files (>100MB), use boto3's transfer manager:

```python
# In s3_streaming.py, add:

def download_with_transfer_manager(self, bucket: str, key: str, local_path: str,
                                  multipart_threshold: int = 100 * 1024 * 1024):
    """Use S3 Transfer Manager for efficient large file downloads."""
    from boto3.s3.transfer import TransferConfig
    
    config = TransferConfig(
        multipart_threshold=multipart_threshold,
        multipart_chunksize=self.chunk_size,
        use_threads=True,
        max_concurrency=4
    )
    
    def progress_callback(bytes_transferred):
        logger.debug(f"Transferred: {bytes_transferred / (1024*1024):.1f} MB")
    
    self.s3_client.download_file(
        Bucket=bucket,
        Key=key,
        Filename=local_path,
        Config=config,
        Callback=progress_callback
    )
```

### Phase 5: Update Worker Configuration

Consider increasing worker memory for large file processing:

```python
# In celery_app.py, add queue-specific memory limits:

# OCR workers need more memory for large PDFs
OCR_WORKER_MAX_MEMORY_MB = 1024  # 1GB for OCR workers
DEFAULT_WORKER_MAX_MEMORY_MB = 512  # 512MB for others

def set_memory_limit(queue_name='default'):
    """Set memory limit based on queue type."""
    limit_mb = OCR_WORKER_MAX_MEMORY_MB if 'ocr' in queue_name else DEFAULT_WORKER_MAX_MEMORY_MB
    limit_bytes = limit_mb * 1024 * 1024
    try:
        resource.setrlimit(resource.RLIMIT_AS, (limit_bytes, limit_bytes))
        logger.info(f"Set worker memory limit to {limit_mb}MB for queue {queue_name}")
    except Exception as e:
        logger.warning(f"Could not set memory limit: {e}")
```

## Testing Plan

### 1. Unit Tests
```python
# tests/unit/test_s3_streaming.py
def test_streaming_download():
    # Test with mock S3
    pass

def test_progress_callback():
    # Test progress reporting
    pass

def test_temp_file_cleanup():
    # Ensure temporary files are cleaned up
    pass
```

### 2. Integration Tests
```python
# tests/integration/test_large_file_handling.py
def test_large_pdf_processing():
    # Test with 1GB+ file
    pass

def test_memory_usage():
    # Monitor memory during download
    pass
```

### 3. Manual Testing
1. Process a 2GB PDF from S3
2. Monitor memory usage: `watch -n 1 'ps aux | grep celery'`
3. Check temp file cleanup: `ls -la /tmp/pdf_download_*`

## Rollout Plan

1. **Immediate**: Implement S3StreamingDownloader
2. **Day 1**: Update pdf_tasks.py to use streaming
3. **Day 2**: Test with production files
4. **Day 3**: Deploy to production with monitoring
5. **Day 4**: Optimize based on metrics

## Monitoring

Add metrics for:
- Download duration by file size
- Memory usage during downloads
- Temporary disk space usage
- Download failures and retries

## Risk Mitigation

1. **Disk Space**: Monitor /tmp usage, implement cleanup
2. **Network Interruption**: Add resume capability
3. **Concurrent Downloads**: Limit simultaneous downloads
4. **Memory Spikes**: Set hard limits per worker type