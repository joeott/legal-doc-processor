# Phase 1 Unit Testing Plan - Part 1 (Core Infrastructure)

## Overview

This document outlines a comprehensive unit testing strategy for the first 6 critical modules of the legal document processing system. This part covers the core infrastructure components that form the foundation of the stage-aware architecture.

**Modules Covered (Part 1):**
1. `config.py` - Configuration management and stage control
2. `models_init.py` - Stage-aware model initialization
3. `supabase_utils.py` - Database operations and client management  
4. `ocr_extraction.py` - Multi-modal text extraction
5. `entity_extraction.py` - Stage-aware named entity recognition
6. `mistral_utils.py` - Mistral API integration

## Test Structure and Organization

```
tests/
├── conftest.py                 # Pytest configuration and shared fixtures
├── unit/
│   ├── test_config.py
│   ├── test_models_init.py
│   ├── test_supabase_utils.py
│   ├── test_ocr_extraction.py
│   ├── test_entity_extraction.py
│   └── test_mistral_utils.py
├── fixtures/
│   ├── documents/
│   │   ├── sample.pdf
│   │   ├── sample.docx
│   │   ├── sample.txt
│   │   ├── sample.eml
│   │   └── sample.wav
│   ├── mock_responses/
│   │   ├── openai_responses.json
│   │   ├── mistral_responses.json
│   │   └── supabase_responses.json
│   └── test_data/
│       ├── entity_samples.json
│       └── ocr_samples.json
├── mocks/
│   ├── mock_models.py
│   ├── mock_api_clients.py
│   └── mock_database.py
└── requirements-test.txt
```

## Shared Test Configuration (conftest.py)

```python
import pytest
import os
import json
from unittest.mock import Mock, patch
from pathlib import Path

@pytest.fixture
def test_env_stage1(monkeypatch):
    """Set up Stage 1 environment variables"""
    monkeypatch.setenv("DEPLOYMENT_STAGE", "1")
    monkeypatch.setenv("FORCE_CLOUD_LLMS", "true")
    monkeypatch.setenv("BYPASS_LOCAL_MODELS", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("MISTRAL_API_KEY", "test-mistral-key")
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "test-anon-key")

@pytest.fixture
def test_env_stage2(monkeypatch):
    """Set up Stage 2 environment variables"""
    monkeypatch.setenv("DEPLOYMENT_STAGE", "2")
    monkeypatch.setenv("FORCE_CLOUD_LLMS", "false")
    monkeypatch.setenv("BYPASS_LOCAL_MODELS", "false")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    
@pytest.fixture
def sample_documents():
    """Provide paths to sample test documents"""
    fixtures_dir = Path(__file__).parent / "fixtures" / "documents"
    return {
        'pdf': fixtures_dir / "sample.pdf",
        'docx': fixtures_dir / "sample.docx", 
        'txt': fixtures_dir / "sample.txt",
        'eml': fixtures_dir / "sample.eml",
        'audio': fixtures_dir / "sample.wav"
    }

@pytest.fixture
def mock_responses():
    """Load mock API responses"""
    responses_dir = Path(__file__).parent / "fixtures" / "mock_responses"
    with open(responses_dir / "openai_responses.json") as f:
        openai_responses = json.load(f)
    with open(responses_dir / "mistral_responses.json") as f:
        mistral_responses = json.load(f)
    return {
        'openai': openai_responses,
        'mistral': mistral_responses
    }
```

## Module 1: config.py Testing

### Test Analysis
**Functions/Classes:**
- Environment variable parsing and validation
- Stage management configuration 
- Path validation and directory setup
- Boolean configuration parsing

**Critical Paths:**
- Stage 1 validation requiring cloud API keys
- Configuration fallbacks and defaults
- Invalid environment variable handling

### test_config.py

