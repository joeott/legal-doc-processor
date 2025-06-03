# Document Processing Flow Monitoring

This document provides details on how to monitor the document processing flow, focusing on phases 1-3 (upload, queue processing, and OCR text extraction) with the new Mistral OCR implementation.

## 1. Flow Control Mechanisms

The document processing flow is controlled through several mechanisms:

### 1.1 Database Triggers

The following database triggers automate the document processing flow:

1. **`auto_queue_document` / `trigger_create_queue_entry` / `queue_document_for_processing`**
   - **Trigger Event**: INSERT on `source_documents` table
   - **Action**: Creates an entry in `document_processing_queue` with status='pending'
   - **Implementation**:
     ```sql
     -- When a new document is created
     INSERT INTO public.document_processing_queue (
         source_document_uuid,
         status,
         processing_step
     ) VALUES (
         NEW.document_uuid,
         'pending',
         'intake'
     )
     ```

2. **`update_queue_on_completion` / `update_queue_on_document_terminal_state`**
   - **Trigger Event**: UPDATE on `source_documents` table
   - **Action**: Updates queue status when document processing completes or fails
   - **Implementation**:
     ```sql
     -- When document status changes to a terminal state ('completed', 'error', etc.)
     UPDATE public.document_processing_queue
     SET
         status = CASE
             WHEN NEW.initial_processing_status = 'completed' THEN 'completed'
             ELSE 'failed'
         END,
         processing_completed_at = NOW()
     WHERE source_document_id = NEW.id AND status = 'processing'
     ```

### 1.2 Supabase Edge Functions

1. **`create-document-entry`**
   - **Path**: `/frontend/supabase/functions/create-document-entry/index.ts`
   - **Purpose**: Creates document entries when files are uploaded via frontend
   - **Actions**:
     - Creates entry in `source_documents` table with status='pending_intake'
     - Sets document_uuid and links to project
     - Database trigger then automatically creates queue entry

## 2. Processing Flow Stages

### 2.1 Phase 1: Document Upload

1. **Frontend Upload**:
   - User uploads PDF through Vercel frontend
   - File is stored in Supabase Storage 'documents' bucket
   - Edge function creates document entry with 'pending_intake' status
   
2. **Trigger Activation**:
   - `queue_document_for_processing` trigger fires automatically
   - Creates entry in `document_processing_queue` with 'pending' status

3. **Monitoring SQL**:
   ```sql
   -- Check for newly created document
   SELECT id, document_uuid, original_file_name, initial_processing_status 
   FROM source_documents 
   ORDER BY id DESC LIMIT 1;
   
   -- Verify queue entry was created
   SELECT id, source_document_uuid, status, processing_step 
   FROM document_processing_queue 
   ORDER BY id DESC LIMIT 1;
   ```

### 2.2 Phase 2: Queue Processing

1. **Worker Initialization**:
   - `queue_processor.py` runs and initializes `QueueProcessor` class
   - Checks for documents with 'pending' status in queue
   
2. **Document Claiming**:
   - Uses `FOR UPDATE SKIP LOCKED` to safely claim documents in concurrent environments
   - Updates queue entry with 'processing' status and processor_id
   - Downloads document from Supabase Storage if needed

3. **Monitoring SQL**:
   ```sql
   -- Check documents being processed
   SELECT id, source_document_id, status, processor_id, processing_started_at 
   FROM document_processing_queue 
   WHERE status = 'processing';
   
   -- Check for stalled processing (running too long)
   SELECT id, source_document_id, status, processor_id, 
          EXTRACT(EPOCH FROM (NOW() - processing_started_at))/60 as minutes_running
   FROM document_processing_queue 
   WHERE status = 'processing' 
   ORDER BY minutes_running DESC;
   ```

### 2.3 Phase 3: OCR Text Extraction

1. **OCR Method Selection**:
   - In `main_pipeline.py:process_single_document`, checks `USE_MISTRAL_FOR_OCR` configuration
   - If true, calls `extract_text_from_pdf_mistral_ocr` from `ocr_extraction.py`
   - Otherwise, uses Qwen VL OCR as fallback

