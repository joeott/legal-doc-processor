
**Objective:** Develop a robust and extensible document intake system that integrates with an existing Supabase-backed processing queue. The system must support web-based drag-and-drop uploads with project linking and be designed for future Slack channel integration.

ALL WORK FOR THIS SCRIPT SHOULD BE IN THE /Users/josephott/Documents/phase_1_2_3_process_v5/frontend/ directory.

**Key Features to Implement:**

1.  **Web-Based Document Upload UI:**
    *   Drag-and-drop area for file uploads.
    *   Text input for users to provide a "Document Name."
    *   A dynamic list/dropdown (populated from the Supabase `projects` table) allowing users to select and link the uploaded document to a specific project.
    *   Automatic tracking of "Date Uploaded" metadata.
2.  **Backend Processing for Web Uploads:**
    *   Securely upload the file to Supabase Storage.
    *   Create an entry in the `source_documents` table, including:
        *   The user-defined "Document Name."
        *   A foreign key linking to the selected project from the `projects` table.
        *   The S3/Supabase Storage path of the uploaded document.
        *   `initial_processing_status` set to 'pending_intake' (to trigger existing queue population logic).
        *   Timestamp for "Date Uploaded."
3.  **Database Schema Considerations:**
    *   Ensure the `source_documents` table can store the user-defined document name and the foreign key to the `projects` table.
    *   Verify existing triggers (`create_queue_entry_for_new_document`) correctly populate the `document_processing_queue` when a new `source_documents` record with 'pending_intake' status is created.
4.  **Extensibility for Slack Integration:**
    *   The design should allow for a future module/service that can:
        *   Monitor a specific Slack channel for file uploads.
        *   Download files from Slack.
        *   Upload files to Supabase Storage.
        *   Create corresponding `source_documents` entries (potentially with a default project or logic to determine the project from Slack message context).

**Outputs Required:**

1.  **Detailed list of scripts/code modules needed** (frontend, backend/API, database migrations/setup).
2.  **For each script/module:**
    *   Primary language/framework.
    *   Key functions/logic to be implemented.
    *   Interaction points with other components (Supabase DB, Supabase Storage, existing queue).
3.  **Optimal configuration recommendations** for Supabase (RLS, Storage policies, Edge Functions if applicable).
4.  **Considerations for integrating with the existing `document_processing_queue` system** described in the "Operation Guide."

**Assume the following existing `projects` table structure (as provided):**

```json
{
  "type": "object",
  "properties": {
    "id": { "type": "integer", "description": "Primary key for the projects table" },
    "projectId": { "type": "string", "description": "Unique identifier for the project" },
    "name": { "type": "string", "description": "Name of the project" },
    // ... other fields
    "createdAt": { "type": "string", "format": "date-time" },
    "updatedAt": { "type": "string", "format": "date-time" }
  },
  "required": ["id", "projectId"]
}
```

---

## Proposed Script Solutions & Configuration:

Based on the prompt and your existing system, here's how we can implement this:

### 1. Database Schema Modifications (SQL)

You'll likely need to add a couple of columns to your `source_documents` table.

**File:** `migrations/YYYYMMDDHHMMSS_add_project_link_to_source_documents.sql` (or run directly in Supabase SQL Editor)

