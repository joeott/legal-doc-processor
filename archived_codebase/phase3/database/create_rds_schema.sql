-- RDS PostgreSQL Schema Creation Script
-- Legal Document Processing Pipeline
-- Version: 1.0
-- Date: 2025-01-29
-- 
-- This script creates the complete schema for the document processing pipeline
-- with all recommended improvements from the schema analysis

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- Create custom types
CREATE TYPE processing_status_enum AS ENUM (
    'pending', 
    'processing', 
    'completed', 
    'failed', 
    'cancelled'
);

CREATE TYPE processing_stage_enum AS ENUM (
    'upload', 
    'ocr', 
    'chunking', 
    'entity_extraction', 
    'entity_resolution', 
    'relationship_extraction', 
    'embedding'
);

CREATE TYPE entity_type_enum AS ENUM (
    'PERSON', 
    'ORGANIZATION', 
    'LOCATION', 
    'DATE', 
    'DOCUMENT', 
    'CASE', 
    'STATUTE', 
    'COURT',
    'MONEY',
    'PHONE',
    'EMAIL',
    'ADDRESS'
);

CREATE TYPE queue_status_enum AS ENUM (
    'pending',
    'assigned',
    'processing',
    'completed',
    'failed',
    'cancelled'
);

CREATE TYPE verification_status_enum AS ENUM (
    'unverified',
    'auto_verified',
    'human_verified',
    'disputed'
);

-- 1. CORE TABLES

-- Projects table
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
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    archived_at TIMESTAMPTZ,
    
    -- Constraints
    CONSTRAINT chk_project_name_length CHECK (length(project_name) > 0)
);

-- Create indexes for projects
CREATE INDEX idx_projects_name ON projects(project_name);
CREATE INDEX idx_projects_active ON projects(archived_at) WHERE archived_at IS NULL;
CREATE INDEX idx_projects_client ON projects(client_name);

-- Documents table
CREATE TABLE documents (
    -- Identity
    document_uuid UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_uuid UUID NOT NULL,
    
    -- Source Information
    original_filename TEXT NOT NULL,
    file_hash TEXT NOT NULL,
    file_size_bytes BIGINT,
    mime_type TEXT,
    
    -- Storage
    storage_provider TEXT DEFAULT 's3',
    storage_path TEXT NOT NULL,
    storage_metadata JSONB DEFAULT '{}',
    
    -- Processing State
    processing_status processing_status_enum NOT NULL DEFAULT 'pending',
    processing_stage processing_stage_enum,
    processing_started_at TIMESTAMPTZ,
    processing_completed_at TIMESTAMPTZ,
    processing_error JSONB,
    processing_duration_seconds INTEGER GENERATED ALWAYS AS 
        (EXTRACT(EPOCH FROM (processing_completed_at - processing_started_at))) STORED,
    
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
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    
    -- Foreign key constraints
    CONSTRAINT fk_documents_project 
        FOREIGN KEY (project_uuid) 
        REFERENCES projects(project_uuid) 
        ON DELETE RESTRICT ON UPDATE CASCADE,
    
    -- Check constraints
    CONSTRAINT chk_processing_dates 
        CHECK (processing_completed_at >= processing_started_at),
    CONSTRAINT chk_file_size 
        CHECK (file_size_bytes >= 0),
    CONSTRAINT chk_counts 
        CHECK (
            (page_count IS NULL OR page_count >= 0) AND
            (word_count IS NULL OR word_count >= 0) AND
            (chunk_count IS NULL OR chunk_count >= 0) AND
            (entity_count IS NULL OR entity_count >= 0) AND
            (relationship_count IS NULL OR relationship_count >= 0)
        )
);

-- Create indexes for documents
CREATE UNIQUE INDEX idx_documents_hash ON documents(project_uuid, file_hash);
CREATE INDEX idx_documents_status ON documents(processing_status, processing_stage);
CREATE INDEX idx_documents_project ON documents(project_uuid, created_at DESC);
CREATE INDEX idx_documents_celery ON documents(celery_task_id) WHERE celery_task_id IS NOT NULL;
CREATE INDEX idx_documents_project_status_covering 
    ON documents(project_uuid, processing_status) 
    INCLUDE (original_filename, created_at);

