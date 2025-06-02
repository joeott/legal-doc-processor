-- Fix the populate_integer_fks function to use correct column names

CREATE OR REPLACE FUNCTION public.populate_integer_fks()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
BEGIN
    -- For source_documents
    IF TG_TABLE_NAME = 'source_documents' THEN
        IF NEW.project_uuid IS NOT NULL THEN
            SELECT id INTO NEW.project_fk_id FROM projects WHERE project_id = NEW.project_uuid;
        END IF;
    END IF;
    
    -- For document_chunks
    IF TG_TABLE_NAME = 'document_chunks' THEN
        IF NEW.document_uuid IS NOT NULL THEN
            SELECT id INTO NEW.document_fk_id FROM source_documents WHERE document_uuid = NEW.document_uuid;
        END IF;
    END IF;
    
    -- For entity_mentions
    IF TG_TABLE_NAME = 'entity_mentions' THEN
        IF NEW.chunk_uuid IS NOT NULL THEN
            SELECT id INTO NEW.chunk_fk_id FROM document_chunks WHERE chunk_uuid = NEW.chunk_uuid;
        END IF;
    END IF;
    
    RETURN NEW;
END;
$function$;