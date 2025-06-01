# Document Processing Queue: Operation Guide

## Introduction

This document provides a detailed explanation of the document processing queue system implemented in the legal document processing pipeline. The queue system manages the flow of documents through various processing stages, ensuring robustness, scalability, and fault tolerance.

## Queue Table Structure

The `document_processing_queue` table in Supabase is the central component of the queue system. Its structure includes:

| Column | Type | Description |
|--------|------|-------------|
| id | bigint | Primary key, auto-incremented |
| source_document_id | bigint | Foreign key to source_documents.id |
| source_document_uuid | uuid | UUID of the source document (for direct references) |
| status | text | Current status: 'pending', 'processing', 'completed', 'failed' |
| priority | integer | Processing priority (lower values = higher priority) |
| attempts | integer | Number of processing attempts made |
| max_attempts | integer | Maximum number of attempts allowed (default: 3) |
| processor_id | text | Identifier of the worker processing this document |
| last_attempt_at | timestamp | When the last processing attempt started |
| last_error | text | Error message if processing failed |
| processing_started_at | timestamp | When current processing began |
| processing_completed_at | timestamp | When processing finished |
| created_at | timestamp | When the record was created |
| updated_at | timestamp | When the record was last updated |

## Processing States and Transitions

Documents in the queue move through several states:

1. **Pending**: Document is ready for processing but not yet claimed by any processor.
2. **Processing**: Document is being processed by a worker.
3. **Completed**: Processing finished successfully.
4. **Failed**: Processing failed after reaching max_attempts or due to a critical error.

State transitions are managed by:
- The queue processor (claiming pending documents)
- Database triggers (automatic updates when source document status changes)
- Error handling in the processing code

## Queue Management System

### Queue Population

Documents enter the queue through:

1. **Direct Intake**: When documents are uploaded directly to the system, they are registered in the `source_documents` table with a status of `pending_intake`. A database trigger then creates corresponding entries in the `document_processing_queue` table.

2. **Bulk Import**: Batch jobs can insert multiple documents into the `source_documents` table, which are then automatically added to the queue via the same trigger mechanism.

### Queue Processing Logic

The `QueueProcessor` class in `queue_processor.py` handles the core queue operations:

#### Document Claiming

```sql
WITH selected_rows AS (
    SELECT id
    FROM document_processing_queue
    WHERE status = 'pending' AND attempts < max_attempts
    ORDER BY priority ASC, created_at ASC
    LIMIT {batch_size}
    FOR UPDATE SKIP LOCKED
)
UPDATE document_processing_queue q
SET
    status = 'processing',
    attempts = q.attempts + 1,
    last_attempt_at = NOW(),
    processing_started_at = NOW(),
    processor_id = '{processor_id}',
    updated_at = NOW()
FROM selected_rows sr
WHERE q.id = sr.id
RETURNING q.id, q.source_document_id, q.source_document_uuid, q.attempts;
```

This SQL query:
- Selects a batch of pending documents
- Locks them to prevent other processors from claiming the same documents (using `FOR UPDATE SKIP LOCKED`)
- Updates their status to 'processing'
- Increments the attempt counter
- Sets the processor ID and timestamps
- Returns the claimed documents' details

#### Document Processing

For each claimed document, the processor:
1. Fetches the full document details from `source_documents`
2. If using S3, downloads the file to a local temporary directory
3. Calls `process_single_document()` from `main_pipeline.py`
4. Handles any exceptions that occur during processing
5. Cleans up temporary files

#### Status Tracking

The system tracks processing status through:

1. **Direct Updates**: `mark_queue_item_failed()` method directly updates the queue table when errors occur.

2. **Database Triggers**: The `update_queue_on_document_terminal_state` trigger automatically updates queue items when the corresponding `source_document` record changes state:

```sql
CREATE TRIGGER update_queue_on_document_terminal_state
AFTER UPDATE ON source_documents
FOR EACH ROW
WHEN (
    (NEW.initial_processing_status = 'completed' OR
     NEW.initial_processing_status LIKE 'error%') AND
    OLD.initial_processing_status <> NEW.initial_processing_status
)
EXECUTE FUNCTION update_queue_status_from_document();
```

