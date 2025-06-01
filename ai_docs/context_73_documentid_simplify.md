Okay, this is a precise and actionable plan. Here's a detailed markdown guide for an agentic coding tool to implement the single document UUID schema.

```markdown
# Guide: Enforcing Single Document UUID Schema

**Objective:** To refactor the existing system to use a single, canonical UUID for each document entity. This UUID will originate from the `source_documents` table (`document_uuid`) and will be used as the primary identifier (`documentId`) in the `neo4j_documents` table. This will eliminate redundancy and simplify document identity management.

**Agent Instructions:**
1.  Utilize your "Model Context Protocol Server Tool for Supabase" for all database schema interactions (DDL, DML for migration).
2.  Apply database schema changes (Phase 1) *before* Python script modifications (Phase 2).
3.  After all changes are implemented, perform the Conformance Check (Phase 3).

---

## Phase 1: Supabase Schema Changes & Data Migration

**Goal:** Modify the `neo4j_documents` table to use the `source_documents.document_uuid` as its primary `documentId`, and remove the redundant `source_document_uuid` column.

**IMPORTANT: Execute these SQL steps in the specified order.**

### Step 1.1: Data Migration - Populate `neo4j_documents.documentId`

**Context:** Before altering the `neo4j_documents` table structure, we must ensure its `documentId` column is correctly populated with the UUID from the corresponding `source_documents` record. We will use the existing `source_document_fk_id` to link the tables for this update.

**Action:** Execute the following SQL query using your Supabase tool. This query updates `neo4j_documents.documentId` to match `source_documents.document_uuid` for all existing records.

```sql
-- Update neo4j_documents.documentId to use the source_documents.document_uuid
-- This ensures that the graph document's primary identifier is the same as the original source document's UUID.
UPDATE public.neo4j_documents n
SET documentId = s.document_uuid,
    updatedAt = CURRENT_TIMESTAMP -- Also update the updatedAt timestamp
FROM public.source_documents s
WHERE n.source_document_fk_id = s.id
  AND n.documentId IS DISTINCT FROM s.document_uuid; -- Only update if different or documentId is NULL
```

**Verification (Optional but Recommended):**
After running the update, check if any `documentId` are still NULL or don't match (should be 0).

```sql
-- Check for NULL documentIds after migration
SELECT COUNT(*) AS null_documentid_count
FROM public.neo4j_documents
WHERE documentId IS NULL;

-- Check for mismatches (should be 0 after the update)
SELECT COUNT(*) AS mismatched_documentid_count
FROM public.neo4j_documents n
JOIN public.source_documents s ON n.source_document_fk_id = s.id
WHERE n.documentId != s.document_uuid;
```

### Step 1.2: Alter `neo4j_documents` Table - Ensure `documentId` is `NOT NULL`

**Context:** Now that `documentId` is populated, we need to ensure it cannot be null going forward.

**Action:** Execute the following SQL DDL statement.

```sql
-- Make documentId NOT NULL as it's now the primary identifier
ALTER TABLE public.neo4j_documents
ALTER COLUMN documentId SET NOT NULL;
```

*(Agent Note: If `documentId` is already part of a PRIMARY KEY constraint, it will inherently be `NOT NULL`. Your Supabase tool might inform you if this alteration is redundant. Proceed if no error, or skip if it's already enforced.)*

### Step 1.3: Alter `neo4j_documents` Table - Add `UNIQUE` Constraint to `documentId` (If not already Primary Key)

**Context:** The `documentId` must be unique across the `neo4j_documents` table. If it's not already the primary key (which enforces uniqueness), a unique constraint is needed. The schema indicates `id` is the primary key.

**Action:** Execute the following SQL DDL statement.

```sql
-- Add a UNIQUE constraint to documentId to ensure no duplicate document representations in the graph.
-- Check existing constraints first; Supabase might name it differently if it already exists.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM   pg_constraint
        WHERE  conname = 'neo4j_documents_documentId_key' -- Common naming convention for unique constraints
        AND    conrelid = 'public.neo4j_documents'::regclass
    ) THEN
        ALTER TABLE public.neo4j_documents
        ADD CONSTRAINT neo4j_documents_documentId_key UNIQUE (documentId);
    END IF;
