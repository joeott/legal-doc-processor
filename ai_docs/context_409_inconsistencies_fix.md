Okay, let's conduct a deep audit of UUID handling across your Python scripts. The goal is to ensure consistency in definition, propagation, and usage of UUIDs to prevent mismatches and errors.

## UUID Handling Audit and Fixes

This report details inconsistencies in UUID handling across the provided Python scripts, outlines the conflicts they cause with Pydantic model definitions or database expectations, and suggests fixes.

**General Principle:**

*   **Pydantic Models:** UUID fields should be typed as `uuid.UUID`. Pydantic will automatically attempt to parse string representations into `uuid.UUID` objects upon model instantiation.
*   **Database Interaction (SQLAlchemy):** When passing UUIDs to SQLAlchemy for database columns of type `UUID`, `uuid.UUID` objects are preferred. SQLAlchemy and `psycopg2` (the PostgreSQL driver) can often handle string representations, but using `uuid.UUID` objects is safer and more explicit.
*   **Celery Task Arguments:** Celery serializes task arguments (often to JSON). `uuid.UUID` objects will be converted to strings during this serialization. Therefore, tasks receiving UUIDs as arguments will typically get them as strings.
*   **Cache Keys:** UUIDs used in cache keys should consistently be strings.
*   **Internal Function Calls:** Within Python code, passing `uuid.UUID` objects is generally preferred for type safety, unless a string is specifically required (e.g., for an external API that expects a string).

---

### 1. `document_uuid`

This is the most critical UUID, identifying a unique document throughout the system.

*   **Source of Truth:**
    *   `models.SourceDocumentMinimal.document_uuid: UUID`
    *   `core.schemas.SourceDocumentModel.document_uuid: uuid.UUID`
    *   `core.pdf_models.PDFDocumentModel.document_uuid: uuid.UUID`
    *   Database column `source_documents.document_uuid` is expected to be of type `UUID`.

