Okay, this is a comprehensive request! Generating a detailed, itemized, sequential task list for unit tests across this entire codebase will be extensive. The goal is to provide clear instructions for an agentic coding tool to create and verify these tests.

**General Instructions for the Agentic Coding Tool:**

1.  **Testing Framework:** Use `pytest` as the primary testing framework.
2.  **Mocking:** Use `unittest.mock.patch` (or `pytest-mock`) for all external dependencies (APIs, database calls, file system interactions, environment variables, and other modules/classes where appropriate).
3.  **Fixtures:** Utilize `pytest` fixtures for setting up common test data, mock objects, and configurations.
4.  **Pydantic Validation:** For functions that accept or return Pydantic models, ensure tests cover both valid and invalid model states to verify Pydantic's validation.
5.  **Coverage:** Aim for high test coverage. Each logical path, conditional branch, and error handling mechanism should be tested.
6.  **Clarity:** Each test case should be atomic and test one specific aspect of the function or method.
7.  **Assertions:** Use specific `pytest` assertions (e.g., `assert isinstance`, `assert_called_once_with`, `raises`).
8.  **Idempotency:** Ensure tests are idempotent and do not depend on the state left by previous tests.
9.  **Temp Files/Dirs:** Use `tmp_path` fixture from `pytest` for tests involving file system operations.
10. **Environment Variables:** Mock `os.getenv` to control configuration values during tests.
11. **Logging:** Verify that appropriate logging messages (info, warning, error) are emitted when expected. Use `caplog` fixture.
12. **Parameterization:** Use `pytest.mark.parametrize` for testing multiple input variations for the same logic.

---

**Sequential Task List for Unit Test Generation**

**File: `image_processing.py`**

1.  **`ImageProcessingConfig` Pydantic Model Tests:**
    1.  [ ] Task: Test successful instantiation with valid API key and other fields.
    2.  [ ] Task: Test `api_key` validator:
        1.  [ ] Sub-task: Raise `ValueError` for an API key not starting with `sk-`.
        2.  [ ] Sub-task: Raise `ValueError` for an empty API key.
        3.  [ ] Sub-task: Raise `ValueError` for a `None` API key.
    3.  [ ] Task: Test default values for `model`, `max_retries`, `timeout`.
    4.  [ ] Task: Test instantiation fails if `pricing` is missing.

2.  **`ImageProcessingRequest` Pydantic Model Tests:**
    1.  [ ] Task: Test successful instantiation with all required fields.
    2.  [ ] Task: Test instantiation fails if `s3_key` is missing.
    3.  [ ] Task: Test instantiation fails if `file_name` is missing.
    4.  [ ] Task: Test `project_context` and `document_uuid` can be `None`.

3.  **`ProcessingMetadata` Pydantic Model Tests:**
    1.  [ ] Task: Test successful instantiation with required fields and verify default values for optional fields.
    2.  [ ] Task: Test instantiation with all fields provided, including optional ones.
    3.  [ ] Task: Verify `timestamp` is an ISO format string.

4.  **`CostBreakdown` Pydantic Model Tests:**
    1.  [ ] Task: Test successful instantiation with all required fields.

5.  **`APIResponse` Pydantic Model Tests:**
    1.  [ ] Task: Test successful instantiation with `choices` and optional `usage`.
    2.  [ ] Task: Test instantiation fails if `choices` is missing.
    3.  [ ] Task: Test instantiation fails if `choices` is an empty list.

6.  **`FallbackResult` Pydantic Model Tests:**
    1.  [ ] Task: Test successful instantiation with required fields (`extracted_text`, `processing_metadata`) and verify defaults for others.

7.  **`ImageProcessingError` Exception Tests:**
    1.  [ ] Task: Test instantiation and verify `message`, `error_code`, and `retry_possible` attributes are set correctly.

8.  **`ImageProcessor` Class Tests:**
    1.  **`__init__` Method Tests:**
        1.  [ ] Task: Test successful initialization:
            *   Mock `os.getenv` for `OPENAI_API_KEY` and `REDIS_URL`.
            *   Mock `SupabaseManager`, `get_redis_manager`, `S3StorageManager` constructors.
            *   Verify `self.config` is an instance of `ImageProcessingConfig`.
            *   Verify `self.config.api_key` is correctly set from `os.getenv`.
            *   Verify manager instances are assigned.
        2.  [ ] Task: Test initialization failure if `OPENAI_API_KEY` is missing or invalid (e.g., mock `os.getenv` to return `None` or an invalid key, expect `ValueError` from `ImageProcessingConfig`).
        3.  [ ] Task: Test initialization with `REDIS_URL` not set (verify `self.redis_manager` is `None`).

    2.  **`process_image` Method Tests:**
        *   **Setup:**
            *   Create an `ImageProcessor` instance.
            *   Mock `time.time()` for consistent timing.
            *   Define a sample `s3_key`, `file_name`, and `project_context`.
        *   **Test Cases:**
        1.  [ ] Task: Test happy path:
            *   Mock `self._generate_cache_key` to return a sample key.
            *   Mock `self._get_cached_result` to return `None` (cache miss).
            *   Mock `self._download_image_from_s3` to return valid image bytes.
            *   Mock `self._validate_image` to pass.
            *   Mock `self._encode_image_base64` to return a base64 string.
            *   Mock `self._generate_legal_context_prompt` to return a prompt.
            *   Mock `self._call_o4_mini_with_retry` to return a valid API response dictionary.
            *   Mock `self._create_image_processing_result` to return a populated `ImageProcessingResultModel`.
            *   Mock `self._cache_result`.
            *   Verify the method returns the `ImageProcessingResultModel`.
            *   Verify `self._cache_result` was called with correct arguments.
        2.  [ ] Task: Test cache hit:
            *   Mock `self._generate_cache_key`.
            *   Mock `self._get_cached_result` to return a valid cached result dictionary.
            *   Verify the method returns an `ImageProcessingResultModel` created from the cached data.
            *   Verify that subsequent methods (`_download_image_from_s3`, etc.) are NOT called.
        3.  [ ] Task: Test failure during image download:
            *   Mock `self._get_cached_result` for cache miss.
            *   Mock `self._download_image_from_s3` to raise `ImageProcessingError`.
            *   Verify `ImageProcessingError` is re-raised.
        4.  [ ] Task: Test failure during image validation:
            *   Mock `self._download_image_from_s3` to succeed.
            *   Mock `self._validate_image` to raise `ImageProcessingError`.
            *   Verify `ImageProcessingError` is re-raised.
        5.  [ ] Task: Test failure during image encoding:
            *   Mock `self._validate_image` to succeed.
            *   Mock `self._encode_image_base64` to raise `ImageProcessingError`.
            *   Verify `ImageProcessingError` is re-raised.
        6.  [ ] Task: Test failure during API call:
            *   Mock `self._encode_image_base64` to succeed.
            *   Mock `self._call_o4_mini_with_retry` to raise `ImageProcessingError`.
            *   Verify `ImageProcessingError` is re-raised.
        7.  [ ] Task: Test unexpected general exception:
            *   Mock `self._download_image_from_s3` to raise a generic `Exception`.
            *   Verify `ImageProcessingError` with `error_code="UNEXPECTED_ERROR"` is raised.
        8.  [ ] Task: Test with `project_context` provided and verify it's used in `_generate_legal_context_prompt`.
        9.  [ ] Task: Test with `project_context` as `None`.

    3.  **`_download_image_from_s3` Method Tests:**
        1.  [ ] Task: Test happy path:
            *   Mock `self.s3_manager.download_file` to succeed.
            *   Mock `tempfile.NamedTemporaryFile` and `open` for file operations.
            *   Verify returned image bytes.
        2.  [ ] Task: Test S3 download failure (e.g., `s3_manager.download_file` raises an exception).
            *   Verify `ImageProcessingError` with `error_code="S3_DOWNLOAD_ERROR"` is raised.

    4.  **`_validate_image` Method Tests:**
        *   **Setup:**
            *   Use sample valid image bytes (e.g., a small JPEG/PNG).
            *   Use sample invalid image bytes.
        *   **Test Cases:**
        1.  [ ] Task: Test happy path with valid image bytes and size within limits.
        2.  [ ] Task: Test image too large (mock `len(image_bytes)` to exceed `max_size_mb`).
            *   Verify `ImageProcessingError` with `error_code="IMAGE_TOO_LARGE"` and `retry_possible=False` is raised.
        3.  [ ] Task: Test invalid image format (mock `Image.open` or `image.verify` to raise an exception).
            *   Verify `ImageProcessingError` with `error_code="INVALID_IMAGE"` and `retry_possible=False` is raised.

    5.  **`_encode_image_base64` Method Tests:**
        1.  [ ] Task: Test happy path with sample image bytes. Verify correct base64 encoding.
        2.  [ ] Task: Test encoding failure (e.g., pass invalid input that `base64.b64encode` might reject, though unlikely for bytes).
            *   Verify `ImageProcessingError` with `error_code="ENCODING_ERROR"` is raised.

    6.  **`_generate_legal_context_prompt` Method Tests:**
        1.  [ ] Task: Test with `project_context = None`. Verify base prompt structure.
        2.  [ ] Task: Test with `project_context` provided. Verify project context is included in the prompt.
        3.  [ ] Task: Verify `file_name` is included in the prompt.

    7.  **`_call_o4_mini_with_retry` Method Tests:**
        *   **Setup:**
            *   Mock `time.sleep`.
        *   **Test Cases:**
        1.  [ ] Task: Test happy path: `_make_vision_api_call` succeeds on the first attempt.
            *   Verify `_make_vision_api_call` is called once.
        2.  [ ] Task: Test retry logic: `_make_vision_api_call` fails twice, then succeeds on the third attempt.
            *   Verify `_make_vision_api_call` is called three times.
            *   Verify `time.sleep` is called with increasing backoff times.
        3.  [ ] Task: Test all retries fail: `_make_vision_api_call` consistently raises an exception.
            *   Verify `ImageProcessingError` with `error_code="API_FAILURE"` is raised after `max_retries + 1` attempts.
        4.  [ ] Task: Test with `max_retries` argument overriding `self.config.max_retries`.

    8.  **`_make_vision_api_call` Method Tests:**
        *   **Setup:**
            *   Mock `requests.post`.
        *   **Test Cases:**
        1.  [ ] Task: Test happy path: `requests.post` returns a 200 status and valid JSON.
            *   Verify correct API endpoint, headers, and payload structure.
            *   Verify `detail: "high"` and correct `model` are used.
        2.  [ ] Task: Test API error (non-200 status code from `requests.post`).
            *   Verify `ImageProcessingError` with `error_code="API_ERROR"` is raised.
        3.  [ ] Task: Test invalid API response (200 status, but JSON missing `choices` or `choices` is empty).
            *   Verify `ImageProcessingError` with `error_code="INVALID_RESPONSE"` is raised.
        4.  [ ] Task: Test `requests.exceptions.Timeout`.
            *   Verify `ImageProcessingError` with `error_code="TIMEOUT"` is raised.
        5.  [ ] Task: Test `requests.exceptions.RequestException` (e.g., connection error).
            *   Verify `ImageProcessingError` with `error_code="REQUEST_ERROR"` is raised.
        6.  [ ] Task: Test `json.JSONDecodeError` if API returns malformed JSON.
            *   Verify `ImageProcessingError` with `error_code="JSON_ERROR"` is raised.

    9.  **`_create_image_processing_result` Method Tests:** (This is the method called by `process_image` as per `process_image` logic, not `_structure_processing_result`)
        *   **Setup:**
            *   Define a sample valid API response dictionary.
            *   Mock `time.time()` and `datetime.utcnow()`.
        *   **Test Cases:**
        1.  [ ] Task: Test with a valid API result.
            *   Verify the returned `ImageProcessingResultModel` has correctly populated fields (`extracted_text`, `overall_confidence`, `image_type_detected`, `key_objects_detected`, `metadata`).
            *   Ensure metadata fields like `processing_time_seconds`, `timestamp`, tokens, cost, etc., are correctly calculated/set.
        2.  [ ] Task: Test API result with missing `usage` field.
            *   Verify token counts default to 0 and cost calculation handles this.
        3.  [ ] Task: Test with different `extracted_text` lengths and content to verify `_calculate_confidence_score` and `_detect_image_type` are called and influence the result.
        4.  [ ] Task: Test exception handling during result structuring (e.g., if API response is unexpectedly malformed after initial checks).
            *   Verify `ImageProcessingError` with `error_code="RESULT_PROCESSING_ERROR"` is raised.

    10. **`_calculate_processing_cost` Method Tests:**
        1.  [ ] Task: Test with zero input and output tokens.
        2.  [ ] Task: Test with non-zero input and output tokens.
            *   Verify calculations against `self.config.pricing`.
            *   Verify the returned `CostBreakdown` Pydantic model structure and rounded values.

    11. **`_calculate_confidence_score` Method Tests:**
        1.  [ ] Task: Test with short `extracted_text` (<200 chars).
        2.  [ ] Task: Test with medium `extracted_text` (200-500 chars).
        3.  [ ] Task: Test with long `extracted_text` (>500 chars).
        4.  [ ] Task: Test with `extracted_text` containing structured keywords.
        5.  [ ] Task: Test with `extracted_text` not containing structured keywords.
        6.  [ ] Task: Test with `usage` dictionary having `completion_tokens` in and out of the "reasonable range" (100-1500).
        7.  [ ] Task: Verify the returned score is capped between 0.1 and 1.0.

    12. **`_detect_image_type` Method Tests:**
        1.  [ ] Task: Test with `extracted_text` clearly indicating "legal_document".
        2.  [ ] Task: Test for "photograph", "scan", "handwritten", "signature", "receipt", "diagram", "screenshot".
        3.  [ ] Task: Test with text not matching any pattern, expecting "unknown".
        4.  [ ] Task: Test case-insensitivity.

    13. **`_extract_preliminary_entities` Method Tests:**
        1.  [ ] Task: Test with `extracted_text` containing names, dates, phone numbers, emails, money, and case numbers.
        2.  [ ] Task: Test with `extracted_text` containing no entities.
        3.  [ ] Task: Test that it limits to the first 5 matches of each entity type.
        4.  [ ] Task: Verify the format of the returned list (e.g., "names: John Doe").

    14. **`_generate_cache_key` Method Tests:**
        1.  [ ] Task: Test that the same `s3_key`, `file_name`, and `self.config.model` produce the same cache key.
        2.  [ ] Task: Test that different inputs produce different cache keys.

    15. **`_get_cached_result` Method Tests:**
        1.  [ ] Task: Test with `self.redis_manager` as `None` (should return `None`).
        2.  [ ] Task: Test cache hit: mock `self.redis_manager.get` to return serialized JSON data. Verify deserialized dict is returned.
        3.  [ ] Task: Test cache miss: mock `self.redis_manager.get` to return `None`. Verify `None` is returned.
        4.  [ ] Task: Test Redis error during `get` (e.g., `self.redis_manager.get` raises an exception). Verify `None` is returned and a warning is logged.
        5.  [ ] Task: Test JSON decoding error if cached data is malformed. Verify `None` is returned and warning logged.

    16. **`_cache_result` Method Tests:**
        1.  [ ] Task: Test with `self.redis_manager` as `None` (should do nothing).
        2.  [ ] Task: Test successful caching: mock `self.redis_manager.setex`. Verify it's called with correct key, TTL (86400), and serialized result.
        3.  [ ] Task: Test Redis error during `setex`. Verify a warning is logged.

