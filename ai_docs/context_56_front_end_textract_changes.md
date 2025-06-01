Okay, the main principle here is that the **frontend should not be responsible for generating the final S3 path if it depends on a backend-generated UUID.** The backend (specifically your Supabase Edge Function `create-document-entry`) will now handle the generation of the `document_uuid`, the construction of the S3 path (`documents/{document_uuid}.{ext}`), and the actual file upload to that specific path.

The frontend will send the raw file data and the necessary metadata (user-defined name, original filename) to the Edge Function.

Here are the suggested changes:

**1. `upload.js` Modifications:**

The most significant changes will be in how the file is handled and sent to the backend.

```javascript
// Get environment variables from window.ENV
const SUPABASE_URL = window.ENV?.SUPABASE_URL || 'https://yalswdiexcuanszujjhl.supabase.co';
const SUPABASE_ANON_KEY = window.ENV?.SUPABASE_ANON_KEY || 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InlhbHN3ZGlleGN1YW5zenVqamhsIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDc1NDI4MDQsImV4cCI6MjA2MzExODgwNH0.pCYoSFf2Z-8a_p9u0ralFm-qgTUF55lG7-faBxJt4ss';

// Initialize Supabase client
const supabase = Supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

// DOM Elements
const uploadForm = document.getElementById('uploadForm');
const documentNameInput = document.getElementById('documentName'); // User-defined name
const projectSelect = document.getElementById('projectSelect');
const dropZone = document.getElementById('dropZone');
const fileInput = document.getElementById('fileInput');
const fileNameDisplay = document.getElementById('fileNameDisplay');
const submitButton = document.getElementById('submitButton');
const statusMessage = document.getElementById('statusMessage');

// State
let selectedFile = null; // This will hold the original File object

// ------- Helper Functions -------

/**
 * Displays a status message with the appropriate styling
 * @param {string} message - The message to display
 * @param {string} type - The type of message (info, success, error)
 */
function displayStatus(message, type = 'info') {
    statusMessage.textContent = message;
    statusMessage.className = 'status-message ' + type;
    
    statusMessage.scrollIntoView({ behavior: 'smooth' });
}

/**
 * Validates the form input fields
 * @returns {boolean} - Whether the form inputs are valid
 */
function validateForm() {
    if (!documentNameInput.value.trim()) {
        displayStatus('Please enter a document name.', 'error');
        return false;
    }

    if (!projectSelect.value) {
        displayStatus('Please select a project.', 'error');
        return false;
    }

    if (!selectedFile) {
        displayStatus('Please select a file to upload.', 'error');
        return false;
    }

    return true;
}

/**
 * Resets the form to its initial state
 */
function resetForm() {
    uploadForm.reset();
    fileNameDisplay.textContent = '';
    selectedFile = null;
    submitButton.disabled = true;
    statusMessage.textContent = '';
    statusMessage.className = 'status-message';
}

/**
 * Handles the selected file, updates UI
 * @param {File} file - The selected file
 */
function handleFile(file) {
    if (file.size > 50 * 1024 * 1024) { // 50MB limit
        displayStatus('File is too large. Maximum file size is 50MB.', 'error');
        selectedFile = null; // Clear invalid file
        fileNameDisplay.textContent = '';
        submitButton.disabled = true;
        return;
    }

    selectedFile = file; // Store the original File object
    fileNameDisplay.textContent = `Selected file: ${file.name}`; // Display original file name
    submitButton.disabled = false;
    displayStatus(`File "${file.name}" selected. Ready to upload.`, 'info');
}

// ------- API Interactions -------

/**
 * Loads available projects from Supabase
 */
async function loadProjects() {
    try {
        displayStatus('Loading projects...', 'info');
        const { data: projects, error } = await supabase
            .from('projects')
            .select('id, name, projectId') // projectId is the UUID, id is the SQL primary key
            .order('name', { ascending: true });

        if (error) {
            throw new Error(error.message);
        }

        if (projects && projects.length > 0) {
            projectSelect.innerHTML = '<option value="">Select a project</option>';
            projects.forEach(project => {
                const option = document.createElement('option');
                option.value = project.id; // Use SQL PK for foreign key reference
                option.textContent = project.name || project.projectId;
                projectSelect.appendChild(option);
            });
            displayStatus('', ''); 
        } else {
            projectSelect.innerHTML = '<option value="">No projects found</option>';
            displayStatus('No projects available. Please create a project first.', 'error');
        }
    } catch (error) {
        console.error('Error loading projects:', error);
        projectSelect.innerHTML = '<option value="">Error loading projects</option>';
        displayStatus(`Failed to load projects: ${error.message}`, 'error');
    }
}

// REMOVE The old uploadFileToStorage function, as the Edge Function will handle the upload logic
/*
async function uploadFileToStorage(file) { ... }
*/

/**
 * Invokes the Edge Function to create a document entry and handle file upload.
 * The Edge Function will generate the document_uuid and upload the file to documents/{document_uuid}.{ext}
 * @param {FormData} formData - The form data containing file and metadata
 * @returns {Promise<Object>} - The response from the Edge Function
 */
async function processDocumentUpload(formData) {
    displayStatus('Processing document upload via Edge Function...', 'info');
    const { data, error } = await supabase.functions.invoke('create-document-entry', {
        body: formData // Send FormData directly
    });

    if (error) {
        throw new Error(`Edge Function error: ${error.message || JSON.stringify(error)}`);
    }
    if (data && data.error) { // Handle application-level errors returned by the function
        throw new Error(`Edge Function processing error: ${data.error}`);
    }


    return data;
}

// ------- Event Listeners -------

// Form submission
uploadForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    
    if (!validateForm()) {
        return;
    }

    submitButton.disabled = true;
    submitButton.textContent = 'Uploading...';
    displayStatus('Preparing upload...', 'info');

    try {
        // 1. Prepare FormData to send to the Edge Function
        // The Edge Function will handle:
        //    - Generating document_uuid
        //    - Constructing the S3 path: documents/{document_uuid}.{ext}
        //    - Uploading the file to this path
        //    - Creating the entry in `source_documents` table
        const formData = new FormData();
        formData.append('userDefinedName', documentNameInput.value.trim());
        formData.append('projectId', parseInt(projectSelect.value)); // SQL PK of the project
        formData.append('originalFileName', selectedFile.name); // Original name of the uploaded file
        formData.append('fileType', selectedFile.type);
        formData.append('fileSize', selectedFile.size);
        formData.append('documentFile', selectedFile); // The actual file blob

        // 2. Call the Edge Function
        const responseData = await processDocumentUpload(formData);
        
        // 3. Show success message
        // The responseData from the Edge function might include the new document_uuid or user-defined name for confirmation
        let successDocName = responseData?.userDefinedName || documentNameInput.value;
        if (responseData?.documentUuid) {
             displayStatus(`Document "${successDocName}" (ID: ${responseData.documentUuid}) uploaded and queued for processing.`, 'success');
        } else {
             displayStatus(`Document "${successDocName}" uploaded and queued for processing.`, 'success');
        }
        
        // 4. Reset form
        resetForm();
        
    } catch (error) {
        console.error('Upload process failed:', error);
        displayStatus(`Error: ${error.message}`, 'error');
    } finally {
        // Ensure button is re-enabled even if it was disabled due to file size validation earlier
        if (selectedFile) {
            submitButton.disabled = false;
        } else {
            submitButton.disabled = true; // Keep disabled if no file is selected after an error/reset
        }
        submitButton.textContent = 'Upload Document';
    }
});

// Drag and drop events (no changes needed here)
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
    
    if (event.dataTransfer.files.length > 0) {
        handleFile(event.dataTransfer.files[0]);
    }
});

// Click to select file (no changes needed here)
dropZone.addEventListener('click', () => {
    fileInput.click();
});

// File input change (no changes needed here)
fileInput.addEventListener('change', (event) => {
    if (event.target.files.length > 0) {
        handleFile(event.target.files[0]);
    }
});

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    loadProjects();
    submitButton.disabled = true; // Initially disable until a file is selected
});
```

