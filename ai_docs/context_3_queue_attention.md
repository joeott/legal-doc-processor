Okay, this is an exciting and significant upgrade to your legal document processing pipeline! We're going to implement a robust queueing system using Supabase. This will make your pipeline more resilient, scalable, and manageable.

Here's a detailed, step-by-step prompt for an agentic coding tool. This prompt focuses on integrating the queue system described in your "Document Processing Queue Implementation Guide" into your existing codebase.

**Overall Goal:**

Implement a robust document processing queue system using the `document_processing_queue` Supabase table. This involves creating a new `QueueProcessor` to manage document flow, modifying `main_pipeline.py` to operate in a queue-driven mode, and ensuring all database interactions utilize the `SupabaseManager` from `supabase_utils.py`. The existing `db_utils.py` functionality will be superseded by methods in `SupabaseManager`.

**Project Context & Existing Files:**

You have the following key Python files that will be involved:
*   `main_pipeline.py`: Core processing logic for a single document.
*   `supabase_utils.py`: Contains the `SupabaseManager` class for interacting with your Supabase database.
*   `relationship_builder.py`: Handles staging relationships.
*   `config.py`: Contains global configurations like `PROJECT_ID_GLOBAL`.
*   Other files like `ocr_extraction.py`, `text_processing.py`, `entity_extraction.py`, `entity_resolution.py`, `chunking_utils.py` which perform specific NLP tasks.


**Step 1: Enhance `supabase_utils.py` (`SupabaseManager`)**

The `SupabaseManager` class will be central. Ensure it has the following capabilities, building upon your existing `supabase_utils.py`:

1.  **Generic Query Execution**:
    *   Verify or implement a method like `execute_raw_query(self, query: str, params: Optional[dict] = None) -> List[Dict]` that can execute arbitrary SQL, especially for `UPDATE ... RETURNING` and `SELECT ... FOR UPDATE SKIP LOCKED` patterns. The existing `self.client.rpc('execute_query', {"query": query}).execute()` might suffice if the RPC function `execute_query` is powerful enough. If not, a more direct execution method may be needed, or ensure the RPC function can handle these specific DML/locking statements.
    *   *Agent Action*: Review the provided `supabase_utils.py`. The `self.client.rpc('execute_query', {"query": query}).execute()` is used. Assume this RPC function is set up in Supabase to execute arbitrary SQL queries passed to it.

2.  **Get Source Document by SQL ID**:
    *   Ensure the method `get_document_by_id(self, doc_id: int) -> Optional[Dict]` (as seen in your `queue_processor.py` snippet) is correctly implemented to fetch a record from the `source_documents` table by its primary key `id`.
    *   *Agent Action*: The provided `supabase_utils.py` has this method. Verify its correctness.

3.  **Timestamp Correction in `create_relationship_staging`**:
    *   In the existing `create_relationship_staging` method in your `supabase_utils.py`, the line `createdAt': datetime.now().isoformat()` is correct. Ensure any similar timestamp fields are handled this way or rely on database defaults (`DEFAULT NOW()`).
    *   *Agent Action*: The provided `supabase_utils.py` seems to handle `createdAt` correctly with `datetime.now().isoformat()`.

4.  **Supersede `db_utils.py`**:
    *   All functions currently imported from `db_utils.py` into `main_pipeline.py` (e.g., `get_or_create_project`, `create_source_document_entry`, `update_source_document_text`, `create_neo4j_document_entry`, `update_neo4j_document_details`, `create_chunk_entry`, `create_entity_mention_entry`, `create_canonical_entity_entry`, `update_entity_mention_with_canonical_id`, `update_neo4j_document_status`) need to have corresponding methods in `SupabaseManager`.
    *   Your provided `supabase_utils.py` already implements most of these. The task is to ensure full coverage and that `main_pipeline.py` will exclusively use these `SupabaseManager` methods.
    *   *Agent Action*: Compare the imports from `db_utils.py` in `main_pipeline.py` with the methods available in the provided `supabase_utils.py` (`SupabaseManager`). Implement any missing methods in `SupabaseManager`, ensuring they match Supabase table/column names and return values (often `(sql_id, uuid)`).

**Step 2: Create `queue_processor.py`**

Create a new file named `queue_processor.py`. This file will contain the `QueueProcessor` class.