```sql
-- Add a column to store the user-defined name for the document
ALTER TABLE public.source_documents
ADD COLUMN IF NOT EXISTS user_defined_name TEXT;

-- Add a foreign key to link to the projects table
-- Assuming your projects table is named 'projects' and its primary key is 'id'
ALTER TABLE public.source_documents
ADD COLUMN IF NOT EXISTS project_id BIGINT REFERENCES public.projects(id) ON DELETE SET NULL;

-- Add an 'uploaded_at' timestamp, distinct from 'created_at' if needed,
-- though 'created_at' of source_documents can often serve this purpose.
-- If you want a dedicated one:
ALTER TABLE public.source_documents
ADD COLUMN IF NOT EXISTS uploaded_at TIMESTAMPTZ DEFAULT NOW();

-- Ensure your existing trigger 'create_queue_entry_for_new_document' correctly handles
-- new 'source_documents' entries with initial_processing_status = 'pending_intake'.
-- The trigger logic seems fine as described in the addendum for 'pending_intake'.
-- What might be missing is how 'pending_intake' transitions to 'pending' or 'pre_ocr_pending'.
-- Let's assume 'pending_intake' is a valid starting point that the QueueProcessor will eventually pick up.
-- If not, the trigger or the QueueProcessor needs a slight adjustment.

-- The 'Operation Guide' trigger `create_queue_entry_for_new_document` already handles this:
-- It creates a queue entry with status 'pending' (or 'pre_ocr_pending' if status is 'pre_ocr_pending').
-- For simple web uploads without immediate OCR, 'pending' is fine for the queue entry.
-- The 'source_documents.initial_processing_status' should be 'pending_intake'.
-- The trigger should then create a 'document_processing_queue' entry with status 'pending'.

-- Reviewing the trigger `create_queue_entry_for_new_document` from the addendum:
/*
CREATE OR REPLACE FUNCTION create_queue_entry_for_new_document() RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO document_processing_queue (
        source_document_id,
        source_document_uuid,
        status, -- This needs to be 'pending' for direct uploads that are ready for general processing
        priority,
        attempts,
        max_attempts,
        created_at,
        updated_at
    )
    VALUES (
        NEW.id,
        NEW.document_uuid, -- Assuming 'source_documents' has 'document_uuid'
        -- If NEW.initial_processing_status = 'pending_intake', set queue status to 'pending'
        CASE
            WHEN NEW.initial_processing_status = 'pre_ocr_pending' THEN 'pre_ocr_pending'
            WHEN NEW.initial_processing_status = 'pending_intake' THEN 'pending' -- Crucial for web uploads
            ELSE 'pending' -- Default fallback
        END,
        COALESCE(NEW.priority, 100), -- Allow overriding priority from source_documents if available
        0,
        COALESCE(NEW.max_attempts, 3), -- Allow overriding max_attempts
        NOW(),
        NOW()
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Make sure this trigger is active on the source_documents table for INSERT.
DROP TRIGGER IF EXISTS trg_create_queue_entry_on_new_source_document ON public.source_documents;
CREATE TRIGGER trg_create_queue_entry_on_new_source_document
AFTER INSERT ON public.source_documents
FOR EACH ROW
EXECUTE FUNCTION create_queue_entry_for_new_document();
*/
```
**Note:** The `document_uuid` column needs to exist in `source_documents`. If it doesn't, you can generate it in the trigger or have the application layer provide it. Typically, `source_documents.id` (bigint) is the PK, and `document_uuid` (uuid) is a globally unique ID.

### 2. Frontend (Web Upload UI)

**File:** `public/upload.html` (or part of a Single Page Application)

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Document Upload</title>
    <script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2"></script>
    <link rel="stylesheet" href="style.css"> <!-- Basic styling -->
</head>
<body>
    <h1>Upload Document</h1>
    <form id="uploadForm">
        <div>
            <label for="documentName">Document Name:</label>
            <input type="text" id="documentName" name="documentName" required>
        </div>
        <div>
            <label for="projectSelect">Link to Project:</label>
            <select id="projectSelect" name="projectId" required>
                <option value="">Loading projects...</option>
            </select>
        </div>
        <div id="dropZone" style="border: 2px dashed #ccc; padding: 20px; text-align: center; margin-top:10px;">
            Drag & Drop your document here or click to select
        </div>
        <input type="file" id="fileInput" style="display: none;">
        <p id="fileNameDisplay"></p>
        <button type="submit" id="submitButton" disabled>Upload Document</button>
    </form>
    <div id="statusMessage"></div>

    <script src="upload.js"></script>
