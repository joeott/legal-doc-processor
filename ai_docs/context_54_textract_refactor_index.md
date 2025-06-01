Okay, here's an index and task list designed to guide an agentic coding tool through the refactoring plan. It breaks down the changes into manageable chunks, referencing the line numbers in your provided `context_53_textract_plan.md` document where the descriptions of these changes occur.

**Agentic Coding Tool - Task Index for Textract Refactor**

**Overall Goal:** Refactor the codebase to replace Mistral OCR with AWS Textract, update S3 handling, and adjust database interactions as per `context_53_textract_plan.md`.

**General Instructions for Agent:**
*   Implement changes sequentially as listed below.
*   Refer to the specified file and line numbers in `context_53_textract_plan.md` for detailed instructions and code snippets.
*   Assume all DDL changes to Supabase tables (`textract_jobs`, `source_documents`, `document_processing_queue`) have been applied.
*   After each file modification, perform basic syntax checks.

---

**Phase 1: Configuration (`config.py`)**
*File to Modify: `config.py`*

1.  **Task 1.1: Remove Mistral OCR Configuration**
    *   **Description:** Delete all environment variables and Python constants related to Mistral OCR.
    *   **Reference:** `context_53_textract_plan.md`, Section 1.1, Lines 7-14.
    *   **Details:**
        *   Remove `MISTRAL_API_KEY`, `USE_MISTRAL_FOR_OCR`, `MISTRAL_OCR_MODEL`, `MISTRAL_OCR_PROMPT`, `MISTRAL_OCR_TIMEOUT`.
        *   Remove related validation checks (e.g., in `StageConfig` or `validate_cloud_services`). See example modification for `StageConfig` around lines 26-31 and `validate_cloud_services` around lines 196-200 in the plan's own Python snippets for `config.py`.

2.  **Task 1.2: Simplify S3 Bucket Configuration**
    *   **Description:** Modify S3 configuration to use a single private bucket (`S3_PRIMARY_DOCUMENT_BUCKET`).
    *   **Reference:** `context_53_textract_plan.md`, Section 1.2, Lines 15-20 (description), Lines 22-31 (code snippet).
    *   **Details:**
        *   Remove `S3_BUCKET_PUBLIC`, `S3_BUCKET_TEMP`.
        *   Ensure `S3_BUCKET_NAME` (if it existed as a distinct variable) is replaced by or consolidated into `S3_PRIMARY_DOCUMENT_BUCKET`.
        *   Verify `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION` are present.

3.  **Task 1.3: Add/Update AWS Textract Configuration**
    *   **Description:** Add new configuration variables for AWS Textract.
    *   **Reference:** `context_53_textract_plan.md`, Section 1.3, Lines 32-34 (description), Lines 38-48 (code snippet).
    *   **Details:** Implement the Python code block provided for Textract configuration variables.

4.  **Task 1.4: Update Validation Logic**
    *   **Description:** Remove Mistral-specific checks and add checks for AWS credentials in `validate_cloud_services()`.
    *   **Reference:** `context_53_textract_plan.md`, Section 1.4, Lines 49-51 (description), Lines 53-65 (code snippet).
    *   **Details:** Modify the `validate_cloud_services()` function as shown.

---

**Phase 2: S3 Utilities (`s3_storage.py`)**
*File to Modify: `s3_storage.py`*

1.  **Task 2.1: Remove Public/Temp Bucket Functions**
    *   **Description:** Delete functions related to now-removed public/temp S3 buckets.
    *   **Reference:** `context_53_textract_plan.md`, Section 2.1, Lines 69-70.
    *   **Details:** Delete `copy_to_public_bucket()`, `generate_presigned_url_for_ocr()`, `cleanup_ocr_file()`.

2.  **Task 2.2: Modify `upload_document_with_uuid_naming()`**
    *   **Description:** Update S3 key generation to use `documents/{document_uuid}{file_ext}` pattern.
    *   **Reference:** `context_53_textract_plan.md`, Section 2.2, Lines 71-76 (description), Lines 77-129 (code snippet for `S3StorageManager` class).
    *   **Details:**
        *   Implement the `upload_document_with_uuid_naming` method as shown, focusing on the new `s3_key` pattern (line 87) and metadata handling.
        *   Ensure `_get_content_type`, `get_s3_document_location`, `check_s3_object_exists`, `handle_s3_errors` are present and correct as per the snippet.
        *   Verify imports (`boto3`, `logging`, `os`, `hashlib`, `Dict`, `Optional`, `datetime`, `config` variables, `botocore.exceptions`).

---

**Phase 3: Supabase Utilities (`supabase_utils.py`)**
*File to Modify: `supabase_utils.py`*

