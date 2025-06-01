You've hit on a very important point. While the proposed Redis Streams implementation is a good step up from a monolithic process, **yes, using Celery in conjunction with Redis (as a message broker and result backend) would generally make your queuing and task management significantly more robust and feature-rich.**

Let's break down why and how:

**Current Redis Streams Proposal (Pros & Cons for Robustness):**

*   **Pros:**
    *   **Persistence:** Streams are persistent.
    *   **Decoupling:** Services are decoupled.
    *   **Basic Retry/DLQ:** Can be manually implemented (checking delivery counts, `XAUTOCLAIM`, moving to DLQ stream).
    *   **Consumer Groups:** Allow multiple workers per stage.
*   **Cons (compared to Celery):**
    *   **Manual Implementation:** Retry logic, DLQ handling, task state tracking, worker monitoring, and scaling are largely manual. This means more boilerplate code and more potential points of failure in your custom logic.
    *   **Task Monitoring:** No built-in dashboard like Celery's Flower. Monitoring relies on Redis commands (`XINFO`, `XPENDING`) and application logs.
    *   **Complex Workflows:** Chaining tasks, parallel execution, or grouping results require more complex application-level logic.
    *   **Error Handling Specificity:** Celery allows fine-grained control over retries based on exception types, custom backoff strategies, etc.
    *   **Resource Management:** Celery provides better tools for managing worker concurrency, prefetching, etc.

**Celery with Redis (Benefits for Robustness):**

Celery is a distributed task queue system. When used with Redis as the message broker and result backend:

1.  **Mature Task Management:**
    *   **Automatic Retries:** Built-in, configurable retry mechanisms (e.g., exponential backoff, max retries).
    *   **Task State Tracking:** Celery tracks task states (PENDING, STARTED, SUCCESS, FAILURE, RETRY).
    *   **Error Handling:** Richer error handling capabilities.
    *   **Time Limits & Rate Limits:** Can set soft/hard time limits for tasks and control task execution rates.
2.  **Worker Management:**
    *   Manages worker processes/threads.
    *   Easy to scale workers horizontally.
    *   Provides signals and events for worker lifecycle.
3.  **Monitoring:**
    *   Excellent monitoring tools like **Flower** provide a web UI to inspect tasks, workers, queues, and performance.
4.  **Workflow Primitives:**
    *   Easily define complex workflows using `chain` (sequence), `group` (parallel), `chord` (group with a callback).
5.  **Reduced Boilerplate:** You write task functions, and Celery handles the queuing, delivery, execution, and state management.

**How Celery and Redis Streams *Could* Work Together (and a Simpler, More Common Celery Approach):**

When people say "Celery with Redis," Celery typically uses Redis **Lists** (or Pub/Sub for broadcast) as its message broker by default, not Redis Streams directly for its core task queuing. It *can* use Redis Streams via an experimental backend (`celery-redis-streams`), but this is less common and might not be as battle-tested as the default List-based broker.

**The Most Robust and Common Approach:**

Use **Celery with Redis as its standard broker (using Lists) and result backend.** Each of your pipeline stages becomes a Celery task.

*   **Intake Service (`QueueProcessor`):** Still fetches from Supabase. Instead of `XADD`ing to a Redis Stream, it will call a Celery task: `ocr_task.delay(...)`.
*   **OCR Task (`@app.task def ocr_task(...)`):** Performs OCR. On success, it can then call the next task in the pipeline: `cleaning_task.delay(...)`.
*   And so on for each stage.

**Why this is generally preferred over manually managing Redis Stream consumers for task processing:**

*   You leverage Celery's mature features for retries, state, monitoring, etc., which you'd have to build yourself if you were only using Redis Streams for inter-service task passing.
*   Celery abstracts the underlying queuing mechanism (Redis Lists in this case).

**When might you *still* use Redis Streams alongside Celery?**

*   **Event Sourcing/Auditing:** If you want an immutable log of all events/state changes in your system (beyond what Celery task history provides), Redis Streams could serve this purpose. Celery tasks could produce events to a separate "audit" stream.
*   **Broadcasting Events to Multiple, Different Types of Consumers:** If an event (e.g., "document OCR complete") needs to be consumed by *multiple different* systems for *different purposes* (not just the next step in the pipeline), Streams with multiple consumer groups are excellent. Celery's equivalent would be more complex (e.g., fanning out to multiple queues or using Pub/Sub).
*   **Extremely High-Throughput Simple Events:** For very high volumes of simple, fire-and-forget events where the full overhead of Celery tasks isn't needed, Streams might be considered.

