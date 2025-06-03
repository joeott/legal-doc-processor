# Context 203: Supabase Structure Redesign Proposal

## Executive Summary

This proposal redesigns the Supabase structure to provide optimal visibility, scale for 450+ document processing, and seamless Neo4j graph compatibility. The design emphasizes clear processing state tracking, efficient querying, and pre-structured data for graph migration.

## Design Principles

1. **Single Source of Truth**: Each piece of data has one authoritative location
2. **Processing Transparency**: Real-time visibility into every stage of the pipeline
3. **Graph-Ready Structure**: Data organized to map directly to Neo4j nodes and relationships
4. **Scale-First Design**: Optimized for parallel processing of hundreds of documents
5. **Error Recovery**: Built-in tracking for failures and reprocessing

## Proposed Table Structure

### 1. Core Tables

#### `projects`
```sql
CREATE TABLE projects (
    -- Identity
    project_uuid UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_name TEXT NOT NULL,
    project_code TEXT UNIQUE,
    
    -- Organization
    client_name TEXT,
    matter_type TEXT,
    
    -- Configuration
    processing_config JSONB DEFAULT '{}',
    entity_resolution_rules JSONB DEFAULT '{}',
    
    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    archived_at TIMESTAMPTZ,
    
    -- Indexes
    INDEX idx_projects_name (project_name),
    INDEX idx_projects_active (archived_at) WHERE archived_at IS NULL
);
```

#### `documents`
```sql
CREATE TABLE documents (
    -- Identity
    document_uuid UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_uuid UUID REFERENCES projects(project_uuid),
    
    -- Source Information
    original_filename TEXT NOT NULL,
    file_hash TEXT NOT NULL,
    file_size_bytes BIGINT,
    mime_type TEXT,
    
    -- Storage
    storage_provider TEXT DEFAULT 's3',
    storage_path TEXT NOT NULL,
    storage_metadata JSONB DEFAULT '{}',
    
    -- Processing State (Single source of truth)
    processing_status TEXT NOT NULL DEFAULT 'pending',
    processing_stage TEXT,
    processing_started_at TIMESTAMPTZ,
    processing_completed_at TIMESTAMPTZ,
    processing_error JSONB,
    
    -- Celery Integration
    celery_task_id TEXT,
    celery_workflow_id TEXT,
    
    -- Results Summary
    page_count INTEGER,
    word_count INTEGER,
    chunk_count INTEGER,
    entity_count INTEGER,
    relationship_count INTEGER,
    
    -- Metadata
    document_date DATE,
    document_type TEXT,
    document_metadata JSONB DEFAULT '{}',
    
    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Indexes
    UNIQUE INDEX idx_documents_hash (project_uuid, file_hash),
    INDEX idx_documents_status (processing_status, processing_stage),
    INDEX idx_documents_project (project_uuid, created_at DESC),
    INDEX idx_documents_celery (celery_task_id) WHERE celery_task_id IS NOT NULL
);
```

### 2. Processing Pipeline Tables

#### `processing_pipeline`
Real-time view of document processing state
```sql
CREATE TABLE processing_pipeline (
    -- Identity
    pipeline_id SERIAL PRIMARY KEY,
    document_uuid UUID REFERENCES documents(document_uuid),
    
    -- Stage Tracking
    stage_name TEXT NOT NULL,
    stage_status TEXT NOT NULL DEFAULT 'pending',
    stage_started_at TIMESTAMPTZ,
    stage_completed_at TIMESTAMPTZ,
    stage_duration_ms INTEGER GENERATED ALWAYS AS 
        (EXTRACT(EPOCH FROM (stage_completed_at - stage_started_at)) * 1000) STORED,
    
    -- Stage Data
    input_data JSONB,
    output_data JSONB,
    error_data JSONB,
    
    -- Performance Metrics
    items_processed INTEGER,
    items_failed INTEGER,
    retry_count INTEGER DEFAULT 0,
    
    -- Celery Integration
    celery_task_id TEXT,
    
    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Indexes
    INDEX idx_pipeline_document (document_uuid, stage_name),
    INDEX idx_pipeline_status (stage_status, created_at DESC),
    INDEX idx_pipeline_performance (stage_name, stage_duration_ms)
);
```

