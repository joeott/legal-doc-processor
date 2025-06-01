# Stage 1 Cloud Services Implementation Plan

## Overview

This document provides a comprehensive implementation plan for the critical Stage 1 cloud services identified in the testing gap analysis. These implementations will enable the system to operate in cloud-only mode using OpenAI and Mistral services, bypassing all local models.

## Components to Implement

### 1. Entity Extraction - OpenAI Implementation
**File**: `entity_extraction.py`  
**Function**: `extract_entities_openai()`

### 2. Audio Transcription - OpenAI Whisper
**File**: `ocr_extraction.py`  
**Function**: `transcribe_audio_openai_whisper()`

### 3. Model Initialization - Stage-Aware Bypass
**File**: `models_init.py`  
**Updates**: Stage-aware model loading logic

### 4. Pipeline Validation - Stage 1 Requirements
**File**: `main_pipeline.py`  
**Function**: `validate_stage1_requirements()`

## Implementation Details

### 1. Entity Extraction with OpenAI

#### Current State Analysis
- Currently only supports local BERT NER pipeline
- No cloud fallback mechanism exists
- Function `extract_entities_from_chunk()` assumes local model availability

#### Implementation Plan

```python
def extract_entities_openai(chunk_text: str, chunk_id: int = None) -> list[dict]:
    """
    Extract named entities using OpenAI GPT-4 for Stage 1 deployment.
    
    Args:
        chunk_text: Text to extract entities from
        chunk_id: Optional chunk identifier for logging
        
    Returns:
        List of entities in standard format:
        [{"entity": str, "label": str, "start": int, "end": int, "score": float}]
    """
```

#### Key Features
1. **Structured Output**: Use GPT-4's JSON mode for reliable entity extraction
2. **Legal Entity Focus**: Specialized prompt for legal document entities
3. **Entity Types**: PERSON, ORG, GPE, DATE, MONEY, LAW, CASE, OTHER
4. **Position Tracking**: Approximate start/end positions for compatibility
5. **Error Handling**: Graceful fallback with empty list on failure

#### Testing Requirements
- Mock OpenAI API responses
- Test JSON parsing and validation
- Verify entity format compatibility
- Test error scenarios (API failures, malformed responses)

### 2. Audio Transcription with OpenAI Whisper

#### Current State Analysis
- Currently uses local Whisper model only
- No cloud transcription fallback
- Function `transcribe_audio_whisper()` loads local model

#### Implementation Plan

```python
def transcribe_audio_openai_whisper(audio_path: str) -> str | None:
    """
    Transcribe audio using OpenAI Whisper API for Stage 1 deployment.
    
    Args:
        audio_path: Path to audio file
        
    Returns:
        Transcribed text or None on failure
    """
```

#### Key Features
1. **File Upload**: Handle audio file upload to OpenAI API
2. **Format Support**: Support common audio formats (mp3, wav, m4a, etc.)
3. **Size Limits**: Handle OpenAI's 25MB file size limit
4. **Error Handling**: Graceful degradation on API failures
5. **Integration**: Seamless replacement for local Whisper

#### Testing Requirements
- Mock file upload operations
- Test various audio formats
- Verify transcription quality
- Test file size limits and chunking

### 3. Model Initialization Updates

#### Current State Analysis
- `models_init.py` loads all models unconditionally
- No stage awareness in initialization
- Memory intensive for Stage 1 deployment

#### Implementation Plan

```python
def should_load_local_models() -> bool:
    """Determine if local models should be loaded based on deployment stage."""
    from config import DEPLOYMENT_STAGE, BYPASS_LOCAL_MODELS
    
    if DEPLOYMENT_STAGE == "1":
        return False
    return not BYPASS_LOCAL_MODELS

# Update each initialization function:
def initialize_qwen2_vl_ocr_model(device: str) -> None:
    if not should_load_local_models():
        logger.info(f"Stage {DEPLOYMENT_STAGE}: Bypassing Qwen2-VL model")
        global QWEN2_VL_OCR_MODEL
        QWEN2_VL_OCR_MODEL = None
        return
    # ... existing initialization code
```

#### Key Features
1. **Conditional Loading**: Skip model loading for Stage 1
2. **Clear Logging**: Log bypass decisions for debugging
3. **Global State**: Set model variables to None when bypassed
4. **Validation**: Add cloud API key validation function

#### Testing Requirements
- Test model bypass in Stage 1
- Verify models load in Stage 2/3
- Test stage transitions
- Validate memory usage reduction

### 4. Pipeline Validation

#### Current State Analysis
- No Stage 1 specific validation exists
- Pipeline assumes all models available
- No pre-flight checks for cloud services

#### Implementation Plan