```python
# queue_processor.py
import os
import logging
import time
import socket
import uuid
from datetime import datetime, timedelta
from typing import List, Dict, Optional

# Ensure these imports are correct based on your project structure
from supabase_utils import SupabaseManager
from main_pipeline import process_single_document, initialize_all_models # Added initialize_all_models
from config import PROJECT_ID_GLOBAL, S3_TEMP_DOWNLOAD_DIR, USE_S3_FOR_INPUT # Added more configs
if USE_S3_FOR_INPUT:
    from s3_utils import S3FileManager


# Setup logger for this module
logger = logging.getLogger(__name__)
# Basic logging config if not already set globally by main_pipeline or another entry point
if not logger.hasHandlers():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(module)s - %(message)s')


class QueueProcessor:
    def __init__(self, batch_size: int = 5, max_processing_time_minutes: int = 60): # Default batch_size 5
        self.db_manager = SupabaseManager()
        self.batch_size = batch_size
        self.max_processing_time = timedelta(minutes=max_processing_time_minutes)
        self.processor_id = f"{socket.gethostname()}_{uuid.uuid4().hex[:12]}" # Unique ID for this processor instance
        logger.info(f"Initialized QueueProcessor with ID: {self.processor_id}, Batch Size: {self.batch_size}, Max Processing Time: {self.max_processing_time}")
        self.s3_manager = S3FileManager() if USE_S3_FOR_INPUT else None


    def claim_pending_documents(self) -> List[Dict]:
        logger.debug(f"Attempting to claim up to {self.batch_size} documents.")
        # Ensure project_sql_id and project_uuid are fetched once or as needed.
        # For simplicity, we can fetch them here, or pass them if they are stable.
        # The main pipeline's process_single_document needs project_sql_id.
        try:
            project_sql_id, project_uuid = self.db_manager.get_or_create_project(PROJECT_ID_GLOBAL, "My Legal Project") # Match name from main_pipeline
        except Exception as e:
            logger.error(f"Failed to get or create project {PROJECT_ID_GLOBAL}: {e}")
            return []

        # SQL query to claim documents using FOR UPDATE SKIP LOCKED
        # This ensures that multiple processor instances do not pick the same document.
        claim_query = f"""
        WITH selected_rows AS (
            SELECT id
            FROM document_processing_queue
            WHERE status = 'pending' AND attempts < max_attempts
            ORDER BY priority ASC, created_at ASC
            LIMIT {self.batch_size}
            FOR UPDATE SKIP LOCKED
        )
        UPDATE document_processing_queue q
        SET
            status = 'processing',
            attempts = q.attempts + 1,
            last_attempt_at = NOW(),
            processing_started_at = NOW(),
            processor_id = '{self.processor_id}',
            updated_at = NOW()
        FROM selected_rows sr
        WHERE q.id = sr.id
        RETURNING q.id AS queue_id, q.source_document_id, q.source_document_uuid, q.attempts;
        """
        try:
            # Use the generic query execution method from SupabaseManager
            # Assuming self.db_manager.client.rpc('execute_query', ...) is the way
            response = self.db_manager.client.rpc('execute_query', {"query": claim_query}).execute()
            claimed_items = response.data if response.data else []
            logger.info(f"Claimed {len(claimed_items)} documents from queue.")

            documents_to_process = []
            for item in claimed_items:
                # Fetch full source document details
                source_doc_details = self.db_manager.get_document_by_id(item['source_document_id'])
                if source_doc_details:
                    # If using S3, ensure the file is downloaded before processing
                    file_path = source_doc_details['original_file_path']
                    if USE_S3_FOR_INPUT and self.s3_manager:
                        s3_key = source_doc_details.get('s3_key') # Assuming s3_key is stored
                        if not s3_key: # Fallback to derive from original_file_name if not stored
                             s3_key = source_doc_details['original_file_name'] # This might need adjustment based on your S3 structure
                        
                        local_s3_path = os.path.join(S3_TEMP_DOWNLOAD_DIR, os.path.basename(s3_key))
                        try:
                            # Check if file already exists locally (e.g. from a previous failed attempt by another worker that downloaded it)
                            if not os.path.exists(local_s3_path):
                               logger.info(f"Downloading {s3_key} from S3 to {local_s3_path} for processing.")
                               self.s3_manager.download_file(s3_key, local_s3_path) # Assumes download_file takes bucket_name from S3FileManager internal config
                            else:
                               logger.info(f"File {local_s3_path} already exists locally, skipping S3 download.")
                            file_path = local_s3_path # Update file_path to the local S3 download
                        except Exception as e:
                            logger.error(f"Failed to download {s3_key} from S3: {e}. Marking queue item as failed.")
                            self.mark_queue_item_failed(item['queue_id'], f"S3 download error: {e}", item['source_document_id'])
                            continue # Skip this document


                    documents_to_process.append({
                        'queue_id': item['queue_id'],
                        'source_doc_sql_id': item['source_document_id'], # Use clear naming
                        'source_doc_uuid': item['source_document_uuid'],
                        'attempts': item['attempts'],
                        'file_path': file_path, # This is original_file_path or local S3 path
                        'file_name': source_doc_details['original_file_name'],
                        'detected_file_type': source_doc_details['detected_file_type'],
                        'project_sql_id': project_sql_id, # Pass project_sql_id
                        # 'project_uuid': project_uuid # Pass if needed by process_single_document
                    })
                else:
                    logger.warning(f"Could not find source document details for ID {item['source_document_id']}. Queue ID: {item['queue_id']}")
                    self.mark_queue_item_failed(item['queue_id'], f"Source document ID {item['source_document_id']} not found.", item['source_document_id'])


            return documents_to_process
        except Exception as e:
            logger.error(f"Error claiming documents from queue: {e}", exc_info=True)
            return []

    def mark_queue_item_failed(self, queue_id: int, error_message: str, source_doc_sql_id: Optional[int] = None):
        logger.error(f"Marking queue item {queue_id} as failed. Error: {error_message}")
        try:
            update_data = {
                'status': 'failed',
                'last_error': str(error_message)[:2000], # Truncate error if too long for TEXT column
                'processing_completed_at': datetime.now().isoformat(), # Mark completion time
                'updated_at': datetime.now().isoformat()
            }
            self.db_manager.client.table('document_processing_queue').update(update_data).eq('id', queue_id).execute()

            # Also update the source_document status to 'error' or a similar terminal state
            if source_doc_sql_id:
                self.db_manager.update_source_document_text(
                    source_doc_sql_id=source_doc_sql_id,
                    raw_text=None, # Or keep existing text
                    status="error", # Or specific error status like "processing_queue_failure"
                    # ocr_meta_json might also include the error
                )
                # The trigger update_queue_on_document_terminal_state should handle the final queue status update
                # if source_documents.initial_processing_status changes.
                # However, direct update here ensures the queue item is marked failed immediately.

        except Exception as e:
            logger.error(f"CRITICAL: Error while marking queue item {queue_id} as failed: {e}", exc_info=True)

    def check_for_stalled_documents(self):
        logger.debug("Checking for stalled documents.")
        stalled_threshold_time = datetime.now() - self.max_processing_time
        
        # Query to find and reset stalled documents
        reset_stalled_query = f"""
        WITH stalled_docs AS (
            SELECT id
            FROM document_processing_queue
            WHERE status = 'processing' AND processing_started_at < '{stalled_threshold_time.isoformat()}'
            ORDER BY processing_started_at ASC -- Process oldest stalled first
            LIMIT 10 -- Reset in batches to avoid long transactions
            FOR UPDATE SKIP LOCKED
        )
        UPDATE document_processing_queue q
        SET
            status = 'pending', -- Reset to pending for another attempt if attempts < max_attempts
            last_error = 'Processing timed out by processor_id=' || q.processor_id || '. Resetting.',
            processing_started_at = NULL, -- Clear processing_started_at
            processor_id = NULL, -- Clear processor_id
            updated_at = NOW()
        FROM stalled_docs sd
        WHERE q.id = sd.id AND q.attempts < q.max_attempts -- Only reset if attempts remain
        RETURNING q.id AS queue_id, q.source_document_id;
        """

        reset_failed_stalled_query = f"""
        WITH stalled_docs_max_attempts AS (
             SELECT id
            FROM document_processing_queue
            WHERE status = 'processing' AND processing_started_at < '{stalled_threshold_time.isoformat()}'
            ORDER BY processing_started_at ASC
            LIMIT 10
            FOR UPDATE SKIP LOCKED
        )
        UPDATE document_processing_queue q
        SET
            status = 'failed', -- Mark as failed if max_attempts reached
            last_error = 'Processing timed out by processor_id=' || q.processor_id || '. Max attempts reached.',
            processing_completed_at = NOW(),
            processing_started_at = NULL,
            processor_id = NULL,
            updated_at = NOW()
        FROM stalled_docs_max_attempts sdma
        WHERE q.id = sdma.id AND q.attempts >= q.max_attempts
        RETURNING q.id AS queue_id, q.source_document_id;
        """
        try:
            response_pending = self.db_manager.client.rpc('execute_query', {"query": reset_stalled_query}).execute()
            response_failed = self.db_manager.client.rpc('execute_query', {"query": reset_failed_stalled_query}).execute()
            
            stalled_docs_reset = response_pending.data if response_pending.data else []
            stalled_docs_failed = response_failed.data if response_failed.data else []

            if stalled_docs_reset:
                logger.warning(f"Reset {len(stalled_docs_reset)} stalled documents to 'pending' state. IDs: {[d['queue_id'] for d in stalled_docs_reset]}")
                for doc in stalled_docs_reset:
                    # Optionally update source_documents table if needed
                    pass
            if stalled_docs_failed:
                logger.warning(f"Marked {len(stalled_docs_failed)} stalled documents as 'failed' (max attempts). IDs: {[d['queue_id'] for d in stalled_docs_failed]}")
                for doc in stalled_docs_failed:
                     if doc.get('source_document_id'):
                        self.db_manager.update_source_document_text(source_doc_sql_id=doc['source_document_id'], raw_text=None, status="error_timeout")


        except Exception as e:
            logger.error(f"Error checking/resetting stalled documents: {e}", exc_info=True)


    def process_queue(self, max_documents_to_process: Optional[int] = None, single_run: bool = False):
        logger.info(f"QueueProcessor {self.processor_id} starting. Single Run: {single_run}, Max Documents: {max_documents_to_process}")
        
        # Initialize models once per processor instance, if not already global
        # This call is already in main_pipeline.py's main(), but if queue_processor is run independently, it might be needed here.
        # For now, assume main_pipeline.py's main() handles it when mode='queue'.
        # initialize_all_models() # Consider if this is the right place.

        processed_count = 0
        try:
            while True:
                self.check_for_stalled_documents()
                
                documents_batch = self.claim_pending_documents()

                if not documents_batch:
                    if single_run:
                        logger.info("No more documents in queue and single_run is True. Exiting.")
                        break
                    logger.info(f"No documents claimed. Waiting for 30 seconds...")
                    time.sleep(30) # Wait before trying to claim again
                    continue

                for doc_to_process in documents_batch:
                    queue_id = doc_to_process['queue_id']
                    source_doc_sql_id = doc_to_process['source_doc_sql_id']
                    logger.info(f"Processing document: {doc_to_process['file_name']} (Source SQL ID: {source_doc_sql_id}, Queue ID: {queue_id}, Attempt: {doc_to_process['attempts']})")
                    
                    try:
                        # Call the main processing function from main_pipeline.py
                        # Ensure its signature matches:
                        # process_single_document(db_manager, source_doc_sql_id, file_path, file_name, detected_file_type, project_sql_id)
                        process_single_document(
                            db_manager=self.db_manager, # Pass SupabaseManager instance
                            source_doc_sql_id=source_doc_sql_id,
                            # source_doc_uuid=doc_to_process['source_doc_uuid'], # Pass if needed
                            file_path=doc_to_process['file_path'],
                            file_name=doc_to_process['file_name'],
                            detected_file_type=doc_to_process['detected_file_type'],
                            project_sql_id=doc_to_process['project_sql_id']
                            # project_uuid=doc_to_process['project_uuid'] # Pass if needed
                        )
                        # If process_single_document completes without error, it means it updated
                        # source_documents.initial_processing_status to 'completed'.
                        # The database trigger `update_queue_on_document_terminal_state`
                        # should then automatically update the queue item's status to 'completed'.
                        logger.info(f"Successfully processed document: {doc_to_process['file_name']} (Queue ID: {queue_id}). Trigger should mark queue item 'completed'.")

                    except Exception as e:
                        logger.error(f"Error processing document {doc_to_process['file_name']} (Queue ID: {queue_id}): {e}", exc_info=True)
                        self.mark_queue_item_failed(queue_id, str(e), source_doc_sql_id)
                    finally:
                        # Clean up downloaded S3 file if applicable
                        if USE_S3_FOR_INPUT and self.s3_manager and os.path.exists(doc_to_process['file_path']) and S3_TEMP_DOWNLOAD_DIR in doc_to_process['file_path']:
                            try:
                                os.remove(doc_to_process['file_path'])
                                logger.info(f"Cleaned up temporary S3 file: {doc_to_process['file_path']}")
                            except Exception as e_clean:
                                logger.warning(f"Could not clean up temp S3 file {doc_to_process['file_path']}: {e_clean}")


                    processed_count += 1
                    if max_documents_to_process is not None and processed_count >= max_documents_to_process:
                        logger.info(f"Processed {processed_count} documents, reaching max_documents_to_process limit. Exiting.")
                        return # Exit the process_queue method

                if single_run:
                    logger.info("Processed one batch in single_run mode. Exiting.")
                    break
                
                # Optional: short delay between batches if not waiting for new items
                # time.sleep(5)

        except KeyboardInterrupt:
            logger.info(f"QueueProcessor {self.processor_id} received KeyboardInterrupt. Shutting down.")
        finally:
            logger.info(f"QueueProcessor {self.processor_id} finished.")
            # Optional: Clean up all S3 temp files on exit, though per-file cleanup is better
            if USE_S3_FOR_INPUT and self.s3_manager:
                # self.s3_manager.cleanup_temp_files() # If you have a general cleanup
                pass


# Main execution block for running the processor directly
if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description="Document Processing Queue Processor")
    parser.add_argument("--batch-size", type=int, default=5, help="Number of documents to process in each batch.")
    parser.add_argument("--max-docs", type=int, default=None, help="Maximum number of documents to process before exiting.")
    parser.add_argument("--single-run", action="store_true", help="Run for one batch and then exit.")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="Set the logging level.")

    args = parser.parse_args()

    # Reconfigure logging level if specified
    logging.getLogger().setLevel(args.log_level)
    logger.setLevel(args.log_level)
    for handler in logging.getLogger().handlers: # Apply to all handlers
        handler.setLevel(args.log_level)

    logger.info(f"Starting Queue Processor directly with Batch Size: {args.batch_size}, Max Docs: {args.max_docs}, Single Run: {args.single_run}")
    
    # Initialize models here if this is the main entry point for the worker
    initialize_all_models()

    processor = QueueProcessor(batch_size=args.batch_size)
    processor.process_queue(max_documents_to_process=args.max_docs, single_run=args.single_run)
```

