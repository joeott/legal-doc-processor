System-Wide Improvements for UUID-Based Document Processing
I've implemented comprehensive improvements to ensure a robust UUID-based document processing system. Here's what each change accomplishes:
1. Updated References to Use UUIDs Instead of IDs
sql-- Key changes:
ALTER TABLE IF EXISTS public.neo4j_documents
DROP CONSTRAINT IF EXISTS neo4j_documents_source_document_id_fkey,
ADD CONSTRAINT neo4j_documents_source_document_uuid_fkey FOREIGN KEY (source_document_uuid) 
REFERENCES public.source_documents(document_uuid);

-- Created function to get documents by either ID or UUID
CREATE OR REPLACE FUNCTION public.get_document_by_id(p_document_id VARCHAR)...
This migration ensures:

Foreign key relationships between tables use UUIDs instead of integer IDs
Functions can lookup documents by either ID or UUID for backward compatibility
The system maintains integrity through proper relationship constraints

2. Audited and Fixed Potential Unique Constraint Issues
sql-- Key improvements:
-- Added missing UUID columns to relationship tables
ALTER TABLE public.neo4j_documents ADD COLUMN source_document_uuid VARCHAR...
ALTER TABLE public.neo4j_chunks ADD COLUMN document_uuid VARCHAR...
ALTER TABLE public.neo4j_entity_mentions ADD COLUMN chunk_uuid VARCHAR...

-- Fixed duplicate relationships that could cause conflicts
WITH duplicates AS (SELECT "fromNodeId", "toNodeId", "relationshipType"...)
DELETE FROM public.neo4j_relationships_staging WHERE...
This audit:

Added UUID-based relationships to all relevant tables
Updated existing data to ensure UUID fields are populated
Removed duplicate relationship entries to prevent conflicts
Established proper references between all entity types

3. Enforced UUID Generation and Validation
sql-- Created validation function
CREATE OR REPLACE FUNCTION is_valid_uuid(text) RETURNS BOOLEAN...

-- Set default UUID generation
ALTER TABLE public.projects ALTER COLUMN "projectId" SET DEFAULT gen_random_uuid()::text;
ALTER TABLE public.neo4j_documents ALTER COLUMN "documentId" SET DEFAULT gen_random_uuid()::text;
...

-- Created automatic validation triggers
CREATE TRIGGER trg_ensure_project_uuids BEFORE INSERT ON public.projects...
CREATE TRIGGER trg_ensure_document_uuids BEFORE INSERT ON public.neo4j_documents...
...
These changes ensure:

All UUID columns have proper default values using gen_random_uuid()
Validation triggers automatically fix invalid or missing UUIDs
The system maintains both ID and UUID references for all entities
UUID format is validated against a standardized pattern

4. Added Migration Tracking System
sqlCREATE TABLE IF NOT EXISTS public.database_migrations (
    id SERIAL PRIMARY KEY,
    migration_name VARCHAR NOT NULL,
    migration_description TEXT,
    applied_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    ...
);

CREATE OR REPLACE FUNCTION public.record_migration(...)...
This system:

Tracks all database migrations applied to the system
Records who applied them and when
Logs any errors that occurred during migration
Provides an audit trail for database changes

Benefits of These Changes

Robust Unique Identifiers: Using UUIDs eliminates conflicts from sequential ID generation
Backward Compatibility: Maintains both ID and UUID references for a smooth transition
Data Integrity: Ensures proper relationships between all entities
Automatic Validation: Triggers fix or generate UUIDs when needed
Error Prevention: Removes duplicate entries that could cause conflicts
Audit Trail: Tracks all database migrations for better maintenance

Your document processing system is now much more robust and should work reliably across all components, with proper UUID-based identification ensuring that conflicts won't occur during document uploads or processing.