-- 2. PROCESSING PIPELINE TABLES

-- Processing pipeline table (partitioned by month)
CREATE TABLE processing_pipeline (
    -- Identity
    pipeline_id BIGSERIAL NOT NULL,
    document_uuid UUID NOT NULL,
    
    -- Stage Tracking
    stage_name processing_stage_enum NOT NULL,
    stage_status processing_status_enum NOT NULL DEFAULT 'pending',
    stage_started_at TIMESTAMPTZ,
    stage_completed_at TIMESTAMPTZ,
    stage_duration_ms INTEGER GENERATED ALWAYS AS 
        (EXTRACT(EPOCH FROM (stage_completed_at - stage_started_at)) * 1000) STORED,
    
    -- Stage Data
    input_data JSONB,
    output_data JSONB,
    error_data JSONB,
    
    -- Performance Metrics
    items_processed INTEGER DEFAULT 0,
    items_failed INTEGER DEFAULT 0,
    retry_count INTEGER DEFAULT 0,
    
    -- Celery Integration
    celery_task_id TEXT,
    
    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    
    -- Constraints
    CONSTRAINT fk_pipeline_document 
        FOREIGN KEY (document_uuid) 
        REFERENCES documents(document_uuid) 
        ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT chk_pipeline_dates 
        CHECK (stage_completed_at >= stage_started_at),
    CONSTRAINT chk_pipeline_metrics 
        CHECK (items_processed >= 0 AND items_failed >= 0 AND retry_count >= 0),
    PRIMARY KEY (pipeline_id, created_at)
) PARTITION BY RANGE (created_at);

-- Create initial partitions for processing_pipeline
CREATE TABLE processing_pipeline_2025_01 PARTITION OF processing_pipeline
    FOR VALUES FROM ('2025-01-01') TO ('2025-02-01');
CREATE TABLE processing_pipeline_2025_02 PARTITION OF processing_pipeline
    FOR VALUES FROM ('2025-02-01') TO ('2025-03-01');
CREATE TABLE processing_pipeline_2025_03 PARTITION OF processing_pipeline
    FOR VALUES FROM ('2025-03-01') TO ('2025-04-01');

-- Create indexes for processing_pipeline
CREATE INDEX idx_pipeline_document ON processing_pipeline(document_uuid, stage_name);
CREATE INDEX idx_pipeline_status ON processing_pipeline(stage_status, created_at DESC);
CREATE INDEX idx_pipeline_performance ON processing_pipeline(stage_name, stage_duration_ms);
CREATE INDEX idx_pipeline_recent ON processing_pipeline(created_at DESC) 
    WHERE stage_status != 'completed';

-- Add unique constraint for document-stage combination
CREATE UNIQUE INDEX idx_pipeline_document_stage ON processing_pipeline(document_uuid, stage_name);

-- Processing queue table
CREATE TABLE processing_queue (
    -- Identity
    queue_id BIGSERIAL PRIMARY KEY,
    document_uuid UUID NOT NULL,
    
    -- Queue Management
    priority INTEGER DEFAULT 5 CHECK (priority BETWEEN 1 AND 10),
    queue_status queue_status_enum DEFAULT 'pending',
    assigned_worker TEXT,
    
    -- Scheduling
    scheduled_at TIMESTAMPTZ DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    
    -- Retry Logic
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    retry_after TIMESTAMPTZ,
    
    -- Constraints
    CONSTRAINT fk_queue_document 
        FOREIGN KEY (document_uuid) 
        REFERENCES documents(document_uuid) 
        ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT chk_queue_dates 
        CHECK (
            (started_at IS NULL OR started_at >= scheduled_at) AND
            (completed_at IS NULL OR completed_at >= started_at)
        ),
    CONSTRAINT chk_retry_count 
        CHECK (retry_count >= 0 AND retry_count <= max_retries)
);

-- Create indexes for processing_queue
CREATE INDEX idx_queue_priority ON processing_queue(queue_status, priority DESC, scheduled_at)
    WHERE queue_status IN ('pending', 'assigned');
