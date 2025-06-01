Okay, this is an excellent and detailed request! To create a comprehensive monitoring script for your OCR document processing pipeline, the agentic coding tool will need to synthesize information from various parts of your codebase and draw inspiration from `flower` for Celery-specific monitoring.

Here's a markdown document to guide the agent:

```markdown
# Comprehensive Monitoring Script for OCR Document Processing Pipeline

## 1. Objective

Create a new, standalone Python script named `pipeline_monitor.py`. This script will provide a comprehensive real-time monitoring dashboard for the OCR document processing pipeline. It should display key metrics, queue statuses, worker health, error rates, and overall system performance. The script will draw conceptual inspiration from `flower` (https://github.com/mher/flower/) for Celery monitoring aspects but will be custom-built to monitor the entire pipeline, including Supabase queues and Redis states.

## 2. Background: Pipeline Overview

The OCR document processing pipeline involves several stages:

1.  **Document Intake & Queueing:** Documents are registered in the `source_documents` table (Supabase). `queue_processor.py` claims items from the `document_processing_queue` table (Supabase) and enqueues them into Celery.
2.  **Celery Application:** Defined in `celery_app.py`, using Redis as the broker and backend. It routes tasks to specific queues (`ocr`, `text`, `entity`, `graph`).
3.  **OCR & Text Extraction:** `ocr_tasks.py` handles text extraction using AWS Textract (for PDFs) or other parsers (for DOCX, TXT, EML) and audio transcription (Whisper). Results and status are updated in `source_documents` and `textract_jobs` (Supabase).
4.  **Text Processing & Chunking:** `text_tasks.py` cleans text, creates `neo4j_documents` entries, categorizes documents, and then chunks them into `neo4j_chunks` (Supabase).
5.  **Entity Extraction & Resolution:** `entity_tasks.py` extracts entities from chunks into `neo4j_entity_mentions` and then resolves them into `neo4j_canonical_entities` (Supabase).
6.  **Relationship Building:** `graph_tasks.py` stages relationships in `neo4j_relationships_staging` (Supabase).
7.  **State Management:** `redis_utils.py` and `cache_keys.py` define how Redis is used for caching and potentially for more granular document state tracking (as seen in `main_pipeline.py`'s `update_document_state` and `cache_warmer.py`).
8.  **Configuration:** Managed via `config.py`.
9.  **Utilities:** `supabase_utils.py`, `s3_storage.py`, `models_init.py`.

Existing scripts like `health_check.py` and `monitor_live_test.py` provide some monitoring capabilities. The new `pipeline_monitor.py` should consolidate, expand, and provide a more holistic, real-time view.

## 3. Core Requirements for `pipeline_monitor.py`

The script should:

1.  **Connect to Supabase and Redis:** Use credentials and settings from `config.py` via `supabase_utils.py` and `redis_utils.py`.
2.  **Display a Real-time Dashboard in the Console:**
    *   The display should refresh automatically (e.g., every 5-10 seconds).
    *   Use `os.system('clear')` or `os.system('cls')` for screen clearing.
    *   The output format should be human-readable, well-organized, and potentially use emojis for status indicators (similar to `monitor_live_test.py`).
3.  **Monitor Key Metrics:**

    *   **A. Supabase Document Processing Queue (`document_processing_queue` table):**
        *   Total items by status: `pending`, `processing`, `failed`, `completed`.
        *   Number of items with `retry_count` >= `max_retries` (default 3).
        *   Average age of `pending` items.
        *   Number of items `processing` for longer than a threshold (e.g., > 30 minutes, configurable).
        *   Recent failed items (last 5, with document ID and error message snippet).

    *   **B. Celery Monitoring (Inspired by Flower - data fetched from Redis broker/backend):**
        *   **Queues:**
            *   List all Celery queues defined in `celery_app.py` (`default`, `ocr`, `text`, `entity`, `graph`).
            *   Number of messages (tasks) in each Celery queue (e.g., using Redis `LLEN` on keys like `ocr`, `celery`, etc. – investigate Celery's default Redis key naming for queues).
        *   **Workers (Conceptual - requires Celery events or custom worker heartbeats):**
            *   Number of currently active/registered Celery workers (if discoverable via Celery/Redis introspection). Flower does this by inspecting control commands or events. If direct worker introspection is too complex, focus on queue lengths and task states.
            *   *(Advanced, if feasible)* Tasks processed/failed per worker type (ocr, text, etc.) if workers identify their type.
        *   **Tasks:**
            *   Number of active (running) tasks by type (ocr, text, entity, graph).
            *   Number of recently completed tasks (last hour) by type.
            *   Number of recently failed tasks (last hour) by type, with error snippets.
            *   Average task processing time by type (e.g., `ocr_tasks.process_ocr`). This requires tracking task start/end times, potentially from Celery events or the Redis backend if `task_track_started` is enabled.

    *   **C. Redis Cache & State Monitoring:**
        *   Overall Redis connection status (ping).
        *   Key cache metrics (Hits, Misses, Hit Rate) using `CacheMetrics` from `redis_utils.py`.
        *   Number of `DOC_STATE` keys in Redis (pattern: `doc:state:*`) to understand how many documents are actively tracked.
        *   Number of `DOC_PROCESSING_LOCK` keys (`doc:lock:*`).
        *   Number of `TEXTRACT_JOB_STATUS` keys (`job:textract:status:*`).

    *   **D. Database Table Metrics (Supabase):**
        *   Total `source_documents` and breakdown by `initial_processing_status`.
        *   Total `neo4j_documents` and breakdown by `processingStatus`.
        *   Total `textract_jobs` and breakdown by `job_status`.
        *   Counts for `neo4j_chunks`, `neo4j_entity_mentions`, `neo4j_canonical_entities`, `neo4j_relationships_staging`.

    *   **E. Overall Pipeline Health & Throughput:**
        *   Documents fully processed (status='completed' in `source_documents`) in the last hour / last 24 hours.
        *   End-to-end processing time for recently completed documents (average, P95). (Calculated from `source_documents.intake_timestamp` to a final completion timestamp, perhaps `ocr_completed_at` if that's the final step tracked directly, or infer from `neo4j_documents.updatedAt` when status is `complete`).
        *   Overall error rate (e.g., (total failed tasks or documents) / (total processed + failed)).

4.  **Error Reporting:**
    *   Display a summary of recent critical errors from different pipeline stages.
    *   Highlight components that appear to be bottlenecks or sources of frequent failures.

5.  **Configuration:**
    *   Allow refresh interval to be configurable via a command-line argument.
    *   Thresholds for "stalled" items should be configurable (e.g., via constants in the script).

## 4. Key Reference Files from Provided Codebase

The agent MUST analyze these files to understand the pipeline's structure, data models, and how to query for status:

*   `config.py`: For database/Redis connection details, queue names, S3 buckets.
*   `celery_app.py`: Celery application setup, queue definitions, broker/backend URLs.
*   `queue_processor.py`: Logic for pulling from Supabase queue and enqueuing to Celery.
*   `supabase_utils.py`: For interacting with Supabase tables.
*   `redis_utils.py` & `cache_keys.py`: For interacting with Redis and understanding cache/state key structures.
*   `ocr_tasks.py`, `text_tasks.py`, `entity_tasks.py`, `graph_tasks.py`: To understand task names and flow.
*   `main_pipeline.py`: For `update_document_state` logic which shows how Redis is used for fine-grained state.
*   `health_check.py` & `monitor_live_test.py`: For existing monitoring ideas and output formatting.
*   Database Schema (Implicit): The Supabase table structures (e.g., `document_processing_queue.status`, `source_documents.initial_processing_status`, `neo4j_documents.processingStatus`, `textract_jobs.job_status`) are critical for queries.

## 5. Inspiration from `flower`

While not directly using `flower`'s code, draw inspiration from:

*   **Types of Celery Metrics:** Number of tasks in queues, active tasks, processed/failed tasks, registered workers.
*   **Dashboard Layout:** How `flower` organizes information about workers, tasks, and queues.
*   **Real-time Updates:** The concept of a continuously updating view.

## 6. Implementation Guidance

*   **Main Loop:** A `while True` loop that fetches data, clears the screen, prints the dashboard, and sleeps.
*   **Data Fetching Functions:** Separate functions for fetching data from Supabase, Redis, and Celery (via Redis).
    *   Example Supabase query for queue stats:
        ```python
        # Inside a function in pipeline_monitor.py
        # db = SupabaseManager() # from supabase_utils
        # response = db.client.table('document_processing_queue').select('status', count='exact').group('status').execute()
        # status_counts = {item['status']: item['count'] for item in response.data}
        ```
    *   Example Redis query for Celery queue length (assuming default Celery naming on Redis):
        ```python
        # Inside a function in pipeline_monitor.py
        # redis_cli = get_redis_manager().get_client() # from redis_utils
        # ocr_queue_length = redis_cli.llen('ocr') # 'ocr' is the queue name
        ```
*   **Display Functions:** Functions to format and print different sections of the dashboard.
*   **Class Structure (Recommended):** A `PipelineMonitor` class could encapsulate the logic.
*   **Error Handling:** The monitoring script itself should be robust. Catch exceptions during data fetching (e.g., Redis/Supabase connection errors) and display appropriate error messages within the dashboard without crashing.
*   **Command-Line Interface:** Use `argparse` for options like `--refresh-interval`.
*   **Start with Core Metrics:** Implement Supabase queue monitoring and Celery queue length monitoring first, then expand.

## 7. Function Stubs (Illustrative)

```python
# In pipeline_monitor.py

