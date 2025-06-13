# Context 391: Legal Document Processing Architecture Analysis

## Current System Architecture

### Core Processing Flow Diagram

```mermaid
graph TB
    %% Document Intake
    S3[S3 Bucket<br/>Document Storage] --> OCR{OCR Processing}
    
    %% OCR Branch
    OCR -->|AWS Textract| TEXTRACT[Textract Service<br/>textract_utils.py]
    OCR -->|Fallback| TESSERACT[Tesseract OCR<br/>Local Fallback]
    
    %% Text Processing
    TEXTRACT --> TEXT[Raw Text]
    TESSERACT --> TEXT
    
    %% Chunking
    TEXT --> CHUNK[Text Chunking<br/>chunking_utils.py]
    CHUNK --> CHUNKS[(Chunks in DB)]
    
    %% Entity Processing
    CHUNKS --> ENTITY[Entity Extraction<br/>entity_service.py]
    ENTITY -->|OpenAI API| OPENAI[GPT-4 Mini]
    ENTITY -->|Local NER| NER[Local Models<br/>Stage 2/3 Only]
    
    %% Entity Resolution
    ENTITY --> MENTIONS[(Entity Mentions)]
    MENTIONS --> RESOLVE[Entity Resolution<br/>entity_service.py]
    RESOLVE --> CANONICAL[(Canonical Entities)]
    
    %% Graph Building
    CANONICAL --> GRAPH[Graph Service<br/>graph_service.py]
    CHUNKS --> GRAPH
    GRAPH --> STAGING[(Relationship Staging)]
    
    %% Orchestration Layer
    CELERY[Celery App<br/>celery_app.py] -.->|Orchestrates| OCR
    CELERY -.->|Orchestrates| CHUNK
    CELERY -.->|Orchestrates| ENTITY
    CELERY -.->|Orchestrates| RESOLVE
    CELERY -.->|Orchestrates| GRAPH
    
    %% Storage Layer
    REDIS[Redis Cache<br/>cache.py] -.->|Caches| TEXT
    REDIS -.->|Caches| CHUNKS
    REDIS -.->|Caches| MENTIONS
    REDIS -.->|Caches| CANONICAL
    
    %% Database Layer
    DB[PostgreSQL/RDS<br/>db.py] -.->|Persists| CHUNKS
    DB -.->|Persists| MENTIONS
    DB -.->|Persists| CANONICAL
    DB -.->|Persists| STAGING
    
    %% PDF to Image Conversion Integration Point
    style PDF fill:#ff9999
    PDF[PDF to Image<br/>Converter<br/>(TO BE INTEGRATED)] -->|Convert Pages| IMAGES[Page Images]
    IMAGES --> OCR
    S3 -.->|Future Path| PDF
```

### Component Responsibilities

#### 1. **celery_app.py** - Task Orchestration
- Manages distributed task processing
- Defines task queues (ocr, text, entity, graph, cleanup)
- Handles retry logic and timeouts
- Redis-based broker and backend

#### 2. **pdf_tasks.py** - Main Processing Tasks
- Core Celery tasks for each pipeline stage
- `extract_text_from_document` - OCR coordination
- `chunk_document_text` - Text chunking
- `extract_entities_from_chunks` - Entity extraction
- `resolve_document_entities` - Entity resolution  
- `build_document_relationships` - Graph building
- Smart retry logic with exponential backoff

#### 3. **textract_utils.py** - OCR Utilities
- AWS Textract integration (async processing)
- Tesseract fallback for local processing
- **Key Integration Point**: Currently handles PDFs directly
- Caches OCR results in Redis

#### 4. **db.py** - Database Operations
- Unified database interface
- Pydantic model validation
- Schema conformance engine
- Connection pooling

#### 5. **cache.py** - Redis Caching
- Centralized cache key management
- Model-aware caching
- Performance metrics
- Distributed locks

#### 6. **entity_service.py** - Entity Operations
- Entity extraction (OpenAI/Local NER)
- Entity resolution (LLM/Fuzzy matching)
- Structured data extraction
- Entity enhancement with embeddings