2. **Mistral OCR Process**:
   - Extracts document path from Supabase Storage
   - Generates public URL using `generate_document_url` from `supabase_utils.py`
   - Calls Mistral OCR API via `extract_text_from_url` in `mistral_utils.py`
   - Processes API response and extracts text with metadata
   - Updates document status to 'ocr_complete_pending_doc_node'

3. **Monitoring SQL**:
   ```sql
   -- Check OCR extraction results
   SELECT id, substring(raw_extracted_text, 1, 200) as text_sample, 
          ocr_metadata_json->0->>'method' as ocr_method,
          ocr_metadata_json->0->>'processing_time_seconds' as processing_time
   FROM source_documents
   WHERE initial_processing_status = 'ocr_complete_pending_doc_node'
   ORDER BY id DESC LIMIT 1;
   ```

## 3. Live Monitoring System

### 3.1 Real-Time Monitoring Dashboard

We've implemented a comprehensive real-time monitoring dashboard in `/monitoring/live_monitor.py` that provides continuous visibility into the document processing pipeline.

#### Architecture Overview

1. **Multi-Layered Monitoring**:
   - **Database Layer**: Tracks document and queue status changes
   - **Process Layer**: Monitors running queue processors
   - **API Layer**: Tracks Mistral OCR API interactions and performance
   - **Flow Layer**: Visualizes document progression through pipeline stages

2. **Real-Time Update Mechanisms**:
   - **PostgreSQL Notification Channels**: Receives immediate updates on document status changes
   - **Polling Fallback**: Gracefully degrades to periodic polling if notifications aren't available
   - **Event-Driven Updates**: Dashboard refreshes instantly when relevant changes occur

3. **Dashboard Components**:
   - **Queue Statistics Panel**: Real-time counts of documents in each state
   - **OCR Method Distribution**: Tracks usage of Mistral vs. Qwen OCR methods
   - **Active Processors Panel**: Shows running processor instances
   - **Document Tracking Table**: Detailed view of documents in the pipeline

#### Key Implementation Features

1. **Robust Connection Management**:
   - Automatic reconnection to database if connection is lost
   - Graceful degradation when notification channels aren't available
   - Multiple connection methods (Supabase SDK + direct PostgreSQL)

2. **Performance Optimizations**:
   - Caches document information to minimize database queries
   - Uses incremental updates where possible
   - Batches database operations for efficiency

3. **Error Handling and Resilience**:
   - Catches and logs exceptions without crashing
   - Recovers from transient database errors
   - Maintains state during connection interruptions

4. **Extensibility for Future Phases**:
   - Modular design easily extends to track additional processing phases
   - Status tracking framework supports arbitrary pipeline stages
   - Color-coded status visualization adaptable to new states

### 3.2 Technical Implementation Details

The monitoring system uses several advanced techniques:

#### 1. PostgreSQL Notification System

```python
def setup_notification_channel(self):
    """Set up PostgreSQL notification channel for real-time updates."""
    cursor = self.db_conn.cursor()
    
    # Create notification function
    notification_function_sql = """
    CREATE OR REPLACE FUNCTION notify_document_status_change()
    RETURNS TRIGGER AS $$
    BEGIN
      PERFORM pg_notify(
        'document_status_changes',
        json_build_object(
          'table', TG_TABLE_NAME,
          'id', NEW.id,
          'status', CASE 
            WHEN TG_TABLE_NAME = 'source_documents' THEN NEW.initial_processing_status
            ELSE NEW.status
            END,
          'timestamp', NOW()
        )::text
      );
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """
    cursor.execute(notification_function_sql)
    
    # Create triggers for both tables
    cursor.execute("LISTEN document_status_changes;")
```

This enables instant updates without polling, significantly reducing database load while providing real-time feedback.

#### 2. Rich UI Framework