#### `processing_queue`
Manages document processing order and priorities
```sql
CREATE TABLE processing_queue (
    -- Identity
    queue_id SERIAL PRIMARY KEY,
    document_uuid UUID REFERENCES documents(document_uuid),
    
    -- Queue Management
    priority INTEGER DEFAULT 5,
    queue_status TEXT DEFAULT 'pending',
    assigned_worker TEXT,
    
    -- Scheduling
    scheduled_at TIMESTAMPTZ DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    
    -- Retry Logic
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    retry_after TIMESTAMPTZ,
    
    -- Indexes
    INDEX idx_queue_priority (queue_status, priority DESC, scheduled_at),
    INDEX idx_queue_document (document_uuid)
);
```

### 3. Content Tables

#### `document_chunks`
Stores document segments with embeddings
```sql
CREATE TABLE document_chunks (
    -- Identity
    chunk_uuid UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_uuid UUID REFERENCES documents(document_uuid),
    
    -- Position
    chunk_index INTEGER NOT NULL,
    page_number INTEGER,
    
    -- Content
    chunk_text TEXT NOT NULL,
    chunk_tokens INTEGER,
    chunk_metadata JSONB DEFAULT '{}',
    
    -- Boundaries
    char_start INTEGER,
    char_end INTEGER,
    
    -- Embeddings (for vector search)
    embedding_model TEXT,
    embedding VECTOR(1536),
    embedding_created_at TIMESTAMPTZ,
    
    -- Quality Metrics
    confidence_score FLOAT,
    quality_flags JSONB DEFAULT '{}',
    
    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Indexes
    UNIQUE INDEX idx_chunks_position (document_uuid, chunk_index),
    INDEX idx_chunks_embedding (embedding) USING ivfflat
);
```

### 4. Entity Tables

#### `entity_mentions`
Raw entity extractions from chunks
```sql
CREATE TABLE entity_mentions (
    -- Identity
    mention_uuid UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chunk_uuid UUID REFERENCES document_chunks(chunk_uuid),
    
    -- Entity Information
    entity_text TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    confidence_score FLOAT,
    
    -- Position
    start_offset INTEGER,
    end_offset INTEGER,
    
    -- Resolution
    canonical_entity_uuid UUID,
    resolution_confidence FLOAT,
    resolution_method TEXT,
    
    -- Context
    context_before TEXT,
    context_after TEXT,
    attributes JSONB DEFAULT '{}',
    
    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Indexes
    INDEX idx_mentions_chunk (chunk_uuid),
    INDEX idx_mentions_canonical (canonical_entity_uuid),
    INDEX idx_mentions_type (entity_type, entity_text)
);
```

#### `canonical_entities`
Resolved unique entities across documents
```sql
CREATE TABLE canonical_entities (
    -- Identity
    entity_uuid UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_uuid UUID REFERENCES projects(project_uuid),
    
    -- Entity Core
    entity_name TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_subtype TEXT,
    
    -- Aliases and Variations
    aliases TEXT[] DEFAULT '{}',
    mention_count INTEGER DEFAULT 0,
    document_count INTEGER DEFAULT 0,
    
    -- Confidence and Quality
    confidence_score FLOAT,
    verification_status TEXT DEFAULT 'unverified',
    verified_by TEXT,
    verified_at TIMESTAMPTZ,
    
    -- Attributes
    attributes JSONB DEFAULT '{}',
    
    -- Graph Preparation
    neo4j_labels TEXT[] DEFAULT '{}',
    neo4j_properties JSONB DEFAULT '{}',
    
    -- Embeddings
    name_embedding VECTOR(1536),
    context_embedding VECTOR(1536),
    
    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Indexes
    INDEX idx_entities_project (project_uuid),
    INDEX idx_entities_type (entity_type, entity_name),
    INDEX idx_entities_name_embedding (name_embedding) USING ivfflat,
    UNIQUE INDEX idx_entities_unique (project_uuid, entity_type, lower(entity_name))
);
```

