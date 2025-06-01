# Stage 1 Testing Implementation Plan

## Overview

This document provides a step-by-step implementation guide for creating and executing the Stage 1 (OpenAI-first, cloud-only) testing suite for the legal document processing system. This focuses exclusively on validating the cloud-based deployment without local model dependencies.

## Objectives

- Validate Stage 1 cloud-only functionality
- Ensure OpenAI API integration works correctly
- Verify Mistral OCR API integration
- Test stage-aware component behavior
- Validate fallback mechanisms
- Establish CI/CD pipeline for automated testing

## Implementation Steps

### Phase 1: Environment Setup

#### Step 1.1: Create Test Directory Structure
```bash
cd /Users/josephott/Documents/phase_1_2_3_process_v5

# Create test directory structure
mkdir -p tests/{unit,integration,fixtures/{documents,mock_responses,test_data},mocks}

# Create test configuration files
touch tests/conftest.py
touch tests/requirements-test.txt

# Create individual test modules
touch tests/unit/test_config.py
touch tests/unit/test_models_init.py
touch tests/unit/test_supabase_utils.py
touch tests/unit/test_ocr_extraction.py
touch tests/unit/test_entity_extraction.py
touch tests/unit/test_mistral_utils.py
touch tests/unit/test_entity_resolution.py
touch tests/unit/test_chunking_utils.py
touch tests/unit/test_structured_extraction.py
touch tests/unit/test_relationship_builder.py
touch tests/unit/test_text_processing.py
touch tests/unit/test_main_pipeline.py

# Create mock modules
touch tests/mocks/mock_models.py
touch tests/mocks/mock_api_clients.py
touch tests/mocks/mock_database.py

# Create integration test
touch tests/integration/test_stage1_pipeline.py
```

#### Step 1.2: Install Test Dependencies
```bash
# Create requirements-test.txt
cat > tests/requirements-test.txt << 'EOF'
pytest>=7.0.0
pytest-cov>=4.0.0
pytest-mock>=3.10.0
pytest-asyncio>=0.21.0
pytest-xdist>=3.0.0
pytest-env>=0.8.0
python-dotenv>=1.0.0
responses>=0.23.0
factory-boy>=3.2.0
faker>=18.0.0
freezegun>=1.2.0
EOF

# Install test dependencies
pip install -r tests/requirements-test.txt
```

#### Step 1.3: Create Test Environment Configuration
```bash
# Create .env.test file for Stage 1 testing
cat > .env.test << 'EOF'
# Stage 1 Configuration
DEPLOYMENT_STAGE=1
FORCE_CLOUD_LLMS=true
BYPASS_LOCAL_MODELS=true

# Required API Keys (use test keys)
OPENAI_API_KEY=test-openai-key
MISTRAL_API_KEY=test-mistral-key

# Supabase Configuration (use test instance)
SUPABASE_URL=https://test-project.supabase.co
SUPABASE_ANON_KEY=test-anon-key

# Model Configuration
LLM_MODEL_FOR_RESOLUTION=gpt-4o-mini
USE_MISTRAL_FOR_OCR=true

# Disable local model paths
SOURCE_DOCUMENT_DIR=/tmp/test_docs
S3_TEMP_DOWNLOAD_DIR=/tmp/test_s3
EOF
```

### Phase 2: Core Test Infrastructure