**Step 3: Modify `main_pipeline.py`**

1.  **Update `process_single_document` function:**
    *   Change the `db_sess` argument to `db_manager` (an instance of `SupabaseManager`).
    *   Replace all calls to `db_utils.py` functions with their corresponding methods from the `db_manager` instance. For example, `create_source_document_entry(db_sess, ...)` becomes `db_manager.create_source_document_entry(...)`.
    *   The function signature should be:
        `process_single_document(db_manager: SupabaseManager, source_doc_sql_id: int, file_path: str, file_name: str, detected_file_type: str, project_sql_id: int)`
        (The `source_doc_uuid` and `project_uuid` can be fetched inside if needed, or passed if convenient).
    *   *Agent Action*: Systematically go through `process_single_document` and replace all `db_utils` calls with `db_manager` method calls, ensuring arguments and return values are handled correctly. For example, `neo4j_doc_record = create_neo4j_document_entry(...)` should change to `neo4j_doc_sql_id, neo4j_doc_uuid = db_manager.create_neo4j_document_entry(...)` if the `SupabaseManager` method returns a tuple. Adjust variable assignments accordingly.

2.  **Modify `main()` function:**
    *   Add a `mode` argument (`'direct'` or `'queue'`).
    *   If `mode == 'queue'`, instantiate and run `QueueProcessor`.
    *   The existing logic for iterating local/S3 files will be part of the `'direct'` mode.
    *   Use `argparse` to allow selecting the mode from the command line.
    *   Ensure `initialize_all_models()` is called appropriately for both modes.
    *   When in `'direct'` mode, the `SupabaseManager` instance needs to be created and used instead of the old `db_sess`.