</body>
</html>
```

**File:** `public/style.css` (very basic styling)
```css
body { font-family: sans-serif; margin: 20px; }
label { display: block; margin-bottom: 5px; }
input[type="text"], select { width: 100%; padding: 8px; margin-bottom: 10px; box-sizing: border-box; }
#dropZone.dragover { border-color: #333; background-color: #f0f0f0; }
button { padding: 10px 15px; background-color: #007bff; color: white; border: none; cursor: pointer; }
button:disabled { background-color: #ccc; }
#statusMessage { margin-top: 15px; }
.error { color: red; }
.success { color: green; }
```

**File:** `public/upload.js`

```javascript
const SUPABASE_URL = 'YOUR_SUPABASE_URL';
const SUPABASE_ANON_KEY = 'YOUR_SUPABASE_ANON_KEY';

const supabase = Supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

const uploadForm = document.getElementById('uploadForm');
const documentNameInput = document.getElementById('documentName');
const projectSelect = document.getElementById('projectSelect');
const dropZone = document.getElementById('dropZone');
const fileInput = document.getElementById('fileInput');
const fileNameDisplay = document.getElementById('fileNameDisplay');
const submitButton = document.getElementById('submitButton');
const statusMessage = document.getElementById('statusMessage');

let selectedFile = null;

// --- Populate Projects Dropdown ---
async function loadProjects() {
    const { data, error } = await supabase
        .from('projects')
        .select('id, name') // Assuming 'id' is PK and 'name' is display name
        .order('name', { ascending: true });

    if (error) {
        console.error('Error fetching projects:', error);
        projectSelect.innerHTML = '<option value="">Error loading projects</option>';
        return;
    }

    if (data && data.length > 0) {
        projectSelect.innerHTML = '<option value="">Select a project</option>'; // Clear loading
        data.forEach(project => {
            const option = document.createElement('option');
            option.value = project.id;
            option.textContent = project.name;
            projectSelect.appendChild(option);
        });
    } else {
        projectSelect.innerHTML = '<option value="">No projects found</option>';
    }
}

// --- Drag and Drop Logic ---
dropZone.addEventListener('dragover', (event) => {
    event.preventDefault();
    dropZone.classList.add('dragover');
});

dropZone.addEventListener('dragleave', () => {
    dropZone.classList.remove('dragover');
});

dropZone.addEventListener('drop', (event) => {
    event.preventDefault();
    dropZone.classList.remove('dragover');
    const files = event.dataTransfer.files;
    if (files.length > 0) {
        handleFile(files[0]);
    }
});

dropZone.addEventListener('click', () => {
    fileInput.click();
});

fileInput.addEventListener('change', (event) => {
    const files = event.target.files;
    if (files.length > 0) {
        handleFile(files[0]);
    }
});

function handleFile(file) {
    selectedFile = file;
    fileNameDisplay.textContent = `Selected file: ${file.name}`;
    submitButton.disabled = false;
}

// --- Form Submission ---
uploadForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!selectedFile || !documentNameInput.value || !projectSelect.value) {
        displayStatus('Please fill all fields and select a file.', 'error');
        return;
    }

    submitButton.disabled = true;
    submitButton.textContent = 'Uploading...';
    displayStatus('Uploading file...', 'info');

    try {
        // 1. Upload file to Supabase Storage
        const fileExt = selectedFile.name.split('.').pop();
        const fileNameInStorage = `${Date.now()}-${Math.random().toString(36).substring(2, 15)}.${fileExt}`;
        const filePathInStorage = `uploads/${fileNameInStorage}`; // Or more structured path e.g., `project_id/uploads/`

        const { data: uploadData, error: uploadError } = await supabase.storage
            .from('documents') // Your Supabase storage bucket name
            .upload(filePathInStorage, selectedFile);

        if (uploadError) {
            throw new Error(`Storage Error: ${uploadError.message}`);
        }

        displayStatus('File uploaded. Creating database entry...', 'info');

        // 2. Call Supabase Edge Function to create source_documents entry
        const payload = {
            userDefinedName: documentNameInput.value,
            projectId: parseInt(projectSelect.value), // Ensure it's an integer if your DB expects it
            originalFileName: selectedFile.name, // Actual name of the uploaded file
            storagePath: uploadData.path, // Path returned by Supabase storage
            fileSize: selectedFile.size,
            fileType: selectedFile.type,
        };

        const { data: functionData, error: functionError } = await supabase.functions.invoke('create-document-entry', {
            body: payload
        });

        if (functionError) {
            // Attempt to clean up storage if function fails
            await supabase.storage.from('documents').remove([filePathInStorage]);
            throw new Error(`Function Error: ${functionError.message || JSON.stringify(functionError)}`);
        }

        displayStatus(`Document '${payload.userDefinedName}' submitted successfully! Queue ID: ${functionData?.queueId || 'N/A'}.`, 'success');
        uploadForm.reset();
        fileNameDisplay.textContent = '';
        selectedFile = null;

    } catch (error) {
        console.error('Upload process failed:', error);
        displayStatus(`Error: ${error.message}`, 'error');
    } finally {
        submitButton.disabled = false;
        submitButton.textContent = 'Upload Document';
    }
});