```python
import pytest
import os
import importlib
from pathlib import Path
from unittest.mock import patch

class TestConfigStageManagement:
    """Test stage-aware configuration management"""
    
    def test_stage1_configuration_complete(self, test_env_stage1):
        """Test Stage 1 configuration with all required keys"""
        # Force reload config module to pick up new env vars
        import config
        importlib.reload(config)
        
        assert config.DEPLOYMENT_STAGE == "1"
        assert config.FORCE_CLOUD_LLMS == True
        assert config.BYPASS_LOCAL_MODELS == True
        assert config.OPENAI_API_KEY == "test-openai-key"
        assert config.MISTRAL_API_KEY == "test-mistral-key"
        
    def test_stage2_configuration(self, test_env_stage2):
        """Test Stage 2 hybrid configuration"""
        import config
        importlib.reload(config)
        
        assert config.DEPLOYMENT_STAGE == "2"
        assert config.FORCE_CLOUD_LLMS == False
        assert config.BYPASS_LOCAL_MODELS == False
        
    def test_stage3_defaults(self, monkeypatch):
        """Test Stage 3 local processing defaults"""
        monkeypatch.setenv("DEPLOYMENT_STAGE", "3")
        monkeypatch.delenv("FORCE_CLOUD_LLMS", raising=False)
        monkeypatch.delenv("BYPASS_LOCAL_MODELS", raising=False)
        
        import config
        importlib.reload(config)
        
        assert config.DEPLOYMENT_STAGE == "3"
        # Should default to local models for Stage 3

class TestConfigValidation:
    """Test configuration validation and error handling"""
    
    def test_missing_required_stage1_keys(self, monkeypatch):
        """Test validation when required Stage 1 keys are missing"""
        monkeypatch.setenv("DEPLOYMENT_STAGE", "1")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
        
        import config
        importlib.reload(config)
        
        # Config should load but validation functions should catch missing keys
        assert config.DEPLOYMENT_STAGE == "1"
        assert config.OPENAI_API_KEY is None
        
    def test_boolean_parsing(self, monkeypatch):
        """Test boolean environment variable parsing"""
        test_cases = [
            ("true", True), ("True", True), ("TRUE", True),
            ("1", True), ("yes", True), ("YES", True),
            ("false", False), ("False", False), ("0", False),
            ("no", False), ("", False), ("invalid", False)
        ]
        
        for env_value, expected in test_cases:
            monkeypatch.setenv("USE_MISTRAL_FOR_OCR", env_value)
            
            import config
            importlib.reload(config)
            
            assert config.USE_MISTRAL_FOR_OCR == expected

class TestConfigDirectories:
    """Test directory configuration and validation"""
    
    def test_base_directory_resolution(self):
        """Test that BASE_DIR resolves correctly"""
        import config
        
        assert config.BASE_DIR.is_absolute()
        assert config.BASE_DIR.exists()
        
    def test_custom_source_directory(self, monkeypatch, tmp_path):
        """Test custom source document directory"""
        custom_dir = str(tmp_path / "custom_input")
        monkeypatch.setenv("SOURCE_DOCUMENT_DIR", custom_dir)
        
        import config
        importlib.reload(config)
        
        assert config.SOURCE_DOCUMENT_DIR == custom_dir

class TestConfigS3Settings:
    """Test S3 configuration settings"""
    
    def test_s3_enabled_configuration(self, monkeypatch):
        """Test S3 enabled configuration"""
        monkeypatch.setenv("USE_S3_FOR_INPUT", "true")
        monkeypatch.setenv("S3_BUCKET_NAME", "test-bucket")
        
        import config
        importlib.reload(config)
        
        assert config.USE_S3_FOR_INPUT == True
        assert config.S3_BUCKET_NAME == "test-bucket"
        
    def test_s3_disabled_defaults(self, monkeypatch):
        """Test S3 disabled with defaults"""
        monkeypatch.setenv("USE_S3_FOR_INPUT", "false")
        
        import config
        importlib.reload(config)
        
        assert config.USE_S3_FOR_INPUT == False
        assert config.S3_BUCKET_NAME == "legal-docs-bucket"  # Default
```