**For your NLP pipeline, the primary goal is processing a document through a sequence of stages with retries, error handling, and monitoring. Celery excels at this.**

---

## Markdown Guide: Implementing Celery with Redis for a Robust NLP Pipeline

This guide outlines how to refactor your pipeline to use Celery, with Redis as the message broker and result backend.

### I. Conceptual Shift

*   **From Manual Stream Consumers to Celery Tasks:** Each processing stage (OCR, cleaning, chunking, NER, etc.) will be defined as a Celery task function.
*   **From Redis Streams for Task Passing to Celery Queues (backed by Redis Lists):** Celery will manage its own queues in Redis.
*   **Intake Service:** Your `QueueProcessor` will fetch from Supabase and then enqueue the first Celery task for a document.

### II. Prerequisites

1.  **Install Celery and Redis Python Client:**
    ```bash
    pip install celery redis "celery[redis]"
    ```

2.  **Ensure Redis Server is Running:**
    Your existing Redis setup is fine. Celery will use it as a broker.

### III. Step-by-Step Implementation

#### A. Configure Celery (`celery_app.py` or in `config.py`)

Create a new file, e.g., `celery_app.py`, or add this to your `config.py` (if `config.py` is imported before tasks are defined).

```python
# celery_app.py
from celery import Celery
import os

# Option 1: Environment variables for Redis URL (Recommended)
# Example: REDIS_URL="redis://your_redis_host:6379/0"
# Ensure REDIS_PASSWORD is part of the URL if needed: redis://:yourpassword@host:port/db
redis_url = os.getenv('CELERY_REDIS_URL', 'redis://localhost:6379/0') # Default, update as needed

# Ensure your RedisManager's REDIS_HOST, REDIS_PORT, REDIS_DB, REDIS_PASSWORD from config.py
# are consistent with this URL, or derive this URL from those settings.
# For example, if using config.py settings:
# from config import REDIS_HOST, REDIS_PORT, REDIS_DB, REDIS_PASSWORD
# if REDIS_PASSWORD:
#    redis_url = f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"
# else:
#    redis_url = f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"


# We need to tell Celery where to find your task modules.
# If your tasks are in services like ocr_service.py, chunking_service.py:
# Assuming these files are in the same directory or accessible via PYTHONPATH
# and each defines Celery tasks.
# For this example, let's assume you'll create a `tasks.py` file.
CELERY_INCLUDE_MODULES = ['app.tasks'] # Adjust to your project structure, e.g., ['your_project.tasks']

app = Celery(
    'nlp_pipeline', # Project name
    broker=redis_url,
    backend=redis_url, # Using Redis for results too
    include=CELERY_INCLUDE_MODULES # List of modules to import when worker starts
)

# Optional Celery configuration
app.conf.update(
    task_serializer='json',
    result_serializer='json',
    accept_content=['json'],
    timezone='UTC', # Or your timezone
    enable_utc=True,
    worker_prefetch_multiplier=1, # Important for long-running tasks
    task_acks_late=True,          # Acknowledge task after it's executed (not just delivered)
    result_expires=3600 * 24 * 7, # Keep results for 7 days
    # Default retry policy (can be overridden per task)
    task_publish_retry_policy={
        'max_retries': 3,
        'interval_start': 0.1,
        'interval_step': 0.2,
        'interval_max': 0.5,
    },
)

if __name__ == '__main__':
    app.start()
```
*   **Agent Note:** Place `celery_app.py` at a level where it can import task modules (e.g., at the root of your application package). Update `CELERY_INCLUDE_MODULES` based on where you define your tasks.

#### B. Define Celery Tasks (e.g., in a new `tasks.py`)

Create `tasks.py` (or organize tasks into respective service files like `ocr_tasks.py`, `chunking_tasks.py`). Import `app` from `celery_app.py`.

