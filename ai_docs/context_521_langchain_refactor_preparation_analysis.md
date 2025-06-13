# Context 521: LangChain Refactor Preparation - Complete Processing Flow Analysis

**Date**: 2025-06-13 02:00 UTC  
**Purpose**: Document current processing flow, identify all modules, and analyze Redis cache usage in preparation for LangChain refactor  
**Current Status**: 459 documents processing, workers active, memory issues detected

## Executive Summary

The current entity extraction and resolution pipeline is experiencing memory-related failures (jiter shared object loading errors) and heavy OpenAI rate limiting. A LangChain refactor could address both issues through better memory management and batch processing capabilities.

## Complete Processing Flow (From Logs)

### 1. Pipeline Entry Point
```
scripts.pdf_tasks.process_pdf_document
└── Orchestrates entire 6-stage pipeline
```

### 2. Stage 1: OCR Extraction
```
scripts.pdf_tasks.extract_text_from_document
├── scripts.textract_utils.TextractProcessor
│   ├── start_document_text_detection_v2() - Async Textract initiation
│   └── get_text_detection_results_v2() - Result polling
├── scripts.textract_job_manager - Job state management
└── scripts.cache.RedisManager - Cache OCR results
```

### 3. Stage 2: Text Chunking
```
scripts.pdf_tasks.chunk_document_text
├── scripts.chunking_utils.simple_chunk_text()
│   └── Semantic chunking with 1000 char chunks, 200 char overlap
└── scripts.cache - Cache chunks
```

### 4. Stage 3: Entity Extraction (CRITICAL FOR REFACTOR)
```
scripts.pdf_tasks.extract_entities_from_chunks
├── scripts.entity_service.EntityService
│   ├── extract_entities_from_chunk()
│   │   ├── OpenAI API call (gpt-4o-mini)
│   │   ├── Rate limiting decorator
│   │   └── JSON parsing with retry logic
│   └── _create_entity_mention() - Database persistence
└── Memory Error: "jiter.cpython-310-x86_64-linux-gnu.so: failed to map segment"
```

### 5. Stage 4: Entity Resolution (CRITICAL FOR REFACTOR)
```
scripts.pdf_tasks.resolve_document_entities
├── scripts.entity_resolution_fixes.resolve_entities_simple()
│   ├── Fuzzy matching with rapidfuzz
│   ├── Entity type grouping
│   └── Canonical entity creation
├── scripts.entity_resolution_fixes.save_canonical_entities_to_db()
└── scripts.entity_resolution_fixes.update_entity_mentions_with_canonical()
```

### 6. Stage 5: Relationship Building
```
scripts.pdf_tasks.build_document_relationships
└── scripts.graph_service.GraphService.stage_structural_relationships()
    └── Limited to entity-document relationships (FK constraint issue)
```

### 7. Stage 6: Pipeline Finalization
```
scripts.pdf_tasks.finalize_document_pipeline
└── Update document status to completed
```

## Critical Modules for LangChain Refactor

### 1. **scripts/entity_service.py**
- Current: Direct OpenAI API calls with custom prompts
- Issues: Memory errors, rate limiting, no cross-document context
- LangChain opportunity: Use LangChain's entity extraction chains

### 2. **scripts/entity_resolution_fixes.py**
- Current: Fuzzy matching with rapidfuzz
- Issues: No semantic understanding, limited to exact/fuzzy matches
- LangChain opportunity: Vector similarity with embeddings

### 3. **scripts/cache.py**
- Current: Redis caching with multi-database setup
- Features: Rate limiting, TTL management, circuit breaker
- LangChain integration: Can be used for chain memory persistence

## Redis Cache Analysis

### Cache Architecture
```
Redis Databases (from logs):
- DB 0: rate_limit (Rate limiting for OpenAI)
- DB 1: cache (Document data, OCR results, chunks, entities)
- DB 2: batch (Batch processing metadata)
- DB 3: metrics (Performance metrics)

Key Patterns:
- doc:state:{document_uuid} - Processing state
- doc:ocr:{document_uuid} - OCR results
- doc:chunks:{document_uuid} - Document chunks
- doc:entity_mentions:{document_uuid} - Extracted entities
- doc:canonical_entities:{document_uuid} - Resolved entities
- rate:limit:* - Rate limiting keys
```

