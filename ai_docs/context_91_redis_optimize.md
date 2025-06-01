# Guide: Enhancing NLP Pipeline with Redis Streams & Optimizations

This guide outlines modifications to integrate Redis Streams for robust NLP pipeline orchestration and other Redis-related optimizations.

## I. Conceptual Overview of Redis Streams Integration

The document processing pipeline will be re-architected as a series of services, each consuming from an input Redis Stream and producing to an output Redis Stream.

**Current Flow (Simplified):**
`QueueProcessor` -> `process_single_document` (monolithic function calling sub-modules)

**Proposed Flow with Streams:**
1.  **Initial Intake:** `QueueProcessor` (or a new `IntakeService`) claims a document from Supabase queue. Instead of calling `process_single_document` directly, it adds a message to an initial Redis Stream, e.g., `tasks:ocr:pending`.
    *   Message: `{ "document_uuid": "...", "source_doc_sql_id": 123, "s3_key": "...", "file_type": ".pdf" }`
2.  **OCR Service:**
    *   Consumes from `tasks:ocr:pending`.
    *   Performs OCR.
    *   On success, produces to `tasks:cleaning-categorization:pending`.
        *   Message: `{ "document_uuid": "...", "source_doc_sql_id": 123, "raw_text_s3_key": "...", "ocr_metadata_s3_key": "..." }` (pointers to where text/metadata are stored)
    *   Acknowledges (`XACK`) message from `tasks:ocr:pending`.
3.  **Cleaning & Categorization Service:**
    *   Consumes from `tasks:cleaning-categorization:pending`.
    *   Performs cleaning & categorization.
    *   Produces to `tasks:chunking:pending`.
        *   Message: `{ "document_uuid": "...", "neo4j_doc_sql_id": 456, "cleaned_text_s3_key": "...", "doc_category": "..." }`
    *   Acknowledges message.
4.  **Chunking & Structured Extraction Service:**
    *   Consumes from `tasks:chunking:pending`.
    *   Performs chunking. Stores chunks in Supabase. Updates `neo4j_documents.metadata_json` with document-level structured data.
    *   Produces to `tasks:ner:pending`.
        *   Message: `{ "document_uuid": "...", "neo4j_doc_sql_id": 456, "chunk_count": N }` (signals NER service to fetch chunks from DB)
    *   Acknowledges message.
5.  **NER Service:**
    *   Consumes from `tasks:ner:pending`.
    *   Fetches chunks for the `neo4j_doc_sql_id` from Supabase.
    *   Extracts entities for each chunk, stores `neo4j_entity_mentions`.
    *   Produces to `tasks:resolution:pending`.
        *   Message: `{ "document_uuid": "...", "neo4j_doc_sql_id": 456, "mention_count": M }`
    *   Acknowledges message.
6.  **Entity Resolution Service:**
    *   Consumes from `tasks:resolution:pending`.
    *   Fetches mentions for `neo4j_doc_sql_id`. Performs resolution. Stores `neo4j_canonical_entities`.
    *   Produces to `tasks:relationships:pending`.
        *   Message: `{ "document_uuid": "...", "neo4j_doc_sql_id": 456, "canonical_count": C }`
    *   Acknowledges message.
7.  **Relationship Staging Service:**
    *   Consumes from `tasks:relationships:pending`.
    *   Builds and stages relationships.
    *   Produces to `tasks:processing:completed` (or similar terminal stream).
        *   Message: `{ "document_uuid": "...", "neo4j_doc_sql_id": 456, "status": "success" }`
    *   Acknowledges message.

**Stream Naming Convention:** `tasks:<stage-name>:<status>` (e.g., `tasks:ocr:pending`, `tasks:ocr:dlq`)
**Consumer Group Name:** `<stage-name>-group` (e.g., `ocr-service-group`)

## II. Redis Configuration (Using `redis-cli`)

Connect to your Redis instance:
`redis-cli -h <your-redis-host> -p <your-redis-port> [-a <your-password>]`

Execute the following commands:

1.  **Set Max Memory and Eviction Policy (Adjust `512mb` as needed):**
    ```bash
    CONFIG SET maxmemory 512mb
    CONFIG SET maxmemory-policy allkeys-lru
    ```
    *   `maxmemory`: Prevents Redis from consuming all system memory.
    *   `maxmemory-policy allkeys-lru`: When memory limit is reached, evicts least recently used keys. Good for caches. `volatile-lru` is an alternative if you only want to evict keys with TTLs.