**2. Supabase Edge Function (`create-document-entry` - Conceptual Changes):**

You will need to modify your `create-document-entry` Edge Function significantly. Here's a conceptual outline of what it needs to do:

```typescript
// supabase/functions/create-document-entry/index.ts (Illustrative)
import { serve } from 'https://deno.land/std@0.177.0/http/server.ts';
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2';
import { v4 as uuidv4 } from 'https://esm.sh/uuid@9.0.1'; // For generating UUIDs

serve(async (req) => {
  const supabaseAdmin = createClient(
    Deno.env.get('SUPABASE_URL')!,
    Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')! // Use service role for admin actions
  );

  try {
    const formData = await req.formData();
    const userDefinedName = formData.get('userDefinedName') as string;
    const projectId = parseInt(formData.get('projectId') as string); // SQL PK of project
    const originalFileName = formData.get('originalFileName') as string;
    const fileType = formData.get('fileType') as string;
    const fileSize = parseInt(formData.get('fileSize') as string);
    const documentFile = formData.get('documentFile') as File;

    if (!documentFile || !userDefinedName || !projectId || !originalFileName) {
      return new Response(JSON.stringify({ error: 'Missing required fields.' }), {
        status: 400,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    // 1. Generate document_uuid
    const documentUuid = uuidv4();
    const fileExt = originalFileName.split('.').pop()?.toLowerCase() || 'bin';
    const s3Key = `documents/${documentUuid}.${fileExt}`; // Path based on refactor plan

    // 2. Upload file to Supabase Storage with the new S3 key
    const { data: uploadData, error: uploadError } = await supabaseAdmin.storage
      .from('documents') // Your private bucket, e.g., S3_PRIMARY_DOCUMENT_BUCKET
      .upload(s3Key, documentFile, {
        contentType: documentFile.type || fileType || 'application/octet-stream',
        cacheControl: '3600',
        // upsert: false, // Optional: depending on whether you want to allow overwrites
      });

    if (uploadError) {
      console.error('Storage upload error:', uploadError);
      return new Response(JSON.stringify({ error: `Storage upload failed: ${uploadError.message}` }), {
        status: 500,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    // 3. Create entry in source_documents table
    const { data: docEntry, error: docEntryError } = await supabaseAdmin
      .from('source_documents')
      .insert({
        document_uuid: documentUuid,
        project_id: projectId, // Foreign key to projects table (SQL PK)
        user_defined_name: userDefinedName, // User's custom name for the document
        original_file_name: originalFileName, // Actual name of the file uploaded
        s3_bucket: 'documents', // Or your S3_PRIMARY_DOCUMENT_BUCKET name
        s3_key: s3Key,
        s3_region: Deno.env.get('AWS_DEFAULT_REGION') || 'us-east-1', // Get from env
        file_size_bytes: fileSize,
        detected_file_type: `.${fileExt}`, // Or more robust detection
        mime_type: documentFile.type || fileType,
        initial_processing_status: 'pending_ocr', // Or 'queued' if directly adding to queue
        // any other necessary default fields
      })
      .select()
      .single();

    if (docEntryError) {
      console.error('Source document insert error:', docEntryError);
      // Potentially delete the uploaded S3 object if DB insert fails to avoid orphans
      await supabaseAdmin.storage.from('documents').remove([s3Key]);
      return new Response(JSON.stringify({ error: `Database insert failed: ${docEntryError.message}` }), {
        status: 500,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    // 4. (Optional but Recommended) Add to document_processing_queue
    const { error: queueError } = await supabaseAdmin
      .from('document_processing_queue')
      .insert({
        source_document_id: docEntry.id, // SQL PK from source_documents
        source_document_uuid: documentUuid,
        status: 'pending',
        priority: 1, // Or your default priority
        // ocr_provider can be set here or later by the queue processor
      });

    if (queueError) {
        console.warn('Failed to add to processing queue:', queueError.message);
        // Decide if this is a critical failure or just a warning
    }

    return new Response(JSON.stringify({
        message: 'Document processed successfully.',
        documentUuid: documentUuid,
        sourceDocumentId: docEntry.id,
        userDefinedName: userDefinedName,
        s3Path: s3Key
    }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });

  } catch (e) {
    console.error('Unhandled error in Edge Function:', e);
    return new Response(JSON.stringify({ error: e.message || 'Internal server error.' }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' },
    });
  }
});
```

