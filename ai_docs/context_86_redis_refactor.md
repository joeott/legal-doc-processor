
Hello Claude,

I need your expertise to refactor an existing Python-based "Legal Document Processing Pipeline" by integrating a Redis layer. A reference repositiory is locatd at /Users/josephott/Documents/phase_1_2_3_process_v5/resources/redis-py. 


**Primary Goal:**
Introduce Redis to enhance the pipeline's performance, robustness, and scalability, specifically focusing on:
1.  **Caching:** Reduce redundant computations and API calls.
2.  **Subprocess Control & Distributed Coordination:** Manage tasks, prevent race conditions, and enable better scaling of workers.
3.  **Data Validity & Idempotency:** Ensure data consistency and allow safe retries of operations.
4.  **Script Independence & Decoupling:** Lay the groundwork for potentially breaking down the pipeline into more independent, loosely coupled services or scripts.

**System Description:**
```
Read CLAUDE.md
```

**Specific Redis Functionalities to Implement:**

Based on the system description, please provide detailed refactoring suggestions, including potential Python code snippets (using a library like `redis-py`) and identify the best modules/functions within the existing codebase to implement these Redis-based features.

**1. Caching Strategies:**
    *   **OCR Results:**
        *   **Where:** `ocr_extraction.py` (specifically around `extract_text_from_pdf_textract` and local OCR functions like `extract_text_from_pdf_qwen_vl_ocr`).
        *   **How:** Cache the extracted raw text. Key could be `doc_uuid:<document_uuid>:ocr_text` or a hash of the input file if feasible. Consider cache expiration.
        *   **Benefit:** Avoid re-running expensive Textract jobs or local OCR for unchanged documents.
    *   **LLM Responses (Structured Extraction, Entity Extraction, Entity Resolution):**
        *   **Where:** `structured_extraction.py` (within `_extract_with_openai`, `_extract_with_qwen`), `entity_extraction.py` (within `extract_entities_openai`), `entity_resolution.py` (within `resolve_document_entities`).
        *   **How:** Cache the JSON response from the LLM. Key could be `llm_cache:<model_name>:<hash_of_prompt_or_input_text>`.
        *   **Benefit:** Significantly reduce costs and latency for repeated LLM calls with identical inputs.
    *   **Chunk-level Extractions:**
        *   **Where:** After entity extraction in `main_pipeline.py` (Phase 3) or within `text_processing.py` if structured extraction is done per chunk there.
        *   **How:** Cache the list of extracted entities or structured data for a given chunk ID/hash. Key: `chunk:<chunk_uuid>:entities` or `chunk:<chunk_uuid>:structured_data`.
        *   **Benefit:** Faster reprocessing if only downstream tasks like resolution or relationship building need to be redone.
    *   **Database Query Caching (Supabase):**
        *   **Where:** Potentially wrap some read-heavy `SupabaseManager` methods in `supabase_utils.py`.
        *   **How:** Cache results of frequently accessed, rarely changing data (e.g., project details, specific document metadata if read multiple times).
        *   **Benefit:** Reduce load on Supabase and speed up internal lookups.

**2. Subprocess Control & Distributed Coordination:**
    *   **Queue Item Claiming (`queue_processor.py`):**
        *   **How:** Use Redis `SETNX` or a similar atomic operation to claim `source_document_id` or `queue_id` before database update. This can make claiming faster and more robust than relying solely on DB transactionality for high concurrency. Key: `lock:queue_item:<queue_id>`.
        *   **Benefit:** Improved efficiency and reliability in distributed queue worker scenarios.
    *   **Textract Job Polling (`textract_utils.py`):**
        *   **How:** If SNS is not used or as a supplementary mechanism, Redis could store Textract `job_id` status. A separate poller script could update Redis, and `get_text_detection_results` could primarily check Redis before making an API call.
        *   **Benefit:** Decouple Textract polling from the main processing thread, potentially reducing direct AWS API calls from many workers.
    *   **Rate Limiting for External APIs (OpenAI, AWS Textract):**
        *   **Where:** Before calls in `structured_extraction.py`, `entity_extraction.py`, `entity_resolution.py`, `textract_utils.py`.
        *   **How:** Implement a sliding window rate limiter using Redis counters and sorted sets.
        *   **Benefit:** Prevent API throttling and manage costs effectively.

