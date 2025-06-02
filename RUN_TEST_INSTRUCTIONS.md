# Instructions to Run the Region Fix Test

## Prerequisites
1. Ensure you're in the project directory:
   ```bash
   cd /opt/legal-doc-processor
   ```

2. Source the environment variables:
   ```bash
   source load_env.sh
   ```

3. Set the required environment variables:
   ```bash
   export S3_BUCKET_REGION=us-east-2
   export PYTHONPATH=/opt/legal-doc-processor:$PYTHONPATH
   ```

## Running the Test

Execute the test script:
```bash
python3 scripts/test_region_fix_complete.py
```

## Expected Output

The test will show progress through 8 stages:

1. **Creating document record** - Generates a new UUID for the test document
2. **Uploading to S3** - Uploads the test PDF to S3 bucket with correct region
3. **Creating database record** - Creates document entry in PostgreSQL
4. **Verifying document in database** - Confirms document exists in DB
5. **Storing metadata in Redis** - Caches document metadata
6. **Submitting OCR task** - Submits Celery task for OCR processing
7. **Monitoring task progress** - Tracks Celery task status
8. **Final status check** - Reports overall pipeline status

## Current Known Issue

The test will likely fail at step 7 with:
```
❌ Task failed!
Error: Document [UUID] not found in database
```

This is the known Celery database visibility issue we're working to resolve. The document IS created successfully (steps 3-4 pass), but Celery workers can't see it due to database connection isolation.

## Test File Location

The test uses this PDF file:
```
/opt/legal-doc-processor/input_docs/Paul, Michael (Acuity)/Paul, Michael - Wombat Corp Disclosure Stmt 10-23-24.pdf
```

## Troubleshooting

If you see errors about missing environment variables:
1. Check that `.env` file exists and contains all required keys
2. Re-run `source load_env.sh`
3. Verify with: `echo $DATABASE_URL` (should show the PostgreSQL connection string)

If you see import errors:
1. Ensure PYTHONPATH is set correctly
2. Check that all dependencies are installed: `pip install -r requirements.txt`

## What Success Looks Like

When the issue is resolved, you should see:
- All 8 stages showing ✓ checkmarks
- Task status progressing through: pending → processing → completed
- Chunks created: > 0
- No "Document not found" errors