*   **Inconsistencies & Fixes:**

    1.  **Generation in `batch_processor.create_document_record`**
        *   **File:** `batch_processor.py`
        *   **Error:** `document_uuid = str(uuid.uuid4())` generates a string. While the DB might handle it, subsequent operations and model instantiations might expect a `uuid.UUID` object. The function returns this string.
        *   **Conflict:** Pydantic models expect `uuid.UUID`. Returning a string can lead to type mismatches if not handled carefully downstream.
        *   **Fix:**
            ```python
            # In batch_processor.py, create_document_record
            # document_uuid_obj = uuid.uuid4() # Generate UUID object
            # document_uuid_str = str(document_uuid_obj) # Convert to string for DB insertion if needed,
            #                                         # or let SQLAlchemy handle the UUID object.
            # ...
            # session.execute(text("""INSERT INTO source_documents (... document_uuid ...)
            #                       VALUES (... :uuid ...)"""),
            #                 {'uuid': document_uuid_obj, ...}) # Pass UUID object
            # ...
            # return document_uuid_obj # Return the UUID object
            ```
            *Alternatively, if the DB insert query strictly needs a string (less ideal):*
            ```python
            # In batch_processor.py, create_document_record
            document_uuid_obj = uuid.uuid4()
            document_uuid_str = str(document_uuid_obj)
            # ... insert document_uuid_str into DB ...
            # return document_uuid_obj # Still return the object for internal use
            ```
            **Update:** The current `create_document_record` uses `session.execute` with `VALUES (:uuid, ...)`, and `{'uuid': document_uuid_str}`. SQLAlchemy with psycopg2 will handle the string-to-UUID conversion for a `UUID` database column. The main concern is what `submit_batch_for_processing` *does* with the returned `document_uuid`. It should ideally receive a `uuid.UUID` object if that's what downstream Python logic expects for model instantiation, or ensure conversion.
            **Revised Fix for `create_document_record`:**
            Return the `uuid.UUID` object. Let the caller decide if string conversion is needed.
            ```python
            # In batch_processor.py, create_document_record
            document_uuid_obj = uuid.uuid4()
            # ...
            # session.execute(..., {'uuid': document_uuid_obj, ...})
            # ...
            # return document_uuid_obj
            ```

    2.  **Propagation to Celery Tasks from `batch_processor.submit_batch_for_processing`**
        *   **File:** `batch_processor.py`
        *   **Error:** If `create_document_record` returns a `uuid.UUID` object (as per revised fix above), then `doc['document_uuid'] = document_uuid` stores the object. When `app.signature('...', args=[document_uuid, s3_url], ...)` is called, Celery will serialize this `uuid.UUID` object to a string for the task payload. This is correct behavior for Celery.
        *   **Conflict:** None if Celery tasks expect strings.
        *   **Fix (Verification):** Ensure Celery tasks are designed to receive `document_uuid` as a string. This is the current design in `pdf_tasks.py`.

    3.  **Usage in Celery Tasks (`pdf_tasks.py`)**
        *   **File:** `pdf_tasks.py`
        *   **Current State:** All tasks like `extract_text_from_document` correctly define `document_uuid: str` in their signature, reflecting Celery's serialization.
        *   **Potential Issue:** When instantiating Pydantic models (e.g., `ChunkModel`, `EntityMentionModel`) inside these tasks, the string `document_uuid` is sometimes passed directly.
            *   Example: `chunk_document_text` -> `chunk_model = ChunkModel(document_uuid=document_uuid, ...)`
        *   **Conflict:** Models like `ChunkModel` expect `document_uuid: uuid.UUID`. Pydantic usually handles string-to-UUID conversion automatically during validation if the string is a valid UUID format.
        *   **Fix (Best Practice):** While Pydantic often handles this, explicitly convert to `uuid.UUID` for clarity and to ensure type safety if Pydantic's auto-conversion behavior changes or has edge cases.
            ```python
            # Inside pdf_tasks.py, e.g., in chunk_document_text
            from uuid import UUID as UUID_TYPE # To avoid conflict with local var 'uuid'
            # ...
            doc_uuid_obj = UUID_TYPE(document_uuid) # document_uuid is the string arg
            # ...
            chunk_model = ChunkModel(
                # ...
                document_uuid=doc_uuid_obj, # Pass the UUID object
                # ...
            )
            # ...
            # When calling other functions/services that expect UUID objects:
            # self.entity_service.some_method(document_uuid=doc_uuid_obj, ...)
            ```

    4.  **Database Interaction in `pdf_tasks.py` (e.g., `poll_textract_job`)**
        *   **File:** `pdf_tasks.py`
        *   **Current State:** `session.execute(query, {'doc_uuid': str(document_uuid)})` converts to string before SQL. This is acceptable for SQL queries where the DB column is UUID type.
        *   **Conflict:** None directly, but consistency is key.
        *   **Fix:** No immediate fix needed here if the DB handles string-to-UUID for queries correctly. Maintain this pattern or switch to passing `uuid.UUID` objects if other parts of the DB layer start strictly requiring them.

    5.  **`textract_utils.py` and `document_uuid`**
        *   **File:** `textract_utils.py`
        *   **`TextractProcessor.start_document_text_detection_v2`** takes `document_uuid_from_db: str`.
        *   It then calls `self.db_manager.create_textract_job_entry(..., document_uuid=document_uuid_from_db, ...)`.
        *   **Error:** `db.DatabaseManager.create_textract_job_entry` is defined to take `document_uuid: uuid.UUID`. Passing a string here relies on implicit conversion or a loosened type hint in the actual implementation that differs from the Pydantic model (`TextractJobModel`).
        *   **Conflict:** Potential type mismatch if `create_textract_job_entry` internally instantiates `TextractJobModel` (which expects `uuid.UUID`) directly from this string without Pydantic's help, or if the DB utility doesn't handle the string for a UUID column correctly.
        *   **Fix for `start_document_text_detection_v2`:**
            ```python
            # In textract_utils.py, TextractProcessor.start_document_text_detection_v2
            from uuid import UUID as UUID_TYPE
            # ...
            doc_uuid_obj = UUID_TYPE(document_uuid_from_db)
            self.db_manager.create_textract_job_entry(
                # ...
                document_uuid=doc_uuid_obj, # Pass UUID object
                # ...
            )
            ```
        *   **`TextractProcessor.extract_text_with_fallback`** takes `document_uuid: str`.
            *   Calls `self.db_manager.get_source_document(document_uuid)`. This should be fine if `get_source_document` in `db.py` correctly handles string UUIDs for its query.
            *   Then calls `self.start_document_text_detection_v2(..., document_uuid_from_db=document_uuid)` (passing string). This needs the fix mentioned above.