```python
# --- START OF MODIFIED main_pipeline.py ---

# main_pipeline.py
import os
import logging
from datetime import datetime
import json # For handling JSON fields from SQL
import argparse # For command line arguments

# Use SupabaseManager instead of db_utils directly
from supabase_utils import SupabaseManager # Assuming SupabaseManager is in supabase_utils.py

from config import (PROJECT_ID_GLOBAL, SOURCE_DOCUMENT_DIR, FORCE_REPROCESS_OCR,
                    USE_S3_FOR_INPUT, S3_TEMP_DOWNLOAD_DIR) # etc.
from models_init import initialize_all_models
# Remove db_utils imports that are now handled by SupabaseManager
# from db_utils import (get_db_session, get_or_create_project, create_source_document_entry, 
#                      update_source_document_text, create_neo4j_document_entry, 
#                      update_neo4j_document_details, create_chunk_entry, 
#                      create_entity_mention_entry, create_canonical_entity_entry,
#                      update_entity_mention_with_canonical_id, update_neo4j_document_status)
from ocr_extraction import extract_text_from_pdf_qwen_vl_ocr, extract_text_from_docx, extract_text_from_txt, extract_text_from_eml, transcribe_audio_whisper # etc.
from text_processing import (clean_extracted_text, categorize_document_text, 
                           process_document_with_structured_extraction) # Removed chunk_text_content, get_document_text_chunks_with_semantic_chunking
from entity_extraction import extract_entities_from_chunk
from entity_resolution import resolve_document_entities
from relationship_builder import stage_structural_relationships # Will need db_manager

# S3 imports
if USE_S3_FOR_INPUT:
    from s3_utils import S3FileManager # Removed sync_s3_input_files as queue processor might handle downloads

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(module)s - %(message)s')
logger = logging.getLogger(__name__)

# MODIFIED process_single_document:
def process_single_document(db_manager: SupabaseManager, source_doc_sql_id: int, file_path: str, file_name: str, detected_file_type: str, project_sql_id: int):
    logger.info(f"Processing document: {file_name} (SQL ID: {source_doc_sql_id}) for Project SQL ID: {project_sql_id}")

    # --- Phase 1: Text Extraction & Initial Document Node Creation ---
    raw_text = None
    ocr_meta = None
    # extraction_successful = False # Not used

    # The source_document entry is already created by the direct mode or handled by queue intake.
    # Here, we primarily update it.

    if detected_file_type == '.pdf':
        raw_text, ocr_meta = extract_text_from_pdf_qwen_vl_ocr(file_path)
    elif detected_file_type == '.docx':
        raw_text = extract_text_from_docx(file_path)
    # ... (other file types as before) ...
    elif detected_file_type == '.txt':
        raw_text = extract_text_from_txt(file_path)
    elif detected_file_type == '.eml':
        raw_text = extract_text_from_eml(file_path)
    elif detected_file_type in ['.wav', '.mp3']: # Add more audio types
        raw_text = transcribe_audio_whisper(file_path)
    else:
        logger.warning(f"Unsupported file type for text extraction: {detected_file_type} for {file_name}")
        # Update source_document status via SupabaseManager
        db_manager.update_source_document_text(source_doc_sql_id, None, status="extraction_unsupported")
        return # Exit processing for this document

    if raw_text:
        # Update source_document entry
        db_manager.update_source_document_text(source_doc_sql_id, raw_text,
                                    ocr_meta_json=json.dumps(ocr_meta) if ocr_meta else None,
                                    status="ocr_complete_pending_doc_node") # This status implies OCR success
        # extraction_successful = True # Not used
    else:
        logger.error(f"Failed to extract text for {file_name}")
        db_manager.update_source_document_text(source_doc_sql_id, None, status="extraction_failed")
        return # Exit processing

    # Fetch source_doc_uuid if needed for neo4j_document creation, or assume db_manager handles it
    # Assuming source_documents table has a document_uuid field that SupabaseManager can use/retrieve
    source_doc_info = db_manager.get_document_by_id(source_doc_sql_id) # You might need a more specific method
    if not source_doc_info or not source_doc_info.get('document_uuid'):
        logger.error(f"Could not retrieve source_document_uuid for SQL ID {source_doc_sql_id}. Aborting further processing.")
        db_manager.update_source_document_text(source_doc_sql_id, raw_text, status="error_missing_uuid") # Update status
        return
    source_doc_uuid = source_doc_info['document_uuid']
    
    # Fetch project_uuid for consistency if create_neo4j_document_entry needs it
    # project_info = db_manager.get_project_by_sql_id(project_sql_id) # Hypothetical method
    # if not project_info or not project_info.get('projectId'): # projectId is the UUID field in projects table
    #     logger.error(f"Could not retrieve project_uuid for Project SQL ID {project_sql_id}. Aborting.")
    #     db_manager.update_source_document_text(source_doc_sql_id, raw_text, status="error_missing_project_uuid")
    #     return
    # project_uuid = project_info['projectId']
    # Simpler: assume get_or_create_project in the calling context (queue or direct mode) provides the necessary project_uuid if needed
    # For now, create_neo4j_document_entry in SupabaseManager will take project_sql_id and can internally get project_uuid or it might be passed.
    # Let's assume db_manager.create_neo4j_document_entry uses project_sql_id to link and internally knows project_uuid or it's passed
    # The current SupabaseManager.create_neo4j_document_entry takes project_fk_id AND project_uuid.
    # So we need project_uuid. It should be available from when project_sql_id was obtained.
    # The QueueProcessor should pass it, or direct mode should fetch it.
    # For now, let's assume project_uuid is available to db_manager methods or fetched by them using project_sql_id.
    # To simplify, the process_single_document could also take project_uuid.
    # Let's modify its signature slightly or ensure the SupabaseManager methods can derive it.
    # The SupabaseManager.create_neo4j_document_entry expects:
    # (self, source_doc_fk_id: int, source_doc_uuid: str, project_fk_id: int, project_uuid: str, file_name: str)
    # So we need project_uuid.
    # We will assume `db_manager.get_project_uuid_by_sql_id(project_sql_id)` exists or is added.
    _project_uuid = db_manager.get_project_by_sql_id_or_global_project_id(project_sql_id, PROJECT_ID_GLOBAL) # You'll need to implement this helper in SupabaseManager

    if not _project_uuid:
        logger.error(f"Critical: Could not determine project_uuid for project_sql_id {project_sql_id}. Aborting {file_name}.")
        db_manager.update_source_document_text(source_doc_sql_id, raw_text, status="error_project_uuid_lookup")
        return


    # Create Neo4j Document Node Entry in SQL (using SupabaseManager)
    # Ensure create_neo4j_document_entry returns (sql_id, uuid)
    neo4j_doc_sql_id, neo4j_doc_uuid = db_manager.create_neo4j_document_entry(
        source_doc_fk_id=source_doc_sql_id, 
        source_doc_uuid=source_doc_uuid, 
        project_fk_id=project_sql_id,
        project_uuid=_project_uuid, # Pass the fetched project_uuid
        file_name=file_name
    )
    if not neo4j_doc_sql_id: # Check if creation failed
        logger.error(f"Failed to create neo4j_documents entry for {file_name}. Aborting further processing.")
        # Status already updated if raw_text failed. If neo4j_doc creation fails, source_doc status should reflect this.
        db_manager.update_source_document_text(source_doc_sql_id, raw_text, status="error_neo4j_doc_creation")
        return
    logger.info(f"Created neo4j_documents entry for {file_name}, SQL ID: {neo4j_doc_sql_id}, Neo4j UUID: {neo4j_doc_uuid}")

    # --- Phase 1.5: Cleaning & Categorization (neo4j_documents) ---
    cleaned_raw_text = clean_extracted_text(raw_text)
    doc_category = categorize_document_text(cleaned_raw_text, ocr_meta)

    db_manager.update_neo4j_document_details(neo4j_doc_sql_id,
                                  category=doc_category,
                                  file_type=detected_file_type,
                                  cleaned_text=cleaned_raw_text, # This field in SupabaseManager is 'cleaned_text_for_chunking'
                                  status="pending_chunking") # This field is 'processingStatus'
    logger.info(f"Document {neo4j_doc_uuid} categorized as '{doc_category}'. Cleaned text stored.")

    # --- Phase 2: Chunking with Structured Extraction ---
    logger.info(f"Starting chunking and structured extraction for document {neo4j_doc_uuid}...")
    from config import USE_STRUCTURED_EXTRACTION # Already imported
    
    # This function is from text_processing.py and does NOT interact with DB directly
    structured_chunks_data_list, document_structured_data = process_document_with_structured_extraction(
        cleaned_raw_text,
        ocr_meta,
        doc_category,
        use_structured_extraction=USE_STRUCTURED_EXTRACTION
    )
    
    if document_structured_data and USE_STRUCTURED_EXTRACTION:
        db_manager.update_neo4j_document_details(
            neo4j_doc_sql_id,
            metadata_json=document_structured_data # SupabaseManager should handle json.dumps if needed
        )
        logger.info(f"Stored document-level structured data for {neo4j_doc_uuid}")
    
    all_chunk_sql_data_for_pipeline = [] # Renamed to avoid confusion with DB schema names
    
    for chunk_data_from_processor in structured_chunks_data_list: # Iterate over the list of chunk dicts
        # Create chunk entry using SupabaseManager
        # Ensure create_chunk_entry returns (sql_id, uuid)
        # SupabaseManager.create_chunk_entry signature:
        # (self, document_fk_id: int, document_uuid: str, chunk_index: int, text_content: str, ...)
        chunk_sql_id, chunk_neo4j_uuid = db_manager.create_chunk_entry(
            document_fk_id=neo4j_doc_sql_id,
            document_uuid=neo4j_doc_uuid, # Pass the parent neo4j_document's UUID
            chunk_index=chunk_data_from_processor['chunk_index'],
            text_content=chunk_data_from_processor['chunk_text'],
            # cleaned_text=chunk_data_from_processor['chunk_text'], # Assuming no separate cleaned text for chunk initially
            char_start_index=chunk_data_from_processor['char_start_index'],
            char_end_index=chunk_data_from_processor['char_end_index'],
            metadata_json=chunk_data_from_processor.get('metadata_json') # Ensure this is a dict or JSON string
        )
        
        if chunk_sql_id and chunk_neo4j_uuid:
            logger.info(f"  Created chunk {chunk_data_from_processor['chunk_index']} (SQL ID: {chunk_sql_id}, Neo4j ID: {chunk_neo4j_uuid}) for doc {neo4j_doc_uuid}")
            
            # Prepare data for subsequent pipeline stages
            # This is data held in memory for the current document processing run
            chunk_info_for_pipeline = {
                "sql_id": chunk_sql_id,
                "neo4j_id": chunk_neo4j_uuid, # This is 'chunkId' in Supabase
                "text": chunk_data_from_processor['chunk_text'],
                "index_int": chunk_data_from_processor['chunk_index'], # This is 'chunkIndex'
                "document_id_neo4j": neo4j_doc_uuid, # Parent document's Neo4j UUID
                "structured_data_from_text_processing": chunk_data_from_processor.get('structured_data') # If available
            }
            all_chunk_sql_data_for_pipeline.append(chunk_info_for_pipeline)
        else:
            logger.error(f"Failed to create chunk entry for index {chunk_data_from_processor['chunk_index']}, doc SQL ID {neo4j_doc_sql_id}. Skipping NER for this chunk.")

    db_manager.update_neo4j_document_status(neo4j_doc_sql_id, "pending_ner") # status field is 'processingStatus'

    # --- Phase 3: Entity Extraction (neo4j_entity_mentions) ---
    logger.info(f"Starting entity extraction for document {neo4j_doc_uuid}...")
    all_entity_mentions_for_doc_with_sql_ids = []
    
    for chunk_data_mem in all_chunk_sql_data_for_pipeline: # Use the in-memory list
        mentions_in_chunk_attrs = extract_entities_from_chunk(chunk_data_mem["text"])
        for mention_attrs in mentions_in_chunk_attrs:
            # SupabaseManager.create_entity_mention_entry signature:
            # (self, chunk_sql_id: int, chunk_uuid: str, value: str, entity_type_label: str, ...)
            em_sql_id, em_neo4j_uuid = db_manager.create_entity_mention_entry(
                chunk_sql_id=chunk_data_mem["sql_id"], # This is chunk_fk_id
                chunk_uuid=chunk_data_mem["neo4j_id"], # This is chunk_uuid
                value=mention_attrs["value"],
                norm_value=mention_attrs["normalizedValue"],
                display_value=mention_attrs.get("displayValue"),
                entity_type_label=mention_attrs["entity_type"], # This is 'entity_type'
                rationale=mention_attrs.get("rationale"),
                attributes_json_str=json.dumps(mention_attrs.get("attributes_json", {})), # Ensure it's string
                phone=mention_attrs.get("phone"),
                email=mention_attrs.get("email"),
                start_offset=mention_attrs.get("offsetStart"), # 'start_char_offset_in_chunk'
                end_offset=mention_attrs.get("offsetEnd") # 'end_char_offset_in_chunk'
            )
            if em_sql_id and em_neo4j_uuid:
                logger.info(f"    Extracted entity '{mention_attrs['value']}' (SQL ID: {em_sql_id}, Neo4j ID: {em_neo4j_uuid}) in chunk {chunk_data_mem['neo4j_id']}")
                
                full_mention_data_for_resolution = mention_attrs.copy()
                full_mention_data_for_resolution['entity_mention_id_neo4j'] = em_neo4j_uuid # 'entityMentionId'
                full_mention_data_for_resolution['entity_mention_sql_id'] = em_sql_id
                full_mention_data_for_resolution['parent_chunk_id_neo4j'] = chunk_data_mem['neo4j_id'] # 'chunk_uuid'
                full_mention_data_for_resolution['chunk_index_int'] = chunk_data_mem['index_int']
                all_entity_mentions_for_doc_with_sql_ids.append(full_mention_data_for_resolution)
            else:
                logger.error(f"Failed to create entity mention entry for '{mention_attrs['value']}' in chunk SQL ID {chunk_data_mem['sql_id']}.")

    db_manager.update_neo4j_document_status(neo4j_doc_sql_id, "pending_canonicalization")

    # --- Phase 4: Canonicalization (neo4j_canonical_entities) ---
    logger.info(f"Starting entity canonicalization for document {neo4j_doc_uuid}...")
    resolved_canonical_entity_data_list, updated_mentions_with_temp_canon_ids = \
        resolve_document_entities(all_entity_mentions_for_doc_with_sql_ids, cleaned_raw_text)
    
    map_temp_canon_id_to_neo4j_uuid = {}
    final_canonical_entities_for_relationships = []

    for ce_attrs_temp in resolved_canonical_entity_data_list:
        # SupabaseManager.create_canonical_entity_entry signature:
        # (self, neo4j_doc_sql_id: int, document_uuid: str, canonical_name: str, entity_type_label: str, ...)
        ce_sql_id, ce_neo4j_uuid = db_manager.create_canonical_entity_entry(
            neo4j_doc_sql_id=neo4j_doc_sql_id, # This is 'documentId' (FK to neo4j_documents.id)
            document_uuid=neo4j_doc_uuid, # This is 'document_uuid' (the UUID of the neo4j_document)
            canonical_name=ce_attrs_temp["canonicalName"],
            entity_type_label=ce_attrs_temp["entity_type"], # 'entity_type'
            aliases_json=ce_attrs_temp.get("allKnownAliasesInDoc_json"), # 'allKnownAliasesInDoc'
            mention_count=ce_attrs_temp.get("mention_count_in_doc", 1), # 'mention_count'
            first_seen_idx=ce_attrs_temp.get("firstSeenAtChunkIndex_int", 0) # 'firstSeenAtChunkIndex'
        )
        if ce_sql_id and ce_neo4j_uuid:
            map_temp_canon_id_to_neo4j_uuid[ce_attrs_temp["canonicalEntityId_temp"]] = ce_neo4j_uuid
            logger.info(f"  Created canonical entity '{ce_attrs_temp['canonicalName']}' (SQL ID: {ce_sql_id}, Neo4j ID: {ce_neo4j_uuid})")
            
            ce_attrs_temp_copy = ce_attrs_temp.copy()
            ce_attrs_temp_copy['canonical_entity_id_neo4j'] = ce_neo4j_uuid # 'canonicalEntityId'
            final_canonical_entities_for_relationships.append(ce_attrs_temp_copy)
        else:
            logger.error(f"Failed to create canonical entity entry for '{ce_attrs_temp['canonicalName']}'.")

    # Update entity mentions with the actual Neo4j UUID of their canonical entity
    # The db_utils.update_entity_mention_with_canonical_id was a placeholder.
    # In Supabase, this link is typically made when creating relationships,
    # or by adding a 'resolved_canonical_entity_uuid' column to 'neo4j_entity_mentions' table
    # and updating it. The SupabaseManager has update_entity_mention_with_canonical_id, but it was a pass.
    # For now, we assume the relationship builder will use the resolved_canonical_id_neo4j.
    # If you want to persist this link on the neo4j_entity_mentions table,
    # you'll need to add a column like `resolved_canonical_entity_uuid` and update `SupabaseManager`.
    final_entity_mentions_for_relationships = []
    for em_data_updated in updated_mentions_with_temp_canon_ids:
        temp_canon_id = em_data_updated.get("resolved_canonical_id_temp")
        if temp_canon_id and temp_canon_id in map_temp_canon_id_to_neo4j_uuid:
            actual_canonical_neo4j_uuid = map_temp_canon_id_to_neo4j_uuid[temp_canon_id]
            # Call SupabaseManager to update the entity mention if schema supports it
            # db_manager.update_entity_mention_with_canonical_id(em_data_updated["entity_mention_sql_id"], actual_canonical_neo4j_uuid)
            # logger.debug(f"  Updating EM SQL ID {em_data_updated['entity_mention_sql_id']} with Canonical Neo4j ID {actual_canonical_neo4j_uuid}")
            em_data_updated['resolved_canonical_id_neo4j'] = actual_canonical_neo4j_uuid
        else:
            logger.warning(f"Could not find mapping for temp canonical ID {temp_canon_id} for EM SQL ID {em_data_updated['entity_mention_sql_id']}")
        final_entity_mentions_for_relationships.append(em_data_updated)

    db_manager.update_neo4j_document_status(neo4j_doc_sql_id, "pending_relationships")

    # --- Phase 5: Relationship Staging ---
    logger.info(f"Starting relationship staging for document {neo4j_doc_uuid}...")
    
    doc_data_for_rels = { # Align with relationship_builder.py expectations
        "documentId": neo4j_doc_uuid, # This is document_id_neo4j
        "sql_id": neo4j_doc_sql_id,
        "category": doc_category,
        "file_type": detected_file_type,
        "name": file_name
    }
    
    # `all_chunk_sql_data_for_pipeline` items need 'chunkId' key for relationship_builder
    # Its items currently have 'neo4j_id' (which is chunk_uuid or chunkId)
    chunks_for_rels = []
    for c in all_chunk_sql_data_for_pipeline:
        chunks_for_rels.append({
            "chunkId": c["neo4j_id"], # This is the chunk_uuid
            "chunkIndex": c["index_int"], # Ensure this is chunkIndex from schema
            # Add other fields if relationship_builder needs them
        })
    
    # `final_entity_mentions_for_relationships` items need 'entityMentionId'
    # Its items currently have 'entity_mention_id_neo4j'
    mentions_for_rels = []
    for m in final_entity_mentions_for_relationships:
        mentions_for_rels.append({
            "entityMentionId": m["entity_mention_id_neo4j"], # This is the entity_mention_uuid
            "chunk_uuid": m["parent_chunk_id_neo4j"], # This is the parent chunk's UUID
            "resolved_canonical_id_neo4j": m.get("resolved_canonical_id_neo4j")
            # Add other fields if relationship_builder needs them
        })

    # `final_canonical_entities_for_relationships` items need 'canonicalEntityId'
    # Its items currently have 'canonical_entity_id_neo4j'
    canonicals_for_rels = []
    for ce in final_canonical_entities_for_relationships:
        canonicals_for_rels.append({
            "canonicalEntityId": ce["canonical_entity_id_neo4j"], # This is the canonical_entity_uuid
            # Add other fields if relationship_builder needs them
        })

    # stage_structural_relationships expects project_id to be the UUID of the project
    stage_structural_relationships(
        db_manager, # Pass SupabaseManager instance
        doc_data_for_rels,
        _project_uuid, # Pass Project UUID
        chunks_for_rels,
        mentions_for_rels,
        canonicals_for_rels
    )

    # Final status update for the source document itself
    db_manager.update_source_document_text(source_doc_sql_id, raw_text, status="completed")
    # The trigger update_queue_on_document_terminal_state will handle the queue item.
    # Also update neo4j_document status
    db_manager.update_neo4j_document_status(neo4j_doc_sql_id, "complete")
    logger.info(f"Successfully processed document {file_name} (Neo4j ID: {neo4j_doc_uuid})")


# MODIFIED main function
def main(processing_mode: str): # Renamed arg for clarity
    logger.info(f"Starting Legal NLP Pre-processing Pipeline in '{processing_mode}' mode...")
    initialize_all_models() # Load all ML/DL models once

    db_manager = SupabaseManager() # Instantiate SupabaseManager

    # Get or Create Project (needed for both modes)
    # project_sql_id, project_uuid = db_manager.get_or_create_project(PROJECT_ID_GLOBAL, "My Legal Project")
    # Project info will be fetched by QueueProcessor or here in direct mode.

    if processing_mode == "queue":
        logger.info("Running in QUEUE mode.")
        from queue_processor import QueueProcessor # Import here to avoid circular deps if any
        
        # Default queue processor arguments, can be configurable too
        queue_proc = QueueProcessor(batch_size=5) # Batch size from config or arg
        queue_proc.process_queue(max_documents_to_process=None, single_run=False) # Run continuously

    elif processing_mode == "direct":
        logger.info("Running in DIRECT mode (processing local/S3 files directly).")
        
        # Get Project Info for direct mode
        try:
            project_sql_id, project_uuid_for_direct_mode = db_manager.get_or_create_project(PROJECT_ID_GLOBAL, "My Legal Project")
            logger.info(f"Using Project SQL ID: {project_sql_id}, Project UUID: {project_uuid_for_direct_mode}")
        except Exception as e:
            logger.error(f"Failed to get or create project in direct mode: {e}. Exiting.")
            return
            
        # Logic for S3 or local file iteration (from original main)
        source_files_to_process = []
        s3_file_manager_instance = None
        if USE_S3_FOR_INPUT:
            logger.info("Using S3 for input files in DIRECT mode...")
            s3_file_manager_instance = S3FileManager()
            try:
                logger.info(f"Syncing files from S3 bucket to {S3_TEMP_DOWNLOAD_DIR}")
                # This syncs ALL files. For direct mode, you might want to process one by one.
                # For simplicity, let's assume it syncs and then we iterate.
                # A true "direct S3" mode might list S3 keys and download one by one.
                # The current s3_utils.sync_s3_input_files implies downloading many.
                # This could be inefficient if only processing a few in direct mode.
                # Let's adapt to download one by one for direct s3.
                # For now, using the existing sync logic for simplicity of prompt.
                # Re-evaluate if s3_utils.sync_input_files should be used or a more targeted download.
                # The original code syncs ALL files then iterates.

                # The original code had sync_s3_input_files here.
                # For direct mode, it's better to list keys and process one by one.
                # However, the prompt is getting very long. Let's stick to the user's original flow for S3 direct.
                # This means `s3_manager.sync_input_files` would be called if that's the intended S3 direct mode.
                # The provided `main_pipeline.py` used `s3_manager.sync_input_files(S3_TEMP_DOWNLOAD_DIR)`.

                local_files_synced = s3_file_manager_instance.sync_input_files(S3_TEMP_DOWNLOAD_DIR) # Assumes this method exists
                
                for file_p in local_files_synced:
                    file_n = os.path.basename(file_p)
                    source_files_to_process.append({
                        "path": file_p, "name": file_n, "type": os.path.splitext(file_n)[1].lower(),
                        "s3_original": True # Flag that it came from S3 for potential cleanup
                    })
                logger.info(f"Synced {len(local_files_synced)} files from S3 for direct processing.")

            except Exception as e:
                logger.error(f"Error syncing files from S3 in DIRECT mode: {e}", exc_info=True)
                # Decide if to proceed with local files or exit
        else: # Local directory
            if os.path.exists(SOURCE_DOCUMENT_DIR):
                for root, _, files in os.walk(SOURCE_DOCUMENT_DIR):
                    for file in files:
                        source_files_to_process.append({
                            "path": os.path.join(root, file), "name": file, "type": os.path.splitext(file)[1].lower(),
                            "s3_original": False
                        })
            else:
                logger.warning(f"Source document directory '{SOURCE_DOCUMENT_DIR}' does not exist for DIRECT mode.")

        # Ensure SupabaseManager has `get_project_uuid_by_sql_id` or similar
        # Add a helper in SupabaseManager:
        # def get_project_by_sql_id_or_global_project_id(self, project_sql_id_param, global_project_id_config):
        #     if project_sql_id_param:
        #         proj = self.client.table('projects').select('projectId').eq('id', project_sql_id_param).single().execute()
        #         if proj.data: return proj.data['projectId']
        #     # Fallback to global project ID if specific not found or not given
        #     proj_global = self.client.table('projects').select('projectId').eq('projectId', global_project_id_config).single().execute()
        #     if proj_global.data: return proj_global.data['projectId']
        #     logger.error(f"Could not find project UUID for SQL ID {project_sql_id_param} or Global ID {global_project_id_config}")
        #     return None
        # This method is now needed by process_single_document to get project_uuid if not passed directly.
        # We added it to process_single_document.

        for file_info in source_files_to_process:
            try:
                # Create source_document entry using SupabaseManager
                src_doc_sql_id, src_doc_uuid = db_manager.create_source_document_entry(
                    project_fk_id=project_sql_id, # SQL ID of the project
                    project_uuid=project_uuid_for_direct_mode,  # UUID of the project
                    original_file_path=file_info["path"],
                    original_file_name=file_info["name"],
                    detected_file_type=file_info["type"]
                    # S3 key can also be stored here if file_info["s3_original"] is true
                )
                if not src_doc_sql_id:
                    logger.error(f"Failed to create source document entry for {file_info['name']} in DIRECT mode. Skipping.")
                    continue
                
                logger.info(f"DIRECT Intake: {file_info['name']} registered with SQL ID: {src_doc_sql_id}, UUID: {src_doc_uuid}")

                # Process the document (passing SupabaseManager)
                process_single_document(
                    db_manager,
                    src_doc_sql_id,
                    file_info["path"],
                    file_info["name"],
                    file_info["type"],
                    project_sql_id # Pass project_sql_id
                )
            except Exception as e:
                logger.error(f"Error processing file {file_info['name']} in DIRECT mode: {e}", exc_info=True)
                # If src_doc_sql_id was created, mark it as error
                if 'src_doc_sql_id' in locals() and src_doc_sql_id:
                    db_manager.update_source_document_text(src_doc_sql_id, None, status="error_direct_processing")


        # CSV Export (remains commented as per original)
        logger.info("Legal NLP Pipeline (DIRECT mode) completed.")
        
        # Clean up S3 temporary files if used in direct mode
        if USE_S3_FOR_INPUT and s3_file_manager_instance:
            try:
                logger.info("Cleaning up S3 temporary files from DIRECT mode processing...")
                s3_file_manager_instance.cleanup_temp_files() # Ensure this method exists and works
                logger.info("S3 temporary files (DIRECT mode) cleaned up.")
            except Exception as e:
                logger.error(f"Error cleaning up S3 temp files (DIRECT mode): {e}")
    else:
        logger.error(f"Invalid processing_mode: {processing_mode}. Choose 'direct' or 'queue'.")

    # db_sess.close() - No longer needed as SupabaseManager manages its client.
    logger.info("Processing finished.")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Legal NLP Pre-processing Pipeline.")
    parser.add_argument('--mode', type=str, default='queue', choices=['direct', 'queue'],
                        help="Processing mode: 'direct' for immediate file processing, 'queue' for queue-based processing.")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="Set the logging level.")

    args = parser.parse_args()

    # Reconfigure logging level if specified
    logging.getLogger().setLevel(args.log_level.upper())
    logger.setLevel(args.log_level.upper())
    for handler in logging.getLogger().handlers: # Apply to all handlers
        handler.setLevel(args.log_level.upper())

    main(processing_mode=args.mode)

# --- END OF MODIFIED main_pipeline.py ---
```