class PipelineMonitor:
    def __init__(self, refresh_interval=10):
        self.db_manager = SupabaseManager()
        self.redis_manager = get_redis_manager()
        self.celery_app = celery_app # Imported from your celery_app.py
        self.refresh_interval = refresh_interval
        # ...

    def get_supabase_queue_stats(self) -> dict:
        # ... query document_processing_queue ...
        pass

    def get_celery_queue_stats(self) -> dict:
        # ... query Redis for Celery queue lengths ...
        # Example: self.redis_manager.get_client().llen('ocr')
        pass

    def get_celery_task_stats(self) -> dict:
        # ... inspect Celery backend (Redis) for task states ...
        # This is more complex, might involve scanning keys related to tasks.
        # Flower uses Celery's event stream or remote control commands.
        # A simpler approach might be to query your `source_documents` and `neo4j_documents`
        # for statuses that indicate task progress/completion/failure if Celery tasks update these.
        # The `celery_app.conf.task_send_sent_event = True` and `worker_send_task_events = True`
        # mean events are available if a consumer is set up. For this script, direct Redis inspection is more likely.
        pass

    def get_database_table_stats(self) -> dict:
        # ... query various Supabase tables for counts ...
        pass

    def get_redis_cache_stats(self) -> dict:
        # ... use CacheMetrics from redis_utils.py ...
        pass

    def display_dashboard(self, stats: dict):
        # ... clear screen and print all formatted stats ...
        # Refer to monitor_live_test.py for formatting ideas
        pass

    def run(self):
        try:
            while True:
                all_stats = {}
                all_stats['supabase_queue'] = self.get_supabase_queue_stats()
                all_stats['celery_queues'] = self.get_celery_queue_stats()
                # ... gather other stats ...
                self.display_dashboard(all_stats)
                time.sleep(self.refresh_interval)
        except KeyboardInterrupt:
            print("Monitoring stopped.")
        except Exception as e:
            print(f"Monitoring script error: {e}")
            # Log traceback

if __name__ == '__main__':
    # argparse setup
    # monitor = PipelineMonitor(refresh_interval=args.refresh_interval)
    # monitor.run()
    pass
```

## 8. Final Output

The agent should produce a single Python script `pipeline_monitor.py` that, when run, connects to the necessary services and displays the real-time monitoring dashboard in the console.

This detailed guidance should enable the agentic tool to create a highly effective monitoring script by understanding the existing pipeline and leveraging the conceptual strengths of tools like `flower`.
```