9.  **`handle_image_processing_failure` Function Tests:**
    1.  [ ] Task: Test with a sample `Exception` instance.
        *   Verify the `FallbackResult` model is correctly populated (description includes filename and error, confidence is 0.1, type is "failed_processing").
        *   Verify the `ProcessingMetadata` within `FallbackResult` is correctly populated (model "fallback", status "failed", error message).
    2.  [ ] Task: Mock `SupabaseManager` and its `client.table().update().eq().execute()` chain.
        *   Verify the database update is called with correct fallback information.
    3.  [ ] Task: Test database update failure (mock Supabase call to raise an exception).
        *   Verify an error is logged.
        *   Verify the function still returns the `FallbackResult`.

**File: `entity_resolution_enhanced.py`**

1.  **`get_entity_embedding` Function Tests:**
    *   **Setup:** Mock `openai_client`.
    1.  [ ] Task: Test with `openai_client` available and API call successful.
        *   Mock `openai_client.embeddings.create` to return a sample embedding response.
        *   Verify correct prompt construction for different entity types ("Person", "Organization", "Location", "Date", other).
        *   Verify a `numpy.ndarray` is returned.
    2.  [ ] Task: Test with `openai_client` set to `None`. Verify `None` is returned.
    3.  [ ] Task: Test API call failure (mock `openai_client.embeddings.create` to raise an exception). Verify `None` is returned and a warning is logged.

2.  **`compute_semantic_similarity` Function Tests:**
    1.  [ ] Task: Test with two valid `numpy.ndarray` embeddings. Verify correct cosine similarity.
    2.  [ ] Task: Test with `emb1` as `None`. Verify returns `0.0`.
    3.  [ ] Task: Test with `emb2` as `None`. Verify returns `0.0`.
    4.  [ ] Task: Test with both `emb1` and `emb2` as `None`. Verify returns `0.0`.
    5.  [ ] Task: Test with zero vectors (should not cause division by zero, handle appropriately or expect specific numpy behavior).
    6.  [ ] Task: Test with identical non-zero vectors (similarity should be 1.0 or very close).
    7.  [ ] Task: Test with orthogonal non-zero vectors (similarity should be 0.0 or very close).

3.  **`fuzzy_string_similarity` Function Tests:**
    *   **Setup:** Mock `difflib.SequenceMatcher`.
    1.  [ ] Task: Test exact match (case-insensitive, strips whitespace). Expect 1.0.
    2.  [ ] Task: Test substring match (e.g., "John Doe" in "The honorable John Doe"). Expect 0.9.
    3.  [ ] Task: Test `SequenceMatcher` ratio for strings that are neither exact nor substring matches.
    4.  [ ] Task: Test token overlap for multi-word entities.
        *   High overlap (e.g., "International Business Machines" vs "IBM Corp").
        *   Low overlap.
    5.  [ ] Task: Test with one or both strings empty.
    6.  [ ] Task: Test with identical strings of different cases.

4.  **`enhanced_entity_resolution` Function Tests:**
    *   **Setup:**
        *   Mock `get_redis_manager` and its methods (`is_available`, `get_cached`, `set_cached`).
        *   Mock `get_entity_embedding`.
        *   Mock `compute_semantic_similarity` and `fuzzy_string_similarity`.
        *   Prepare sample `entity_mentions_for_doc` and `document_text`.
    *   **Test Cases:**
    1.  [ ] Task: Test happy path: multiple mentions, some grouping based on combined similarity.
        *   Verify structure and content of `canonical_entities` (check `canonicalName`, `entity_type`, `allKnownAliasesInDoc_json`, `mention_count_in_doc`, `confidence_score`).
        *   Verify structure and content of `updated_mentions` (check `resolved_canonical_id_temp`).
    2.  [ ] Task: Test with no entity mentions. Expect empty lists to be returned.
    3.  [ ] Task: Test Redis cache hit:
        *   Mock `redis_mgr.get_cached` to return a valid cached result.
        *   Verify the function returns data from cache and doesn't perform computations.
    4.  [ ] Task: Test Redis cache miss and successful caching:
        *   Mock `redis_mgr.get_cached` to return `None`.
        *   Verify computations are performed.
        *   Verify `redis_mgr.set_cached` is called with correct arguments and TTL.
    5.  [ ] Task: Test with `chunk_embeddings` provided:
        *   Ensure `get_entity_embedding` is still called.
        *   Verify embeddings are combined (0.7 * entity_emb + 0.3 * chunk_emb).
    6.  [ ] Task: Test with `chunk_embeddings` as `None`.
    7.  [ ] Task: Test when `get_entity_embedding` returns `None` for some/all mentions.
        *   Verify fallback to string similarity or chunk embedding if available.
    8.  [ ] Task: Test with different `similarity_threshold` values affecting grouping.
    9.  [ ] Task: Test with `semantic_weight` = 0 (only string similarity used if embeddings exist).
    10. [ ] Task: Test with `semantic_weight` = 1 (only semantic similarity used if embeddings exist).
    11. [ ] Task: Test canonical name selection logic for "Person" type (prefer full names).
    12. [ ] Task: Test average embedding calculation for canonical entities.

5.  **`_generate_resolution_cache_key` Function Tests:**
    1.  [ ] Task: Test that the same `entity_mentions` (order-independent for values/types) and `doc_text_snippet` produce the same key.
    2.  [ ] Task: Test that different inputs produce different keys.
    3.  [ ] Task: Test that only 'value' and 'entity_type' from mentions are used in key generation.

6.  **`cross_document_entity_linking` Function Tests:**
    *   **Setup:**
        *   Mock `db_manager.service_client.rpc('find_similar_canonical_entities', ...).execute()`.
        *   Prepare sample `canonical_entities` (some with embeddings, some without).
    *   **Test Cases:**
    1.  [ ] Task: Test happy path: some entities link to existing global IDs, some do not.
        *   Verify `id_mapping` contains correct mappings.
    2.  [ ] Task: Test with no embeddings present in `canonical_entities`. Verify no DB calls are made.
    3.  [ ] Task: Test when `db_manager.service_client.rpc` returns data (mock a successful match).
    4.  [ ] Task: Test when `db_manager.service_client.rpc` returns no data (no match found).
    5.  [ ] Task: Test database call failure (mock RPC call to raise an exception). Verify a warning is logged.
    6.  [ ] Task: Test with different `similarity_threshold`.

**File: `redis_utils.py`**

1.  **`RedisManager` Class Tests:**
    *   **`__init__` Method Tests:**
        1.  [ ] Task: Test successful connection when `USE_REDIS_CACHE=True`.
            *   Mock `redis.ConnectionPool` and `redis.Redis().ping()`.
            *   Verify `_pool` is created and `CacheMetrics` is initialized.
        2.  [ ] Task: Test connection failure (e.g., `ping()` raises `redis.exceptions.ConnectionError`). Expect `_pool` to be `None` and error to be re-raised or handled.
        3.  [ ] Task: Test initialization when `USE_REDIS_CACHE=False`. Verify `_pool` remains `None`.
        4.  [ ] Task: Test configuration with `REDIS_USERNAME` provided.
        5.  [ ] Task: Test configuration with `REDIS_SSL=True`. Verify `connection_class` is `redis.SSLConnection`.
        6.  [ ] Task: Test initialization of `_metrics` attribute.

    *   **`get_client` Method Tests:**
        1.  [ ] Task: Test returns a `redis.Redis` instance when pool is available.
        2.  [ ] Task: Test raises `RuntimeError` if `USE_REDIS_CACHE=False` or `_pool` is `None`.

    *   **`is_available` Method Tests:**
        1.  [ ] Task: Test returns `True` if `USE_REDIS_CACHE=True`, pool exists, and `ping()` succeeds.
        2.  [ ] Task: Test returns `False` if `USE_REDIS_CACHE=False`.
        3.  [ ] Task: Test returns `False` if `_pool` is `None`.
        4.  [ ] Task: Test returns `False` if `ping()` fails.

    *   **`generate_cache_key` Static Method Tests:**
        1.  [ ] Task: Test with no `args` or `kwargs`.
        2.  [ ] Task: Test with `args` (primitives, dicts, lists).
        3.  [ ] Task: Test with `kwargs` (primitives, dicts, lists).
        4.  [ ] Task: Test with both `args` and `kwargs`.
        5.  [ ] Task: Verify consistency: same inputs produce same key.
        6.  [ ] Task: Verify uniqueness: different inputs produce different keys.
        7.  [ ] Task: Verify MD5 hashing for dict/list arguments.

    *   **Cache Operations (`get_cached`, `set_cached`, `delete`, `exists`) Tests:**
        *   For each method:
            1.  [ ] Task: Mock `self.get_client()` and the underlying Redis command (e.g., `client.get`).
            2.  [ ] Task: Test happy path (e.g., `get_cached` returns deserialized JSON or string, `set_cached` successful).
            3.  [ ] Task: Test when key not found (for `get_cached`, `exists`).
            4.  [ ] Task: Test Redis client error (e.g., command raises `redis.exceptions.RedisError`). Verify error logging and appropriate return value (e.g., `None` or `False`).
            5.  [ ] Task: For `get_cached`, test deserialization of JSON and fallback to raw string.
            6.  [ ] Task: For `set_cached`, test serialization of dict/list to JSON. Test with and without TTL.

    *   **Hash Operations (`hset`, `hget`, `hgetall`) Tests:**
        *   Similar structure to cache operations: mock client, test happy path, key/field not found, Redis errors, JSON serialization/deserialization.

    *   **`lock` Context Manager Tests:**
        1.  [ ] Task: Test successful lock acquisition and release: mock `client.lock().acquire()` to return `True`, then mock `lock.release()`.
        2.  [ ] Task: Test lock acquisition failure (non-blocking): mock `client.lock().acquire(blocking=False)` to return `False`. Expect `RuntimeError`.
        3.  [ ] Task: Test lock timeout: mock `client.lock().acquire(blocking=True, blocking_timeout=...)` to return `False` after timeout. Expect `RuntimeError`.
        4.  [ ] Task: Test exception during lock usage, ensure lock is released in `finally` block.

    *   **`setnx` Method Tests:**
        1.  [ ] Task: Test successful `setnx` when key doesn't exist (mock `client.setnx` returns `True`). Verify TTL is set if provided.
        2.  [ ] Task: Test `setnx` when key already exists (mock `client.setnx` returns `False`). Verify returns `False`.
        3.  [ ] Task: Test Redis error.

    *   **`check_rate_limit` Method Tests:**
        1.  [ ] Task: Test action is within limit (mock `pipe.execute()` results).
        2.  [ ] Task: Test action exceeds limit.
        3.  [ ] Task: Test Redis pipeline error. Verify allows action on error.

    *   **Pub/Sub Operations (`publish`, `get_pubsub`) Tests:**
        1.  [ ] Task: Test `publish` with dict/list and string messages. Mock `client.publish`.
        2.  [ ] Task: Test `get_pubsub` returns a `PubSub` instance. Mock `client.pubsub`.
        3.  [ ] Task: Test Redis errors for `publish`.

    *   **Cache Invalidation (`invalidate_document_cache`, `invalidate_pattern`) Tests:**
        1.  [ ] Task: Mock `client.scan_iter` and `client.delete`.
        2.  [ ] Task: For `invalidate_document_cache`, test with patterns generated by `CacheKeys.get_all_document_patterns`.
        3.  [ ] Task: Verify correct number of keys deleted.
        4.  [ ] Task: Test when Redis is unavailable.
        5.  [ ] Task: Test Redis error during scan or delete.

    *   **Batch Operations (`batch_set_cached`, `batch_get_cached`) Tests:**
        1.  [ ] Task: Mock `client.pipeline()` and `pipe.execute()`.
        2.  [ ] Task: Test `batch_set_cached` with multiple key-value pairs, with/without TTL. Verify metrics updated.
        3.  [ ] Task: Test `batch_get_cached` for existing and non-existing keys. Verify metrics updated (hits/misses).
        4.  [ ] Task: Test Redis pipeline error.

    *   **`log_pool_stats` Method Tests:**
        1.  [ ] Task: Mock `time.time()` and `self._pool` attributes (`created_connections`, `_available_connections`, `_in_use_connections`, `max_connections`).
        2.  [ ] Task: Test logging when interval is met.
        3.  [ ] Task: Test logging when interval is not met (no log).
        4.  [ ] Test high usage warning (usage_ratio > 0.8).
        5.  [ ] Test when `_pool` or Redis is unavailable.

    *   **Stream Operations (`produce_to_stream`, `create_consumer_group`) Tests:**
        1.  [ ] Task: Test `produce_to_stream`: mock `client.xadd`. Verify message data cleaning.
        2.  [ ] Task: Test `create_consumer_group`: mock `client.xgroup_create`. Test idempotency (BUSYGROUP error).
        3.  [ ] Task: Test Redis errors for stream operations.

    *   **Pydantic-aware Cache Operations Tests:**
        *   **`get_cached_model`:**
            1.  [ ] Task: Test cache hit with valid Pydantic model data. Verify model instance returned and metadata updated.
            2.  [ ] Task: Test cache miss. Verify `None` returned.
            3.  [ ] Task: Test deserialization error (invalid JSON or Pydantic validation failure). Verify `None` returned and key deleted.
            4.  [ ] Task: Test expired cache entry (mock `model_instance.is_valid()` to be `False`). Verify `None` returned and key deleted.
            5.  [ ] Task: Test Redis error.
        *   **`set_cached_model`:**
            1.  [ ] Task: Test successful set with a `BaseCacheModel` instance.
            2.  [ ] Task: Test TTL override uses model's TTL if `ttl` arg is `None`.
            3.  [ ] Task: Verify `_metrics.record_set` is called.
            4.  [ ] Task: Test Redis error.
        *   **`get_or_create_cached_model`:**
            1.  [ ] Task: Test cache hit (returns cached model).
            2.  [ ] Task: Test cache miss: `factory_func` is called, new model is cached and returned.
            3.  [ ] Task: Test `factory_func` raises an exception. Verify `None` returned.
        *   **`invalidate_by_tags`:**
            1.  [ ] Task: Mock `client.scan_iter` and `client.delete`.
            2.  [ ] Task: Test invalidation with multiple tags and various key patterns.
        *   **`batch_get_cached_models`:**
            1.  [ ] Task: Test retrieving multiple valid models.
            2.  [ ] Task: Test with some keys missing or containing invalid/expired data.
            3.  [ ] Task: Verify metrics (hits/misses).
        *   **`batch_set_cached_models`:**
            1.  [ ] Task: Test setting multiple Pydantic models.
            2.  [ ] Task: Verify correct TTLs are used.
            3.  [ ] Task: Verify metrics.

    *   **`_extract_cache_type_from_key` Method Tests:**
        1.  [ ] Task: Test with various valid key formats (e.g., "prefix:id:suffix").
        2.  [ ] Task: Test with keys that don't match expected patterns (should return 'unknown').
        3.  [ ] Task: Test with empty key or key without colons.

    *   **Enhanced Cache Operations (`set_cached_with_auto_invalidation`, `invalidate_by_tag_sets`) Tests:**
        1.  [ ] Task: Test `set_cached_with_auto_invalidation`:
            *   Verify main entry is set (Pydantic model or other).
            *   Verify tag keys are created using `client.sadd` and `client.expire`.
        2.  [ ] Task: Test `invalidate_by_tag_sets`:
            *   Mock `client.smembers` and `client.delete`.
            *   Verify correct keys are identified and deleted.