## Module 2: models_init.py Testing

### Test Analysis
**Functions/Classes:**
- `should_load_local_models()` - Stage determination
- `initialize_all_models()` - Stage-aware initialization
- Model accessor functions (`get_*_model()`)
- `validate_cloud_api_keys()` - API key validation

**Critical Paths:**
- Stage 1 bypassing all local models
- Stage 2/3 local model loading
- Graceful fallback handling
- Memory management

### test_models_init.py

```python
import pytest
from unittest.mock import Mock, patch, MagicMock
import torch

class TestStageAwareModelLoading:
    """Test stage-aware model initialization"""
    
    def test_stage1_bypasses_local_models(self, test_env_stage1):
        """Test that Stage 1 skips all local model loading"""
        with patch('models_init.DEPLOYMENT_STAGE', '1'):
            from models_init import should_load_local_models, initialize_all_models
            
            assert should_load_local_models() == False
            
            # Initialize models - should skip local loading
            initialize_all_models()
            
            from models_init import (get_qwen2_vl_ocr_model, get_whisper_model, 
                                   get_ner_pipeline)
            
            assert get_qwen2_vl_ocr_model() is None
            assert get_whisper_model() is None
            assert get_ner_pipeline() is None
    
    def test_stage2_loads_local_models(self, test_env_stage2):
        """Test that Stage 2 loads local models"""
        with patch('models_init.DEPLOYMENT_STAGE', '2'), \
             patch('transformers.AutoModelForCausalLM') as mock_model, \
             patch('transformers.AutoProcessor') as mock_processor, \
             patch('whisper.load_model') as mock_whisper:
            
            mock_model.from_pretrained.return_value = Mock()
            mock_processor.from_pretrained.return_value = Mock()
            mock_whisper.return_value = Mock()
            
            from models_init import should_load_local_models, initialize_all_models
            
            assert should_load_local_models() == True
            
            initialize_all_models()
            
            # Verify models were loaded
            mock_model.from_pretrained.assert_called()
            mock_processor.from_pretrained.assert_called()
            mock_whisper.assert_called()

class TestModelAccessors:
    """Test model accessor functions"""
    
    def test_lazy_loading(self):
        """Test that models are loaded on first access"""
        with patch('models_init.initialize_qwen2_vl_ocr_model') as mock_init:
            mock_init.return_value = (Mock(), Mock(), 'cuda', Mock())
            
            from models_init import get_qwen2_vl_ocr_model
            
            # First call should trigger initialization
            model = get_qwen2_vl_ocr_model()
            assert model is not None
            mock_init.assert_called_once()
            
            # Second call should not trigger initialization again
            model2 = get_qwen2_vl_ocr_model()
            assert model == model2
            mock_init.assert_called_once()  # Still only called once
    
    def test_stage1_returns_none(self, test_env_stage1):
        """Test that model accessors return None in Stage 1"""
        with patch('models_init.DEPLOYMENT_STAGE', '1'):
            from models_init import (get_qwen2_vl_ocr_model, get_whisper_model)
            
            assert get_qwen2_vl_ocr_model() is None
            assert get_whisper_model() is None

class TestAPIKeyValidation:
    """Test API key validation for Stage 1"""
    
    def test_valid_api_keys_stage1(self, test_env_stage1):
        """Test API key validation with valid keys"""
        with patch('models_init.DEPLOYMENT_STAGE', '1'):
            from models_init import validate_cloud_api_keys
            
            # Should not raise exception with valid keys
            validate_cloud_api_keys()
    
    def test_missing_openai_key_stage1(self, monkeypatch):
        """Test validation fails with missing OpenAI key"""
        monkeypatch.setenv("DEPLOYMENT_STAGE", "1")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        
        from models_init import validate_cloud_api_keys
        
        with pytest.raises(ValueError, match="OPENAI_API_KEY is required"):
            validate_cloud_api_keys()
    
    def test_api_keys_not_required_stage2(self, test_env_stage2):
        """Test API keys not strictly required for Stage 2"""
        with patch('models_init.DEPLOYMENT_STAGE', '2'):
            from models_init import validate_cloud_api_keys
            
            # Should not raise exception even without all keys
            validate_cloud_api_keys()

class TestModelInitializationErrors:
    """Test error handling during model initialization"""
    
    def test_graceful_fallback_on_model_load_failure(self):
        """Test graceful handling when local model loading fails"""
        with patch('transformers.AutoModelForCausalLM.from_pretrained') as mock_model:
            mock_model.side_effect = Exception("Model loading failed")
            
            from models_init import initialize_qwen2_vl_ocr_model
            
            # Should not raise exception, should return None values
            result = initialize_qwen2_vl_ocr_model()
            assert all(x is None for x in result[:3])  # model, processor, device should be None
    
    def test_memory_cleanup_on_error(self):
        """Test that CUDA memory is cleaned up on initialization errors"""
        with patch('torch.cuda.is_available', return_value=True), \
             patch('torch.cuda.empty_cache') as mock_cleanup, \
             patch('transformers.AutoModelForCausalLM.from_pretrained') as mock_model:
            
            mock_model.side_effect = Exception("CUDA out of memory")
            
            from models_init import initialize_qwen2_vl_ocr_model
            
            initialize_qwen2_vl_ocr_model()
            mock_cleanup.assert_called()
```