function displayStatus(message, type = 'info') {
    statusMessage.textContent = message;
    statusMessage.className = type; // Use CSS classes for styling
}

// Initialize
loadProjects();

```

### 3. Backend (Supabase Edge Function)

This function will handle the creation of the `source_documents` entry.

**File:** `supabase/functions/create-document-entry/index.ts`

```typescript
// Follow Supabase Edge Functions structure
// (https://supabase.com/docs/guides/functions)
// Ensure you have Deno and Supabase CLI installed and set up.

import { serve } from "https://deno.land/std@0.177.0/http/server.ts";
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2';

// WARNING: Better to use environment variables for service_role key in production
// For local dev, you might need to pass it or handle anon key with appropriate RLS
// For production, the function should run with elevated privileges (service_role).
const SUPABASE_SERVICE_ROLE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;

serve(async (req) => {
  if (req.method === 'OPTIONS') {
    return new Response('ok', { headers: {
      'Access-Control-Allow-Origin': '*', // Adjust for production
      'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
    } });
  }

  try {
    const supabaseAdmin = createClient(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY);
    const payload = await req.json();

    const {
      userDefinedName,
      projectId,
      originalFileName, // Original name of the file uploaded by user
      storagePath,      // Path in Supabase Storage (e.g., "uploads/file.pdf")
      fileSize,
      fileType,
    } = payload;

    if (!userDefinedName || !projectId || !originalFileName || !storagePath) {
      return new Response(JSON.stringify({ error: "Missing required fields" }), {
        status: 400,
        headers: { "Content-Type": "application/json", 'Access-Control-Allow-Origin': '*' },
      });
    }

    // Generate a UUID for the document_uuid field if your table requires it
    // and it's not auto-generated by the DB.
    const documentUuid = crypto.randomUUID();

    // Create entry in source_documents
    const { data: sourceDocData, error: sourceDocError } = await supabaseAdmin
      .from('source_documents')
      .insert({
        user_defined_name: userDefinedName,
        project_id: projectId,
        original_file_name: originalFileName, // Store the actual file name
        s3_key: storagePath, // Assuming s3_key stores the Supabase Storage path
        // document_uuid: documentUuid, // If you have this column
        initial_processing_status: 'pending_intake', // This will trigger queue population
        // uploaded_at: new Date().toISOString(), // Or use DB default
        // detected_file_type: fileType, // If you have this column
        // file_size: fileSize, // If you have this column
        // Add other relevant metadata like who uploaded if auth is integrated
      })
      .select('id') // Select the ID of the newly created source document
      .single();

    if (sourceDocError) {
      console.error("Error inserting into source_documents:", sourceDocError);
      throw sourceDocError;
    }

    // The trigger on `source_documents` should now create the queue entry.
    // Optionally, you could query the queue table here to return the queue_id,
    // but it adds complexity and relies on trigger timing.
    // For now, we assume the trigger works and just confirm source_doc creation.

    return new Response(JSON.stringify({
      message: "Document entry created successfully.",
      sourceDocumentId: sourceDocData.id
      // queueId: could be fetched if needed but complicates things
    }), {
      headers: { "Content-Type": "application/json", 'Access-Control-Allow-Origin': '*' },
      status: 201,
    });

  } catch (error) {
    console.error("Function error:", error);
    return new Response(JSON.stringify({ error: error.message || "An unexpected error occurred." }), {
      status: 500,
      headers: { "Content-Type": "application/json", 'Access-Control-Allow-Origin': '*' },
    });
  }
});