END
$$;
```

### Step 1.4: Alter `neo4j_documents` Table - Drop Redundant `source_document_uuid` Column

**Context:** With `documentId` now correctly populated and constrained, the `source_document_uuid` column in `neo4j_documents` is redundant.

**Action:** Execute the following SQL DDL statement.

```sql
-- Drop the now-redundant source_document_uuid column
ALTER TABLE public.neo4j_documents
DROP COLUMN IF EXISTS source_document_uuid;
```

---

## Phase 2: Python Script Modifications

**Goal:** Update Python scripts to reflect the new single document UUID schema.

### Script: `supabase_utils.py`

**Function:** `create_neo4j_document_entry`

**Current Behavior:** This function generates a *new* UUID for `documentId` and also stores the passed `source_doc_uuid` in a separate `source_document_uuid` column.

**Required Change:**
1.  The `documentId` for the new `neo4j_documents` record *must be* the `source_doc_uuid` passed into the function.
2.  The `source_document_uuid` key-value pair should be removed from the `document` dictionary being inserted, as the column will no longer exist.

**Specific Change Instructions:**

Locate the `create_neo4j_document_entry` function.

**Change this part:**
```python
        # Before:
        # try:
        #     # Generate UUID that matches the CHECK constraint in schema
        #     doc_uuid = str(uuid.uuid4()) # This line generates a NEW UUID
            
        #     # Get storage path from source document
        #     source_response = self.client.table('source_documents').select('original_file_path').eq('id', source_doc_fk_id).execute()
        #     storage_path = source_response.data[0]['original_file_path'] if source_response.data else None
            
        #     document = {
        #         'documentId': doc_uuid,  # Uses the NEWLY generated doc_uuid
        #         'source_document_fk_id': source_doc_fk_id,
        #         'source_document_uuid': source_doc_uuid,  # Add link via UUID (This will be removed)
        #         'project_id': project_fk_id,
        #         # ... rest of the fields
        #     }
```

**To this:**
```python
        try:
            # Use the passed-in source_doc_uuid as the documentId for neo4j_documents
            doc_uuid = source_doc_uuid # Key change: doc_uuid IS the source_doc_uuid

            # Get storage path from source document
            source_response = self.client.table('source_documents').select('original_file_path').eq('id', source_doc_fk_id).execute()
            storage_path = source_response.data[0]['original_file_path'] if source_response.data else None

            document = {
                'documentId': doc_uuid,  # Now uses the source_doc_uuid
                'source_document_fk_id': source_doc_fk_id,
                # 'source_document_uuid': source_doc_uuid, # REMOVE THIS LINE - column no longer exists
                'project_id': project_fk_id,  # Match schema field name
                'project_uuid': project_uuid,  # Add link via UUID
                'name': file_name,
                'storagePath': storage_path,  # Match schema field name
                'processingStatus': 'pending_metadata',  # Match schema field name
                'createdAt': datetime.now().isoformat(),
                'updatedAt': datetime.now().isoformat()
            }
            # Ensure 'project_id', 'name', 'storagePath', etc., are correctly mapped to schema names if they differ from this example.
            # The provided schema dump shows these are correct.
```
**Ensure the function still returns `doc_id, doc_uuid` where `doc_uuid` is now the unified UUID.**

---

### Script: `main_pipeline.py`

**Function:** `process_single_document`

**Context:** This function orchestrates the document processing, including calls to `create_source_document_entry` and `create_neo4j_document_entry`.

**Required Change:** Primarily, ensure that the UUID returned by `create_source_document_entry` (which is `source_doc_uuid`) is correctly passed to `create_neo4j_document_entry` and that the UUID returned by `create_neo4j_document_entry` (which will now be the same unified UUID, referred to as `neo4j_doc_uuid` in the script) is used consistently thereafter.

**Verification (No Code Change Expected, but verify logic):**

1.  Locate the call to `db_manager.create_source_document_entry`. It returns `src_doc_sql_id, src_doc_uuid`.
    ```python
    # source_doc_uuid = source_doc_info.get('document_uuid') # This is good
    # ...
    # neo4j_doc_sql_id, neo4j_doc_uuid = db_manager.create_neo4j_document_entry(
    #     source_doc_fk_id=source_doc_sql_id,
    #     source_doc_uuid=source_doc_uuid, # This `source_doc_uuid` is from source_documents
    #     project_fk_id=project_sql_id,
    #     project_uuid=_project_uuid,
    #     file_name=file_name
    # )
    ```
    The variable `source_doc_uuid` (from `source_doc_info` or `create_source_document_entry`) is correctly passed as the `source_doc_uuid` argument to `create_neo4j_document_entry`.

2.  The `neo4j_doc_uuid` returned by `create_neo4j_document_entry` will now *be* the `source_doc_uuid`.
    Ensure that this `neo4j_doc_uuid` is used for all subsequent operations that require the graph document's UUID (e.g., creating chunks, canonical entities, relationships).

    For example, when creating chunks:
    ```python
    # chunk_sql_id, chunk_neo4j_uuid = db_manager.create_chunk_entry(
    #     document_fk_id=neo4j_doc_sql_id,
    #     document_uuid=neo4j_doc_uuid, # This neo4j_doc_uuid is now the unified UUID
    #     # ...
    # )
    ```
    And when creating canonical entities:
    ```python
    # ce_sql_id, ce_neo4j_uuid = db_manager.create_canonical_entity_entry(
    #     neo4j_doc_sql_id=neo4j_doc_sql_id,
    #     document_uuid=neo4j_doc_uuid, # This neo4j_doc_uuid is now the unified UUID
    #     # ...
    # )
    ```
    This appears to be logically sound based on the provided `main_pipeline.py` structure. The key is that `create_neo4j_document_entry` now correctly sets `documentId` to the passed `source_doc_uuid`.

**No specific line changes are mandated for `main_pipeline.py` itself if the above logic holds, but the agent should verify this flow.**

---

### Script: `relationship_builder.py`

**Function:** `stage_structural_relationships`

**Context:** This script creates relationships. The `document_data` argument contains `documentId`, which should be the unified UUID.

**Verification (No Code Change Expected, but verify logic):**
The argument `document_data: dict` is expected to have a key `documentId`.
```python
    # document_uuid_val = document_data.get('documentId') # This is the neo4j_document_uuid