The trigger function:
```sql
CREATE OR REPLACE FUNCTION update_queue_status_from_document() RETURNS TRIGGER AS $$
BEGIN
    IF NEW.initial_processing_status = 'completed' THEN
        UPDATE document_processing_queue
        SET status = 'completed',
            processing_completed_at = NOW(),
            updated_at = NOW()
        WHERE source_document_id = NEW.id
          AND status = 'processing';
    ELSIF NEW.initial_processing_status LIKE 'error%' THEN
        UPDATE document_processing_queue
        SET status = 'failed',
            last_error = 'Document status updated to: ' || NEW.initial_processing_status,
            processing_completed_at = NOW(),
            updated_at = NOW()
        WHERE source_document_id = NEW.id
          AND status = 'processing';
    END IF;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
```

This ensures that queue items are automatically marked as completed or failed based on the final status of the source document processing.

#### Stalled Document Recovery

The queue processor periodically checks for stalled documents:

```sql
WITH stalled_docs AS (
    SELECT id
    FROM document_processing_queue
    WHERE status = 'processing' AND processing_started_at < '{stalled_threshold_time}'
    ORDER BY processing_started_at ASC
    LIMIT 10
    FOR UPDATE SKIP LOCKED
)
UPDATE document_processing_queue q
SET
    status = 'pending',
    last_error = 'Processing timed out. Resetting.',
    processing_started_at = NULL,
    processor_id = NULL,
    updated_at = NOW()
FROM stalled_docs sd
WHERE q.id = sd.id AND q.attempts < q.max_attempts
RETURNING q.id, q.source_document_id;
```

Documents that have been in 'processing' state for too long are:
- Reset to 'pending' if they haven't reached max_attempts
- Marked as 'failed' if they have reached max_attempts

This prevents documents from being stuck in 'processing' if a worker crashes or is terminated unexpectedly.

## Processing Flow and Integration

### Integration with Main Pipeline

1. **Initialization**: The `main_pipeline.py` file now supports two modes:
   - `direct`: Traditional processing of local or S3 files
   - `queue`: Processing documents from the queue

2. **Mode Selection**: When run with `--mode queue`, it initializes the QueueProcessor and starts processing documents from the queue.

3. **Processing Flow**:
   - QueueProcessor claims documents from the queue
   - For each document, it calls `process_single_document()`
   - The same processing logic is used for both direct and queue modes
   - When `process_single_document()` completes successfully, it updates the source document status to 'completed'
   - The database trigger then automatically marks the queue item as 'completed'

### Document Lifecycle

1. **Intake**:
   - Document is registered in `source_documents` with status 'pending_intake'
   - Database trigger creates a queue entry with status 'pending'

2. **Claiming**:
   - QueueProcessor claims the document and updates its status to 'processing'
   - Source document details are retrieved

3. **Processing**:
   - Text extraction (OCR, parsing)
   - Document categorization
   - Chunking with structured extraction
   - Entity extraction
   - Entity canonicalization
   - Relationship staging

4. **Completion**:
   - Source document status is updated to 'completed'
   - Database trigger updates queue status to 'completed'

5. **Error Handling**:
   - If an error occurs, the queue item is marked as 'failed'
   - If attempts < max_attempts, it can be retried later
   - The source document is also marked with an appropriate error status

## Scalability and Fault Tolerance

### Parallel Processing

Multiple QueueProcessor instances can run in parallel, either on the same machine or distributed across multiple servers. The `FOR UPDATE SKIP LOCKED` mechanism ensures that each document is processed by only one worker.

### Fault Tolerance Features

1. **Transaction Safety**: Database operations use transactions to ensure consistency.

2. **Retry Mechanism**: Failed documents can be retried automatically up to max_attempts.

3. **Stalled Document Recovery**: Documents stuck in 'processing' are automatically reset.

4. **Processor Identification**: Each processor has a unique ID to track which worker is handling which document.

5. **Error Tracking**: Detailed error messages are stored in the queue table.

6. **S3 File Cleanup**: Temporary S3 files are cleaned up after processing.

## Monitoring and Management

### Queue Metrics

Key metrics to monitor:
- Number of pending documents
- Number of processing documents
- Number of completed/failed documents
- Average processing time
- Distribution of error types

### Queue Management Commands

