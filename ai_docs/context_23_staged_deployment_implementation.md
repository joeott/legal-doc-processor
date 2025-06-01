# Staged Deployment Implementation Plan

## Executive Summary

This document provides a comprehensive implementation plan for the three-stage deployment strategy outlined in `context_0_staged_deployment_strategy.md`. Based on the analysis of the entire codebase and the OpenAI Stage 1 proposal in `context_22_openai_stage_1.md`, this plan identifies specific code modifications needed to achieve a fluid cloud transition from local development (Stage 1) through dockerization (Stage 2) to production deployment (Stage 3).

## Current System Architecture Analysis

### ✅ **Cloud-Ready Components** (No Changes Needed)
- **Database Operations**: Supabase integration throughout
- **Mistral OCR**: Primary cloud-based OCR service
- **Entity Resolution** (`entity_resolution.py`): OpenAI-based implementation
- **Frontend**: Static files compatible with cloud hosting
- **Queue System**: Supabase-based queue processor

### ⚠️ **Hybrid Components** (Conditional Changes Needed)
- **Structured Extraction** (`structured_extraction.py`): Supports both OpenAI and local Qwen
- **OCR Fallback**: Mistral primary, Qwen2-VL local fallback
- **Audio Processing**: No current cloud fallback for Whisper

### ❌ **Local-Dependent Components** (Major Changes Required)
- **Entity Extraction** (`entity_extraction.py`): Only local BERT NER pipeline
- **Model Initialization** (`models_init.py`): Loads all local models at startup
- **Main Pipeline** (`main_pipeline.py`): Assumes all models available

## Stage 1: OpenAI-First Implementation

### Core Strategy
Transform the system to use cloud services (primarily OpenAI) for all LLM operations while maintaining the existing pipeline structure. Local models will be bypassed entirely.

### Required Configuration Changes

#### 1. **config.py** - Enhanced Stage Management
```python
# Add to config.py
import os

# Stage Management Configuration
DEPLOYMENT_STAGE = os.getenv("DEPLOYMENT_STAGE", "1")  # 1=OpenAI-first, 2=hybrid, 3=local
FORCE_CLOUD_LLMS = os.getenv("FORCE_CLOUD_LLMS", "true").lower() in ("true", "1", "yes")
BYPASS_LOCAL_MODELS = os.getenv("BYPASS_LOCAL_MODELS", "true").lower() in ("true", "1", "yes")

# Stage 1 Specific Overrides
if DEPLOYMENT_STAGE == "1":
    FORCE_CLOUD_LLMS = True
    BYPASS_LOCAL_MODELS = True
    USE_OPENAI_FOR_STRUCTURED_EXTRACTION = True
    USE_OPENAI_FOR_ENTITY_EXTRACTION = True
    USE_OPENAI_FOR_AUDIO_TRANSCRIPTION = True

# OpenAI Configuration Enhancement
USE_OPENAI_FOR_STRUCTURED_EXTRACTION = os.getenv("USE_OPENAI_FOR_STRUCTURED_EXTRACTION", 
                                                  "true" if DEPLOYMENT_STAGE == "1" else "false").lower() in ("true", "1", "yes")
USE_OPENAI_FOR_ENTITY_EXTRACTION = os.getenv("USE_OPENAI_FOR_ENTITY_EXTRACTION", 
                                              "true" if DEPLOYMENT_STAGE == "1" else "false").lower() in ("true", "1", "yes")
USE_OPENAI_FOR_AUDIO_TRANSCRIPTION = os.getenv("USE_OPENAI_FOR_AUDIO_TRANSCRIPTION", 
                                                "true" if DEPLOYMENT_STAGE == "1" else "false").lower() in ("true", "1", "yes")

# Validation for Stage 1
if DEPLOYMENT_STAGE == "1":
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY is required for Stage 1 deployment")
    if not MISTRAL_API_KEY:
        raise ValueError("MISTRAL_API_KEY is required for Stage 1 OCR processing")
```

