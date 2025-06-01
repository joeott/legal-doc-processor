# Definitive Migration Guide: Celery & Redis-Controlled Processing Queue

## 1. Objective

Refactor the OCR document processing pipeline to establish **Celery, using Redis as its standard message broker, as the sole and definitive controller of the processing queue and workflow.** This directive involves:

1.  **Eliminating Reliance on Supabase Queues:** The Supabase `document_processing_queue` table will no longer be used as an active queuing mechanism for new work.
2.  **Neutralizing Supabase Triggers:** Any Supabase database triggers attempting to manage document processing states or workflow based on table changes must be disabled or removed. State management will be explicit within Celery tasks.
3.  **Direct Celery Task Submission:** New documents will be directly submitted as tasks to Celery.
4.  **Celery-Managed Workflow:** Celery tasks will manage their own state progression and robustly chain to subsequent Celery tasks using standard Celery mechanisms (e.g., `.delay()`, `.apply_async()`, or Celery Canvas primitives if complex workflows are needed later).
5.  **Clarification on Redis Streams:** The existing Redis Stream functionalities in `redis_utils.py` (`produce_to_stream`, `create_consumer_group`) will **not** be integrated to manage the primary task-to-task flow *within* the Celery pipeline. Celery will use Redis as its broker via its default list-based mechanisms. These stream functions may be used in the future for eventing to external systems or for specialized, isolated use cases outside the main Celery workflow.
6.  **Role of `task_coordinator.py`:** This custom Redis-based task system will not be used for the primary Celery workflow. Celery itself will be the orchestrator.

## 2. Problem Statement

The current pipeline's dependency on the Supabase `document_processing_queue` table and associated database triggers for workflow management has proven unreliable and complex to maintain. Previous attempts to fix triggers (`fix_triggers.py`, `apply_migration.py`) and migrate documents (`migrate_to_celery.py`) highlight the need for a fundamental shift to a more robust, Celery-native control flow.

## 3. Mandated Architecture: Celery-Centric Workflow with Standard Redis Broker

1.  **Document Intake:**
    *   All new documents (regardless of source: S3, local, API) will initiate processing by directly creating an initial Celery task (e.g., `ocr_tasks.process_ocr.delay(...)`).
    *   The `source_documents` table in Supabase will be updated with a `celery_task_id` and an initial status like `ocr_queued`.
2.  **Celery as the Definitive Queue Manager:**
    *   Redis, as configured in `celery_app.py` (broker and backend), will exclusively manage Celery task queues (`ocr`, `text`, `entity`, `graph`) using Celery's standard Redis list operations.
3.  **Task Chaining via Celery:**
    *   Each Celery task, upon successful completion, will be solely responsible for:
        *   Updating the persistent document status in the relevant Supabase tables (e.g., `source_documents.initial_processing_status`, `neo4j_documents.processingStatus`) via `SupabaseManager`.
        *   Triggering the next Celery task in the pipeline using standard Celery invocation methods (e.g., `next_task.delay(...)`).
        *   Updating the fine-grained, *monitoring-specific* document state in Redis using the `update_document_state` function.
4.  **Error Handling and Retries:**
    *   Celery's built-in retry mechanisms (`max_retries`, `default_retry_delay`, exponential backoff) will be the primary method for handling transient task failures.
    *   Tasks that ultimately fail (after exhausting retries) will update the document status in Supabase to an appropriate error state (e.g., `error_ocr`, `error_text_processing`).
5.  **Source of Truth for Workflow and State:**
    *   **Workflow Control:** Celery's internal state (managed via the Redis broker) dictates task execution and sequencing.
    *   **Persistent Document Status:** Supabase tables (`source_documents`, `neo4j_documents`) will store the canonical, persistent processing status of each document.
    *   **Monitoring State:** Redis (via `update_document_state`) will store a detailed, potentially ephemeral, state for real-time monitoring dashboards.
6.  **Supabase `document_processing_queue` Table:**
    *   This table will be **deprecated** for active queue management. No new work items will be added to it by the Python application.
    *   It may be retained for a period for historical data or completely removed in a subsequent cleanup phase.
    *   The `queue_processor.py` script, in its current form polling this table, will be significantly refactored or deprecated.

## 4. Detailed Implementation Directives for the Agent

### Directive 1: Modify Document Intake – Direct to Celery Submission

*   **Target Files:** `queue_processor.py`, `main_pipeline.py`, `live_document_test.py`.

