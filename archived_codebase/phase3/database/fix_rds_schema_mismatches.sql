-- Fix RDS Schema to Match Pydantic Models
-- Date: 2025-01-06
-- Purpose: Align RDS schema with Pydantic models for successful document processing

-- 1. Fix source_documents table column names
ALTER TABLE source_documents 
    RENAME COLUMN filename TO file_name;

ALTER TABLE source_documents 
    RENAME COLUMN processing_status TO status;

-- Add missing columns expected by SourceDocumentModel
ALTER TABLE source_documents 
    ADD COLUMN IF NOT EXISTS processing_completed_at TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS error_message TEXT,
    ADD COLUMN IF NOT EXISTS retry_count INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS last_retry_at TIMESTAMP WITH TIME ZONE;

-- 2. Create missing processing_tasks table
CREATE TABLE IF NOT EXISTS processing_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES source_documents(document_uuid),
    task_type VARCHAR(50) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    celery_task_id VARCHAR(255),
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    -- Add indexes for performance
    CONSTRAINT idx_processing_tasks_document_id 
        FOREIGN KEY (document_id) REFERENCES source_documents(document_uuid) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_processing_tasks_document_id ON processing_tasks(document_id);
CREATE INDEX IF NOT EXISTS idx_processing_tasks_status ON processing_tasks(status);
CREATE INDEX IF NOT EXISTS idx_processing_tasks_task_type ON processing_tasks(task_type);

-- 3. Fix document_chunks table
ALTER TABLE document_chunks 
    RENAME COLUMN content TO text;

-- Add missing columns for ChunkModel
ALTER TABLE document_chunks 
    ADD COLUMN IF NOT EXISTS start_char_index INTEGER,
    ADD COLUMN IF NOT EXISTS end_char_index INTEGER,
    ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}';

-- 4. Fix entity_mentions table
-- Add missing columns expected by EntityMentionModel
ALTER TABLE entity_mentions 
    ADD COLUMN IF NOT EXISTS chunk_id UUID,
    ADD COLUMN IF NOT EXISTS confidence_score NUMERIC(5,4);

-- 5. Update projects table to match ProjectModel
ALTER TABLE projects 
    ADD COLUMN IF NOT EXISTS description TEXT,
    ADD COLUMN IF NOT EXISTS status VARCHAR(50) DEFAULT 'active',
    ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS client_name VARCHAR(255),
    ADD COLUMN IF NOT EXISTS matter_number VARCHAR(100);

-- 6. Add updated_at triggers for all tables that need them
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Create triggers for tables missing them
CREATE TRIGGER update_processing_tasks_updated_at 
    BEFORE UPDATE ON processing_tasks 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();

-- 7. Fix any foreign key constraints
-- Ensure document_chunks references source_documents properly
ALTER TABLE document_chunks
    DROP CONSTRAINT IF EXISTS document_chunks_document_id_fkey;

ALTER TABLE document_chunks
    ADD CONSTRAINT document_chunks_document_id_fkey 
    FOREIGN KEY (document_id) 
    REFERENCES source_documents(document_uuid) 
    ON DELETE CASCADE;

-- 8. Create index for better performance
CREATE INDEX IF NOT EXISTS idx_source_documents_status ON source_documents(status);
CREATE INDEX IF NOT EXISTS idx_source_documents_document_uuid ON source_documents(document_uuid);

-- 9. Update existing data to match new schema (if any)
UPDATE source_documents 
SET status = processing_status 
WHERE status IS NULL AND processing_status IS NOT NULL;

-- 10. Add comment to document the schema version
COMMENT ON TABLE source_documents IS 'Aligned with Pydantic models - Version 2025-01-06';
COMMENT ON TABLE processing_tasks IS 'Created to match ProcessingTaskModel - Version 2025-01-06';

-- Verify the changes
-- Run these queries to confirm the schema is correct:
-- SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'source_documents';
-- SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'processing_tasks';
-- SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'document_chunks';