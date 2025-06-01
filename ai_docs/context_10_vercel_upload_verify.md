# Vercel Upload Verification and Document Processing Flow

## Upload Verification Success

We have successfully fixed the document upload functionality in the Vercel deployment. The key issues were:

1. **Unique Constraint Violation**: Documents were failing to be inserted due to a conflict on the `source_document_id` column in the `document_processing_queue` table.

2. **Case Sensitivity in SQL Function**: The database function was attempting to access a column named "projectid" (all lowercase) when the actual column is "projectId" (camelCase).

3. **Document Queue Creation**: The document processing queue entries weren't being properly created due to inconsistencies in how UUIDs were being handled.

These issues have been resolved through:

1. **Properly Using UUIDs**: We implemented a consistent UUID-based approach for identifying documents throughout the system.

2. **Three-Tier Upload Strategy**: We created a robust upload strategy with three fallback methods:
   - Database Function: Direct SQL function call through RPC
   - Edge Function: Supabase Edge Function as first fallback
   - Direct API Calls: Manual document and queue creation as a final fallback

3. **SQL Function Fix**: We corrected the case sensitivity issue in the SQL function by properly quoting column names.

The successful upload debug output shows:
```
[03:50:01] Document created via edge function: {"success":true,"message":"Document entry created successfully","sourceDocumentId":462,"documentUuid":"164192bc-9ce3-4e8f-b06b-0b83fb805c79","queueId":289}
```

## How the Vercel App Works

The Vercel app provides a streamlined document upload interface that:

1. **Authenticates with Supabase**: Uses the Supabase ANON_KEY to connect to your database.

2. **Lists Available Projects**: Fetches and displays projects from the database.

3. **Handles File Upload**: Processes the selected file and uploads it to Supabase Storage.

4. **Creates Document Entries**: Inserts document information into the database and queues it for processing.

5. **Provides Debug Information**: Shows detailed logs about the upload process and any errors.

The app is designed with reliability in mind, implementing multiple fallback strategies to ensure documents are properly uploaded and queued for processing even if one method fails.

## Document Processing Flow - Next Steps for Debugging

With the upload mechanism now working correctly, you can trace the document processing pipeline to identify and debug the next components in the flow:

### 1. Document Processing Queue Flow

When a document is uploaded, the following occurs:

1. **Document Entry**: A record is created in the `source_documents` table with:
   - `document_uuid`: A unique identifier for the document
   - `initial_processing_status`: Set to 'pending_intake'
   - Other metadata about the document

2. **Queue Entry**: An entry is added to the `document_processing_queue` table with:
   - `source_document_uuid`: Linked to the document's UUID
   - `status`: Set to 'pending'
   - `processing_step`: Set to 'intake'

3. **Processing Trigger**: The document is now ready for processing by the backend system.

### 2. Debugging the Processing Pipeline

To debug the next stage of the document processing pipeline, you should:

#### Check Queue Status

```sql
SELECT * FROM document_processing_queue 
WHERE status = 'pending' 
ORDER BY created_at DESC 
LIMIT 10;
```

This will show you the most recently queued documents waiting for processing.

#### Verify Worker Status

If documents remain in 'pending' status:

1. Check if the worker process is running:
   ```bash
   # If using systemd
   sudo systemctl status document-processor.service
   
   # If using PM2
   pm2 status
   
   # Check process by name
   ps aux | grep queue_processor
   ```

2. Check worker logs:
   ```bash
   # If using systemd
   sudo journalctl -u document-processor.service -f
   
   # If using PM2
   pm2 logs document-processor
   
   # Check log files directly
   tail -f /var/log/document-processor.log
   ```

#### Trace Document Through Pipeline

For a specific document, track its progress:

```sql
-- Get the document details
SELECT id, document_uuid, initial_processing_status 
FROM source_documents 
WHERE id = 462;

-- Check its queue entries
SELECT * FROM document_processing_queue 
WHERE source_document_uuid = '164192bc-9ce3-4e8f-b06b-0b83fb805c79';
```

### 3. Key Components to Inspect

Based on the project structure, these are the key components in the processing pipeline:

1. **`/scripts/queue_processor.py`**: The main worker that processes document queue entries.
   - Check if it's running
   - Verify it's connecting to the database correctly
   - Look for errors in its logs

2. **`/scripts/main_pipeline.py`**: Likely the orchestrator for the document processing workflow.
   - Review how it handles documents in different stages
   - Check for error handling mechanisms

3. **`/scripts/text_processing.py` and `/scripts/ocr_extraction.py`**: Handle the actual text extraction from documents.
   - Verify they can access the uploaded documents
   - Check for errors in processing specific file types

### 4. Common Processing Issues

If documents aren't being processed, common issues include:

1. **Worker Not Running**: The queue processor may not be active.

2. **Database Connectivity**: The worker might not be able to connect to the database.

3. **Storage Access**: The worker might not have access to the uploaded files.

4. **Missing Dependencies**: Required libraries or tools (like OCR engines) might be missing.

5. **Processing Errors**: The worker might be encountering errors when processing certain documents.

### 5. Next Steps for Debugging

1. **Enable Verbose Logging**: Add additional logging to the processing scripts.

2. **Test Manual Processing**: Try running the processing steps manually on a test document.

3. **Check Database Triggers**: Ensure all necessary triggers are properly configured.

4. **Monitor Queue Status**: Watch the queue in real-time as documents are uploaded.

5. **Examine State Changes**: Track how document status changes throughout the processing pipeline.

## Conclusion

The document upload process has been successfully fixed and is now reliably creating both document entries and queue entries in the database. The next step is to verify that the document processing worker is picking up these queue entries and processing the documents.

By following the debugging steps outlined above, you can identify any issues in the processing pipeline and ensure documents flow smoothly from upload to completed processing.