### Model Initialization Changes

#### 2. **models_init.py** - Stage-Aware Model Loading
```python
# Add to models_init.py
from config import DEPLOYMENT_STAGE, BYPASS_LOCAL_MODELS, FORCE_CLOUD_LLMS
import logging

logger = logging.getLogger(__name__)

def should_load_local_models() -> bool:
    """Determine if local models should be loaded based on deployment stage."""
    if DEPLOYMENT_STAGE == "1":
        return False
    return not BYPASS_LOCAL_MODELS

def initialize_qwen2_vl_ocr_model(device: str) -> None:
    global QWEN2_VL_OCR_MODEL, QWEN2_VL_OCR_PROCESSOR, QWEN2_VL_OCR_DEVICE, PROCESS_VISION_INFO_FN
    
    if not should_load_local_models():
        logger.info(f"Stage {DEPLOYMENT_STAGE}: Bypassing local Qwen2-VL-OCR model initialization.")
        QWEN2_VL_OCR_MODEL = None
        QWEN2_VL_OCR_PROCESSOR = None
        PROCESS_VISION_INFO_FN = None
        QWEN2_VL_OCR_DEVICE = None
        return
    
    # Original loading logic continues here for stages 2 and 3
    if QWEN2_VL_OCR_MODEL is not None:
        logger.info("Qwen2-VL-OCR model already initialized, skipping.")
        return
    # ... rest of original function

def initialize_whisper_model(device: str) -> None:
    global WHISPER_MODEL
    
    if not should_load_local_models():
        logger.info(f"Stage {DEPLOYMENT_STAGE}: Bypassing local Whisper model initialization.")
        WHISPER_MODEL = None
        return
    
    # Original loading logic continues here for stages 2 and 3
    if WHISPER_MODEL is not None:
        logger.info("Whisper model already initialized, skipping.")
        return
    # ... rest of original function

def initialize_ner_pipeline(model_name: str, device: str) -> None:
    global NER_PIPELINE
    
    if not should_load_local_models():
        logger.info(f"Stage {DEPLOYMENT_STAGE}: Bypassing local NER pipeline initialization.")
        NER_PIPELINE = None
        return
    
    # Original loading logic continues here for stages 2 and 3
    # ... rest of original function

def initialize_all_models() -> None:
    """Initialize models appropriate for current deployment stage."""
    if DEPLOYMENT_STAGE == "1":
        logger.info("Stage 1: Cloud-only deployment - skipping all local model initialization")
        # Initialize only cloud service configurations
        validate_cloud_api_keys()
        return
    
    # For stages 2 and 3, initialize local models
    logger.info(f"Stage {DEPLOYMENT_STAGE}: Initializing local models")
    # ... existing initialization logic

def validate_cloud_api_keys():
    """Validate required API keys for cloud services."""
    from config import OPENAI_API_KEY, MISTRAL_API_KEY
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY required for cloud deployment")
    if not MISTRAL_API_KEY:
        raise ValueError("MISTRAL_API_KEY required for cloud OCR")
    logger.info("Cloud API keys validated successfully")
```

### OCR Processing Updates