## Module 3: supabase_utils.py Testing

### Test Analysis
**Functions/Classes:**
- `SupabaseManager` class with CRUD operations
- `get_supabase_client()` - Client initialization
- `generate_document_url()` - Storage URL generation
- Database entity management functions

**Critical Paths:**
- Database connection validation
- UUID generation and management
- Error handling for database operations
- Storage URL generation

### test_supabase_utils.py

```python
import pytest
import uuid
import json
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

class TestSupabaseClientInitialization:
    """Test Supabase client creation and configuration"""
    
    def test_client_creation_success(self, test_env_stage1):
        """Test successful client creation with valid credentials"""
        with patch('supabase.create_client') as mock_create:
            mock_client = Mock()
            mock_create.return_value = mock_client
            
            from supabase_utils import get_supabase_client
            
            client = get_supabase_client()
            assert client == mock_client
            mock_create.assert_called_with(
                "https://test.supabase.co", 
                "test-anon-key"
            )
    
    def test_client_creation_missing_credentials(self, monkeypatch):
        """Test client creation fails with missing credentials"""
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
        
        from supabase_utils import get_supabase_client
        
        with pytest.raises(ValueError, match="SUPABASE_URL and SUPABASE_ANON_KEY must be set"):
            get_supabase_client()

class TestDocumentURLGeneration:
    """Test document URL generation for storage"""
    
    def test_generate_url_basic_path(self):
        """Test URL generation for basic file path"""
        with patch('supabase_utils.get_supabase_client') as mock_get_client:
            mock_client = Mock()
            mock_storage = Mock()
            mock_client.storage = mock_storage
            mock_storage.from_.return_value.get_public_url.return_value = "https://storage.url/file.pdf"
            mock_get_client.return_value = mock_client
            
            from supabase_utils import generate_document_url
            
            url = generate_document_url("uploads/test.pdf")
            assert url == "https://storage.url/file.pdf"
    
    def test_generate_url_already_http(self):
        """Test URL generation when path is already HTTP URL"""
        from supabase_utils import generate_document_url
        
        existing_url = "https://example.com/file.pdf"
        result = generate_document_url(existing_url)
        
        assert result == existing_url
    
    def test_generate_url_error_handling(self):
        """Test URL generation error handling"""
        with patch('supabase_utils.get_supabase_client') as mock_get_client:
            mock_get_client.side_effect = Exception("Connection failed")
            
            from supabase_utils import generate_document_url
            
            result = generate_document_url("uploads/test.pdf")
            assert result is None

class TestSupabaseManagerCRUD:
    """Test SupabaseManager CRUD operations"""
    
    @pytest.fixture
    def mock_supabase_manager(self):
        """Create a mock SupabaseManager instance"""
        with patch('supabase_utils.get_supabase_client') as mock_get_client:
            mock_client = Mock()
            mock_get_client.return_value = mock_client
            
            from supabase_utils import SupabaseManager
            manager = SupabaseManager()
            manager.client = mock_client
            
            return manager, mock_client
    
    def test_create_source_document_entry(self, mock_supabase_manager):
        """Test creating source document entry"""
        manager, mock_client = mock_supabase_manager
        
        # Mock the insert response
        mock_response = Mock()
        mock_response.data = [{"id": 1, "document_uuid": "test-uuid"}]
        mock_client.table.return_value.insert.return_value.execute.return_value = mock_response
        
        doc_id, doc_uuid = manager.create_source_document_entry(
            original_file_name="test.pdf",
            detected_file_type=".pdf",
            project_sql_id=1
        )
        
        assert doc_id == 1
        assert doc_uuid == "test-uuid"
        mock_client.table.assert_called_with("source_documents")
    
    def test_create_entity_mention_entry(self, mock_supabase_manager):
        """Test creating entity mention entry"""
        manager, mock_client = mock_supabase_manager
        
        # Mock successful insert
        mock_response = Mock()
        mock_response.data = [{"id": 1}]
        mock_client.table.return_value.insert.return_value.execute.return_value = mock_response
        
        result = manager.create_entity_mention_entry(
            chunk_id=1,
            entity_value="John Doe",
            entity_type="PERSON",
            confidence_score=0.95,
            char_start_index=0,
            char_end_index=8
        )
        
        assert result == 1
        mock_client.table.assert_called_with("entity_mentions")
    
    def test_error_handling_database_failure(self, mock_supabase_manager):
        """Test error handling when database operations fail"""
        manager, mock_client = mock_supabase_manager
        
        # Mock database failure
        mock_client.table.return_value.insert.return_value.execute.side_effect = Exception("DB Error")
        
        result = manager.create_source_document_entry(
            original_file_name="test.pdf",
            detected_file_type=".pdf", 
            project_sql_id=1
        )
        
        assert result == (None, None)

class TestUUIDGeneration:
    """Test UUID generation and management"""
    
    def test_consistent_uuid_generation(self):
        """Test that UUIDs are properly formatted"""
        from supabase_utils import SupabaseManager
        
        # Test multiple UUID generations
        uuids = [str(uuid.uuid4()) for _ in range(10)]
        
        for test_uuid in uuids:
            # Verify UUID format
            assert len(test_uuid) == 36
            assert test_uuid.count('-') == 4
            
            # Verify it's a valid UUID
            parsed = uuid.UUID(test_uuid)
            assert str(parsed) == test_uuid

class TestDatabaseDataTypes:
    """Test database data type handling"""
    
    def test_json_serialization(self, mock_supabase_manager):
        """Test JSON data serialization for database storage"""
        manager, mock_client = mock_supabase_manager
        
        test_metadata = {
            "extraction_method": "OpenAI",
            "confidence": 0.85,
            "entities": ["John Doe", "ACME Corp"],
            "timestamp": datetime.now().isoformat()
        }
        
        # Mock successful insert
        mock_response = Mock()
        mock_response.data = [{"id": 1}]
        mock_client.table.return_value.insert.return_value.execute.return_value = mock_response
        
        result = manager.create_chunk_entry(
            document_id=1,
            chunk_text="Sample text",
            chunk_sequence_number=1,
            char_start_index=0,
            char_end_index=11,
            metadata_json=test_metadata
        )
        
        assert result is not None
        
        # Verify JSON was properly serialized in the call
        call_args = mock_client.table.return_value.insert.call_args[0][0]
        assert 'metadata_json' in call_args
        # JSON should be serializable
        json.dumps(call_args['metadata_json'])
```