```python
# tasks.py
import logging
import json # For type hints and potential serialization if needed directly
from datetime import datetime

from .celery_app import app # Assuming celery_app.py is in the same directory or accessible
from .supabase_utils import SupabaseManager
from .main_pipeline import update_document_state # Or move this to a shared util
# Import your processing functions (these will be wrapped by tasks)
from .ocr_extraction import extract_text_from_pdf_textract, extract_text_from_docx # etc.
from .text_processing import clean_extracted_text, categorize_document_text, process_document_with_semantic_chunking
from .entity_extraction import extract_entities_from_chunk
from .entity_resolution import resolve_document_entities
from .relationship_builder import stage_structural_relationships
from .config import USE_STRUCTURED_EXTRACTION # And other relevant configs

logger = logging.getLogger(__name__)

# --- Helper to initialize managers within tasks ---
# Celery tasks should be self-contained or receive all necessary data.
# Instantiating managers inside tasks is common for DB/Redis connections.
def get_managers():
    db_manager = SupabaseManager()
    # redis_mgr = get_redis_manager() # If direct Redis access is needed beyond Celery
    return db_manager #, redis_mgr

# --- Define Celery Tasks for each pipeline stage ---

@app.task(bind=True, max_retries=3, default_retry_delay=60) # Retry after 1 min, up to 3 times
def ocr_task(self, document_uuid: str, source_doc_sql_id: int, file_path: str, file_name: str, detected_file_type: str, project_sql_id: int):
    """
    Celery task for OCR processing.
    """
    logger.info(f"[TASK_OCR:{self.request.id}] Processing doc_uuid: {document_uuid}, sql_id: {source_doc_sql_id}")
    db_manager = get_managers()
    update_document_state(document_uuid, "ocr", "celery_started", {"task_id": self.request.id})
    db_manager.update_processing_status('source_documents', source_doc_sql_id, 'ocr_celery_processing')

    raw_text = None
    ocr_meta_for_db = None
    ocr_provider = None

    try:
        if detected_file_type == '.pdf':
            ocr_provider = 'textract'
            db_manager.client.table('source_documents').update({
                'ocr_provider': ocr_provider, 'textract_job_status': 'not_started', 'last_modified_at': datetime.now().isoformat()
            }).eq('id', source_doc_sql_id).execute()
            raw_text, ocr_meta_for_db = extract_text_from_pdf_textract(
                db_manager=db_manager, source_doc_sql_id=source_doc_sql_id,
                pdf_path_or_s3_uri=file_path, document_uuid_from_db=document_uuid
            )
        # ... (add other file type extractions: docx, txt, eml, audio as in main_pipeline.py) ...
        # Example for DOCX:
        elif detected_file_type == '.docx':
            ocr_provider = 'docx_parser'
            raw_text = extract_text_from_docx(file_path)
            ocr_meta_for_db = [{"method": "docx_parser"}]
        else:
            logger.error(f"[TASK_OCR:{self.request.id}] Unsupported file type: {detected_file_type} for {document_uuid}")
            update_document_state(document_uuid, "ocr", "celery_failed", {"error": "Unsupported file type"})
            db_manager.update_source_document_text(source_doc_sql_id, None, status="extraction_unsupported")
            # Optionally, you might want to explicitly fail the task so it doesn't retry
            # raise Ignore() or a custom exception Celery won't retry.
            return # Stop processing for this document

        if raw_text is not None:
            db_manager.update_source_document_text(
                source_doc_sql_id, raw_text,
                ocr_meta_json=json.dumps(ocr_meta_for_db) if ocr_meta_for_db else None,
                status="ocr_celery_complete_pending_neo4j_node"
            )
            if ocr_provider:
                 db_manager.client.table('source_documents').update({
                    'ocr_provider': ocr_provider, 'ocr_completed_at': datetime.now().isoformat()
                }).eq('id', source_doc_sql_id).execute()
            update_document_state(document_uuid, "ocr", "celery_completed")
            
            # Chain to the next task
            create_document_node_task.delay(
                document_uuid=document_uuid,
                source_doc_sql_id=source_doc_sql_id,
                project_sql_id=project_sql_id,
                file_name=file_name,
                detected_file_type=detected_file_type,
                raw_text=raw_text, # Pass raw_text if needed by next stage, or fetch from DB
                ocr_meta_json_str=json.dumps(ocr_meta_for_db) if ocr_meta_for_db else None
            )
        else:
            # This means OCR process (e.g., Textract job) itself failed or returned no text
            logger.error(f"[TASK_OCR:{self.request.id}] OCR failed to extract text for {document_uuid}.")
            update_document_state(document_uuid, "ocr", "celery_failed", {"error": "OCR returned no text"})
            # DB status already updated by extract_text_from_pdf_textract on failure
            # No need to call db_manager.update_source_document_text for status here if OCR function handles it.
            # Consider raising an exception to trigger Celery retry if appropriate
            # raise self.retry(exc=Exception("OCR returned no text"), countdown=300) # Retry in 5 mins
            return # Stop processing

    except Exception as exc:
        logger.error(f"[TASK_OCR:{self.request.id}] Error processing {document_uuid}: {exc}", exc_info=True)
        update_document_state(document_uuid, "ocr", "celery_failed", {"error": str(exc)})
        db_manager.update_source_document_text(source_doc_sql_id, None, status="ocr_celery_error")
        raise self.retry(exc=exc, countdown=int(self.default_retry_delay * (self.request.retries + 1)))


@app.task(bind=True, max_retries=3, default_retry_delay=60)
def create_document_node_task(self, document_uuid: str, source_doc_sql_id: int, project_sql_id: int, file_name: str, detected_file_type: str, raw_text: str, ocr_meta_json_str: str):
    logger.info(f"[TASK_DOC_NODE:{self.request.id}] Creating Neo4j document node for {document_uuid}")
    db_manager = get_managers()
    update_document_state(document_uuid, "doc_node_creation", "celery_started", {"task_id": self.request.id})
    
    try:
        # Fetch project_uuid
        _project_uuid = db_manager.get_project_by_sql_id_or_global_project_id(project_sql_id, None) # PROJECT_ID_GLOBAL if needed
        if not _project_uuid:
            raise ValueError(f"Could not find project_uuid for project_sql_id {project_sql_id}")

        neo4j_doc_sql_id, neo4j_doc_uuid = db_manager.create_neo4j_document_entry(
            source_doc_fk_id=source_doc_sql_id, source_doc_uuid=document_uuid,
            project_fk_id=project_sql_id, project_uuid=_project_uuid, file_name=file_name
        )
        if not neo4j_doc_sql_id:
            raise RuntimeError(f"Failed to create neo4j_documents entry for {file_name}")
        
        ocr_meta_for_db = json.loads(ocr_meta_json_str) if ocr_meta_json_str else None
        cleaned_raw_text = clean_extracted_text(raw_text)
        doc_category = categorize_document_text(cleaned_raw_text, ocr_meta_for_db)

        db_manager.update_neo4j_document_details(
            neo4j_doc_sql_id, category=doc_category, file_type=detected_file_type,
            cleaned_text=cleaned_raw_text, status="pending_chunking"
        )
        update_document_state(document_uuid, "doc_node_creation", "celery_completed")
        
        # Chain to chunking task
        chunking_task.delay(
            document_uuid=document_uuid, # This is source_doc_uuid
            neo4j_doc_sql_id=neo4j_doc_sql_id,
            neo4j_doc_uuid=neo4j_doc_uuid, # This is the UUID of the neo4j_document record
            cleaned_text=cleaned_raw_text,
            ocr_meta_json_str=ocr_meta_json_str,
            doc_category=doc_category
        )
    except Exception as exc:
        logger.error(f"[TASK_DOC_NODE:{self.request.id}] Error: {exc}", exc_info=True)
        update_document_state(document_uuid, "doc_node_creation", "celery_failed", {"error": str(exc)})
        # Update source_document status to reflect failure at this stage
        db_manager.update_source_document_text(source_doc_sql_id, raw_text, status="error_neo4j_doc_creation")
        raise self.retry(exc=exc)


@app.task(bind=True, max_retries=3, default_retry_delay=60)
def chunking_task(self, document_uuid: str, neo4j_doc_sql_id: int, neo4j_doc_uuid: str, cleaned_text: str, ocr_meta_json_str: str, doc_category: str):
    logger.info(f"[TASK_CHUNKING:{self.request.id}] Chunking for neo4j_doc_uuid: {neo4j_doc_uuid}")
    db_manager = get_managers()
    update_document_state(document_uuid, "chunking", "celery_started", {"task_id": self.request.id})
    
    try:
        ocr_meta_for_db = json.loads(ocr_meta_json_str) if ocr_meta_json_str else None
        
        # process_document_with_semantic_chunking already inserts chunks and updates their metadata
        # It returns: Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]
        # The first element is a list of chunk dicts that includes 'sql_id' and 'chunk_uuid'
        processed_chunks_list, document_structured_data = process_document_with_semantic_chunking(
            db_manager, neo4j_doc_sql_id, neo4j_doc_uuid, cleaned_text,
            ocr_meta_for_db, doc_category, use_structured_extraction=USE_STRUCTURED_EXTRACTION
        )
        
        if document_structured_data and USE_STRUCTURED_EXTRACTION:
            db_manager.update_neo4j_document_details(
                neo4j_doc_sql_id, metadata_json=document_structured_data
            )
        
        db_manager.update_neo4j_document_status(neo4j_doc_sql_id, "pending_ner")
        update_document_state(document_uuid, "chunking", "celery_completed", {"chunk_count": len(processed_chunks_list)})

        # Prepare data for NER task (list of chunk SQL IDs and UUIDs)
        # The NER task will then fetch chunk text itself from the DB.
        # Alternatively, pass all chunk texts if they are small enough and it simplifies NER task.
        # For robustness, passing IDs is better.
        chunk_ids_for_ner = [{"sql_id": c['sql_id'], "chunk_uuid": c['chunk_uuid'], "chunk_index": c['chunkIndex']} for c in processed_chunks_list]

        ner_task.delay(
            document_uuid=document_uuid,
            neo4j_doc_sql_id=neo4j_doc_sql_id,
            neo4j_doc_uuid=neo4j_doc_uuid,
            chunk_ids_for_ner=chunk_ids_for_ner
        )
    except Exception as exc:
        logger.error(f"[TASK_CHUNKING:{self.request.id}] Error: {exc}", exc_info=True)
        update_document_state(document_uuid, "chunking", "celery_failed", {"error": str(exc)})
        db_manager.update_neo4j_document_status(neo4j_doc_sql_id, "error_chunking")
        raise self.retry(exc=exc)


@app.task(bind=True, max_retries=3, default_retry_delay=60)
def ner_task(self, document_uuid: str, neo4j_doc_sql_id: int, neo4j_doc_uuid: str, chunk_ids_for_ner: list):
    logger.info(f"[TASK_NER:{self.request.id}] NER for neo4j_doc_uuid: {neo4j_doc_uuid}, chunks: {len(chunk_ids_for_ner)}")
    db_manager = get_managers()
    update_document_state(document_uuid, "ner", "celery_started", {"task_id": self.request.id})
    
    all_entity_mentions_for_doc = []
    try:
        for chunk_info in chunk_ids_for_ner:
            chunk_sql_id = chunk_info['sql_id']
            # Fetch chunk text
            chunk_record = db_manager.client.table('neo4j_chunks').select('text').eq('id', chunk_sql_id).maybe_single().execute()
            if not chunk_record.data or not chunk_record.data['text']:
                logger.warning(f"[TASK_NER:{self.request.id}] Skipping chunk SQL ID {chunk_sql_id} as text is missing.")
                continue
            
            chunk_text = chunk_record.data['text']
            mentions_in_chunk = extract_entities_from_chunk(chunk_text, chunk_info['chunk_index']) # Pass chunk_index
            
            for mention_attrs in mentions_in_chunk:
                em_sql_id, em_neo4j_uuid = db_manager.create_entity_mention_entry(
                    chunk_sql_id=chunk_sql_id, chunk_uuid=chunk_info['chunk_uuid'],
                    value=mention_attrs["value"], norm_value=mention_attrs["normalizedValue"],
                    display_value=mention_attrs.get("displayValue"), entity_type_label=mention_attrs["entity_type"],
                    rationale=mention_attrs.get("rationale"),
                    attributes_json_str=json.dumps(mention_attrs.get("attributes_json", {})),
                    phone=mention_attrs.get("phone"), email=mention_attrs.get("email"),
                    start_offset=mention_attrs.get("offsetStart"), end_offset=mention_attrs.get("offsetEnd")
                )
                if em_sql_id and em_neo4j_uuid:
                    mention_data_for_resolution = {**mention_attrs, 
                                                   "entity_mention_id_neo4j": em_neo4j_uuid,
                                                   "entity_mention_sql_id": em_sql_id,
                                                   "parent_chunk_id_neo4j": chunk_info['chunk_uuid'],
                                                   "chunk_index_int": chunk_info['chunk_index']}
                    all_entity_mentions_for_doc.append(mention_data_for_resolution)
        
        db_manager.update_neo4j_document_status(neo4j_doc_sql_id, "pending_canonicalization")
        update_document_state(document_uuid, "ner", "celery_completed", {"mention_count": len(all_entity_mentions_for_doc)})

        # Fetch full document text for resolution context
        doc_record = db_manager.client.table('neo4j_documents').select('cleaned_text_for_chunking').eq('id', neo4j_doc_sql_id).maybe_single().execute()
        full_cleaned_text = doc_record.data['cleaned_text_for_chunking'] if doc_record.data else ""

        resolution_task.delay(
            document_uuid=document_uuid,
            neo4j_doc_sql_id=neo4j_doc_sql_id,
            neo4j_doc_uuid=neo4j_doc_uuid,
            all_mentions_json_str=json.dumps(all_entity_mentions_for_doc), # Pass as JSON string
            full_document_text=full_cleaned_text
        )
    except Exception as exc:
        logger.error(f"[TASK_NER:{self.request.id}] Error: {exc}", exc_info=True)
        update_document_state(document_uuid, "ner", "celery_failed", {"error": str(exc)})
        db_manager.update_neo4j_document_status(neo4j_doc_sql_id, "error_ner")
        raise self.retry(exc=exc)

# ... Define resolution_task and relationship_task similarly ...
# resolution_task input: document_uuid, neo4j_doc_sql_id, neo4j_doc_uuid, all_mentions_json_str, full_document_text
# resolution_task output: chains to relationship_task with resolved_canonical_entities_json_str, updated_mentions_json_str

@app.task(bind=True, max_retries=3, default_retry_delay=60)
def resolution_task(self, document_uuid: str, neo4j_doc_sql_id: int, neo4j_doc_uuid: str, all_mentions_json_str: str, full_document_text: str):
    logger.info(f"[TASK_RESOLUTION:{self.request.id}] Resolution for neo4j_doc_uuid: {neo4j_doc_uuid}")
    db_manager = get_managers()
    update_document_state(document_uuid, "resolution", "celery_started", {"task_id": self.request.id})

    try:
        all_entity_mentions_for_doc = json.loads(all_mentions_json_str)
        
        resolved_canonicals_list, updated_mentions_list = resolve_document_entities(
            all_entity_mentions_for_doc, full_document_text
        )
        
        map_temp_canon_id_to_neo4j_uuid = {}
        final_canonical_entities_for_rels = []

        for ce_attrs_temp in resolved_canonicals_list:
            ce_sql_id, ce_neo4j_uuid = db_manager.create_canonical_entity_entry(
                neo4j_doc_sql_id=neo4j_doc_sql_id, document_uuid=neo4j_doc_uuid,
                canonical_name=ce_attrs_temp["canonicalName"], entity_type_label=ce_attrs_temp["entity_type"],
                aliases_json=ce_attrs_temp.get("allKnownAliasesInDoc_json"),
                mention_count=ce_attrs_temp.get("mention_count_in_doc", 1),
                first_seen_idx=ce_attrs_temp.get("firstSeenAtChunkIndex_int", 0)
            )
            if ce_sql_id and ce_neo4j_uuid:
                map_temp_canon_id_to_neo4j_uuid[ce_attrs_temp["canonicalEntityId_temp"]] = ce_neo4j_uuid
                final_canonical_entities_for_rels.append({**ce_attrs_temp, "canonicalEntityId": ce_neo4j_uuid}) # Use actual ID

        final_entity_mentions_for_rels = []
        for em_data_updated in updated_mentions_list:
            temp_canon_id = em_data_updated.get("resolved_canonical_id_temp")
            if temp_canon_id and temp_canon_id in map_temp_canon_id_to_neo4j_uuid:
                em_data_updated['resolved_canonical_id_neo4j'] = map_temp_canon_id_to_neo4j_uuid[temp_canon_id]
            final_entity_mentions_for_rels.append(em_data_updated)
            
        db_manager.update_neo4j_document_status(neo4j_doc_sql_id, "pending_relationships")
        update_document_state(document_uuid, "resolution", "celery_completed", {"canonical_count": len(final_canonical_entities_for_rels)})

        # For relationship task, we need doc details, project_uuid, chunks, mentions, canonicals
        # Fetch doc details
        doc_data_raw = db_manager.client.table('neo4j_documents').select('name, category, fileType, project_id').eq('id', neo4j_doc_sql_id).maybe_single().execute().data
        project_uuid_for_rels = db_manager.get_project_by_sql_id_or_global_project_id(doc_data_raw['project_id'], None)

        doc_data_for_rels = {
            "documentId": neo4j_doc_uuid, "sql_id": neo4j_doc_sql_id,
            "name": doc_data_raw['name'], "category": doc_data_raw['category'], "file_type": doc_data_raw['fileType']
        }
        # Fetch chunk UUIDs and indices
        chunks_raw = db_manager.client.table('neo4j_chunks').select('chunkId, chunkIndex').eq('document_id', neo4j_doc_sql_id).execute().data
        chunks_for_rels = [{"chunkId": c['chunkId'], "chunkIndex": c['chunkIndex']} for c in chunks_raw]

        relationship_task.delay(
            document_uuid=document_uuid, # source_doc_uuid
            doc_data_for_rels_json_str=json.dumps(doc_data_for_rels),
            project_uuid_for_rels=project_uuid_for_rels,
            chunks_for_rels_json_str=json.dumps(chunks_for_rels),
            final_mentions_json_str=json.dumps(final_entity_mentions_for_rels),
            final_canonicals_json_str=json.dumps(final_canonical_entities_for_rels)
        )
    except Exception as exc:
        logger.error(f"[TASK_RESOLUTION:{self.request.id}] Error: {exc}", exc_info=True)
        update_document_state(document_uuid, "resolution", "celery_failed", {"error": str(exc)})
        db_manager.update_neo4j_document_status(neo4j_doc_sql_id, "error_resolution")
        raise self.retry(exc=exc)


@app.task(bind=True, max_retries=3, default_retry_delay=60)
def relationship_task(self, document_uuid: str, doc_data_for_rels_json_str: str, project_uuid_for_rels: str, chunks_for_rels_json_str: str, final_mentions_json_str: str, final_canonicals_json_str: str):
    logger.info(f"[TASK_RELATIONSHIP:{self.request.id}] Relationships for source_doc_uuid: {document_uuid}")
    db_manager = get_managers()
    update_document_state(document_uuid, "relationships", "celery_started", {"task_id": self.request.id})

    doc_data_for_rels = json.loads(doc_data_for_rels_json_str)
    chunks_for_rels = json.loads(chunks_for_rels_json_str)
    final_entity_mentions_for_rels = json.loads(final_mentions_json_str)
    final_canonical_entities_for_rels = json.loads(final_canonicals_json_str)
    neo4j_doc_sql_id = doc_data_for_rels['sql_id'] # Get this from the passed data

    try:
        stage_structural_relationships(
            db_manager,
            doc_data_for_rels,
            project_uuid_for_rels,
            chunks_for_rels,
            final_entity_mentions_for_rels, # These need 'entityMentionId', 'chunk_uuid', 'resolved_canonical_id_neo4j'
            final_canonical_entities_for_rels # These need 'canonicalEntityId'
        )
        
        # Final updates
        # Fetch source_doc_sql_id if not directly available, e.g., from neo4j_document linked to document_uuid
        source_doc_info = db_manager.client.table('source_documents').select('id, raw_extracted_text').eq('document_uuid', document_uuid).maybe_single().execute().data
        if source_doc_info:
            db_manager.update_source_document_text(source_doc_info['id'], source_doc_info['raw_extracted_text'], status="completed")
        
        db_manager.update_neo4j_document_status(neo4j_doc_sql_id, "complete")
        update_document_state(document_uuid, "relationships", "celery_completed")
        logger.info(f"[TASK_RELATIONSHIP:{self.request.id}] Successfully processed document {document_uuid}")

    except Exception as exc:
        logger.error(f"[TASK_RELATIONSHIP:{self.request.id}] Error: {exc}", exc_info=True)
        update_document_state(document_uuid, "relationships", "celery_failed", {"error": str(exc)})
        db_manager.update_neo4j_document_status(neo4j_doc_sql_id, "error_relationships")
        raise self.retry(exc=exc)
```
*   **Agent Note:**
    *   Ensure all data passed between tasks is JSON serializable.
    *   `bind=True` allows access to `self` (the task instance) for retries, task ID, etc.
    *   Consider passing only necessary IDs between tasks and fetching data from the DB within each task to keep message payloads small and ensure tasks work with the freshest data. This example passes some data (like `cleaned_text`) for simplicity, but for very large texts, fetching from DB is better.
    *   Error handling in each task should update `update_document_state` and potentially the Supabase status for the document.
    *   The `update_document_state` calls are illustrative; integrate them properly.
    *   The `get_managers()` helper is a simple way to get DB access in tasks. For more complex apps, dependency injection might be used.