The QueueProcessor can be run directly with various options:

```bash
python queue_processor.py --batch-size 5 --max-docs 100 --single-run --log-level INFO
```

Options:
- `--batch-size`: Number of documents to process in each batch
- `--max-docs`: Maximum number of documents to process before exiting
- `--single-run`: Process one batch and exit
- `--log-level`: Set logging verbosity (DEBUG, INFO, WARNING, ERROR)

### Troubleshooting

Common issues and solutions:

1. **Stalled Documents**: If documents are frequently stalled, consider increasing the processing timeout or adding more resources.

2. **High Failure Rate**: Examine the last_error field for common error patterns. Possible causes include invalid input files, insufficient resources, or bugs in the processing code.

3. **Queue Buildup**: If the queue grows too large, consider:
   - Adding more processing workers
   - Increasing batch size
   - Prioritizing important documents

## Conclusion

The document processing queue system provides a robust, scalable solution for managing the flow of documents through the legal document processing pipeline. By separating document intake from processing and implementing comprehensive error handling and recovery mechanisms, the system ensures reliable operation even under heavy load or when processing problematic documents.

## Addendum: S3 Document Detection and Pre-OCR Queue Integration

### Challenge: Identifying Documents Ready for Processing

A key challenge in the queue system is detecting when new documents are available in S3 buckets and tracking documents before they even reach the OCR stage. This is critical for:

1. Ensuring all documents in S3 are properly processed
2. Tracking documents that fail during OCR processing
3. Providing visibility into the entire document lifecycle, starting from initial upload
4. Maintaining processing statistics across all stages, including pre-OCR

### Proposed Solutions

#### 1. S3 Event-Triggered Document Registration

**Implementation:**
- Configure S3 bucket to send event notifications when new objects are created
- Set up an AWS Lambda function or Supabase Edge Function to receive these events
- The function will:
  - Extract document metadata from the S3 event
  - Create an entry in the `source_documents` table with status `pre_ocr_pending`
  - The database trigger will then create a corresponding queue entry

**SQL Trigger Modification:**
```sql
CREATE OR REPLACE FUNCTION create_queue_entry_for_new_document() RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO document_processing_queue (
        source_document_id,
        source_document_uuid,
        status,
        priority,
        attempts,
        max_attempts,
        created_at,
        updated_at
    )
    VALUES (
        NEW.id,
        NEW.document_uuid,
        CASE 
            WHEN NEW.initial_processing_status = 'pre_ocr_pending' THEN 'pre_ocr_pending'
            ELSE 'pending'
        END,
        100, -- Default priority
        0,   -- No attempts yet
        3,   -- Default max attempts
        NOW(),
        NOW()
    );
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
```

**Modified Queue Processor:**
```python
def claim_documents_by_status(self, status='pending', batch_size=None) -> List[Dict]:
    """Claim documents with a specific status"""
    if batch_size is None:
        batch_size = self.batch_size

    claim_query = f"""
    WITH selected_rows AS (
        SELECT id
        FROM document_processing_queue
        WHERE status = '{status}' AND attempts < max_attempts
        ORDER BY priority ASC, created_at ASC
        LIMIT {batch_size}
        FOR UPDATE SKIP LOCKED
    )
    UPDATE document_processing_queue q
    SET
        status = CASE 
            WHEN '{status}' = 'pre_ocr_pending' THEN 'pre_ocr_processing'
            ELSE 'processing'
        END,
        attempts = q.attempts + 1,
        last_attempt_at = NOW(),
        processing_started_at = NOW(),
        processor_id = '{self.processor_id}',
        updated_at = NOW()
    FROM selected_rows sr
    WHERE q.id = sr.id
    RETURNING q.id AS queue_id, q.source_document_id, q.source_document_uuid, q.attempts, q.status;
    """
    # ... rest of the method
```

#### 2. S3 Bucket Polling Service

**Implementation:**
- Create a separate service that periodically polls the S3 bucket for new files
- Compare against a record of already-processed files (stored in a database table)
- For each new file discovered:
  - Create a `source_documents` entry with S3 path information and status `pre_ocr_pending`
  - The database trigger will create the queue entry