**3. Data Validity & Idempotency:**
    *   **Document Processing State Tracking:**
        *   **How:** Use Redis Hashes to track the completion status of major pipeline stages for each document. E.g., `HSET doc_state:<document_uuid> ocr_completed 1`, `HSET doc_state:<document_uuid> chunking_completed 1`.
        *   **Where:** Update these states at the end of each phase in `main_pipeline.process_single_document`.
        *   **Benefit:** Allows for easier resumption of failed pipelines, ensures steps are not skipped, and provides a quick way for `health_check.py` or `recover_stuck_documents.py` to assess progress.
    *   **Input Data Hashing for Reprocessing:**
        *   **How:** Before OCR or other expensive steps, store a hash of the input file (if local) or S3 ETag in Redis. If the hash/ETag matches a previously processed one, consider using cached results. Key: `file_hash:<md5_or_sha256_of_file_content_or_s3_etag> -> document_uuid_or_ocr_cache_key`.
        *   **Benefit:** Avoid reprocessing identical files even if they are submitted under a new ID.
    *   **Idempotency for Database Writes:**
        *   **How:** For critical writes (e.g., creating canonical entities), generate an idempotency key, check Redis if it's been processed. If not, perform the operation and store the key in Redis with a TTL.
        *   **Benefit:** Safe retries for operations that should only occur once, especially relevant with queue-based retries.