#### C. Modify Intake Service (`queue_processor.py`)

Your existing `QueueProcessor` will now be the "Intake Service."

1.  **Import Celery task:**
    ```python
    # queue_processor.py
    # ... other imports ...
    from .tasks import ocr_task # Assuming tasks.py is in the same directory or package
    ```

2.  **In `process_queue` (or `_process_claimed_documents`), instead of producing to Redis Stream, call the Celery task:**
    ```python
    # In QueueProcessor, after claiming a document `doc_to_process`
    # and getting `source_doc_sql_id`, `source_doc_uuid` etc.

                    logger.info(f"Enqueueing OCR task for document: {doc_to_process['file_name']} (Source SQL ID: {source_doc_sql_id})")
                    
                    # Call the first Celery task in the chain
                    ocr_task.delay(
                        document_uuid=str(doc_to_process['source_doc_uuid']),
                        source_doc_sql_id=source_doc_sql_id,
                        file_path=str(doc_to_process['file_path']),
                        file_name=str(doc_to_process['file_name']),
                        detected_file_type=str(doc_to_process['detected_file_type']),
                        project_sql_id=int(doc_to_process['project_sql_id'])
                    )
                    
                    # Update source_documents.initial_processing_status to indicate it's been queued in Celery
                    self.db_manager.update_processing_status('source_documents', source_doc_sql_id, 'ocr_celery_queued')
                    
                    # Release Redis lock for the Supabase queue item
                    try:
                        redis_mgr = get_redis_manager()
                        lock_key = f"queue:lock:{queue_id}" # queue_id is item['queue_id']
                        if redis_mgr.is_available() and redis_mgr.exists(lock_key):
                            redis_mgr.delete(lock_key)
                            logger.debug(f"Released Redis lock for Supabase queue item {queue_id} after Celery task enqueue.")
                    except Exception as e_lock_release:
                        logger.warning(f"Could not release Supabase queue item lock {queue_id}: {e_lock_release}")

                    # The Supabase `document_processing_queue` item's status ('completed' or 'failed')
                    # should be updated by a trigger when the final Celery task for the document
                    # updates `source_documents.initial_processing_status` to a terminal state.
    ```

