Okay, this is a great goal. Leveraging Redis effectively can significantly boost both idempotency and efficiency. Let's break down how to achieve this, focusing on your desire to persist data through the pipeline for in-memory entity resolution.

**Core Principles for Optimization:**

1.  **Idempotency through State & Output Caching:**
    *   If a task (or a stage within a task) has already run successfully for a given input/version, its output should be available in Redis. Subsequent runs can fetch this output and skip re-computation.
    *   Use locks (`CacheKeys.DOC_PROCESSING_LOCK`) to prevent concurrent processing of the same document, or specific critical sections.

2.  **Efficiency through Cached Intermediate Results:**
    *   Each significant processing stage (OCR, chunking, entity extraction) should write its primary output to Redis.
    *   Subsequent stages read their inputs from Redis. This reduces DB load and avoids re-fetching/re-computing.

3.  **Atomic Updates & State Management:**
    *   Use Redis hashes (`CacheKeys.DOC_STATE`) to track the progress of a document through various micro-stages within a Celery task.
    *   Update database status (`source_documents.celery_status`, `neo4j_documents.processingStatus`) at the beginning and end of Celery tasks, or upon successful completion of major internal stages.

4.  **Data Flow via Redis (for your "in-memory entity resolution" goal):**
    *   **OCR Output:** Store full extracted text in Redis.
    *   **Chunking Output:** Store a list of chunk IDs/UUIDs and perhaps the text of each chunk (if not too large and frequently re-read).
    *   **Entity Extraction Output:** For *all* chunks of a document, aggregate the extracted entity mentions and store them in Redis under a single key for the document.
    *   **Entity Resolution Input:** The resolution task will then load the full text and *all* aggregated entity mentions for the document directly from Redis, perform resolution, and then write its output (canonical entities, updated mentions) back to Redis.
    *   **Graph Building Input:** The graph task loads resolved entities, chunks, etc., from Redis.

**Detailed Changes and Optimizations:**

**1. Cache Key Strategy (Refinement of `CacheKeys.py`):**

You have a good `CacheKeys.py`. We'll add a few or ensure existing ones are used consistently for pipeline flow:

*   `CacheKeys.DOC_OCR_RESULT`: Already there. Value: JSON `{ "text": "full_ocr_text", "metadata": {...} }`
*   `CacheKeys.DOC_CHUNKS_LIST`: **New/Refined**. Value: JSON list of chunk UUIDs/IDs `["uuid1", "uuid2", ...]`.
*   `CacheKeys.DOC_CHUNK_TEXT`: **New/Refined**. `doc:chunk_text:{chunk_uuid}`. Value: Raw text of the chunk. (Optional, if chunks are large and re-reading from DB for NER is slow).
*   `CacheKeys.DOC_ALL_EXTRACTED_MENTIONS`: **New Key**. `doc:all_mentions:{document_uuid}`. Value: JSON list of all entity mention dicts extracted from all chunks of the document.
*   `CacheKeys.DOC_CANONICAL_ENTITIES`: **New Key**. `doc:canonical_entities:{document_uuid}`. Value: JSON list of canonical entity dicts created by the resolution step.
*   `CacheKeys.DOC_RESOLVED_MENTIONS`: **New Key**. `doc:resolved_mentions:{document_uuid}`. Value: JSON list of entity mentions updated with their `resolved_canonical_id_neo4j`.