CREATE INDEX idx_queue_document ON processing_queue(document_uuid);
CREATE INDEX idx_queue_retry ON processing_queue(retry_after, queue_status)
    WHERE retry_after IS NOT NULL;

-- 3. CONTENT TABLES

-- Document chunks table
CREATE TABLE document_chunks (
    -- Identity
    chunk_uuid UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_uuid UUID NOT NULL,
    
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
    
    -- Embeddings
    embedding_model TEXT,
    embedding VECTOR(1536),
    embedding_created_at TIMESTAMPTZ,
    
    -- Quality Metrics
    confidence_score FLOAT CHECK (confidence_score BETWEEN 0 AND 1),
    quality_flags JSONB DEFAULT '{}',
    
    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    
    -- Constraints
    CONSTRAINT fk_chunks_document 
        FOREIGN KEY (document_uuid) 
        REFERENCES documents(document_uuid) 
        ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT chk_chunk_boundaries 
        CHECK (
            char_start >= 0 AND 
            char_end > char_start AND
            chunk_index >= 0
        ),
    CONSTRAINT chk_chunk_tokens 
        CHECK (chunk_tokens > 0)
);

-- Create indexes for document_chunks
CREATE UNIQUE INDEX idx_chunks_position ON document_chunks(document_uuid, chunk_index);
CREATE INDEX idx_chunks_document_order ON document_chunks(document_uuid, chunk_index);
CREATE INDEX idx_chunks_embedding ON document_chunks USING ivfflat (embedding vector_cosine_ops)
    WHERE embedding IS NOT NULL;

-- 4. ENTITY TABLES

-- Entity mentions table
CREATE TABLE entity_mentions (
    -- Identity
    mention_uuid UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chunk_uuid UUID NOT NULL,
    
    -- Entity Information
    entity_text TEXT NOT NULL,
    entity_type entity_type_enum NOT NULL,
    confidence_score FLOAT CHECK (confidence_score BETWEEN 0 AND 1),
    
    -- Position
    start_offset INTEGER CHECK (start_offset >= 0),
    end_offset INTEGER CHECK (end_offset > start_offset),
    
    -- Resolution
    canonical_entity_uuid UUID,
    resolution_confidence FLOAT CHECK (resolution_confidence BETWEEN 0 AND 1),
    resolution_method TEXT,
    
    -- Context
    context_before TEXT,
    context_after TEXT,
    attributes JSONB DEFAULT '{}',
    
    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    
    -- Constraints
    CONSTRAINT fk_mentions_chunk 
        FOREIGN KEY (chunk_uuid) 
        REFERENCES document_chunks(chunk_uuid) 
        ON DELETE CASCADE ON UPDATE CASCADE
);

-- Create indexes for entity_mentions
CREATE INDEX idx_mentions_chunk ON entity_mentions(chunk_uuid);
CREATE INDEX idx_mentions_canonical ON entity_mentions(canonical_entity_uuid)
    WHERE canonical_entity_uuid IS NOT NULL;
CREATE INDEX idx_mentions_type ON entity_mentions(entity_type, entity_text);

-- Canonical entities table
CREATE TABLE canonical_entities (
    -- Identity
    entity_uuid UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_uuid UUID NOT NULL,
    
    -- Entity Core
    entity_name TEXT NOT NULL,
    entity_type entity_type_enum NOT NULL,
    entity_subtype TEXT,
    
    -- Aliases and Variations
    aliases TEXT[] DEFAULT '{}',
    mention_count INTEGER DEFAULT 0 CHECK (mention_count >= 0),
    document_count INTEGER DEFAULT 0 CHECK (document_count >= 0),
    
    -- Confidence and Quality
    confidence_score FLOAT CHECK (confidence_score BETWEEN 0 AND 1),
    verification_status verification_status_enum DEFAULT 'unverified',
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
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    
    -- Constraints
    CONSTRAINT fk_entities_project 
        FOREIGN KEY (project_uuid) 
        REFERENCES projects(project_uuid) 
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT chk_verification 
        CHECK (
            (verified_by IS NULL AND verified_at IS NULL) OR
            (verified_by IS NOT NULL AND verified_at IS NOT NULL)
        )
);