*   **`queue_processor.py`:**
    *   **Action:** This script must **no longer poll** the Supabase `document_processing_queue` for new work.
    *   It should be **refactored or replaced** by a mechanism that directly submits tasks to Celery upon new document arrival (e.g., if it's triggered by an S3 event, an API call, or a directory watcher).
    *   If `queue_processor.py` is currently the *entry point* for some intake process, that process must be changed to directly call the first Celery task.
    *   **Remove all logic** related to `claim_pending_documents` that reads from `document_processing_queue`.

*   **`main_pipeline.py` (Direct Mode):**
    *   The `process_single_document` function (when `processing_mode == "direct"`) **must be modified.**
    *   **Action:** After registering the document in `source_documents` (via `db_manager.create_source_document_entry`), it must **immediately submit the first Celery task** (e.g., `ocr_tasks.process_ocr.delay(...)`) with all necessary parameters.
    *   Update `source_documents` with the `celery_task_id` and an initial Celery-related status (e.g., `ocr_queued`).
    *   **Remove all subsequent synchronous processing steps** (OCR, chunking, etc.) from `process_single_document`, as these will now be handled by the Celery task chain.

*   **`live_document_test.py`:**
    *   The `_test_queue_processing` method **must be modified.**
    *   **Action:** Remove calls to `self.db_manager.create_queue_entry()` and `QueueProcessor`. Instead, after registering the document, directly submit the first Celery task (e.g., `ocr_tasks.process_ocr.delay(...)`).
    *   The `_wait_for_completion` method will need to be adapted to monitor either the Celery task's result (if feasible and simple) or, more reliably, the final status of the document in the `source_documents` or `neo4j_documents` table as updated by the last Celery task in the chain.

### Directive 2: Ensure Robust Celery Task State Management and Chaining

*   **Target Files:** `ocr_tasks.py`, `text_tasks.py`, `entity_tasks.py`, `graph_tasks.py`.

*   **Explicit State Updates in Supabase:**
    *   **Action:** At the beginning of each task, update the document's status in the relevant Supabase table (e.g., `source_documents.initial_processing_status = 'ocr_processing'`, `neo4j_documents.processingStatus = 'text_processing_started'`) using `self.db_manager`.
    *   Upon successful completion of a task's logic, update the Supabase status to reflect completion of that stage (e.g., `'ocr_complete'`, `'text_processing_completed'`).
    *   If a task fails permanently (after Celery retries), its `on_failure` handler (or a `try...except` block within the task) **must** update the Supabase status to an error state (e.g., `'error_ocr'`, `'error_entity_extraction'`).
    *   The `update_document_state(document_uuid, phase, status, metadata)` calls using Redis are for **monitoring purposes** and should continue, but are not the primary state for workflow control.

*   **Reliable Task Chaining:**
    *   **Action:** Verify that each task, upon successful completion of its primary logic and Supabase status update, correctly and reliably calls the next task in the sequence using `next_task.delay(...)` or `next_task.apply_async(...)`.
    *   Ensure all necessary data (IDs, UUIDs, paths, critical results from the current task) is passed to the next task in the chain.

*   **Idempotency:**
    *   **Action:** Review tasks for idempotency. If a Celery task retries, it should ideally be ables to resume or re-process without creating duplicate data or side effects. This might involve checking the current Supabase status of the document/chunk before performing extensive work. The existing `IDEMPOTENT_*` cache keys in `cache_keys.py` (if used by tasks) should be reviewed for effectiveness in this new Celery-centric flow.

### Directive 3: Disable and Remove Supabase Trigger Dependencies

*   **Target Files:** Database schema (SQL migration files), `fix_triggers.py`, `apply_migration.py`.

*   **Action:**
    1.  The agent must identify any Supabase database triggers (e.g., on `source_documents`, `neo4j_documents`) that automatically modify processing statuses or attempt to initiate subsequent processing steps.
    2.  These triggers **must be disabled or completely removed** from the database schema. Workflow progression and status updates will be handled explicitly by Celery tasks.
    3.  Analyze `fix_triggers.py` and the SQL migration `00005_fix_status_enums_and_triggers.sql`. If they already disable the problematic triggers, ensure this is comprehensive. If not, generate new SQL or modify these scripts to achieve complete removal of trigger-based workflow.

### Directive 4: Verify Redis Configuration for Celery and State Management

*   **Target Files:** `celery_app.py`, `redis_utils.py`, `cache_keys.py`.

*   **Action:**
    1.  **Confirm `celery_app.py`:** Ensure Redis is correctly configured as the `broker_url` and `result_backend`. All Celery queues (`ocr`, `text`, `entity`, `graph`) should be properly defined.
    2.  **Role of `redis_utils.py` Stream Functions:** Reiterate that `produce_to_stream`, `create_consumer_group` are **not** to be used for the main Celery task-to-task workflow. Their use is reserved for potential future eventing to external systems. No modifications are needed here unless such eventing is explicitly part of another requirement.
    3.  **State Management via `update_document_state`:** This function (present in `*_tasks.py` and `main_pipeline.py`) using `CacheKeys.DOC_STATE` is valuable for *monitoring*. Ensure it's called appropriately at the start/end/failure of relevant processing phases within Celery tasks.

### Directive 5: Configuration Review

*   **Target File:** `config.py`.

*   **Action:**
    1.  Remove any configuration variables related to polling the Supabase `document_processing_queue` (e.g., old batch sizes for Supabase queue, polling intervals) if they are no longer used.
    2.  Ensure all Celery, Redis, Supabase, and AWS configurations are clear and correctly utilized by the refactored system.

### Directive 6: Update Monitoring and Health Checks

*   **Target Files:** `pipeline_monitor.py` (to be created/updated based on prior instruction), `health_check.py`.

*   **Action:**
    1.  The `pipeline_monitor.py` script's logic for "Supabase Document Processing Queue" metrics **must be removed or heavily adapted** to reflect that this queue is no longer active for new work. It might show historical counts if the table is kept.
    2.  The focus of `pipeline_monitor.py` must shift to Celery queue lengths (from Redis), Celery task states (if introspectable from Redis backend), and document statuses in `source_documents` / `neo4j_documents` as the primary indicators of pipeline health and progress.
    3.  `health_check.py`'s `check_queue_health` method needs similar adaptation.

## 5. Key Files for Agent Modification/Review:

*   **`queue_processor.py`**: **Major refactor or deprecation.** Its role as a Supabase queue poller must cease.
*   **`main_pipeline.py`**: Modify `direct` mode to submit to Celery. Ensure `update_document_state` is used for monitoring state.
*   **`live_document_test.py`**: Modify `_test_queue_processing` to submit to Celery directly. Adapt `_wait_for_completion`.
*   **Celery Task Files (`ocr_tasks.py`, `text_tasks.py`, `entity_tasks.py`, `graph_tasks.py`)**: Implement explicit Supabase status updates. Ensure robust Celery task chaining. Call `update_document_state` for monitoring.
*   **`supabase_utils.py`**: Remove or comment out functions that actively write to or poll `document_processing_queue` for new work.
*   **`celery_app.py`**: Verify Redis broker/backend configuration.
*   **Database Schema & Migrations (e.g., `fix_triggers.py`, `00005_fix_status_enums_and_triggers.sql`)**: **Critically ensure** workflow-related triggers are disabled/removed.
*   **`config.py`**: Review and remove obsolete configurations.

## 6. Verification and Testing Strategy

1.  **New Document Intake:**
    *   Test submitting documents via the refactored `main_pipeline.py` (direct mode).
    *   Test submitting documents via the refactored `live_document_test.py`.
    *   If any other intake mechanisms exist, ensure they now directly submit to Celery.
2.  **Celery Workflow:**
    *   Use `flower` or Redis CLI (`LLEN queue_name`) to observe tasks moving through Celery queues (`ocr`, `text`, `entity`, `graph`).
    *   Monitor Celery worker logs for task execution.
3.  **Supabase State Integrity:**
    *   Verify that `source_documents.initial_processing_status` and `neo4j_documents.processingStatus` are updated correctly and sequentially by the Celery tasks at each stage.
    *   Confirm `source_documents.celery_task_id` is populated.
4.  **Supabase Queue Deprecation:**
    *   Confirm that **no new items** are added to the `document_processing_queue` table during processing of new documents.
    *   Verify that no component is polling `document_processing_queue` for work.
5.  **Error Handling:**
    *   Intentionally cause a task in each stage to fail (e.g., by invalid input, temporary resource unavailability).
    *   Observe Celery's retry behavior.
    *   Verify that after retries are exhausted, the document's status in Supabase is correctly marked as an error state, and the error message is logged.
6.  **Monitoring:**
    *   Run the (updated) `pipeline_monitor.py` and `health_check.py` to ensure they accurately reflect the state of the Celery-controlled system.
7.  **Log Analysis:** Thoroughly review application logs for any errors, warnings, or indications of attempts to use the old Supabase queueing logic.

This refined directive provides a clear, decisive architectural path. The agent should focus on making Celery the robust and sole orchestrator of the document processing workflow, using Redis as its standard broker.