```python
def create_dashboard(self):
    """Create a comprehensive dashboard with all panels."""
    layout = Layout()
    
    # Create multi-panel layout
    layout.split(
        Layout(name="upper", ratio=1),
        Layout(name="lower", ratio=2)
    )
    
    layout["upper"].split_row(
        Layout(name="queue_stats"),
        Layout(name="ocr_stats"),
        Layout(name="processors")
    )
    
    # Assign panels to layout sections
    layout["queue_stats"].update(self.create_stats_table())
    layout["ocr_stats"].update(self.create_ocr_stats_table())
    layout["processors"].update(self.create_processors_panel())
    layout["lower"].update(self.create_documents_table())
    
    return layout
```

The UI layout is designed for information density while maintaining clarity, with color coding to highlight status changes and issues.

#### 3. Hybrid Update Strategy

```python
def refresh_data(self, force=False):
    """Refresh all data from database using optimal strategy."""
    notification_received = self.check_for_notifications()
    
    # Refresh on notification or scheduled interval
    if force or notification_received or time.time() - self._last_refresh > self.refresh_interval:
        self.fetch_queue_stats()
        self.fetch_ocr_stats()
        self.fetch_active_processors()
        self.fetch_recent_documents()
        
        self._last_refresh = time.time()
        return True
        
    return False
```

This hybrid approach provides the responsiveness of event-driven updates with the reliability of periodic polling.

### 3.3 Extensibility for Downstream Processing Phases

The monitor is designed to seamlessly incorporate additional processing phases beyond OCR:

#### 1. Modular Status Tracking

Each processing phase is tracked independently, with separate SQL queries and status panels that can be extended without modifying existing components.

```python
# Example extension for entity extraction phase
def fetch_entity_extraction_stats(self):
    """Fetch statistics about entity extraction."""
    query = """
    SELECT 
      COUNT(*) as total_entities,
      COUNT(DISTINCT document_id) as documents_with_entities,
      AVG(entity_count) as avg_entities_per_doc
    FROM (
      SELECT 
        d.id as document_id,
        COUNT(em.id) as entity_count
      FROM neo4j_documents d
      JOIN neo4j_chunks c ON d.id = c.document_id
      JOIN neo4j_entity_mentions em ON c.id = em.chunk_id
      GROUP BY d.id
    ) entity_counts
    """
    
    response = self.supabase.rpc('execute_query', {'query': query}).execute()
    # Process response...
```

#### 2. Phase-Specific Visualization

The dashboard has a pluggable panel system where new visualizations can be added for additional phases:

```python
# Extension method for entity visualization
def create_entity_distribution_panel(self):
    """Create a panel showing entity type distribution."""
    table = Table(title="Entity Type Distribution")
    
    table.add_column("Entity Type", style="bold")
    table.add_column("Count")
    table.add_column("Percentage")
    
    # Add entity type rows...
    
    return table
```

#### 3. Progressive Status Tracking

The dashboard can monitor the entire document lifecycle by tracking status transitions through all processing phases:

```python
# Status progression tracking across all phases
document_lifecycle_states = {
    "Phase 1 - Upload": ["pending_intake"],
    "Phase 2 - Queue": ["pending", "processing"],
    "Phase 3 - OCR": ["ocr_complete_pending_doc_node"],
    "Phase 4 - Neo4j": ["pending_metadata", "pending_chunking"],
    "Phase 5 - Chunking": ["pending_ner", "pending_entities"],
    "Phase 6 - NER": ["pending_canonicalization"],
    "Phase 7 - Entity Resolution": ["pending_relationships"],
    "Phase 8 - Relationships": ["complete"],
    "Error States": ["error", "failed", "extraction_failed", "extraction_unsupported"]
}
```

## 4. Log-Based Monitoring

In addition to the live dashboard, traditional logging remains available:

### 4.1 Script Logging

1. **Script Logging**:
   - Enable DEBUG logging when running queue processor:
     ```bash
     python queue_processor.py --single-run --log-level DEBUG
     ```
   - All scripts use Python's logging module with configurable levels
   - Key logs to watch for:
     - "Claiming pending documents"
     - "Processing document with Mistral OCR API"
     - "OCR request successful"

2. **Log File Location**:
   - Logs are printed to standard output by default
   - To save logs to a file, redirect output:
     ```bash
     python queue_processor.py --single-run --log-level DEBUG > processing.log 2>&1
     ```
   - The live monitor can also capture and display logs in its interface

