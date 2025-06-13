"""Test S3 streaming download functionality."""
import os
import tempfile
import logging
from unittest.mock import Mock, patch, MagicMock
import pytest
from scripts.utils.s3_streaming import S3StreamingDownloader, download_s3_file_streaming, check_s3_file_size

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TestS3StreamingDownloader:
    """Test S3 streaming downloader functionality."""
    
    def test_parse_s3_url(self):
        """Test S3 URL parsing."""
        downloader = S3StreamingDownloader()
        
        # Valid URL
        bucket, key = downloader.parse_s3_url("s3://my-bucket/path/to/file.pdf")
        assert bucket == "my-bucket"
        assert key == "path/to/file.pdf"
        
        # Invalid URL
        with pytest.raises(ValueError):
            downloader.parse_s3_url("https://not-s3-url.com/file.pdf")
    
    @patch('boto3.client')
    def test_get_file_size_mb(self, mock_boto_client):
        """Test getting file size without downloading."""
        # Setup mock
        mock_s3 = Mock()
        mock_boto_client.return_value = mock_s3
        mock_s3.head_object.return_value = {
            'ContentLength': 104857600  # 100MB
        }
        
        downloader = S3StreamingDownloader()
        size_mb = downloader.get_file_size_mb("test-bucket", "test-key")
        
        assert size_mb == 100.0
        mock_s3.head_object.assert_called_once_with(Bucket="test-bucket", Key="test-key")
    
    @patch('boto3.client')
    def test_download_streaming(self, mock_boto_client):
        """Test streaming download."""
        # Setup mock
        mock_s3 = Mock()
        mock_boto_client.return_value = mock_s3
        
        # Mock head_object response
        mock_s3.head_object.return_value = {
            'ContentLength': 1024 * 1024  # 1MB
        }
        
        # Mock get_object response with streaming body
        mock_body = MagicMock()
        mock_body.read.side_effect = [
            b'x' * (512 * 1024),  # First 512KB
            b'y' * (512 * 1024),  # Second 512KB
            b''  # EOF
        ]
        mock_s3.get_object.return_value = {'Body': mock_body}
        
        # Test download
        downloader = S3StreamingDownloader(chunk_size=512 * 1024)
        
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            temp_path = tmp.name
        
        try:
            result_path = downloader.download_streaming("test-bucket", "test-key", temp_path)
            
            # Verify file was created
            assert os.path.exists(result_path)
            assert os.path.getsize(result_path) == 1024 * 1024
            
            # Verify S3 calls
            mock_s3.head_object.assert_called_once_with(Bucket="test-bucket", Key="test-key")
            mock_s3.get_object.assert_called_once_with(Bucket="test-bucket", Key="test-key")
            
        finally:
            # Cleanup
            if os.path.exists(temp_path):
                os.unlink(temp_path)
    
    @patch('boto3.client')
    def test_download_with_progress(self, mock_boto_client):
        """Test download with progress callback."""
        # Setup mock
        mock_s3 = Mock()
        mock_boto_client.return_value = mock_s3
        
        mock_s3.head_object.return_value = {
            'ContentLength': 1024  # 1KB for simplicity
        }
        
        mock_body = MagicMock()
        mock_body.read.side_effect = [
            b'x' * 512,  # First 512B
            b'y' * 512,  # Second 512B
            b''  # EOF
        ]
        mock_s3.get_object.return_value = {'Body': mock_body}
        
        # Track progress
        progress_calls = []
        def progress_callback(downloaded, total):
            progress_calls.append((downloaded, total))
        
        downloader = S3StreamingDownloader(chunk_size=512)
        
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            temp_path = tmp.name
        
        try:
            downloader.download_streaming(
                "test-bucket", "test-key", temp_path,
                progress_callback=progress_callback
            )
            
            # Verify progress was tracked
            assert len(progress_calls) == 2
            assert progress_calls[0] == (512, 1024)
            assert progress_calls[1] == (1024, 1024)
            
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
    
    @patch('boto3.client')
    def test_download_to_temp_context_manager(self, mock_boto_client):
        """Test temporary file context manager."""
        # Setup mock
        mock_s3 = Mock()
        mock_boto_client.return_value = mock_s3
        
        mock_s3.head_object.return_value = {'ContentLength': 1024}
        mock_body = MagicMock()
        mock_body.read.side_effect = [b'test_data', b'']
        mock_s3.get_object.return_value = {'Body': mock_body}
        
        downloader = S3StreamingDownloader()
        temp_path_used = None
        
        # Use context manager
        with downloader.download_to_temp("test-bucket", "test-key") as temp_path:
            temp_path_used = temp_path
            # File should exist inside context
            assert os.path.exists(temp_path)
            assert "pdf_download_" in temp_path
            assert temp_path.endswith(".pdf")
        
        # File should be cleaned up after context
        assert not os.path.exists(temp_path_used)
    
    @patch('boto3.client')
    def test_error_handling(self, mock_boto_client):
        """Test error handling for S3 operations."""
        # Setup mock
        mock_s3 = Mock()
        mock_boto_client.return_value = mock_s3
        
        # Test 404 error
        from botocore.exceptions import ClientError
        mock_s3.head_object.side_effect = ClientError(
            {'Error': {'Code': '404', 'Message': 'Not Found'}},
            'HeadObject'
        )
        
        downloader = S3StreamingDownloader()
        
        with pytest.raises(FileNotFoundError):
            downloader.download_streaming("test-bucket", "non-existent-key", "/tmp/test.pdf")


def test_convenience_functions():
    """Test convenience functions."""
    with patch('scripts.utils.s3_streaming.S3StreamingDownloader') as MockDownloader:
        mock_instance = Mock()
        MockDownloader.return_value = mock_instance
        
        # Test check_s3_file_size
        mock_instance.parse_s3_url.return_value = ("bucket", "key")
        mock_instance.get_file_size_mb.return_value = 50.0
        
        size = check_s3_file_size("s3://bucket/key")
        assert size == 50.0
        
        # Test download_s3_file_streaming
        mock_instance.download_streaming.return_value = "/tmp/downloaded.pdf"
        
        result = download_s3_file_streaming("s3://bucket/key", "/tmp/output.pdf")
        mock_instance.download_streaming.assert_called_once_with("bucket", "key", "/tmp/output.pdf")


if __name__ == "__main__":
    # Run specific test
    test = TestS3StreamingDownloader()
    test.test_parse_s3_url()
    test.test_get_file_size_mb()
    test.test_download_streaming()
    test.test_download_with_progress()
    test.test_download_to_temp_context_manager()
    test.test_error_handling()
    test_convenience_functions()
    
    print("All tests passed!")