2.  **`CacheMetrics` Class Tests:**
    *   **`record_hit`, `record_miss`, `record_set` Method Tests:**
        1.  [ ] Task: Mock `self.redis_mgr.get_client().hincrby`.
        2.  [ ] Task: Verify correct Redis keys and fields are incremented for specific `cache_type` and "total".
        3.  [ ] Task: Test when Redis is unavailable.
    *   **`get_metrics` Method Tests:**
        1.  [ ] Task: Mock `self.redis_mgr.get_client().hgetall`.
        2.  [ ] Task: Test with and without `cache_type`. Verify correct calculations (hit_rate).
        3.  [ ] Task: Test when Redis is unavailable.
        4.  [ ] Task: Test with no hits/misses (avoid division by zero).
    *   **`reset_metrics` Method Tests:**
        1.  [ ] Task: Mock `self.redis_mgr.get_client().delete` and `scan_iter`.
        2.  [ ] Task: Test resetting specific `cache_type`.
        3.  [ ] Task: Test resetting all metrics (no `cache_type`).
        4.  [ ] Task: Test when Redis is unavailable.

3.  **Decorator Tests (`redis_cache`, `with_redis_lock`, `rate_limit`):**
    *   **`redis_cache` Decorator:**
        1.  [ ] Task: Create a dummy function and decorate it.
        2.  [ ] Task: Test cache hit: call decorated function twice with same args, verify second call uses cache (mock underlying `RedisManager.get_cached` and `set_cached`).
        3.  [ ] Task: Test cache miss: first call performs computation and caches.
        4.  [ ] Task: Test with `key_func` provided.
        5.  [ ] Task: Test when `USE_REDIS_CACHE=False` (function executes normally, no cache interaction).
        6.  [ ] Task: Test when Redis is unavailable (function executes normally).
        7.  [ ] Verify `_metrics.record_hit/miss/set` are called.
    *   **`with_redis_lock` Decorator:**
        1.  [ ] Task: Decorate a dummy function. Mock `lock_name_func`.
        2.  [ ] Task: Test successful lock acquisition: mock `RedisManager().lock()` context manager.
        3.  [ ] Task: Test lock acquisition failure: mock `RedisManager().lock()` to raise `RuntimeError`. Verify decorated function is not called (or handles error).
        4.  [ ] Task: Test when `USE_REDIS_CACHE=False`.
        5.  [ ] Task: Test when Redis is unavailable.
    *   **`rate_limit` Decorator:**
        1.  [ ] Task: Decorate a dummy function.
        2.  [ ] Task: Test within limit: mock `RedisManager().check_rate_limit` to return `True`.
        3.  [ ] Task: Test exceeding limit (`wait=False`): mock `check_rate_limit` to return `False`. Expect `RuntimeError`.
        4.  [ ] Task: Test exceeding limit (`wait=True`): mock `check_rate_limit` to return `False` then `True`. Mock `time.sleep`. Verify wait behavior.
        5.  [ ] Task: Test `max_wait` timeout.
        6.  [ ] Task: Test when `USE_REDIS_CACHE=False`.
        7.  [ ] Task: Test when Redis is unavailable.

4.  **`get_redis_manager` Function Tests:**
    1.  [ ] Task: Test that it returns a `RedisManager` instance.
    2.  [ ] Task: Test that subsequent calls return the same instance (singleton behavior).

**File: `cache_keys.py`**

1.  **`CacheKeys` Class Tests:**
    1.  **`format_key` Static Method Tests:**
        1.  [ ] Task: Test with a template and various `kwargs`.
        2.  [ ] Task: Test with `version` argument provided.
        3.  [ ] Task: Test raises `ValueError` if a required `kwarg` for the template is missing.
    2.  **`get_pattern` Static Method Tests:**
        1.  [ ] Task: Test with a sample template, verify placeholders are replaced with `wildcard`.
    3.  **`get_all_document_patterns` Class Method Tests:**
        1.  [ ] Task: Test with a sample `document_uuid`.
        2.  [ ] Task: Test with `include_versioned=True` and `False`. Verify generated patterns.
    4.  **`get_chunk_cache_patterns` Class Method Tests:**
        1.  [ ] Task: Test with a list of `chunk_uuids`. Verify generated patterns.
    5.  **`get_cache_type_from_key` Class Method Tests:**
        1.  [ ] Task: Test with various key strings matching different cache types defined in the method.
        2.  [ ] Task: Test with a key not matching any defined type, expecting "unknown".

**File: `logging_config.py`**

1.  **`setup_logging` Function Tests:**
    *   **Setup:**
        *   Mock `logging.getLogger`, `logging.StreamHandler`, `logging.handlers.TimedRotatingFileHandler`.
        *   Mock `Path.mkdir`.
    *   **Test Cases:**
    1.  [ ] Task: Test with default `name=None` and default `log_level`.
        *   Verify root logger is configured.
        *   Verify correct log level is set.
        *   Verify handlers (Console, File, Error) are created and added to the logger.
        *   Verify formatters are set correctly for each handler.
        *   Verify log filenames are generated correctly.
    2.  [ ] Task: Test with a custom `name` and `log_level`.
    3.  [ ] Task: Verify existing handlers are removed if logger is called multiple times for the same name.
    4.  [ ] Task: Verify startup log messages are emitted.

2.  **`get_logger` Function Tests:**
    1.  [ ] Task: Verify it calls `setup_logging` with the provided name and returns the logger instance.

**File: `structured_extraction.py`**

1.  **`StructuredExtractor` Class Tests:**
    *   **`__init__` Method Tests:**
        *   **Setup:** Mock `os.getenv` for `DEPLOYMENT_STAGE`, `OPENAI_API_KEY`. Mock `should_load_local_models`.
        1.  [ ] Task: Test with `DEPLOYMENT_STAGE="1"`. Verify `self.use_qwen` is `False` and OpenAI client is initialized (or attempted).
        2.  [ ] Task: Test with `should_load_local_models() == False`. Verify `self.use_qwen` is `False` and OpenAI client is initialized.
        3.  [ ] Task: Test with `use_qwen=True` and `should_load_local_models() == True`:
            *   Mock `AutoTokenizer.from_pretrained` and `AutoModelForCausalLM.from_pretrained` to succeed.
            *   Verify Qwen model and tokenizer are loaded. `self.use_qwen` is `True`.
        4.  [ ] Task: Test Qwen model loading failure (mock `AutoModelForCausalLM.from_pretrained` to raise an error).
            *   Verify `self.use_qwen` becomes `False` and OpenAI client is used as fallback. Log warning.
        5.  [ ] Task: Test OpenAI client initialization failure (mock `OpenAI()` to raise an error, or `OPENAI_API_KEY` is missing). Expect `ValueError`.

    *   **`extract_structured_data_from_chunk` Method Tests:**
        *   **Setup:** Create `StructuredExtractor` instance. Prepare `chunk_text` and `chunk_metadata`.
        1.  [ ] Task: Test with `self.use_qwen=True`.
            *   Mock `self._extract_with_qwen` to return a valid JSON string.
            *   Mock `self._parse_extraction_response` to process the JSON.
            *   Verify a `StructuredChunkData` instance is returned.
        2.  [ ] Task: Test with `self.use_qwen=False` (OpenAI path).
            *   Mock `self._extract_with_openai` to return a valid JSON string.
            *   Mock `self._parse_extraction_response`.
            *   Verify `StructuredChunkData` is returned.
        3.  [ ] Task: Test when `_extract_with_qwen` or `_extract_with_openai` raises an exception.
            *   Verify `_fallback_extraction` is called and its result is returned.
        4.  [ ] Task: Test when `_parse_extraction_response` fails after a successful LLM call.
            *   Verify `_fallback_extraction` is called.

    *   **`_create_extraction_prompt` Method Tests:**
        1.  [ ] Task: Verify the prompt structure includes `doc_category`, `page_range`, and `chunk_text`.
        2.  [ ] Task: Test with minimal `chunk_metadata`.

    *   **`_extract_with_qwen` Method Tests:** (Assuming Qwen model is loaded or mocked)
        1.  [ ] Task: Mock `self.tokenizer.apply_chat_template`, `self.tokenizer`, `self.model.generate`, `self.tokenizer.batch_decode`.
        2.  [ ] Task: Verify the method returns the decoded string from the model.

    *   **`_extract_with_openai` Method Tests:** (Rate limit decorator is tested elsewhere)
        *   **Setup:** Mock `OpenAI` client, `get_redis_manager`.
        1.  [ ] Task: Test OpenAI API call success: mock `self.openai_client.chat.completions.create`.
            *   Verify prompt is passed correctly.
            *   Verify `response_format={"type": "json_object"}` is used.
        2.  [ ] Task: Test Redis cache hit: mock `redis_mgr.get_cached` to return data.
        3.  [ ] Task: Test Redis cache miss and successful caching: mock `redis_mgr.set_cached`.
        4.  [ ] Task: Test OpenAI API error (e.g., `create` raises an exception). Expect error to be re-raised.
        5.  [ ] Task: Test when `self.openai_client` is `None`. Expect `ValueError`.

    *   **`_parse_extraction_response` Method Tests:**
        1.  [ ] Task: Test with a valid JSON string matching the expected structure. Verify `StructuredChunkData` is correctly populated.
        2.  [ ] Task: Test with JSON string wrapped in markdown code blocks (e.g., ```json ... ```).
        3.  [ ] Task: Test with invalid JSON string. Verify empty `StructuredChunkData` (fallback) is returned and error is logged.
        4.  [ ] Task: Test with JSON that's valid but doesn't match Pydantic models (e.g., missing keys). Verify graceful handling (default values in Pydantic models).
        5.  [ ] Task: Test with empty response string.

    *   **`_fallback_extraction` Method Tests:**
        1.  [ ] Task: Test with `chunk_text` containing dates, money, case numbers. Verify they are extracted.
        2.  [ ] Task: Test with `chunk_text` not containing these patterns.
        3.  [ ] Task: Verify `StructuredChunkData` output with `extraction_method='fallback'`.

2.  **`format_document_level_for_supabase` Function Tests:**
    1.  [ ] Task: Test with sample aggregated `structured_data`. Verify the output dictionary structure matches expectations for Supabase JSONB.
    2.  [ ] Task: Test with empty or partially filled `structured_data`.

3.  **`format_chunk_level_for_supabase` Function Tests:**
    1.  [ ] Task: Test with a sample `StructuredChunkData` instance. Verify output dict includes `extraction_timestamp`.

4.  **`aggregate_chunk_structures` Function Tests:**
    1.  [ ] Task: Test with a list of `StructuredChunkData` instances.
        *   Verify aggregation of `document_metadata` (type, date, parties, case_numbers, title).
        *   Verify aggregation of `key_facts`, `entities` (all types), and `relationships`.
        *   Verify sets are converted to lists.
        *   Verify `key_facts` are sorted by confidence.
    2.  [ ] Task: Test with an empty list of chunks.

5.  **`extract_structured_data_from_document` Function Tests:**
    *   **Setup:** Mock `StructuredExtractor` and its methods. Prepare sample `chunks`.
    1.  [ ] Task: Test happy path: multiple chunks, all successful extractions.
        *   Verify `aggregate_chunk_structures` is called.
        *   Verify `StructuredExtractionResultModel` is populated correctly (confidence scores, aggregated data).
    2.  [ ] Task: Test with an empty list of `chunks`.
    3.  [ ] Task: Test when `extractor.extract_structured_data_from_chunk` returns `None` or raises an error for some/all chunks.
        *   Verify `successful_extractions` count.
        *   Verify overall confidence calculation.
    4.  [ ] Task: Test overall exception handling (e.g., if `StructuredExtractor` init fails).
        *   Verify error `StructuredExtractionResultModel` is returned.

**File: `celery_app.py`**

1.  **Celery App Configuration Tests:**
    *   **Setup:** Mock `os.getenv` to control `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`, `REDIS_SSL`, `REDIS_USERNAME`, `REDIS_DB`, `DEPLOYMENT_STAGE`.
    1.  [ ] Task: Verify `redis_url` construction with SSL enabled and username/password.
    2.  [ ] Task: Verify `redis_url` construction with SSL disabled and no auth.
    3.  [ ] Task: Verify `redis_url` construction with password but no username.
    4.  [ ] Task: Verify basic Celery app configurations (serializer, timezone, prefetch, acks_late).
    5.  [ ] Task: Verify task routes are correctly defined.
    6.  [ ] Task: Test `DEPLOYMENT_STAGE = STAGE_CLOUD_ONLY` specific `broker_transport_options`.

**File: `text_processing.py`**

1.  **`clean_extracted_text` Function Tests:**
    1.  [ ] Task: Test with text containing `<|im_end|>`. Verify it's removed.
    2.  [ ] Task: Test with text containing excessive whitespace (3+ spaces/newlines). Verify normalization to `\n\n`.
    3.  [ ] Task: Test with leading/trailing whitespace. Verify it's stripped.
    4.  [ ] Task: Test with an empty string. Verify returns empty string.
    5.  [ ] Task: Test with `None` input. Verify returns empty string.

