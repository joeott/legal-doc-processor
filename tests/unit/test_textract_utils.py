"""
Unit tests for textract_utils.py - OCR and document processing utilities.
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
import tempfile
import os

from scripts.textract_utils import TextractProcessor


@pytest.mark.unit
class TestTextractProcessor:
    """Test the TextractProcessor class."""
    
    def test_init(self, test_db):
        """Test TextractProcessor initialization."""
        processor = TextractProcessor(test_db)
        
        assert processor.db_manager == test_db
        assert processor.region_name == 'us-east-2'  # From config
        assert hasattr(processor, 'client')
        assert hasattr(processor, 'textractor')
        assert hasattr(processor, 's3_client')
    
    @patch('scripts.textract_utils.boto3.client')
    def test_is_scanned_pdf_true(self, mock_boto_client, test_db):
        """Test scanned PDF detection for image-only PDF."""
        # Mock Textract response with no text blocks
        mock_client = Mock()
        mock_boto_client.return_value = mock_client
        mock_client.detect_document_text.return_value = {
            'Blocks': [
                {'BlockType': 'PAGE', 'Id': 'page-1'}
            ]
        }
        
        processor = TextractProcessor(test_db)
        result = processor._is_scanned_pdf('test-bucket', 'test.pdf')
        
        assert result is True
        mock_client.detect_document_text.assert_called_once()
    
    @patch('scripts.textract_utils.boto3.client')
    def test_is_scanned_pdf_false(self, mock_boto_client, test_db):
        """Test scanned PDF detection for text-based PDF."""
        # Mock Textract response with text blocks
        mock_client = Mock()
        mock_boto_client.return_value = mock_client
        mock_client.detect_document_text.return_value = {
            'Blocks': [
                {'BlockType': 'PAGE', 'Id': 'page-1'},
                {'BlockType': 'LINE', 'Text': 'Sample text', 'Id': 'line-1'},
                {'BlockType': 'LINE', 'Text': 'More text', 'Id': 'line-2'},
                {'BlockType': 'WORD', 'Text': 'Sample', 'Id': 'word-1'},
                {'BlockType': 'WORD', 'Text': 'text', 'Id': 'word-2'},
                {'BlockType': 'WORD', 'Text': 'More', 'Id': 'word-3'},
            ]
        }
        
        processor = TextractProcessor(test_db)
        result = processor._is_scanned_pdf('test-bucket', 'test.pdf')
        
        assert result is False
        mock_client.detect_document_text.assert_called_once()
    
    @patch('scripts.textract_utils.convert_from_path')
    @patch('scripts.textract_utils.tempfile.NamedTemporaryFile')
    def test_convert_pdf_to_images_s3(self, mock_temp_file, mock_convert, test_db, mock_s3_client):
        """Test PDF to images conversion and S3 upload."""
        # Mock temporary file
        mock_temp = Mock()
        mock_temp.name = '/tmp/test.pdf'
        mock_temp_file.return_value.__enter__.return_value = mock_temp
        
        # Mock PDF conversion
        mock_image = Mock()
        mock_image.save = Mock()
        mock_convert.return_value = [mock_image, mock_image]  # 2 pages
        
        processor = TextractProcessor(test_db)
        
        with patch.object(processor, 's3_client', mock_s3_client):
            result = processor._convert_pdf_to_images_s3(
                'test-bucket', 'documents/test.pdf', 'test-uuid'
            )
        
        assert len(result) == 2
        assert result[0]['page_num'] == 1
        assert result[1]['page_num'] == 2
        assert 'converted-images/' in result[0]['key']
        
        # Verify S3 uploads
        assert mock_s3_client.put_object.call_count == 2
    
    @patch('scripts.textract_utils.boto3.client')
    def test_process_scanned_pdf_pages(self, mock_boto_client, test_db):
        """Test processing converted PDF pages with Textract."""
        # Mock Textract client
        mock_client = Mock()
        mock_boto_client.return_value = mock_client
        mock_client.detect_document_text.return_value = {
            'Blocks': [
                {
                    'BlockType': 'LINE',
                    'Text': 'Sample page text',
                    'Confidence': 95.0
                },
                {
                    'BlockType': 'WORD', 
                    'Text': 'Sample',
                    'Confidence': 95.0
                }
            ]
        }
        
        processor = TextractProcessor(test_db)
        
        image_keys = [
            {'key': 'converted-images/test/page_001.png', 'page_num': 1, 'bucket': 'test-bucket'},
            {'key': 'converted-images/test/page_002.png', 'page_num': 2, 'bucket': 'test-bucket'}
        ]
        
        text, metadata = processor._process_scanned_pdf_pages(
            'test-bucket', image_keys, 123, 'test-uuid'
        )
        
        assert 'Sample page text' in text
        assert 'Page 1' in text
        assert 'Page 2' in text
        assert metadata['method'] == 'textract_scanned_pdf'
        assert metadata['pages'] == 2
        assert metadata['converted_from_pdf'] is True
        
        # Verify Textract calls
        assert mock_client.detect_document_text.call_count == 2
    
    def test_extract_text_from_textract_document(self, test_db):
        """Test text extraction from Textractor document."""
        # Mock Textractor document
        mock_doc = Mock()
        mock_doc.text = "Primary document text"
        
        processor = TextractProcessor(test_db)
        result = processor.extract_text_from_textract_document(mock_doc)
        
        assert result == "Primary document text"
    
    def test_extract_text_from_textract_document_fallback(self, test_db):
        """Test text extraction with fallback to lines and words."""
        # Mock Textractor document with empty primary text
        mock_doc = Mock()
        mock_doc.text = ""
        
        # Mock lines fallback
        mock_line1 = Mock()
        mock_line1.text = "Line 1 text"
        mock_line2 = Mock()
        mock_line2.text = "Line 2 text"
        mock_doc.lines = [mock_line1, mock_line2]
        
        processor = TextractProcessor(test_db)
        result = processor.extract_text_from_textract_document(mock_doc)
        
        assert result == "Line 1 text\nLine 2 text"
    
    def test_calculate_ocr_confidence(self, test_db):
        """Test OCR confidence calculation."""
        # Mock Textractor document
        mock_word1 = Mock()
        mock_word1.confidence = 95.0
        mock_word2 = Mock()
        mock_word2.confidence = 85.0
        mock_word3 = Mock()
        mock_word3.confidence = 90.0
        
        mock_doc = Mock()
        mock_doc.words = [mock_word1, mock_word2, mock_word3]
        
        processor = TextractProcessor(test_db)
        confidence = processor.calculate_ocr_confidence(mock_doc)
        
        assert confidence == 90.0  # Average of 95, 85, 90
    
    def test_calculate_ocr_confidence_no_words(self, test_db):
        """Test OCR confidence calculation with no words."""
        mock_doc = Mock()
        mock_doc.words = []
        
        processor = TextractProcessor(test_db)
        confidence = processor.calculate_ocr_confidence(mock_doc)
        
        assert confidence == 0.0


@pytest.mark.unit  
@pytest.mark.requires_aws
class TestTextractProcessorAWS:
    """Tests requiring AWS credentials."""
    
    @pytest.mark.slow
    def test_start_document_text_detection_v2_real(self, test_db):
        """Test actual Textract job initiation (slow test)."""
        # This test requires real AWS credentials and S3 access
        pytest.skip("Requires AWS credentials and valid S3 object")
        
        processor = TextractProcessor(test_db)
        job_id = processor.start_document_text_detection_v2(
            'test-bucket', 'test.pdf', 123, 'test-uuid'
        )
        
        assert job_id is not None
        assert len(job_id) > 10  # AWS job IDs are long


@pytest.mark.unit
class TestTextractUtilityFunctions:
    """Test utility functions in textract_utils module."""
    
    def test_extract_text_from_blocks(self, test_db):
        """Test text extraction from Textract blocks."""
        blocks = [
            {
                'BlockType': 'LINE',
                'Text': 'First line of text',
                'Page': 1
            },
            {
                'BlockType': 'LINE', 
                'Text': 'Second line of text',
                'Page': 1
            },
            {
                'BlockType': 'LINE',
                'Text': 'Third line on page 2',
                'Page': 2
            }
        ]
        
        processor = TextractProcessor(test_db)
        result = processor._extract_text_from_blocks(blocks)
        
        assert 'First line of text' in result
        assert 'Second line of text' in result
        assert 'Third line on page 2' in result
        # Should have page break between pages
        assert '\n\n' in result
    
    def test_calculate_confidence_from_blocks(self, test_db):
        """Test confidence calculation from Textract blocks."""
        blocks = [
            {
                'BlockType': 'WORD',
                'Text': 'word1',
                'Confidence': 95.0
            },
            {
                'BlockType': 'WORD',
                'Text': 'word2', 
                'Confidence': 85.0
            },
            {
                'BlockType': 'LINE',
                'Text': 'line1',
                'Confidence': 90.0
            }
        ]
        
        processor = TextractProcessor(test_db)
        confidence = processor._calculate_confidence_from_blocks(blocks)
        
        assert confidence == 90.0  # Average of 95, 85, 90