/*
To deploy (after Supabase CLI login and init):
supabase functions deploy create-document-entry --no-verify-jwt
(or use --project-ref if not in linked directory)

Set environment variables in Supabase Dashboard > Project Settings > Functions > create-document-entry
SUPABASE_URL=your_project_url
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key
*/
```

### 4. Supabase Configuration

1.  **Storage Bucket:**
    *   Create a bucket (e.g., `documents`) in Supabase Storage.
    *   **Bucket Policies:**
        *   **SELECT:** Allow authenticated users (or specific roles) to select if they need to download/view files directly through the storage URL (often not needed if your app proxies).
        *   **INSERT:** Allow authenticated users to upload files. This policy should be quite specific if possible, e.g., users can only upload to paths prefixed with their `user_id` or a temporary staging path. The Edge Function will use service_role, bypassing these for its specific action if needed, but client-side upload needs this.
            ```sql
            -- Example: Allow authenticated users to upload into an 'uploads/' folder
            -- Policy for INSERT on storage.objects for bucket 'documents'
            -- (Authenticated users can upload to any path in this example, refine as needed)
            CREATE POLICY "Authenticated users can upload files"
            ON storage.objects FOR INSERT TO authenticated
            WITH CHECK (bucket_id = 'documents');

            -- More restrictive: users can only upload to a folder matching their user_id
            -- CREATE POLICY "User can upload to their own folder"
            -- ON storage.objects FOR INSERT TO authenticated
            -- WITH CHECK ( bucket_id = 'documents' AND (storage.foldername(name))[1] = auth.uid()::text );
            ```
        *   **UPDATE/DELETE:** Typically restricted to service_role or specific admin roles. The Edge Function can handle deletions if needed.

2.  **Row Level Security (RLS) Policies:**
    *   **`projects` table:**
        *   `SELECT`: `auth.role() = 'authenticated'` (or specific user roles if applicable).
    *   **`source_documents` table:**
        *   `INSERT`: Handled by the Edge Function using `service_role`, so client doesn't need direct insert. If you ever allow direct insert from client (not recommended for this flow), policies would be needed.
        *   `SELECT`: Users might need to see documents they uploaded or are part of their project. Example: `(auth.uid() = user_id_column OR project_id IN (SELECT id FROM user_projects WHERE user_id = auth.uid()))`. This depends on your exact auth setup and how users are linked to projects/documents.
    *   **`document_processing_queue` table:**
        *   Likely no direct client access needed. Managed by backend processors.

3.  **Edge Function Deployment:**
    *   Deploy `create-document-entry` function.
    *   Set environment variables for `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` in the Supabase dashboard for this function.

### 5. Extensibility for Slack Integration (Conceptual)

**File:** `slack_ingestor/slack_bot.py` (Example using Python and `slack_bolt`)

```python
import os
import logging
import uuid
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
import requests
from supabase import create_client, Client

# --- Configuration ---
logging.basicConfig(level=logging.INFO)
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_APP_TOKEN = os.environ.get("SLACK_APP_TOKEN") # Socket Mode
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") # Use service role for backend
SUPABASE_BUCKET_NAME = "documents"
# Potentially map Slack channels to Project IDs or use a default
DEFAULT_PROJECT_ID = 1 # Example: Your default project ID for Slack uploads

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
app = App(token=SLACK_BOT_TOKEN)

def download_file_from_slack(file_url, token):
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(file_url, headers=headers, stream=True)
    response.raise_for_status()
    return response.content, response.headers.get('content-type', 'application/octet-stream')