**S3Scanner Class:**
```python
class S3Scanner:
    def __init__(self, bucket_name, db_manager, scan_interval=300):
        self.bucket_name = bucket_name
        self.db_manager = db_manager
        self.scan_interval = scan_interval  # Seconds between scans
        self.s3_client = boto3.client('s3')

    def start_scanning(self):
        """Start the scanning loop"""
        while True:
            try:
                self.scan_bucket()
            except Exception as e:
                logger.error(f"Error scanning S3 bucket: {e}")
            
            time.sleep(self.scan_interval)
    
    def scan_bucket(self):
        """Scan the bucket for new files"""
        # Get all objects in the bucket
        response = self.s3_client.list_objects_v2(Bucket=self.bucket_name)
        
        for item in response.get('Contents', []):
            s3_key = item['Key']
            
            # Check if this file is already in our database
            query = """
            SELECT id FROM source_documents 
            WHERE s3_key = %s OR original_file_name = %s
            """
            result = self.db_manager.client.rpc('execute_query', {
                "query": query, 
                "params": [s3_key, s3_key]
            }).execute()
            
            if not result.data:
                # New file found, register it
                original_file_name = os.path.basename(s3_key)
                detected_file_type = os.path.splitext(original_file_name)[1].lower()
                
                # Get or create project
                project_sql_id, project_uuid = self.db_manager.get_or_create_project(
                    PROJECT_ID_GLOBAL, "My Legal Project"
                )
                
                # Create source document entry
                self.db_manager.create_source_document_entry(
                    project_fk_id=project_sql_id,
                    project_uuid=project_uuid,
                    original_file_path=f"s3://{self.bucket_name}/{s3_key}",
                    original_file_name=original_file_name,
                    detected_file_type=detected_file_type,
                    s3_key=s3_key,
                    status="pre_ocr_pending"  # Special status for pre-OCR tracking
                )
                
                logger.info(f"Registered new document from S3: {s3_key}")
```

#### 3. Extended Status Tracking in Queue

**Additional Queue States:**
- `pre_ocr_pending`: Document detected in S3, awaiting OCR
- `pre_ocr_processing`: OCR in progress
- `ocr_complete`: OCR completed, ready for further processing
- `ocr_failed`: OCR failed, may be retried or require manual intervention

**Modified Process Flow:**
1. S3 detection mechanism creates `source_documents` entry with status `pre_ocr_pending`
2. Queue processor claims document with status `pre_ocr_pending` and updates to `pre_ocr_processing`
3. OCR processing is performed
4. On success:
   - Source document status updated to `ocr_complete_pending_doc_node`
   - Queue status automatically updated to `ocr_complete`
5. On failure:
   - Source document status updated to `ocr_failed`
   - Queue status automatically updated to `ocr_failed`
6. For retry logic, documents with status `ocr_failed` can be reset to `pre_ocr_pending` if attempts < max_attempts

#### 4. Document Registry with Web Interface

**Implementation:**
- Create a web-based document upload interface that:
  - Accepts files directly from users
  - Uploads them to the S3 bucket
  - Creates the necessary database entries with proper pre-OCR tracking
  - Provides real-time status updates
- This centralizes the document intake process and ensures all documents are properly registered before processing begins

**Key Components:**
- Upload form with drag-and-drop functionality
- Backend API to handle file uploads and database registration
- Real-time status display showing all processing stages
- User authentication and document access controls
- Bulk upload capabilities with metadata tagging

### Recommended Implementation: Combined Approach

For optimal document tracking from pre-OCR stages, we recommend implementing:

1. **Event-Based + Polling Hybrid**:
   - Use S3 event notifications when possible (most reliable)
   - Supplement with periodic polling to catch any missed events
   - This provides redundancy and ensures all documents are detected

2. **Extended Status Tracking**:
   - Add pre-OCR status tracking to the queue system
   - Modify queue processor to handle these specialized statuses
   - Update database triggers to properly transition between status states

3. **Centralized Document Registry**:
   - Provide a web interface for document uploads
   - Integrate with S3 for storage
   - Automatically handle queue and status management
   - Offer document reprocessing options for failed items

This approach ensures complete visibility into the document processing pipeline from the moment a document arrives in the S3 bucket, through OCR processing, and to completion, with robust error handling and retry mechanisms at every stage.