-- Create indexes for canonical_entities
CREATE INDEX idx_entities_project ON canonical_entities(project_uuid);
CREATE INDEX idx_entities_type ON canonical_entities(entity_type, entity_name);
CREATE INDEX idx_entities_name_embedding ON canonical_entities USING ivfflat (name_embedding vector_cosine_ops)
    WHERE name_embedding IS NOT NULL;
CREATE UNIQUE INDEX idx_entities_unique ON canonical_entities(project_uuid, entity_type, lower(entity_name));
CREATE INDEX idx_entities_name_trgm ON canonical_entities USING gin (entity_name gin_trgm_ops);

-- 5. RELATIONSHIP TABLES

-- Relationship staging table
CREATE TABLE relationship_staging (
    -- Identity
    staging_uuid UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Relationship Definition
    from_entity_uuid UUID NOT NULL,
    from_entity_type entity_type_enum NOT NULL,
    to_entity_uuid UUID NOT NULL,
    to_entity_type entity_type_enum NOT NULL,
    relationship_type TEXT NOT NULL,
    
    -- Provenance
    source_chunk_uuid UUID,
    source_document_uuid UUID,
    extraction_confidence FLOAT CHECK (extraction_confidence BETWEEN 0 AND 1),
    
    -- Properties
    properties JSONB DEFAULT '{}',
    
    -- Graph Sync
    synced_to_neo4j BOOLEAN DEFAULT FALSE,
    neo4j_relationship_id TEXT,
    sync_attempted_at TIMESTAMPTZ,
    sync_error JSONB,
    
    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    
    -- Constraints
    CONSTRAINT fk_staging_chunk 
        FOREIGN KEY (source_chunk_uuid) 
        REFERENCES document_chunks(chunk_uuid) 
        ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT fk_staging_document 
        FOREIGN KEY (source_document_uuid) 
        REFERENCES documents(document_uuid) 
        ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT chk_different_entities 
        CHECK (from_entity_uuid != to_entity_uuid)
);

-- Create indexes for relationship_staging
CREATE INDEX idx_staging_from ON relationship_staging(from_entity_uuid, relationship_type);
CREATE INDEX idx_staging_to ON relationship_staging(to_entity_uuid, relationship_type);
CREATE INDEX idx_staging_sync ON relationship_staging(synced_to_neo4j, created_at) 
    WHERE NOT synced_to_neo4j;
CREATE INDEX idx_staging_document ON relationship_staging(source_document_uuid);

-- 6. MONITORING TABLES

-- Processing metrics table
CREATE TABLE processing_metrics (
    -- Identity
    metric_id BIGSERIAL PRIMARY KEY,
    
    -- Time Window
    metric_date DATE NOT NULL,
    metric_hour INTEGER CHECK (metric_hour BETWEEN 0 AND 23),
    
    -- Dimensions
    project_uuid UUID,
    processing_stage processing_stage_enum,
    
    -- Metrics
    documents_processed INTEGER DEFAULT 0 CHECK (documents_processed >= 0),
    documents_failed INTEGER DEFAULT 0 CHECK (documents_failed >= 0),
    avg_duration_ms FLOAT CHECK (avg_duration_ms >= 0),
    p95_duration_ms FLOAT CHECK (p95_duration_ms >= 0),
    total_chunks INTEGER DEFAULT 0 CHECK (total_chunks >= 0),
    total_entities INTEGER DEFAULT 0 CHECK (total_entities >= 0),
    total_relationships INTEGER DEFAULT 0 CHECK (total_relationships >= 0),
    
    -- Error Tracking
    error_count INTEGER DEFAULT 0 CHECK (error_count >= 0),
    error_types JSONB DEFAULT '{}',
    
    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    
    -- Constraints
    CONSTRAINT fk_metrics_project 
        FOREIGN KEY (project_uuid) 
        REFERENCES projects(project_uuid) 
        ON DELETE CASCADE ON UPDATE CASCADE
);

-- Create indexes for processing_metrics
CREATE UNIQUE INDEX idx_metrics_window 
    ON processing_metrics(metric_date, metric_hour, project_uuid, processing_stage);
CREATE INDEX idx_metrics_performance ON processing_metrics(metric_date DESC, avg_duration_ms);

