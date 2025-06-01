-- Fix timestamp trigger issues by removing all update triggers
-- Since Celery/Redis manage state, we don't need automatic timestamp updates

-- Drop all update timestamp triggers
DROP TRIGGER IF EXISTS update_source_documents_updated_at ON source_documents;
DROP TRIGGER IF EXISTS update_neo4j_documents_updated_at ON neo4j_documents;
DROP TRIGGER IF EXISTS update_queue_updated_at ON document_processing_queue;

-- Drop the update functions if they exist
DROP FUNCTION IF EXISTS update_updated_at_column() CASCADE;
DROP FUNCTION IF EXISTS update_last_modified_at_column() CASCADE;

-- Verify no update triggers remain
SELECT 
    c.relname AS table_name,
    t.tgname AS trigger_name
FROM pg_trigger t
JOIN pg_class c ON t.tgrelid = c.oid
JOIN pg_namespace n ON c.relnamespace = n.oid
WHERE n.nspname = 'public'
  AND NOT t.tgisinternal
  AND t.tgname LIKE '%update%'
ORDER BY c.relname, t.tgname;