---

### 2. `project_uuid`

*   **Source of Truth:**
    *   `models.SourceDocumentMinimal.project_uuid: UUID`
    *   `core.schemas.ProjectModel.project_id: Optional[uuid.UUID]` (aliased `projectId`) - Note the name difference (`project_id` vs `project_uuid`).
    *   `core.schemas.SourceDocumentModel.project_uuid: Optional[uuid.UUID]`
    *   Database table `projects` has `project_uuid` (type UUID) and `id` (int, PK).
    *   Database table `source_documents` has `project_uuid` (type UUID, FK to `projects.project_uuid`) and `project_fk_id` (int, FK to `projects.id`).

*   **Inconsistencies & Fixes:**

    1.  **Dual Referencing in `source_documents`:**
        *   The table `source_documents` has both `project_fk_id` (int) and `project_uuid` (UUID). This is acceptable but requires careful, consistent updates.
        *   `production_processor.py`: `ensure_project_exists` correctly returns `project_uuid` (as a string).
        *   `batch_processor.py`: `create_document_record` takes `project_id: int` and `project_uuid: str` (or `None`). It correctly inserts these into `project_fk_id` and `project_uuid` columns respectively.
        *   **Conflict:** Potential for these to go out of sync if one is updated and the other is not.
        *   **Fix (Recommendation):** Ensure that whenever a document's project association changes, *both* `project_fk_id` and `project_uuid` are updated in `source_documents`. Or, consider making `project_uuid` in `source_documents` the single source of truth and deriving/joining for the integer ID if needed elsewhere. For now, the dual FKs seem handled in `batch_processor`.

    2.  **`project_id` vs. `project_uuid` in `core.schemas.ProjectModel`:**
        *   `ProjectModel.project_id: Optional[uuid.UUID]` is an alias for the database's `project_uuid` column.
        *   **Conflict:** This can be confusing. Code using `ProjectModel` might use `project_id` expecting an integer PK but get a UUID.
        *   **Fix:** Rename the Pydantic field to `project_uuid` to match the DB column and avoid ambiguity:
            ```python
            # In core/schemas.py
            class ProjectModel(BaseTimestampModel):
                project_uuid: Optional[uuid.UUID] = Field(None, alias="projectId") # Keep alias for DB mapping if 'projectId' is actual col name
                # ... or if DB col is project_uuid:
                # project_uuid: Optional[uuid.UUID] = Field(None, alias="project_uuid")
            ```
            **Update:** `check_schema.py` shows `projects` table has `project_uuid` and `project_name`. `id` is the integer PK. So `ProjectModel` should have `project_uuid: uuid.UUID` and also potentially `id: Optional[int]`. The alias `projectId` might be for `project_uuid` if the database column was historically named `projectId`.
            **Revised Fix (assuming DB col is `project_uuid`):**
            ```python
            # In core/schemas.py
            class ProjectModel(BaseTimestampModel):
                id: Optional[int] = Field(None, description="Database primary key") # Add if it's part of the model
                project_uuid: Optional[uuid.UUID] = Field(None, alias="project_uuid") # If DB col name is 'project_uuid'
                name: str = Field(..., description="Project name", alias="project_name") # If DB col name is 'project_name'
                # ... other fields
            ```
            If the DB column for the UUID is actually `projectId`, then the alias is correct, but the field name `project_id` in Pydantic is misleading for a UUID. Prefer `project_uuid: Optional[uuid.UUID] = Field(None, alias="projectId")`.

