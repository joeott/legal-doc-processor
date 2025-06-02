-- Fix data_layer conversion issue
-- First remove the default, then change type

-- Remove the TEXT default
ALTER TABLE projects 
ALTER COLUMN data_layer DROP DEFAULT;

-- Now convert to JSONB
ALTER TABLE projects 
ALTER COLUMN data_layer TYPE JSONB 
USING CASE 
    WHEN data_layer IS NULL THEN NULL 
    WHEN data_layer = 'production' THEN '{"layer": "production"}'::jsonb
    WHEN data_layer = 'development' THEN '{"layer": "development"}'::jsonb
    ELSE jsonb_build_object('layer', data_layer) 
END;

-- Verify the change
SELECT column_name, data_type, column_default
FROM information_schema.columns
WHERE table_name = 'projects' 
AND column_name = 'data_layer';