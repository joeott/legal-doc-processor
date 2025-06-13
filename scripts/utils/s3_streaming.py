"""
S3 Streaming Download Utility for Large Files

This module provides memory-efficient downloading of large S3 files
by streaming them in chunks rather than loading entire files into memory.
"""

import boto3
import tempfile
import os
from pathlib import Path
from typing import Optional, Generator, ContextManager
from contextlib import contextmanager
import logging

logger = logging.getLogger(__name__)


class S3StreamingDownloader:
    """Download large S3 files without loading into memory."""
    
    def __init__(self, chunk_size: int = 8 * 1024 * 1024):  # 8MB chunks
        """
        Initialize the S3 streaming downloader.
        
        Args:
            chunk_size: Size of chunks to download at a time (default 8MB)
        """
        self.chunk_size = chunk_size
        self.s3_client = boto3.client('s3')
        self.logger = logger
    
    @contextmanager
    def download_to_temp(self, bucket: str, key: str) -> Generator[str, None, None]:
        """
        Download S3 object to temporary file using streaming.
        
        Args:
            bucket: S3 bucket name
            key: S3 object key
            
        Yields:
            Path to temporary file containing downloaded content
            
        Note:
            The temporary file is automatically deleted when exiting the context.
        """
        temp_file = None
        temp_path = None
        
        try:
            # Create temporary file
            temp_file = tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.pdf')
            temp_path = temp_file.name
            
            self.logger.info(f"Starting streaming download of s3://{bucket}/{key} to {temp_path}")
            
            # Get object and stream download
            response = self.s3_client.get_object(Bucket=bucket, Key=key)
            total_size = response['ContentLength']
            downloaded = 0
            
            self.logger.info(f"File size: {total_size / (1024*1024):.1f} MB")
            
            # Download in chunks
            for chunk in response['Body'].iter_chunks(chunk_size=self.chunk_size):
                temp_file.write(chunk)
                downloaded += len(chunk)
                
                # Log progress every 50MB
                if downloaded % (50 * 1024 * 1024) == 0:
                    progress = (downloaded / total_size) * 100
                    self.logger.info(
                        f"Download progress: {progress:.1f}% "
                        f"({downloaded/(1024*1024):.1f}MB/{total_size/(1024*1024):.1f}MB)"
                    )
            
            temp_file.close()
            
            # Final progress log
            self.logger.info(
                f"Download complete: {downloaded/(1024*1024):.1f}MB downloaded to {temp_path}"
            )
            
            yield temp_path
            
        except Exception as e:
            self.logger.error(f"Error downloading s3://{bucket}/{key}: {str(e)}")
            raise
            
        finally:
            # Cleanup
            if temp_file and not temp_file.closed:
                temp_file.close()
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                    self.logger.debug(f"Cleaned up temporary file: {temp_path}")
                except Exception as e:
                    self.logger.warning(f"Failed to cleanup temporary file {temp_path}: {e}")
    
    def get_file_size(self, bucket: str, key: str) -> int:
        """
        Get S3 object size without downloading.
        
        Args:
            bucket: S3 bucket name
            key: S3 object key
            
        Returns:
            File size in bytes
        """
        try:
            response = self.s3_client.head_object(Bucket=bucket, Key=key)
            return response['ContentLength']
        except Exception as e:
            self.logger.error(f"Error getting file size for s3://{bucket}/{key}: {str(e)}")
            raise
    
    def download_to_file(self, bucket: str, key: str, output_path: str, 
                        progress_callback: Optional[callable] = None) -> None:
        """
        Download S3 object to a specific file path using streaming.
        
        Args:
            bucket: S3 bucket name
            key: S3 object key
            output_path: Path where file should be saved
            progress_callback: Optional callback function(downloaded_bytes, total_bytes)
        """
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        
        try:
            response = self.s3_client.get_object(Bucket=bucket, Key=key)
            total_size = response['ContentLength']
            downloaded = 0
            
            with open(output_path, 'wb') as f:
                for chunk in response['Body'].iter_chunks(chunk_size=self.chunk_size):
                    f.write(chunk)
                    downloaded += len(chunk)
                    
                    if progress_callback:
                        progress_callback(downloaded, total_size)
                    
                    # Log progress every 50MB
                    if downloaded % (50 * 1024 * 1024) == 0:
                        progress = (downloaded / total_size) * 100
                        self.logger.info(f"Download progress: {progress:.1f}%")
            
            self.logger.info(f"Successfully downloaded to {output_path}")
            
        except Exception as e:
            self.logger.error(f"Error downloading to {output_path}: {str(e)}")
            # Clean up partial file
            if os.path.exists(output_path):
                try:
                    os.unlink(output_path)
                except:
                    pass
            raise


class S3StreamingUploader:
    """Upload large files to S3 using multipart upload."""
    
    def __init__(self, chunk_size: int = 8 * 1024 * 1024):
        """
        Initialize the S3 streaming uploader.
        
        Args:
            chunk_size: Size of chunks for multipart upload (default 8MB)
        """
        self.chunk_size = chunk_size
        self.s3_client = boto3.client('s3')
        self.logger = logger
    
    def upload_file_streaming(self, file_path: str, bucket: str, key: str,
                            progress_callback: Optional[callable] = None) -> None:
        """
        Upload a large file to S3 using multipart upload.
        
        Args:
            file_path: Local file path to upload
            bucket: S3 bucket name
            key: S3 object key
            progress_callback: Optional callback function(uploaded_bytes, total_bytes)
        """
        file_size = os.path.getsize(file_path)
        
        if file_size <= self.chunk_size:
            # Small file - use regular upload
            self.logger.info(f"File size {file_size/(1024*1024):.1f}MB - using regular upload")
            with open(file_path, 'rb') as f:
                self.s3_client.put_object(Bucket=bucket, Key=key, Body=f)
            return
        
        # Large file - use multipart upload
        self.logger.info(f"File size {file_size/(1024*1024):.1f}MB - using multipart upload")
        
        # Use S3 Transfer Manager for efficient multipart uploads
        from boto3.s3.transfer import TransferConfig
        
        config = TransferConfig(
            multipart_threshold=self.chunk_size,
            multipart_chunksize=self.chunk_size,
            max_concurrency=4,
            use_threads=True
        )
        
        uploaded = 0
        
        def upload_callback(bytes_amount):
            nonlocal uploaded
            uploaded += bytes_amount
            if progress_callback:
                progress_callback(uploaded, file_size)
            # Log every 50MB
            if uploaded % (50 * 1024 * 1024) < bytes_amount:
                progress = (uploaded / file_size) * 100
                self.logger.info(f"Upload progress: {progress:.1f}%")
        
        try:
            self.s3_client.upload_file(
                file_path, bucket, key,
                Config=config,
                Callback=upload_callback
            )
            self.logger.info(f"Successfully uploaded to s3://{bucket}/{key}")
        except Exception as e:
            self.logger.error(f"Error uploading to s3://{bucket}/{key}: {str(e)}")
            raise