---

### 3. `chunk_uuid` and `chunk_id`

*   **Source of Truth:**
    *   `models.DocumentChunkMinimal.chunk_uuid: UUID`
    *   `core.schemas.ChunkModel.chunk_id: uuid.UUID` (aliased `chunkId`) - Name mismatch!
    *   `core.pdf_models.PDFChunkModel.chunk_id: uuid.UUID`
    *   Database column `document_chunks.chunk_uuid` (type UUID). `id` is the int PK.

*   **Inconsistencies & Fixes:**

    1.  **Field Name Mismatch (`chunk_uuid` vs. `chunk_id`):**
        *   `models.py` uses `chunk_uuid`. `core/schemas.py` and `core/pdf_models.py` use `chunk_id` (for the UUID).
        *   **Conflict:** Code using different model definitions will refer to the same logical UUID by different names.
        *   **Fix (Recommendation):** Standardize on `chunk_uuid` across all Pydantic models to match the likely database column name (as per `models.py` and `check_schema.py` output).
            ```python
            # In core/schemas.py ChunkModel
            # chunk_id: uuid.UUID = Field(..., alias="chunkId")
            # ----> change to:
            chunk_uuid: uuid.UUID = Field(..., alias="chunk_uuid") # Assuming DB col is chunk_uuid

            # In core/pdf_models.py PDFChunkModel
            # chunk_id: uuid.UUID = Field(default_factory=uuid.uuid4)
            # ----> change to:
            chunk_uuid: uuid.UUID = Field(default_factory=uuid.uuid4)
            ```
            If the database column is indeed `chunk_id` of type UUID, then models should use `chunk_id: uuid.UUID` and `models.py` should be updated. The `check_schema.py` output for `document_chunks` shows `chunk_uuid`, so `chunk_uuid` is likely correct.

    2.  **Generation and Usage in `pdf_tasks.chunk_document_text`:**
        *   **File:** `pdf_tasks.py`
        *   `chunk_model = ChunkModel(chunk_uuid=uuid.uuid4(), ...)`: Correctly generates a `uuid.UUID` object.
        *   `db_data = { 'chunk_uuid': str(chunk_model.chunk_uuid), ... }`: Converts to string for `insert_record`. This is acceptable if `insert_record` expects strings or if the DB handles it.
        *   Return value `serialized_chunks`: Contains `chunk_uuid` as a string because `chunk.model_dump(mode='json')` serializes UUIDs to strings.
        *   This string `chunk_uuid` is then passed to `extract_entities_from_chunks`.
        *   **Conflict:** None if subsequent tasks expect string UUIDs for `chunk_uuid`.
        *   **Fix (Verification):** Ensure `extract_entities_from_chunks` and `entity_service` handle string `chunk_uuid` correctly when instantiating `EntityMentionModel` (which expects `chunk_uuid: UUID`).

    3.  **Usage in `pdf_tasks.extract_entities_from_chunks`:**
        *   **File:** `pdf_tasks.py`
        *   `chunk_uuid = chunk['chunk_uuid']`: Receives string `chunk_uuid`.
        *   `self.entity_service.extract_entities_from_chunk(..., chunk_uuid=chunk_uuid, ...)`: Passes string `chunk_uuid`.

    4.  **Usage in `entity_service._perform_entity_extraction`:**
        *   **File:** `entity_service.py`
        *   Takes `chunk_uuid: Union[uuid.UUID, str]`.
        *   `chunk_uuid_obj = uuid.UUID(chunk_uuid) if isinstance(chunk_uuid, str) else chunk_uuid`: **GOOD PRACTICE**. Converts to `uuid.UUID` object.
        *   `EntityMentionModel(..., chunk_uuid=chunk_uuid_obj, ...)`: Correctly passes `uuid.UUID` object.

---

### 4. `entity_mention_uuid` / `mention_uuid`

*   **Source of Truth:**
    *   `models.EntityMentionMinimal.mention_uuid: UUID`
    *   `core.schemas.EntityMentionModel.entity_mention_id: uuid.UUID` (aliased `entityMentionId`) - Name mismatch!
    *   Database column `entity_mentions.mention_uuid` (type UUID). `id` is int PK.

