-- Simplified RDS PostgreSQL Schema for Legal Document Processing
-- Version: 1.0-simple
-- Date: 2025-01-29
-- 
-- This simplified schema supports all core functionality with minimal complexity

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Create simple schema version tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMPTZ DEFAULT NOW(),
    description TEXT
);

-- 1. PROJECTS TABLE
-- Tracks legal matters/cases
CREATE TABLE projects (
    project_uuid UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    client_name TEXT,
    matter_type TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

CREATE INDEX idx_projects_name ON projects(name);
CREATE INDEX idx_projects_created ON projects(created_at DESC);

-- 2. DOCUMENTS TABLE  
-- Tracks source documents and processing status
CREATE TABLE documents (
    document_uuid UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_uuid UUID REFERENCES projects(project_uuid) ON DELETE CASCADE,
    
    -- File info
    original_filename TEXT NOT NULL,
    file_hash TEXT,
    file_size_bytes BIGINT,
    mime_type TEXT,
    
    -- Storage
    s3_bucket TEXT NOT NULL,
    s3_key TEXT NOT NULL,
    
    -- Processing
    processing_status TEXT NOT NULL DEFAULT 'pending',
    processing_error TEXT,
    celery_task_id TEXT,
    
    -- Results
    page_count INTEGER,
    chunk_count INTEGER,
    entity_count INTEGER,
    
    -- Metadata
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    
    -- Basic constraints
    CONSTRAINT chk_status CHECK (processing_status IN ('pending', 'processing', 'completed', 'failed')),
    CONSTRAINT chk_positive_counts CHECK (
        (page_count IS NULL OR page_count >= 0) AND
        (chunk_count IS NULL OR chunk_count >= 0) AND
        (entity_count IS NULL OR entity_count >= 0)
    )
);

CREATE INDEX idx_documents_project ON documents(project_uuid);
CREATE INDEX idx_documents_status ON documents(processing_status);
CREATE INDEX idx_documents_created ON documents(created_at DESC);
CREATE UNIQUE INDEX idx_documents_hash ON documents(project_uuid, file_hash) WHERE file_hash IS NOT NULL;

-- 3. CHUNKS TABLE
-- Stores document text segments
CREATE TABLE chunks (
    chunk_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_uuid UUID NOT NULL REFERENCES documents(document_uuid) ON DELETE CASCADE,
    
    -- Position
    chunk_index INTEGER NOT NULL,
    page_number INTEGER,
    
    -- Content
    content TEXT NOT NULL,
    token_count INTEGER,
    
    -- Metadata
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    
    -- Ensure unique chunk positions
    CONSTRAINT uq_chunk_position UNIQUE (document_uuid, chunk_index)
);

CREATE INDEX idx_chunks_document ON chunks(document_uuid, chunk_index);

-- 4. ENTITIES TABLE
-- Stores extracted entities
CREATE TABLE entities (
    entity_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_uuid UUID NOT NULL REFERENCES documents(document_uuid) ON DELETE CASCADE,
    chunk_id UUID REFERENCES chunks(chunk_id) ON DELETE SET NULL,
    
    -- Entity info
    entity_type TEXT NOT NULL,
    entity_text TEXT NOT NULL,
    canonical_name TEXT,
    
    -- Quality
    confidence_score FLOAT,
    
    -- Position (optional)
    start_offset INTEGER,
    end_offset INTEGER,
    
    -- Metadata
    attributes JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

CREATE INDEX idx_entities_document ON entities(document_uuid);
CREATE INDEX idx_entities_type ON entities(entity_type);
CREATE INDEX idx_entities_canonical ON entities(canonical_name) WHERE canonical_name IS NOT NULL;

-- 5. RELATIONSHIPS TABLE
-- Stores entity relationships
CREATE TABLE relationships (
    relationship_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_uuid UUID NOT NULL REFERENCES documents(document_uuid) ON DELETE CASCADE,
    
    -- Relationship definition
    from_entity_id UUID NOT NULL REFERENCES entities(entity_id) ON DELETE CASCADE,
    to_entity_id UUID NOT NULL REFERENCES entities(entity_id) ON DELETE CASCADE,
    relationship_type TEXT NOT NULL,
    
    -- Quality
    confidence_score FLOAT,
    
    -- Metadata
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    
    -- Prevent self-relationships
    CONSTRAINT chk_different_entities CHECK (from_entity_id != to_entity_id)
);

CREATE INDEX idx_relationships_document ON relationships(document_uuid);
CREATE INDEX idx_relationships_from ON relationships(from_entity_id);
CREATE INDEX idx_relationships_to ON relationships(to_entity_id);

-- 6. SIMPLE PROCESSING LOGS TABLE (Optional but useful)
-- Tracks processing events for debugging
CREATE TABLE processing_logs (
    log_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_uuid UUID REFERENCES documents(document_uuid) ON DELETE CASCADE,
    
    -- Event info
    event_type TEXT NOT NULL,
    event_status TEXT NOT NULL,
    event_message TEXT,
    event_data JSONB DEFAULT '{}',
    
    -- Timing
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

CREATE INDEX idx_logs_document ON processing_logs(document_uuid, created_at DESC);
CREATE INDEX idx_logs_type ON processing_logs(event_type, created_at DESC);

-- Update timestamp trigger
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply update trigger to tables with updated_at
CREATE TRIGGER update_projects_updated_at BEFORE UPDATE ON projects
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_documents_updated_at BEFORE UPDATE ON documents
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Create application user
CREATE ROLE app_user WITH LOGIN PASSWORD 'CHANGE_ME_IN_PRODUCTION';
GRANT CONNECT ON DATABASE postgres TO app_user;
GRANT USAGE ON SCHEMA public TO app_user;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO app_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO app_user;

-- Insert schema version
INSERT INTO schema_version (version, description) 
VALUES (1, 'Simplified schema - 6 core tables for document processing');

-- Summary view for monitoring
CREATE VIEW v_document_status AS
SELECT 
    d.document_uuid,
    d.original_filename,
    p.name as project_name,
    d.processing_status,
    d.chunk_count,
    d.entity_count,
    d.created_at,
    d.updated_at
FROM documents d
LEFT JOIN projects p ON d.project_uuid = p.project_uuid
ORDER BY d.created_at DESC;

-- Basic stats view
CREATE VIEW v_project_stats AS
SELECT 
    p.project_uuid,
    p.name,
    COUNT(DISTINCT d.document_uuid) as document_count,
    COUNT(DISTINCT CASE WHEN d.processing_status = 'completed' THEN d.document_uuid END) as completed_count,
    COUNT(DISTINCT CASE WHEN d.processing_status = 'failed' THEN d.document_uuid END) as failed_count,
    MAX(d.created_at) as last_document_date
FROM projects p
LEFT JOIN documents d ON p.project_uuid = d.project_uuid
GROUP BY p.project_uuid, p.name;

-- Grant view access
GRANT SELECT ON v_document_status TO app_user;
GRANT SELECT ON v_project_stats TO app_user;

-- Done! 
-- Total: 6 tables, 2 views, ~200 lines vs 1500+ lines in complex schema