2.  **`categorize_document_text` Function Tests:**
    1.  [ ] Task: Test with text samples matching keywords for 'contract'.
    2.  [ ] Task: Test for 'affidavit', 'correspondence', 'exhibit', 'deposition', 'legal_filing', 'financial'.
    3.  [ ] Task: Test with text not matching any category, expecting 'document'.
    4.  [ ] Task: Test case-insensitivity of keyword matching.
    5.  [ ] Task: Test with `metadata` argument (though currently unused by the function).

3.  **`generate_simple_markdown` Function Tests (as defined in this file):**
    1.  [ ] Task: Test with text containing paragraphs that are all uppercase and short (should become `## Heading`).
    2.  [ ] Task: Test with text containing numbered items that are short (should become `### Heading`).
    3.  [ ] Task: Test with regular paragraphs.
    4.  [ ] Task: Test with mixed content.
    5.  [ ] Task: Test with empty input or input with only whitespace.

4.  **`process_document_with_semantic_chunking` Function Tests:**
    *   **Setup:**
        *   Mock `SupabaseManager` instance (`db_manager`).
        *   Mock `clean_extracted_text`.
        *   Mock `generate_simple_markdown` (from this file).
        *   Mock `process_and_insert_chunks` (from `chunking_utils.py`).
        *   Mock `StructuredExtractor` and its method `extract_structured_data_from_chunk`.
        *   Mock `format_chunk_level_for_supabase`.
        *   Mock `uuid.uuid4()` for predictable chunk IDs if needed.
    *   **Test Cases:**
    1.  [ ] Task: Test happy path with `use_structured_extraction=True`.
        *   Verify `clean_extracted_text` and `generate_simple_markdown` are called.
        *   Verify `process_and_insert_chunks` is called and its return value is used.
        *   Verify `StructuredExtractor` is initialized and `extract_structured_data_from_chunk` is called for each chunk.
        *   Verify `db_manager.update_chunk_metadata` is called if structured data is extracted.
        *   Verify `ChunkingResultModel` is populated correctly (chunks, counts, average_chunk_size).
        *   Verify `StructuredExtractionResultModel` is populated correctly (entities, facts, relationships, metadata).
    2.  [ ] Task: Test with `use_structured_extraction=False`.
        *   Verify `StructuredExtractor` is not called.
        *   Verify `structured_extraction_result` is `None`.
    3.  [ ] Task: Test when `process_and_insert_chunks` returns an empty list.
        *   Verify `total_chunks` is 0 and appropriate defaults in `ChunkingResultModel`.
    4.  [ ] Task: Test when `structured_extractor.extract_structured_data_from_chunk` returns `None`.
        *   Verify it's handled gracefully.
    5.  [ ] Task: Test overall exception handling (e.g., if `process_and_insert_chunks` raises an error).
        *   Verify `ChunkingResultModel` status is `FAILED` and `error_message` is set.

5.  **`convert_chunks_to_models` Function Tests:**
    1.  [ ] Task: Test with a list of valid raw chunk dictionaries. Verify correct `ChunkModel` instances are created.
    2.  [ ] Task: Test with chunk data missing required fields (e.g., "text"). Verify it's skipped or handled with defaults.
    3.  [ ] Task: Test with empty `raw_chunks` list. Expect an empty list of `ChunkModel`.
    4.  [ ] Task: Verify `uuid.UUID` generation for `chunk_uuid` if not provided in raw data.

**File: `s3_storage.py`**

1.  **`S3StorageManager` Class Tests:**
    *   **`__init__` Method Tests:**
        1.  [ ] Task: Mock `boto3.client('s3', ...)` to verify it's called with correct region and credentials (from mocked `config`).
        2.  [ ] Task: Verify `self.private_bucket_name` is set from `config.S3_PRIMARY_DOCUMENT_BUCKET`.

    *   **`_get_content_type` Method Tests:**
        1.  [ ] Task: Test with various known extensions ('.pdf', '.txt', '.jpg', etc.).
        2.  [ ] Task: Test with an unknown extension. Verify it returns 'application/octet-stream'.
        3.  [ ] Task: Test with a filename having no extension.
        4.  [ ] Task: Test case-insensitivity of extensions.

    *   **`upload_document_with_uuid_naming` Method Tests:**
        *   **Setup:**
            *   Mock `self.s3_client.put_object`.
            *   Mock `open` and `hashlib.md5`.
            *   Create a temporary local file using `tmp_path`.
        *   **Test Cases:**
        1.  [ ] Task: Test successful upload.
            *   Verify `s3_client.put_object` is called with correct `Bucket`, `Key` (UUID-based), `Body`, `Metadata` (original-filename, document-uuid, timestamp, content-type), and `ContentType`.
            *   Verify the returned dictionary structure and content.
        2.  [ ] Task: Test S3 upload failure (mock `put_object` to raise `ClientError`).
            *   Verify `self.handle_s3_errors` is called and the error is re-raised.

    *   **`get_s3_document_location` Method Tests:**
        1.  [ ] Task: Test with `s3_key` only (uses default bucket).
        2.  [ ] Task: Test with `s3_key` and custom `s3_bucket`.
        3.  [ ] Task: Test with `version_id` provided.
        4.  [ ] Task: Verify the returned dictionary structure.

    *   **`check_s3_object_exists` Method Tests:**
        *   **Setup:** Mock `self.s3_client.head_object`.
        *   **Test Cases:**
        1.  [ ] Task: Test when object exists (mock `head_object` to succeed). Expect `True`.
        2.  [ ] Task: Test when object does not exist (mock `head_object` to raise `ClientError` with '404' code). Expect `False`.
        3.  [ ] Task: Test other `ClientError` from `head_object`. Expect error to be re-raised.
        4.  [ ] Task: Test unexpected exception from `head_object`. Expect error to be re-raised.

    *   **`handle_s3_errors` Method Tests:**
        1.  [ ] Task: Test with `NoCredentialsError`. Expect `ValueError` with specific message.
        2.  [ ] Task: Test with `PartialCredentialsError`. Expect `ValueError`.
        3.  [ ] Task: Test with `ClientError` - 'NoSuchBucket'. Expect `ValueError`.
        4.  [ ] Task: Test with `ClientError` - 'AccessDenied'. Expect `ValueError`.
        5.  [ ] Task: Test with `ClientError` - 'InvalidObjectState'. Expect `ValueError`.
        6.  [ ] Task: Test with other `ClientError` codes. Expect `ValueError`.
        7.  [ ] Task: Test with a generic `Exception`. Expect it to be re-raised (or wrapped if behavior changes).

**File: `textract_utils.py`**

1.  **`TextractProcessor` Class Tests:**
    *   **`__init__` Method Tests:**
        1.  [ ] Task: Mock `boto3.client('textract', ...)` and `SupabaseManager`. Verify initialization.

    *   **`start_document_text_detection` Method Tests:**
        *   **Setup:** Create `TextractProcessor` instance. Mock `self.client.start_document_text_detection`. Mock `self.db_manager` methods.
        *   **Test Cases:**
        1.  [ ] Task: Test successful job start.
            *   Verify Textract API call with correct `DocumentLocation`, `ClientRequestToken` (deterministic if not provided), `JobTag`.
            *   Verify `NotificationChannel`, `OutputConfig`, `KMSKeyId` are included if configured in `config.py`.
            *   Verify `db_manager.create_textract_job_entry` and `db_manager.update_source_document_with_textract_outcome` are called with correct data.
            *   Verify `JobId` is returned.
        2.  [ ] Task: Test `ClientError` from Textract API.
            *   Verify error is logged and `db_manager.update_source_document_with_textract_outcome` is called with 'failed' status.
            *   Verify error is re-raised.
        3.  [ ] Task: Test with `job_tag` and `client_request_token` provided.

    *   **`_check_job_status_cache` and `_cache_job_status` Method Tests:**
        *   **Setup:** Mock `get_redis_manager` and its methods.
        1.  [ ] Task: Test `_check_job_status_cache` cache hit.
        2.  [ ] Task: Test `_check_job_status_cache` cache miss.
        3.  [ ] Task: Test `_cache_job_status` successful caching.
        4.  [ ] Task: Test Redis errors for both methods.

    *   **`get_text_detection_results` Method Tests:**
        *   **Setup:** Mock `self.client.get_document_text_detection`, `self.db_manager` methods, `time.sleep`, `datetime.now`. Mock `_check_job_status_cache` and `_cache_job_status`.
        *   **Test Cases:**
        1.  [ ] Task: Test job SUCCEEDED on first poll.
            *   Verify blocks and metadata are returned.
            *   Verify DB updates for `textract_jobs` and `source_documents` with 'succeeded' status and results.
            *   Verify status caching.
        2.  [ ] Task: Test job SUCCEEDED with pagination (`NextToken`).
            *   Verify multiple calls to `get_document_text_detection`.
            *   Verify blocks from all pages are aggregated.
        3.  [ ] Task: Test job FAILED.
            *   Verify `None, None` is returned.
            *   Verify DB updates with 'failed' status and error message.
            *   Verify status caching.
        4.  [ ] Task: Test job IN_PROGRESS then SUCCEEDED.
            *   Verify polling loop and `time.sleep` calls.
            *   Verify DB updates for 'in_progress' then 'succeeded'.
        5.  [ ] Task: Test job polling timeout.
            *   Verify `None, None` is returned after `TEXTRACT_ASYNC_MAX_POLLING_TIME_SECONDS`.
            *   Verify DB updates with 'failed' status and 'Polling Timeout' message.
        6.  [ ] Task: Test `ClientError` during polling. Verify DB updates and retry/error handling.
        7.  [ ] Task: Test cached job status hit (SUCCEEDED/FAILED). Verify API is not called again for status.

    *   **`_cache_ocr_result` and `get_cached_ocr_result` Method Tests:**
        *   **Setup:** Mock `get_redis_manager`.
        1.  [ ] Task: Test `_cache_ocr_result` successful caching with correct key and TTL.
        2.  [ ] Task: Test `get_cached_ocr_result` cache hit and miss.
        3.  [ ] Task: Test Redis errors.

    *   **`process_textract_blocks_to_text` Method Tests:**
        1.  [ ] Task: Test with a list of sample Textract `LINE` blocks across multiple pages. Verify correct text assembly and page separation.
        2.  [ ] Task: Test with blocks having confidence below `TEXTRACT_CONFIDENCE_THRESHOLD`. Verify they are skipped.
        3.  [ ] Task: Test with blocks missing `Geometry` or `BoundingBox`. Verify graceful handling.
        4.  [ ] Task: Test with an empty list of blocks. Expect empty string.
        5.  [ ] Task: Test with `doc_metadata` indicating more pages than found in blocks. Verify placeholder text for missing pages.

**File: `chunking_utils.py`**

1.  **`_basic_strip_markdown_for_search` Function Tests:**
    1.  [ ] Task: Test removal of images `![]()`.
    2.  [ ] Task: Test removal of headings `# ## ###`.
    3.  [ ] Task: Test conversion of links `[]()` to link text.
    4.  [ ] Task: Test removal of bold/italic markers `**__* _`.
    5.  [ ] Task: Test removal of horizontal rules `--- *** ___`.
    6.  [ ] Task: Test removal of fenced code block markers ``` ```, keeping content.
    7.  [ ] Task: Test table formatting removal (pipe characters, `|---|` lines).
    8.  [ ] Task: Test LaTeX math removal `$$ \\(\\)`.
    9.  [ ] Task: Test normalization of multiple newlines and spaces.
    10. [ ] Task: Test stripping of whitespace from each line and removal of empty lines.
    11. [ ] Task: Test with empty or whitespace-only input.

2.  **`chunk_markdown_text` Function Tests:**
    *   **Setup:** Prepare `markdown_guide` and `raw_text_to_chunk` samples. Mock `_basic_strip_markdown_for_search`.
    *   **Test Cases:**
    1.  [ ] Task: Test with simple markdown (a few headings and paragraphs). Verify chunks align with markdown structure.
    2.  [ ] Task: Test when a searchable segment from markdown is NOT found in `raw_text_to_chunk`. Verify warning is logged and subsequent searches are handled.
    3.  [ ] Task: Test with empty `markdown_guide` or `raw_text_to_chunk`.
    4.  [ ] Task: Test with markdown segments that become empty after stripping. Verify they are skipped.
    5.  [ ] Task: Verify `char_start_index`, `char_end_index`, and `metadata` (heading level/text) are correct for each chunk.

3.  **`refine_chunks` Function Tests:**
    1.  [ ] Task: Test with a list of chunks, some smaller than `min_chunk_size`. Verify small chunks are merged.
    2.  [ ] Task: Test with all chunks already larger than `min_chunk_size`. Verify no changes.
    3.  [ ] Task: Test merging logic: verify text concatenation, `char_end_index` update, and `metadata` (is_combined, combined_headings) update.
    4.  [ ] Task: Test with an empty list of input chunks.
    5.  [ ] Task: Test scenario where the last combined chunk is still smaller than `min_chunk_size` (it should still be added).
    6.  [ ] Task: Test handling of empty/whitespace chunks during merging.

4.  **`prepare_chunks_for_database` Function Tests:**
    1.  [ ] Task: Test with a list of refined chunks. Verify each chunk is transformed into the Supabase schema format.
    2.  [ ] Task: Verify `chunkId` is a new UUID, `document_id` and `document_uuid` are passed through, `chunkIndex` is sequential.
    3.  [ ] Task: Verify `metadata_json` is correctly stringified.

5.  **`simple_chunk_text` Function Tests:**
    1.  [ ] Task: Test with text shorter than `chunk_size`.
    2.  [ ] Task: Test with text longer than `chunk_size`, creating multiple chunks. Verify overlap.
    3.  [ ] Task: Test with `overlap = 0`.
    4.  [ ] Task: Test exact boundary conditions (e.g., `text_length` is a multiple of `chunk_size - overlap`).
    5.  [ ] Task: Verify `char_start_index`, `char_end_index`, and `metadata` for each chunk.

6.  **`process_and_insert_chunks` Function Tests:**
    *   **Setup:**
        *   Mock `db_manager` (`SupabaseManager` instance) and its `create_chunk_entry` method.
        *   Mock `chunk_markdown_text`, `refine_chunks`, `prepare_chunks_for_database`, `simple_chunk_text`.
        *   Optionally mock `IdempotentDatabaseOps` if `use_idempotent_ops=True`.
    *   **Test Cases:**
    1.  [ ] Task: Test happy path: markdown chunking succeeds, chunks are refined and inserted.
        *   Verify `db_manager.create_chunk_entry` (or `idempotent_ops.upsert_chunk`) is called for each prepared chunk.
        *   Verify returned list contains the inserted chunk data (with `sql_id` and `chunk_uuid`).
    2.  [ ] Task: Test fallback to `simple_chunk_text` if `chunk_markdown_text` returns no chunks.
    3.  [ ] Task: Test with `use_idempotent_ops=True`. Verify `IdempotentDatabaseOps.upsert_chunk` is called.
    4.  [ ] Task: Test database insertion failure for some chunks. Verify error logging and continuation.
    5.  [ ] Task: Test when `prepare_chunks_for_database` returns an empty list.