```python
def validate_stage1_requirements():
    """
    Validate Stage 1 deployment requirements before processing.
    
    Raises:
        ValueError: If required cloud services are not configured
    """
    from config import OPENAI_API_KEY, MISTRAL_API_KEY, USE_OPENAI_FOR_ENTITY_EXTRACTION
    
    errors = []
    
    if not OPENAI_API_KEY:
        errors.append("OPENAI_API_KEY required for Stage 1 entity extraction")
        
    if not MISTRAL_API_KEY:
        errors.append("MISTRAL_API_KEY required for Stage 1 OCR processing")
        
    if not USE_OPENAI_FOR_ENTITY_EXTRACTION:
        errors.append("USE_OPENAI_FOR_ENTITY_EXTRACTION must be True for Stage 1")
        
    if errors:
        raise ValueError("Stage 1 validation failed:\n" + "\n".join(errors))
        
    logger.info("Stage 1 requirements validated successfully")
```

#### Key Features
1. **API Key Validation**: Ensure required keys present
2. **Configuration Check**: Verify stage-appropriate settings
3. **Clear Error Messages**: Detailed validation failures
4. **Pre-flight Check**: Run before document processing

#### Testing Requirements
- Test with missing API keys
- Test with incorrect configuration
- Verify error message clarity
- Test successful validation

## Implementation Order

### Phase 1: Model Initialization (1-2 hours)
1. Implement `should_load_local_models()` function
2. Update all model initialization functions
3. Add cloud API validation
4. Write comprehensive tests

### Phase 2: OpenAI Entity Extraction (2-3 hours)
1. Implement `extract_entities_openai()` function
2. Update `extract_entities_from_chunk()` with stage routing
3. Create structured prompts for legal entities
4. Write unit tests with mocked responses

### Phase 3: OpenAI Whisper Integration (1-2 hours)
1. Implement `transcribe_audio_openai_whisper()` function
2. Update audio processing routing
3. Handle file uploads and size limits
4. Write tests for audio transcription

### Phase 4: Pipeline Validation (1 hour)
1. Implement `validate_stage1_requirements()` function
2. Integrate into `main_pipeline.py`
3. Update `process_single_document()` flow
4. Write validation tests

## Testing Strategy

### Unit Tests Required
1. **models_init.py** (4 tests)
   - Test stage 1 bypass behavior
   - Test stage 2/3 normal loading
   - Test API validation
   - Test stage transitions

2. **entity_extraction.py** (6 tests)
   - Test OpenAI entity extraction
   - Test JSON parsing
   - Test error handling
   - Test stage routing
   - Test entity format compatibility
   - Test empty/null inputs

3. **ocr_extraction.py** (4 tests)
   - Test OpenAI Whisper transcription
   - Test file upload handling
   - Test size limit handling
   - Test error scenarios

4. **main_pipeline.py** (3 tests)
   - Test stage 1 validation success
   - Test validation failures
   - Test integration with pipeline

### Integration Tests
1. End-to-end Stage 1 document processing
2. Cloud service error recovery
3. Performance benchmarking
4. Cost tracking validation

## Success Metrics

1. **Functionality**
   - All Stage 1 tests passing (100%)
   - No local models loaded in Stage 1
   - Cloud services properly integrated

2. **Performance**
   - Document processing < 5 minutes
   - Memory usage < 2GB (no local models)
   - API response times < 30 seconds

3. **Reliability**
   - Graceful error handling
   - Clear error messages
   - Proper logging throughout

4. **Code Quality**
   - 90%+ test coverage for new code
   - Type hints on all functions
   - Comprehensive documentation

## Risk Mitigation

### API Rate Limits
- Implement exponential backoff
- Add rate limiting logic
- Monitor usage patterns

### Cost Management
- Track API calls per document
- Implement cost estimation
- Add usage warnings

### Error Recovery
- Implement retry logic
- Provide clear error messages
- Log all API interactions

### Testing Challenges
- Mock complex API responses
- Simulate network failures
- Test timeout scenarios

## Dependencies

### External Libraries
```python
# Required for OpenAI integration
openai>=1.0.0
```

### Environment Variables
```
DEPLOYMENT_STAGE=1
OPENAI_API_KEY=<your-key>
MISTRAL_API_KEY=<your-key>
USE_OPENAI_FOR_ENTITY_EXTRACTION=true
USE_OPENAI_FOR_AUDIO_TRANSCRIPTION=true
```

## Next Steps

After implementing these components:
1. Run comprehensive Stage 1 integration tests
2. Benchmark performance vs local models
3. Monitor API costs and usage
4. Document deployment procedures
5. Prepare Stage 2 hybrid implementation

This implementation will complete the critical gaps for Stage 1 deployment, enabling fully cloud-based document processing without local model dependencies.