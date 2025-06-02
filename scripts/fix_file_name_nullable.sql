-- Make file_name nullable to match Pydantic model
-- The Pydantic SourceDocumentModel only has original_file_name, not file_name
ALTER TABLE source_documents 
ALTER COLUMN file_name DROP NOT NULL;

-- Verify the change
SELECT column_name, is_nullable 
FROM information_schema.columns 
WHERE table_name = 'source_documents' 
AND column_name IN ('file_name', 'original_file_name');