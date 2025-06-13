# Context 243: Scripts Implementation Flow Analysis

**Date**: 2025-05-30
**Type**: Implementation Architecture
**Status**: ACTIVE
**Component**: Actual Script Processing Flow and Dependencies

## Overview

This document analyzes the actual implementation flow in the `/scripts/` directory, revealing how the document processing pipeline is really structured versus the idealized RDS schema.

## High-Level Script Architecture

```mermaid
graph TB
    subgraph "Entry Points"
        CLI[CLI Import<br/>scripts/cli/import.py]
        API[API Endpoint]
        DIRECT[Direct Pipeline<br/>scripts/pdf_pipeline.py]
    end
    
    subgraph "Task Orchestration"
        CELERY[Celery Tasks<br/>scripts/pdf_tasks.py]
        REDIS[Redis Cache<br/>scripts/cache.py]
    end
    
    subgraph "Processing Stages"
        OCR[OCR Extraction<br/>scripts/ocr_extraction.py]
        CHUNK[Text Processing<br/>scripts/text_processing.py]
        ENTITY[Entity Service<br/>scripts/entity_service.py]
        GRAPH[Graph Service<br/>scripts/graph_service.py]
    end
    
    subgraph "Storage"
        S3[S3 Storage<br/>scripts/s3_storage.py]
        DB[Database<br/>scripts/db.py]
    end
    
    CLI --> CELERY
    API --> CELERY
    DIRECT --> OCR
    
    CELERY --> OCR
    CELERY --> REDIS
    
    OCR --> CHUNK
    CHUNK --> ENTITY
    ENTITY --> GRAPH
    
    OCR --> S3
    OCR --> DB
    CHUNK --> DB
    ENTITY --> DB
    GRAPH --> DB
    
    REDIS -.-> OCR
    REDIS -.-> CHUNK
    REDIS -.-> ENTITY
```

## Detailed Implementation Flow

```mermaid
sequenceDiagram
    participant User
    participant CLI as CLI (import.py)
    participant S3
    participant DB as Database (db.py)
    participant Celery
    participant Redis
    participant OCR as OCR Service
    participant Chunk as Chunking Service
    participant Entity as Entity Service
    participant Graph as Graph Service
    
    User->>CLI: Upload document manifest
    CLI->>CLI: Validate with ImportManifestModel
    CLI->>DB: Create import_sessions record
    
    loop For each document
        CLI->>S3: Upload file (UUID naming)
        CLI->>DB: Insert into source_documents
        CLI->>Celery: Submit process_pdf_document task
    end
    
    Note over Celery: Async Processing Begins
    
    Celery->>Redis: Check cache doc:ocr:{uuid}
    Redis-->>Celery: Cache miss
    Celery->>DB: Get document from source_documents
    Celery->>S3: Retrieve document
    Celery->>OCR: Extract text (Textract)
    OCR->>DB: Create textract_jobs record
    OCR-->>Celery: Return extracted text
    Celery->>DB: Update source_documents
    Celery->>Redis: Cache OCR results
    
    Celery->>Chunk: Process text chunks
    Chunk->>DB: Insert into document_chunks
    Chunk->>Redis: Cache chunks
    
    Celery->>Entity: Extract entities
    Entity->>DB: Insert into entity_mentions
    Entity->>Redis: Cache entities
    
    Celery->>Entity: Resolve canonical entities
    Entity->>DB: Insert into canonical_entities
    
    Celery->>Graph: Build relationships
    Graph->>DB: Insert into relationship_staging
    
    Celery->>DB: Update processing status
    Celery->>Redis: Update state cache
```

## Actual Database Tables Used