**Step 4: Modify `relationship_builder.py`**

1.  The `stage_structural_relationships` function currently takes `db_session`. This should now expect an instance of `SupabaseManager`.
2.  The `create_relationship` function within `relationship_builder.py` should be modified to call `db_manager.create_relationship_staging(...)`.
    *   The `project_id` argument to `stage_structural_relationships` should be the Project *UUID*.

```python
# --- START OF MODIFIED relationship_builder.py ---

# relationship_builder.py
import uuid
import json # Not strictly needed here if properties are passed as dict
import logging

# Use SupabaseManager for DB operations
# from supabase_utils import SupabaseManager # Not needed to import here if passed as arg

logger = logging.getLogger(__name__)

# MODIFIED stage_structural_relationships
def stage_structural_relationships(db_manager, # Changed from db_session to db_manager (SupabaseManager instance)
                                  document_data: dict,
                                  project_uuid: str, # Explicitly project_uuid
                                  chunks_data: list[dict],
                                  entity_mentions_data: list[dict],
                                  canonical_entities_data: list[dict]):
    """
    Stages relationships like BELONGS_TO, CONTAINS_MENTION, MEMBER_OF_CLUSTER, NEXT/PREV_CHUNK.
    Uses db_manager.create_relationship_staging.
    
    Arguments:
        db_manager: SupabaseManager instance
        document_data: Dictionary with document info (must contain 'documentId' which is neo4j_document_uuid)
        project_uuid: Project UUID (not SQL ID)
        chunks_data: List of chunk dictionaries (must contain 'chunkId' which is chunk_uuid, 'chunkIndex')
        entity_mentions_data: List of entity mention dictionaries (must contain 'entityMentionId', 'chunk_uuid', 'resolved_canonical_id_neo4j')
        canonical_entities_data: List of canonical entity dictionaries (must contain 'canonicalEntityId')
    """
    document_uuid_val = document_data.get('documentId') # This is the neo4j_document_uuid
    if not document_uuid_val:
        logger.error("No documentId (neo4j_document_uuid) in document_data for relationship_builder, cannot create relationships.")
        return
        
    logger.info(f"Staging structural relationships for document {document_uuid_val}")
    
    # 1. (Document)-[:BELONGS_TO]->(Project)
    # Ensure project_uuid is a valid UUID string.
    if not project_uuid or not isinstance(project_uuid, str) : # Basic check
         logger.error(f"Invalid project_uuid: {project_uuid} for document {document_uuid_val}. Skipping Document-Project relationship.")
    else:
        _create_relationship_wrapper( # Use the wrapper
            db_manager,
            from_id=document_uuid_val, 
            from_label="Document", # As per schema.json NodeLabel
            to_id=project_uuid, 
            to_label="Project", # As per schema.json NodeLabel
            rel_type="BELONGS_TO" # As per schema.json RelationshipType
        )

    # 2. (Chunk)-[:BELONGS_TO]->(Document)
    for chunk in chunks_data:
        chunk_uuid_val = chunk.get('chunkId') # This is chunk_uuid
        if not chunk_uuid_val:
            logger.warning(f"Chunk data item {chunk} has no chunkId (chunk_uuid), skipping BELONGS_TO Document relationship.")
            continue
        _create_relationship_wrapper(db_manager, from_id=chunk_uuid_val, from_label="Chunk",
                           to_id=document_uuid_val, to_label="Document", rel_type="BELONGS_TO")

    # 3. (Chunk)-[:CONTAINS_MENTION]->(EntityMention)
    for em in entity_mentions_data:
        em_uuid_val = em.get('entityMentionId') # This is entity_mention_uuid
        chunk_uuid_for_em = em.get('chunk_uuid') # The chunk this EM belongs to
        
        if not em_uuid_val or not chunk_uuid_for_em:
            logger.warning(f"Entity mention {em} or its chunk_uuid missing, skipping CONTAINS_MENTION relationship.")
            continue
        _create_relationship_wrapper(db_manager, from_id=chunk_uuid_for_em, from_label="Chunk",
                           to_id=em_uuid_val, to_label="EntityMention", rel_type="CONTAINS_MENTION")

    # 4. (EntityMention)-[:MEMBER_OF_CLUSTER]->(CanonicalEntity)
    for em in entity_mentions_data:
        em_uuid_val = em.get('entityMentionId')
        canon_uuid_val = em.get('resolved_canonical_id_neo4j') # This is canonical_entity_uuid
        
        if not em_uuid_val or not canon_uuid_val:
            # This is normal if the entity isn't resolved to a canonical entity or if it's the canonical itself.
            logger.debug(f"Entity mention {em_uuid_val} has no resolved_canonical_id_neo4j or is self-canonical. Skipping MEMBER_OF_CLUSTER.")
            continue
        _create_relationship_wrapper(db_manager, from_id=em_uuid_val, from_label="EntityMention",
                           to_id=canon_uuid_val, to_label="CanonicalEntity", rel_type="MEMBER_OF_CLUSTER")

    # 5. (Chunk)-[:NEXT_CHUNK/PREVIOUS_CHUNK]->(Chunk)
    # Sort chunks by chunkIndex for the current document
    sorted_chunks = sorted(chunks_data, key=lambda c: c.get('chunkIndex', 0)) # chunkIndex is int
    
    for i in range(len(sorted_chunks) - 1):
        chunk_curr = sorted_chunks[i]
        chunk_next = sorted_chunks[i+1]
        
        curr_uuid = chunk_curr.get('chunkId')
        next_uuid = chunk_next.get('chunkId')
        
        if not curr_uuid or not next_uuid:
            logger.warning(f"Chunk UUID missing in sorted chunk list. Curr: {curr_uuid}, Next: {next_uuid}. Skipping NEXT_CHUNK/PREVIOUS_CHUNK.")
            continue
        
        # Add a unique id property to the NEXT_CHUNK relationship for potential GDS usage or uniqueness if needed
        next_rel_props = {"id": str(uuid.uuid4())}

        _create_relationship_wrapper(db_manager, from_id=curr_uuid, from_label="Chunk", to_id=next_uuid, 
                           to_label="Chunk", rel_type="NEXT_CHUNK", properties=next_rel_props)
        
        _create_relationship_wrapper(db_manager, from_id=next_uuid, from_label="Chunk", to_id=curr_uuid, 
                           to_label="Chunk", rel_type="PREVIOUS_CHUNK") # No specific props for PREVIOUS
        
    logger.info(f"Successfully staged structural relationships for document {document_uuid_val}")

# MODIFIED _create_relationship_wrapper (renamed from create_relationship)
# This function now calls db_manager.create_relationship_staging
def _create_relationship_wrapper(db_manager, from_id: str, from_label: str, 
                                 to_id: str, to_label: str, rel_type: str, 
                                 properties: Optional[dict] = None):
    """
    Wrapper to call db_manager.create_relationship_staging.
    Properties should be a dict. SupabaseManager will handle JSON conversion if necessary.
    """
    try:
        # db_manager.create_relationship_staging should handle creation of batchProcessId and createdAt
        rel_id = db_manager.create_relationship_staging(
            from_node_id=from_id,
            from_node_label=from_label,
            to_node_id=to_id,
            to_node_label=to_label,
            relationship_type=rel_type,
            properties=properties # Pass dict directly
        )
        if rel_id:
            logger.debug(f"Staged relationship: {from_label}({from_id}) -[{rel_type}]-> {to_label}({to_id}), Staging ID: {rel_id}")
            return rel_id
        else:
            # Log error if create_relationship_staging returns None or raises an error handled by itself
            logger.error(f"Failed to stage relationship: {from_label}({from_id}) -[{rel_type}]-> {to_label}({to_id}) via SupabaseManager.")
            return None
        
    except Exception as e:
        # This catches errors if db_manager.create_relationship_staging itself raises an unhandled exception
        logger.error(f"Exception calling db_manager.create_relationship_staging for {from_label}({from_id}) -[{rel_type}]-> {to_label}({to_id}): {str(e)}", exc_info=True)
        return None

# --- END OF MODIFIED relationship_builder.py ---
```