**4. Script Independence & Decoupling (More Advanced Refactoring):**
    *   **Message Bus for Pipeline Stages:**
        *   **How:** Instead of `main_pipeline.process_single_document` calling functions sequentially, each major stage (OCR, Chunking, Entity Extraction, etc.) could become an independent worker/script.
            *   OCR worker: Consumes `new_document` messages from a Redis Stream/List, performs OCR, publishes `ocr_completed` message with text (or pointer to text) to another Stream/List.
            *   Chunking worker: Consumes `ocr_completed`, performs chunking, publishes `chunking_completed` with chunk details.
            *   And so on for other stages.
        *   **Benefit:** True decoupling, independent scaling of stages, improved resilience (one stage failing doesn't halt others directly). This is a larger architectural change.
    *   **Centralized Document Status/Progress via Redis:**
        *   **How:** As mentioned in "Data Validity," use Redis Hashes or simple keys to store the current processing stage and status of each document. This would be the "source of truth" for progress, queryable by any component.
        *   **Benefit:** Allows `health_check.py` and `recover_stuck_documents.py` to get faster, more direct status updates without solely relying on Supabase queries.

**Request for You, Claude:**

1.  **Identify Key Integration Points:** For each of the Redis functionalities listed above, pinpoint the most suitable Python files, classes, and functions in the provided codebase where these integrations should occur.
2.  **Provide Code Examples:** Offer illustrative Python code snippets (using `redis-py`) for implementing these Redis patterns (e.g., a caching decorator, a lock context manager, publishing to a Redis Stream).
3.  **Data Structures for Redis:** Suggest appropriate Redis data structures (Hashes, Sets, Lists, Streams, simple Keys) for each use case.
4.  **Configuration:** How should Redis connection details be managed within `config.py`?
5.  **Impact on Existing Logic:** Discuss how integrating Redis might change the existing data flow, error handling, and interactions with Supabase (e.g., when to read from cache vs. DB, how locks affect queue claiming).
6.  **Consider Deployment Stages:** How might the use of Redis differ or need to be conditional based on the `DEPLOYMENT_STAGE`? (e.g., local Redis for dev, Elasticache for cloud).
7.  **Testing Considerations:** Briefly mention how one might test the Redis-integrated components.

I'm looking for a practical and detailed refactoring plan. Thank you!
```

## Top 15 Documentation Examples/Guides for Redis Integration in Python

Here are some URLs that provide good documentation and examples for the kind of Redis integration you're looking to do:

1.  **Redis-Py (Official Client Library)**
    *   URL: [https://redis-py.readthedocs.io/en/stable/](https://redis-py.readthedocs.io/en/stable/)
    *   Why: Essential for any Python-Redis interaction. Covers all commands and connection pooling.

2.  **Redis Caching Patterns with Python**
    *   URL: [https://redis.io/docs/latest/develop/use/patterns/caching/](https://redis.io/docs/latest/develop/use/patterns/caching/) (Official Redis Docs, conceptual)
    *   Why: Explains general caching strategies like read-through, write-through, cache-aside which are language-agnostic but crucial.
    *   Python specific example: [https://realpython.com/caching-in-python-with-redis/](https://realpython.com/caching-in-python-with-redis/)

3.  **Implementing a Cache-Aside Pattern in Python with Redis**
    *   URL: (Often found in blog posts, e.g., a search for "python redis cache aside pattern") A good example: [https://testdriven.io/blog/caching-django-redis/](https://testdriven.io/blog/caching-django-redis/) (Django context, but pattern is general)
    *   Why: Practical guide for a common and effective caching strategy.

4.  **Distributed Locks with Redis**
    *   URL: [https://redis.io/docs/latest/develop/use/patterns/distributed-locks/](https://redis.io/docs/latest/develop/use/patterns/distributed-locks/)
    *   Why: Official documentation on implementing distributed locks using Redlock algorithm or simpler single-instance SETNX. Essential for subprocess control.
    *   Python `redis-py` lock implementation: [https://redis-py.readthedocs.io/en/stable/lock.html](https://redis-py.readthedocs.io/en/stable/lock.html)

5.  **Using Redis for Task Queues in Python (Conceptual & RQ library)**
    *   URL: [https://python-rq.org/](https://python-rq.org/) (RQ - Redis Queue library)
    *   URL: [https://testdriven.io/blog/asynchronous-tasks-with-django-and-redis-queue/](https://testdriven.io/blog/asynchronous-tasks-with-django-and-redis-queue/) (RQ example)
    *   Why: While you have a Supabase queue, understanding how Redis is used for robust task queues can inform decoupling efforts or enhance your current queue.

6.  **Rate Limiting with Redis in Python**
    *   URL: [https://redis.io/docs/latest/develop/use/patterns/rate-limiting/](https://redis.io/docs/latest/develop/use/patterns/rate-limiting/) (Generic patterns)
    *   URL: [https://redislabs.com/blog/5-ways-to-implement-api-rate-limiting-with-redis/](https://redislabs.com/blog/5-ways-to-implement-api-rate-limiting-with-redis/) (Redis Labs blog with examples)
    *   Why: Directly applicable for managing calls to external APIs like OpenAI/Textract.

7.  **Redis Streams Introduction**
    *   URL: [https://redis.io/docs/latest/develop/data-types/streams/](https://redis.io/docs/latest/develop/data-types/streams/)
    *   Why: For the "Script Independence & Decoupling" goal, Redis Streams are a powerful way to build a message bus.

8.  **Using Redis Streams in Python**
    *   URL: [https://redis-py.readthedocs.io/en/stable/examples/streams_example.html](https://redis-py.readthedocs.io/en/stable/examples/streams_example.html)
    *   Why: Practical `redis-py` examples for producing and consuming messages with Streams.

9.  **Idempotency Keys with Redis**
    *   URL: (Often found in API design blogs, search "api idempotency key redis") Example: [https://blog.bearer.com/api-idempotency/](https://blog.bearer.com/api-idempotency/) (Conceptual, but applicable)
    *   Why: Explains the pattern for ensuring operations can be safely retried.

10. **Building a Leaderboard with Redis (Uses Sorted Sets)**
    *   URL: [https://redis.io/docs/latest/develop/use/patterns/leaderboards/](https://redis.io/docs/latest/develop/use/patterns/leaderboards/)
    *   Why: While not directly a leaderboard, it showcases Sorted Sets, which are useful for managing items with scores/timestamps (e.g., for prioritized queues or time-based event processing).

11. **Redis Pub/Sub**
    *   URL: [https://redis.io/docs/latest/develop/interact/pubsub/](https://redis.io/docs/latest/develop/interact/pubsub/)
    *   URL: [https://redis-py.readthedocs.io/en/stable/examples/pubsub_example.html](https://redis-py.readthedocs.io/en/stable/examples/pubsub_example.html)
    *   Why: Simpler messaging than Streams for certain decoupling scenarios, like broadcasting status updates.

12. **Redis Hashes for Storing Objects**
    *   URL: [https://redis.io/docs/latest/develop/data-types/hashes/](https://redis.io/docs/latest/develop/data-types/hashes/)
    *   Why: Useful for storing structured data like document processing states (`doc_state:<doc_id> field value`).

13. **Best Practices for Redis with Python**
    *   URL: (Often found in blogs or talks) Search for "python redis best practices". Example: [https://www.section.io/engineering-education/redis-py-python-redis-part-2/](https://www.section.io/engineering-education/redis-py-python-redis-part-2/) (Covers connection pooling, pipelines).
    *   Why: General tips for efficient and correct Redis usage.

14. **Error Handling and Retries with Redis-Py**
    *   URL: Check `redis-py` documentation for `redis.exceptions` and recommended retry logic for transient network issues. (The library itself handles some retries on connections).
    *   Why: Important for building robust applications.

15. **Designing Data Structures in Redis**
    *   URL: [https://redis.com/ebook/part-2-core-concepts/chapter-6-designing-data-structures/](https://redis.com/ebook/part-2-core-concepts/chapter-6-designing-data-structures/) (From Redis University / Redis Whitepaper)
    *   Why: Good overview of how to think about modeling your data effectively in Redis for various use cases.

This should give Claude (and you!) a solid foundation for the refactoring task. Remember that integrating Redis effectively often involves thinking about data access patterns, consistency requirements, and the specific bottlenecks you're trying to solve.