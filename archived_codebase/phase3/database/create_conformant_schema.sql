-- RDS Conformant Schema for Document Processing Pipeline
-- This schema matches exactly what the scripts expect
-- Date: 2025-05-30

-- Drop existing tables if they exist (be careful in production!)
DROP TABLE IF EXISTS document_processing_history CASCADE;
DROP TABLE IF EXISTS canonical_entity_embeddings CASCADE;
DROP TABLE IF EXISTS chunk_embeddings CASCADE;
DROP TABLE IF EXISTS textract_jobs CASCADE;
DROP TABLE IF EXISTS relationship_staging CASCADE;
DROP TABLE IF EXISTS canonical_entities CASCADE;
DROP TABLE IF EXISTS entity_mentions CASCADE;
DROP TABLE IF EXISTS document_chunks CASCADE;
DROP TABLE IF EXISTS neo4j_documents CASCADE;
DROP TABLE IF EXISTS import_sessions CASCADE;
DROP TABLE IF EXISTS source_documents CASCADE;
DROP TABLE IF EXISTS projects CASCADE;

-- Also drop the simplified tables if they exist
DROP TABLE IF EXISTS relationships CASCADE;
DROP TABLE IF EXISTS entities CASCADE;
DROP TABLE IF EXISTS chunks CASCADE;
DROP TABLE IF EXISTS documents CASCADE;
DROP TABLE IF EXISTS processing_logs CASCADE;