-- Import sessions table
CREATE TABLE import_sessions (
    -- Identity
    session_uuid UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_uuid UUID NOT NULL,
    
    -- Session Info
    session_name TEXT NOT NULL,
    import_source TEXT,
    total_files INTEGER CHECK (total_files >= 0),
    
    -- Progress Tracking
    files_uploaded INTEGER DEFAULT 0 CHECK (files_uploaded >= 0),
    files_processing INTEGER DEFAULT 0 CHECK (files_processing >= 0),
    files_completed INTEGER DEFAULT 0 CHECK (files_completed >= 0),
    files_failed INTEGER DEFAULT 0 CHECK (files_failed >= 0),
    
    -- Performance
    started_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    completed_at TIMESTAMPTZ,
    
    -- Metadata
    import_config JSONB DEFAULT '{}',
    error_summary JSONB DEFAULT '{}',
    
    -- Constraints
    CONSTRAINT fk_sessions_project 
        FOREIGN KEY (project_uuid) 
        REFERENCES projects(project_uuid) 
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT chk_session_progress 
        CHECK (
            files_uploaded + files_processing + files_completed + files_failed <= total_files
        ),
    CONSTRAINT chk_session_dates 
        CHECK (completed_at IS NULL OR completed_at >= started_at)
);

-- Create indexes for import_sessions
CREATE INDEX idx_sessions_project ON import_sessions(project_uuid, started_at DESC);
CREATE INDEX idx_sessions_active ON import_sessions(completed_at) WHERE completed_at IS NULL;

-- 7. AUDIT AND COMPLIANCE TABLES

-- Audit log table
CREATE TABLE audit_log (
    audit_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    table_name TEXT NOT NULL,
    record_id UUID NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('INSERT', 'UPDATE', 'DELETE')),
    old_values JSONB,
    new_values JSONB,
    changed_by TEXT NOT NULL,
    changed_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    change_reason TEXT,
    client_ip INET,
    session_id TEXT
);

-- Create indexes for audit_log
CREATE INDEX idx_audit_record ON audit_log(table_name, record_id, changed_at DESC);
CREATE INDEX idx_audit_action ON audit_log(action, changed_at DESC);
CREATE INDEX idx_audit_user ON audit_log(changed_by, changed_at DESC);

-- Document access log table
CREATE TABLE document_access_log (
    access_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_uuid UUID NOT NULL,
    user_id TEXT NOT NULL,
    access_type TEXT NOT NULL CHECK (access_type IN ('view', 'download', 'edit', 'delete')),
    access_timestamp TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    ip_address INET,
    session_id TEXT,
    access_duration_seconds INTEGER,
    
    -- Constraints
    CONSTRAINT fk_access_document 
        FOREIGN KEY (document_uuid) 
        REFERENCES documents(document_uuid) 
        ON DELETE CASCADE ON UPDATE CASCADE
);

-- Create indexes for document_access_log
CREATE INDEX idx_access_document ON document_access_log(document_uuid, access_timestamp DESC);
CREATE INDEX idx_access_user ON document_access_log(user_id, access_timestamp DESC);

-- Document versions table
CREATE TABLE document_versions (
    version_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_uuid UUID NOT NULL,
    version_number INTEGER NOT NULL CHECK (version_number > 0),
    change_description TEXT,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    version_metadata JSONB DEFAULT '{}',
    
    -- Constraints
    CONSTRAINT fk_versions_document 
        FOREIGN KEY (document_uuid) 
        REFERENCES documents(document_uuid) 
        ON DELETE CASCADE ON UPDATE CASCADE
);

-- Create indexes for document_versions
CREATE UNIQUE INDEX idx_versions_unique ON document_versions(document_uuid, version_number);
CREATE INDEX idx_versions_document ON document_versions(document_uuid, created_at DESC);

-- 8. DATABASE VIEWS

-- Pipeline status view
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
    d.relationship_count,
    d.processing_duration_seconds
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
CREATE VIEW v_entity_resolution_quality AS
SELECT 
    p.project_uuid,
    p.project_name,
    ce.entity_type,
    COUNT(DISTINCT ce.entity_uuid) as unique_entities,
    AVG(ce.confidence_score) as avg_confidence,
    SUM(ce.mention_count) as total_mentions,
    COUNT(DISTINCT ce.entity_uuid) FILTER (WHERE ce.verification_status = 'verified') as verified_count,
    COUNT(DISTINCT ce.entity_uuid) FILTER (WHERE ce.verification_status = 'human_verified') as human_verified_count