#### 3. **ocr_extraction.py** - Enhanced Cloud Integration
```python
# Add to ocr_extraction.py imports
from config import USE_OPENAI_FOR_AUDIO_TRANSCRIPTION, DEPLOYMENT_STAGE
import openai
from openai import OpenAI

def extract_text_from_pdf_qwen_vl_ocr(pdf_path: str) -> tuple[str | None, list | None]:
    """Enhanced with stage-aware fallback handling."""
    qwen_model = get_qwen2_vl_ocr_model()
    qwen_processor = get_qwen2_vl_ocr_processor()
    qwen_vision_fn = get_process_vision_info()

    if not all([qwen_model, qwen_processor, qwen_vision_fn]):
        logger.info(f"Qwen2-VL-OCR components not available (Stage {DEPLOYMENT_STAGE} bypass). Cannot process PDF with local Qwen-VL.")
        return None, None
    
    # Original function logic continues here for stages 2 and 3
    # ... rest of function

def transcribe_audio_whisper(audio_path: str) -> str | None:
    """Enhanced with OpenAI Whisper API support for Stage 1."""
    from models_init import get_whisper_model
    
    # Stage 1: Use OpenAI Whisper API
    if USE_OPENAI_FOR_AUDIO_TRANSCRIPTION or DEPLOYMENT_STAGE == "1":
        return transcribe_audio_openai_whisper(audio_path)
    
    # Stages 2-3: Try local model first, fall back to OpenAI
    local_whisper_model = get_whisper_model()
    if not local_whisper_model:
        logger.warning("Local Whisper model not available, falling back to OpenAI API")
        return transcribe_audio_openai_whisper(audio_path)
    
    # Original local Whisper logic
    logger.info(f"Using local Whisper model for {audio_path}")
    try:
        use_fp16 = False
        if hasattr(local_whisper_model, 'device') and local_whisper_model.device.type == 'cuda':
            use_fp16 = True
        result = local_whisper_model.transcribe(audio_path, fp16=use_fp16)
        return result["text"].strip()
    except Exception as e:
        logger.error(f"Local Whisper failed for {audio_path}: {e}")
        return transcribe_audio_openai_whisper(audio_path)

def transcribe_audio_openai_whisper(audio_path: str) -> str | None:
    """OpenAI Whisper API transcription."""
    from config import OPENAI_API_KEY
    
    if not OPENAI_API_KEY:
        logger.error("OPENAI_API_KEY not set. Cannot use OpenAI Whisper API.")
        return None
    
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        with open(audio_path, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file
            )
        return transcript.text.strip()
    except Exception as e:
        logger.error(f"OpenAI Whisper API transcription failed for {audio_path}: {e}")
        return None
```

### Entity Extraction Transformation