2.  **Enable AOF Persistence (Append Only File) for Durability:**
    ```bash
    CONFIG SET appendonly yes
    CONFIG SET appendfsync everysec
    ```
    *   `appendonly yes`: Enables AOF. RDB snapshots are good for backups, but AOF provides better durability for Streams.
    *   `appendfsync everysec`: `fsync` data to disk every second. Balances performance and durability. (`always` is safer but slower).

3.  **Configure AOF Rewrite for Managing AOF File Size:**
    ```bash
    CONFIG SET auto-aof-rewrite-percentage 100
    CONFIG SET auto-aof-rewrite-min-size 64mb
    ```
    *   Rewrites the AOF file when it grows by 100% since last rewrite and is at least 64MB.

4.  **Slow Log Configuration (for debugging performance issues):**
    ```bash
    CONFIG SET slowlog-log-slower-than 10000
    CONFIG SET slowlog-max-len 128
    ```
    *   `slowlog-log-slower-than 10000`: Log commands taking longer than 10,000 microseconds (10ms).
    *   `slowlog-max-len 128`: Keep the last 128 slow log entries.

5.  **Keyspace Notifications (Optional, useful for advanced monitoring/triggering):**
    ```bash
    CONFIG SET notify-keyspace-events KEA
    ```
    *   `KEA`: Enables notifications for (K)eyspace, (E)xpired, (A)ll commands. Can be resource-intensive. Use `Ex` for just expired keys if that's all you need.

6.  **Save Configuration Changes:**
    ```bash
    CONFIG REWRITE
    ```
    *   This writes the current configuration to your `redis.conf` file, making changes permanent across restarts.

**Note:** For cloud-managed Redis (like ElastiCache or Redis Cloud), some of these settings might be managed through the cloud provider's console or API and `CONFIG SET` might be restricted.

## III. Step-by-Step Implementation Guide (for Agentic Coding Tool)

### A. Modify `redis_utils.py`

**Goal:** Add helper functions for Redis Streams.

1.  **Add Stream Constants:**
    ```python
    # At the top of redis_utils.py, with other constants
    STREAM_MAX_LEN = 10000  # Approximate max length for streams before trimming
    STREAM_READ_COUNT = 10  # How many messages to read at a time
    STREAM_BLOCK_MS = 5000  # Block for 5 seconds when reading
    ```

2.  **Add `produce_to_stream` function:**
    ```python
    # In RedisManager class
    def produce_to_stream(self, stream_name: str, message_data: Dict[str, Any], max_len: Optional[int] = None) -> Optional[str]:
        """Produce a message to a Redis Stream."""
        if not self.is_available():
            logger.error("Redis not available, cannot produce to stream.")
            return None
        try:
            client = self.get_client()
            # Ensure all message_data values are strings, bytes, int, or float for XADD
            cleaned_message_data = {
                k: (json.dumps(v) if isinstance(v, (dict, list)) else v)
                for k, v in message_data.items()
            }
            msg_id = client.xadd(
                stream_name,
                cleaned_message_data,
                maxlen=max_len if max_len is not None else STREAM_MAX_LEN,
                approximate=True # Needed if maxlen is used
            )
            logger.debug(f"Produced message {msg_id} to stream {stream_name}: {message_data}")
            return msg_id
        except Exception as e:
            logger.error(f"Error producing to stream {stream_name}: {e}")
            return None
    ```

3.  **Add `create_consumer_group` function:**
    ```python
    # In RedisManager class
    def create_consumer_group(self, stream_name: str, group_name: str, create_stream_if_not_exists: bool = True) -> bool:
        """Create a consumer group for a stream. Idempotent."""
        if not self.is_available():
            logger.error("Redis not available, cannot create consumer group.")
            return False
        try:
            client = self.get_client()
            client.xgroup_create(
                name=stream_name,
                groupname=group_name,
                id='0',  # Start from the beginning of the stream
                mkstream=create_stream_if_not_exists
            )
            logger.info(f"Consumer group {group_name} ensured for stream {stream_name}.")
            return True
        except redis.exceptions.ResponseError as e:
            if "BUSYGROUP" in str(e):
                logger.debug(f"Consumer group {group_name} already exists for stream {stream_name}.")
                return True # Group already exists
            logger.error(f"Error creating consumer group {group_name} for {stream_name}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error creating consumer group {group_name} for {stream_name}: {e}")
            return False
    ```