### Rate Limiting Implementation
```python
# From logs - OpenAI rate limiting
WARNING:scripts.cache:Rate limited on openai, waiting 39.83s
WARNING:scripts.cache:Rate limited on openai, waiting 50.06s
```

## Memory Error Analysis

### Error Pattern
```
OSError: /opt/legal-doc-processor/venv/lib/python3.10/site-packages/jiter.cpython-310-x86_64-linux-gnu.so: 
failed to map segment from shared object
```

### Root Cause
- Shared library loading failure under memory pressure
- Occurs during entity extraction JSON parsing
- jiter is used by Pydantic for fast JSON parsing

### Solution in LangChain
- LangChain handles JSON parsing internally
- Better memory management through streaming
- Built-in retry mechanisms

## LangChain Refactor Opportunities

### 1. Entity Extraction Chain
Replace current implementation with:
```python
from langchain.chains import create_extraction_chain
from langchain.chat_models import ChatOpenAI
from langchain.memory import ConversationSummaryBufferMemory

# Use extraction chain with schema
extraction_chain = create_extraction_chain(
    schema=entity_schema,
    llm=ChatOpenAI(model="gpt-4o-mini", temperature=0)
)
```

### 2. Cross-Document Entity Resolution
Implement vector store for semantic matching:
```python
from langchain.vectorstores import Redis
from langchain.embeddings import OpenAIEmbeddings

# Use Redis as vector store
vectorstore = Redis(
    redis_url=redis_url,
    index_name="canonical_entities",
    embedding_function=OpenAIEmbeddings()
)
```

### 3. Batch Processing
Use LangChain's batch capabilities:
```python
from langchain.callbacks import get_openai_callback

# Process multiple chunks in batch
with get_openai_callback() as cb:
    results = await extraction_chain.abatch(chunks)
    print(f"Total tokens: {cb.total_tokens}")
```

### 4. Memory Management
Implement conversation memory for context:
```python
from langchain.memory import RedisChatMessageHistory

# Persistent memory across documents
memory = RedisChatMessageHistory(
    session_id=project_uuid,
    url=redis_url,
    ttl=86400
)
```

## Implementation Plan

### Phase 1: Entity Extraction Refactor
1. Create `scripts/langchain_entity_service.py`
2. Implement extraction chain with proper error handling
3. Add batch processing for chunks
4. Integrate with existing Redis cache

### Phase 2: Entity Resolution Enhancement
1. Create `scripts/langchain_entity_resolver.py`
2. Implement vector store for canonical entities
3. Add semantic similarity matching
4. Maintain backward compatibility with DB schema

### Phase 3: Cross-Document State
1. Implement project-level entity memory
2. Create entity knowledge graph
3. Add incremental learning capabilities

### Phase 4: Performance Optimization
1. Implement streaming for large documents
2. Add request batching to avoid rate limits
3. Optimize token usage with summarization

## Required LangChain Components

```python
# Core dependencies for refactor
langchain==0.1.0
langchain-openai==0.0.5
langchain-community==0.0.10
langchain-redis==0.0.1
tiktoken==0.5.2  # Already installed
numpy==1.26.2    # Already installed
```

## Worker Restart Considerations

Before implementing:
1. Current batch must complete or be paused
2. Workers must be gracefully stopped
3. New code deployed
4. Workers restarted with new modules

Commands for controlled restart:
```bash
# Check current progress
python scripts/cli/monitor.py live

# Graceful shutdown
celery -A scripts.celery_app control shutdown

# After code deployment
celery -A scripts.celery_app worker --loglevel=info --queues=default,ocr,text,entity,graph,cleanup &
```

## Conclusion

The current system is well-architected but suffering from memory issues and rate limiting. LangChain provides solutions for both through better memory management, built-in batching, and semantic entity resolution capabilities. The refactor can be implemented incrementally without disrupting the current pipeline structure.