#### 4. **entity_extraction.py** - OpenAI-Based Entity Extraction
```python
# Major update to entity_extraction.py
from config import USE_OPENAI_FOR_ENTITY_EXTRACTION, DEPLOYMENT_STAGE, OPENAI_API_KEY, LLM_MODEL_FOR_RESOLUTION
from openai import OpenAI
import json
import logging

logger = logging.getLogger(__name__)

def extract_entities_from_chunk(chunk_text: str, chunk_id: int = None) -> list[dict]:
    """Stage-aware entity extraction with OpenAI fallback."""
    
    # Stage 1: Use OpenAI exclusively
    if USE_OPENAI_FOR_ENTITY_EXTRACTION or DEPLOYMENT_STAGE == "1":
        return extract_entities_openai(chunk_text, chunk_id)
    
    # Stages 2-3: Try local NER first, fall back to OpenAI
    try:
        return extract_entities_local_ner(chunk_text, chunk_id)
    except Exception as e:
        logger.warning(f"Local NER failed for chunk {chunk_id}: {e}")
        return extract_entities_openai(chunk_text, chunk_id)

def extract_entities_openai(chunk_text: str, chunk_id: int = None) -> list[dict]:
    """OpenAI-based entity extraction for Stage 1."""
    if not OPENAI_API_KEY:
        logger.error("OPENAI_API_KEY not set. Cannot perform OpenAI entity extraction.")
        return []
    
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        
        prompt = f"""
Extract named entities from the following legal document text. Return a JSON array of entities with the following structure:
[
    {{"entity": "entity_text", "label": "PERSON|ORG|GPE|DATE|MONEY|LAW|CASE|OTHER", "start": start_position, "end": end_position}}
]

Focus on legal entities such as:
- PERSON: Names of individuals (judges, lawyers, parties)
- ORG: Organizations, companies, law firms, courts
- GPE: Geographic/political entities (jurisdictions, locations)
- DATE: Dates, time periods
- MONEY: Monetary amounts, financial figures
- LAW: Statutes, regulations, legal codes
- CASE: Case names, legal precedents
- OTHER: Other legally relevant entities

Text to analyze:
{chunk_text}

Return only valid JSON array:"""

        response = client.chat.completions.create(
            model=LLM_MODEL_FOR_RESOLUTION,
            messages=[
                {"role": "system", "content": "You are a legal document entity extraction specialist. Return only valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=2000
        )
        
        response_text = response.choices[0].message.content.strip()
        
        # Parse JSON response
        try:
            entities_raw = json.loads(response_text)
            if not isinstance(entities_raw, list):
                logger.error("OpenAI entity extraction returned non-list response")
                return []
            
            # Format entities to match expected structure
            formatted_entities = []
            for entity in entities_raw:
                if isinstance(entity, dict) and all(key in entity for key in ['entity', 'label']):
                    formatted_entity = {
                        'entity': str(entity['entity']),
                        'label': str(entity['label']).upper(),
                        'start': entity.get('start', 0),
                        'end': entity.get('end', len(entity['entity'])),
                        'score': 0.95  # High confidence for OpenAI extractions
                    }
                    formatted_entities.append(formatted_entity)
            
            logger.info(f"OpenAI extracted {len(formatted_entities)} entities from chunk {chunk_id}")
            return formatted_entities
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse OpenAI entity extraction JSON: {e}")
            logger.debug(f"Response text: {response_text}")
            return []
            
    except Exception as e:
        logger.error(f"OpenAI entity extraction failed for chunk {chunk_id}: {e}")
        return []

def extract_entities_local_ner(chunk_text: str, chunk_id: int = None) -> list[dict]:
    """Original local NER pipeline extraction (for stages 2-3)."""
    from models_init import get_ner_pipeline
    
    ner_pipeline = get_ner_pipeline()
    if not ner_pipeline:
        raise ValueError("Local NER pipeline not available")
    
    # Original NER logic
    try:
        ner_results = ner_pipeline(chunk_text)
        formatted_entities = []
        
        for entity in ner_results:
            formatted_entity = {
                'entity': entity['word'],
                'label': entity['entity'],
                'start': entity.get('start', 0),
                'end': entity.get('end', 0),
                'score': entity.get('score', 0.0)
            }
            formatted_entities.append(formatted_entity)
        
        logger.info(f"Local NER extracted {len(formatted_entities)} entities from chunk {chunk_id}")
        return formatted_entities
        
    except Exception as e:
        logger.error(f"Local NER pipeline failed for chunk {chunk_id}: {e}")
        raise
```

### Pipeline Integration Updates

#### 5. **main_pipeline.py** - Stage-Aware Processing
```python
# Add to main_pipeline.py imports
from config import DEPLOYMENT_STAGE, FORCE_CLOUD_LLMS

def process_single_document(
    file_path: str, 
    file_name: str, 
    detected_file_type: str, 
    project_sql_id: int, 
    mode: str = "direct"
) -> dict:
    """Enhanced with stage-aware processing."""
    
    logger.info(f"Processing document in Stage {DEPLOYMENT_STAGE} mode: {file_name}")
    
    # Stage-specific initialization
    if DEPLOYMENT_STAGE == "1":
        logger.info("Stage 1: Using cloud-only processing pipeline")
        # Ensure cloud services are ready
        validate_stage1_requirements()
    else:
        # Initialize models for stages 2-3
        initialize_all_models()
    
    # Continue with existing pipeline logic
    # The individual functions will handle stage-specific routing
    # ... rest of existing function

def validate_stage1_requirements():
    """Validate Stage 1 deployment requirements."""
    from config import OPENAI_API_KEY, MISTRAL_API_KEY
    
    if not OPENAI_API_KEY:
        raise ValueError("Stage 1 requires OPENAI_API_KEY for entity extraction and resolution")
    if not MISTRAL_API_KEY:
        raise ValueError("Stage 1 requires MISTRAL_API_KEY for OCR processing")
    
    logger.info("Stage 1 requirements validated")

# Add to initialize_all_models call
def initialize_all_models():
    """Stage-aware model initialization."""
    if DEPLOYMENT_STAGE == "1":
        logger.info("Stage 1: Skipping local model initialization")
        from models_init import validate_cloud_api_keys
        validate_cloud_api_keys()
        return
    
    # Original initialization for stages 2-3
    from models_init import (
        initialize_qwen2_vl_ocr_model, 
        initialize_whisper_model, 
        initialize_ner_pipeline
    )
    
    device = "cuda" if torch.cuda.is_available() else "cpu"
    logger.info(f"Initializing models on device: {device}")
    
    initialize_qwen2_vl_ocr_model(device)
    initialize_whisper_model(device)
    initialize_ner_pipeline(NER_MODEL_NAME, device)
```