@app.event("file_shared") # Or "message" and check for files
def handle_file_shared(body, say, logger):
    event = body.get("event", {})
    file_id = event.get("file_id")
    user_id = event.get("user_id") # Slack user ID

    if not file_id:
        return

    try:
        file_info_response = app.client.files_info(file=file_id)
        if not file_info_response["ok"]:
            logger.error(f"Failed to get file info: {file_info_response['error']}")
            return

        file_data = file_info_response["file"]
        original_file_name = file_data["name"]
        slack_file_url = file_data["url_private_download"] # Requires auth

        logger.info(f"New file '{original_file_name}' shared by {user_id}")

        # 1. Download file content from Slack
        file_content, file_type = download_file_from_slack(slack_file_url, SLACK_BOT_TOKEN)
        logger.info(f"File '{original_file_name}' downloaded from Slack, size: {len(file_content)} bytes")

        # 2. Upload to Supabase Storage
        file_ext = original_file_name.split('.')[-1] if '.' in original_file_name else 'bin'
        storage_file_name = f"slack_uploads/{uuid.uuid4()}.{file_ext}"

        upload_response = supabase.storage.from_(SUPABASE_BUCKET_NAME).upload(
            file=file_content,
            path=storage_file_name,
            file_options={"content-type": file_type}
        )
        # Supabase Python client's upload response doesn't have a 'data' attribute directly in older versions.
        # It throws an exception on failure. If no exception, it's successful.
        # Check newer client versions for response structure. For now, we assume success if no error.
        logger.info(f"File '{original_file_name}' uploaded to Supabase Storage as '{storage_file_name}'")


        # 3. Create source_documents entry
        # Determine project_id (e.g., based on channel, or a default)
        project_id_for_doc = DEFAULT_PROJECT_ID # Placeholder
        document_uuid_val = str(uuid.uuid4())

        source_doc_payload = {
            "user_defined_name": f"From Slack: {original_file_name}", # Or parse from message
            "project_id": project_id_for_doc,
            "original_file_name": original_file_name,
            "s3_key": storage_file_name, # Path in Supabase storage
            # "document_uuid": document_uuid_val, # If you have this column
            "initial_processing_status": 'pending_intake',
            "uploaded_at": datetime.utcnow().isoformat(),
            # "detected_file_type": file_type,
            # "file_size": len(file_content),
            "source_details": {"type": "slack", "user_id": user_id, "channel_id": event.get("channel_id")} # Example of extra metadata
        }
        
        source_doc_insert_resp = supabase.table("source_documents").insert(source_doc_payload).execute()

        if source_doc_insert_resp.data:
            logger.info(f"Source document entry created for '{original_file_name}', ID: {source_doc_insert_resp.data[0]['id']}")
            say(channel=event.get("channel_id"), text=f"Thanks! I've received '{original_file_name}' and added it to the processing queue.")
        else:
            # Clean up storage if DB insert fails
            supabase.storage.from_(SUPABASE_BUCKET_NAME).remove([storage_file_name])
            logger.error(f"Failed to create source_document entry: {source_doc_insert_resp.error}")
            say(channel=event.get("channel_id"), text=f"Sorry, I couldn't process '{original_file_name}' due to an error.")


    except Exception as e:
        logger.error(f"Error processing shared file: {e}", exc_info=True)
        say(channel=event.get("channel_id"), text=f"Oops! Something went wrong while processing your file: {original_file_name}")

if __name__ == "__main__":
    if not all([SLACK_BOT_TOKEN, SLACK_APP_TOKEN, SUPABASE_URL, SUPABASE_KEY]):
        print("Error: Missing required environment variables for Slack bot or Supabase.")
    else:
        handler = SocketModeHandler(app, SLACK_APP_TOKEN)
        print("🤖 Slack Ingestor Bot is running in Socket Mode!")
        handler.start()
```
**Slack Bot Setup:**
1.  Create a Slack App.
2.  Enable "Socket Mode."
3.  Add Scopes: `files:read` (to get file info and download), `chat:write` (to respond).
4.  Install app to your workspace.
5.  Get Bot User OAuth Token (`SLACK_BOT_TOKEN`) and App-Level Token (`SLACK_APP_TOKEN`).
6.  Run this Python script in an environment where it can connect to Slack and Supabase.

### Summary of Scripts:

1.  **SQL Migration(s):** (e.g., `migrations/..._add_project_link_to_source_documents.sql`) - Modifies `source_documents` table. Potentially updates the `create_queue_entry_for_new_document` trigger.
2.  **Frontend HTML:** `public/upload.html` - Structure for the upload form.
3.  **Frontend CSS:** `public/style.css` - Basic styling for the form.
4.  **Frontend JavaScript:** `public/upload.js` - Handles UI interactions, project loading, file selection, and calls to Supabase Storage & Edge Function.
5.  **Supabase Edge Function:** `supabase/functions/create-document-entry/index.ts` - Backend logic to create `source_documents` entry after file upload.
6.  **Slack Ingestor (Future):** `slack_ingestor/slack_bot.py` (or similar) - Listens to Slack, downloads files, uploads to Supabase, creates `source_documents` entry.

This comprehensive setup provides a user-friendly web upload interface that integrates directly into your existing queueing mechanism and lays the groundwork for future Slack integration. Remember to replace placeholders like `YOUR_SUPABASE_URL`, `YOUR_SUPABASE_ANON_KEY`, and bucket names with your actual values.