```mermaid
erDiagram
    import_sessions ||--o{ source_documents : "imports"
    projects ||--o{ source_documents : "contains"
    source_documents ||--o{ textract_jobs : "triggers"
    source_documents ||--o{ document_chunks : "split into"
    document_chunks ||--o{ entity_mentions : "contains"
    entity_mentions }o--|| canonical_entities : "resolved to"
    document_chunks ||--o{ chunk_embeddings : "has"
    canonical_entities ||--o{ canonical_entity_embeddings : "has"
    canonical_entities }o--o{ relationship_staging : "related via"
    
    import_sessions {
        uuid session_uuid PK
        uuid project_uuid FK
        jsonb manifest_data
        timestamp created_at
    }
    
    source_documents {
        integer id PK
        uuid document_uuid
        uuid project_uuid FK
        text filename
        text s3_key
        text processing_status
        text raw_extracted_text
        jsonb ocr_metadata_json
        timestamp created_at
    }
    
    textract_jobs {
        integer id PK
        uuid document_uuid FK
        text job_id
        text status
        jsonb metadata
        timestamp created_at
    }
    
    document_chunks {
        integer id PK
        uuid chunk_uuid
        uuid document_uuid FK
        integer chunk_index
        text text_content
        integer char_start_index
        integer char_end_index
        jsonb metadata_json
    }
    
    entity_mentions {
        integer id PK
        uuid mention_uuid
        uuid chunk_uuid FK
        text entity_text
        text entity_type
        float confidence_score
        integer start_char
        integer end_char
    }
    
    canonical_entities {
        integer id PK
        uuid canonical_entity_uuid
        text entity_type
        text canonical_name
        integer mention_count
        float confidence_score
    }
    
    relationship_staging {
        integer id PK
        uuid source_entity_uuid FK
        uuid target_entity_uuid FK
        text relationship_type
        float confidence_score
    }
```

## Celery Task Flow

```mermaid
graph TD
    subgraph "Main Orchestrator"
        MAIN[process_pdf_document<br/>Queue: general]
    end
    
    subgraph "OCR Queue"
        OCR1[extract_text_from_document<br/>Queue: ocr]
        OCR2[Textract Async Processing]
        OCR3[Poll for Results]
    end
    
    subgraph "Text Queue"
        TEXT1[chunk_document_text<br/>Queue: text]
        TEXT2[Semantic Chunking]
        TEXT3[Fallback Chunking]
    end
    
    subgraph "Entity Queue"
        ENT1[extract_entities_from_chunks<br/>Queue: entity]
        ENT2[resolve_document_entities<br/>Queue: entity]
    end
    
    subgraph "Graph Queue"
        GRAPH1[build_document_relationships<br/>Queue: graph]
    end
    
    MAIN --> OCR1
    OCR1 --> OCR2
    OCR2 --> OCR3
    OCR3 --> TEXT1
    TEXT1 --> TEXT2
    TEXT2 --> TEXT3
    TEXT1 --> ENT1
    ENT1 --> ENT2
    ENT2 --> GRAPH1
    
    GRAPH1 --> COMPLETE[Update Status: Complete]
```

## Redis Cache Architecture

```mermaid
graph LR
    subgraph "Cache Keys Structure"
        DOC[Document Level]
        CHUNK[Chunk Level]
        ENTITY[Entity Level]
        TASK[Task Level]
    end
    
    subgraph "Document Cache"
        DOC --> D1[doc:state:{uuid}]
        DOC --> D2[doc:ocr:{uuid}]
        DOC --> D3[doc:chunks:{uuid}]
        DOC --> D4[doc:canonical_entities:{uuid}]
    end
    
    subgraph "Chunk Cache"
        CHUNK --> C1[doc:chunk_text:{chunk_uuid}]
        CHUNK --> C2[doc:entities:{doc_uuid}:{chunk_id}]
    end
    
    subgraph "Processing Cache"
        TASK --> T1[task:status:{task_id}]
        TASK --> T2[textract:result:{uuid}]
    end
    
    subgraph "TTL Settings"
        TTL1[OCR: 7 days]
        TTL2[Chunks: 2 days]
        TTL3[Entities: 12 hours]
        TTL4[Task Status: 24 hours]
    end
    
    D2 --> TTL1
    D3 --> TTL2
    C2 --> TTL3
    T1 --> TTL4
```

## Error Handling and Recovery Flow