1.  **Task 3.1: Add Methods for `textract_jobs` Table Interaction**
    *   **Description:** Implement new methods in `SupabaseManager` for the `textract_jobs` table and update `source_documents` with Textract outcomes.
    *   **Reference:** `context_53_textract_plan.md`, Section 3.1, Lines 131-133 (description).
    *   **Details:**
        *   Implement `create_textract_job_entry()` (Lines 138-172). Ensure imports from `config` for `TEXTRACT_CONFIDENCE_THRESHOLD`, `TEXTRACT_SNS_TOPIC_ARN`.
        *   Implement `update_textract_job_status()` (Lines 173-211).
        *   Implement `get_textract_job_by_job_id()` (Lines 212-219).
        *   Implement `update_source_document_with_textract_outcome()` (Lines 221-264). Ensure `json` and `datetime` are imported.

---

**Phase 4: New Textract Utilities (`textract_utils.py`)**
*File to Create: `textract_utils.py`*

1.  **Task 4.1: Implement `TextractProcessor` Class**
    *   **Description:** Create the `TextractProcessor` class, initializing it with `SupabaseManager` and implementing Textract interaction logic.
    *   **Reference:** `context_53_textract_plan.md`, Section 4, Lines 266-268 (description).
    *   **Details:**
        *   Implement `__init__()` (Lines 276-280). Ensure `SupabaseManager` is imported and config variables are imported.
        *   Implement `start_document_text_detection()` (Lines 281-328). This includes DB calls via `self.db_manager`. Import `uuid`.
        *   Implement `get_text_detection_results()` (Lines 329-422). This includes polling logic and DB updates. Import `time`, `datetime`.
        *   Implement `process_textract_blocks_to_text()` (Lines 424-454). Import `defaultdict`. Ensure it uses `TEXTRACT_CONFIDENCE_THRESHOLD`.

---

**Phase 5: OCR Extraction Logic (`ocr_extraction.py`)**
*File to Modify: `ocr_extraction.py`*

1.  **Task 5.1: Remove Mistral-related Elements**
    *   **Description:** Delete Mistral-specific functions and imports.
    *   **Reference:** `context_53_textract_plan.md`, Section 5.1, Line 458.
    *   **Details:** Remove `extract_text_from_pdf_mistral_ocr()` and any associated utility imports if they were solely for Mistral.

2.  **Task 5.2: Update `extract_text_from_pdf_textract()`**
    *   **Description:** Modify this function to be the primary PDF OCR handler using the new `TextractProcessor`.
    *   **Reference:** `context_53_textract_plan.md`, Section 5.2, Lines 459-461 (description), Lines 468-604 (code snippet).
    *   **Details:**
        *   Ensure `SupabaseManager`, `TextractProcessor`, `S3StorageManager` are imported.
        *   Implement the helper `_download_supabase_file_to_temp()` (Lines 476-493) if it doesn't exist or needs update. Import `tempfile`, `requests`.
        *   Modify `extract_text_from_pdf_textract()` signature and logic as shown:
            *   Accept `db_manager`, `source_doc_sql_id`.
            *   Fetch `document_uuid` (Line 506).
            *   Handle various `pdf_path_or_s3_uri` types (S3, HTTP, local) by ensuring file is on S3 (Lines 519-560). This involves calling `s3_manager.upload_document_with_uuid_naming()` and updating `source_documents` with S3 info.
            *   Call `textract_processor.start_document_text_detection()` and `textract_processor.get_text_detection_results()` (Lines 573-590).
            *   Process blocks and prepare `page_level_metadata_for_db` (Lines 594-609).
            *   The final update to `source_documents` with extracted text is handled within this function or by `TextractProcessor` during its callbacks. The plan indicates `get_text_detection_results` handles most DB updates for status, and `extract_text_from_pdf_textract` handles the final text and its specific metadata. Review Lines 594-609 carefully.
            *   Implement robust error handling and `finally` block for cleanup (Lines 602-620).

---

**Phase 6: Main Pipeline Logic (`main_pipeline.py`)**
*File to Modify: `main_pipeline.py`*

1.  **Task 6.1: Update Imports**
    *   **Description:** Adjust imports for new OCR functions.
    *   **Reference:** `context_53_textract_plan.md`, Section 6.1, Line 624.
    *   **Details:** Ensure `extract_text_from_pdf_textract` is imported. Remove Mistral-related imports.