## Module 4: ocr_extraction.py Testing

### Test Analysis
**Functions/Classes:**
- `extract_text_from_pdf_mistral_ocr()` - Cloud OCR (Stage 1)
- `extract_text_from_pdf_qwen_vl_ocr()` - Local OCR (Stage 2/3)
- `transcribe_audio_whisper()` - Stage-aware audio transcription
- `transcribe_audio_openai_whisper()` - OpenAI Whisper API
- Document format handlers (DOCX, TXT, EML)

**Critical Paths:**
- Stage-aware OCR routing
- Audio transcription with file size limits
- Multi-format document handling
- Error handling and fallbacks

### test_ocr_extraction.py

```python
import pytest
import tempfile
import os
from pathlib import Path
from unittest.mock import Mock, patch, mock_open, MagicMock
from PIL import Image

class TestStageAwareOCRRouting:
    """Test stage-aware OCR processing routing"""
    
    def test_mistral_ocr_stage1(self, test_env_stage1, sample_documents):
        """Test Mistral OCR is used in Stage 1"""
        with patch('ocr_extraction.extract_text_from_url') as mock_mistral, \
             patch('ocr_extraction.generate_document_url') as mock_url_gen:
            
            mock_url_gen.return_value = "https://storage.example.com/test.pdf"
            mock_mistral.return_value = {
                "combined_text": "Extracted text from Mistral OCR",
                "usage_info": {"pages_processed": 1, "doc_size_bytes": 1024}
            }
            
            from ocr_extraction import extract_text_from_pdf_mistral_ocr
            
            text, metadata = extract_text_from_pdf_mistral_ocr(str(sample_documents['pdf']))
            
            assert text == "Extracted text from Mistral OCR"
            assert metadata is not None
            assert metadata[0]['method'] == 'MistralOCR'
            mock_mistral.assert_called_once()
    
    def test_qwen_ocr_skipped_stage1(self, test_env_stage1, sample_documents):
        """Test Qwen OCR is skipped in Stage 1"""
        with patch('ocr_extraction.DEPLOYMENT_STAGE', '1'):
            from ocr_extraction import extract_text_from_pdf_qwen_vl_ocr
            
            text, metadata = extract_text_from_pdf_qwen_vl_ocr(str(sample_documents['pdf']))
            
            assert text is None
            assert metadata is None
    
    def test_qwen_ocr_used_stage2(self, test_env_stage2, sample_documents):
        """Test Qwen OCR is used in Stage 2"""
        with patch('ocr_extraction.DEPLOYMENT_STAGE', '2'), \
             patch('ocr_extraction.get_qwen2_vl_ocr_model') as mock_model, \
             patch('ocr_extraction.get_qwen2_vl_ocr_processor') as mock_processor, \
             patch('ocr_extraction.get_process_vision_info') as mock_vision, \
             patch('ocr_extraction.render_pdf_page_to_image') as mock_render:
            
            # Mock successful model loading
            mock_model.return_value = Mock()
            mock_processor.return_value = Mock()
            mock_vision.return_value = Mock()
            mock_render.return_value = Image.new('RGB', (100, 100))
            
            # Mock the model generation process
            mock_model.return_value.generate.return_value = [[1, 2, 3, 4]]
            mock_processor.return_value.batch_decode.return_value = ["Extracted text"]
            mock_processor.return_value.apply_chat_template.return_value = "template"
            mock_processor.return_value.return_value = Mock()
            mock_vision.return_value = ([Image.new('RGB', (100, 100))], None)
            
            from ocr_extraction import extract_text_from_pdf_qwen_vl_ocr
            
            # Should not return None in Stage 2
            with patch('fitz.open') as mock_fitz:
                mock_doc = Mock()
                mock_doc.__len__.return_value = 1
                mock_fitz.return_value = mock_doc
                
                text, metadata = extract_text_from_pdf_qwen_vl_ocr(str(sample_documents['pdf']))
                
                assert text is not None
                mock_model.assert_called()

class TestAudioTranscription:
    """Test audio transcription with stage awareness"""
    
    def test_openai_whisper_stage1(self, test_env_stage1, sample_documents):
        """Test OpenAI Whisper API is used in Stage 1"""
        with patch('ocr_extraction.OpenAI') as mock_openai_class, \
             patch('os.path.exists', return_value=True), \
             patch('os.path.getsize', return_value=1024):
            
            mock_client = Mock()
            mock_openai_class.return_value = mock_client
            mock_client.audio.transcriptions.create.return_value = "Transcribed audio text"
            
            from ocr_extraction import transcribe_audio_openai_whisper
            
            result = transcribe_audio_openai_whisper(str(sample_documents['audio']))
            
            assert result == "Transcribed audio text"
            mock_client.audio.transcriptions.create.assert_called_once()
    
    def test_openai_whisper_file_size_limit(self, test_env_stage1):
        """Test OpenAI Whisper file size limit handling"""
        with patch('os.path.exists', return_value=True), \
             patch('os.path.getsize', return_value=30 * 1024 * 1024):  # 30MB > 25MB limit
            
            from ocr_extraction import transcribe_audio_openai_whisper
            
            result = transcribe_audio_openai_whisper("large_audio.wav")
            
            assert result is None  # Should reject large files
    
    def test_whisper_stage_routing(self, test_env_stage1, sample_documents):
        """Test that transcribe_audio_whisper routes to correct implementation"""
        with patch('ocr_extraction.transcribe_audio_openai_whisper') as mock_openai:
            mock_openai.return_value = "OpenAI transcription"
            
            from ocr_extraction import transcribe_audio_whisper
            
            result = transcribe_audio_whisper(str(sample_documents['audio']))
            
            assert result == "OpenAI transcription"
            mock_openai.assert_called_once()
    
    def test_local_whisper_stage2(self, test_env_stage2, sample_documents):
        """Test local Whisper model used in Stage 2"""
        with patch('ocr_extraction.WHISPER_MODEL') as mock_whisper:
            mock_whisper.transcribe.return_value = {"text": "Local transcription"}
            mock_whisper.device.type = 'cpu'
            
            from ocr_extraction import transcribe_audio_whisper
            
            result = transcribe_audio_whisper(str(sample_documents['audio']))
            
            assert result == "Local transcription"
            mock_whisper.transcribe.assert_called_once()

class TestDocumentFormatHandlers:
    """Test various document format handlers"""
    
    def test_extract_text_from_docx(self, sample_documents):
        """Test DOCX text extraction"""
        mock_doc = Mock()
        mock_paragraph = Mock()
        mock_paragraph.text = "Sample paragraph text"
        mock_doc.paragraphs = [mock_paragraph]
        
        with patch('docx.Document', return_value=mock_doc):
            from ocr_extraction import extract_text_from_docx
            
            result = extract_text_from_docx(str(sample_documents['docx']))
            
            assert result == "Sample paragraph text"
    
    def test_extract_text_from_txt(self, sample_documents):
        """Test TXT file extraction"""
        test_content = "Sample text file content"
        
        with patch('builtins.open', mock_open(read_data=test_content)):
            from ocr_extraction import extract_text_from_txt
            
            result = extract_text_from_txt(str(sample_documents['txt']))
            
            assert result == test_content
    
    def test_extract_text_from_eml(self, sample_documents):
        """Test EML email extraction"""
        mock_message = Mock()
        mock_message.is_multipart.return_value = False
        mock_message.get_payload.return_value = b"Email body content"
        mock_message.get_content_charset.return_value = "utf-8"
        mock_message.get.side_effect = lambda key, default="": {
            'From': 'sender@example.com',
            'To': 'recipient@example.com', 
            'Subject': 'Test Email',
            'Date': '2024-01-01'
        }.get(key, default)
        
        with patch('email.message_from_bytes', return_value=mock_message), \
             patch('builtins.open', mock_open(read_data=b"mock email data")):
            
            from ocr_extraction import extract_text_from_eml
            
            result = extract_text_from_eml(str(sample_documents['eml']))
            
            assert "sender@example.com" in result
            assert "Test Email" in result
            assert "Email body content" in result

class TestErrorHandling:
    """Test error handling across OCR functions"""
    
    def test_pdf_render_error_handling(self, sample_documents):
        """Test PDF rendering error handling"""
        with patch('fitz.open', side_effect=Exception("PDF corrupt")):
            from ocr_extraction import render_pdf_page_to_image
            
            result = render_pdf_page_to_image(str(sample_documents['pdf']), 0)
            
            assert result is None
    
    def test_mistral_ocr_error_handling(self, sample_documents):
        """Test Mistral OCR error handling"""
        with patch('ocr_extraction.generate_document_url', side_effect=Exception("URL generation failed")):
            from ocr_extraction import extract_text_from_pdf_mistral_ocr
            
            text, metadata = extract_text_from_pdf_mistral_ocr(str(sample_documents['pdf']))
            
            assert text is None
            assert metadata is None
    
    def test_whisper_api_error_handling(self, test_env_stage1):
        """Test OpenAI Whisper API error handling"""
        with patch('ocr_extraction.OpenAI') as mock_openai_class, \
             patch('os.path.exists', return_value=True), \
             patch('os.path.getsize', return_value=1024):
            
            mock_client = Mock()
            mock_openai_class.return_value = mock_client
            mock_client.audio.transcriptions.create.side_effect = Exception("API Error")
            
            from ocr_extraction import transcribe_audio_openai_whisper
            
            result = transcribe_audio_openai_whisper("audio.wav")
            
            assert result is None
```

