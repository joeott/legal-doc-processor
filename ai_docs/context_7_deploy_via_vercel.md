# Deploying the Document Intake Frontend to Vercel

This guide provides step-by-step instructions for deploying the document intake frontend to Vercel. Vercel is a cloud platform for static sites and serverless functions that enables developers to host websites and web services that deploy instantly and scale automatically.

## Prerequisites

- A [Vercel account](https://vercel.com/signup) (free tier is sufficient)
- The Vercel CLI installed (optional for command-line deployment)
- Your Supabase project URL and anonymous API key

## Quick Start (Simplified Approach)

For the fastest and most reliable deployment:

1. Ensure your Supabase credentials are hardcoded in `env-config.js`
2. Use a minimal `vercel.json` configuration file 
3. Deploy using the Vercel CLI

This simplified approach is recommended after encountering issues with more complex configurations.

## Deployment Options

You can deploy to Vercel in two ways:

1. **Web Interface**: Upload files through the Vercel dashboard
2. **Command Line**: Use the Vercel CLI to deploy from your terminal

## Lessons Learned

Before proceeding to deployment options, here are the key lessons learned from our deployment experience:

1. **Simple Works Best**: Vercel works best with minimalist configuration. Complex `vercel.json` configurations can lead to deployment failures.

2. **Content Type Handling**: Let Vercel handle content types automatically rather than specifying complex header rules.

3. **Environment Variables**: For simplicity and reliability, hardcoding environment variables in `env-config.js` can be more straightforward than relying on Vercel's environment variable system, especially for static sites.

4. **Avoiding Mixed Routing Properties**: Using both `routes` and other routing properties like `cleanUrls` and `rewrites` simultaneously causes conflicts in Vercel.

5. **Error Diagnosis**: When deployment fails, incrementally simplify your configuration until deployment succeeds, then add complexity back carefully.

## Option 1: Web Interface Deployment

### Step 1: Prepare Your Files

The `/Users/josephott/Documents/phase_1_2_3_process_v5/frontend/vercel-deploy` directory contains all the files needed for deployment. This directory includes:

- `public/`: Directory containing all static assets
  - `index.html`: Main page with redirect to upload.html
  - `upload.html`: The document upload form
  - `style.css`: Styling for the application
  - `upload.js`: JavaScript for handling the upload functionality
  - `env-config.js`: Will be generated during build with your environment variables
- `vercel.json`: Configuration file for Vercel
- `package.json`: Project metadata and build scripts
- `generate-env-config.js`: Script to generate environment config during build

### Step 2: Create a New Project in Vercel

1. Log in to your [Vercel dashboard](https://vercel.com/dashboard)
2. Click "Add New" > "Project"
3. Choose "Upload" from the deployment options
4. Compress the contents of the `vercel-deploy` directory into a ZIP file
5. Drag and drop the ZIP file or click to browse and select it
6. Click "Deploy"

### Step 3: Configure Environment Variables

After deployment starts, you'll need to configure environment variables:

1. Navigate to your project in the Vercel dashboard
2. Click on "Settings" > "Environment Variables"
3. Add the following variables:
   - Name: `SUPABASE_URL`, Value: `https://your-project-id.supabase.co`
   - Name: `SUPABASE_ANON_KEY`, Value: `your-anon-key`
4. Click "Save"
5. Go to "Deployments" and click "Redeploy" to deploy with the new environment variables

## Option 2: Command Line Deployment

### Step 1: Install Vercel CLI

If you haven't already installed the Vercel CLI, do so with npm:

```bash
npm install -g vercel
```

### Step 2: Log in to Vercel

```bash
vercel login
```

Follow the instructions to authenticate your account.

### Step 3: Navigate to the Deploy Directory

```bash
cd /Users/josephott/Documents/phase_1_2_3_process_v5/frontend/vercel-deploy
```

### Step 4: Deploy to Vercel

```bash
vercel --prod
```

During deployment, the CLI will ask if you want to:
- Set up project settings
- Link to an existing project or create a new one
- Set up environment variables

For environment variables, provide:
- `SUPABASE_URL`: Your Supabase project URL
- `SUPABASE_ANON_KEY`: Your Supabase anonymous API key

## Verifying Deployment

After successful deployment, Vercel will provide a URL where your site is hosted (e.g., `https://your-project.vercel.app`).

1. Open this URL in your browser
2. You should be redirected to the upload page
3. The form should be functional and able to connect to your Supabase backend

## Troubleshooting

### Complex Configuration Issues

If deployment fails with complex `vercel.json` configurations:

1. Simplify your `vercel.json` to the minimal configuration:
   ```json
   {
     "version": 2
   }
   ```

2. Hardcode Supabase credentials in `env-config.js` directly:
   ```javascript
   // Hardcoded environment variables for simplicity
   window.ENV = {
     SUPABASE_URL: "https://your-project-id.supabase.co",
     SUPABASE_ANON_KEY: "your-anon-key"
   };
   ```

3. Redeploy with the simplified configuration

### Environment Variables Not Loading

If your application cannot connect to Supabase:

1. Check the browser console for errors
2. Verify that environment variables are set correctly in the Vercel dashboard
3. Redeploy the application after updating environment variables

### CORS Issues

If you see CORS errors in the browser console:

1. Go to your Supabase project dashboard
2. Navigate to "Settings" > "API"
3. Under "CORS", add your Vercel deployment URL to the allowed origins
4. Include both `https://your-project.vercel.app` and `https://www.your-project.vercel.app`

### Content Type Issues

If HTML files display as plain text:

1. Remove complex headers configuration from vercel.json
2. Let Vercel's built-in server handle content types automatically
3. Redeploy with the simplified configuration

### Edge Function Access

For the form to connect to your Supabase Edge Functions:

1. Ensure your Edge Function has the appropriate CORS headers:
   ```js
   // In your Edge Function
   if (req.method === 'OPTIONS') {
     return new Response('ok', {
       headers: {
         'Access-Control-Allow-Origin': '*',
         'Access-Control-Allow-Methods': 'POST, OPTIONS',
         'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
       }
     });
   }
   ```

2. Add headers to all Edge Function responses:
   ```js
   return new Response(JSON.stringify(data), {
     headers: {
       'Content-Type': 'application/json',
       'Access-Control-Allow-Origin': '*',
     }
   });
   ```

## Updating Your Deployment

To update your Vercel deployment after making changes:

### Web Interface

1. Create a new ZIP file with your updated files
2. Go to your project in the Vercel dashboard
3. Click "Deployments" > "Deploy" > "Upload"
4. Upload the new ZIP file

### Command Line

1. Make your changes to the files in the `vercel-deploy` directory
2. Run:
   ```bash
   vercel --prod
   ```

## Monitoring and Logs

Vercel provides built-in analytics and logging:

1. Visit your project in the Vercel dashboard
2. Click "Analytics" to view usage metrics
3. Click "Logs" to see request logs and errors

## Custom Domain (Optional)

To use a custom domain for your frontend:

1. Go to your project in the Vercel dashboard
2. Click "Settings" > "Domains"
3. Click "Add" and enter your domain
4. Follow the instructions to configure DNS settings for your domain

## Verification and Testing

After successful deployment, you need to verify that the document upload system works end-to-end:

### 1. Verify Frontend Rendering

1. Access your Vercel deployment URL (e.g., `https://your-project.vercel.app`)
2. Confirm that the HTML renders correctly (not as plain text)
3. Verify all styles are applied (proper CSS loading)
4. Check the browser console for any JavaScript errors

### 2. Test Project Loading

1. When the upload page loads, the project dropdown should populate automatically
2. This confirms that your Supabase connection is working
3. If projects don't load, check browser console for API errors
4. Verify CORS settings in Supabase if needed

### 3. Document Upload Testing

1. Select a small test document (PDF, Word, etc.)
2. Enter a document name in the form
3. Select a project from the dropdown
4. Submit the form
5. Monitor the status messages during the upload process
6. Verify that a success message appears after upload completes

### 4. Backend Processing Verification

1. After a successful upload, log into your Supabase dashboard
2. Navigate to "Table Editor" > "source_documents"
3. Verify that a new record has been created with:
   - The document name you specified
   - The correct project_id
   - initial_processing_status set to "pending_intake"

4. Check the "document_processing_queue" table to ensure:
   - A queue entry was created by the trigger
   - The status shows as "pending" or is being processed

5. Monitor the processing through logs and table updates to ensure the queue processor is working

### 5. Check Storage Bucket

1. In Supabase dashboard, go to "Storage" > "documents" bucket
2. Verify the file was uploaded to the "uploads" folder
3. Check that the file has the expected name pattern (timestamp-randomstring.extension)

## Troubleshooting Successful Uploads

If documents upload but don't process correctly:

1. **Queue Trigger Issues**: Check that the database trigger is properly configured and active
2. **Processing Errors**: Check logs for the queue processor
3. **Storage Access**: Ensure the queue processor has proper access to the storage bucket
4. **Format Support**: Verify that the document format is supported by your processing pipeline

## Conclusion

Your document intake frontend is now deployed on Vercel! Users can access the upload form through your Vercel URL and upload documents that will be processed by your Supabase backend.

With Vercel handling your frontend deployment, you benefit from:
- Global CDN for fast loading times
- Automatic HTTPS for security
- Built-in CI/CD for future updates
- Scaling to handle any number of users

The simplified deployment approach addresses common issues with content-type handling and environment variables, providing a reliable and maintainable solution.

For additional configuration options and advanced features, refer to the [Vercel documentation](https://vercel.com/docs).