### Structured Extraction Updates

#### 6. **structured_extraction.py** - Stage Integration
```python
# Update structured_extraction.py constructor
from config import DEPLOYMENT_STAGE, USE_OPENAI_FOR_STRUCTURED_EXTRACTION

class StructuredExtractor:
    def __init__(self, use_qwen: bool = False):
        # Stage 1: Force OpenAI usage
        if DEPLOYMENT_STAGE == "1" or USE_OPENAI_FOR_STRUCTURED_EXTRACTION:
            self.use_qwen = False
            logger.info("Stage 1: Using OpenAI for structured extraction")
        else:
            self.use_qwen = use_qwen
        
        # Rest of existing initialization
        # ... existing code
```

## Stage 2: Dockerized Local Models

### Dockerfile Creation
```dockerfile
# Dockerfile for Stage 2
FROM python:3.10-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY scripts/ ./scripts/
COPY monitoring/ ./monitoring/
COPY ai_docs/ ./ai_docs/

# Create non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Set environment variables for Stage 2
ENV DEPLOYMENT_STAGE=2
ENV FORCE_CLOUD_LLMS=false
ENV BYPASS_LOCAL_MODELS=false

# Command to run queue processor
CMD ["python", "scripts/queue_processor.py"]
```

### Docker Compose Configuration
```yaml
# docker-compose.yml for Stage 2
version: '3.8'
services:
  legal-pipeline:
    build: .
    environment:
      - DEPLOYMENT_STAGE=2
      - SUPABASE_URL=${SUPABASE_URL}
      - SUPABASE_ANON_KEY=${SUPABASE_ANON_KEY}
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - MISTRAL_API_KEY=${MISTRAL_API_KEY}
    volumes:
      - ./temp_downloads:/app/temp_downloads
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 8G
        reservations:
          memory: 4G
```

## Stage 3: Production EC2 Deployment

### Infrastructure Configuration
```bash
#!/bin/bash
# deploy-stage3.sh
# EC2 deployment script for Stage 3

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh

# Install docker-compose
pip3 install docker-compose

# Pull application image
docker pull your-registry/legal-pipeline:stage3

# Set production environment variables
export DEPLOYMENT_STAGE=3
export FORCE_CLOUD_LLMS=false
export BYPASS_LOCAL_MODELS=false

# Run with production configuration
docker-compose -f docker-compose.prod.yml up -d
```

## Implementation Timeline

### Phase 1: Stage 1 Core Implementation (2-3 days)
1. **Day 1**: Configuration and model initialization updates
   - Update `config.py` with stage management
   - Modify `models_init.py` for conditional loading
   - Update `main_pipeline.py` with stage validation

2. **Day 2**: Entity extraction transformation
   - Implement OpenAI-based entity extraction
   - Update `entity_extraction.py` with cloud integration
   - Test entity extraction accuracy vs local NER

3. **Day 3**: OCR and audio processing updates  
   - Enhance `ocr_extraction.py` with OpenAI Whisper
   - Update `structured_extraction.py` stage integration
   - End-to-end Stage 1 testing

### Phase 2: Stage 2 Dockerization (1-2 days)
1. **Day 4**: Docker configuration
   - Create Dockerfile with model dependencies
   - Set up docker-compose for hybrid mode
   - Test local model loading in containers

