# Document Intake System: Step-by-Step Implementation Guide

This comprehensive guide provides detailed instructions for implementing the document intake system that integrates with your existing Supabase-backed processing queue. Follow these steps carefully to set up the web-based upload interface, backend processing, and optional Slack integration.

## Prerequisites

Before beginning implementation, ensure you have:

- A Supabase project with existing tables for document processing
- Admin access to your Supabase project for SQL execution and function deployment
- Web hosting solution for the frontend files
- [Supabase CLI](https://supabase.com/docs/guides/cli) installed and configured (for Edge Function deployment)
- For Slack integration: A Slack workspace where you can create applications

## 1. Database Schema Modifications

The first step is to extend your database schema to support the new document intake features.

### 1.1 Access Supabase SQL Editor

1. Log in to your Supabase dashboard
2. Select your project
3. Navigate to the "SQL Editor" section
4. Click "New Query" to create a new SQL script

### 1.2 Execute Database Migration

1. Copy the entire contents of `frontend/migrations/00001_add_project_link_to_source_documents.sql`
2. Paste it into the SQL Editor
3. Review the script to ensure compatibility with your existing schema
4. Click "Run" to execute the migration

### 1.3 Verify Database Changes

1. Navigate to "Table Editor"
2. Open the `source_documents` table
3. Confirm the new columns have been added:
   - `user_defined_name` (TEXT)
   - `project_id` (BIGINT)
   - `project_uuid` (TEXT)
   - `uploaded_at` (TIMESTAMPTZ)
   - `file_size` (BIGINT)
   - `file_type` (TEXT)
   - `s3_key` (TEXT)
4. Navigate to "Database Triggers" section
5. Verify two triggers are present on the `source_documents` table:
   - `trg_create_queue_entry_on_new_source_document`
   - `update_queue_on_document_terminal_state`

## 2. Storage Configuration

Next, configure storage for document uploads.

### 2.1 Create Storage Bucket

1. In Supabase dashboard, navigate to "Storage"
2. Click "Create a new bucket"
3. Enter "documents" as the bucket name
4. Choose whether to make the bucket public or private (recommended: private)
5. Click "Create bucket"

### 2.2 Configure Storage RLS Policies

1. Click on the "documents" bucket
2. Select the "Policies" tab
3. Click "Add Policy" to create an upload policy
4. Choose "INSERT" operation
5. Set policy name: "Authenticated users can upload files"
6. Configure the policy using this SQL:
   ```sql
   (bucket_id = 'documents')
   ```
7. For "Target roles", select "authenticated"
8. Click "Save Policy"

9. Add another policy for viewing uploaded files:
10. Click "Add Policy" again
11. Choose "SELECT" operation
12. Set policy name: "Authenticated users can view uploaded files"
13. Configure the policy using this SQL:
   ```sql
   (bucket_id = 'documents')
   ```
14. For "Target roles", select "authenticated"
15. Click "Save Policy"

## 3. Edge Function Deployment

Now deploy the backend Edge Function to handle document entries.

### 3.1 Install and Configure Supabase CLI

If you haven't already, install the Supabase CLI:
```bash
# Install with npm
npm install -g supabase

# Or with yarn
yarn global add supabase
```

### 3.2 Login and Link Project

```bash
# Login to Supabase
supabase login

# Find your project reference ID in the Supabase dashboard URL
# It looks like: abcdefghijklmnopqrst

# Link to your project
supabase link --project-ref <your-project-ref>
```

### 3.3 Deploy Edge Function

1. Navigate to the directory containing your function:
```bash
cd /Users/josephott/Documents/phase_1_2_3_process_v5/frontend
```

2. Deploy the function:
```bash
supabase functions deploy create-document-entry --no-verify-jwt
```

3. Wait for confirmation of successful deployment

### 3.4 Configure Environment Variables

1. In Supabase dashboard, navigate to "Settings" > "Functions"
2. Select the "create-document-entry" function
3. In the "Environment variables" section, add:
   - Key: `SUPABASE_URL`, Value: `https://<your-project-id>.supabase.co`
   - Key: `SUPABASE_SERVICE_ROLE_KEY`, Value: `your_service_role_key`
4. Click "Save"

## 4. Web UI Deployment

Set up the frontend upload interface.

### 4.1 Configure Frontend Connection

1. Open `/Users/josephott/Documents/phase_1_2_3_process_v5/frontend/public/upload.js`
2. Locate lines 2-3:
```javascript
const SUPABASE_URL = 'YOUR_SUPABASE_URL';
const SUPABASE_ANON_KEY = 'YOUR_SUPABASE_ANON_KEY';
```
3. Replace with your actual Supabase URL and anon key:
```javascript
const SUPABASE_URL = 'https://<your-project-id>.supabase.co';
const SUPABASE_ANON_KEY = 'your_anon_key'; // from API settings in Supabase dashboard
```
4. Save the file

### 4.2 Host Static Files

Option A: Use Supabase Storage for hosting with automated setup script (recommended):

1. Ensure your environment variables are properly set in the root `.env` file:
   ```
   SUPABASE_URL=https://your-project-id.supabase.co
   SUPABASE_ANON_KEY=your-anon-key
   SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
   ```

2. Run the setup script that handles everything automatically:
   ```bash
   cd frontend
   npm install
   npm run generate-env
   npm run setup-web-hosting
   ```

3. This script will:
   - Create or verify a "web" bucket in Supabase Storage
   - Make the bucket public
   - Upload all required files with proper MIME types
   - Set proper content-type headers for each file type
   - Show URLs where you can access your web pages

Option B: Manual setup in Supabase Storage:

1. Create a new "web" bucket in Supabase Storage via the Dashboard
2. Enable public access for this bucket
3. Upload the files from the `public` directory, being careful to set the correct content type for each:
   - `upload.html` → Content-Type: `text/html`
   - `index.html` → Content-Type: `text/html`
   - `style.css` → Content-Type: `text/css`
   - `upload.js` → Content-Type: `application/javascript`
   - `env-config.js` → Content-Type: `application/javascript`
4. For each file, click its name after uploading
5. Then click "Edit" and manually set the Content-Type if it's not correct
6. Click "Get URL" to get the public access URL

Option C: Host on a web server:

1. Upload the contents of the `public` directory to your web hosting provider
2. Configure the server to serve these static files
3. Access the form via `your-domain.com/upload.html`

Option C: Local development server:

1. Navigate to the `frontend/public` directory
2. Start a basic HTTP server:
```bash
# Using Python 3
python -m http.server 8000

# OR using Node.js with npx
npx serve
```
3. Access the form at `http://localhost:8000/upload.html`

## 5. Testing the Implementation

Verify that all components are working correctly.

### 5.1 Test Web Upload

1. Open the upload form in a web browser
2. The project dropdown should populate with available projects
3. Enter a document name
4. Drag and drop a test file (e.g., a small PDF)
5. Click "Upload Document"
6. You should see a success message when the upload completes

### 5.2 Verify Database Entries

1. In Supabase dashboard, navigate to "Table Editor"
2. Check the `source_documents` table:
   - A new record should be present with your document name
   - The `initial_processing_status` should be "pending_intake"
3. Check the `document_processing_queue` table:
   - A corresponding queue entry should be created
   - The `status` should be "pending"

### 5.3 Check Storage

1. Navigate to "Storage" > "documents" bucket
2. Verify your uploaded file is present in the "uploads" folder
3. The filename should have a timestamp prefix and random string

## 6. Slack Integration (Optional)

For the optional Slack integration, follow these additional steps.

### 6.1 Create Slack App

1. Go to [Slack API Dashboard](https://api.slack.com/apps)
2. Click "Create New App"
3. Choose "From scratch"
4. Enter a name (e.g., "Document Ingestor") and select your workspace
5. Click "Create App"

### 6.2 Configure Slack App Permissions

1. In the app configuration, navigate to "OAuth & Permissions"
2. Under "Bot Token Scopes", add the following permissions:
   - `files:read` (to access files)
   - `chat:write` (to send messages)
3. Navigate to "Socket Mode" and enable it
4. Generate an App-Level Token with `connections:write` scope
5. Save the token (it starts with `xapp-`)
6. Go back to "OAuth & Permissions"
7. Click "Install to Workspace" and confirm
8. Copy the Bot User OAuth Token (starts with `xoxb-`)

### 6.3 Configure the Slack Bot

1. Navigate to the `slack_ingestor` directory:
```bash
cd /Users/josephott/Documents/phase_1_2_3_process_v5/frontend/slack_ingestor
```

2. Create a `.env` file from the template:
```bash
cp .env.example .env
```

3. Edit the `.env` file with your credentials:
```
SLACK_BOT_TOKEN=xoxb-your-bot-token-here
SLACK_APP_TOKEN=xapp-your-app-token-here
SUPABASE_URL=https://your-project-id.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key-here
SUPABASE_BUCKET_NAME=documents
DEFAULT_PROJECT_ID=1
```

4. Optionally configure channel-to-project mapping:
```
CHANNEL_PROJECT_MAPPING={"C01234567": "1", "C09876543": "2"}
```

### 6.4 Install Python Dependencies

```bash
pip install -r requirements.txt
```

### 6.5 Run the Slack Bot

```bash
python slack_bot.py
```

You should see confirmation that the bot is running. Test it by uploading a file in a Slack channel where the bot is present.

## 7. Troubleshooting

### 7.1 Database Issues

- **Trigger not working**: Check the Supabase logs for error messages
- **Migration errors**: Verify that column names don't conflict with existing ones
- **Missing queue entries**: Ensure the trigger function exists and is properly associated with the table

### 7.2 Edge Function Issues

- **Deployment failures**: Check Supabase CLI output for error messages
- **Runtime errors**: Review function logs in Supabase dashboard (Settings > Functions > Logs)
- **CORS issues**: Ensure the function properly handles OPTIONS requests and sets Access-Control-Allow-Origin headers

### 7.3 Frontend Issues

- **Projects not loading**: Check browser console for API errors
- **Upload failures**: Verify storage permissions and bucket configuration
- **Missing file in storage**: Ensure the file upload path is correct in both client and Edge Function
- **HTML files display as plain text**: This means content-type headers are incorrect. Manually set Content-Type to "text/html" in the Supabase Storage dashboard, or use the provided setup script: `npm run setup-web-hosting`
- **CSS not applying**: Make sure style.css has Content-Type "text/css" in Supabase Storage

### 7.4 Slack Bot Issues

- **Bot not responding**: Verify tokens and permissions
- **File processing errors**: Check bot logs for API errors
- **Document not appearing in queue**: Ensure the document entry is being created correctly

## 8. Common Customizations

### 8.1 Change Storage Paths

To organize files differently:

1. In `upload.js`, modify the `filePathInStorage` variable:
```javascript
const filePathInStorage = `custom-folder/${project_id}/${fileNameInStorage}`;
```

2. Update the same path pattern in the Edge Function (`index.ts`)

### 8.2 Add Custom Metadata

To add additional metadata to document entries:

1. Add UI fields in `upload.html`
2. Include the values in the payload in `upload.js`
3. Update the Edge Function to process and store these values
4. Consider adding new columns to the `source_documents` table if needed

### 8.3 Advanced Project Filtering

To filter projects by specific criteria:

1. Modify the project query in `upload.js`:
```javascript
.from('projects')
.select('id, name')
.eq('status', 'active') // Example: only show active projects
.order('name', { ascending: true });
```

## 9. Security Considerations

### 9.1 Storage Security

- Consider restricting file types by validating file extensions
- Implement file size limits to prevent abuse
- Use dedicated storage paths for each project or user

### 9.2 Authentication

- Ensure RLS policies are properly configured for all resources
- Consider adding user-specific constraints to limit access
- Never expose service role keys in client-side code

### 9.3 Rate Limiting

- Consider implementing rate limiting for the upload endpoint
- Monitor for suspicious activity, such as rapid uploads

## 10. Maintenance and Monitoring

### 10.1 Regular Checks

- Periodically review Supabase logs for errors
- Monitor storage usage and database size
- Check for stalled or failed document processing

### 10.2 Upgrades

- Keep Supabase CLI and client libraries updated
- Review and test with new Supabase feature releases
- Plan for scaling if document volume increases

## Conclusion

By following this guide, you've implemented a robust document intake system that seamlessly integrates with your existing document processing queue. The system provides a user-friendly web interface for document uploads and optionally integrates with Slack for automated file processing.

For further assistance or to report issues, refer to the documentation or contact the development team.

---

## Appendix: File Locations

All files for this implementation are located in the `/Users/josephott/Documents/phase_1_2_3_process_v5/frontend/` directory:

- **Web UI**: `public/upload.html`, `public/style.css`, `public/upload.js`
- **Edge Function**: `supabase/functions/create-document-entry/index.ts`
- **Database Migration**: `migrations/00001_add_project_link_to_source_documents.sql`
- **Slack Integration**: `slack_ingestor/slack_bot.py`, `slack_ingestor/requirements.txt`, `slack_ingestor/.env.example`
- **Documentation**: `README.md`