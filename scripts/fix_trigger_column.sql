-- Fix the trigger function to use project_id instead of project_uuid
CREATE OR REPLACE FUNCTION populate_integer_fks()
RETURNS TRIGGER AS $$
BEGIN
    -- Populate project_id from project_uuid (which is actually project_id due to renaming)
    IF NEW.project_uuid IS NOT NULL AND NEW.project_id IS NULL THEN
        SELECT id INTO NEW.project_id
        FROM projects 
        WHERE project_id = NEW.project_uuid;
    END IF;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;