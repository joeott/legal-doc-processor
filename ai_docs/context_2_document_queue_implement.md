# Document Processing Queue Implementation Guide

## Introduction to the Processing Queue

The document processing queue is a robust system designed to improve the reliability and scalability of your legal document processing pipeline. This guide explains how to effectively implement and utilize the queue system based on the `document_processing_queue` table created in the database.

## Table of Contents

1. [Queue System Overview](#queue-system-overview)
2. [Database Schema Details](#database-schema-details)
3. [Queue Processor Implementation](#queue-processor-implementation)
4. [Running the Queue Processor](#running-the-queue-processor)
5. [Monitoring and Troubleshooting](#monitoring-and-troubleshooting)
6. [Advanced Queue Optimization](#advanced-queue-optimization)
7. [Integration with Main Pipeline](#integration-with-main-pipeline)

## Queue System Overview

The document processing queue manages documents through the entire processing lifecycle with these key benefits:

- **Reliability**: Automatic retries for failed documents
- **Scalability**: Multiple processors can work simultaneously
- **Monitoring**: Track processing times and failures
- **Prioritization**: Process important documents first
- **Error Handling**: Standardized approach to errors

## Database Schema Details

The queue is implemented using the `document_processing_queue` table:

```sql
CREATE TABLE IF NOT EXISTS public.document_processing_queue (
    id SERIAL PRIMARY KEY,
    source_document_id INTEGER REFERENCES public.source_documents(id),
    source_document_uuid VARCHAR REFERENCES public.source_documents(document_uuid),
    status VARCHAR NOT NULL DEFAULT 'pending',
    priority INTEGER NOT NULL DEFAULT 5,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    last_attempt_at TIMESTAMPTZ,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processing_started_at TIMESTAMPTZ,
    processing_completed_at TIMESTAMPTZ,
    processing_duration_seconds INTEGER,
    processor_id VARCHAR,
    CONSTRAINT unique_source_document UNIQUE (source_document_id)
);

-- Create an index for efficient querying
CREATE INDEX idx_document_processing_queue_status ON public.document_processing_queue(status);
```

### Key Fields

| Field | Description |
|-------|-------------|
| `id` | Unique identifier for the queue item |
| `source_document_id` | Reference to the source document being processed |
| `source_document_uuid` | UUID of the source document (for Neo4j relationships) |
| `status` | Current status: 'pending', 'processing', 'completed', 'failed', 'cancelled' |
| `priority` | Processing priority (lower numbers = higher priority) |
| `attempts` | Number of processing attempts so far |
| `max_attempts` | Maximum allowed retry attempts |
| `last_attempt_at` | Timestamp of the most recent processing attempt |
| `last_error` | Text description of the most recent error |
| `processing_started_at` | When current processing began |
| `processing_completed_at` | When processing finished (success or failure) |
| `processing_duration_seconds` | Total processing time in seconds |
| `processor_id` | Identifier of the processor handling this document |

### Automatic Queue Management with Triggers

Two database triggers keep the queue in sync with document status:

#### 1. Auto-queue new documents trigger:

```sql
CREATE OR REPLACE FUNCTION queue_document_for_processing()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO public.document_processing_queue (
        source_document_id,
        source_document_uuid,
        status,
        created_at,
        updated_at
    ) VALUES (
        NEW.id,
        NEW.document_uuid,
        'pending',
        NOW(),
        NOW()
    )
    ON CONFLICT (source_document_id) DO NOTHING;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER auto_queue_document
AFTER INSERT ON public.source_documents
FOR EACH ROW
EXECUTE FUNCTION queue_document_for_processing();
```

This trigger automatically adds each new document to the queue when it's inserted into the `source_documents` table.

#### 2. Auto-update on completion trigger:

```sql
CREATE OR REPLACE FUNCTION update_queue_on_document_completion()
RETURNS TRIGGER AS $$
BEGIN
    -- Only update the queue if the processing status indicates completion or failure
    IF NEW.initial_processing_status IN ('completed', 'error', 'extraction_failed', 'extraction_unsupported') THEN
        UPDATE public.document_processing_queue
        SET 
            status = CASE 
                WHEN NEW.initial_processing_status = 'completed' THEN 'completed'
                ELSE 'failed'
            END,
            processing_completed_at = NOW(),
            processing_duration_seconds = EXTRACT(EPOCH FROM (NOW() - processing_started_at))::INTEGER,
            updated_at = NOW()
        WHERE source_document_id = NEW.id;
    END IF;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_queue_on_completion
AFTER UPDATE OF initial_processing_status ON public.source_documents
FOR EACH ROW
WHEN (OLD.initial_processing_status IS DISTINCT FROM NEW.initial_processing_status)
EXECUTE FUNCTION update_queue_on_document_completion();
```

This trigger updates the queue item status when a document's processing status changes to a terminal state.

## Queue Processor Implementation

The QueueProcessor class is the core component that interacts with the queue table. Here's how to implement it in a new file called `queue_processor.py`:

```python
# queue_processor.py
import os
import logging
import time
import socket
import uuid
from datetime import datetime, timedelta
from typing import List, Dict, Optional

from supabase_utils import SupabaseManager
from main_pipeline import process_single_document
from config import PROJECT_ID_GLOBAL

logger = logging.getLogger(__name__)

class QueueProcessor:
    """
    Process documents from the document_processing_queue
    """
    
    def __init__(self, batch_size: int = 10, max_processing_time_minutes: int = 30):
        """Initialize the queue processor"""
        self.db_manager = SupabaseManager()
        self.batch_size = batch_size
        self.max_processing_time = max_processing_time_minutes
        # Generate a unique processor ID using hostname and a UUID
        self.processor_id = f"{socket.gethostname()}_{uuid.uuid4()}"
        logger.info(f"Initialized QueueProcessor with ID: {self.processor_id}")
        
    def claim_pending_documents(self) -> List[Dict]:
        """Claim a batch of pending documents for processing using SQL FOR UPDATE SKIP LOCKED"""
        try:
            # Get project info first
            project_sql_id, project_uuid = self.db_manager.get_or_create_project(PROJECT_ID_GLOBAL)
            
            # Execute query to claim documents
            query = f"""
            UPDATE document_processing_queue
            SET 
                status = 'processing',
                attempts = attempts + 1,
                last_attempt_at = NOW(),
                processing_started_at = NOW(),
                processor_id = '{self.processor_id}',
                updated_at = NOW()
            WHERE id IN (
                SELECT id FROM document_processing_queue
                WHERE status = 'pending'
                AND attempts < max_attempts
                ORDER BY priority, created_at
                LIMIT {self.batch_size}
                FOR UPDATE SKIP LOCKED
            )
            RETURNING id, source_document_id, source_document_uuid, attempts;
            """
            
            result = self.db_manager.client.rpc('execute_query', {"query": query}).execute()
            claimed_docs = result.data if result.data else []
            
            if claimed_docs:
                logger.info(f"Claimed {len(claimed_docs)} documents for processing")
                
                # Get full source document info for each claimed document
                claimed_docs_with_details = []
                for doc in claimed_docs:
                    source_doc = self.db_manager.get_document_by_id(doc['source_document_id'])
                    if source_doc:
                        claimed_docs_with_details.append({
                            'queue_id': doc['id'],
                            'source_doc_id': doc['source_document_id'],
                            'source_doc_uuid': doc['source_document_uuid'],
                            'attempts': doc['attempts'],
                            'project_id': project_sql_id,
                            'project_uuid': project_uuid,
                            'file_path': source_doc['original_file_path'],
                            'file_name': source_doc['original_file_name'],
                            'file_type': source_doc['detected_file_type']
                        })
                
                return claimed_docs_with_details
            else:
                logger.info("No pending documents found in queue")
                return []
                
        except Exception as e:
            logger.error(f"Error claiming documents from queue: {str(e)}")
            return []
    
    def mark_queue_item_failed(self, queue_id: int, error_message: str) -> None:
        """Mark a queue item as failed"""
        try:
            update_data = {
                'status': 'failed',
                'last_error': error_message,
                'processing_completed_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat()
            }
            
            response = self.db_manager.client.table('document_processing_queue').update(update_data).eq('id', queue_id).execute()
            logger.info(f"Queue item {queue_id} marked as failed: {error_message}")
            
        except Exception as e:
            logger.error(f"Error marking queue item {queue_id} as failed: {str(e)}")
    
    def check_for_stalled_documents(self) -> None:
        """Check for documents that have been processing for too long and reset them"""
        try:
            stall_threshold = datetime.now() - timedelta(minutes=self.max_processing_time)
            
            query = f"""
            UPDATE document_processing_queue
            SET 
                status = 'pending',
                last_error = 'Processing timed out after {self.max_processing_time} minutes',
                updated_at = NOW()
            WHERE status = 'processing'
            AND processing_started_at < '{stall_threshold.isoformat()}'
            RETURNING id;
            """
            
            result = self.db_manager.client.rpc('execute_query', {"query": query}).execute()
            stalled_docs = result.data if result.data else []
            
            if stalled_docs:
                logger.warning(f"Reset {len(stalled_docs)} stalled documents in queue")
            
        except Exception as e:
            logger.error(f"Error checking for stalled documents: {str(e)}")
    
    def process_queue(self, max_documents: int = None, single_run: bool = False) -> None:
        """
        Process documents from the queue
        
        Args:
            max_documents: Maximum number of documents to process (None = unlimited)
            single_run: If True, process one batch and exit; if False, run continuously
        """
        documents_processed = 0
        
        logger.info(f"Starting queue processing (max_documents={max_documents}, single_run={single_run})")
        
        while True:
            # Check for stalled documents
            self.check_for_stalled_documents()
            
            # Claim a batch of documents
            documents = self.claim_pending_documents()
            
            if not documents:
                if single_run:
                    logger.info("No more documents to process and single_run=True, exiting")
                    break
                else:
                    logger.info("No documents to process, waiting 60 seconds before checking again")
                    time.sleep(60)
                    continue
            
            # Process each document
            for doc in documents:
                try:
                    logger.info(f"Processing document: {doc['file_name']} (queue_id: {doc['queue_id']})")
                    
                    # Process the document
                    process_single_document(
                        self.db_manager,
                        doc['source_doc_id'],
                        doc['source_doc_uuid'],
                        doc['file_path'],
                        doc['file_name'],
                        doc['file_type'],
                        doc['project_id'],
                        doc['project_uuid']
                    )
                    
                    # Note: We don't need to explicitly mark as completed
                    # The trigger will update the status when source_document is updated
                    
                    documents_processed += 1
                    
                    # Check if we've reached the maximum number of documents
                    if max_documents and documents_processed >= max_documents:
                        logger.info(f"Reached maximum number of documents to process ({max_documents}), exiting")
                        return
                        
                except Exception as e:
                    logger.error(f"Error processing document {doc['file_name']}: {str(e)}")
                    self.mark_queue_item_failed(doc['queue_id'], str(e))
            
            # If single_run, exit after processing one batch
            if single_run:
                logger.info(f"Processed {len(documents)} documents in single run, exiting")
                break
                
            # Small delay between batches
            time.sleep(5)

def main():
    """Main function to start the queue processor"""
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(module)s - %(message)s')
    
    processor = QueueProcessor(batch_size=5)
    processor.process_queue()

if __name__ == '__main__':
    main()
```

## Running the Queue Processor

### Setting Up as a Service

For production environments, run the queue processor as a system service:

1. Create a systemd service file (on Linux):

```bash
sudo nano /etc/systemd/system/document-queue-processor.service
```

2. Add the following content:

```
[Unit]
Description=Document Processing Queue Service
After=network.target

[Service]
User=youruser
WorkingDirectory=/path/to/your/project
ExecStart=/usr/bin/python3 /path/to/your/project/queue_processor.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

3. Enable and start the service:

```bash
sudo systemctl enable document-queue-processor
sudo systemctl start document-queue-processor
```

### Running Multiple Processors

For higher throughput, run multiple queue processors in parallel:

```bash
# Start 3 processors with different batch sizes
python queue_processor.py --batch-size 10 --processor-name processor1
python queue_processor.py --batch-size 5 --processor-name processor2
python queue_processor.py --batch-size 5 --processor-name processor3
```

The "FOR UPDATE SKIP LOCKED" SQL pattern ensures each processor claims different documents from the queue.

## Monitoring and Troubleshooting

### Queue Monitoring View

Create a database view for monitoring queue status:

```sql
CREATE OR REPLACE VIEW queue_status_summary AS
SELECT
    status,
    COUNT(*) AS item_count,
    MIN(created_at) AS oldest_item,
    AVG(EXTRACT(EPOCH FROM (NOW() - created_at)))/3600 AS avg_age_hours,
    SUM(CASE WHEN attempts > 0 THEN 1 ELSE 0 END) AS items_with_attempts,
    AVG(attempts) AS avg_attempts,
    AVG(processing_duration_seconds) AS avg_processing_time_seconds
FROM 
    document_processing_queue
GROUP BY 
    status;
```

### Monitoring Query Examples

Check stalled processing items:

```sql
SELECT 
    id, source_document_id, attempts, 
    processing_started_at, last_error, processor_id
FROM 
    document_processing_queue
WHERE 
    status = 'processing'
    AND processing_started_at < NOW() - INTERVAL '1 hour'
ORDER BY 
    processing_started_at;
```

Check frequently failing documents:

```sql
SELECT 
    id, source_document_id, attempts, 
    last_error
FROM 
    document_processing_queue
WHERE 
    attempts >= 2
ORDER BY 
    attempts DESC, last_attempt_at DESC;
```

### Dashboard Metrics to Consider

1. Queue size by status
2. Average processing time
3. Failure rate
4. Documents processed per hour
5. Queue age distribution

## Advanced Queue Optimization

### Priority Strategies

Implement priority assignment based on document characteristics:

```python
def determine_document_priority(doc_type, file_size, project_id):
    # Lower number = higher priority
    if doc_type == "legal_filing":
        return 1  # Highest priority
    elif doc_type == "contract":
        return 2
    elif file_size > 10 * 1024 * 1024:  # Large files (>10MB)
        return 8  # Lower priority for resource-intensive docs
    else:
        return 5  # Default priority
```

### Resource-Aware Processing

Make queue processing adapt to system resources:

```python
def adjust_batch_size_based_on_resources():
    """Dynamically adjust batch size based on system resources"""
    import psutil
    
    # Check available memory
    mem = psutil.virtual_memory()
    cpu_percent = psutil.cpu_percent()
    
    if mem.percent > 80 or cpu_percent > 80:
        # System under heavy load
        return 2  # Small batch size
    elif mem.percent > 60 or cpu_percent > 60:
        # Moderate load
        return 5
    else:
        # Low load
        return 10
```

### Adding Bulk Operations

Optimize database operations with bulk updates:

```python
def bulk_claim_documents(self, count: int) -> List[Dict]:
    """Claim multiple documents in a single database operation"""
    # Implementation details...
    
def bulk_mark_completed(self, queue_ids: List[int]) -> None:
    """Mark multiple documents as completed in a single operation"""
    # Implementation details...
```

## Integration with Main Pipeline

### Add to main_pipeline.py

Integrate queue processing with your main pipeline by modifying the `main` function:

```python
# In main_pipeline.py

def main(mode: str = "direct"):
    """
    Run the legal document processing pipeline
    
    Args:
        mode: Processing mode ('direct' or 'queue')
    """
    logger.info(f"Starting Legal NLP Pre-processing Pipeline in {mode} mode")
    initialize_all_models()  # Load all ML/DL models once

    # Initialize Supabase manager
    db_manager = SupabaseManager()

    # Get project info
    project_sql_id, project_uuid = db_manager.get_or_create_project(
        PROJECT_ID_GLOBAL, 
        "My Legal Project"
    )
    
    if mode == "queue":
        # Use queue-based processing
        from queue_processor import QueueProcessor
        
        processor = QueueProcessor(batch_size=5)
        processor.process_queue(max_documents=None, single_run=False)
    else:
        # Direct processing (original implementation)
        # [... existing document processing code ...]
        pass

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Legal NLP Pre-processing Pipeline')
    parser.add_argument('--mode', choices=['direct', 'queue'], default='queue',
                        help='Processing mode (direct or queue-based)')
    args = parser.parse_args()
    
    main(mode=args.mode)
```

### Command to Start Processing

Run the pipeline in queue mode:

```bash
python main_pipeline.py --mode queue
```

### Queue Population for Existing Documents

For existing projects, populate the queue with documents that need processing:

```python
def populate_queue_with_documents(project_uuid: str, status_filter: str = None):
    """Populate the queue with documents from a project"""
    db_manager = SupabaseManager()
    
    query = f"""
    INSERT INTO document_processing_queue
    (source_document_id, source_document_uuid, status, created_at, updated_at)
    SELECT 
        sd.id, 
        sd.document_uuid, 
        'pending', 
        NOW(), 
        NOW()
    FROM 
        source_documents sd
    WHERE 
        sd.project_uuid = '{project_uuid}'
    """
    
    if status_filter:
        query += f"AND sd.initial_processing_status = '{status_filter}'"
    
    query += """
    ON CONFLICT (source_document_id) DO NOTHING
    RETURNING id;
    """
    
    result = db_manager.client.rpc('execute_query', {"query": query}).execute()
    added_count = len(result.data) if result.data else 0
    
    logger.info(f"Added {added_count} documents to the processing queue for project {project_uuid}")
    return added_count
```

Run this function to populate the queue for your existing projects:

```python
# For Project 1: Populate with all pending documents
populate_queue_with_documents('ca7b5cba-c5f6-493c-a6b5-a8e237787b9b', 'pending_intake')

# For Project 2: Populate with OCR completed documents ready for next steps
populate_queue_with_documents('372fa7d7-96b2-463b-85ac-0120e502d0a8', 'ocr_completed')
```

---

By implementing this queue-based processing system, you'll transform your pipeline into a robust, scalable system that can handle large volumes of documents reliably. The queue ensures no document is lost in processing, provides retries for transient failures, and gives you visibility into the processing status of each document.