#### Step 2.1: Create Shared Test Configuration
```python
# tests/conftest.py
import pytest
import os
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch
import sys

# Add scripts directory to Python path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """Set up test environment variables for all tests"""
    os.environ.update({
        "DEPLOYMENT_STAGE": "1",
        "FORCE_CLOUD_LLMS": "true", 
        "BYPASS_LOCAL_MODELS": "true",
        "OPENAI_API_KEY": "test-openai-key",
        "MISTRAL_API_KEY": "test-mistral-key",
        "SUPABASE_URL": "https://test.supabase.co",
        "SUPABASE_ANON_KEY": "test-anon-key",
        "LLM_MODEL_FOR_RESOLUTION": "gpt-4o-mini",
        "USE_MISTRAL_FOR_OCR": "true"
    })

@pytest.fixture
def test_env_stage1(monkeypatch):
    """Ensure Stage 1 environment for specific tests"""
    monkeypatch.setenv("DEPLOYMENT_STAGE", "1")
    monkeypatch.setenv("FORCE_CLOUD_LLMS", "true")
    monkeypatch.setenv("BYPASS_LOCAL_MODELS", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("MISTRAL_API_KEY", "test-mistral-key")

@pytest.fixture
def sample_documents():
    """Create sample test documents"""
    fixtures_dir = Path(__file__).parent / "fixtures" / "documents"
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    
    # Create sample PDF content (mock file)
    pdf_path = fixtures_dir / "sample.pdf"
    pdf_path.write_text("Mock PDF content for testing")
    
    # Create sample text file
    txt_path = fixtures_dir / "sample.txt"
    txt_path.write_text("This is a sample text document for testing.")
    
    # Create sample audio file (mock)
    audio_path = fixtures_dir / "sample.wav"
    audio_path.write_bytes(b"Mock audio content")
    
    return {
        'pdf': str(pdf_path),
        'txt': str(txt_path),
        'audio': str(audio_path)
    }

@pytest.fixture
def mock_openai_responses():
    """Mock OpenAI API responses"""
    return {
        "entity_extraction": {
            "choices": [{
                "message": {
                    "content": json.dumps([
                        {"entity_value": "John Doe", "entity_type": "PERSON", "confidence": 0.95},
                        {"entity_value": "ACME Corp", "entity_type": "ORGANIZATION", "confidence": 0.87}
                    ])
                }
            }]
        },
        "structured_extraction": {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "document_metadata": {"type": "contract", "parties": ["John Doe", "ACME Corp"]},
                        "key_facts": [{"fact": "Contract signed", "confidence": 0.9}],
                        "entities": {"persons": ["John Doe"], "organizations": ["ACME Corp"]},
                        "relationships": []
                    })
                }
            }]
        }
    }

@pytest.fixture
def mock_mistral_responses():
    """Mock Mistral OCR API responses"""
    return {
        "ocr_success": {
            "combined_text": "Sample document text extracted by Mistral OCR",
            "usage_info": {"pages_processed": 1, "doc_size_bytes": 1024}
        }
    }
```

#### Step 2.2: Create Mock API Clients
```python
# tests/mocks/mock_api_clients.py
from unittest.mock import Mock
import json

class MockOpenAIClient:
    """Mock OpenAI client for testing"""
    
    def __init__(self, responses=None):
        self.responses = responses or {}
        self.chat = Mock()
        self.audio = Mock()
        self.setup_mocks()
    
    def setup_mocks(self):
        """Set up mock responses"""
        # Chat completions mock
        self.chat.completions = Mock()
        self.chat.completions.create = Mock()
        
        # Audio transcriptions mock  
        self.audio.transcriptions = Mock()
        self.audio.transcriptions.create = Mock(return_value="Mock transcription")
    
    def set_response(self, response_type, response_data):
        """Set specific mock response"""
        if response_type == "chat":
            self.chat.completions.create.return_value = Mock(
                choices=[Mock(message=Mock(content=json.dumps(response_data)))]
            )
        elif response_type == "audio":
            self.audio.transcriptions.create.return_value = response_data

class MockMistralClient:
    """Mock Mistral client for testing"""
    
    def __init__(self, responses=None):
        self.responses = responses or {
            "combined_text": "Mock OCR text",
            "usage_info": {"pages_processed": 1}
        }
    
    def extract_text_from_url(self, url, filename):
        """Mock OCR extraction"""
        return self.responses

class MockSupabaseClient:
    """Mock Supabase client for testing"""
    
    def __init__(self):
        self.table_data = {}
        self.storage = Mock()
        self.setup_storage_mock()
    
    def setup_storage_mock(self):
        """Set up storage mock"""
        self.storage.from_ = Mock()
        self.storage.from_.return_value.get_public_url = Mock(
            return_value="https://mock-storage.url/file.pdf"
        )
    
    def table(self, table_name):
        """Mock table operations"""
        mock_table = Mock()
        mock_table.insert = Mock()
        mock_table.insert.return_value.execute = Mock()
        mock_table.insert.return_value.execute.return_value = Mock(
            data=[{"id": 1, "document_uuid": "test-uuid"}]
        )
        return mock_table
```

