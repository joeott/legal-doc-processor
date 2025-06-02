-- Fix project UUID column name to match Pydantic model
-- Pydantic has: project_id (UUID type)
-- Database has: project_uuid

-- Rename the column to match Pydantic
ALTER TABLE projects 
RENAME COLUMN project_uuid TO project_id;

-- Also update any indexes
DROP INDEX IF EXISTS idx_projects_project_uuid;
CREATE INDEX idx_projects_project_id ON projects(project_id);

-- Check if there are any foreign key references to update
-- (None found in our schema)

-- Verify the change
SELECT column_name, data_type, column_default
FROM information_schema.columns
WHERE table_name = 'projects' 
AND column_name IN ('project_id', 'project_uuid')
ORDER BY ordinal_position;