*   **Inconsistencies & Fixes:**

    1.  **Field Name Mismatch (`mention_uuid` vs. `entity_mention_id`):**
        *   **Conflict:** Similar to `chunk_uuid` vs. `chunk_id`.
        *   **Fix (Recommendation):** Standardize on `mention_uuid` across all Pydantic models.
            ```python
            # In core/schemas.py EntityMentionModel
            # entity_mention_id: uuid.UUID = Field(..., alias="entityMentionId")
            # ----> change to:
            mention_uuid: uuid.UUID = Field(..., alias="mention_uuid") # Assuming DB col is mention_uuid
            ```
            `check_schema.py` output for `entity_mentions` confirms column is `mention_uuid`.

    2.  **Generation in `entity_service._perform_entity_extraction`:**
        *   `entity_data_minimal = { 'mention_uuid': uuid.uuid4(), ... }`: Correctly generates `uuid.UUID` object.
        *   `entity_mention = EntityMentionModel(**entity_data_minimal)`: Instantiates model with `uuid.UUID` object.

    3.  **Usage in `pdf_tasks.resolve_document_entities` -> `_resolve_entities_simple`:**
        *   `entity_mentions` list contains dicts. `mention_uuid` is likely a string if it came from `extract_entities_from_chunks` -> `model_dump()`.
        *   `uuid1 = mention1['mention_uuid']`: `uuid1` is a string.
        *   `mention_uuids = [uuid.UUID(str(u)) ... for u in mention_uuids]`: **GOOD PRACTICE**. Converts these strings back to `uuid.UUID` objects for `create_canonical_entity_for_minimal_model`.

---

### 5. `canonical_entity_uuid` / `canonical_entity_id` / `resolved_canonical_id`

*   **Source of Truth:**
    *   `models.EntityMentionMinimal.canonical_entity_uuid: Optional[UUID]`
    *   `models.CanonicalEntityMinimal.canonical_entity_uuid: UUID`
    *   `core.schemas.EntityMentionModel.resolved_canonical_id: Optional[uuid.UUID]` (aliased `resolvedCanonicalId`) - Name mismatch!
    *   `core.schemas.CanonicalEntityModel.canonical_entity_id: uuid.UUID` (aliased `canonicalEntityId`) - Name mismatch!
    *   Database table `canonical_entities` has `entity_uuid` (type UUID, as per `check_schema.py`). `id` is int PK.
    *   Database table `entity_mentions` has `canonical_entity_uuid` (type UUID, FK to `canonical_entities.entity_uuid`).