#### D. Running Celery Workers

1.  **Open a terminal in your project's root directory.**
2.  **Start Celery worker(s):**
    ```bash
    celery -A your_project.celery_app worker -l INFO -P gevent -c 4
    ```
    *   `your_project.celery_app`: Path to your Celery app instance (e.g., `nlp_pipeline_project.celery_app` if `celery_app.py` is in a package `nlp_pipeline_project`). Adjust based on your project structure. If `celery_app.py` is in the root and tasks are in `tasks.py` (also root), and `CELERY_INCLUDE_MODULES=['tasks']`, then `-A celery_app` might work if `celery_app.py` is in PYTHONPATH.
    *   `-l INFO`: Log level.
    *   `-P gevent`: Use gevent for concurrency (good for I/O-bound tasks). Other options: `eventlet`, `prefork` (default), `solo` (for debugging).
    *   `-c 4`: Number of concurrent worker processes/threads (adjust based on CPU cores and task nature).

    **Agent Note:** If your task modules are not automatically discovered, you might need to adjust `PYTHONPATH` or how you specify the app (`-A`). For example, if `celery_app.py` is at the top level and your tasks are in `app/tasks.py`, then include might be `['app.tasks']` and you run from the directory *above* `app`.

#### E. Running the Intake Service

Your `queue_processor.py` (now the Intake Service) will run as a separate process:
```bash
python queue_processor.py --batch-size 10
```
(Or however you were running it before).