#### Step 2.3: Create Mock Database Manager
```python
# tests/mocks/mock_database.py
from unittest.mock import Mock
import uuid

class MockSupabaseManager:
    """Mock database manager for testing"""
    
    def __init__(self):
        self.tables = {
            'source_documents': [],
            'chunks': [],
            'entity_mentions': [],
            'relationships': []
        }
        self.id_counter = 1
    
    def create_source_document_entry(self, **kwargs):
        """Mock source document creation"""
        doc_id = self.id_counter
        doc_uuid = str(uuid.uuid4())
        
        entry = {
            'id': doc_id,
            'document_uuid': doc_uuid,
            **kwargs
        }
        self.tables['source_documents'].append(entry)
        self.id_counter += 1
        
        return doc_id, doc_uuid
    
    def create_chunk_entry(self, **kwargs):
        """Mock chunk creation"""
        chunk_id = self.id_counter
        entry = {'id': chunk_id, **kwargs}
        self.tables['chunks'].append(entry)
        self.id_counter += 1
        return chunk_id
    
    def create_entity_mention_entry(self, **kwargs):
        """Mock entity mention creation"""
        entity_id = self.id_counter
        entry = {'id': entity_id, **kwargs}
        self.tables['entity_mentions'].append(entry)
        self.id_counter += 1
        return entity_id
    
    def stage_relationship(self, **kwargs):
        """Mock relationship staging"""
        rel_id = str(uuid.uuid4())
        entry = {'id': rel_id, **kwargs}
        self.tables['relationships'].append(entry)
        return True
    
    def create_neo4j_document_entry(self, **kwargs):
        """Mock Neo4j document creation"""
        return str(uuid.uuid4())
```

### Phase 3: Core Module Tests

#### Step 3.1: Configuration Testing
```python
# tests/unit/test_config.py
import pytest
import os
import importlib
from unittest.mock import patch

class TestStage1Configuration:
    """Test Stage 1 configuration validation"""
    
    def test_stage1_environment_setup(self, test_env_stage1):
        """Test Stage 1 environment is properly configured"""
        # Force reload config to pick up test environment
        if 'config' in sys.modules:
            importlib.reload(sys.modules['config'])
        
        import config
        
        assert config.DEPLOYMENT_STAGE == "1"
        assert config.FORCE_CLOUD_LLMS == True
        assert config.BYPASS_LOCAL_MODELS == True
        assert config.OPENAI_API_KEY == "test-openai-key"
        assert config.MISTRAL_API_KEY == "test-mistral-key"
    
    def test_stage1_api_key_validation(self, test_env_stage1):
        """Test that Stage 1 requires OpenAI and Mistral API keys"""
        import config
        
        # Should have required keys for Stage 1
        assert config.OPENAI_API_KEY is not None
        assert config.MISTRAL_API_KEY is not None
        assert config.USE_MISTRAL_FOR_OCR == True
    
    def test_local_model_bypass_configuration(self, test_env_stage1):
        """Test that local model settings are bypassed in Stage 1"""
        import config
        
        assert config.BYPASS_LOCAL_MODELS == True
        assert config.FORCE_CLOUD_LLMS == True
```

