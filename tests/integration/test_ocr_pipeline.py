"""
Integration tests for OCR pipeline - OCR processing with database integration.
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
import tempfile
import os

from scripts.textract_utils import TextractProcessor
from scripts.pdf_tasks import extract_text_from_document


@pytest.mark.integration
@pytest.mark.requires_db
class TestOCRPipelineIntegration:
    """Test OCR pipeline integration with database."""
    
    def test_textract_processor_with_database(self, test_db):
        """Test TextractProcessor integration with database operations."""
        processor = TextractProcessor(test_db)
        
        # Test database manager integration
        assert processor.db_manager == test_db
        
        # Test processor can access database methods
        assert hasattr(processor.db_manager, 'get_source_document')
        assert hasattr(processor.db_manager, 'get_session')
    
    @patch('scripts.textract_utils.boto3.client')
    @patch('scripts.textract_utils.DBSessionLocal')
    def test_save_extracted_text_to_db(self, mock_session_local, mock_boto_client, test_db):
        """Test saving extracted text to database."""
        # Mock database session
        mock_session = Mock()
        mock_session_local.return_value = mock_session
        
        processor = TextractProcessor(test_db)
        
        text = "Sample extracted text from document"
        metadata = {
            'pages': 2,
            'confidence': 0.95,
            'method': 'textract'
        }
        
        # Should not raise exception
        processor._save_extracted_text_to_db(123, text, metadata)
        
        # Verify database operations
        mock_session.execute.assert_called_once()
        mock_session.commit.assert_called_once()
        mock_session.close.assert_called_once()
    
    @patch('scripts.textract_utils.boto3.client')
    def test_cache_integration(self, mock_boto_client, test_db, test_redis):
        """Test OCR results caching integration."""
        processor = TextractProcessor(test_db)
        
        document_uuid = "test-cache-doc-123"
        text = "Cached OCR text"
        metadata = {'pages': 1, 'confidence': 0.9}
        
        # Cache the result
        processor._cache_ocr_result(document_uuid, text, metadata)
        
        # Retrieve from cache
        cached_result = processor.get_cached_ocr_result(document_uuid)
        
        if test_redis.is_available():
            assert cached_result is not None
            cached_text, cached_metadata = cached_result
            assert cached_text == text
            assert cached_metadata['confidence'] == 0.9
        else:
            # If Redis not available, should handle gracefully
            assert cached_result is None
    
    @patch('scripts.pdf_tasks.TextractProcessor')
    @patch('scripts.pdf_tasks.validate_document_exists')
    @patch('scripts.pdf_tasks.check_file_size')
    def test_extract_text_from_document_integration(
        self, mock_check_size, mock_validate_doc, mock_textract_class, 
        test_db, sample_document_uuid
    ):
        """Test extract_text_from_document task integration."""
        # Mock file size check
        mock_check_size.return_value = 2.5  # MB
        
        # Mock document validation
        mock_validate_doc.return_value = True
        
        # Mock TextractProcessor
        mock_processor = Mock()
        mock_textract_class.return_value = mock_processor
        
        # Mock successful OCR result
        mock_processor.extract_text_with_fallback.return_value = {
            'status': 'completed',
            'text': 'Extracted document text',
            'metadata': {
                'method': 'textract',
                'confidence': 0.95,
                'pages': 1
            }
        }
        
        # Mock database manager
        mock_db_manager = Mock()
        mock_db_manager.get_source_document.return_value = Mock(id=123)
        
        with patch('scripts.pdf_tasks.DatabaseManager', return_value=mock_db_manager):
            with patch('scripts.pdf_tasks.update_document_state'):
                with patch('scripts.pdf_tasks.continue_pipeline_after_ocr'):
                    # Create mock task
                    task = Mock()
                    task.validate_conformance = Mock()
                    task.db_manager = mock_db_manager
                    
                    # Call the function
                    result = extract_text_from_document.func(
                        task, sample_document_uuid, 's3://test-bucket/test.pdf'
                    )
        
        # Verify result
        assert result['status'] == 'completed'
        assert result['text_length'] > 0
        assert 'confidence' in result
        
        # Verify integrations
        mock_processor.extract_text_with_fallback.assert_called_once()
        mock_db_manager.get_source_document.assert_called_once()


@pytest.mark.integration
@pytest.mark.requires_aws
class TestOCRPipelineAWS:
    """Integration tests requiring AWS services."""
    
    @pytest.mark.slow
    def test_scanned_pdf_detection_integration(self, test_db):
        """Test scanned PDF detection with real AWS integration."""
        # This test requires real AWS credentials
        pytest.skip("Requires AWS credentials for integration testing")
        
        processor = TextractProcessor(test_db)
        
        # Test with a known scanned PDF in S3
        is_scanned = processor._is_scanned_pdf(
            'test-bucket', 'samples/scanned_document.pdf'
        )
        
        assert isinstance(is_scanned, bool)
    
    @pytest.mark.slow  
    def test_textract_job_submission_integration(self, test_db):
        """Test Textract job submission integration."""
        # This test requires real AWS credentials and S3 object
        pytest.skip("Requires AWS credentials and valid S3 object")
        
        processor = TextractProcessor(test_db)
        
        job_id = processor.start_document_text_detection_v2(
            'test-bucket', 'samples/test_document.pdf', 123, 'test-uuid'
        )
        
        assert job_id is not None
        assert len(job_id) > 10


@pytest.mark.integration
@pytest.mark.requires_redis
class TestOCRCacheIntegration:
    """Test OCR pipeline caching integration."""
    
    def test_ocr_result_caching_flow(self, test_db, test_redis):
        """Test complete OCR result caching flow."""
        if not test_redis.is_available():
            pytest.skip("Redis not available for caching tests")
        
        processor = TextractProcessor(test_db)
        
        document_uuid = "integration-test-doc-456"
        original_text = "Integration test OCR text"
        metadata = {
            'method': 'textract',
            'confidence': 0.92,
            'pages': 3,
            'word_count': 100
        }
        
        # Cache the result
        processor._cache_ocr_result(document_uuid, original_text, metadata)
        
        # Verify cache hit
        cached_result = processor.get_cached_ocr_result(document_uuid)
        assert cached_result is not None
        
        cached_text, cached_metadata = cached_result
        assert cached_text == original_text
        assert cached_metadata['confidence'] == 0.92
        assert cached_metadata['pages'] == 3
        
        # Test cache key structure
        cache_key = f"textract:result:{document_uuid}"
        direct_cached = test_redis.get_cached(cache_key)
        assert direct_cached is not None
        assert direct_cached['text'] == original_text
    
    def test_ocr_job_status_caching(self, test_db, test_redis):
        """Test Textract job status caching."""
        if not test_redis.is_available():
            pytest.skip("Redis not available for caching tests")
        
        processor = TextractProcessor(test_db)
        
        job_id = "test-job-integration-789"
        status_data = {
            'JobStatus': 'IN_PROGRESS',
            'StatusMessage': 'Processing document',
            'JobId': job_id
        }
        
        # Cache job status
        processor._cache_job_status(job_id, status_data, ttl=300)
        
        # Retrieve from cache
        cached_status = processor._check_job_status_cache(job_id)
        assert cached_status is not None
        assert cached_status['JobStatus'] == 'IN_PROGRESS'
        assert cached_status['JobId'] == job_id


@pytest.mark.integration
class TestOCRErrorHandling:
    """Test OCR pipeline error handling integration."""
    
    @patch('scripts.textract_utils.boto3.client')
    def test_textract_error_handling(self, mock_boto_client, test_db):
        """Test Textract error handling integration."""
        # Mock Textract client that raises exception
        mock_client = Mock()
        mock_boto_client.return_value = mock_client
        mock_client.detect_document_text.side_effect = Exception("AWS Error")
        
        processor = TextractProcessor(test_db)
        
        # Should handle error gracefully in detection
        with pytest.raises(Exception):
            processor._is_scanned_pdf('test-bucket', 'test.pdf')
    
    @patch('scripts.textract_utils.DBSessionLocal')
    def test_database_error_handling(self, mock_session_local, test_db):
        """Test database error handling in OCR pipeline."""
        # Mock database session that raises exception
        mock_session = Mock()
        mock_session_local.return_value = mock_session
        mock_session.execute.side_effect = Exception("Database Error")
        
        processor = TextractProcessor(test_db)
        
        # Should handle database errors
        with pytest.raises(Exception):
            processor._save_extracted_text_to_db(
                123, "test text", {'pages': 1, 'confidence': 0.9}
            )
        
        # Verify rollback was called
        mock_session.rollback.assert_called_once()
        mock_session.close.assert_called_once()
    
    def test_cache_error_handling(self, test_db):
        """Test cache error handling in OCR pipeline."""
        processor = TextractProcessor(test_db)
        
        # Mock Redis manager that raises exception
        with patch('scripts.textract_utils.get_redis_manager') as mock_redis:
            mock_redis_mgr = Mock()
            mock_redis_mgr.is_available.return_value = True
            mock_redis_mgr.set_cached.side_effect = Exception("Redis Error")
            mock_redis.return_value = mock_redis_mgr
            
            # Should handle cache errors gracefully (not crash)
            processor._cache_ocr_result("test-doc", "text", {})
            
            # Function should complete without raising exception