**2. Task Modifications:**

   **`ocr_tasks.py` (`process_ocr`):**
   *   **Idempotency Check:**
        *   At the start, check `CacheKeys.DOC_OCR_RESULT` for `document_uuid`. If exists (and not `force_reprocess`), retrieve it and pass it to the next task directly, mark OCR as 'skipped_cached'.
        *   If `source_documents.celery_status` is already `ocr_complete` or further, consider skipping.
   *   **Output Caching:**
        *   On successful OCR, store `raw_text` and `ocr_meta` in `CacheKeys.DOC_OCR_RESULT.format(document_uuid=document_uuid)`.
        *   TTL: `REDIS_OCR_CACHE_TTL`.
   *   **State Update:** Continue using `update_document_state(document_uuid, "ocr", "completed", ...)`.
   *   **Next Task Call:** Pass `document_uuid`, `source_doc_sql_id`, `project_sql_id`, `file_name`, `detected_file_type`. `raw_text` and `ocr_meta_json` can be implicitly retrieved by the next task from Redis using `document_uuid`. Or, pass a flag indicating successful cache of OCR results.

   **`text_tasks.py` (`create_document_node`):**
   *   **Input:** Receives `document_uuid`, etc.
   *   **Fetch OCR Result:** Load `raw_text` and `ocr_meta` from `CacheKeys.DOC_OCR_RESULT.format(document_uuid=document_uuid)`.
   *   **Idempotency:** `idempotent_ops.upsert_neo4j_document` is good.
   *   **Output:** `cleaned_text`, `doc_category`, `neo4j_doc_uuid`, `neo4j_doc_sql_id`.
   *   **Caching:**
        *   Cache `cleaned_text` and `doc_category` if computation is significant: `doc:cleaned_text:{document_uuid}` and `doc:category:{document_uuid}`.
   *   **Next Task Call:** Pass `document_uuid`, `neo4j_doc_sql_id`, `neo4j_doc_uuid`, `source_doc_sql_id`. `cleaned_text`, `ocr_meta_json`, `doc_category` can be fetched from Redis by the next task.

   **`text_tasks.py` (`process_chunking`):**
   *   **Input:** Receives `document_uuid`, `neo4j_doc_sql_id`, etc.
   *   **Fetch Inputs:** Load `cleaned_text`, `ocr_meta`, `doc_category` from Redis using `document_uuid`.
   *   **Idempotency:** Relies on `idempotent_ops.upsert_chunk` through `process_and_insert_chunks`. If reprocessing, `clear_chunks_for_document` should be called first (perhaps by `cleanup_document_for_reprocessing` task).
   *   **Output Caching:**
        *   After `process_and_insert_chunks` (or `process_document_with_semantic_chunking`), store:
            *   A list of chunk UUIDs/SQL_IDs: `CacheKeys.DOC_CHUNKS_LIST.format(document_uuid=document_uuid)`.
            *   Optionally, text for each chunk: `CacheKeys.DOC_CHUNK_TEXT.format(chunk_uuid=chunk['chunk_uuid'])` (value: chunk text).
        *   If `document_structured_data` is produced, cache it: `CacheKeys.DOC_STRUCTURED.format(document_uuid=document_uuid, chunk_id='document_level')`.
   *   **Next Task Call:** Pass `document_uuid`, `source_doc_sql_id`, `neo4j_doc_sql_id`, `neo4j_doc_uuid`. The `chunk_data` (list of chunk dicts {sql_id, chunk_uuid, chunk_index}) should be passed directly if not too large, or store it in Redis and pass the key. For now, direct passing is in your code.

   **`entity_tasks.py` (`extract_entities`):**
   *   **Input:** Receives `document_uuid`, `chunk_data` (list of dicts).
   *   **Fetch Chunk Texts:** If `DOC_CHUNK_TEXT` is cached, use it. Otherwise, fetch from DB (as currently done).
   *   **Idempotency/Caching:** `extract_entities_from_chunk` (which calls `extract_entities_openai` or `extract_entities_local_ner`) already uses `@redis_cache` for *individual chunk* entity extraction results. This is good.
   *   **Output Aggregation & Caching:**
        *   After processing all chunks, `all_entity_mentions` (list of dicts) is created.
        *   Store this *entire list* in Redis: `CacheKeys.DOC_ALL_EXTRACTED_MENTIONS.format(document_uuid=document_uuid)`.
   *   **Next Task Call:** Pass `document_uuid`, `source_doc_sql_id`, `neo4j_doc_sql_id`, `neo4j_doc_uuid`. `entity_mentions` and `full_document_text` will be fetched from Redis by the resolution task.

   **`entity_tasks.py` (`resolve_entities`):**
   *   **Input:** Receives `document_uuid`, etc.
   *   **Fetch Inputs (CRUCIAL FOR YOUR GOAL):**
        *   Load `all_entity_mentions` from `CacheKeys.DOC_ALL_EXTRACTED_MENTIONS.format(document_uuid=document_uuid)`.
        *   Load `full_document_text` (actually, `cleaned_text`) from `doc:cleaned_text:{document_uuid}` or, if not cached there, from `CacheKeys.DOC_OCR_RESULT.format(document_uuid=document_uuid)` (then extract text and clean).
   *   **Idempotency/Caching:** `resolve_document_entities` already uses a cache key based on its inputs. This remains valid.
   *   **Output Caching:**
        *   After resolution, store `resolved_canonicals_list` in `CacheKeys.DOC_CANONICAL_ENTITIES.format(document_uuid=document_uuid)`.
        *   Store `updated_mentions_list` (which now includes `resolved_canonical_id_neo4j`) in `CacheKeys.DOC_RESOLVED_MENTIONS.format(document_uuid=document_uuid)`.
   *   **Next Task Call:** Pass `document_uuid`, `source_doc_sql_id`, `doc_data` (containing `neo4j_doc_uuid`, etc.), `project_uuid`. Other inputs (`chunks`, `entity_mentions`, `canonical_entities`) will be fetched from Redis by the graph task.

   **`graph_tasks.py` (`build_relationships`):**
   *   **Input:** Receives `document_uuid`, `doc_data` (with `neo4j_doc_uuid`), `project_uuid`.
   *   **Fetch Inputs from Redis:**
        *   Load chunk list from `CacheKeys.DOC_CHUNKS_LIST.format(document_uuid=neo4j_doc_uuid or source_doc_uuid)`. The task currently receives `chunks_for_rels` (a list of dicts {chunkId, chunkIndex}). This is fine if passed directly.
        *   Load *resolved* entity mentions from `CacheKeys.DOC_RESOLVED_MENTIONS.format(document_uuid=neo4j_doc_uuid or source_doc_uuid)`.
        *   Load canonical entities from `CacheKeys.DOC_CANONICAL_ENTITIES.format(document_uuid=neo4j_doc_uuid or source_doc_uuid)`.
   *   **Idempotency:** Staging relationships usually involves inserting into `neo4j_relationships_staging`. If reprocessing, old relationships for this document need to be cleared first (handled by `cleanup_document_for_reprocessing`). The `batchProcessId` can also help differentiate reprocessing attempts if needed.