2.  **Task 6.2: Modify PDF Processing in `process_single_document()`**
    *   **Description:** Adapt the PDF handling branch to use the updated `extract_text_from_pdf_textract`.
    *   **Reference:** `context_53_textract_plan.md`, Section 6.2, Lines 625-627 (description), Lines 629-717 (code snippet for `process_single_document`).
    *   **Details:**
        *   Fetch `source_doc_info` and `source_doc_uuid` (Lines 636-644).
        *   Update `source_documents.ocr_provider` and `textract_job_status` to 'not_started' *before* calling the extraction function for PDFs (Lines 646-651).
        *   Call `extract_text_from_pdf_textract(db_manager, source_doc_sql_id, file_path, document_uuid_from_db)` (Lines 656-661).
        *   Note: The plan states DB updates for Textract job status are handled within the `extract_text_from_pdf_textract` function.
        *   For non-PDF types (docx, txt, audio), ensure their `ocr_provider` and `ocr_completed_at` (and other relevant fields like `raw_extracted_text`, `initial_processing_status`) are updated in `source_documents` (Lines 663-683).
        *   Ensure the logic after extraction (Neo4j node creation, etc.) uses the correct `source_doc_uuid` and `project_uuid` (Lines 700-717).

---

**Phase 7: Queue Processor Adjustments (`queue_processor.py`)**
*File to Modify: `queue_processor.py`*

1.  **Task 7.1: Update File Path Handling and Provider Update in `_process_claimed_documents()`**
    *   **Description:** Adjust how `file_path_for_pipeline` is determined and update `ocr_provider` on queue item for PDFs.
    *   **Reference:** `context_53_textract_plan.md`, Section 7.1, Lines 719-721 (description), Lines 727-762 (code snippet).
    *   **Details:**
        *   Modify `_process_claimed_documents` to derive `file_path_for_pipeline` from `source_doc_details.s3_key/s3_bucket` or `original_file_path` (Lines 737-751).
        *   If `detected_file_type` is '.pdf', update `ocr_provider` to 'textract' on the `document_processing_queue` item (Lines 753-754).

2.  **Task 7.2: Update `mark_queue_item_failed()`**
    *   **Description:** Enhance failure marking to potentially update associated Textract job status and `source_documents` more comprehensively.
    *   **Reference:** `context_53_textract_plan.md`, Section 7.1, within `QueueProcessor` class, Lines 766-795 (code snippet).
    *   **Details:** Implement the logic to fetch `textract_job_id` from the queue item and use it to update `textract_jobs` and `source_documents` tables on failure.

3.  **Task 7.3: Update `claim_pending_documents()`**
    *   **Description:** Ensure claiming logic correctly fetches necessary fields (like `source_document_uuid`, `textract_job_id` if present on queue table) and passes them to `_process_claimed_documents`. The provided snippet uses direct Supabase queries.
    *   **Reference:** `context_53_textract_plan.md`, Section 7.1, within `QueueProcessor` class, Lines 806-852 (code snippet for `claim_pending_documents`).
    *   **Details:** Implement the direct Supabase query logic for claiming, ensuring all relevant fields (`id, source_document_id, source_document_uuid, retry_count, textract_job_id`) are selected from the queue table and passed appropriately. `textract_job_id` is *not* set here during claim, but passed if already existing.

4.  **Task 7.4 (Review): `check_for_stalled_documents()`**
    *   **Description:** The plan notes this function may need future enhancements to interact with `textract_jobs`. For now, ensure the existing logic (resetting or failing queue items based on timeout) correctly calls the updated `mark_queue_item_failed`.
    *   **Reference:** `context_53_textract_plan.md`, Lines 853-861 in the plan's description for `QueueProcessor`. (Note: The plan's snippet for `claim_pending_documents` in section 7.1 seems to be more extensive and might have been intended as a full class replacement including a basic stalled check. The agent should use the provided code as the basis for the `QueueProcessor` methods mentioned).
    *   **Action:** Review the existing `check_for_stalled_documents` method (if one exists in the current codebase, or use the example logic from the plan if provided, typically near line 860 of the plan document) to ensure it integrates well with the changes, especially how it calls `mark_queue_item_failed`.

---

**Phase 8: Final Checks and Considerations (Informational for Agent/Developer)**
*No direct coding tasks, but important for context and testing.*
*Reference: `context_53_textract_plan.md`, Section 8, Lines 854-876.*

*   Verify IAM permissions.
*   Test error handling in `TextractProcessor` for specific Textract exceptions.
*   Consider migration strategy for existing S3 files if needed (outside this scope).
*   Confirm `TEXTRACT_OUTPUT_S3_PREFIX` configuration.
*   Understand idempotency via `ClientRequestToken`.
*   Be aware of potential for long-running jobs and future SNS integration.

---

This index should help the agent navigate the plan systematically. Good luck!