**Step 5: Final Review and Testing**

*   **Environment Variables**: Ensure `SUPABASE_URL` and `SUPABASE_ANON_KEY` are correctly set in the environment where `queue_processor.py` and `main_pipeline.py` will run.
*   **Dependencies**: Add any new dependencies (like `psutil` if you implement resource-aware processing, though not in the main prompt now).
*   **Database Migrations**: Apply the SQL for `document_processing_queue` table and triggers to your Supabase database.
*   **Testing `direct` mode**: Run `python main_pipeline.py --mode direct` and verify it processes a test document correctly using `SupabaseManager`.
*   **Testing `queue` mode**:
    1.  Ensure a document is in `source_documents` (which should trigger its addition to `document_processing_queue`).
    2.  Run `python main_pipeline.py --mode queue` (or `python queue_processor.py` if you run it standalone).
    3.  Monitor the `document_processing_queue` table and logs to see the document being claimed and processed.
    4.  Verify the `source_documents` and `neo4j_*` tables are populated correctly.
    5.  Test failure scenarios (e.g., an unreadable PDF) to see if `attempts` increase and `last_error` is logged.
    6.  Test stalled document recovery.

This detailed prompt should guide the agent to implement the queueing system. Remember that this is a significant refactor, especially the parts involving `SupabaseManager` replacing `db_utils.py`. Thorough testing will be key. Good luck!