4.  **Add `consume_from_stream` function:**
    ```python
    # In RedisManager class
    def consume_from_stream(self, stream_name: str, group_name: str, consumer_name: str, count: int = STREAM_READ_COUNT, block_ms: int = STREAM_BLOCK_MS) -> Optional[List[Tuple[str, Dict[str, Any]]]]:
        """Consume messages from a stream using a consumer group."""
        if not self.is_available():
            logger.error("Redis not available, cannot consume from stream.")
            return None
        try:
            client = self.get_client()
            # '>' means get new messages for this consumer
            messages = client.xreadgroup(
                groupname=group_name,
                consumername=consumer_name,
                streams={stream_name: '>'},
                count=count,
                block=block_ms
            )
            if messages:
                # messages is like [[b'stream_name', [(b'msg_id', {b'key': b'val'})]]]
                # We need to decode keys and values, especially if they were JSON dumped
                processed_messages = []
                for _stream_name, msg_list in messages:
                    for msg_id, msg_data_raw in msg_list:
                        msg_data_decoded = {}
                        for k, v_raw in msg_data_raw.items():
                            # Attempt to JSON decode if it looks like JSON
                            v_str = v_raw # Assuming decode_responses=True in pool
                            try:
                                if isinstance(v_str, str) and ((v_str.startswith('{') and v_str.endswith('}')) or \
                                   (v_str.startswith('[') and v_str.endswith(']'))):
                                    msg_data_decoded[k] = json.loads(v_str)
                                else:
                                    msg_data_decoded[k] = v_str
                            except json.JSONDecodeError:
                                msg_data_decoded[k] = v_str # Keep as string if not JSON
                        processed_messages.append((msg_id, msg_data_decoded))
                return processed_messages
            return [] # No new messages
        except Exception as e:
            logger.error(f"Error consuming from stream {stream_name} by {consumer_name} in {group_name}: {e}")
            return None
    ```

5.  **Add `acknowledge_message` function:**
    ```python
    # In RedisManager class
    def acknowledge_message(self, stream_name: str, group_name: str, message_id: str) -> bool:
        """Acknowledge a message in a stream."""
        if not self.is_available():
            logger.error("Redis not available, cannot acknowledge message.")
            return False
        try:
            client = self.get_client()
            acked_count = client.xack(stream_name, group_name, message_id)
            logger.debug(f"Acknowledged message {message_id} in stream {stream_name} for group {group_name}. Count: {acked_count}")
            return acked_count > 0
        except Exception as e:
            logger.error(f"Error acknowledging message {message_id} in {stream_name}: {e}")
            return False
    ```

6.  **Add `claim_pending_messages` (for error recovery):**
    ```python
    # In RedisManager class
    def claim_pending_messages(self, stream_name: str, group_name: str, consumer_name: str, min_idle_time_ms: int, count: int = 10) -> Optional[List[Tuple[str, Dict[str, Any]]]]:
        """Claim pending messages that have been idle for too long."""
        if not self.is_available():
            return None
        try:
            client = self.get_client()
            # Get pending message IDs
            pending_info = client.xpending_range(stream_name, group_name, min_idle_time_ms=min_idle_time_ms, count=count, start='-', end='+')
            message_ids_to_claim = [info['message_id'] for info in pending_info if info['consumer'] != consumer_name] # Claim from others or if owner is gone

            if not message_ids_to_claim:
                return []

            claimed_messages_raw = client.xclaim(
                name=stream_name,
                groupname=group_name,
                consumername=consumer_name,
                min_idle_time=min_idle_time_ms,
                message_ids=message_ids_to_claim,
                # Additional options like IDLE, TIME, RETRYCOUNT, FORCE can be used here
            )
            
            if claimed_messages_raw:
                processed_messages = []
                # claimed_messages_raw is like [(b'msg_id', {b'key': b'val'})]
                for msg_id, msg_data_raw in claimed_messages_raw:
                    msg_data_decoded = {k: (json.loads(v) if isinstance(v, str) and v.startswith('{') else v) for k, v in msg_data_raw.items()}
                    processed_messages.append((msg_id, msg_data_decoded))
                logger.info(f"{consumer_name} claimed {len(processed_messages)} messages from {stream_name}/{group_name}.")
                return processed_messages
            return []
        except Exception as e:
            logger.error(f"Error claiming messages in {stream_name} by {consumer_name}: {e}")
            return None
    ```