**3. Reprocessing and Cache Invalidation (`cleanup_tasks.py`):**

*   `cleanup_document_for_reprocessing`:
    *   When cleaning stages, **crucially**, it must also invalidate the corresponding Redis caches for that `document_uuid`.
    *   Use `redis_mgr.invalidate_document_cache(document_uuid)` (from `redis_utils.py`, which uses `CacheKeys.get_all_document_patterns`).
    *   If `preserve_ocr` is true, explicitly *do not* delete `CacheKeys.DOC_OCR_RESULT`.
    *   Ensure it clears the new aggregate keys: `DOC_CHUNKS_LIST`, `DOC_ALL_EXTRACTED_MENTIONS`, `DOC_CANONICAL_ENTITIES`, `DOC_RESOLVED_MENTIONS`.
    *   The `processing_version` increment in `source_documents` is a good mechanism. You can incorporate this version into cache keys if you need to keep historical processed data, e.g., `doc:ocr_result:{document_uuid}:v{version}`. For now, simple invalidation is fine.

**4. TTL Management:**

*   Review `REDIS_*_CACHE_TTL` values in `config.py`.
*   `DOC_OCR_RESULT`: Can have a long TTL (e.g., 7 days, as set).
*   Intermediate results like `DOC_CHUNKS_LIST`, `DOC_ALL_EXTRACTED_MENTIONS`: TTL could be shorter (e.g., 1-2 days) as they are transient states if the pipeline completes.
*   `DOC_CANONICAL_ENTITIES`, `DOC_RESOLVED_MENTIONS`: Similar to above, or slightly longer if these are end-products often queried.
*   `DOC_STATE`: 7 days is fine.
*   Locks: `REDIS_LOCK_TIMEOUT` (e.g., 5-10 minutes) for processing lock.

**5. `idempotent_ops.py` & `processing_state.py`:**

*   These are good utilities. `IdempotentDatabaseOps` handles DB-level upserts.
*   `ProcessingStateManager` provides a higher-level abstraction for stage tracking, which is good. The individual tasks also update `celery_status` in `source_documents`. Ensure these are consistent. The `celery_status` in the DB is the "master" status for external observers, while Redis `DOC_STATE` can hold more granular, transient state.

**Summary of Code Changes (Conceptual):**

*   **Celery Tasks:**
    *   Modify input arguments: Primarily pass `document_uuid` and other essential IDs.
    *   Add logic at the start of tasks to fetch necessary data from Redis using `document_uuid`.
    *   Add logic at the end of tasks to store their primary outputs to Redis using `document_uuid`.
    *   Implement idempotency checks (e.g., check if output already exists in Redis for the current version).
*   **`CacheKeys.py`:**
    *   Add `DOC_CHUNKS_LIST`, `DOC_CHUNK_TEXT` (optional), `DOC_ALL_EXTRACTED_MENTIONS`, `DOC_CANONICAL_ENTITIES`, `DOC_RESOLVED_MENTIONS`.
    *   Ensure `get_all_document_patterns` in `CacheKeys` includes these new keys for comprehensive invalidation.