7.  **`generate_simple_markdown` Function Tests (this is a duplicate name, assume the one in `text_processing.py` is primary, this one is for internal use if called by `chunk_markdown_text` if it's not the imported one):**
    *   (Covered by `text_processing.py` tests if it's the same, or add specific tests if its behavior/usage here is distinct). If it's purely an internal helper for `chunk_markdown_text`, its behavior is implicitly tested by `chunk_markdown_text` tests.

**File: `models_init.py`**

1.  **`should_load_local_models` Function Tests:**
    1.  [ ] Task: Test returns `False` if `DEPLOYMENT_STAGE == STAGE_CLOUD_ONLY`.
    2.  [ ] Task: Test returns `False` if `BYPASS_LOCAL_MODELS` is `True` (and stage is not cloud-only).
    3.  [ ] Task: Test returns `True` if `BYPASS_LOCAL_MODELS` is `False` (and stage is not cloud-only).

2.  **`validate_cloud_api_keys` Function Tests:**
    *   **Setup:** Mock `os.getenv` for `OPENAI_API_KEY`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`.
    1.  [ ] Task: Test raises `ValueError` if `OPENAI_API_KEY` is missing.
    2.  [ ] Task: Test raises `ValueError` if `AWS_ACCESS_KEY_ID` is missing.
    3.  [ ] Task: Test raises `ValueError` if `AWS_SECRET_ACCESS_KEY` is missing.
    4.  [ ] Task: Test succeeds if all required keys are present.

3.  **`initialize_all_models` Function Tests:**
    1.  [ ] Task: Test with `DEPLOYMENT_STAGE = STAGE_CLOUD_ONLY`.
        *   Verify `validate_cloud_api_keys` is called.
        *   Verify local model init functions (`initialize_qwen2_vl_ocr_model`, etc.) are NOT called.
    2.  [ ] Task: Test with other stages (e.g., `STAGE_HYBRID`).
        *   Mock `initialize_qwen2_vl_ocr_model`, `initialize_whisper_model`, `initialize_ner_pipeline`.
        *   Verify these functions are called.
        *   Verify GPU availability check message.

4.  **`initialize_qwen2_vl_ocr_model` Function Tests:**
    *   **Setup:** Mock `transformers.AutoModelForCausalLM.from_pretrained`, `transformers.AutoProcessor.from_pretrained`. Mock `process_vision_info` import attempts. Set global `QWEN2_VL_OCR_MODEL` to `None` before each relevant test.
    1.  [ ] Task: Test when `should_load_local_models()` is `False`. Verify early exit and models remain `None`.
    2.  [ ] Task: Test when `QWEN2_VL_OCR_MODEL` is already initialized. Verify early exit.
    3.  [ ] Task: Test successful initialization (mock transformers calls to succeed).
        *   Verify global model, processor, device, and vision function are set.
        *   Test with `QWEN2_VL_USE_HALF_PRECISION = True/False` and `device = "cuda"/"cpu"`.
    4.  [ ] Task: Test model loading failure (e.g., `AutoModelForCausalLM.from_pretrained` raises error). Verify globals remain `None` and error is logged.
    5.  [ ] Task: Test `process_vision_info` import failure from all sources. Verify warning is logged.

5.  **`initialize_whisper_model` Function Tests:**
    *   **Setup:** Mock `whisper.load_model`. Set global `WHISPER_MODEL` to `None`.
    1.  [ ] Task: Test when `should_load_local_models()` is `False`.
    2.  [ ] Task: Test when `WHISPER_MODEL` is already initialized.
    3.  [ ] Task: Test successful initialization. Verify global `WHISPER_MODEL` is set.
        *   Test with `WHISPER_USE_HALF_PRECISION = True/False` and `device = "cuda"/"cpu"`.
    4.  [ ] Task: Test model loading failure. Verify `WHISPER_MODEL` remains `None` and error is logged.

6.  **`initialize_ner_pipeline` Function Tests:**
    *   **Setup:** Mock `transformers.pipeline`. Set global `NER_PIPELINE` to `None`.
    1.  [ ] Task: Test when `should_load_local_models()` is `False`.
    2.  [ ] Task: Test successful initialization. Verify global `NER_PIPELINE` is set.
        *   Test with `device = "cuda"` and `device = "cpu"` (affects `device_num`).
    3.  [ ] Task: Test pipeline creation failure. Verify `NER_PIPELINE` remains `None` and error is logged.

7.  **Getter Function Tests (`get_qwen2_vl_ocr_model`, `get_qwen2_vl_ocr_processor`, etc.):**
    *   For each getter function:
        1.  [ ] Task: Test when the global model/processor variable is already set. Verify it's returned directly.
        2.  [ ] Task: Test when the global model/processor variable is `None`.
            *   Mock the corresponding `initialize_*` function.
            *   Verify the `initialize_*` function is called.
            *   Verify the (mocked) initialized model/processor is returned.

**File: `relationship_builder.py`**

1.  **`stage_structural_relationships` Function Tests:**
    *   **Setup:**
        *   Mock `db_manager.create_relationship_staging` to return a mock relationship ID (e.g., an integer).
        *   Prepare sample `document_data`, `project_uuid`, `chunks_data`, `entity_mentions_data`, `canonical_entities_data`.
        *   Ensure `document_uuid` argument is also tested.
    *   **Test Cases:**
    1.  [ ] Task: Test happy path with valid data for all relationship types:
        *   Document-BELONGS_TO-Project
        *   Chunk-BELONGS_TO-Document
        *   Chunk-CONTAINS_MENTION-EntityMention
        *   EntityMention-MEMBER_OF_CLUSTER-CanonicalEntity
        *   Chunk-NEXT_CHUNK/PREVIOUS_CHUNK-Chunk
        *   Verify `RelationshipBuildingResultModel` structure, `total_relationships`, and `staged_relationships` content.
        *   Verify correct arguments are passed to `_create_relationship_wrapper` (and thus to `db_manager.create_relationship_staging`).
    2.  [ ] Task: Test with missing `documentId` (neo4j_document_uuid) in `document_data`. Expect failure status and error message.
    3.  [ ] Task: Test with invalid `project_uuid` (e.g., `None` or not a string). Verify Document-Project relationship is skipped and logged.
    4.  [ ] Task: Test with `chunks_data` items missing `chunkId`. Verify relationship is skipped.
    5.  [ ] Task: Test with `entity_mentions_data` items missing `entityMentionId` or `chunk_uuid`. Verify CONTAINS_MENTION is skipped.
    6.  [ ] Task: Test with `entity_mentions_data` items missing `resolved_canonical_id_neo4j`. Verify MEMBER_OF_CLUSTER is skipped.
    7.  [ ] Task: Test with `chunks_data` for NEXT/PREVIOUS_CHUNK missing `chunkId`.
    8.  [ ] Task: Test overall exception handling (e.g., if `_create_relationship_wrapper` raises an unexpected error). Verify failure status.
    9.  [ ] Task: Test when `document_uuid` argument is provided vs. when it's `None` (should use `document_data.get('documentId')`).

2.  **`_create_relationship_wrapper` Function Tests:**
    *   **Setup:** Mock `db_manager.create_relationship_staging`.
    *   **Test Cases:**
    1.  [ ] Task: Test successful relationship staging.
        *   Mock `db_manager.create_relationship_staging` to return a valid ID.
        *   Verify a `StagedRelationship` model instance is returned with correct fields.
        *   Test with and without `properties`.
    2.  [ ] Task: Test when `db_manager.create_relationship_staging` returns `None` (or falsy value indicating failure).
        *   Verify `None` is returned and an error is logged.
    3.  [ ] Task: Test when `db_manager.create_relationship_staging` raises an exception.
        *   Verify `None` is returned and an error is logged.

**File: `ocr_extraction.py`**

1.  **`detect_file_category` Function Tests:**
    1.  [ ] Task: Test with various image extensions (e.g., ".jpg", ".PNG"). Expect 'image'.
    2.  [ ] Task: Test with document extensions (e.g., ".pdf", ".DOCX"). Expect 'document'.
    3.  [ ] Task: Test with audio extensions. Expect 'audio'.
    4.  [ ] Task: Test with video extensions. Expect 'video'.
    5.  [ ] Task: Test with an unknown extension. Expect 'unknown' and log warning.
    6.  [ ] Task: Test with a path having no extension. Expect 'unknown'.
    7.  [ ] Task: Test with an exception during path processing (e.g., invalid path characters if `Path` raises). Expect 'unknown' and log error.

2.  **`is_image_file` Function Tests:**
    1.  [ ] Task: Test returns `True` for image extensions.
    2.  [ ] Task: Test returns `False` for non-image extensions.

3.  **`get_supported_file_types` Function Tests:**
    1.  [ ] Task: Verify the returned dictionary structure and content matches `IMAGE_EXTENSIONS`, `DOCUMENT_EXTENSIONS`, etc. from `config`.

4.  **`render_pdf_page_to_image` Function Tests:**
    *   **Setup:** Mock `fitz.open()` and its methods (`load_page`, `get_pixmap`, `close`). Mock `Image.frombytes`.
    1.  [ ] Task: Test successful rendering of a page. Verify `Image.Image` instance is returned.
    2.  [ ] Task: Test with `page_number` out of range. Expect `None` and log error.
    3.  [ ] Task: Test exception during `fitz.open()` (e.g., invalid PDF). Expect `None` and log error.
    4.  [ ] Task: Test exception during `page.get_pixmap()`. Expect `None` and log error.

5.  **`extract_text_from_pdf_qwen_vl_ocr` Function Tests:**
    *   **Setup:**
        *   Mock `should_load_local_models`.
        *   Mock model/processor getters (`get_qwen2_vl_ocr_model`, etc.).
        *   Mock `fitz.open()` for page count.
        *   Mock `render_pdf_page_to_image`.
        *   Mock Qwen model's `generate` method and processor's `apply_chat_template`, `batch_decode`.
        *   Mock `process_vision_info`.
    *   **Test Cases:**
    1.  [ ] Task: Test bypass if `DEPLOYMENT_STAGE="1"` or `should_load_local_models()` is `False`. Expect `None, None`.
    2.  [ ] Task: Test bypass if Qwen models/processor are not initialized. Expect `None, None`.
    3.  [ ] Task: Test successful extraction from a multi-page PDF.
        *   Verify `render_pdf_page_to_image` is called for each page.
        *   Verify Qwen model/processor methods are called with correct inputs for each page.
        *   Verify aggregated `full_document_text` and `page_level_metadata`.
    4.  [ ] Task: Test failure in `fitz.open()` (reading PDF). Expect `None, None`.
    5.  [ ] Task: Test failure in `render_pdf_page_to_image` for a page. Verify error text is included in output and metadata reflects failure for that page.
    6.  [ ] Task: Test failure in Qwen model `generate` for a page. Verify error text and metadata.
    7.  [ ] Task: Test empty PDF (0 pages).
    8.  [ ] Task: Test GPU cache clearing if `QWEN2_VL_OCR_DEVICE == 'cuda'`.

6.  **`_download_supabase_file_to_temp` Function Tests:**
    *   **Setup:** Mock `requests.get` and `tempfile.NamedTemporaryFile`.
    1.  [ ] Task: Test successful download. Verify temp file is created and its name is returned.
    2.  [ ] Task: Test `requests.exceptions.RequestException` (e.g., HTTP error). Expect `None` and log error.
    3.  [ ] Task: Test other exceptions during download. Expect `None` and log error.

7.  **`extract_text_from_pdf_textract` Function Tests:**
    *   **Setup:**
        *   Mock `SupabaseManager` (`db_manager`), `S3StorageManager`, `TextractProcessor`.
        *   Mock `TextractProcessor.get_cached_ocr_result`.
        *   Mock `os.path.exists`, `os.unlink`.
    *   **Test Cases:**
    1.  [ ] Task: Test cache hit: `get_cached_ocr_result` returns data.
    2.  [ ] Task: Test processing S3 URI (`s3://bucket/key`):
        *   Mock `s3_manager.check_s3_object_exists` to be `True`.
        *   Mock `textract_processor.start_document_text_detection` and `get_text_detection_results`.
        *   Verify `process_textract_blocks_to_text` is called.
        *   Verify DB updates and result caching.
    3.  [ ] Task: Test processing Supabase URL (`supabase://bucket/path`):
        *   Mock `_download_supabase_file_to_temp` to return a temp path.
        *   Mock `s3_manager.upload_document_with_uuid_naming`.
        *   Verify subsequent Textract flow.
    4.  [ ] Task: Test processing HTTP(S) URL: Similar to Supabase URL.
    5.  [ ] Task: Test processing local file path:
        *   Mock `os.path.exists` to be `True`.
        *   Mock `s3_manager.upload_document_with_uuid_naming`.
        *   Verify subsequent Textract flow.
    6.  [ ] Task: Test file not found (local path, S3 object, download failure). Verify DB update and error return.
    7.  [ ] Task: Test `TEXTRACT_USE_ASYNC_FOR_PDF = True` (async flow).
    8.  [ ] Task: Test `TEXTRACT_USE_ASYNC_FOR_PDF = False` (sync flow, expect error as it's not fully supported).
    9.  [ ] Task: Test Textract job start failure (`start_document_text_detection` returns `None`).
    10. [ ] Task: Test Textract job result failure (`get_text_detection_results` returns `None, None`).
    11. [ ] Task: Test empty `blocks` returned from successful Textract job.
    12. [ ] Task: Verify temporary file cleanup in `finally` block.

8.  **`extract_text_from_pdf_olmocr` Function Tests:**
    1.  [ ] Task: Verify it logs an error and returns `None, None`.

9.  **`extract_text_from_docx` Function Tests:**
    *   **Setup:** Mock `docx.Document`.
    1.  [ ] Task: Test with a valid DOCX file path. Mock `Document()` to return a doc with paragraphs.
    2.  [ ] Task: Test exception during DOCX parsing. Expect `None`.

10. **`extract_text_from_docx_s3_aware` Function Tests:**
    *   **Setup:** Mock `S3StorageManager`, `tempfile.NamedTemporaryFile`, `os.path.exists/unlink`, `docx.Document`.
    1.  [ ] Task: Test with S3 URI. Mock S3 download.
    2.  [ ] Task: Test with local file path.
    3.  [ ] Task: Test DOCX parsing with paragraphs and tables.
    4.  [ ] Task: Test invalid S3 URI format.
    5.  [ ] Task: Test DOCX parsing error.
    6.  [ ] Task: Verify temp file cleanup.
    7.  [ ] Task: Test page count approximation logic.

11. **`extract_text_from_txt` Function Tests:**
    *   **Setup:** Mock `open`.
    1.  [ ] Task: Test with a valid TXT file path.
    2.  [ ] Task: Test exception during file reading. Expect `None`.

12. **`extract_text_from_eml` Function Tests:**
    *   **Setup:** Mock `email.message_from_bytes`.
    1.  [ ] Task: Test with a multipart EML having a plain text part.
    2.  [ ] Task: Test with a multipart EML having an HTML part (no plain text). Verify basic HTML stripping.
    3.  [ ] Task: Test with a non-multipart EML.
    4.  [ ] Task: Test exception during EML parsing. Expect `None`.
    5.  [ ] Task: Verify headers are included in the output.

13. **`transcribe_audio_whisper` Function Tests:**
    *   **Setup:** Mock `should_load_local_models`, `get_whisper_model`, `transcribe_audio_openai_whisper`.
    1.  [ ] Task: Test when `DEPLOYMENT_STAGE = STAGE_CLOUD_ONLY`. Verify `transcribe_audio_openai_whisper` is called.
    2.  [ ] Task: Test when `USE_OPENAI_FOR_AUDIO_TRANSCRIPTION = True`. Verify `transcribe_audio_openai_whisper` is called.
    3.  [ ] Task: Test when `should_load_local_models()` is `False`. Verify `transcribe_audio_openai_whisper` is called.
    4.  [ ] Task: Test local Whisper model path:
        *   Mock `get_whisper_model` to return a mock model.
        *   Mock `mock_model.transcribe` to return a sample transcription result.
        *   Verify correct `fp16` usage based on device.
    5.  [ ] Task: Test local Whisper model not initialized (`get_whisper_model` returns `None`). Expect `None`.
    6.  [ ] Task: Test local Whisper `transcribe` method raises exception. Expect `None`.

14. **`transcribe_audio_openai_whisper` Function Tests:**
    *   **Setup:** Mock `OpenAI` client, `os.path.exists`, `os.path.getsize`, `open`.
    1.  [ ] Task: Test successful transcription. Mock `client.audio.transcriptions.create`.
    2.  [ ] Task: Test with `OPENAI_API_KEY` not set. Expect `None`.
    3.  [ ] Task: Test with audio file not found. Expect `None`.
    4.  [ ] Task: Test with audio file too large (>25MB). Expect `None`.
    5.  [ ] Task: Test API call failure (mock `create` to raise exception). Expect `None`.

**File: `supabase_utils.py`**

1.  **`get_supabase_client` Function Tests:**
    1.  [ ] Task: Mock `os.getenv` for `SUPABASE_URL` and `SUPABASE_ANON_KEY`. Verify `create_client` is called.
    2.  [ ] Task: Test raises `ValueError` if URL or key is missing.

2.  **`generate_document_url` Function Tests:**
    *   **Setup:** Mock `create_client` and its storage methods. Mock `S3StorageManager`.
    1.  [ ] Task: Test with S3 path (`s3://...`). Verify `S3StorageManager.generate_presigned_url_for_ocr` is called.
    2.  [ ] Task: Test with Supabase path (`bucket/path` or `path` assuming default bucket).
        *   Test with `use_signed_url=True`. Mock `client.storage.from_().create_signed_url()`.
        *   Test with `use_signed_url=False`. Mock `client.storage.from_().get_public_url()`.
    3.  [ ] Task: Test with an already fully qualified HTTP/HTTPS URL. Verify it's returned directly.
    4.  [ ] Task: Test various Supabase path formats (e.g., "uploads/filename", "documents/uploads/filename").
    5.  [ ] Task: Test exception handling.

3.  **`SupabaseManager` Class Tests:**
    *   **`__init__` Method Tests:**
        1.  [ ] Task: Mock `create_client`. Verify `self.client` and `self.service_client` are initialized.
        2.  [ ] Task: Test with `SUPABASE_SERVICE_ROLE_KEY` present and absent.
        3.  [ ] Task: Test raises `ValueError` if URL/key missing.

    *   **Project Management (`get_or_create_project`) Tests:**
        1.  [ ] Task: Test project exists: mock `self.client.table('projects').select().eq().execute()` to return data. Verify existing project data is used. Test Pydantic model creation.
        2.  [ ] Task: Test project does not exist: mock select to return empty data, then mock insert. Verify new project is created with `ProjectModel`. Test UUID generation if `project_id` is not a valid UUID.
        3.  [ ] Task: Test Pydantic validation error for existing project. Verify fallback.

    *   **Source Document Management (`create_source_document_entry`, `update_source_document_text`) Tests:**
        1.  [ ] Task: Test `create_source_document_entry`: mock insert. Verify `SourceDocumentModel` is used and correct data returned.
        2.  [ ] Task: Test `update_source_document_text`: mock update. Test with/without `ocr_meta_json`. Handle potential trigger error warning.

    *   **Neo4j Document Management (`create_neo4j_document_entry`, etc.) Tests:**
        1.  [ ] Task: Test `create_neo4j_document_entry`: mock insert. Verify `documentId` is `source_doc_uuid`.
        2.  [ ] Task: Test `update_neo4j_document_details`, `update_neo4j_document_status`: mock updates.

    *   **Chunk Management (`create_chunk_entry`, `update_chunk_metadata`) Tests:**
        1.  [ ] Task: Test `create_chunk_entry`: mock insert. Verify `ChunkModel` like structure.
        2.  [ ] Task: Test `update_chunk_metadata`: mock update.

    *   **Entity Management (`create_entity_mention_entry`, `create_canonical_entity_entry`, etc.) Tests:**
        1.  [ ] Task: Test creation methods: mock insert. Verify `EntityMentionModel`/`CanonicalEntityModel` like structure.
        2.  [ ] Task: Test `update_entity_mention_with_canonical_id` (currently a pass).

    *   **Relationship Management (`create_relationship_staging`) Tests:**
        1.  [ ] Task: Test `create_relationship_staging`: mock `self.service_client.table().insert()`. Test with/without properties.

    *   **Helper Methods (`_is_valid_uuid`, `get_public_url_for_document`, etc.) Tests:**
        1.  [ ] Task: Test `_is_valid_uuid` with valid and invalid UUID strings.
        2.  [ ] Task: Test `get_public_url_for_document` (similar to standalone `generate_document_url` but uses instance client).
        3.  [ ] Task: Test `get_project_by_sql_id_or_global_project_id` scenarios.

    *   **Batch Operations and Queries (`get_pending_documents`, etc.) Tests:**
        1.  [ ] Task: Test `get_pending_documents`.
        2.  [ ] Task: Test `get_documents_for_entity_extraction` (mock multiple select calls).
        3.  [ ] Task: Test `update_processing_status` for different tables.
        4.  [ ] Task: Test `log_processing_error`.
        5.  [ ] Task: Test `get_document_by_id`.

    *   **Textract Job Management Methods Tests:**
        1.  [ ] Task: Test `create_textract_job_entry`: mock insert. Verify data.
        2.  [ ] Task: Test `update_textract_job_status`: mock update. Test status mapping.
        3.  [ ] Task: Test `get_textract_job_by_job_id`: mock select.
        4.  [ ] Task: Test `update_source_document_with_textract_outcome`: mock update. Test various payload combinations and status mapping. Test duration calculation. Test retry logic for Supabase update.

    *   **Database Cleanup Methods (`cleanup_all_data`, `cleanup_project_data`) Tests:**
        *   **Caution:** These are destructive. Ensure tests run against a mock or test DB.
        1.  [ ] Task: Test `cleanup_all_data` requires `confirm=True`. Mock delete calls for all tables in order. Verify counts. Test Redis flush if available.
        2.  [ ] Task: Test `cleanup_project_data`: mock select and delete calls. Verify correct data for the project is targeted.

    *   **Image Processing Helper Methods Tests:**
        1.  [ ] Task: Test `update_image_processing_status`: mock update.
        2.  [ ] Task: Test `store_image_processing_result`: mock update with full image processing data.
        3.  [ ] Task: Test `get_image_processing_costs`, `get_image_processing_stats`, `get_failed_image_documents`: mock select calls and verify calculations/filtering.

    *   **Enhanced Batch Operations with Pydantic Models Tests:**
        1.  [ ] Task: Test `get_pending_documents_as_models`: mock select. Verify Pydantic model creation and validation error handling.
        2.  [ ] Task: Test `batch_create_chunks`: mock batch insert. Verify Pydantic models.
        3.  [ ] Task: Test `batch_update_processing_status`: mock batch updates.
        4.  [ ] Task: Test `get_documents_with_chunks_as_models`: mock multiple select calls. Verify Pydantic models.

**File: `config.py`**

1.  **`StageConfig` Class Tests:**
    1.  [ ] Task: Test `_build_stage_config` returns correct dictionary for `STAGE_CLOUD_ONLY`.
    2.  [ ] Task: Test for `STAGE_HYBRID`.
    3.  [ ] Task: Test for `STAGE_LOCAL_PROD`.
    4.  [ ] Task: Test `validate_requirements`:
        *   Mock `os.getenv("OPENAI_API_KEY")`.
        *   Test raises `ValueError` if required keys are missing for a stage.
        *   Test passes if keys are present.

2.  **`validate_deployment_stage` Function Tests:**
    *   **Setup:** Mock `os.getenv("DEPLOYMENT_STAGE")`.
    1.  [ ] Task: Test with valid stages (`STAGE_CLOUD_ONLY`, `STAGE_HYBRID`, `STAGE_LOCAL_PROD`).
    2.  [ ] Task: Test with an invalid stage string. Expect `ValueError`.
    3.  [ ] Task: Test with `DEPLOYMENT_STAGE` not set (defaults to `STAGE_CLOUD_ONLY`).

3.  **`get_redis_config_for_stage` Function Tests:**
    *   **Setup:** Mock `os.getenv` for Redis related variables.
    1.  [ ] Task: Test for `STAGE_CLOUD_ONLY`. Verify correct host/port/ssl.
    2.  [ ] Task: Test for `STAGE_HYBRID`.
    3.  [ ] Task: Test for `STAGE_LOCAL_PROD`.

4.  **`validate_cloud_services` Function Tests:**
    *   **Setup:** Mock `os.getenv` for `OPENAI_API_KEY`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION`.
    *   Mock `USE_OPENAI_FOR_ENTITY_EXTRACTION`, `USE_OPENAI_FOR_STRUCTURED_EXTRACTION`.
    1.  [ ] Task: Test when OpenAI services are enabled but key is missing.
    2.  [ ] Task: Test when AWS credentials are missing.
    3.  [ ] Task: Test when all required cloud service configs are present.

5.  **`get_stage_info` Function Tests:**
    1.  [ ] Task: Call the function and verify the structure of the returned dictionary for a known stage.

6.  **`reset_stage_config` and `set_stage_for_testing` Function Tests:**
    1.  [ ] Task: Test `set_stage_for_testing` correctly changes `DEPLOYMENT_STAGE` and related global config flags.
    2.  [ ] Task: Test `reset_stage_config` reverts to environment-defined stage and re-applies logic.
    3.  [ ] Task: Verify that after `set_stage_for_testing`, relevant global flags (e.g., `FORCE_CLOUD_LLMS`) are updated according to the new stage's config.

**File: `entity_resolution.py` (Legacy)**

1.  **`_generate_resolution_cache_key` Function Tests:**
    *   (This is likely superseded by the one in `entity_resolution_enhanced.py`. If still used, test as per the enhanced version.)

2.  **`resolve_document_entities` Function Tests:**
    *   **Setup:** Mock `OpenAI` client, `get_redis_manager`, `rate_limit` behavior if applicable.
    1.  [ ] Task: Test fallback to `_fallback_resolution` if `LLM_API_KEY` is missing or invalid.
    2.  [ ] Task: Test successful LLM call (mock `client.chat.completions.create`).
        *   Verify prompt structure.
        *   Verify JSON parsing from LLM output (including handling of potential markdown wrappers).
        *   Verify `EntityResolutionResultModel` is correctly populated with `CanonicalEntity` instances.
    3.  [ ] Task: Test Redis cache hit and miss.
    4.  [ ] Task: Test LLM API error. Verify fallback or error state.
    5.  [ ] Task: Test invalid JSON from LLM. Verify fallback.
    6.  [ ] Task: Test when `entity_mentions_for_doc` is empty.

3.  **`_fallback_resolution` Function Tests:**
    1.  [ ] Task: Test with a list of `entity_mentions_for_doc`.
        *   Verify each mention becomes a `CanonicalEntity`.
        *   Verify `updated_mentions` have `resolved_canonical_id_temp`.
        *   Verify `EntityResolutionResultModel` structure.

**File: `entity_extraction.py` (Legacy, where `extract_entities_from_chunk` is primary)**

1.  **`extract_entities_from_chunk` Function Tests:**
    *   **Setup:** Mock `extract_entities_openai`, `extract_entities_local_ner`.
    1.  [ ] Task: Test with `use_openai=True`. Verify `extract_entities_openai` is called.
    2.  [ ] Task: Test with `use_openai=False` (or `None` and default config leads to local).
        *   Verify `extract_entities_local_ner` is called.
        *   Mock `extract_entities_local_ner` to raise an error, then verify `extract_entities_openai` is called as fallback.
    3.  [ ] Task: Test with empty `chunk_text`. Expect skipped status.
    4.  [ ] Task: Verify `EntityExtractionResultModel` is populated correctly from the results of the called function.
    5.  [ ] Test conversion of raw entity data to `ExtractedEntity` models, including error handling for individual entities.

2.  **`_generate_entity_cache_key` Function Tests:**
    1.  [ ] Task: Test consistency and uniqueness.

3.  **`extract_entities_openai` Function Tests:**
    *   **Setup:** Mock `OpenAI` client, `get_redis_manager` (for cache decorator), `rate_limit`.
    1.  [ ] Task: Test with `OPENAI_API_KEY` not set. Expect empty list.
    2.  [ ] Task: Test successful API call.
        *   Verify prompt structure.
        *   Verify `response_format={"type": "json_object"}`.
        *   Mock `client.chat.completions.create` to return sample JSON.
        *   Verify JSON parsing and mapping to schema entity types.
        *   Verify basic attribute extraction (email, phone, date normalization).
    3.  [ ] Task: Test API returns no choices or no message.
    4.  [ ] Task: Test API returns malformed JSON or non-JSON text. Test extraction from markdown code blocks.
    5.  [ ] Task: Test `redis_cache` decorator behavior (hit/miss).
    6.  [ ] Task: Test `rate_limit` decorator behavior (mock it or test its effects indirectly).

4.  **`extract_entities_local_ner` Function Tests:**
    *   **Setup:** Mock `get_ner_pipeline`, `dateparser.parse`.
    1.  [ ] Task: Test with `NER_PIPELINE` not available. Expect `ValueError`.
    2.  [ ] Task: Test successful NER extraction. Mock `NER_PIPELINE()` to return sample results.
        *   Verify mapping of model labels to `ENTITY_TYPE_SCHEMA_MAP`.
        *   Verify date extraction logic (regex + dateparser) and handling of overlaps.
        *   Verify attribute extraction (email, phone, normalized_date).
    3.  [ ] Task: Test NER pipeline raising an error.
    4.  [ ] Task: Test `redis_cache` decorator behavior.

**File: `monitor.py`**

1.  **`SimpleMonitor` Class Tests:**
    *   **`__init__` Method Tests:**
        1.  [ ] Task: Mock `create_client` (Supabase), `redis_lib.Redis`, `Celery`. Verify clients are initialized.
        2.  [ ] Task: Test raises `ValueError` if Supabase URL/Key are missing.
    *   **`get_pipeline_stats` Method Tests:**
        1.  [ ] Task: Mock `self.supabase.table().select().execute()` for `source_documents`.
        2.  [ ] Task: Verify calculation of `status_counts`, `recent_failures`, `total_documents`.
        3.  [ ] Task: Test Supabase call failure.
    *   **`get_celery_stats` Method Tests:**
        1.  [ ] Task: Mock `self.celery_app.control.inspect()` and its methods (`active`, `stats`, `registered`).
        2.  [ ] Task: Verify returned dictionary structure.
        3.  [ ] Task: Test Celery inspect call failure.
    *   **`get_redis_stats` Method Tests:**
        1.  [ ] Task: Mock `self.redis_client.info()` and `self.redis_client.scan_iter()`.
        2.  [ ] Task: Verify hit rate calculation and key counts.
        3.  [ ] Task: Test Redis call failure.

2.  **CLI Command Tests (using `click.testing.CliRunner`):**
    *   For `pipeline`, `workers`, `redis_cache`, `document @<doc_id>` commands:
        1.  [ ] Task: Instantiate `CliRunner`.
        2.  [ ] Task: Mock `SimpleMonitor` and its methods called by the command.
        3.  [ ] Task: Invoke the command using `runner.invoke(cli_module.<command_name>, [...args])`.
        4.  [ ] Task: Assert `result.exit_code == 0`.
        5.  [ ] Task: Assert expected output is present in `result.output` (e.g., table titles, key stats).
        6.  [ ] Task: For `document` command, test with existing and non-existing `document_id`.

**File: `admin.py`**

1.  **`get_supabase_client` Function Tests:** (Covered in `supabase_utils.py` tests)

2.  **CLI Command Tests (using `click.testing.CliRunner`):**
    *   **Setup:** Mock `get_supabase_client()` to return a mock Supabase client. Mock the chain of Supabase client methods (`table().select()...execute()`, `table().update()...execute()`, etc.) for each command.
    *   **`documents list` Tests:**
        1.  [ ] Task: Test with no status filter and with a status filter.
        2.  [ ] Task: Test with no documents found.
        3.  [ ] Task: Verify table output format.
    *   **`documents reset <uuid>` Tests:**
        1.  [ ] Task: Test successful reset. Verify Supabase update call.
        2.  [ ] Task: Test Supabase update failure.
    *   **`documents stuck --minutes <m>` Tests:**
        1.  [ ] Task: Test when stuck documents are found. Verify table output.
        2.  [ ] Task: Test when no stuck documents are found.
    *   **`documents stats` Tests:**
        1.  [ ] Task: Test statistics calculation and table output.
        2.  [ ] Task: Test with no documents.
    *   **`documents failures --hours <h>` Tests:**
        1.  [ ] Task: Test when failures are found. Verify table output.
        2.  [ ] Task: Test when no failures are found.
    *   **`cleanup history --days <d>` Tests:**
        1.  [ ] Task: Test with `--dry-run`. Verify no delete call.
        2.  [ ] Task: Test actual deletion (mock `click.confirm` to return `True`). Verify Supabase delete call.
        3.  [ ] Task: Test with no old records found.
    *   **`cleanup orphans` Tests:**
        1.  [ ] Task: Test finding orphaned chunks and mentions.
        2.  [ ] Task: Test deletion of orphans (mock `click.confirm`).
    *   **`batch reset-failed --status <s>` Tests:**
        1.  [ ] Task: Test with `--dry-run`.
        2.  [ ] Task: Test actual reset (mock `click.confirm`). Verify multiple Supabase update calls.
        3.  [ ] Task: Test with no documents matching status.
    *   **`batch reset-project <id>` Tests:**
        1.  [ ] Task: Test finding documents and prompting for reset.
        2.  [ ] Task: Test actual reset (mock `click.confirm`).
        3.  [ ] Task: Test with no documents in project.

**File: `import.py`**

1.  **`TypeSafeImporter` Class Tests:**
    *   **`__init__` Method Tests:**
        1.  [ ] Task: Mock `SupabaseManager`, `S3StorageManager`, `CacheManager`. Verify instances are created.
    *   **`validate_manifest` Method Tests:**
        *   **Setup:** Create sample manifest files (valid and invalid JSON, valid and invalid Pydantic structure). Mock `Path.exists`. Mock `_estimate_processing_cost`.
        1.  [ ] Task: Test with a valid manifest file. Verify `ImportValidationResultModel` with `is_valid=True`.
        2.  [ ] Task: Test with manifest file not found.
        3.  [ ] Task: Test with invalid JSON in manifest.
        4.  [ ] Task: Test with manifest data failing `ImportManifestModel` Pydantic validation (e.g., missing `metadata.case_name`). Verify detailed error messages.
        5.  [ ] Task: Test additional validations:
            *   Missing files in `manifest.files` (mock `Path(base_path / file_info.path).exists()`).
            *   Duplicate file hashes.
            *   Large files.
    *   **`_estimate_processing_cost` Method Tests:**
        1.  [ ] Task: Test with a sample `ImportManifestModel` containing various file types and sizes. Verify cost calculation.
    *   **`create_import_session` Method Tests:**
        *   **Setup:** Mock `self.db.client.table().select().eq().execute()` for project lookup and `insert().execute()` for session creation.
        1.  [ ] Task: Test successful session creation. Verify `ImportSessionModel` data and DB insert.
        2.  [ ] Task: Test when project UUID is not found. Expect `ValueError`.
        3.  [ ] Task: Test DB insert failure.
    *   **`import_document` Method Tests:**
        *   **Setup:** Mock `self.s3_manager.upload_document_with_uuid_naming`, `self.db.client.table().insert/update().execute()`, `process_ocr.delay`, `self.cache_manager.set_cached_document`. Create a temp file using `tmp_path`.
        1.  [ ] Task: Test successful document import and Celery task submission.
            *   Verify S3 upload is called.
            *   Verify `SourceDocumentModel` and `DocumentMetadata` are correctly populated.
            *   Verify DB insert for `source_documents`.
            *   Verify Celery task `process_ocr.delay` is called with correct arguments.
            *   Verify DB update with `celery_task_id`.
            *   Verify cache update.
            *   Verify returned dictionary.
        2.  [ ] Task: Test with file not found at `base_path / file_info.path`. Expect failure.
        3.  [ ] Task: Test S3 upload failure. Expect failure.
        4.  [ ] Task: Test DB insert failure. Expect failure.
        5.  [ ] Task: Test Celery submission failure. Expect failure (or handle as appropriate).

2.  **CLI Command Tests (using `click.testing.CliRunner`):**
    *   **Setup:** Mock `TypeSafeImporter` and its methods.
    *   **`from_manifest` Tests:**
        1.  [ ] Task: Test manifest validation success path.
        2.  [ ] Task: Test manifest validation failure path. Verify error output.
        3.  [ ] Task: Test `--validate-only` flag.
        4.  [ ] Task: Test `--dry-run` flag.
        5.  [ ] Task: Test actual import flow:
            *   Mock `click.confirm` to return `True`.
            *   Mock `importer.create_import_session` and `importer.import_document`.
            *   Verify batching logic and progress messages.
            *   Verify session status update at the end.
            *   Verify summary output.
        6.  [ ] Task: Test import failure for some documents. Verify error logging and summary.
    *   **`from_directory` Tests:**
        *   **Setup:** Create a temporary directory structure with sample files using `tmp_path`.
        1.  [ ] Task: Test directory scanning with and without `--recursive`.
        2.  [ ] Task: Test `--file-types` filtering.
        3.  [ ] Task: Test when no matching files are found.
        4.  [ ] Task: Test temporary manifest creation and validation.
        5.  [ ] Task: Test invocation of `from_manifest` logic by mocking `ctx.invoke`.

**File: `db_migration_helper.py`**

1.  **`ValidationResult` and `MigrationReport` Dataclass Tests:**
    1.  [ ] Task: Test `ValidationResult` instantiation and default `errors`, `warnings`, `suggested_fixes`.
    2.  [ ] Task: Test `MigrationReport` instantiation and `success_rate` property.
    3.  [ ] Task: Test `MigrationReport.get_errors_by_table` method.

2.  **`DatabaseMigrationHelper` Class Tests:**
    *   **`__init__` Method Tests:**
        1.  [ ] Task: Verify `self.client` is set.
    *   **`validate_table_data` Method Tests:**
        *   **Setup:** Mock `self.client.table().select().range().execute()` or `limit().execute()`.
        1.  [ ] Task: Test with a table name not in `TABLE_MODEL_MAPPING`. Expect `ValueError`.
        2.  [ ] Task: Test with valid records. Mock `_validate_record` to return valid results.
        3.  [ ] Task: Test with invalid records. Mock `_validate_record` to return invalid results.
        4.  [ ] Task: Test Supabase query failure. Verify error result for the table.
        5.  [ ] Task: Test with `limit` argument.
    *   **`_validate_record` Method Tests:**
        *   **Setup:** Mock `create_model_from_db`.
        1.  [ ] Task: Test with data that successfully creates a Pydantic model.
        2.  [ ] Task: Test with data that causes `ValidationError` from `create_model_from_db`.
            *   Verify errors are parsed and `suggested_fixes` are generated (mock `_suggest_fix`).
        3.  [ ] Task: Test with `create_model_from_db` raising a generic `Exception`.
    *   **`_suggest_fix` Method Tests:**
        1.  [ ] Task: Test for each known `error_type` (e.g., 'value_error.uuid', 'type_error.datetime').
        2.  [ ] Task: Test with an unknown `error_type`. Expect `None`.
    *   **`validate_all_tables` Method Tests:**
        1.  [ ] Task: Mock `self.validate_table_data`.
        2.  [ ] Task: Test with default tables and `sample_size`.
        3.  [ ] Task: Test with a specific list of `tables`.
        4.  [ ] Task: Verify `MigrationReport` structure and content.
    *   **`generate_migration_script` Method Tests:**
        1.  [ ] Task: Provide a sample `MigrationReport`. Verify SQL script content and structure. Mock file write.
    *   **`export_validation_report` Method Tests:**
        1.  [ ] Task: Provide a sample `MigrationReport`. Verify JSON output structure. Mock file write.
    *   **`fix_common_issues` Method Tests:**
        1.  [ ] Task: Test (currently a placeholder, verify logging for dry_run).

3.  **Utility Function Tests (`validate_single_table`, `quick_validation_check`):**
    *   **Setup:** Mock `DatabaseMigrationHelper` methods.
    1.  [ ] Task: Test `validate_single_table`.
    2.  [ ] Task: Test `quick_validation_check`. Verify success rates calculation.

**File: `task_models.py` (Pydantic Models)**

*   For each Pydantic model in the file (e.g., `BaseTaskPayload`, `OCRTaskPayload`, `OCRTaskResult`, `TaskProgressUpdate`):
    1.  [ ] Task: Test successful instantiation with valid data, including all required fields and representative optional fields.
    2.  [ ] Task: Test instantiation fails (`ValidationError`) if required fields are missing.
    3.  [ ] Task: Test specific validators if present (e.g., `ensure_task_id` in `BaseTaskPayload`, `validate_provider` in `OCRTaskPayload`, `set_completion_time` and `calculate_duration` in `BaseTaskResult`, `set_dimensions` in `EmbeddingGenerationTaskResult`).
    4.  [ ] Task: Test `model_config` behavior for `json_encoders` (e.g., `datetime` to ISO string, `uuid.UUID` to string).
    5.  [ ] Task: Test properties if present (e.g., `success_rate` in `BatchProcessingTaskResult`).
    6.  [ ] Task: Test enum fields with valid and invalid enum values.
*   **`create_task_payload` Factory Function Tests:**
    1.  [ ] Task: Test creating payload for each known `task_type`. Verify correct Pydantic model instance is returned.
    2.  [ ] Task: Test with an unknown `task_type`. Expect `ValueError`.
*   **`create_task_result` Factory Function Tests:**
    1.  [ ] Task: Test creating result for each known `task_type`.
    2.  [ ] Task: Test with an unknown `task_type`. Expect `ValueError`.

**File: `cache_models.py` (Pydantic Models)**

*   **`CacheMetadataModel` Tests:**
    1.  [ ] Task: Test successful instantiation.
    2.  [ ] Task: Test `expires_at` validator logic (set from `ttl_seconds`).
    3.  [ ] Task: Test `is_expired` property (mock `datetime.now()` or set `expires_at` in past/future).
    4.  [ ] Task: Test `status` property.
    5.  [ ] Task: Test `update_access` method (increments `hit_count`, updates `last_accessed`).
*   **`BaseCacheModel` Tests:**
    1.  [ ] Task: Test successful instantiation.
    2.  [ ] Task: Test `is_valid` method (delegates to `metadata.is_expired`).
*   For each specific cache model (e.g., `CachedProjectModel`, `CachedDocumentModel`):
    1.  [ ] Task: Test successful instantiation with required fields.
    2.  [ ] Task: Test its `create` (or `create_with_metadata`) classmethod:
        *   Verify correct `CacheMetadataModel` is generated (cache_key, ttl, source, tags).
        *   Verify the main model data is populated.
    3.  [ ] Task: Test any properties defined on the model.
*   **`create_cache_key` Function Tests:**
    1.  [ ] Task: Test with prefix and various `args`. Verify key format.
*   **`get_cache_tags` Function Tests:**
    1.  [ ] Task: Test with `model_type`, `entity_id`, and `kwargs`. Verify tag list.
*   **`CacheInvalidationModel` Tests:**
    1.  [ ] Task: Test successful instantiation.

**File: `processing_models.py` (Pydantic Models)**

*   **`BaseProcessingResult` Tests:**
    1.  [ ] Task: Test successful instantiation, default `processing_timestamp` and `status`.
*   **`OCRPageResult` and `OCRResultModel` Tests:**
    1.  [ ] Task: Test `OCRPageResult` confidence validator.
    2.  [ ] Task: Test `OCRResultModel` validators (`calculate_average_confidence`, `combine_page_text`).
*   **Image Processing Models (`DetectedObject`, `ImageAnalysisResult`, `ImageProcessingResultModel`) Tests:**
    1.  [ ] Task: Test instantiation. Test `ImageProcessingResultModel.combine_extracted_text` validator.
*   **Audio Transcription Models (`TranscriptionSegment`, `AudioTranscriptionResultModel`) Tests:**
    1.  [ ] Task: Test instantiation. Test `AudioTranscriptionResultModel.combine_segments` validator.
*   **Entity Extraction Models (`ExtractedEntity`, `EntityExtractionResultModel`) Tests:**
    1.  [ ] Task: Test `ExtractedEntity.confidence_level` property.
    2.  [ ] Task: Test `EntityExtractionResultModel` validators (`count_entities`, `collect_entity_types`, `count_high_confidence`).
*   **Chunking Models (`ChunkMetadata`, `ProcessedChunk`, `ChunkingResultModel`) Tests:**
    1.  [ ] Task: Test `ProcessedChunk.estimate_tokens` validator.
    2.  [ ] Task: Test `ChunkingResultModel` validators (`count_chunks`, `calculate_average_size`).
*   **Embedding Models (`EmbeddingResultModel`) Tests:**
    1.  [ ] Task: Test `EmbeddingResultModel` validators (`set_dimensions`, `validate_embedding`).
*   **Batch Processing Models (`BatchProcessingResultModel`) Tests:**
    1.  [ ] Task: Test `success_rate` property and `add_result` method.
*   **Structured Extraction Models (`DocumentMetadata`, `KeyFact`, `EntitySet`, etc.) Tests:**
    1.  [ ] Task: Test `DocumentMetadata.parse_date` validator.
    2.  [ ] Task: Test `EntitySet` properties (`total_entities`, `entity_types_present`).
    3.  [ ] Task: Test `StructuredChunkData` properties (`has_content`, `extraction_summary`).
    4.  [ ] Task: Test `StructuredExtractionResultModel` properties (`has_structured_data`, `extraction_completeness`).
*   **Entity Resolution Models (`CanonicalEntity`, `EntityResolutionResultModel`) Tests:**
    1.  [ ] Task: Test `CanonicalEntity.confidence_level` property.
    2.  [ ] Task: Test `EntityResolutionResultModel.resolution_ratio` property.
*   **Relationship Building Models (`StagedRelationship`, `RelationshipBuildingResultModel`) Tests:**
    1.  [ ] Task: Test `StagedRelationship.relationship_signature` property.
    2.  [ ] Task: Test `RelationshipBuildingResultModel.relationship_types` property.
*   **Import Operation Models (`ImportMetadataModel`, `ImportFileModel`, etc.) Tests:**
    1.  [ ] Task: Test validators (e.g., `ImportMetadataModel.validate_base_path`, `ImportFileModel.validate_file_type`, `ImportConfigModel.validate_batch_size`).
    2.  [ ] Task: Test properties (e.g., `ImportManifestModel.total_size`, `ImportProgressModel.progress_percentage`, `ImportSummaryModel.success_rate`).

**File: `error_handler.py`**

1.  **`ErrorHandler` Class Tests:**
    *   **`__init__` Method Tests:**
        1.  [ ] Task: Mock `SupabaseManager`. Verify it's initialized.
    *   **`analyze_error` Method Tests:**
        1.  [ ] Task: Test with error messages matching each pattern in `ERROR_PATTERNS`. Verify correct category, strategy, delay, and retries are returned.
        2.  [ ] Task: Test with an error message not matching any pattern. Verify 'unknown' category and default retry strategy.
        3.  [ ] Task: Verify `stacktrace` is included.
    *   **`log_error` Method Tests:**
        *   **Setup:** Mock `self.db_manager.client.table().select().eq().execute()` and `insert().execute()`.
        1.  [ ] Task: Test successful error logging to `document_processing_history`. Verify `error_details` and `metadata` JSON structure.
        2.  [ ] Task: Test when `document_uuid` is not found in DB.
        3.  [ ] Task: Test Supabase insert failure.
    *   **`get_error_summary` Method Tests:**
        *   **Setup:** Mock `self.db_manager.client.table().select().eq().gte().execute()`.
        1.  [ ] Task: Test with recent errors. Verify calculation of `total_errors`, `errors_by_stage`, `errors_by_category`.
        2.  [ ] Task: Test with no recent errors.
        3.  [ ] Task: Test Supabase query failure.
    *   **`get_recovery_candidates` Method Tests:**
        *   **Setup:** Mock `self.db_manager.client.table().select().in_().limit().execute()`.
        1.  [ ] Task: Test with documents matching retryable error categories.
        2.  [ ] Task: Test with documents matching non-retryable error categories.
        3.  [ ] Task: Test filtering by `error_category`.
    *   **`create_error_report` Method Tests:**
        1.  [ ] Task: Mock `self.get_error_summary` and `self.get_recovery_candidates`.
        2.  [ ] Task: Test JSON output format.
        3.  [ ] Task: Test text output format (call `_format_text_report`).
        4.  [ ] Task: Test with unsupported format.
    *   **`_generate_recommendations` Method Tests:**
        1.  [ ] Task: Test with different error summaries to trigger various recommendations.
    *   **`_format_text_report` Method Tests:**
        1.  [ ] Task: Provide a sample report dictionary and verify the formatted text output.

**File: `entity_processor.py`**

1.  **`EntityProcessor` Class Tests:**
    *   **`__init__` Method Tests:**
        1.  [ ] Task: Mock `SupabaseManager` and `get_redis_manager`. Verify initialization.
    *   **`get_entity_mentions_for_document` Method Tests:**
        *   **Setup:** Mock `self.redis_manager` methods, `self.db_manager.client` table calls.
        1.  [ ] Task: Test cache hit.
        2.  [ ] Task: Test cache miss and successful DB fetch and caching.
            *   Mock Supabase calls for `neo4j_documents`, `neo4j_chunks`, `neo4j_entity_mentions`.
        3.  [ ] Task: Test when no neo4j document or no chunks are found.
        4.  [ ] Task: Test Supabase query failure.
    *   **`get_canonical_entities` Method Tests:**
        1.  [ ] Task: Mock `self.db_manager.client.table('neo4j_canonical_entities').select()...execute()`.
        2.  [ ] Task: Test with `entity_ids` filter.
        3.  [ ] Task: Test with `project_id` filter.
        4.  [ ] Task: Test with no filters.
    *   **`get_entity_resolution_stats` Method Tests:**
        1.  [ ] Task: Mock `self.get_entity_mentions_for_document`.
        2.  [ ] Task: Test calculations for stats (total, resolved, unresolved, unique, rate, types).
        3.  [ ] Task: Test with no mentions.
    *   **`find_duplicate_entities` Method Tests:**
        1.  [ ] Task: Mock `self.get_canonical_entities`.
        2.  [ ] Task: Test with entities having same names and types.
        3.  [ ] Task: Test with entities having similar (substring) names and same types.
        4.  [ ] Task: Test with no duplicates.
        5.  [ ] Task: Test with less than 2 entities.
    *   **`merge_canonical_entities` Method Tests:**
        1.  [ ] Task: Mock `self.db_manager.client.table().update()...execute()` and `delete()...execute()`.
        2.  [ ] Task: Verify mentions are updated and entities are deleted.
        3.  [ ] Task: Mock Redis clear cache calls (if applicable, or log check).
    *   **`export_entities_for_project` Method Tests:**
        1.  [ ] Task: Mock `self.get_canonical_entities`.
        2.  [ ] Task: Test JSON output format.
        3.  [ ] Task: Test CSV output format (mock `csv.DictWriter`).
        4.  [ ] Task: Test with unsupported format.

**File: `document_processor.py`**

1.  **`DocumentProcessor` Class Tests:**
    *   **`__init__` Method Tests:**
        1.  [ ] Task: Mock `SupabaseManager`, `get_redis_manager`, `get_stage_info`. Verify initialization.
    *   **`get_document_by_uuid` and `get_document_by_id` Method Tests:**
        1.  [ ] Task: Mock `self.db_manager.client.table('source_documents').select().eq().execute()`.
        2.  [ ] Task: Test document found and not found.
    *   **`update_document_status` Method Tests:**
        1.  [ ] Task: Mock `self.db_manager.client.table('source_documents').update().eq().execute()`.
        2.  [ ] Task: Test with `error_message` and `additional_fields`.
    *   **`get_pending_documents`, `get_failed_documents`, `get_stuck_documents` Method Tests:**
        1.  [ ] Task: Mock Supabase select calls with appropriate filters. Verify data returned.
        2.  [ ] Task: For `get_failed_documents`, test with and without `stage` filter.
    *   **`reset_document_status` Method Tests:**
        1.  [ ] Task: Mock Supabase update call.
        2.  [ ] Task: Mock `self.redis_manager.client.delete`. Verify cache keys (using `CacheKeys`) are deleted.
    *   **`get_processing_stats` Method Tests:**
        1.  [ ] Task: Mock Supabase select call. Verify calculations for `total_documents`, `status_counts`, `status_percentages`.
    *   **`validate_document_file` Method Tests:**
        *   **Setup:** Mock `os.path.exists`, `os.access`, `os.path.getsize`.
        1.  [ ] Task: Test with a valid, existing, readable file.
        2.  [ ] Task: Test with a non-existing file.
        3.  [ ] Task: Test with an existing but unreadable file.
        4.  [ ] Task: Test exception during OS calls.

**File: `cache_manager.py`**

1.  **`CacheManager` Class Tests:**
    *   **`__init__` Method Tests:**
        1.  [ ] Task: Test with `redis_manager` provided and `None` (causes `RedisManager` instantiation). Mock `RedisManager` if instantiated internally.
    *   **`is_available` Property Tests:**
        1.  [ ] Task: Mock `self.redis.is_available()`.
    *   **Cache Clearing Methods (`clear_document_cache`, `clear_project_cache`) Tests:**
        *   **Setup:** Mock `self.redis.client.delete`. Mock `CacheKeys.format_key`.
        1.  [ ] Task: Verify correct keys (including versioned ones) are attempted for deletion.
        2.  [ ] Task: Test when cache is unavailable.
    *   **`get_cache_stats` Method Tests:**
        1.  [ ] Task: Mock `self.redis.client.info()` and `self._count_keys_by_pattern`.
        2.  [ ] Task: Verify returned dictionary structure and calculations.
        3.  [ ] Task: Test when cache is unavailable.
    *   **`_count_keys_by_pattern` Method Tests:**
        1.  [ ] Task: Mock `self.redis.client.scan_iter`. Verify counts for defined patterns.
    *   **`warm_cache_for_document` Method Tests:**
        *   **Setup:** Mock `SupabaseManager` and its client calls. Mock `self.redis.set_cached`.
        1.  [ ] Task: Test successful warming: OCR text and chunk list are cached.
        2.  [ ] Task: Test document not found.
        3.  [ ] Task: Test no chunks found.
        4.  [ ] Task: Test when cache is unavailable.
    *   **`invalidate_stale_cache` Method Tests:**
        1.  [ ] Task: Test (currently placeholder, verify logging).
    *   **`export_cache_keys` Method Tests:**
        1.  [ ] Task: Mock `self.redis.client.scan_iter`. Verify sorted list of keys returned.
    *   **Type-safe Cache Operations (e.g., `get_cached_document`, `set_cached_document`) Tests:**
        *   For each get/set pair:
            1.  [ ] Task: Mock underlying `self.redis.get_cached_model` or `set_cached_with_auto_invalidation`/`set_cached_model`.
            2.  [ ] Task: Test successful get/set with Pydantic models.
            3.  [ ] Task: For `set_`, verify `CacheKeys` usage and `Cached...Model.create_with_metadata` is called.
            4.  [ ] Task: For `set_cached_with_auto_invalidation`, verify invalidation tags.
    *   **Batch Operations (`batch_get_documents`, `batch_set_documents`) Tests:**
        1.  [ ] Task: Mock `self.redis.batch_get_cached_models` / `batch_set_cached_models`.
        2.  [ ] Task: Verify correct key mapping and model creation.
    *   **Enhanced Invalidation (`invalidate_document_cache`, etc. - these are specific implementations in `CacheManager`) Tests:**
        1.  [ ] Task: Mock `self.redis.invalidate_by_tag_sets`. Verify correct tags are passed.
    *   **`get_cache_health_status` Method Tests:**
        1.  [ ] Task: Mock `self.get_cache_stats`, `self.redis` model operations. Verify structure of health report.
    *   **`validate_cache_integrity` Method Tests:**
        1.  [ ] Task: Mock `self.redis.client.scan_iter` and `get`. Test JSON parsing, metadata validation, expired entry deletion.

**File: `schemas.py` (Pydantic Models)**

*   For each Pydantic model defined in the file (e.g., `BaseTimestampModel`, `ProjectModel`, `SourceDocumentModel`):
    1.  [ ] Task: Test successful instantiation with all fields populated correctly.
    2.  [ ] Task: Test instantiation with only required fields, relying on defaults for optional ones.
    3.  [ ] Task: Test instantiation fails (`ValidationError`) if required fields are missing.
    4.  [ ] Task: Test specific field validators (e.g., `parse_datetime` in `BaseTimestampModel`, `ensure_project_id` in `ProjectModel`, `parse_json_metadata` in `SourceDocumentModel`, `validate_embedding` in `ChunkModel`).
    5.  [ ] Task: Test model validators (`@model_validator`) if present (e.g., `validate_processing_status` in `SourceDocumentModel`, `validate_indices` in `ChunkModel`).
    6.  [ ] Task: Test `model_config` behavior for alias population (`populate_by_name=True`) and JSON encoders (datetime, UUID).
    7.  [ ] Task: Test `to_db_dict()` method, ensuring it produces a dictionary suitable for DB operations (check `by_alias` and `exclude_none` behavior).
    8.  [ ] Task: For Enum fields, test with valid and invalid enum string values.
*   **`create_model_from_db` Function Tests:**
    1.  [ ] Task: Test with valid database row data that matches a Pydantic model.
    2.  [ ] Task: Test with database row data containing `None` values for optional fields.
    3.  [ ] Task: Test with empty `data` dict. Expect `None`.
    4.  [ ] Task: Test with data that causes `ValidationError` during full validation, then verify it attempts validation with only required fields.
    5.  [ ] Task: Test with data that fails even minimal required field validation.

---
This detailed list should guide the agentic tool effectively. Remember to replace placeholders like "sample data" with concrete examples during actual test implementation.