#### 7. **chunking_utils.py** - Text Chunking
- Markdown-guided semantic chunking
- Simple fallback chunking
- Chunk validation and refinement

#### 8. **graph_service.py** - Relationship Building
- Stages structural relationships
- Document-Entity-Chunk relationships
- Prepares data for Neo4j export

## PDF to Image Conversion Integration Points

### Primary Integration Point: `textract_utils.py`

The `extract_with_tesseract` method already handles PDF conversion:

```python
# Line 365-378 in textract_utils.py
if local_file_path.lower().endswith('.pdf'):
    # Convert PDF to images
    logger.info("Converting PDF to images for Tesseract")
    images = convert_from_path(local_file_path, dpi=200)
    
    text_parts = []
    for i, image in enumerate(images):
        logger.debug(f"Processing PDF page {i+1}")
        page_text = pytesseract.image_to_string(image, config='--psm 1 --oem 3')
        text_parts.append(page_text)
    
    extracted_text = '\n\n'.join(text_parts)
```

### Recommended Enhancement Points:

1. **Enhanced PDF Processing in `textract_utils.py`**:
   - Add configurable DPI settings
   - Implement page-level caching
   - Add image preprocessing (deskew, denoise)
   - Support for parallel page processing

2. **New PDF Preprocessing Task in `pdf_tasks.py`**:
   - Create `preprocess_pdf_document` task
   - Handle large PDFs with streaming
   - Generate page thumbnails for UI
   - Extract document metadata

3. **Cache Individual Pages in `cache.py`**:
   - Add page-level cache keys
   - Cache preprocessed images
   - Implement smart eviction for large documents

## Test Script Proliferation Analysis

### Current State: 462 Test Scripts!

This is a serious technical debt issue. The test scripts are scattered across:
- `/opt/legal-doc-processor/scripts/test_*.py` (15 files)
- `/opt/legal-doc-processor/test_*.py` (9 files)  
- `/opt/legal-doc-processor/archived_codebase/test_scripts/` (47 files)
- `/opt/legal-doc-processor/tests/` (2 files)
- Many more scattered throughout

### Root Causes:
1. **No Test Organization Strategy**: Tests created ad-hoc during debugging
2. **Duplicate Testing**: Same functionality tested multiple times
3. **Debug Scripts Promoted to Tests**: Quick debug scripts never cleaned up
4. **No Test Categories**: Mix of unit, integration, E2E tests

### Recommended Consolidation Plan:

```
tests/
├── unit/
│   ├── test_cache.py
│   ├── test_db_operations.py
│   ├── test_entity_extraction.py
│   └── test_chunking.py
├── integration/
│   ├── test_ocr_pipeline.py
│   ├── test_entity_pipeline.py
│   └── test_celery_tasks.py
├── e2e/
│   ├── test_document_processing.py
│   └── test_production_scenarios.py
└── fixtures/
    ├── sample_documents/
    └── mock_data.py
```

### Consolidation Steps:

1. **Categorize Existing Tests**:
   - Identify unique test scenarios
   - Group by functionality
   - Mark duplicates for removal

2. **Create Core Test Suite**:
   - One test file per module
   - Clear test naming conventions
   - Shared fixtures and utilities

3. **Archive Debug Scripts**:
   - Move one-off debug scripts to `archived_codebase/debug_scripts/`
   - Keep only production-ready tests

4. **Implement Test Standards**:
   - Use pytest exclusively
   - Standardize mocking approach
   - Document test coverage requirements

## Deployment Stage Considerations

The system supports 3 deployment stages:
- **Stage 1**: Cloud-only (OpenAI/Textract)
- **Stage 2**: Hybrid (local models with cloud fallback)
- **Stage 3**: Local production (EC2 with full local models)

PDF processing should respect these stages:
- Stage 1: Can use cloud-based PDF services
- Stage 2/3: Must use local PDF processing

## Next Steps

1. **Immediate**: Document current test scenarios before consolidation
2. **Short-term**: Implement PDF preprocessing enhancements
3. **Medium-term**: Complete test consolidation
4. **Long-term**: Add monitoring for PDF processing performance