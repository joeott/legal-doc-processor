# Context 64: Frontend Upload Error Analysis

## Error Summary
The document upload process is failing with a 400 Bad Request error when the Edge Function attempts to insert into the `document_processing_queue` table. The error occurs after successfully uploading the file to Supabase Storage and creating the `source_documents` entry.

## Error Details

### Supabase Error Response
```json
{
  "request": {
    "method": "POST",
    "path": "/rest/v1/document_processing_queue",
    "host": "yalswdiexcuanszujjhl.supabase.co",
    "headers": {
      "content_type": "application/json",
      "user_agent": "Vercel Edge Functions",
      "x_client_info": "supabase-js-node/2.49.8"
    }
  },
  "response": {
    "status_code": 400,
    "headers": {
      "content_type": "application/json; charset=utf-8"
    }
  }
}
```

## System Components Analysis

### 1. Frontend Upload Form (`/frontend/public/upload.html`)
```html
<form id="uploadForm">
  <input type="text" id="documentName" name="documentName" required>
  <select id="projectSelect" name="projectId" required>
    <option value="">Select a project</option>
    <option value="_new_">+ Create New Project</option>
  </select>
  <!-- File input handled by dropzone -->
</form>
```

### 2. Upload JavaScript (`/frontend/public/upload.js`)

#### Key Functions:
- **`processDocumentUpload(formData)`**: Sends FormData to Edge Function
- **`loadProjects()`**: Fetches projects from Supabase
- **Form submission handler**: Prepares FormData with:
  ```javascript
  formData.append('userDefinedName', documentNameInput.value.trim());
  formData.append('projectId', projectSelect.value);
  formData.append('originalFileName', selectedFile.name);
  formData.append('fileType', selectedFile.type);
  formData.append('fileSize', selectedFile.size);
  formData.append('documentFile', selectedFile);
  ```

### 3. Vercel Edge Function (`/frontend/api/create-document-entry.ts`)

#### Process Flow:
1. **Parse FormData** from request
2. **Validate inputs** (userDefinedName, projectId/projectName, file)
3. **Create/validate project**:
   - If new project: Insert into `projects` table
   - If existing: Validate project exists
4. **Generate document UUID** and S3 key
5. **Upload file** to Supabase Storage bucket `documents`
6. **Insert into `source_documents`** table with columns:
   - `document_uuid`
   - `project_fk_id` (integer)
   - `project_uuid`
   - `user_defined_name`
   - `original_file_name`
   - `original_file_path`
   - `s3_bucket`
   - `s3_key`
   - `s3_region`
   - `file_size_bytes`
   - `detected_file_type`
   - `content_type`
   - `initial_processing_status`
   - `intake_timestamp`
7. **Insert into `document_processing_queue`** (THIS IS WHERE IT FAILS):
   ```typescript
   const { error: queueError } = await supabaseAdmin
     .from('document_processing_queue')
     .insert({
       source_document_id: docData.id,
       source_document_uuid: documentUuid,
       status: 'pending',
       priority: 1,
       retry_count: 0,
       max_retries: 3,
       ocr_provider: fileExt === 'pdf' ? 'textract' : null,
     });
   ```

### 4. Database Tables Involved

#### `projects` Table
- `id` (integer, primary key)
- `projectId` (varchar, unique)
- `displayName` (text)
- `isActive` (boolean)

#### `source_documents` Table
- `id` (integer, primary key)
- `project_fk_id` (integer, NOT NULL, FK to projects.id)
- `document_uuid` (varchar, NOT NULL)
- `original_file_path` (text, NOT NULL, UNIQUE)
- `original_file_name` (text, NOT NULL)
- `project_uuid` (varchar, NOT NULL)
- Additional metadata columns...

#### `document_processing_queue` Table
- Structure needs investigation for column requirements

### 5. Database Triggers

There may be database triggers that automatically create queue entries when documents are inserted. Need to check:
- Triggers on `source_documents` table
- Trigger conditions based on `initial_processing_status`

## Root Cause Analysis

### Hypothesis 1: Duplicate Queue Entry
If a database trigger automatically creates a queue entry when `initial_processing_status = 'pending_ocr'`, then the Edge Function's attempt to manually insert into the queue would fail with a duplicate key error.