### 5. Relationship Tables

#### `relationship_staging`
Pre-graph relationship storage
```sql
CREATE TABLE relationship_staging (
    -- Identity
    staging_uuid UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Relationship Definition
    from_entity_uuid UUID NOT NULL,
    from_entity_type TEXT NOT NULL,
    to_entity_uuid UUID NOT NULL,
    to_entity_type TEXT NOT NULL,
    relationship_type TEXT NOT NULL,
    
    -- Provenance
    source_chunk_uuid UUID REFERENCES document_chunks(chunk_uuid),
    source_document_uuid UUID REFERENCES documents(document_uuid),
    extraction_confidence FLOAT,
    
    -- Properties
    properties JSONB DEFAULT '{}',
    
    -- Graph Sync
    synced_to_neo4j BOOLEAN DEFAULT FALSE,
    neo4j_relationship_id TEXT,
    sync_attempted_at TIMESTAMPTZ,
    sync_error JSONB,
    
    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Indexes
    INDEX idx_staging_from (from_entity_uuid, relationship_type),
    INDEX idx_staging_to (to_entity_uuid, relationship_type),
    INDEX idx_staging_sync (synced_to_neo4j, created_at) WHERE NOT synced_to_neo4j,
    INDEX idx_staging_document (source_document_uuid)
);
```

### 6. Monitoring Tables

#### `processing_metrics`
Aggregated performance metrics
```sql
CREATE TABLE processing_metrics (
    -- Identity
    metric_id SERIAL PRIMARY KEY,
    
    -- Time Window
    metric_date DATE NOT NULL,
    metric_hour INTEGER,
    
    -- Dimensions
    project_uuid UUID REFERENCES projects(project_uuid),
    processing_stage TEXT,
    
    -- Metrics
    documents_processed INTEGER DEFAULT 0,
    documents_failed INTEGER DEFAULT 0,
    avg_duration_ms FLOAT,
    p95_duration_ms FLOAT,
    total_chunks INTEGER DEFAULT 0,
    total_entities INTEGER DEFAULT 0,
    total_relationships INTEGER DEFAULT 0,
    
    -- Error Tracking
    error_count INTEGER DEFAULT 0,
    error_types JSONB DEFAULT '{}',
    
    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Indexes
    UNIQUE INDEX idx_metrics_window (metric_date, metric_hour, project_uuid, processing_stage),
    INDEX idx_metrics_performance (metric_date DESC, avg_duration_ms)
);
```

#### `import_sessions`
Track batch imports and their status
```sql
CREATE TABLE import_sessions (
    -- Identity
    session_uuid UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_uuid UUID REFERENCES projects(project_uuid),
    
    -- Session Info
    session_name TEXT NOT NULL,
    import_source TEXT,
    total_files INTEGER,
    
    -- Progress Tracking
    files_uploaded INTEGER DEFAULT 0,
    files_processing INTEGER DEFAULT 0,
    files_completed INTEGER DEFAULT 0,
    files_failed INTEGER DEFAULT 0,
    
    -- Performance
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    
    -- Metadata
    import_config JSONB DEFAULT '{}',
    error_summary JSONB DEFAULT '{}',
    
    -- Indexes
    INDEX idx_sessions_project (project_uuid, started_at DESC),
    INDEX idx_sessions_active (completed_at) WHERE completed_at IS NULL
);
```

## Database Views for Visibility