#### Step 3.2: Model Initialization Testing
```python
# tests/unit/test_models_init.py
import pytest
from unittest.mock import patch, Mock

class TestStage1ModelInitialization:
    """Test Stage 1 model initialization behavior"""
    
    def test_stage1_bypasses_local_models(self, test_env_stage1):
        """Test that Stage 1 skips local model loading"""
        with patch('models_init.DEPLOYMENT_STAGE', '1'):
            from models_init import should_load_local_models
            
            assert should_load_local_models() == False
    
    def test_stage1_model_accessors_return_none(self, test_env_stage1):
        """Test that model accessors return None in Stage 1"""
        with patch('models_init.DEPLOYMENT_STAGE', '1'):
            from models_init import (
                get_qwen2_vl_ocr_model, 
                get_whisper_model,
                get_ner_pipeline
            )
            
            assert get_qwen2_vl_ocr_model() is None
            assert get_whisper_model() is None  
            assert get_ner_pipeline() is None
    
    def test_stage1_api_key_validation(self, test_env_stage1):
        """Test API key validation for Stage 1"""
        with patch('models_init.DEPLOYMENT_STAGE', '1'), \
             patch('models_init.OPENAI_API_KEY', 'test-key'), \
             patch('models_init.MISTRAL_API_KEY', 'test-key'):
            
            from models_init import validate_cloud_api_keys
            
            # Should not raise exception with valid keys
            validate_cloud_api_keys()
    
    def test_stage1_missing_api_keys_raises_error(self):
        """Test that missing API keys raise validation errors"""
        with patch('models_init.DEPLOYMENT_STAGE', '1'), \
             patch('models_init.OPENAI_API_KEY', None):
            
            from models_init import validate_cloud_api_keys
            
            with pytest.raises(ValueError, match="OPENAI_API_KEY"):
                validate_cloud_api_keys()
```

#### Step 3.3: Entity Extraction Testing
```python
# tests/unit/test_entity_extraction.py
import pytest
from unittest.mock import Mock, patch
import json

class TestStage1EntityExtraction:
    """Test Stage 1 entity extraction using OpenAI"""
    
    def test_stage1_uses_openai_extraction(self, test_env_stage1, mock_openai_responses):
        """Test that Stage 1 uses OpenAI for entity extraction"""
        with patch('entity_extraction.OpenAI') as mock_openai_class:
            mock_client = Mock()
            mock_openai_class.return_value = mock_client
            mock_client.chat.completions.create.return_value = Mock(
                choices=[Mock(message=Mock(
                    content=mock_openai_responses["entity_extraction"]["choices"][0]["message"]["content"]
                ))]
            )
            
            from entity_extraction import extract_entities_from_chunk
            
            result = extract_entities_from_chunk("John Doe works at ACME Corp", chunk_id=1)
            
            assert len(result) > 0
            assert any(entity['entity_value'] == 'John Doe' for entity in result)
            assert any(entity['entity_type'] == 'PERSON' for entity in result)
            mock_client.chat.completions.create.assert_called_once()
    
    def test_stage1_bypasses_local_ner(self, test_env_stage1):
        """Test that Stage 1 bypasses local NER pipeline"""
        with patch('entity_extraction.DEPLOYMENT_STAGE', '1'):
            from entity_extraction import extract_entities_local_ner
            
            # Should return empty result or None for Stage 1
            result = extract_entities_local_ner("Test text", chunk_id=1)
            assert result == [] or result is None
    
    def test_openai_api_error_handling(self, test_env_stage1):
        """Test error handling when OpenAI API fails"""
        with patch('entity_extraction.OpenAI') as mock_openai_class:
            mock_client = Mock()
            mock_openai_class.return_value = mock_client
            mock_client.chat.completions.create.side_effect = Exception("API Error")
            
            from entity_extraction import extract_entities_openai
            
            result = extract_entities_openai("Test text", chunk_id=1)
            
            # Should handle error gracefully
            assert result == []
```