### B. Modify `config.py`

**Goal:** Add Stream name constants.

```python
# In config.py

# ... other configs ...

# Redis Stream Names for Pipeline Stages
STREAM_PREFIX = os.getenv("STREAM_PREFIX", "docpipe") # e.g., "docpipe" or "tasks"

# Pending Streams (tasks to be done)
STREAM_OCR_PENDING = f"{STREAM_PREFIX}:ocr:pending"
STREAM_CLEAN_CAT_PENDING = f"{STREAM_PREFIX}:clean-cat:pending"
STREAM_CHUNK_PENDING = f"{STREAM_PREFIX}:chunking:pending"
STREAM_NER_PENDING = f"{STREAM_PREFIX}:ner:pending"
STREAM_RESOLUTION_PENDING = f"{STREAM_PREFIX}:resolution:pending"
STREAM_RELATIONSHIPS_PENDING = f"{STREAM_PREFIX}:relationships:pending"

# Dead Letter Queues (for failed tasks after retries)
STREAM_OCR_DLQ = f"{STREAM_PREFIX}:ocr:dlq"
STREAM_CLEAN_CAT_DLQ = f"{STREAM_PREFIX}:clean-cat:dlq"
# ... (add DLQs for other stages) ...
STREAM_PROCESSING_COMPLETED = f"{STREAM_PREFIX}:processing:completed"

# Consumer Group Names
GROUP_OCR = "ocr-service-group"
GROUP_CLEAN_CAT = "clean-cat-service-group"
GROUP_CHUNKING = "chunking-service-group"
GROUP_NER = "ner-service-group"
GROUP_RESOLUTION = "resolution-service-group"
GROUP_RELATIONSHIPS = "relationships-service-group"

# Retry configuration
MAX_STREAM_RETRIES = int(os.getenv("MAX_STREAM_RETRIES", "3"))
STREAM_MSG_IDLE_TIMEOUT_MS = int(os.getenv("STREAM_MSG_IDLE_TIMEOUT_MS", "300000")) # 5 minutes
Use code with caution.
Markdown
C. Modify queue_processor.py (becomes an Intake Service)
Goal: Change QueueProcessor to fetch from Supabase and produce to the first Redis Stream (STREAM_OCR_PENDING).
Import new configs:
from config import (
    # ... existing ...
    STREAM_OCR_PENDING, MAX_STREAM_RETRIES, STREAM_MSG_IDLE_TIMEOUT_MS
)
Use code with caution.
Python
Modify process_queue (or rename to run_intake_service):
The loop that calls process_single_document will now produce a message to STREAM_OCR_PENDING.
# Inside QueueProcessor.process_queue or its replacement
# ... after documents_batch = self.claim_pending_documents() ...
# ... and for doc_to_process in documents_batch: ...

                # Instead of calling process_single_document directly:
                logger.info(f"Publishing document {doc_to_process['file_name']} (Source SQL ID: {source_doc_sql_id}) to OCR queue.")
                
                # Prepare message for the stream
                # Ensure large data (like full text) is NOT put in the stream. Pass references.
                # For OCR, we pass the S3 key or path.
                ocr_task_message = {
                    "document_uuid": str(doc_to_process['source_doc_uuid']), # Ensure it's string
                    "source_doc_sql_id": str(source_doc_sql_id), # Ensure it's string
                    "file_path": str(doc_to_process['file_path']),
                    "file_name": str(doc_to_process['file_name']),
                    "detected_file_type": str(doc_to_process['detected_file_type']),
                    "project_sql_id": str(doc_to_process['project_sql_id']),
                    "attempt_count": "1" # Initial attempt for stream processing
                }
                
                redis_mgr = get_redis_manager()
                msg_id = redis_mgr.produce_to_stream(STREAM_OCR_PENDING, ocr_task_message)

                if msg_id:
                    logger.info(f"Document {source_doc_sql_id} added to stream {STREAM_OCR_PENDING} with msg ID {msg_id}.")
                    # Update the Supabase queue item status to 'queued_for_ocr' or similar
                    # to prevent re-picking by this intake service.
                    # Or, if the Supabase queue's 'completed' status is tied to the final pipeline
                    # completion, this step might just log.
                    # For clarity, let's assume the trigger `update_queue_on_document_terminal_state`
                    # will mark the Supabase queue item once the *entire* stream pipeline finishes.
                    # This means the Redis lock on the Supabase queue item should be released here.
                    
                    # Release Redis lock on successful handoff to stream
                    try:
                        lock_key = f"queue:lock:{queue_id}" # queue_id is from item['queue_id']
                        if redis_mgr.exists(lock_key): # Check if lock is owned by this processor_id if possible or just delete
                            redis_mgr.delete(lock_key)
                            logger.debug(f"Released Redis lock for Supabase queue item {queue_id} after handoff to stream.")
                    except Exception as e_lock_release:
                        logger.warning(f"Could not release Supabase queue item lock {queue_id}: {e_lock_release}")

                    # Update source_documents.initial_processing_status to indicate it's in stream pipeline
                    self.db_manager.update_processing_status('source_documents', source_doc_sql_id, 'ocr_stream_pending')
                else:
                    logger.error(f"Failed to add document {source_doc_sql_id} to stream {STREAM_OCR_PENDING}. Will be retried by claimer.")
                    # The item remains 'processing' in Supabase queue and will be picked up by stall checker or next claim.
                    # The Redis lock `queue:lock:{queue_id}` will eventually time out.
Use code with caution.
Python
Important: The process_single_document call is REMOVED from QueueProcessor.
The Redis lock on the Supabase document_processing_queue item (e.g., queue:lock:{queue_id}) should be released once the task is successfully handed off to the first Redis Stream.
D. Create New Service Modules (e.g., ocr_service.py, chunking_service.py, etc.)
Goal: Each core processing logic from main_pipeline.py becomes a dedicated stream consumer.
Example: ocr_service.py
import logging
import time
import json
import os
import uuid # For consumer name

from supabase_utils import SupabaseManager
from redis_utils import get_redis_manager
from config import (
    STREAM_OCR_PENDING, STREAM_OCR_DLQ,
    STREAM_CLEAN_CAT_PENDING,
    GROUP_OCR, MAX_STREAM_RETRIES, STREAM_MSG_IDLE_TIMEOUT_MS
)
from ocr_extraction import extract_text_from_pdf_textract, extract_text_from_docx, extract_text_from_txt, extract_text_from_eml, transcribe_audio_whisper
# from logging_config import setup_logging # If you have it

# logger = setup_logging(__name__) # Or basicConfig
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')


class OcrService:
    def __init__(self):
        self.redis_mgr = get_redis_manager()
        self.db_manager = SupabaseManager()
        self.consumer_name = f"ocr-consumer-{uuid.uuid4().hex[:8]}"
        
        if not self.redis_mgr.is_available():
            raise ConnectionError("Redis is not available. OCR Service cannot start.")
            
        # Ensure consumer group exists
        if not self.redis_mgr.create_consumer_group(STREAM_OCR_PENDING, GROUP_OCR):
            raise RuntimeError(f"Failed to create/ensure consumer group {GROUP_OCR} for stream {STREAM_OCR_PENDING}")
        logger.info(f"OCR Service consumer {self.consumer_name} initialized for group {GROUP_OCR}.")

    def _handle_failed_message(self, stream_name: str, group_name: str, msg_id: str, message_data: dict, error: str, attempt_count: int):
        logger.error(f"Message {msg_id} failed on attempt {attempt_count}. Error: {error}. Data: {message_data}")
        if attempt_count >= MAX_STREAM_RETRIES:
            logger.warning(f"Message {msg_id} reached max retries ({MAX_STREAM_RETRIES}). Moving to DLQ: {STREAM_OCR_DLQ}.")
            dlq_msg_data = {**message_data, "error": error, "original_msg_id": msg_id, "failed_at_attempt": str(attempt_count)}
            self.redis_mgr.produce_to_stream(STREAM_OCR_DLQ, dlq_msg_data)
            # Acknowledge the original message so it's removed from pending
            if not self.redis_mgr.acknowledge_message(stream_name, group_name, msg_id):
                logger.error(f"CRITICAL: Failed to ACK message {msg_id} after DLQing. It might be reprocessed.")
        else:
            # For simplicity, we're not explicitly re-queueing with a delay here.
            # The message remains unacknowledged and will be picked up by XPENDING/XCLAIM logic after timeout.
            # A more sophisticated approach might involve adding it back with an increased attempt_count or to a retry stream.
            logger.info(f"Message {msg_id} will be retried later (remains unacknowledged).")
            # To explicitly re-queue with updated attempt count:
            # message_data["attempt_count"] = str(attempt_count + 1)
            # self.redis_mgr.produce_to_stream(stream_name, message_data) # Add to end of stream
            # self.redis_mgr.acknowledge_message(stream_name, group_name, msg_id) # Ack original

    def process_single_message(self, msg_id: str, message_data: dict):
        document_uuid = message_data.get("document_uuid")
        source_doc_sql_id = int(message_data.get("source_doc_sql_id"))
        file_path = message_data.get("file_path")
        file_name = message_data.get("file_name")
        detected_file_type = message_data.get("detected_file_type")
        # project_sql_id = int(message_data.get("project_sql_id")) # If needed by OCR funcs
        
        attempt_count = int(message_data.get("attempt_count", 1))

        logger.info(f"Processing OCR for doc_uuid: {document_uuid}, sql_id: {source_doc_sql_id}, attempt: {attempt_count}")
        
        # Update main_pipeline.update_document_state (or equivalent)
        # update_document_state(document_uuid, "ocr", "stream_processing_started", {"attempt": attempt_count})
        self.db_manager.update_processing_status('source_documents', source_doc_sql_id, 'ocr_stream_processing')


        raw_text = None
        ocr_meta_for_db = None
        ocr_provider = None

        try:
            if detected_file_type == '.pdf':
                ocr_provider = 'textract'
                self.db_manager.client.table('source_documents').update({
                    'ocr_provider': ocr_provider,
                    'textract_job_status': 'not_started',
                    'last_modified_at': datetime.now().isoformat() 
                }).eq('id', source_doc_sql_id).execute()
                raw_text, ocr_meta_for_db = extract_text_from_pdf_textract(
                    db_manager=self.db_manager,
                    source_doc_sql_id=source_doc_sql_id,
                    pdf_path_or_s3_uri=file_path,
                    document_uuid_from_db=document_uuid
                )
            elif detected_file_type == '.docx':
                ocr_provider = 'docx_parser'
                raw_text = extract_text_from_docx(file_path)
                ocr_meta_for_db = [{"method": "docx_parser"}]
            # ... Add other file types from main_pipeline.py's process_single_document ...
            else:
                raise ValueError(f"Unsupported file type for OCR: {detected_file_type}")

            if raw_text is not None: # Check for None, not just falsy (empty string is valid)
                # Store raw_text and ocr_meta_for_db (e.g., to S3 or directly in Supabase if small)
                # For this example, assume they are stored and we get S3 keys
                # This part needs careful implementation based on data size.
                # Let's assume update_source_document_text handles storing text
                # and ocr_metadata_json is updated there.

                self.db_manager.update_source_document_text(
                    source_doc_sql_id, 
                    raw_text,
                    ocr_meta_json=json.dumps(ocr_meta_for_db) if ocr_meta_for_db else None,
                    status="ocr_stream_complete_pending_clean_cat" # New status
                )
                if ocr_provider: # Update provider if determined
                     self.db_manager.client.table('source_documents').update({
                        'ocr_provider': ocr_provider, 
                        'ocr_completed_at': datetime.now().isoformat()
                    }).eq('id', source_doc_sql_id).execute()

                # Produce to next stream
                next_task_message = {
                    "document_uuid": document_uuid,
                    "source_doc_sql_id": str(source_doc_sql_id), # Keep as string for stream
                    # "raw_text_s3_key": "s3_key_for_raw_text", # If stored in S3
                    "attempt_count": "1" # Reset for next stage
                }
                next_msg_id = self.redis_mgr.produce_to_stream(STREAM_CLEAN_CAT_PENDING, next_task_message)
                if next_msg_id:
                    logger.info(f"OCR complete for {document_uuid}. Produced to {STREAM_CLEAN_CAT_PENDING} (msg: {next_msg_id}).")
                    if not self.redis_mgr.acknowledge_message(STREAM_OCR_PENDING, GROUP_OCR, msg_id):
                         logger.error(f"Failed to ACK message {msg_id} after successful processing and producing to next stage.")
                    # update_document_state(document_uuid, "ocr", "stream_processing_completed")
                else:
                    # This is a critical failure - if we can't produce to next stream,
                    # we should not ACK the current message. It will be retried.
                    logger.error(f"CRITICAL: Failed to produce to {STREAM_CLEAN_CAT_PENDING} for {document_uuid}. Message {msg_id} will be retried.")
                    # Do NOT ACK
            else:
                # OCR failed to produce text (could be Textract job failure, or other)
                # extract_text_from_pdf_textract should update DB status to failed.
                # Here, we handle the stream message.
                error_detail = f"OCR process returned no text for {file_name} ({detected_file_type})."
                logger.error(error_detail)
                # No explicit DB update here as OCR function should handle its own failure state in source_documents
                # The source_documents.textract_job_status would be 'failed'.
                # We need to decide if this is a DLQ candidate or if it just stops the pipeline for this doc.
                self._handle_failed_message(STREAM_OCR_PENDING, GROUP_OCR, msg_id, message_data, error_detail, attempt_count)

        except Exception as e:
            logger.error(f"Exception in OCR processing for msg {msg_id}, doc_uuid {document_uuid}: {e}", exc_info=True)
            self.db_manager.update_source_document_text(source_doc_sql_id, None, status="ocr_stream_error")
            self._handle_failed_message(STREAM_OCR_PENDING, GROUP_OCR, msg_id, message_data, str(e), attempt_count)


    def run(self):
        logger.info(f"OCR Service worker {self.consumer_name} starting to listen to {STREAM_OCR_PENDING}...")
        while True:
            try:
                # Try to claim messages that might have timed out from other consumers
                # claimed_messages = self.redis_mgr.claim_pending_messages(
                # STREAM_OCR_PENDING, GROUP_OCR, self.consumer_name, STREAM_MSG_IDLE_TIMEOUT_MS
                # )
                # if claimed_messages:
                #     for msg_id, msg_data in claimed_messages:
                #         logger.info(f"Claimed stale message {msg_id}.")
                #         msg_data["attempt_count"] = str(int(msg_data.get("attempt_count", 1)) + 1) # Increment attempt
                #         self.process_single_message(msg_id, msg_data)
                
                # Read new messages
                messages = self.redis_mgr.consume_from_stream(
                    STREAM_OCR_PENDING, GROUP_OCR, self.consumer_name
                )
                if messages:
                    for msg_id, msg_data in messages:
                        logger.info(f"Received message {msg_id} from {STREAM_OCR_PENDING}.")
                        self.process_single_message(msg_id, msg_data)
                else:
                    # No new messages, sleep briefly
                    time.sleep(1) # Avoid busy-waiting if block_ms is low or 0
            except ConnectionError as e: # Specific to Redis connection
                logger.error(f"Redis connection error in OCR service: {e}. Retrying connection...")
                time.sleep(10)
                self.redis_mgr = get_redis_manager() # Attempt to re-initialize
                if not self.redis_mgr.is_available():
                    logger.error("Failed to reconnect to Redis. OCR Service stopping.")
                    break
            except Exception as e:
                logger.error(f"Unhandled exception in OCR Service run loop: {e}", exc_info=True)
                time.sleep(5) # Pause before continuing

if __name__ == "__main__":
    # This allows running the service independently
    # You would have one such main block for each service (ocr, chunking, etc.)
    # In a production setup, these would be managed by systemd, Docker Compose, or Kubernetes.
    # Initialize models if this service needs them (OCR service might not if Textract is pure API)
    # from models_init import initialize_all_models
    # initialize_all_models() # Or specific models
    
    ocr_worker = OcrService()
    ocr_worker.run()
Use code with caution.
Python
Repeat the structure of ocr_service.py for other pipeline stages:
cleaning_categorization_service.py: Consumes from STREAM_CLEAN_CAT_PENDING, produces to STREAM_CHUNK_PENDING.
Logic from main_pipeline.py Phase 1.5.
chunking_service.py: Consumes from STREAM_CHUNK_PENDING, produces to STREAM_NER_PENDING.
Logic from main_pipeline.py Phase 2.
ner_service.py: Consumes from STREAM_NER_PENDING, produces to STREAM_RESOLUTION_PENDING.
Logic from main_pipeline.py Phase 3.
resolution_service.py: Consumes from STREAM_RESOLUTION_PENDING, produces to STREAM_RELATIONSHIPS_PENDING.
Logic from main_pipeline.py Phase 4.
relationship_service.py: Consumes from STREAM_RELATIONSHIPS_PENDING, produces to STREAM_PROCESSING_COMPLETED.
Logic from main_pipeline.py Phase 5.
E. Modify main_pipeline.py
Goal: Remove the monolithic process_single_document. The main function might now be responsible for starting different service workers based on arguments, or it might be removed if services are run as separate processes.
The process_single_document function is no longer needed here as its logic is distributed into the individual stream-consuming services.
The main function in main_pipeline.py might change:
# main_pipeline.py
# ...
def main(processing_mode: str, service_name: Optional[str] = None):
    logger.info(f"Starting Legal NLP Pipeline in '{processing_mode}' mode (Stage {DEPLOYMENT_STAGE})...")
    # ... (stage validation and model init as before) ...

    if processing_mode == "queue_intake": # New mode for the intake service
        logger.info("Running in QUEUE_INTAKE mode (Supabase to Redis Stream).")
        from queue_processor import QueueProcessor # This is now the intake service
        intake_service = QueueProcessor(batch_size=5)
        intake_service.process_queue(single_run=False) # Renamed from run_intake_service for consistency

    elif processing_mode == "stream_worker":
        if not service_name:
            logger.error("Service name must be provided for stream_worker mode.")
            return

        logger.info(f"Running in STREAM_WORKER mode for service: {service_name}")
        if service_name == "ocr":
            from ocr_service import OcrService # Assuming you create this file
            worker = OcrService()
            worker.run()
        elif service_name == "clean_cat":
            # from cleaning_categorization_service import CleaningCategorizationService
            # worker = CleaningCategorizationService()
            # worker.run()
            logger.info("CleaningCategorizationService not implemented in this example.")
        # ... add other services ...
        else:
            logger.error(f"Unknown service name: {service_name}")
    
    elif processing_mode == "direct": # Keep direct for testing single files outside queue
        # ... (existing direct mode logic, but it should now also publish to STREAM_OCR_PENDING
        #      instead of calling process_single_document)
        logger.warning("Direct mode needs refactoring to publish to initial Redis Stream.")
        # For each file:
        #   1. Create source_document_entry
        #   2. Prepare message like in QueueProcessor
        #   3. redis_mgr.produce_to_stream(STREAM_OCR_PENDING, ocr_task_message)
    else:
        logger.error(f"Invalid processing_mode: {processing_mode}.")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Legal NLP Pre-processing Pipeline.")
    parser.add_argument(
        '--mode', type=str, default='queue_intake', 
        choices=['direct', 'queue_intake', 'stream_worker'],
        help="Processing mode."
    )
    parser.add_argument(
        '--service', type=str,
        help="Name of the stream worker service to run (e.g., ocr, chunking). Required if mode is stream_worker."
    )
    # ... (log level arg) ...
    args = parser.parse_args()
    # ... (logging setup) ...
    main(processing_mode=args.mode, service_name=args.service)
Use code with caution.
Python
F. Update Document State Tracking
The update_document_state, get_document_state, clear_document_state functions in main_pipeline.py are still useful. Each service worker should call update_document_state at the beginning and end of its processing for a given document_uuid.
Example in a service worker:
# At the start of processing a message for document_uuid
update_document_state(document_uuid, "ocr-service", "processing_started", {"msg_id": msg_id})

# On success
update_document_state(document_uuid, "ocr-service", "completed", {"output_msg_id": next_msg_id})

# On failure (before DLQ or retry logic)
update_document_state(document_uuid, "ocr-service", "failed", {"error": str(e)})
Use code with caution.
Python
Consider making these state update functions part of redis_utils.py or a new state_manager.py for better organization.
G. General Considerations for Agent
Error Handling & Idempotency: Each stream consumer must be idempotent. If it crashes after partial work but before XACK, the message will be redelivered. Ensure operations can be safely repeated or detect prior partial completion.
Large Data: Store large data (full text, extensive metadata) in Supabase or S3. Stream messages should contain IDs and pointers, not the large data itself.
Configuration: Ensure all stream names, group names, and retry parameters are configurable via config.py.
Logging: Each service should have robust logging, including message IDs, document UUIDs, and processing times.
Deployment: Each service (ocr_service.py, chunking_service.py, etc.) and the queue_processor.py (intake) will run as separate, long-lived processes. Consider Docker containers and an orchestrator (like Docker Compose for development, Kubernetes for production).
Model Initialization: Ensure initialize_all_models() or specific model initializations are called appropriately at the start of each service that requires ML models.
Database Updates: Transactions may be needed if a service updates multiple Supabase tables and needs to roll back on error. For simplicity, this guide assumes per-operation updates.
This detailed guide should provide the agentic coding tool with a clear path to refactor the pipeline using Redis Streams. The transition is significant but offers substantial benefits in terms of scalability, resilience, and decoupling of processing stages.