2. **Day 5**: Integration testing
   - Validate Stage 2 hybrid processing
   - Performance benchmarking
   - Resource usage optimization

### Phase 3: Stage 3 Production Deployment (1 day)
1. **Day 6**: Production setup
   - EC2 instance configuration
   - Production environment setup
   - Final integration testing

## Testing Strategy

### Stage 1 Testing
```python
# test_stage1.py
def test_stage1_entity_extraction():
    """Validate OpenAI entity extraction works correctly."""
    os.environ["DEPLOYMENT_STAGE"] = "1"
    entities = extract_entities_from_chunk("John Doe vs. ABC Corp.")
    assert len(entities) > 0
    assert any(e['label'] == 'PERSON' for e in entities)

def test_stage1_ocr_processing():
    """Validate OCR works without local models."""
    os.environ["DEPLOYMENT_STAGE"] = "1"
    # Test with sample PDF
    result = process_single_document(test_pdf_path, "test.pdf", ".pdf", 1)
    assert result['status'] == 'success'

def test_stage1_full_pipeline():
    """End-to-end Stage 1 processing test."""
    os.environ["DEPLOYMENT_STAGE"] = "1"
    # Upload document through queue processor
    # Verify complete processing using only cloud services
```

## Migration Checklist

### Pre-Stage 1 Deployment
- [ ] Validate OpenAI API key and quotas
- [ ] Validate Mistral API key and quotas  
- [ ] Test OpenAI entity extraction accuracy
- [ ] Update environment variables for Stage 1
- [ ] Run Stage 1 integration tests

### Stage 1 to Stage 2 Migration
- [ ] Create Dockerfile with model dependencies
- [ ] Test local model loading in containers
- [ ] Validate hybrid processing works correctly
- [ ] Performance benchmark vs Stage 1
- [ ] Update deployment configuration

### Stage 2 to Stage 3 Migration
- [ ] Provision EC2 instance with appropriate resources
- [ ] Configure production security groups
- [ ] Set up monitoring and logging
- [ ] Deploy production container
- [ ] Validate production performance

## Risk Mitigation

### Stage 1 Risks
1. **OpenAI API Limits**: Monitor usage, implement rate limiting
2. **Entity Extraction Accuracy**: Compare with local NER, fine-tune prompts
3. **Cost Management**: Track API costs, optimize prompts for efficiency

### Stage 2 Risks
1. **Container Size**: Optimize model loading, use multi-stage builds
2. **Memory Usage**: Monitor resource consumption, adjust limits
3. **Model Loading Time**: Implement model caching, warm-up strategies

### Stage 3 Risks
1. **EC2 Costs**: Right-size instances, use spot instances where appropriate
2. **Scaling**: Implement auto-scaling groups for queue processing
3. **Monitoring**: Set up CloudWatch alerts for system health

## Success Metrics

### Stage 1 Metrics
- Pipeline processing time (target: <5 minutes per document)
- Entity extraction accuracy (target: >85% vs local NER)
- System reliability (target: >99% uptime)
- API cost per document (target: <$0.50)

### Stage 2 Metrics
- Container startup time (target: <2 minutes)
- Memory usage (target: <8GB per container)
- Processing throughput (target: 10 documents/hour)

### Stage 3 Metrics
- Production uptime (target: >99.9%)
- Auto-scaling effectiveness
- End-to-end processing latency
- Cost per document processed

## Conclusion

This staged deployment implementation provides a structured approach to migrating the legal document processing pipeline from local development to cloud production. Stage 1 focuses on cloud-first processing using OpenAI services, Stage 2 introduces local model dockerization for hybrid processing, and Stage 3 achieves full production deployment on EC2.

The implementation prioritizes maintaining pipeline functionality while incrementally introducing complexity, ensuring each stage is thoroughly tested before progression. This approach minimizes deployment risks and provides clear rollback points at each stage.