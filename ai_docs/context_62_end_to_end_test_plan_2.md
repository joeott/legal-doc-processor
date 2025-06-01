# Context 62: End-to-End Test Plan v2 (Post-Textract Refactor)

**Date**: January 23, 2025  
**Status**: TEST PLAN  
**Scope**: Complete end-to-end testing of document processing pipeline with Textract integration

## Executive Summary

This test plan provides a comprehensive guide for conducting an end-to-end test of the document processing pipeline following the Textract refactor. Building on lessons learned from context_39 and context_40, this plan includes enhanced monitoring, error handling verification, and specific commands for each stage.

## Prerequisites

### 1. Environment Setup
```bash
# Verify environment variables
echo "DEPLOYMENT_STAGE: $DEPLOYMENT_STAGE"  # Should be "1"
echo "AWS_ACCESS_KEY_ID: ${AWS_ACCESS_KEY_ID:0:10}..."  # Verify AWS creds
echo "OPENAI_API_KEY: ${OPENAI_API_KEY:0:10}..."  # Verify OpenAI key
echo "SUPABASE_URL: $SUPABASE_URL"
echo "S3_PRIMARY_DOCUMENT_BUCKET: $S3_PRIMARY_DOCUMENT_BUCKET"
```

### 2. Verify Database Connectivity
```bash
# Test Supabase connection
python -c "
from scripts.supabase_utils import SupabaseManager
db = SupabaseManager()
print(f'Connected to Supabase: {db.client.table(\"projects\").select(\"*\").limit(1).execute()}')"
```

### 3. Verify AWS Services
```bash
# Test S3 access
aws s3 ls s3://$S3_PRIMARY_DOCUMENT_BUCKET/documents/ --max-items 5

# Test Textract access
aws textract describe-document-text-detection --job-id test 2>&1 | grep -E "(Invalid|Access|Job)"
```

## Phase 1: Frontend Deployment and Setup

### 1.1 Deploy Frontend to Vercel
```bash
# Navigate to Vercel deployment directory
cd frontend/vercel-deploy

# Generate environment configuration
npm run generate-env-config

# Deploy to Vercel
npm run deploy

# Note the deployment URL
echo "Deployment URL: https://your-app.vercel.app"
```

### 1.2 Verify Edge Function Deployment
```bash
# Check Edge Function logs in Vercel dashboard
# Or use Vercel CLI
vercel logs --follow
```

### 1.3 Prepare Test Document
```bash
# Use a simple PDF for testing
ls -la input/Verified+Petition+for+Discovery+of+Assets\ \(1\).PDF
# Or create a simple test PDF
echo "Test Document Content" | enscript -B -o - | ps2pdf - test_document.pdf
```

## Phase 2: Document Upload and Queue Entry

### 2.1 Open Monitoring Terminal
```bash
# Terminal 1: Live Monitor
cd /Users/josephott/Documents/phase_1_2_3_process_v5
python monitoring/live_monitor.py
```

### 2.2 Upload Document via Frontend
1. Open browser to your Vercel deployment URL
2. Navigate to `/upload.html`
3. Select your test PDF
4. Click "Upload and Process"
5. Note the document UUID returned

### 2.3 Verify Upload in Database
```bash
# Terminal 2: Database Verification
python -c "
from scripts.supabase_utils import SupabaseManager
db = SupabaseManager()

# Check latest source document
docs = db.client.table('source_documents') \
    .select('*') \
    .order('created_at', desc=True) \
    .limit(1) \
    .execute()

if docs.data:
    doc = docs.data[0]
    print(f'Document ID: {doc[\"id\"]}')
    print(f'UUID: {doc[\"document_uuid\"]}')
    print(f'S3 Key: {doc[\"s3_key\"]}')
    print(f'Status: {doc[\"initial_processing_status\"]}')
    
    # Check queue entry
    queue = db.client.table('document_processing_queue') \
        .select('*') \
        .eq('source_document_id', doc['id']) \
        .execute()
    
    if queue.data:
        print(f'\\nQueue Entry: {queue.data[0][\"id\"]}')
        print(f'Queue Status: {queue.data[0][\"status\"]}')
"
```