### 4.2 Database Monitoring

1. **Status Tracking**:
   - Monitor document status in `source_documents.initial_processing_status`:
     - 'pending_intake' → Initial upload state
     - 'ocr_complete_pending_doc_node' → OCR successful
     - 'error' → Processing failed
   
   - Monitor queue status in `document_processing_queue.status`:
     - 'pending' → Waiting to be processed
     - 'processing' → Currently being processed
     - 'completed' → Successfully processed
     - 'failed' → Processing failed

2. **Error Monitoring**:
   - Check error messages in `document_processing_queue.last_error`
   - Check error details in `source_documents.error_message`

3. **Performance Monitoring**:
   - Track processing duration in `document_processing_queue.processing_duration_seconds`
   - Check OCR processing time in `source_documents.ocr_metadata_json->>'processing_time_seconds'`

### 4.3 Real-time Monitoring SQL Queries

1. **Queue Status Summary**:
   ```sql
   SELECT status, COUNT(*) as count
   FROM document_processing_queue
   GROUP BY status
   ORDER BY count DESC;
   ```

2. **Recent Processing Activity**:
   ```sql
   SELECT 
     q.id as queue_id,
     sd.original_file_name,
     q.status as queue_status,
     sd.initial_processing_status as doc_status,
     q.processing_started_at,
     q.processing_completed_at,
     EXTRACT(EPOCH FROM (q.processing_completed_at - q.processing_started_at)) as duration_seconds
   FROM document_processing_queue q
   JOIN source_documents sd ON q.source_document_uuid = sd.document_uuid
   ORDER BY q.processing_started_at DESC NULLS LAST
   LIMIT 10;
   ```

3. **OCR Method Distribution**:
   ```sql
   SELECT 
     ocr_metadata_json->0->>'method' as ocr_method,
     COUNT(*) as count,
     AVG((ocr_metadata_json->0->>'processing_time_seconds')::NUMERIC) as avg_processing_time
   FROM source_documents
   WHERE ocr_metadata_json IS NOT NULL
   GROUP BY ocr_method
   ORDER BY count DESC;
   ```

4. **Error Detection**:
   ```sql
   SELECT 
     sd.id,
     sd.original_file_name,
     sd.initial_processing_status,
     q.status as queue_status,
     q.last_error,
     sd.error_message
   FROM source_documents sd
   JOIN document_processing_queue q ON sd.document_uuid = q.source_document_uuid
   WHERE sd.initial_processing_status LIKE '%error%' OR q.status = 'failed'
   ORDER BY sd.id DESC;
   ```

## 5. Using the Live Monitor

### 5.1 Setup and Configuration

1. **Installation**:
   - Required libraries: rich, psycopg2-binary, python-dotenv, tabulate
   - Install with pip:
     ```bash
     pip install rich psycopg2-binary python-dotenv tabulate
     ```

2. **Environment Configuration**:
   - Set up database credentials in .env file or environment variables:
     ```bash
     SUPABASE_URL=your_supabase_url
     SUPABASE_ANON_KEY=your_supabase_anon_key
     ```

3. **Starting the Monitor**:
   - Basic usage:
     ```bash
     cd /Users/josephott/Documents/phase_1_2_3_process_v5
     python monitoring/live_monitor.py
     ```
   - With configuration options:
     ```bash
     python monitoring/live_monitor.py --refresh 2 --max-docs 20 --hide-completed
     ```

### 5.2 Command Line Options

The monitor supports several configuration options:

1. **`--refresh N`**: Set refresh interval in seconds (default: 5)
2. **`--max-docs N`**: Maximum number of documents to display (default: 15)
3. **`--hide-completed`**: Hide completed documents from the display
4. **`--log-level LEVEL`**: Set logging level (DEBUG, INFO, WARNING, ERROR)

### 5.3 Workflow Integration

The live monitor integrates seamlessly with the document processing workflow:

1. **Development Workflow**:
   - Run the monitor in one terminal
   - Upload documents and run processors in other terminals
   - Watch documents progress through the pipeline in real-time

