# Context 242: RDS Data Flow Analysis and Architecture

**Date**: 2025-05-30
**Type**: Data Flow Architecture
**Status**: ACTIVE
**Component**: RDS PostgreSQL Data Flow and Processing Pipeline

## Overview

This document visualizes the data flow through the RDS-based document processing pipeline, showing how documents move from intake through final knowledge graph creation.

## High-Level Data Flow

```mermaid
graph TB
    subgraph "Input Sources"
        A[PDF Documents]
        B[Word Documents]
        C[Audio Files]
        D[Images]
    end
    
    subgraph "Storage Layer"
        E[S3 Bucket]
        F[RDS PostgreSQL]
    end
    
    subgraph "Processing Pipeline"
        G[OCR/Transcription]
        H[Text Chunking]
        I[Entity Extraction]
        J[Relationship Building]
        K[Embeddings Generation]
    end
    
    subgraph "Output"
        L[Knowledge Graph]
        M[Search Index]
        N[Analytics]
    end
    
    A --> E
    B --> E
    C --> E
    D --> E
    
    E --> G
    G --> F
    G --> H
    H --> F
    H --> I
    I --> F
    I --> J
    J --> F
    H --> K
    K --> F
    
    F --> L
    F --> M
    F --> N
```

## Detailed RDS Table Data Flow

```mermaid
graph LR
    subgraph "1. Project Creation"
        P1[Client/Matter Info] --> P2[projects table]
        P2 --> P3[project_uuid]
    end
    
    subgraph "2. Document Import"
        D1[File Upload] --> D2[S3 Storage]
        D2 --> D3[documents table]
        P3 --> D3
        D3 --> D4[document_uuid]
    end
    
    subgraph "3. OCR Processing"
        D4 --> O1[AWS Textract/OpenAI Vision]
        O1 --> O2[Extracted Text]
        O2 --> D3
        O1 --> PL1[processing_logs]
    end
    
    subgraph "4. Text Chunking"
        O2 --> C1[Chunking Algorithm]
        C1 --> C2[chunks table]
        D4 --> C2
        C2 --> C3[chunk_uuid]
    end
    
    subgraph "5. Entity Extraction"
        C3 --> E1[NER Models]
        E1 --> E2[entities table]
        C3 --> E2
        E2 --> E3[entity_uuid]
    end
    
    subgraph "6. Relationship Discovery"
        E3 --> R1[Relationship Engine]
        R1 --> R2[relationships table]
        E3 --> R2
    end
    
    subgraph "7. Processing Logs"
        PL1[processing_logs table]
        D4 --> PL1
        C3 --> PL1
        E3 --> PL1
    end
```

## RDS Schema Data Relationships

```mermaid
erDiagram
    projects ||--o{ documents : "contains"
    documents ||--o{ chunks : "split into"
    chunks ||--o{ entities : "extracted from"
    entities ||--o{ relationships : "connected by"
    documents ||--o{ processing_logs : "tracked by"
    
    projects {
        uuid project_uuid PK
        text name
        text client_name
        text matter_type
        jsonb metadata
        timestamp created_at
        timestamp updated_at
    }
    
    documents {
        uuid document_uuid PK
        uuid project_uuid FK
        text filename
        text file_path
        text file_type
        text processing_status
        text extracted_text
        jsonb metadata
        timestamp created_at
        timestamp updated_at
    }
    
    chunks {
        uuid chunk_uuid PK
        uuid document_uuid FK
        integer chunk_index
        text text_content
        text cleaned_text
        integer char_start_index
        integer char_end_index
        jsonb metadata
        timestamp created_at
    }
    
    entities {
        uuid entity_uuid PK
        uuid chunk_uuid FK
        text entity_text
        text entity_type
        float confidence_score
        integer start_position
        integer end_position
        jsonb metadata
        timestamp created_at
    }
    
    relationships {
        uuid relationship_uuid PK
        uuid source_entity_uuid FK
        uuid target_entity_uuid FK
        text relationship_type
        float confidence_score
        jsonb metadata
        timestamp created_at
    }
    
    processing_logs {
        uuid log_uuid PK
        uuid document_uuid FK
        text event_type
        text status
        jsonb event_data
        timestamp created_at
    }
    
    schema_version {
        integer version PK
        text description
        timestamp applied_at
    }
```

