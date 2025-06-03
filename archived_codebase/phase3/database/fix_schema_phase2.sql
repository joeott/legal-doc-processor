-- Phase 2: Fix RDS Schema to Match Pydantic Models
-- The Pydantic models are the source of truth

-- 1. Fix column names in source_documents
ALTER TABLE source_documents 
RENAME COLUMN original_filename TO original_file_name;

-- 2. Fix data_layer type in projects table
-- Convert from TEXT to JSONB to match Pydantic Dict[str, Any]
ALTER TABLE projects 
ALTER COLUMN data_layer TYPE JSONB 
USING CASE 
    WHEN data_layer IS NULL THEN NULL 
    WHEN data_layer = 'production' THEN '{"layer": "production"}'::jsonb
    WHEN data_layer = 'development' THEN '{"layer": "development"}'::jsonb
    ELSE jsonb_build_object('layer', data_layer) 
END;

-- 3. Fix default values to match Pydantic models
-- Pydantic models default these to None, not empty objects
ALTER TABLE source_documents 
ALTER COLUMN ocr_metadata_json DROP DEFAULT;

ALTER TABLE source_documents 
ALTER COLUMN transcription_metadata_json DROP DEFAULT;

ALTER TABLE projects 
ALTER COLUMN metadata DROP DEFAULT;

-- 4. Add helpful indexes for UUID lookups
CREATE INDEX IF NOT EXISTS idx_source_documents_document_uuid 
ON source_documents(document_uuid);

CREATE INDEX IF NOT EXISTS idx_projects_project_uuid 
ON projects(project_uuid);

CREATE INDEX IF NOT EXISTS idx_source_documents_project_fk_id 
ON source_documents(project_fk_id);

-- 5. Verify constraints are proper
-- UUID columns should accept UUID type (they already do)
-- Timestamps have CURRENT_TIMESTAMP defaults (good)

-- Show results
SELECT 'Schema fixes applied. Verifying structure...' as status;

-- Verify source_documents changes
SELECT column_name, data_type, column_default
FROM information_schema.columns
WHERE table_name = 'source_documents' 
AND column_name IN ('original_file_name', 'ocr_metadata_json', 'transcription_metadata_json')
ORDER BY column_name;

-- Verify projects changes  
SELECT column_name, data_type, column_default
FROM information_schema.columns
WHERE table_name = 'projects' 
AND column_name IN ('data_layer', 'metadata')
ORDER BY column_name;