#### Step 3.4: OCR Extraction Testing
```python
# tests/unit/test_ocr_extraction.py
import pytest
from unittest.mock import Mock, patch
import os

class TestStage1OCRExtraction:
    """Test Stage 1 OCR extraction using Mistral"""
    
    def test_stage1_uses_mistral_ocr(self, test_env_stage1, mock_mistral_responses, sample_documents):
        """Test that Stage 1 uses Mistral OCR"""
        with patch('ocr_extraction.extract_text_from_url') as mock_mistral_ocr, \
             patch('ocr_extraction.generate_document_url') as mock_url_gen:
            
            mock_url_gen.return_value = "https://storage.test.com/sample.pdf"
            mock_mistral_ocr.return_value = mock_mistral_responses["ocr_success"]
            
            from ocr_extraction import extract_text_from_pdf_mistral_ocr
            
            text, metadata = extract_text_from_pdf_mistral_ocr(sample_documents['pdf'])
            
            assert text == "Sample document text extracted by Mistral OCR"
            assert metadata is not None
            assert metadata[0]['method'] == 'MistralOCR'
            mock_mistral_ocr.assert_called_once()
    
    def test_stage1_bypasses_qwen_ocr(self, test_env_stage1, sample_documents):
        """Test that Stage 1 bypasses Qwen OCR"""
        with patch('ocr_extraction.DEPLOYMENT_STAGE', '1'):
            from ocr_extraction import extract_text_from_pdf_qwen_vl_ocr
            
            text, metadata = extract_text_from_pdf_qwen_vl_ocr(sample_documents['pdf'])
            
            assert text is None
            assert metadata is None
    
    def test_stage1_openai_whisper_transcription(self, test_env_stage1, sample_documents):
        """Test Stage 1 uses OpenAI Whisper for audio transcription"""
        with patch('ocr_extraction.OpenAI') as mock_openai_class, \
             patch('os.path.exists', return_value=True), \
             patch('os.path.getsize', return_value=1024 * 1024):  # 1MB file
            
            mock_client = Mock()
            mock_openai_class.return_value = mock_client
            mock_client.audio.transcriptions.create.return_value = "Transcribed audio content"
            
            from ocr_extraction import transcribe_audio_openai_whisper
            
            result = transcribe_audio_openai_whisper(sample_documents['audio'])
            
            assert result == "Transcribed audio content"
            mock_client.audio.transcriptions.create.assert_called_once()
    
    def test_openai_whisper_file_size_limit(self, test_env_stage1):
        """Test OpenAI Whisper file size limit (25MB)"""
        with patch('os.path.exists', return_value=True), \
             patch('os.path.getsize', return_value=30 * 1024 * 1024):  # 30MB > 25MB limit
            
            from ocr_extraction import transcribe_audio_openai_whisper
            
            result = transcribe_audio_openai_whisper("large_audio.wav")
            
            assert result is None  # Should reject large files
```

### Phase 4: Integration Testing

#### Step 4.1: End-to-End Pipeline Testing
```python
# tests/integration/test_stage1_pipeline.py
import pytest
from unittest.mock import Mock, patch
import sys
from pathlib import Path

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

class TestStage1IntegrationPipeline:
    """Integration tests for Stage 1 cloud-only pipeline"""
    
    def test_complete_document_processing_pipeline(self, test_env_stage1, sample_documents, mock_openai_responses, mock_mistral_responses):
        """Test complete document processing in Stage 1"""
        from tests.mocks.mock_database import MockSupabaseManager
        
        mock_db = MockSupabaseManager()
        
        with patch('main_pipeline.SupabaseManager', return_value=mock_db), \
             patch('main_pipeline.extract_text_from_pdf_mistral_ocr') as mock_ocr, \
             patch('main_pipeline.OpenAI') as mock_openai_class, \
             patch('main_pipeline.extract_text_from_url') as mock_mistral:
            
            # Mock OCR
            mock_ocr.return_value = ("Sample document text", [{"method": "MistralOCR"}])
            mock_mistral.return_value = mock_mistral_responses["ocr_success"]
            
            # Mock OpenAI
            mock_client = Mock()
            mock_openai_class.return_value = mock_client
            mock_client.chat.completions.create.return_value = Mock(
                choices=[Mock(message=Mock(content='[{"entity_value": "John Doe", "entity_type": "PERSON"}]'))]
            )
            
            from main_pipeline import process_single_document
            
            # Process document
            result = process_single_document(
                db_manager=mock_db,
                source_doc_sql_id=1,
                file_path=sample_documents['pdf'],
                file_name="test.pdf", 
                detected_file_type=".pdf",
                project_sql_id=1
            )
            
            # Verify pipeline completed
            assert len(mock_db.tables['source_documents']) > 0
            assert len(mock_db.tables['chunks']) > 0
            assert len(mock_db.tables['entity_mentions']) > 0
            
            # Verify cloud services were used
            mock_ocr.assert_called()
            mock_client.chat.completions.create.assert_called()
    
    def test_stage1_validation_requirements(self, test_env_stage1):
        """Test Stage 1 validation requirements"""
        from main_pipeline import validate_stage1_requirements
        
        # Should pass with proper Stage 1 setup
        validate_stage1_requirements()
    
    def test_stage1_validation_missing_keys(self):
        """Test Stage 1 validation fails with missing keys"""
        with patch.dict(os.environ, {'DEPLOYMENT_STAGE': '1', 'OPENAI_API_KEY': ''}):
            from main_pipeline import validate_stage1_requirements
            
            with pytest.raises(ValueError):
                validate_stage1_requirements()
```