### `v_pipeline_status`
Real-time pipeline overview
```sql
CREATE VIEW v_pipeline_status AS
SELECT 
    d.project_uuid,
    p.project_name,
    d.document_uuid,
    d.original_filename,
    d.processing_status,
    d.processing_stage,
    pp.stage_status,
    pp.stage_duration_ms,
    pp.error_data,
    d.chunk_count,
    d.entity_count,
    d.relationship_count
FROM documents d
JOIN projects p ON d.project_uuid = p.project_uuid
LEFT JOIN LATERAL (
    SELECT *
    FROM processing_pipeline pp
    WHERE pp.document_uuid = d.document_uuid
    ORDER BY pp.created_at DESC
    LIMIT 1
) pp ON true
WHERE d.processing_status != 'completed';
```

### `v_entity_resolution_quality`
Monitor entity resolution effectiveness
```sql
CREATE VIEW v_entity_resolution_quality AS
SELECT 
    p.project_uuid,
    p.project_name,
    ce.entity_type,
    COUNT(DISTINCT ce.entity_uuid) as unique_entities,
    AVG(ce.confidence_score) as avg_confidence,
    SUM(ce.mention_count) as total_mentions,
    COUNT(DISTINCT ce.entity_uuid) FILTER (WHERE ce.verification_status = 'verified') as verified_count
FROM canonical_entities ce
JOIN projects p ON ce.project_uuid = p.project_uuid
GROUP BY p.project_uuid, p.project_name, ce.entity_type;
```

### `v_processing_throughput`
Monitor system performance
```sql
CREATE VIEW v_processing_throughput AS
SELECT 
    date_trunc('hour', pp.created_at) as hour,
    pp.stage_name,
    COUNT(*) as stages_processed,
    AVG(pp.stage_duration_ms) as avg_duration_ms,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY pp.stage_duration_ms) as p95_duration_ms,
    COUNT(*) FILTER (WHERE pp.stage_status = 'failed') as failures
FROM processing_pipeline pp
WHERE pp.created_at > NOW() - INTERVAL '24 hours'
GROUP BY date_trunc('hour', pp.created_at), pp.stage_name;
```

## Key Design Decisions

### 1. **No Triggers**
- All processing controlled by Celery
- Database is purely for state storage and querying
- Eliminates trigger-based race conditions

### 2. **UUID Everything**
- All primary keys are UUIDs
- Matches Neo4j node identification
- Enables distributed ID generation

### 3. **JSONB for Flexibility**
- Metadata, properties, and configurations use JSONB
- Allows schema evolution without migrations
- Supports varied document types

### 4. **Separation of Concerns**
- Documents table: Core metadata and overall state
- Processing pipeline: Detailed stage tracking
- Separate tables for chunks, entities, relationships

### 5. **Pre-Graph Structure**
- relationship_staging mirrors Neo4j structure
- canonical_entities includes neo4j_labels and properties
- Easy migration path to graph

## Migration Strategy

1. **Backup Current Data**
2. **Create New Schema in Parallel**
3. **Migrate Historical Data**
4. **Update Application Code**
5. **Cutover with Feature Flags**
6. **Archive Old Schema**

## Performance Optimizations

1. **Partitioning**: Consider partitioning large tables by project_uuid or created_at
2. **Archival**: Move completed documents to archive tables after 90 days
3. **Indexes**: Strategic indexes on all foreign keys and common query patterns
4. **Materialized Views**: For expensive aggregations
5. **Connection Pooling**: Optimize for high concurrent reads

## Monitoring and Visibility

1. **Grafana Dashboards**:
   - Pipeline flow visualization
   - Error rate tracking
   - Performance metrics
   - Entity resolution quality

2. **Alerts**:
   - Processing failures above threshold
   - Performance degradation
   - Queue backup

3. **Admin Interfaces**:
   - Document reprocessing
   - Entity verification
   - Relationship validation

## Next Steps

1. Review and refine schema with team
2. Create migration scripts
3. Update application code for new schema
4. Implement monitoring dashboards
5. Load test with 450+ documents

This structure provides the visibility, scale, and graph compatibility needed for production deployment while maintaining flexibility for future enhancements.