FROM canonical_entities ce
JOIN projects p ON ce.project_uuid = p.project_uuid
GROUP BY p.project_uuid, p.project_name, ce.entity_type;

-- Processing throughput view
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

-- 9. MATERIALIZED VIEWS

-- Pipeline summary materialized view
CREATE MATERIALIZED VIEW mv_pipeline_summary AS
SELECT 
    project_uuid,
    processing_status,
    processing_stage,
    COUNT(*) as document_count,
    AVG(processing_duration_seconds) as avg_duration_seconds,
    MAX(updated_at) as last_update
FROM documents
GROUP BY project_uuid, processing_status, processing_stage
WITH DATA;

CREATE UNIQUE INDEX ON mv_pipeline_summary (project_uuid, processing_status, processing_stage);

-- Entity statistics materialized view
CREATE MATERIALIZED VIEW mv_entity_statistics AS
SELECT 
    ce.project_uuid,
    ce.entity_type,
    COUNT(DISTINCT ce.entity_uuid) as unique_count,
    SUM(ce.mention_count) as total_mentions,
    AVG(ce.confidence_score) as avg_confidence,
    COUNT(DISTINCT ce.entity_uuid) FILTER (WHERE ce.verification_status != 'unverified') as verified_count
FROM canonical_entities ce
GROUP BY ce.project_uuid, ce.entity_type
WITH DATA;

CREATE UNIQUE INDEX ON mv_entity_statistics (project_uuid, entity_type);

-- 10. FUNCTIONS AND TRIGGERS

-- Update timestamp function
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create update triggers for all tables with updated_at
CREATE TRIGGER update_projects_updated_at BEFORE UPDATE ON projects
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_documents_updated_at BEFORE UPDATE ON documents
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_processing_pipeline_updated_at BEFORE UPDATE ON processing_pipeline
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_document_chunks_updated_at BEFORE UPDATE ON document_chunks
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_canonical_entities_updated_at BEFORE UPDATE ON canonical_entities
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_processing_metrics_updated_at BEFORE UPDATE ON processing_metrics
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- 11. PERMISSIONS AND SECURITY

-- Create application role
CREATE ROLE document_processor WITH LOGIN PASSWORD 'CHANGE_ME_IN_PRODUCTION';

-- Grant permissions
GRANT CONNECT ON DATABASE postgres TO document_processor;
GRANT USAGE ON SCHEMA public TO document_processor;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO document_processor;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO document_processor;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO document_processor;

-- Create read-only role for analytics
CREATE ROLE analytics_reader WITH LOGIN PASSWORD 'CHANGE_ME_IN_PRODUCTION';
GRANT CONNECT ON DATABASE postgres TO analytics_reader;
GRANT USAGE ON SCHEMA public TO analytics_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO analytics_reader;

-- 12. INITIAL DATA

-- Insert default project for testing
INSERT INTO projects (project_uuid, project_name, project_code, client_name)
VALUES ('550e8400-e29b-41d4-a716-446655440000', 'Test Project', 'TEST001', 'Test Client');

-- 13. MAINTENANCE COMMANDS

-- Refresh materialized views (schedule this regularly)
-- REFRESH MATERIALIZED VIEW CONCURRENTLY mv_pipeline_summary;
-- REFRESH MATERIALIZED VIEW CONCURRENTLY mv_entity_statistics;

-- Analyze tables for query optimization (schedule this regularly)
-- ANALYZE;

-- Create future partitions (run monthly)
-- CREATE TABLE processing_pipeline_2025_04 PARTITION OF processing_pipeline
--     FOR VALUES FROM ('2025-04-01') TO ('2025-05-01');

-- Schema version tracking
CREATE TABLE schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMPTZ DEFAULT NOW(),
    description TEXT
);

INSERT INTO schema_version (version, description) 
VALUES (1, 'Initial schema with all improvements from analysis');

-- End of schema creation script