### Hypothesis 2: Missing Required Fields
The `document_processing_queue` table may have required fields not being provided in the insert.

### Hypothesis 3: Data Type Mismatch
The `ocr_provider` field uses a custom enum type that may require special handling.

## Debugging Steps

1. **Check for database triggers**:
   ```sql
   SELECT trigger_name, event_manipulation, event_object_table, action_statement 
   FROM information_schema.triggers 
   WHERE event_object_schema = 'public' 
   AND event_object_table IN ('source_documents', 'document_processing_queue');
   ```

2. **Examine queue table schema**:
   ```sql
   SELECT column_name, data_type, is_nullable, column_default 
   FROM information_schema.columns 
   WHERE table_name = 'document_processing_queue' 
   ORDER BY ordinal_position;
   ```

3. **Check for existing queue entries**:
   ```sql
   SELECT * FROM document_processing_queue 
   WHERE source_document_uuid = '[document_uuid_from_error]' 
   OR source_document_id = [id_from_source_documents];
   ```

## Recommended Fixes

### Option 1: Remove Manual Queue Insert
If a trigger handles queue creation, remove the manual insert from the Edge Function:
```typescript
// Remove or comment out this section:
const { error: queueError } = await supabaseAdmin
  .from('document_processing_queue')
  .insert({...});
```

### Option 2: Check Before Insert
Add logic to check if queue entry already exists:
```typescript
// Check if queue entry exists
const { data: existingQueue } = await supabaseAdmin
  .from('document_processing_queue')
  .select('id')
  .eq('source_document_id', docData.id)
  .single();

if (!existingQueue) {
  // Only insert if not exists
  const { error: queueError } = await supabaseAdmin
    .from('document_processing_queue')
    .insert({...});
}
```

### Option 3: Fix Data Types
Ensure all data types match the schema, particularly for enum types:
```typescript
ocr_provider: fileExt === 'pdf' ? 'textract' : null
```

## Related Files and Scripts

1. **Frontend Files**:
   - `/frontend/public/upload.html` - Upload form UI
   - `/frontend/public/upload.js` - Client-side upload logic
   - `/frontend/public/style.css` - Styling
   - `/frontend/public/env-config.js` - Environment configuration

2. **Backend/Edge Function**:
   - `/frontend/api/create-document-entry.ts` - Vercel Edge Function
   - `/frontend/package.json` - Dependencies
   - `/frontend/vercel.json` - Vercel configuration

3. **Database Migrations**:
   - `/frontend/migrations/00001_add_project_link_to_source_documents.sql`
   - `/frontend/migrations/00002_fix_queue_triggers.sql`
   - `/frontend/migrations/00003_fix_notification_trigger.sql`

4. **Backend Processing**:
   - `/scripts/queue_processor.py` - Processes queued documents
   - `/scripts/main_pipeline.py` - Main processing pipeline
   - `/scripts/supabase_utils.py` - Database utilities

## Environment Variables Required

- `SUPABASE_URL`
- `SUPABASE_ANON_KEY` (frontend)
- `SUPABASE_SERVICE_ROLE_KEY` (Edge Function)
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `AWS_DEFAULT_REGION`
- `S3_PRIMARY_DOCUMENT_BUCKET`

## Root Cause Identified

Database triggers automatically create queue entries when documents are inserted into `source_documents`. There are THREE triggers that handle this:

1. **`auto_queue_document`** - Simple queue entry creation with ON CONFLICT DO NOTHING
2. **`modernized_create_queue_entry_trigger`** - Sophisticated with duplicate checking and dynamic priority
3. **`trigger_create_queue_entry`** - Mid-level implementation with dynamic processing steps

These triggers fire on INSERT to `source_documents` and automatically create the queue entry, making the manual insert in the Edge Function redundant and causing a conflict.

## Solution Applied

Removed the manual queue insertion from the Edge Function (`/frontend/api/create-document-entry.ts`). The database triggers handle queue creation automatically based on the `initial_processing_status` field.

## Deployment Status

The fix has been implemented and is ready for deployment. The Edge Function now:
1. Uploads file to Supabase Storage
2. Creates entry in `source_documents` with `initial_processing_status = 'pending_ocr'`
3. Lets database triggers handle queue creation automatically

This resolves the 400 Bad Request error on the `document_processing_queue` insertion.