```mermaid
stateDiagram-v2
    [*] --> Processing: Start Task
    Processing --> Success: No Errors
    Processing --> Error: Exception
    
    Error --> Retry: Retryable Error
    Error --> Failed: Non-Retryable
    
    Retry --> Processing: Retry Count < Max
    Retry --> Failed: Max Retries Reached
    
    Failed --> Manual: Manual Intervention
    Manual --> Processing: Resubmit
    
    Success --> [*]
    
    state Error {
        [*] --> CheckType
        CheckType --> NetworkError: Timeout/Connection
        CheckType --> ValidationError: Bad Data
        CheckType --> APIError: Service Error
        
        NetworkError --> RetryDecision
        APIError --> RetryDecision
        ValidationError --> FailDecision
    }
```

## Processing Time Analysis

```mermaid
gantt
    title Document Processing Timeline
    dateFormat X
    axisFormat %s
    
    section Import
    File Upload       :0, 2
    S3 Upload        :2, 3
    DB Record        :5, 1
    
    section OCR
    Textract Start   :6, 2
    Textract Process :8, 20
    Result Polling   :28, 5
    
    section Chunking
    Text Cleaning    :33, 2
    Chunk Creation   :35, 5
    DB Storage       :40, 2
    
    section Entities
    Entity Extract   :42, 10
    Entity Resolve   :52, 5
    
    section Graph
    Relationship Build :57, 8
    Graph Storage     :65, 2
    
    section Complete
    Status Update     :67, 1
```

## Implementation vs RDS Schema Discrepancies

```mermaid
graph TD
    subgraph "Scripts Expect"
        SE1[source_documents table]
        SE2[document_chunks table]
        SE3[entity_mentions table]
        SE4[canonical_entities table]
        SE5[relationship_staging table]
        SE6[textract_jobs table]
        SE7[import_sessions table]
    end
    
    subgraph "RDS Has"
        RDS1[documents table]
        RDS2[chunks table]
        RDS3[entities table]
        RDS4[relationships table]
        RDS5[processing_logs table]
    end
    
    subgraph "Missing in RDS"
        M1[No source_documents]
        M2[No textract_jobs]
        M3[No import_sessions]
        M4[No canonical_entities]
        M5[No embeddings tables]
    end
    
    SE1 -.->|Maps to| RDS1
    SE2 -.->|Maps to| RDS2
    SE3 -.->|Maps to| RDS3
    SE4 -.->|Missing| M4
    SE5 -.->|Maps to| RDS4
    SE6 -.->|Missing| M2
    SE7 -.->|Missing| M3
```

## Key Implementation Patterns

### 1. **Conformance Validation**
```python
# Every database operation validates conformance
db_manager = DatabaseManager(validate_conformance=True)
```

### 2. **Idempotent Operations**
```python
# Tasks check for existing results before processing
existing = cache.get(f"doc:ocr:{document_uuid}")
if existing:
    return existing
```

### 3. **Rate Limiting**
```python
@rate_limit(calls=10, period=60)  # 10 calls per minute
def call_openai_api():
    pass
```

### 4. **Async Pattern**
```python
# Textract uses async API with polling
job_id = start_textract_job()
result = poll_for_completion(job_id)
```

## Performance Characteristics

### Processing Times (per document)
- **Import & Upload**: 2-5 seconds
- **OCR (Textract)**: 20-30 seconds
- **Text Chunking**: 5-10 seconds
- **Entity Extraction**: 10-15 seconds
- **Relationship Building**: 5-10 seconds
- **Total**: 45-70 seconds per document

### Bottlenecks
1. **OCR Processing**: Textract async API latency
2. **LLM Calls**: OpenAI API rate limits
3. **Database Writes**: Connection pool saturation
4. **Redis Operations**: Network latency

### Optimization Strategies
1. **Parallel OCR**: Process multiple pages concurrently
2. **Batch Operations**: Group database inserts
3. **Smart Caching**: Cache expensive operations
4. **Queue Prioritization**: Separate queues by operation type

## Conclusion

The actual implementation reveals a sophisticated but complex system that expects a different database schema than what RDS currently provides. The heavy use of caching, async processing, and Celery task orchestration enables scalable document processing, but the schema mismatch creates immediate operational challenges that must be resolved through mapping layers or schema alignment.