*   **Inconsistencies & Fixes:**

    1.  **Massive Field Name Mismatch:**
        *   `models.py` uses `canonical_entity_uuid`.
        *   `core/schemas.py EntityMentionModel` uses `resolved_canonical_id`.
        *   `core/schemas.py CanonicalEntityModel` uses `canonical_entity_id`.
        *   Database `canonical_entities` table's UUID PK is named `entity_uuid` (from `check_schema.py`).
        *   Database `entity_mentions` FK is `canonical_entity_uuid`.
        *   **This is highly problematic and needs urgent standardization.**
        *   **Conflict:** Extreme confusion, high risk of errors in queries and model usage.
        *   **Fix (Urgent Recommendation):**
            1.  **Standardize Database `canonical_entities` Primary Key:** The `check_schema.py` output says the PK is `entity_uuid`. This should ideally be `canonical_entity_uuid` for clarity. If changing the DB is too hard now, models must adapt.
            2.  **Standardize Pydantic Field Name:** Choose one name (e.g., `canonical_entity_uuid`) and use it EVERYWHERE.
                *   Update `models.py`, `core/schemas.py`, `core/pdf_models.py` accordingly.
                *   If DB `canonical_entities.entity_uuid` cannot be changed, then `CanonicalEntityModel` should be:
                    ```python
                    # In core/schemas.py or models.py
                    class CanonicalEntityModel(...): # or CanonicalEntityMinimal
                        canonical_entity_uuid: uuid.UUID = Field(..., alias="entity_uuid") # Alias to match DB
                        # ...
                    ```
                *   And `EntityMentionModel` should consistently use `canonical_entity_uuid` for its FK field.
                    ```python
                    # In core/schemas.py or models.py
                    class EntityMentionModel(...): # or EntityMentionMinimal
                        # ...
                        canonical_entity_uuid: Optional[uuid.UUID] = Field(None, alias="canonical_entity_uuid")
                    ```
            **Based on `check_schema.py`:**
            *   `canonical_entities.entity_uuid` IS THE PK.
            *   `entity_mentions.canonical_entity_uuid` IS THE FK.
            *   **Fix:**
                *   `CanonicalEntityMinimal` and `CanonicalEntityModel` should have:
                    `entity_uuid: UUID` (as the primary identifier field).
                    And potentially `canonical_name: str`.
                *   `EntityMentionMinimal` and `EntityMentionModel` should have:
                    `canonical_entity_uuid: Optional[UUID]` (this is the FK, and it correctly refers to `canonical_entities.entity_uuid`).
                This means `models.py` `CanonicalEntityMinimal.canonical_entity_uuid` should be `entity_uuid`.
                And `core.schemas.py` `CanonicalEntityModel.canonical_entity_id` should be `entity_uuid`.
                `core.schemas.py` `EntityMentionModel.resolved_canonical_id` should be `canonical_entity_uuid`.

    2.  **Generation in `pdf_tasks.resolve_document_entities` -> `_resolve_entities_simple`:**
        *   `create_canonical_entity_for_minimal_model`: Generates `canonical_entity_uuid: uuid.uuid4()`.
        *   **Conflict:** If the DB PK for `canonical_entities` is `entity_uuid`, then the model `CanonicalEntityMinimal` should have an `entity_uuid` field, and this generated UUID should be assigned to `entity_uuid`.
        *   **Fix:** Adjust `create_canonical_entity_for_minimal_model` and `CanonicalEntityMinimal` to use `entity_uuid` as the primary UUID field, matching the database schema (`canonical_entities.entity_uuid`).
            ```python
            # In pdf_tasks.py, _resolve_entities_simple (inside resolve_document_entities)
            def create_canonical_entity_for_minimal_model(...):
                return {
                    'entity_uuid': uuid.uuid4(), # Match DB PK
                    'canonical_name': entity_name,
                    # ...
                }
            ```
            And ensure `CanonicalEntityMinimal` in `models.py` reflects this:
            ```python
            # In models.py
            class CanonicalEntityMinimal(BaseModel):
                entity_uuid: UUID # Changed from canonical_entity_uuid
                # ...
            ```

    3.  **Usage in `graph_service.py`:**
        *   `_create_relationship_wrapper` takes `from_id: str`, `to_id: str`. These are expected to be canonical entity UUIDs (as strings).
        *   It creates `RelationshipStagingMinimal(source_entity_uuid=from_id_str, target_entity_uuid=to_id_str, ...)`.
        *   `RelationshipStagingMinimal` in `models.py` expects `source_entity_uuid: UUID`, `target_entity_uuid: UUID`.
        *   **Conflict:** String UUIDs are passed to a model expecting `uuid.UUID` objects.
        *   **Fix:**
            ```python
            # In graph_service.py, _create_relationship_wrapper
            from uuid import UUID as UUID_TYPE
            # ...
            source_uuid_obj = UUID_TYPE(from_id_str)
            target_uuid_obj = UUID_TYPE(to_id_str)
            relationship = RelationshipStagingMinimal(
                source_entity_uuid=source_uuid_obj,
                target_entity_uuid=target_uuid_obj,
                # ...
            )
            ```

---

### 6. `relationship_uuid`

*   **Source of Truth:**
    *   `models.RelationshipStagingMinimal.relationship_uuid: UUID`
    *   Database `relationship_staging.relationship_uuid` (from `check_schema.py`)