### 2.4 Verify S3 Upload
```bash
# Check S3 for uploaded file
LATEST_UUID=$(python -c "
from scripts.supabase_utils import SupabaseManager
db = SupabaseManager()
doc = db.client.table('source_documents').select('document_uuid').order('created_at', desc=True).limit(1).execute()
print(doc.data[0]['document_uuid'] if doc.data else 'NOT_FOUND')
")

aws s3 ls s3://$S3_PRIMARY_DOCUMENT_BUCKET/documents/$LATEST_UUID.pdf
```

## Phase 3: Queue Processing Initiation

### 3.1 Start Queue Processor
```bash
# Terminal 3: Queue Processor
cd /Users/josephott/Documents/phase_1_2_3_process_v5
python scripts/queue_processor.py --batch-size 1 --single-run --log-level DEBUG
```

### 3.2 Monitor Processing Stages
The queue processor will execute these stages in order:

1. **Queue Claim** (0-5 seconds)
   - Processor claims document from queue
   - Status changes from 'pending' to 'processing'

2. **OCR Extraction** (5-60 seconds)
   - Textract job initiated
   - Monitor for job ID in logs
   - Status: 'extracting_text'

3. **Text Processing** (1-5 seconds)
   - Text cleaning and categorization
   - Status: 'processing_text'

4. **Semantic Chunking** (5-10 seconds)
   - Document split into semantic chunks
   - Status: 'chunking'

5. **Entity Extraction** (10-30 seconds per chunk)
   - OpenAI extracts entities from each chunk
   - Status: 'extracting_entities'

6. **Entity Resolution** (5-15 seconds)
   - Deduplication and canonicalization
   - Status: 'resolving_entities'

7. **Relationship Building** (5-10 seconds)
   - Graph relationships created
   - Status: 'building_relationships'

8. **Completion** (1-2 seconds)
   - Final status updates
   - Status: 'completed'

## Phase 4: Monitoring Commands

### 4.1 Real-Time Textract Job Monitoring
```bash
# Terminal 4: Textract Job Monitor
watch -n 5 'python -c "
from scripts.supabase_utils import SupabaseManager
db = SupabaseManager()
jobs = db.client.table(\"textract_jobs\") \
    .select(\"*\") \
    .order(\"created_at\", desc=True) \
    .limit(5) \
    .execute()
    
for job in jobs.data:
    print(f\"Job ID: {job[\"job_id\"][:20]}... Status: {job[\"status\"]} Created: {job[\"created_at\"]}\")
"'
```

### 4.2 Queue Status Monitoring
```bash
# Check queue status
python -c "
from scripts.supabase_utils import SupabaseManager
db = SupabaseManager()
status = db.get_queue_status()
print(f'Queue Status: {status}')
"
```

### 4.3 Document Processing Progress
```bash
# Monitor document progress
python -c "
from scripts.supabase_utils import SupabaseManager
db = SupabaseManager()

# Get latest document
doc = db.client.table('source_documents') \
    .select('*, neo4j_documents(id), neo4j_chunks(id), neo4j_entity_mentions(id)') \
    .order('created_at', desc=True) \
    .limit(1) \
    .execute()

if doc.data:
    d = doc.data[0]
    print(f'Document: {d[\"filename\"]}')
    print(f'Status: {d[\"initial_processing_status\"]}')
    print(f'Neo4j Documents: {len(d.get(\"neo4j_documents\", []))}')
    print(f'Chunks: {len(d.get(\"neo4j_chunks\", []))}')
    print(f'Entities: {len(d.get(\"neo4j_entity_mentions\", []))}')
"
```

## Phase 5: Verification and Troubleshooting

### 5.1 Check for Errors
```bash
# Check for processing errors
python -c "
from scripts.supabase_utils import SupabaseManager
db = SupabaseManager()

# Check failed queue items
failed = db.client.table('document_processing_queue') \
    .select('*, source_documents(filename)') \
    .eq('status', 'failed') \
    .order('updated_at', desc=True) \
    .limit(5) \
    .execute()

if failed.data:
    print('Failed Documents:')
    for f in failed.data:
        print(f'  - {f[\"source_documents\"][\"filename\"]}: {f.get(\"error_message\", \"Unknown error\")}')
"
```