-- 1. Projects table with script-expected structure
CREATE TABLE IF NOT EXISTS projects (
    id SERIAL PRIMARY KEY,
    project_uuid UUID UNIQUE NOT NULL DEFAULT gen_random_uuid(),
    supabase_project_id UUID,  -- Legacy compatibility
    name TEXT NOT NULL,
    client_name TEXT,
    matter_type TEXT,
    data_layer TEXT DEFAULT 'production',
    airtable_id TEXT,
    metadata JSONB DEFAULT '{}',
    active BOOLEAN DEFAULT true,
    script_run_count INTEGER DEFAULT 0,
    processed_by_scripts BOOLEAN DEFAULT false,
    last_synced_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 2. Source documents (main document table)
CREATE TABLE IF NOT EXISTS source_documents (
    id SERIAL PRIMARY KEY,
    document_uuid UUID UNIQUE NOT NULL DEFAULT gen_random_uuid(),
    project_uuid UUID REFERENCES projects(project_uuid) ON DELETE CASCADE,
    project_fk_id INTEGER REFERENCES projects(id),  -- Scripts expect integer FK
    import_session_id UUID,
    
    -- File information
    filename TEXT NOT NULL,
    original_filename TEXT,
    original_file_path TEXT,
    file_path TEXT,
    file_type TEXT,
    detected_file_type TEXT,
    file_size_bytes BIGINT,
    
    -- S3 storage
    s3_key TEXT,
    s3_bucket TEXT,
    s3_region TEXT DEFAULT 'us-east-1',
    s3_key_public TEXT,
    s3_bucket_public TEXT,
    
    -- Processing status
    processing_status TEXT DEFAULT 'pending',
    initial_processing_status TEXT,
    celery_status TEXT,
    celery_task_id TEXT,
    
    -- Extracted content
    raw_extracted_text TEXT,
    markdown_text TEXT,
    cleaned_text TEXT,
    
    -- OCR metadata
    ocr_metadata_json JSONB DEFAULT '{}',
    ocr_provider TEXT,
    ocr_completed_at TIMESTAMP WITH TIME ZONE,
    ocr_processing_seconds NUMERIC,
    ocr_confidence_score NUMERIC,
    
    -- Textract specific
    textract_job_id TEXT,
    textract_job_status TEXT,
    textract_start_time TIMESTAMP WITH TIME ZONE,
    textract_end_time TIMESTAMP WITH TIME ZONE,
    textract_page_count INTEGER,
    textract_error_message TEXT,
    
    -- Audio/transcription
    transcription_metadata_json JSONB DEFAULT '{}',
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 3. Import sessions
CREATE TABLE IF NOT EXISTS import_sessions (
    id SERIAL PRIMARY KEY,
    session_uuid UUID UNIQUE NOT NULL DEFAULT gen_random_uuid(),
    project_uuid UUID REFERENCES projects(project_uuid),
    manifest_data JSONB NOT NULL,
    total_documents INTEGER DEFAULT 0,
    processed_documents INTEGER DEFAULT 0,
    failed_documents INTEGER DEFAULT 0,
    status TEXT DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP WITH TIME ZONE
);

-- 4. Neo4j documents (for graph representation)
CREATE TABLE IF NOT EXISTS neo4j_documents (
    id SERIAL PRIMARY KEY,
    document_uuid UUID REFERENCES source_documents(document_uuid) ON DELETE CASCADE,
    neo4j_node_id TEXT,
    title TEXT,
    document_type TEXT,
    summary TEXT,
    key_entities JSONB DEFAULT '[]',
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 5. Document chunks
CREATE TABLE IF NOT EXISTS document_chunks (
    id SERIAL PRIMARY KEY,
    chunk_uuid UUID UNIQUE NOT NULL DEFAULT gen_random_uuid(),
    document_uuid UUID REFERENCES source_documents(document_uuid) ON DELETE CASCADE,
    document_fk_id INTEGER REFERENCES source_documents(id),
    chunk_index INTEGER NOT NULL,
    chunk_number INTEGER,
    
    -- Content
    text_content TEXT NOT NULL,
    cleaned_text TEXT,
    
    -- Position
    char_start_index INTEGER,
    char_end_index INTEGER,
    start_page INTEGER,
    end_page INTEGER,
    
    -- Metadata
    metadata_json JSONB DEFAULT '{}',
    chunk_type TEXT DEFAULT 'text',
    
    -- Embeddings (can be stored here or separate table)
    embedding_vector FLOAT[],
    embedding_model TEXT,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 6. Entity mentions (raw entities)
CREATE TABLE IF NOT EXISTS entity_mentions (
    id SERIAL PRIMARY KEY,
    mention_uuid UUID UNIQUE NOT NULL DEFAULT gen_random_uuid(),
    document_uuid UUID REFERENCES source_documents(document_uuid) ON DELETE CASCADE,
    chunk_uuid UUID REFERENCES document_chunks(chunk_uuid) ON DELETE CASCADE,
    chunk_fk_id INTEGER REFERENCES document_chunks(id),
    
    -- Entity data
    entity_text TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_subtype TEXT,
    
    -- Position
    start_char INTEGER,
    end_char INTEGER,
    
    -- Confidence and metadata
    confidence_score FLOAT DEFAULT 0.0,
    extraction_method TEXT,
    processing_metadata JSONB DEFAULT '{}',
    
    -- Canonical reference
    canonical_entity_uuid UUID,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 7. Canonical entities (resolved entities)
CREATE TABLE IF NOT EXISTS canonical_entities (
    id SERIAL PRIMARY KEY,
    canonical_entity_uuid UUID UNIQUE NOT NULL DEFAULT gen_random_uuid(),
    entity_type TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    
    -- Resolution data
    mention_count INTEGER DEFAULT 1,
    confidence_score FLOAT DEFAULT 0.0,
    resolution_method TEXT,
    
    -- Additional info
    aliases JSONB DEFAULT '[]',
    properties JSONB DEFAULT '{}',
    metadata JSONB DEFAULT '{}',
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 8. Relationship staging
CREATE TABLE IF NOT EXISTS relationship_staging (
    id SERIAL PRIMARY KEY,
    source_entity_uuid UUID REFERENCES canonical_entities(canonical_entity_uuid),
    target_entity_uuid UUID REFERENCES canonical_entities(canonical_entity_uuid),
    relationship_type TEXT NOT NULL,
    confidence_score FLOAT DEFAULT 0.0,
    
    -- Context
    source_chunk_uuid UUID REFERENCES document_chunks(chunk_uuid),
    evidence_text TEXT,
    
    -- Metadata
    properties JSONB DEFAULT '{}',
    metadata JSONB DEFAULT '{}',
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(source_entity_uuid, target_entity_uuid, relationship_type)
);

-- 9. Textract jobs
CREATE TABLE IF NOT EXISTS textract_jobs (
    id SERIAL PRIMARY KEY,
    job_id TEXT UNIQUE NOT NULL,
    document_uuid UUID REFERENCES source_documents(document_uuid),
    job_type TEXT DEFAULT 'DetectDocumentText',
    status TEXT DEFAULT 'IN_PROGRESS',
    
    -- Timing
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    
    -- Results
    page_count INTEGER,
    result_s3_key TEXT,
    error_message TEXT,
    metadata JSONB DEFAULT '{}'
);

-- 10. Chunk embeddings
CREATE TABLE IF NOT EXISTS chunk_embeddings (
    id SERIAL PRIMARY KEY,
    chunk_uuid UUID REFERENCES document_chunks(chunk_uuid) ON DELETE CASCADE,
    embedding_vector FLOAT[] NOT NULL,
    model_name TEXT NOT NULL,
    model_version TEXT,
    dimensions INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(chunk_uuid, model_name)
);

-- 11. Canonical entity embeddings
CREATE TABLE IF NOT EXISTS canonical_entity_embeddings (
    id SERIAL PRIMARY KEY,
    canonical_entity_uuid UUID REFERENCES canonical_entities(canonical_entity_uuid) ON DELETE CASCADE,
    embedding_vector FLOAT[] NOT NULL,
    model_name TEXT NOT NULL,
    model_version TEXT,
    dimensions INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(canonical_entity_uuid, model_name)
);

-- 12. Document processing history
CREATE TABLE IF NOT EXISTS document_processing_history (
    id SERIAL PRIMARY KEY,
    document_uuid UUID REFERENCES source_documents(document_uuid) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    event_status TEXT,
    event_data JSONB DEFAULT '{}',
    error_message TEXT,
    processing_time_seconds NUMERIC,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Keep schema_version table for migrations
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    description TEXT,
    applied_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Insert schema version
INSERT INTO schema_version (version, description) VALUES 
(2, 'Complete conformant schema matching script expectations')
ON CONFLICT (version) DO NOTHING;

-- Critical performance indexes
CREATE INDEX idx_source_documents_project_uuid ON source_documents(project_uuid);
CREATE INDEX idx_source_documents_processing_status ON source_documents(processing_status);
CREATE INDEX idx_source_documents_created_at ON source_documents(created_at DESC);
CREATE INDEX idx_source_documents_import_session ON source_documents(import_session_id);

CREATE INDEX idx_document_chunks_document_uuid ON document_chunks(document_uuid);
CREATE INDEX idx_document_chunks_chunk_index ON document_chunks(document_uuid, chunk_index);

CREATE INDEX idx_entity_mentions_document_uuid ON entity_mentions(document_uuid);
CREATE INDEX idx_entity_mentions_chunk_uuid ON entity_mentions(chunk_uuid);
CREATE INDEX idx_entity_mentions_canonical ON entity_mentions(canonical_entity_uuid);
CREATE INDEX idx_entity_mentions_type ON entity_mentions(entity_type);

CREATE INDEX idx_canonical_entities_type ON canonical_entities(entity_type);
CREATE INDEX idx_canonical_entities_name ON canonical_entities(canonical_name);

CREATE INDEX idx_relationship_staging_source ON relationship_staging(source_entity_uuid);
CREATE INDEX idx_relationship_staging_target ON relationship_staging(target_entity_uuid);
CREATE INDEX idx_relationship_staging_type ON relationship_staging(relationship_type);

CREATE INDEX idx_textract_jobs_document ON textract_jobs(document_uuid);
CREATE INDEX idx_textract_jobs_status ON textract_jobs(status);

-- Full text search indexes
CREATE INDEX idx_source_documents_text_search ON source_documents USING gin(to_tsvector('english', COALESCE(raw_extracted_text, '')));
CREATE INDEX idx_document_chunks_text_search ON document_chunks USING gin(to_tsvector('english', COALESCE(text_content, '')));

-- Update timestamp function
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Apply update triggers
CREATE TRIGGER update_projects_updated_at BEFORE UPDATE ON projects
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_source_documents_updated_at BEFORE UPDATE ON source_documents
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_neo4j_documents_updated_at BEFORE UPDATE ON neo4j_documents
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_document_chunks_updated_at BEFORE UPDATE ON document_chunks
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_canonical_entities_updated_at BEFORE UPDATE ON canonical_entities
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Auto-populate integer foreign keys
CREATE OR REPLACE FUNCTION populate_integer_fks()
RETURNS TRIGGER AS $$
BEGIN
    -- For source_documents
    IF TG_TABLE_NAME = 'source_documents' AND NEW.project_uuid IS NOT NULL THEN
        SELECT id INTO NEW.project_fk_id FROM projects WHERE project_uuid = NEW.project_uuid;
    END IF;
    
    -- For document_chunks
    IF TG_TABLE_NAME = 'document_chunks' AND NEW.document_uuid IS NOT NULL THEN
        SELECT id INTO NEW.document_fk_id FROM source_documents WHERE document_uuid = NEW.document_uuid;
    END IF;
    
    -- For entity_mentions
    IF TG_TABLE_NAME = 'entity_mentions' AND NEW.chunk_uuid IS NOT NULL THEN
        SELECT id INTO NEW.chunk_fk_id FROM document_chunks WHERE chunk_uuid = NEW.chunk_uuid;
    END IF;
    
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER populate_source_documents_fks BEFORE INSERT OR UPDATE ON source_documents
    FOR EACH ROW EXECUTE FUNCTION populate_integer_fks();

CREATE TRIGGER populate_document_chunks_fks BEFORE INSERT OR UPDATE ON document_chunks
    FOR EACH ROW EXECUTE FUNCTION populate_integer_fks();

CREATE TRIGGER populate_entity_mentions_fks BEFORE INSERT OR UPDATE ON entity_mentions
    FOR EACH ROW EXECUTE FUNCTION populate_integer_fks();

-- Grant permissions to app_user
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO app_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO app_user;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO app_user;