```
After the changes, `document_data.get('documentId')` (which is populated from `neo4j_documents.documentId`) will correctly be the unified document UUID. This means relationships involving the "Document" node will use the correct, unified UUID.

**No specific line changes are mandated for `relationship_builder.py` itself, assuming it correctly uses the `documentId` from its input.**

---

### Scripts: `queue_processor.py`, `textract_utils.py`, `ocr_extraction.py`

**Context:** These scripts might interact with `source_documents` or `neo4j_documents` and their UUIDs.

**Verification (No Code Change Expected for this specific refactor, but verify consistency):**
*   `queue_processor.py`: Uses `source_document_uuid` from the `document_processing_queue` table, which refers to `source_documents.document_uuid`. This is correct and unaffected. When it calls `process_single_document`, the unified UUID logic within that function will apply.
*   `textract_utils.py` / `ocr_extraction.py (extract_text_from_pdf_textract)`: These functions seem to work primarily with `source_documents.document_uuid` (passed as `document_uuid_from_db`). This `document_uuid_from_db` *is* the unified UUID. When they update `source_documents`, they use this correct UUID.

**No specific line changes are mandated for these scripts for *this particular* UUID unification, as they already seem to operate with the `source_documents.document_uuid` as the primary external identifier for a document.**

---

## Phase 3: Conformance Check & Testing

**Goal:** Verify that the changes have been implemented correctly and the system functions as expected with the unified document UUID.

**Action:** After applying all schema and code changes, perform the following checks:

### 3.1 Database Conformance Check

Execute the following SQL query using your Supabase tool. This query verifies that for every `neo4j_documents` record, its `documentId` matches the `document_uuid` of its parent `source_documents` record. The count should be 0.

```sql
SELECT
    COUNT(*) AS non_conforming_documents
FROM
    public.neo4j_documents n_doc
JOIN
    public.source_documents s_doc ON n_doc.source_document_fk_id = s_doc.id
WHERE
    n_doc.documentId IS DISTINCT FROM s_doc.document_uuid;
```
**Expected Result:** `non_conforming_documents` should be `0`.

### 3.2 Pipeline Test Run

1.  **Identify 2-3 diverse test documents** (e.g., a short PDF, a longer PDF, a .docx file).
2.  **Process these documents** through the entire pipeline using the `direct` mode of `main_pipeline.py`.
    ```bash
    python main_pipeline.py --mode direct --log-level DEBUG
    ```
3.  **Monitor Logs:** Check for any UUID-related errors or warnings during processing, particularly around the creation of `neo4j_documents` and subsequent linking of chunks, entities, and relationships.
4.  **Verify Database Entries:**
    *   For each test document, check the `source_documents` table and note its `document_uuid`.
    *   Check the corresponding `neo4j_documents` table entry (linked by `source_document_fk_id`). Verify its `documentId` matches the `document_uuid` from `source_documents`.
    *   Verify that the `neo4j_chunks.document_uuid` for chunks of this document matches this unified UUID.
    *   Verify that `neo4j_canonical_entities.document_uuid` for canonical entities of this document matches this unified UUID.
    *   Verify relationships in `neo4j_relationships_staging` involving the document node use this unified UUID.

### 3.3 (Optional) Graph Database Check

If you have a process to load this data into Neo4j:
1.  Load the processed test documents into Neo4j.
2.  Query Neo4j to ensure `Document` nodes have the correct UUID (the unified one).
3.  Verify that relationships like `(Chunk)-[:BELONGS_TO]->(Document)` are correctly formed using these UUIDs.

---

**Conclusion:**
Upon successful completion of these phases and conformance checks, the system will have a more streamlined and robust document identity schema, reducing potential inconsistencies and simplifying data management.

```