2. **Production Monitoring**:
   - Run as a background service using systemd or supervisor
   - Connect to it using SSH or a web-based terminal
   - Set up alerts based on error states

3. **Debugging Workflow**:
   - Start the monitor before running problematic processes
   - Observe status changes and catch errors as they happen
   - Identify bottlenecks and performance issues

## 6. Testing the Mistral OCR Implementation

To test the Mistral OCR implementation:

1. **Set Environment Variables**:
   ```bash
   export MISTRAL_API_KEY=your_api_key
   export USE_MISTRAL_FOR_OCR=true
   export MISTRAL_OCR_MODEL=mistral-ocr-latest
   ```

2. **Start the Live Monitor**:
   ```bash
   cd /Users/josephott/Documents/phase_1_2_3_process_v5
   python monitoring/live_monitor.py
   ```

3. **Upload Test Document**:
   - Use Vercel frontend to upload a PDF document
   - Verify it appears in the monitor's document list with "pending" status

4. **Run Queue Processor**:
   ```bash
   cd /Users/josephott/Documents/phase_1_2_3_process_v5/scripts
   python queue_processor.py --single-run --log-level DEBUG
   ```

5. **Monitor Processing**:
   - Watch document status change to "processing" then "ocr_complete_pending_doc_node"
   - Observe OCR method shown as "MistralOCR"
   - Check processing time and extracted text

6. **Verify Results**:
   - Check text extraction quality
   - Compare processing time with Qwen VL OCR
   - Examine any warnings or errors

## 7. Troubleshooting Common Issues

### 7.1 Document Stuck in Queue

**Symptoms**:
- Document remains in 'pending' status
- No processing activity visible

**Monitoring Approach**:
- Check "Queue Statistics" panel for pending documents
- Look for the document in the main document list with "pending" status
- Verify no active processors in the "Active Processors" panel

**Fix Options**:
1. Manually reset the queue entry:
   ```sql
   UPDATE document_processing_queue
   SET status = 'pending', processor_id = NULL, processing_started_at = NULL
   WHERE id = <queue_id>;
   ```
2. Check if queue processor is running correctly

### 7.2 OCR Failures

**Symptoms**:
- Document status changes to 'extraction_failed'
- Error message appears in document list
- OCR method shows as empty or fallback method

**Monitoring Approach**:
- Look for red status indicators in the document list
- Check error messages in the "Error" column
- Review OCR statistics for method distribution

**Fix Options**:
1. Check Mistral API key is valid
2. Verify document URL generation is working
3. Try with Qwen VL OCR as fallback

### 7.3 Monitor Connection Issues

**Symptoms**:
- "Failed to establish database connection" error
- Dashboard not updating with new documents
- Notification channel not working

**Checks**:
1. Verify environment variables are set correctly
2. Check Supabase service status
3. Try restarting the monitor with `--log-level DEBUG`

## 8. Extending the Monitor for Downstream Phases

The live monitor can be extended to track all phases of document processing:

### 8.1 Adding New Status Panels

Create new visualization panels for later phases:

```python
def create_entity_statistics_panel(self):
    """Create a panel showing entity extraction statistics."""
    # Implementation details...
```

### 8.2 Tracking Additional Tables

Add tracking for additional database tables:

```python
def fetch_chunking_statistics(self):
    """Fetch statistics about document chunking."""
    # Implementation details...
```

### 8.3 Creating End-to-End Dashboards

Combine all phases into a single visualization:

```python
def create_pipeline_visualization(self):
    """Create a visual representation of the entire pipeline."""
    # Implementation details...
```

## 9. Conclusion

The comprehensive monitoring system provides:

1. **Real-Time Visibility**: Through the live monitor dashboard and notification channels
2. **Robust Tracking**: Of all document processing phases from upload through OCR
3. **Extensible Design**: That can incorporate additional processing phases
4. **Multi-Modal Monitoring**: Via UI dashboard, logs, and database queries

This monitoring system ensures complete visibility into the document processing pipeline, making it easy to verify that the Mistral OCR implementation is working correctly, identify and troubleshoot issues quickly, and track the performance and reliability of the entire system.