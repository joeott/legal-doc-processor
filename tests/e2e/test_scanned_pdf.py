"""
End-to-end tests for scanned PDF processing functionality.
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
import tempfile
import os

from scripts.textract_utils import TextractProcessor
from scripts.pdf_tasks import extract_text_from_document


@pytest.mark.e2e
@pytest.mark.slow
class TestScannedPDFProcessing:
    """Test complete scanned PDF processing pipeline."""
    
    @patch('scripts.textract_utils.convert_from_path')
    @patch('scripts.textract_utils.tempfile.NamedTemporaryFile')
    @patch('scripts.textract_utils.boto3.client')
    @patch('scripts.textract_utils.DBSessionLocal')
    def test_complete_scanned_pdf_pipeline(
        self, mock_session_local, mock_boto_client, mock_temp_file, 
        mock_convert, test_db, sample_document_uuid
    ):
        """Test complete scanned PDF processing from detection to text extraction."""
        
        # Mock S3 and Textract clients
        mock_s3_client = Mock()
        mock_textract_client = Mock()
        
        def mock_client_factory(service_name, **kwargs):
            if service_name == 's3':
                return mock_s3_client
            elif service_name == 'textract':
                return mock_textract_client
            return Mock()
        
        mock_boto_client.side_effect = mock_client_factory
        
        # Mock database session
        mock_session = Mock()
        mock_session_local.return_value = mock_session
        
        # Mock temporary file for PDF download
        mock_temp = Mock()
        mock_temp.name = '/tmp/test_scanned.pdf'
        mock_temp_file.return_value.__enter__.return_value = mock_temp
        
        # Mock PDF to image conversion
        mock_image1 = Mock()
        mock_image1.save = Mock()
        mock_image2 = Mock() 
        mock_image2.save = Mock()
        mock_convert.return_value = [mock_image1, mock_image2]  # 2 pages
        
        # Mock scanned PDF detection (returns True for scanned)
        mock_textract_client.detect_document_text.return_value = {
            'Blocks': [{'BlockType': 'PAGE', 'Id': 'page-1'}]  # No text blocks
        }
        
        # Mock Textract processing of individual images
        def mock_detect_text(Document=None, **kwargs):
            if 'page_001.png' in str(Document):
                return {
                    'Blocks': [
                        {
                            'BlockType': 'LINE',
                            'Text': 'Page 1 scanned text content',
                            'Confidence': 95.0
                        },
                        {
                            'BlockType': 'WORD',
                            'Text': 'Page',
                            'Confidence': 95.0
                        }
                    ]
                }
            elif 'page_002.png' in str(Document):
                return {
                    'Blocks': [
                        {
                            'BlockType': 'LINE', 
                            'Text': 'Page 2 scanned text content',
                            'Confidence': 92.0
                        },
                        {
                            'BlockType': 'WORD',
                            'Text': 'Page',
                            'Confidence': 92.0
                        }
                    ]
                }
            return {'Blocks': []}
        
        # Set up detection vs processing calls
        detection_call_count = 0
        def detect_text_router(**kwargs):
            nonlocal detection_call_count
            detection_call_count += 1
            if detection_call_count == 1:
                # First call is for scanned PDF detection
                return {'Blocks': [{'BlockType': 'PAGE', 'Id': 'page-1'}]}
            else:
                # Subsequent calls are for image processing
                return mock_detect_text(**kwargs)
        
        mock_textract_client.detect_document_text.side_effect = detect_text_router
        
        # Mock S3 operations
        mock_s3_client.download_file.return_value = None
        mock_s3_client.put_object.return_value = {'ETag': '"test-etag"'}
        
        # Create processor and test
        processor = TextractProcessor(test_db)
        
        # Test scanned PDF detection
        is_scanned = processor._is_scanned_pdf('test-bucket', 'scanned.pdf')
        assert is_scanned is True
        
        # Test complete scanned PDF processing
        result = processor.process_scanned_pdf_sync(
            'test-bucket', 'documents/scanned.pdf', 123, sample_document_uuid
        )
        
        # Verify results
        assert result['status'] == 'completed'
        assert result['method'] == 'textract_scanned_pdf_sync'
        assert 'text' in result
        assert 'metadata' in result
        
        # Verify text contains content from both pages
        extracted_text = result['text']
        assert 'Page 1 scanned text content' in extracted_text
        assert 'Page 2 scanned text content' in extracted_text
        assert '=== Page 1 ===' in extracted_text
        assert '=== Page 2 ===' in extracted_text
        
        # Verify metadata
        metadata = result['metadata']
        assert metadata['method'] == 'textract_scanned_pdf'
        assert metadata['pages'] == 2
        assert metadata['converted_from_pdf'] is True
        assert metadata['dpi'] == 300  # Default DPI
        
        # Verify S3 operations
        assert mock_s3_client.download_file.called
        assert mock_s3_client.put_object.call_count == 2  # 2 pages uploaded
        
        # Verify database save
        mock_session.execute.assert_called_once()
        mock_session.commit.assert_called_once()
    
    @patch('scripts.textract_utils.boto3.client')
    def test_scanned_pdf_detection_flow(self, mock_boto_client, test_db):
        """Test scanned PDF detection decision flow."""
        mock_client = Mock()
        mock_boto_client.return_value = mock_client
        
        processor = TextractProcessor(test_db)
        
        # Test scanned PDF (no text blocks)
        mock_client.detect_document_text.return_value = {
            'Blocks': [
                {'BlockType': 'PAGE', 'Id': 'page-1'},
                {'BlockType': 'LAYOUT_FIGURE', 'Id': 'figure-1'}
            ]
        }
        
        is_scanned = processor._is_scanned_pdf('test-bucket', 'scanned.pdf')
        assert is_scanned is True
        
        # Test text-based PDF (has text blocks)
        mock_client.detect_document_text.return_value = {
            'Blocks': [
                {'BlockType': 'PAGE', 'Id': 'page-1'},
                {'BlockType': 'LINE', 'Text': 'Text line 1', 'Id': 'line-1'},
                {'BlockType': 'LINE', 'Text': 'Text line 2', 'Id': 'line-2'},
                {'BlockType': 'WORD', 'Text': 'Text', 'Id': 'word-1'},
                {'BlockType': 'WORD', 'Text': 'line', 'Id': 'word-2'},
                {'BlockType': 'WORD', 'Text': '1', 'Id': 'word-3'},
            ]
        }
        
        is_scanned = processor._is_scanned_pdf('test-bucket', 'text.pdf')
        assert is_scanned is False
    
    @patch('scripts.textract_utils.os.getenv')
    def test_scanned_pdf_configuration(self, mock_getenv, test_db):
        """Test scanned PDF processing configuration options."""
        # Test with detection disabled
        def mock_env_values(key, default=None):
            env_values = {
                'ENABLE_SCANNED_PDF_DETECTION': 'false',
                'PDF_CONVERSION_DPI': '150',
                'PDF_CONVERSION_FORMAT': 'JPEG',
                'SCANNED_PDF_IMAGE_PREFIX': 'test-images/'
            }
            return env_values.get(key, default)
        
        mock_getenv.side_effect = mock_env_values
        
        # Reload config to pick up mocked values
        import importlib
        import scripts.config
        importlib.reload(scripts.config)
        
        processor = TextractProcessor(test_db)
        
        # With detection disabled, should always return False
        with patch.object(processor, 'client') as mock_client:
            mock_client.detect_document_text.return_value = {'Blocks': []}
            is_scanned = processor._is_scanned_pdf('test-bucket', 'any.pdf')
            assert is_scanned is False
            # Should not call Textract when detection is disabled
            mock_client.detect_document_text.assert_not_called()
    
    def test_scanned_pdf_error_handling(self, test_db):
        """Test error handling in scanned PDF processing."""
        processor = TextractProcessor(test_db)
        
        # Test detection error handling
        with patch.object(processor, 'client') as mock_client:
            mock_client.detect_document_text.side_effect = Exception("AWS Error")
            
            # Should assume scanned on detection error
            is_scanned = processor._is_scanned_pdf('test-bucket', 'error.pdf')
            assert is_scanned is True
    
    @patch('scripts.pdf_tasks.TextractProcessor')
    def test_scanned_pdf_integration_with_extract_task(
        self, mock_textract_class, test_db, sample_document_uuid
    ):
        """Test scanned PDF integration with extract_text_from_document task."""
        # Mock TextractProcessor
        mock_processor = Mock()
        mock_textract_class.return_value = mock_processor
        
        # Mock synchronous scanned PDF completion
        mock_processor.extract_text_with_fallback.return_value = {
            'status': 'completed',
            'text': 'Scanned PDF extracted text',
            'metadata': {
                'method': 'textract_scanned_pdf_sync',
                'confidence': 0.93,
                'pages': 2,
                'converted_from_pdf': True
            }
        }
        
        # Mock other dependencies
        with patch('scripts.pdf_tasks.validate_document_exists', return_value=True):
            with patch('scripts.pdf_tasks.check_file_size', return_value=2.0):
                with patch('scripts.pdf_tasks.DatabaseManager') as mock_db_class:
                    with patch('scripts.pdf_tasks.update_document_state'):
                        with patch('scripts.pdf_tasks.continue_pipeline_after_ocr'):
                            
                            mock_db_manager = Mock()
                            mock_db_manager.get_source_document.return_value = Mock(id=123)
                            mock_db_class.return_value = mock_db_manager
                            
                            # Create mock task
                            task = Mock()
                            task.validate_conformance = Mock()
                            task.db_manager = mock_db_manager
                            
                            # Call extract_text_from_document
                            result = extract_text_from_document.func(
                                task, sample_document_uuid, 's3://test-bucket/scanned.pdf'
                            )
        
        # Verify scanned PDF was processed synchronously
        assert result['status'] == 'completed'
        assert result['method'] == 'textract_scanned_pdf_sync'
        assert result['text_length'] > 0
        assert 'converted_from_pdf' not in result  # This is in metadata


@pytest.mark.e2e
@pytest.mark.requires_aws
@pytest.mark.slow
class TestScannedPDFRealAWS:
    """Real AWS integration tests for scanned PDF processing."""
    
    def test_real_scanned_pdf_detection(self, test_db):
        """Test scanned PDF detection with real AWS services."""
        pytest.skip("Requires AWS credentials and test PDF in S3")
        
        processor = TextractProcessor(test_db)
        
        # Test with known scanned PDF
        is_scanned = processor._is_scanned_pdf(
            'test-legal-docs', 'samples/scanned_contract.pdf'
        )
        assert isinstance(is_scanned, bool)
        
        # Test with known text PDF
        is_text = processor._is_scanned_pdf(
            'test-legal-docs', 'samples/text_contract.pdf'
        )
        assert isinstance(is_text, bool)
        
        # They should be different
        assert is_scanned != is_text
    
    def test_real_pdf_conversion_and_processing(self, test_db):
        """Test real PDF conversion and Textract processing."""
        pytest.skip("Requires AWS credentials and test PDF in S3")
        
        processor = TextractProcessor(test_db)
        
        # Test with small test PDF
        result = processor.process_scanned_pdf_sync(
            'test-legal-docs', 'samples/small_scanned.pdf', 999, 'test-real-uuid'
        )
        
        assert result['status'] == 'completed'
        assert len(result['text']) > 0
        assert result['metadata']['pages'] > 0