## Processing State Flow

```mermaid
stateDiagram-v2
    [*] --> Uploaded: Document uploaded to S3
    Uploaded --> Pending: Record created in documents table
    Pending --> Processing: OCR/Transcription started
    Processing --> Extracted: Text extraction complete
    Extracted --> Chunking: Text chunking in progress
    Chunking --> Chunked: Chunks stored in database
    Chunked --> Analyzing: Entity extraction running
    Analyzing --> Analyzed: Entities identified
    Analyzed --> Linking: Building relationships
    Linking --> Complete: All processing done
    
    Processing --> Failed: OCR error
    Chunking --> Failed: Chunking error
    Analyzing --> Failed: Entity extraction error
    Linking --> Failed: Relationship error
    
    Failed --> Pending: Retry processing
```

## Data Volume Flow Analysis

```mermaid
graph TD
    subgraph "Input Volume"
        IV1[1 Document: ~10MB PDF]
        IV2[~50 pages]
    end
    
    subgraph "OCR Output"
        OC1[Raw Text: ~200KB]
        OC2[Metadata: ~10KB]
    end
    
    subgraph "Chunking Output"
        CH1[~100 chunks]
        CH2[~2KB per chunk]
        CH3[Total: ~200KB]
    end
    
    subgraph "Entity Output"
        EN1[~500 entities]
        EN2[~0.5KB per entity]
        EN3[Total: ~250KB]
    end
    
    subgraph "Relationship Output"
        RE1[~1000 relationships]
        RE2[~0.2KB per relationship]
        RE3[Total: ~200KB]
    end
    
    subgraph "Total Storage"
        TS1[S3: 10MB original]
        TS2[RDS: ~1MB processed data]
        TS3[Ratio: 10:1 compression]
    end
    
    IV1 --> OC1
    OC1 --> CH1
    CH1 --> EN1
    EN1 --> RE1
    
    IV1 --> TS1
    OC1 --> TS2
    CH3 --> TS2
    EN3 --> TS2
    RE3 --> TS2
```

## Celery Task Flow

```mermaid
sequenceDiagram
    participant U as User
    participant API as API/CLI
    participant C as Celery
    participant R as Redis
    participant DB as RDS
    participant S3 as S3
    participant OCR as OCR Service
    
    U->>API: Upload document
    API->>S3: Store file
    API->>DB: Create document record
    API->>C: Submit OCR task
    C->>R: Queue task
    
    Note over C: Worker picks up task
    
    C->>S3: Retrieve document
    C->>OCR: Process document
    OCR-->>C: Return text
    C->>DB: Update document with text
    C->>C: Submit chunking task
    
    Note over C: Chunking task
    
    C->>DB: Get document text
    C->>DB: Save chunks
    C->>C: Submit entity task
    
    Note over C: Entity extraction
    
    C->>DB: Get chunks
    C->>DB: Save entities
    C->>C: Submit relationship task
    
    Note over C: Relationship building
    
    C->>DB: Get entities
    C->>DB: Save relationships
    C->>DB: Update status to complete
    
    API->>DB: Check status
    DB-->>API: Return complete
    API-->>U: Processing complete
```

## Data Integrity Flow

```mermaid
graph TB
    subgraph "Input Validation"
        IV[File Upload] --> FV{Valid File?}
        FV -->|No| REJ[Reject]
        FV -->|Yes| HASH[Generate SHA256]
    end
    
    subgraph "Deduplication"
        HASH --> DUP{Duplicate?}
        DUP -->|Yes| EXIST[Return Existing]
        DUP -->|No| NEW[Create New Record]
    end
    
    subgraph "Processing Validation"
        NEW --> PROC[Process Document]
        PROC --> VAL{Valid Output?}
        VAL -->|No| RETRY[Retry/Flag]
        VAL -->|Yes| STORE[Store Results]
    end
    
    subgraph "Referential Integrity"
        STORE --> FK{FK Valid?}
        FK -->|No| ERR[Log Error]
        FK -->|Yes| COMMIT[Commit Transaction]
    end
    
    subgraph "Audit Trail"
        COMMIT --> LOG[processing_logs]
        ERR --> LOG
        RETRY --> LOG
    end
```