### Phase 5: Test Execution and Validation

#### Step 5.1: Create Test Execution Scripts
```bash
# Create test runner script
cat > run_stage1_tests.sh << 'EOF'
#!/bin/bash

echo "=== Stage 1 Testing Suite ==="
echo "Setting up test environment..."

# Set test environment
export DEPLOYMENT_STAGE=1
export FORCE_CLOUD_LLMS=true
export BYPASS_LOCAL_MODELS=true
export OPENAI_API_KEY=test-openai-key
export MISTRAL_API_KEY=test-mistral-key

# Run tests with coverage
echo "Running Stage 1 unit tests..."
pytest tests/unit/ -v --cov=scripts --cov-report=html --cov-report=term -k "stage1 or Stage1"

echo "Running Stage 1 integration tests..."  
pytest tests/integration/test_stage1_pipeline.py -v

echo "=== Test Results ==="
echo "Coverage report available at htmlcov/index.html"
echo "Stage 1 testing complete!"
EOF

chmod +x run_stage1_tests.sh
```

#### Step 5.2: Create Specific Test Commands
```bash
# Test individual modules
pytest tests/unit/test_config.py -v
pytest tests/unit/test_models_init.py -v  
pytest tests/unit/test_entity_extraction.py -v
pytest tests/unit/test_ocr_extraction.py -v

# Test with coverage
pytest tests/unit/ --cov=scripts --cov-report=html

# Test only Stage 1 functionality
pytest -k "stage1" -v

# Run integration tests
pytest tests/integration/ -v
```

#### Step 5.3: Validate Test Results
```bash
# Expected test results for Stage 1:
# - Configuration tests: 100% pass
# - Model initialization tests: 100% pass (all return None/bypass)
# - Entity extraction tests: 100% pass (OpenAI only)
# - OCR extraction tests: 100% pass (Mistral + OpenAI Whisper)
# - Integration tests: 100% pass (end-to-end pipeline)

# Coverage targets:
# - config.py: >95% coverage
# - models_init.py: >90% coverage (Stage 1 paths)
# - entity_extraction.py: >85% coverage (OpenAI paths)
# - ocr_extraction.py: >80% coverage (Mistral/OpenAI paths)
# - main_pipeline.py: >75% coverage (Stage 1 workflow)
```

### Phase 6: Continuous Integration Setup

#### Step 6.1: Create GitHub Actions Workflow
```yaml
# .github/workflows/stage1-tests.yml
name: Stage 1 Testing Suite

on:
  push:
    branches: [ main, develop ]
  pull_request:
    branches: [ main ]

jobs:
  stage1-tests:
    runs-on: ubuntu-latest
    
    steps:
    - uses: actions/checkout@v3
    
    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.10'
    
    - name: Install dependencies
      run: |
        pip install -r requirements.txt
        pip install -r tests/requirements-test.txt
    
    - name: Run Stage 1 tests
      env:
        DEPLOYMENT_STAGE: 1
        FORCE_CLOUD_LLMS: true
        BYPASS_LOCAL_MODELS: true
        OPENAI_API_KEY: test-openai-key
        MISTRAL_API_KEY: test-mistral-key
        SUPABASE_URL: https://test.supabase.co
        SUPABASE_ANON_KEY: test-anon-key
      run: |
        pytest tests/unit/ -v --cov=scripts --cov-report=xml -k "stage1 or Stage1"
        pytest tests/integration/test_stage1_pipeline.py -v
    
    - name: Upload coverage to Codecov
      uses: codecov/codecov-action@v3
      with:
        file: coverage.xml
        flags: stage1
        name: stage1-coverage
```