### 5.2 Textract-Specific Debugging
```bash
# Check Textract job details
python -c "
from scripts.supabase_utils import SupabaseManager
import boto3

db = SupabaseManager()
textract = boto3.client('textract')

# Get latest Textract job
job = db.client.table('textract_jobs') \
    .select('*') \
    .order('created_at', desc=True) \
    .limit(1) \
    .execute()

if job.data:
    job_id = job.data[0]['job_id']
    print(f'Checking Textract job: {job_id}')
    
    try:
        response = textract.get_document_text_detection(JobId=job_id)
        print(f'AWS Status: {response[\"JobStatus\"]}')
        print(f'Pages: {response.get(\"DocumentMetadata\", {}).get(\"Pages\", 0)}')
    except Exception as e:
        print(f'Error: {e}')
"
```

### 5.3 View Extracted Text
```bash
# View extracted text from latest document
python -c "
from scripts.supabase_utils import SupabaseManager
db = SupabaseManager()

doc = db.client.table('source_documents') \
    .select('extracted_text') \
    .order('created_at', desc=True) \
    .limit(1) \
    .execute()

if doc.data and doc.data[0]['extracted_text']:
    text = doc.data[0]['extracted_text']
    print(f'Extracted Text (first 500 chars):')
    print(text[:500])
    print(f'\\nTotal length: {len(text)} characters')
"
```

## Phase 6: Success Criteria

### 6.1 Expected Timeline
- **Upload to Queue Entry**: < 5 seconds
- **Queue Processing Start**: < 30 seconds (depending on batch interval)
- **OCR Extraction**: 10-60 seconds (depending on document size)
- **Full Pipeline Completion**: 2-5 minutes for typical document

### 6.2 Success Indicators
1. ✅ Document appears in `source_documents` with UUID
2. ✅ Queue entry created automatically via trigger
3. ✅ S3 file exists at `documents/{uuid}.pdf`
4. ✅ Textract job initiated and completed
5. ✅ Text extracted and stored
6. ✅ Chunks created in `neo4j_chunks`
7. ✅ Entities extracted in `neo4j_entity_mentions`
8. ✅ Canonical entities in `neo4j_canonical_entities`
9. ✅ Relationships in `neo4j_relationship_staging`
10. ✅ Final status is 'completed'

### 6.3 Common Issues and Solutions

| Issue | Symptom | Solution |
|-------|---------|----------|
| Upload fails | No document in DB | Check Edge Function logs |
| Queue stuck | Status remains 'pending' | Verify queue processor running |
| Textract timeout | Job status 'IN_PROGRESS' > 10 min | Check AWS permissions |
| Empty extraction | extracted_text is null | Verify PDF is valid |
| Entity extraction fails | No entities found | Check OpenAI API key |
| S3 access denied | Upload/download errors | Verify AWS credentials |

## Phase 7: Cleanup

### 7.1 Stop Services
```bash
# Stop queue processor (Ctrl+C in Terminal 3)
# Stop live monitor (Ctrl+C in Terminal 1)
```

### 7.2 Optional: Clean Test Data
```bash
# Remove test documents (careful!)
python -c "
from scripts.supabase_utils import SupabaseManager
db = SupabaseManager()

# Get test document IDs
test_docs = db.client.table('source_documents') \
    .select('id') \
    .like('filename', '%test%') \
    .execute()

if test_docs.data:
    print(f'Found {len(test_docs.data)} test documents')
    # Uncomment to delete:
    # for doc in test_docs.data:
    #     db.client.table('source_documents').delete().eq('id', doc['id']).execute()
"
```

## Appendix: Quick Reference

### All-in-One Test Command
```bash
# Start everything in tmux/screen sessions
tmux new-session -d -s monitor 'cd /Users/josephott/Documents/phase_1_2_3_process_v5 && python monitoring/live_monitor.py'
tmux new-session -d -s queue 'cd /Users/josephott/Documents/phase_1_2_3_process_v5 && python scripts/queue_processor.py --batch-size 1 --log-level INFO'

# Upload via frontend, then monitor
watch -n 2 'python -c "from scripts.supabase_utils import SupabaseManager; db = SupabaseManager(); print(db.get_queue_status())"'
```

### Key Log Patterns to Watch
```
# Success patterns
"Successfully uploaded document"
"Textract job started: job-"
"Textract job completed successfully"
"Extracted [0-9]+ entities from chunk"
"Document processing completed"

# Error patterns
"Failed to upload"
"Textract job failed"
"Error extracting entities"
"Queue item marked as failed"
```

## Conclusion

This end-to-end test plan provides a systematic approach to validating the entire document processing pipeline with the new Textract integration. By following these steps and monitoring commands, you can verify that documents flow correctly from upload through final knowledge graph staging.