#### F. Monitoring with Flower (Optional but Highly Recommended)

1.  **Install Flower:**
    ```bash
    pip install flower
    ```
2.  **Run Flower:**
    ```bash
    celery -A your_project.celery_app flower --port=5555 --broker=${CELERY_REDIS_URL}
    ```
    (Replace `your_project.celery_app` and `${CELERY_REDIS_URL}` accordingly).
    Access Flower UI at `http://localhost:5555`.

### IV. Impact on Existing Redis Usage

*   **Queuing:** Celery takes over this, using Redis Lists internally (by default) for its broker. You no longer need the custom Redis Stream producer/consumer logic *for inter-service task passing*.
*   **Caching (`redis_cache`):** Remains unchanged and highly beneficial.
*   **Distributed Locking (`with_redis_lock`, `setnx` for Supabase queue items):** The lock for Supabase queue items in `QueueProcessor` is still essential. General distributed locks can also remain.
*   **Rate Limiting (`rate_limit`):** Remains unchanged and useful for external API calls within Celery tasks.
*   **State Persistence (`update_document_state`):** This can still be used. Celery provides task-level state, but your custom `update_document_state` offers a more application-specific view of the document's journey across multiple Celery tasks. You can log Celery task IDs within this state.

### V. Redis Configuration with `redis-cli`

The Redis configuration steps outlined previously (maxmemory, AOF, etc.) are still valid and recommended for a production Redis instance serving as a Celery broker and cache. Celery itself doesn't require special Redis server-side configuration beyond what's good for a general-purpose Redis.

---

This Celery-based approach provides a much more robust, scalable, and maintainable solution for your NLP pipeline's task management. It requires a significant refactor but leverages a mature, widely-used library for many complex aspects of distributed task processing.