**Key Changes & Rationale:**

*   **`upload.js`:**
    *   No longer creates the S3 storage path.
    *   Sends `userDefinedName` (from the input field) and `originalFileName` (from the `File` object) along with the file itself as `FormData` to the Edge Function.
    *   The `uploadFileToStorage` function is removed as this responsibility shifts to the backend.
    *   Calls a new/modified `processDocumentUpload` which invokes the Edge Function.
*   **Edge Function (`create-document-entry` - Conceptual):**
    *   Receives `FormData`.
    *   **Generates the `document_uuid` (e.g., using a UUID library).** This is crucial.
    *   **Constructs the `s3_key` as `documents/{document_uuid}.${fileExt}`.** This aligns with the refactor plan.
    *   Uploads the file to Supabase Storage using this exact `s3_key`.
    *   Inserts a new record into `source_documents` storing:
        *   `document_uuid` (the generated UUID).
        *   `user_defined_name` (from frontend input).
        *   `original_file_name` (from the uploaded file's actual name).
        *   `s3_key` (the `documents/{document_uuid}.${fileExt}` path).
        *   `s3_bucket` (your primary private bucket name, matching `S3_PRIMARY_DOCUMENT_BUCKET` in backend config).
    *   Optionally adds an entry to `document_processing_queue`.
*   **Database (`source_documents` table):** Ensure you have columns:
    *   `document_uuid` (TEXT or UUID, UNIQUE, indexed)
    *   `user_defined_name` (TEXT)
    *   `original_file_name` (TEXT)
    *   `s3_key` (TEXT)
    *   `s3_bucket` (TEXT)
    *   ... and other fields as per your schema.

This approach centralizes the naming and storage logic on the backend, making the frontend simpler and the overall system more robust and aligned with your refactoring goals. Remember to deploy the updated Edge Function.