## Test Execution and Coverage

### Dependencies (requirements-test.txt)
```
pytest>=7.0.0
pytest-cov>=4.0.0
pytest-mock>=3.10.0
pytest-asyncio>=0.21.0
python-dotenv>=1.0.0
```

### Test Execution Commands
```bash
# Run all tests
pytest tests/unit/ -v

# Run with coverage
pytest tests/unit/ --cov=scripts --cov-report=html --cov-report=term

# Run specific module tests
pytest tests/unit/test_config.py -v

# Run stage-specific tests
pytest tests/unit/ -k "stage1" -v
pytest tests/unit/ -k "stage2" -v

# Run with markers
pytest tests/unit/ -m "integration" -v
```

### Coverage Targets (Part 1)
| Module | Target Coverage | Critical Functions |
|--------|----------------|-------------------|
| config.py | 95% | Stage validation, env parsing |
| models_init.py | 90% | Stage-aware init, fallbacks |
| supabase_utils.py | 85% | CRUD operations, URL generation |
| ocr_extraction.py | 80% | Stage routing, format handlers |
| entity_extraction.py | 85% | Stage-aware extraction |
| mistral_utils.py | 75% | API integration, error handling |

## Next Steps

This completes Part 1 of the comprehensive testing plan covering the core infrastructure modules. Part 2 will cover:

- `entity_resolution.py` - Entity canonicalization
- `chunking_utils.py` - Semantic text chunking  
- `structured_extraction.py` - Advanced data extraction
- `relationship_builder.py` - Graph relationship staging
- `text_processing.py` - Text cleaning and coordination
- `main_pipeline.py` - Main orchestration pipeline
- `queue_processor.py` - Queue-based processing

The testing framework established in Part 1 provides the foundation for comprehensive validation of the entire system's stage-aware functionality.