### Phase 7: Documentation and Validation

#### Step 7.1: Create Test Documentation
```markdown
# Stage 1 Test Results Documentation

## Test Coverage Summary
- Total tests: 45+
- Stage 1 specific tests: 35+
- Integration tests: 5+
- Expected pass rate: 100%

## Key Validations
✅ Stage 1 configuration properly set
✅ Local models bypassed correctly  
✅ OpenAI API integration working
✅ Mistral OCR API integration working
✅ End-to-end pipeline functional
✅ Error handling robust
✅ Fallback mechanisms operational

## Performance Benchmarks
- Document processing: <30 seconds
- Entity extraction: <5 seconds per chunk
- OCR processing: <60 seconds per document
- Memory usage: <2GB (no local models)
```

#### Step 7.2: Create Troubleshooting Guide
```markdown
# Stage 1 Testing Troubleshooting

## Common Issues

### Import Errors
**Problem**: Module import failures
**Solution**: Ensure scripts directory is in Python path
```bash
export PYTHONPATH="${PYTHONPATH}:/path/to/scripts"
```

### API Mock Failures  
**Problem**: Mock API responses not working
**Solution**: Verify mock setup in conftest.py and individual test files

### Environment Variable Issues
**Problem**: Stage 1 environment not properly set
**Solution**: Check .env.test file and test fixtures

### Coverage Issues
**Problem**: Low test coverage
**Solution**: Add more specific Stage 1 test cases

## Debugging Commands
```bash
# Run single test with verbose output
pytest tests/unit/test_config.py::TestStage1Configuration::test_stage1_environment_setup -v -s

# Run tests with debugging
pytest --pdb tests/unit/test_entity_extraction.py

# Check test discovery
pytest --collect-only tests/unit/
```

## Expected Results
All Stage 1 tests should pass with 100% success rate when:
- Environment properly configured for Stage 1
- All required mock responses set up
- API clients properly mocked
- Stage-aware logic correctly implemented
```

### Phase 8: Execution Checklist

#### Pre-Execution Checklist
- [ ] Test directory structure created
- [ ] Test dependencies installed
- [ ] Test environment configured (.env.test)
- [ ] Mock classes implemented
- [ ] Sample test documents created
- [ ] conftest.py properly configured

#### Test Implementation Checklist
- [ ] config.py tests implemented
- [ ] models_init.py tests implemented  
- [ ] entity_extraction.py tests implemented
- [ ] ocr_extraction.py tests implemented
- [ ] Integration pipeline test implemented
- [ ] Mock API clients working
- [ ] Mock database manager working

#### Execution Checklist
- [ ] Individual unit tests pass
- [ ] Integration tests pass
- [ ] Coverage targets met (>80% overall)
- [ ] No false positives in test results
- [ ] Performance benchmarks met
- [ ] CI/CD pipeline configured and working

#### Validation Checklist
- [ ] Stage 1 configuration correctly identified
- [ ] Local models properly bypassed
- [ ] OpenAI API integration validated
- [ ] Mistral OCR integration validated  
- [ ] End-to-end pipeline functional
- [ ] Error handling robust
- [ ] Documentation complete

## Summary

This implementation plan provides a complete roadmap for implementing Stage 1 testing. The plan focuses exclusively on validating cloud-only functionality while ensuring the stage-aware architecture correctly bypasses local model dependencies.

**Key Success Metrics:**
- 100% test pass rate for Stage 1 functionality
- >80% code coverage for Stage 1 code paths
- <30 second end-to-end processing time
- Zero false positives or test flakiness
- Robust error handling validation
- Complete CI/CD integration

Execute this plan step-by-step to establish a solid testing foundation for the Stage 1 deployment, ensuring reliable cloud-only operation before progressing to hybrid Stage 2/3 implementations.