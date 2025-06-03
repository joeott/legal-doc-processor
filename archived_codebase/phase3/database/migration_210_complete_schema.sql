-- Migration 210: Complete Context 203 Schema Implementation
-- Date: 2025-05-30
-- Based on: context_203_supabase_redesign_proposal.md

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;

-- =============================================================================
-- 1. CORE TABLES
-- =============================================================================

-- Projects table (already exists, but ensure proper structure)
CREATE TABLE IF NOT EXISTS projects (
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
    archived_at TIMESTAMPTZ
);

-- Create indexes for projects if they don't exist
CREATE INDEX IF NOT EXISTS idx_projects_name ON projects (project_name);
CREATE INDEX IF NOT EXISTS idx_projects_active ON projects (archived_at) WHERE archived_at IS NULL;

-- Documents table (update existing or create new structure)
DROP TABLE IF EXISTS documents CASCADE;
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
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create indexes for documents
CREATE UNIQUE INDEX idx_documents_hash ON documents (project_uuid, file_hash);
CREATE INDEX idx_documents_status ON documents (processing_status, processing_stage);
CREATE INDEX idx_documents_project ON documents (project_uuid, created_at DESC);
CREATE INDEX idx_documents_celery ON documents (celery_task_id) WHERE celery_task_id IS NOT NULL;

-- =============================================================================
-- 2. PROCESSING PIPELINE TABLES
-- =============================================================================

-- Processing pipeline table
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
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create indexes for processing_pipeline
CREATE INDEX idx_pipeline_document ON processing_pipeline (document_uuid, stage_name);
CREATE INDEX idx_pipeline_status ON processing_pipeline (stage_status, created_at DESC);
CREATE INDEX idx_pipeline_performance ON processing_pipeline (stage_name, stage_duration_ms);

-- Processing queue table
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
    retry_after TIMESTAMPTZ
);

-- Create indexes for processing_queue
CREATE INDEX idx_queue_priority ON processing_queue (queue_status, priority DESC, scheduled_at);
CREATE INDEX idx_queue_document ON processing_queue (document_uuid);

-- =============================================================================
-- 3. CONTENT TABLES
-- =============================================================================

-- Document chunks table
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
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create indexes for document_chunks
CREATE UNIQUE INDEX idx_chunks_position ON document_chunks (document_uuid, chunk_index);
CREATE INDEX idx_chunks_embedding ON document_chunks USING ivfflat (embedding) WITH (lists = 100);

-- =============================================================================
-- 4. ENTITY TABLES
-- =============================================================================

-- Entity mentions table
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
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create indexes for entity_mentions
CREATE INDEX idx_mentions_chunk ON entity_mentions (chunk_uuid);
CREATE INDEX idx_mentions_canonical ON entity_mentions (canonical_entity_uuid);
CREATE INDEX idx_mentions_type ON entity_mentions (entity_type, entity_text);

-- Canonical entities table
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
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create indexes for canonical_entities
CREATE INDEX idx_entities_project ON canonical_entities (project_uuid);
CREATE INDEX idx_entities_type ON canonical_entities (entity_type, entity_name);
CREATE INDEX idx_entities_name_embedding ON canonical_entities USING ivfflat (name_embedding) WITH (lists = 100);
CREATE UNIQUE INDEX idx_entities_unique ON canonical_entities (project_uuid, entity_type, lower(entity_name));

-- =============================================================================
-- 5. RELATIONSHIP TABLES
-- =============================================================================

-- Relationship staging table
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
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create indexes for relationship_staging
CREATE INDEX idx_staging_from ON relationship_staging (from_entity_uuid, relationship_type);
CREATE INDEX idx_staging_to ON relationship_staging (to_entity_uuid, relationship_type);
CREATE INDEX idx_staging_sync ON relationship_staging (synced_to_neo4j, created_at) WHERE NOT synced_to_neo4j;
CREATE INDEX idx_staging_document ON relationship_staging (source_document_uuid);

-- =============================================================================
-- 6. MONITORING TABLES
-- =============================================================================

-- Processing metrics table
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
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create indexes for processing_metrics
CREATE UNIQUE INDEX idx_metrics_window ON processing_metrics (metric_date, metric_hour, project_uuid, processing_stage);
CREATE INDEX idx_metrics_performance ON processing_metrics (metric_date DESC, avg_duration_ms);

-- Import sessions table (ensure proper structure)
DROP TABLE IF EXISTS import_sessions CASCADE;
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
    error_summary JSONB DEFAULT '{}'
);

-- Create indexes for import_sessions
CREATE INDEX idx_sessions_project ON import_sessions (project_uuid, started_at DESC);
CREATE INDEX idx_sessions_active ON import_sessions (completed_at) WHERE completed_at IS NULL;

-- =============================================================================
-- 7. DATABASE VIEWS
-- =============================================================================

-- Pipeline status view
CREATE OR REPLACE VIEW v_pipeline_status AS
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

-- Entity resolution quality view
CREATE OR REPLACE VIEW v_entity_resolution_quality AS
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

-- Processing throughput view
CREATE OR REPLACE VIEW v_processing_throughput AS
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

-- =============================================================================
-- 8. ADDITIONAL CONSTRAINTS AND TRIGGERS
-- =============================================================================

-- Add foreign key constraints to entity_mentions
ALTER TABLE entity_mentions 
ADD CONSTRAINT fk_mentions_canonical 
FOREIGN KEY (canonical_entity_uuid) 
REFERENCES canonical_entities(entity_uuid);

-- Add check constraints for valid statuses
ALTER TABLE documents 
ADD CONSTRAINT chk_processing_status 
CHECK (processing_status IN ('pending', 'processing', 'completed', 'failed', 'paused'));

ALTER TABLE processing_pipeline 
ADD CONSTRAINT chk_stage_status 
CHECK (stage_status IN ('pending', 'processing', 'completed', 'failed', 'skipped'));

ALTER TABLE processing_queue 
ADD CONSTRAINT chk_queue_status 
CHECK (queue_status IN ('pending', 'assigned', 'processing', 'completed', 'failed'));

-- Add updated_at triggers for main tables
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Apply updated_at triggers
DROP TRIGGER IF EXISTS update_projects_updated_at ON projects;
CREATE TRIGGER update_projects_updated_at 
    BEFORE UPDATE ON projects 
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_documents_updated_at ON documents;
CREATE TRIGGER update_documents_updated_at 
    BEFORE UPDATE ON documents 
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_processing_pipeline_updated_at ON processing_pipeline;
CREATE TRIGGER update_processing_pipeline_updated_at 
    BEFORE UPDATE ON processing_pipeline 
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_document_chunks_updated_at ON document_chunks;
CREATE TRIGGER update_document_chunks_updated_at 
    BEFORE UPDATE ON document_chunks 
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_canonical_entities_updated_at ON canonical_entities;
CREATE TRIGGER update_canonical_entities_updated_at 
    BEFORE UPDATE ON canonical_entities 
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_processing_metrics_updated_at ON processing_metrics;
CREATE TRIGGER update_processing_metrics_updated_at 
    BEFORE UPDATE ON processing_metrics 
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- =============================================================================
-- MIGRATION COMPLETE
-- =============================================================================

-- Migration summary comment
COMMENT ON SCHEMA public IS 'Context 203 Schema - Complete legal document processing pipeline schema optimized for 450+ documents with Neo4j compatibility';