## Query Pattern Flow

```mermaid
graph LR
    subgraph "Common Queries"
        Q1[Get Project Documents]
        Q2[Get Document Chunks]
        Q3[Find Entity Mentions]
        Q4[Get Relationships]
    end
    
    subgraph "Optimized Paths"
        Q1 --> I1[Index: project_uuid]
        Q2 --> I2[Index: document_uuid]
        Q3 --> I3[Index: entity_text]
        Q4 --> I4[Index: entity_uuids]
    end
    
    subgraph "Join Patterns"
        J1[projects ⟷ documents]
        J2[documents ⟷ chunks]
        J3[chunks ⟷ entities]
        J4[entities ⟷ relationships]
    end
    
    I1 --> J1
    I2 --> J2
    I3 --> J3
    I4 --> J4
```

## Performance Characteristics

### Write Performance
- **Document Creation**: ~10ms (single record)
- **Chunk Batch Insert**: ~100ms (100 chunks)
- **Entity Batch Insert**: ~200ms (500 entities)
- **Relationship Building**: ~500ms (1000 relationships)

### Read Performance
- **Document Retrieval**: ~5ms (with indexes)
- **Chunk Retrieval**: ~20ms (100 chunks)
- **Entity Search**: ~50ms (full-text search)
- **Graph Traversal**: ~100ms (2-hop relationships)

### Storage Efficiency
- **Original Document**: 10MB (S3)
- **Extracted Text**: 200KB (RDS)
- **Processing Metadata**: 50KB (RDS)
- **Total RDS Storage**: ~1MB per document
- **Compression Ratio**: 10:1

## Data Lifecycle

```mermaid
graph TD
    subgraph "Active Phase"
        A1[Document Upload]
        A2[Processing]
        A3[Analysis]
        A4[Active Use]
    end
    
    subgraph "Archive Phase"
        AR1[Move to Cold Storage]
        AR2[Compress Chunks]
        AR3[Archive Entities]
    end
    
    subgraph "Retention"
        R1[7 Years Legal Hold]
        R2[Audit Trail Forever]
        R3[Purge Personal Data]
    end
    
    A1 --> A2 --> A3 --> A4
    A4 -->|After 1 Year| AR1
    AR1 --> AR2 --> AR3
    AR3 --> R1
    A1 --> R2
    R1 -->|GDPR Request| R3
```

## Bottleneck Analysis

```mermaid
graph TB
    subgraph "Potential Bottlenecks"
        B1[OCR Processing: 5-30s per page]
        B2[Entity Extraction: 2s per chunk]
        B3[Relationship Building: O(n²) complexity]
        B4[Database Writes: Connection pool limits]
    end
    
    subgraph "Mitigation Strategies"
        M1[Parallel OCR with Textract]
        M2[Batch Entity Processing]
        M3[Graph Algorithm Optimization]
        M4[Connection Pool Tuning]
    end
    
    B1 --> M1
    B2 --> M2
    B3 --> M3
    B4 --> M4
```

## Monitoring Points

```mermaid
graph LR
    subgraph "Key Metrics"
        M1[Documents/Hour]
        M2[Average Processing Time]
        M3[Error Rate]
        M4[Storage Growth]
        M5[Query Performance]
    end
    
    subgraph "Alerts"
        A1[Processing > 5 min]
        A2[Error Rate > 5%]
        A3[Storage > 80%]
        A4[Connection Pool Exhausted]
    end
    
    M1 --> A1
    M3 --> A2
    M4 --> A3
    M5 --> A4
```

## Conclusion

The RDS implementation provides a straightforward, efficient data flow with clear progression from document upload through knowledge graph creation. The simplified 7-table schema reduces complexity while maintaining full tracking capabilities through the `processing_logs` table.

Key advantages of this flow:
1. **Linear progression** through well-defined states
2. **Strong referential integrity** with foreign keys
3. **Efficient storage** with 10:1 compression ratio
4. **Clear audit trail** for compliance
5. **Scalable architecture** with indexed access patterns

The main challenges are OCR processing time and relationship building complexity, both of which can be mitigated through parallel processing and algorithm optimization.