*   **`redis_utils.py` (`invalidate_document_cache`):**
    *   Ensure it uses `CacheKeys.get_all_document_patterns` correctly to clear all relevant keys.
*   **`cleanup_tasks.py` (`cleanup_document_for_reprocessing`):**
    *   Integrate robust Redis cache invalidation, respecting `preserve_ocr`.
*   **Error Handling:** If a task fails and retries, it should ideally be able to pick up from the last successfully cached intermediate result.

**Example: `entity_tasks.py - resolve_entities` (Conceptual Modification)**

```python
# entity_tasks.py

# ... imports ...
from scripts.config import REDIS_ENTITY_CACHE_TTL # For the function's own cache

@app.task(bind=True, base=EntityTask, ...)
def resolve_entities(self, document_uuid: str, source_doc_sql_id: int,
                    neo4j_doc_sql_id: int, neo4j_doc_uuid: str
                    # REMOVED: entity_mentions, full_document_text from direct args
                    ) -> Dict[str, Any]:
    logger.info(f"[RESOLUTION_TASK:{self.request.id}] Resolving entities for document {neo4j_doc_uuid}")
    update_document_state(document_uuid, "resolution", "started", {"task_id": self.request.id})

    redis_mgr = get_redis_manager()
    if not redis_mgr or not redis_mgr.is_available():
        raise ConnectionError("Redis is not available for fetching inputs.")

    # Fetch inputs from Redis
    try:
        # 1. Get all extracted mentions for the document
        all_mentions_key = CacheKeys.format_key(CacheKeys.DOC_ALL_EXTRACTED_MENTIONS, document_uuid=document_uuid)
        entity_mentions = redis_mgr.get_cached(all_mentions_key)
        if not entity_mentions:
            logger.error(f"No cached entity mentions found for {document_uuid} at {all_mentions_key}")
            # Fallback: try to get from DB if the previous task somehow failed to cache
            # This adds complexity, ideally the previous task *must* cache.
            # For now, let's assume the cache must exist.
            raise ValueError(f"Cached entity mentions not found for {document_uuid}")

        # 2. Get full document text (cleaned version)
        # Option A: if cleaned_text was cached by create_document_node
        cleaned_text_key = f"doc:cleaned_text:{document_uuid}" # Assuming this key was used
        full_document_text = redis_mgr.get_cached(cleaned_text_key)
        if not full_document_text:
            # Option B: Fallback to OCR result text
            ocr_result_key = CacheKeys.format_key(CacheKeys.DOC_OCR_RESULT, document_uuid=document_uuid)
            ocr_data = redis_mgr.get_cached(ocr_result_key)
            if not ocr_data or 'text' not in ocr_data:
                raise ValueError(f"Cached OCR text not found for {document_uuid}")
            full_document_text = clean_extracted_text(ocr_data['text']) # Re-clean if needed
            # Optionally cache this cleaned_text now
            redis_mgr.set_cached(cleaned_text_key, full_document_text, ttl=REDIS_ENTITY_CACHE_TTL)


    except Exception as e:
        logger.error(f"Failed to fetch inputs from Redis for resolution task: {e}")
        raise # Propagate error to Celery for retry

    # ... (rest of the existing resolve_entities logic using fetched entity_mentions and full_document_text) ...
    # ... resolve_document_entities call ...

    # After resolution:
    # resolved_canonicals_list, updated_mentions_list = ...

    # Cache the outputs
    try:
        canonical_key = CacheKeys.format_key(CacheKeys.DOC_CANONICAL_ENTITIES, document_uuid=document_uuid)
        redis_mgr.set_cached(canonical_key, resolved_canonicals_list, ttl=REDIS_ENTITY_CACHE_TTL)

        resolved_mentions_key = CacheKeys.format_key(CacheKeys.DOC_RESOLVED_MENTIONS, document_uuid=document_uuid)
        redis_mgr.set_cached(resolved_mentions_key, updated_mentions_list, ttl=REDIS_ENTITY_CACHE_TTL)
    except Exception as e:
        logger.warning(f"Failed to cache resolution outputs for {document_uuid}: {e}")

    # ... chain to graph_tasks.build_relationships, passing only IDs.
    # build_relationships will then fetch its inputs from these new Redis keys.
    # ...
```

By making these kinds of changes system-wide, you'll achieve a more robust, efficient, and idempotent pipeline where Redis acts as a high-speed intermediary data layer, fulfilling your goal of "in-memory" access for stages like entity resolution. Remember to thoroughly test after these changes.