*   **Inconsistencies & Fixes:**
    *   This seems to be generated internally and consistently as `uuid.UUID` within `RelationshipStagingMinimal` if not provided, or when models are created.
    *   Ensure it's handled as `uuid.UUID` internally and converted to string only for DB storage if the column is `VARCHAR` (though `check_schema.py` output suggests it's `uuid`). `check_schema.py` output for `relationship_staging` indicates `relationship_uuid` is `uuid` type. This seems fine.

---

### General Recommendations for UUID Handling:

1.  **Standardize Field Names:** Pick one name for each logical UUID (e.g., `document_uuid`, `chunk_uuid`, `canonical_entity_uuid` for the canonical entity's main ID) and use it consistently across all Pydantic models and code. Update database column names if feasible, otherwise use Pydantic `alias` for mapping. The `check_schema.py` output is crucial here for DB column names.
    *   **`canonical_entities` PK is `entity_uuid`**. Models for this table must use `entity_uuid` as the primary UUID field.
    *   The FK in `entity_mentions` pointing to it is `canonical_entity_uuid`. This is confusing. It should ideally be `canonical_entity_db_id` or similar if it refers to the `canonical_entities.entity_uuid`. Or, rename the FK to `fk_canonical_entity_uuid` and ensure it stores the value from `canonical_entities.entity_uuid`. The current setup of `entity_mentions.canonical_entity_uuid` storing the value from `canonical_entities.entity_uuid` is technically fine but the naming is not ideal.

2.  **Type Conversion Discipline:**
    *   **Celery Task Input:** Tasks will receive UUIDs as strings. Convert them to `uuid.UUID` objects immediately at the beginning of the task if they will be used to instantiate Pydantic models or passed to functions expecting `uuid.UUID` objects.
        ```python
        from uuid import UUID as UUID_TYPE # Avoid name collision
        def my_celery_task(self, document_uuid_str: str, ...):
            document_uuid_obj = UUID_TYPE(document_uuid_str)
            # use document_uuid_obj henceforth
        ```
    *   **Pydantic Model Instantiation:** When creating Pydantic models, ensure you pass `uuid.UUID` objects for fields typed as `uuid.UUID`. While Pydantic can auto-convert valid strings, being explicit is safer.
    *   **Database Operations:** When using SQLAlchemy with models, passing `uuid.UUID` objects is generally fine. If constructing raw SQL or using lower-level DB utilities, ensure UUIDs are correctly formatted as strings if needed, or pass `uuid.UUID` objects and let the driver handle it. `str(my_uuid_obj)` is the standard way to get the string form.

3.  **Pydantic Aliases:** Use Pydantic's `Field(alias="db_column_name")` if model field names need to differ from database column names for clarity or historical reasons. This allows your Python code to use consistent names while mapping correctly to the DB.

4.  **Review `db.py` and `rds_utils.py`:**
    *   Ensure that methods like `insert_record`, `update_record`, and `select_records` handle `uuid.UUID` objects correctly when they are part of the `data` or `where` dictionaries. If the DB column is `UUID` type, psycopg2 (Python's PostgreSQL driver) can usually handle `uuid.UUID` objects directly. If these utilities always convert UUIDs to strings before forming SQL, that's also a consistent approach. The key is that the final value passed to the DB query execution for a `UUID` column is either a `uuid.UUID` object or a string that PostgreSQL can cast to UUID.

5.  **Model Coherence:**
    *   There are multiple sets of Pydantic models (`models.py`, `core/schemas.py`, `core/pdf_models.py`). Strive to consolidate these or have a very clear distinction for their usage. `models.py` with "Minimal" in class names seems to be an attempt to bypass conformance issues. The target should be a single, consistent set of models that accurately reflects the database schema.
    *   Use the output of `check_schema.py` as the definitive source for database column names and types when aligning Pydantic models.

By systematically applying these changes, especially standardizing names and ensuring type conversions at boundaries (Celery tasks, DB interactions), the UUID mismatch issues should be resolved. The `canonical_entity_uuid` naming is the most tangled and needs the most careful attention.