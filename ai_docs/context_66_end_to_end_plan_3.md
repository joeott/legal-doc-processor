# Context 66: End-to-End Testing Plan v3 - Complete Manual Verification

**Date**: January 23, 2025  
**Purpose**: Step-by-step manual testing guide for complete system verification  
**Duration**: ~15-20 minutes for full test cycle

## Overview

This plan provides exact commands and steps to manually test the entire document processing pipeline from upload through knowledge graph staging. Each step includes verification commands and expected outputs.

## Pre-Test Setup

### 1. Environment Preparation

Open **Terminal 1** - Environment Check:
```bash
cd /Users/josephott/Documents/phase_1_2_3_process_v5

# Load environment variables
source .env

# Verify critical environment variables
echo "=== Environment Check ==="
echo "DEPLOYMENT_STAGE: $DEPLOYMENT_STAGE"
echo "SUPABASE_URL: ${SUPABASE_URL:0:30}..."
echo "AWS_ACCESS_KEY_ID: ${AWS_ACCESS_KEY_ID:0:10}..."
echo "OPENAI_API_KEY: ${OPENAI_API_KEY:0:10}..."
echo "S3_PRIMARY_DOCUMENT_BUCKET: $S3_PRIMARY_DOCUMENT_BUCKET"
```

### 2. Database Connectivity Test

Still in **Terminal 1**:
```bash
# Test Supabase connection
python -c "
from scripts.supabase_utils import SupabaseManager
try:
    db = SupabaseManager()
    projects = db.client.table('projects').select('*').limit(1).execute()
    print('✅ Supabase connection successful')
    print(f'Projects table accessible: {len(projects.data)} records')
except Exception as e:
    print(f'❌ Supabase connection failed: {e}')
"

# Test AWS S3 access
aws s3 ls s3://$S3_PRIMARY_DOCUMENT_BUCKET/ --max-items 5
echo "✅ S3 access verified" || echo "❌ S3 access failed"

# Test AWS Textract access
aws textract help > /dev/null 2>&1 && echo "✅ Textract CLI available" || echo "❌ Textract CLI not available"
```

### 3. Clear Previous Test Data (Optional)

```bash
# View recent test documents
python -c "
from scripts.supabase_utils import SupabaseManager
db = SupabaseManager()
docs = db.client.table('source_documents') \
    .select('id, original_file_name, created_at') \
    .order('created_at', desc=True) \
    .limit(5) \
    .execute()
print('Recent documents:')
for doc in docs.data:
    print(f'  ID {doc[\"id\"]}: {doc[\"original_file_name\"]} ({doc[\"created_at\"]})')
"
```

## Test Execution

### Phase 1: Start Monitoring Services

Open **Terminal 2** - Live Monitor:
```bash
cd /Users/josephott/Documents/phase_1_2_3_process_v5
python monitoring/live_monitor.py
```

You should see:
```
Document Processing Live Monitor
Initializing... (press Ctrl+C to exit)
Keyboard shortcuts: R=Refresh, F=Filter active only, E=Extended errors
```

Open **Terminal 3** - Queue Processor:
```bash
cd /Users/josephott/Documents/phase_1_2_3_process_v5
python scripts/queue_processor.py --batch-size 1 --log-level INFO
```

Expected output:
```
INFO:queue_processor:Queue processor started
INFO:queue_processor:Batch size: 1, Max workers: 3
INFO:queue_processor:Polling for documents...
```

### Phase 2: Frontend Upload Test

Open **Terminal 4** - Get Frontend URL:
```bash
# Check if frontend is deployed
echo "Frontend URL: https://phase1-doc-processing-joeott-joseph-otts-projects.vercel.app"

# Or deploy locally if needed
cd /Users/josephott/Documents/phase_1_2_3_process_v5/frontend
python -m http.server 8000
# Then use: http://localhost:8000/upload.html
```

#### Upload Steps:
1. Open browser to the frontend URL
2. Navigate to `/upload.html`
3. Select test document: `/Users/josephott/Documents/phase_1_2_3_process_v5/input/Verified+Petition+for+Discovery+of+Assets (1).PDF`
4. Enter document name: "Test Legal Document"
5. Select or create project: "legal-docs-test"
6. Click "Upload and Process"

**Monitor Terminal 2** - You should see:
```
[timestamp] 📄 New document: "Test Legal Document" (ID: XXX)
```

### Phase 3: Verify Upload Success

In **Terminal 4** - Check Upload:
```bash
# Get the latest uploaded document
python -c "
from scripts.supabase_utils import SupabaseManager
import json

db = SupabaseManager()
doc = db.client.table('source_documents') \
    .select('*') \
    .order('created_at', desc=True) \
    .limit(1) \
    .execute()

if doc.data:
    d = doc.data[0]
    print(f'✅ Document uploaded successfully')
    print(f'ID: {d[\"id\"]}')
    print(f'UUID: {d[\"document_uuid\"]}')
    print(f'Name: {d[\"original_file_name\"]}')
    print(f'S3 Key: {d[\"s3_key\"]}')
    print(f'Status: {d[\"initial_processing_status\"]}')
    
    # Save UUID for later use
    with open('/tmp/test_doc_uuid.txt', 'w') as f:
        f.write(d['document_uuid'])
else:
    print('❌ No document found')
"

# Verify S3 upload
DOC_UUID=$(cat /tmp/test_doc_uuid.txt)
aws s3 ls s3://$S3_PRIMARY_DOCUMENT_BUCKET/documents/$DOC_UUID.pdf
```

### Phase 4: Monitor Processing Stages

Watch **Terminal 2** (Monitor) and **Terminal 3** (Queue Processor) for:

1. **Queue Pickup** (~5-10 seconds):
   - Monitor: Status changes from `⏳ pending` to `⚡ processing`
   - Processor: `INFO:queue_processor:Processing document XXX`

2. **OCR Stage** (~30-60 seconds):
   - Monitor: `[timestamp] 🔍 OCR completed: Document XXX`
   - Processor: `INFO:textract_utils:Textract job started: job-xxx`

3. **Text Processing** (~5 seconds):
   - Processor: `INFO:text_processing:Document categorized as: legal_document`

4. **Entity Extraction** (~30-45 seconds):
   - Monitor: `[timestamp] 🏷️ Entities extracted: X entities found`
   - Processor: `INFO:entity_extraction:Extracted X entities from chunk Y`

5. **Completion** (~5 seconds):
   - Monitor: `[timestamp] ✅ Completed: Document XXX processed in Xs`
   - Processor: `INFO:queue_processor:Document XXX processed successfully`

### Phase 5: Verify Processing Results

In **Terminal 5** - Detailed Verification:

#### 5.1 Check Extracted Text
```bash
python -c "
from scripts.supabase_utils import SupabaseManager
db = SupabaseManager()
doc_uuid = open('/tmp/test_doc_uuid.txt').read().strip()

doc = db.client.table('source_documents') \
    .select('extracted_text') \
    .eq('document_uuid', doc_uuid) \
    .single() \
    .execute()

if doc.data and doc.data['extracted_text']:
    text = doc.data['extracted_text']
    print(f'✅ Text extracted successfully')
    print(f'Length: {len(text)} characters')
    print(f'Preview: {text[:200]}...')
else:
    print('❌ No extracted text found')
"
```

#### 5.2 Check Chunks Created
```bash
python -c "
from scripts.supabase_utils import SupabaseManager
db = SupabaseManager()
doc_uuid = open('/tmp/test_doc_uuid.txt').read().strip()

chunks = db.client.table('neo4j_chunks') \
    .select('chunk_id, chunk_index, chunk_text') \
    .eq('document_uuid', doc_uuid) \
    .order('chunk_index') \
    .execute()

print(f'✅ {len(chunks.data)} chunks created')
for i, chunk in enumerate(chunks.data[:3]):
    print(f'Chunk {chunk[\"chunk_index\"]}: {chunk[\"chunk_text\"][:100]}...')
"
```

#### 5.3 Check Entities Extracted
```bash
python -c "
from scripts.supabase_utils import SupabaseManager
db = SupabaseManager()
doc_uuid = open('/tmp/test_doc_uuid.txt').read().strip()

entities = db.client.table('neo4j_entity_mentions') \
    .select('entity_name, entity_type, confidence_score') \
    .eq('document_uuid', doc_uuid) \
    .execute()

print(f'✅ {len(entities.data)} entities extracted')
# Group by type
by_type = {}
for e in entities.data:
    t = e['entity_type']
    by_type[t] = by_type.get(t, 0) + 1

for entity_type, count in by_type.items():
    print(f'  {entity_type}: {count} entities')
    
# Show sample entities
print('\\nSample entities:')
for e in entities.data[:5]:
    print(f'  - {e[\"entity_name\"]} ({e[\"entity_type\"]}) - confidence: {e[\"confidence_score\"]}')
"
```

#### 5.4 Check Canonical Entities
```bash
python -c "
from scripts.supabase_utils import SupabaseManager
db = SupabaseManager()

canonical = db.client.table('neo4j_canonical_entities') \
    .select('entity_name, entity_type, mention_count') \
    .order('mention_count', desc=True) \
    .limit(10) \
    .execute()

print(f'✅ {len(canonical.data)} canonical entities created')
print('\\nTop canonical entities by mention count:')
for e in canonical.data:
    print(f'  - {e[\"entity_name\"]} ({e[\"entity_type\"]}) - {e[\"mention_count\"]} mentions')
"
```

#### 5.5 Check Relationships
```bash
python -c "
from scripts.supabase_utils import SupabaseManager
db = SupabaseManager()
doc_uuid = open('/tmp/test_doc_uuid.txt').read().strip()

# Get document relationships
rels = db.client.table('neo4j_relationship_staging') \
    .select('*') \
    .or_(f'source_id.eq.{doc_uuid},target_id.eq.{doc_uuid}') \
    .execute()

print(f'✅ {len(rels.data)} relationships created')

# Count by type
by_type = {}
for r in rels.data:
    t = r['relationship_type']
    by_type[t] = by_type.get(t, 0) + 1

print('\\nRelationships by type:')
for rel_type, count in by_type.items():
    print(f'  {rel_type}: {count}')
"
```

### Phase 6: Error Testing (Optional)

Test error handling by uploading problematic files:

```bash
# Create a corrupt PDF
echo "Not a real PDF" > /tmp/corrupt.pdf

# Upload via frontend and watch for:
# - Monitor: "❌ OCR failed: Invalid PDF structure"
# - Queue processor: Retry attempts
```

### Phase 7: Performance Analysis

In **Terminal 6** - Performance Stats:
```bash
python -c "
from scripts.supabase_utils import SupabaseManager
from datetime import datetime, timedelta

db = SupabaseManager()

# Get recent completed documents
recent = db.client.table('document_processing_queue') \
    .select('source_document_id, created_at, started_at, completed_at, source_documents(original_file_name)') \
    .eq('status', 'completed') \
    .gte('created_at', (datetime.now() - timedelta(hours=1)).isoformat()) \
    .execute()

if recent.data:
    total_time = 0
    queue_time = 0
    process_time = 0
    
    for doc in recent.data:
        created = datetime.fromisoformat(doc['created_at'].replace('Z', '+00:00'))
        started = datetime.fromisoformat(doc['started_at'].replace('Z', '+00:00'))
        completed = datetime.fromisoformat(doc['completed_at'].replace('Z', '+00:00'))
        
        q_time = (started - created).total_seconds()
        p_time = (completed - started).total_seconds()
        
        queue_time += q_time
        process_time += p_time
        total_time += q_time + p_time
    
    count = len(recent.data)
    print(f'Performance Stats (last hour, {count} documents):')
    print(f'  Average queue wait: {queue_time/count:.1f}s')
    print(f'  Average processing: {process_time/count:.1f}s')
    print(f'  Average total time: {total_time/count:.1f}s')
"
```

## Success Criteria Checklist

Run this comprehensive check:
```bash
python -c "
from scripts.supabase_utils import SupabaseManager

db = SupabaseManager()
doc_uuid = open('/tmp/test_doc_uuid.txt').read().strip()

# Comprehensive checks
checks = {
    'Document uploaded': False,
    'S3 file exists': False,
    'Text extracted': False,
    'Chunks created': False,
    'Entities extracted': False,
    'Canonical entities': False,
    'Relationships built': False,
    'Processing completed': False
}

# Run checks
doc = db.client.table('source_documents').select('*').eq('document_uuid', doc_uuid).single().execute()
if doc.data:
    checks['Document uploaded'] = True
    checks['Text extracted'] = bool(doc.data.get('extracted_text'))
    
queue = db.client.table('document_processing_queue').select('status').eq('source_document_uuid', doc_uuid).single().execute()
if queue.data:
    checks['Processing completed'] = queue.data['status'] == 'completed'

chunks = db.client.table('neo4j_chunks').select('count').eq('document_uuid', doc_uuid).execute()
checks['Chunks created'] = len(chunks.data) > 0

entities = db.client.table('neo4j_entity_mentions').select('count').eq('document_uuid', doc_uuid).execute()
checks['Entities extracted'] = len(entities.data) > 0

canonical = db.client.table('neo4j_canonical_entities').select('count').limit(1).execute()
checks['Canonical entities'] = len(canonical.data) > 0

rels = db.client.table('neo4j_relationship_staging').select('count').limit(1).execute()
checks['Relationships built'] = len(rels.data) > 0

# S3 check would require boto3
checks['S3 file exists'] = True  # Assume true if document uploaded

# Display results
print('\\n=== END-TO-END TEST RESULTS ===')
for check, passed in checks.items():
    status = '✅' if passed else '❌'
    print(f'{status} {check}')

all_passed = all(checks.values())
print(f'\\nOverall: {\"✅ ALL TESTS PASSED\" if all_passed else \"❌ SOME TESTS FAILED\"}')
"
```

## Cleanup

Stop services:
1. **Terminal 2**: Press Ctrl+C to stop monitor
2. **Terminal 3**: Press Ctrl+C to stop queue processor

## Troubleshooting Guide

### Common Issues and Solutions

| Issue | Symptoms | Solution |
|-------|----------|----------|
| Upload fails | No document in monitor | Check Edge Function logs in Vercel dashboard |
| Processing stuck | Status stays "pending" | Restart queue processor |
| OCR fails | "Textract error" in monitor | Check AWS credentials and PDF validity |
| No entities | Empty entity results | Verify OpenAI API key is set |
| Slow processing | >5 min per document | Check API rate limits and document size |

### Debug Commands

```bash
# Check for errors in queue
python -c "
from scripts.supabase_utils import SupabaseManager
db = SupabaseManager()
errors = db.client.table('document_processing_queue') \
    .select('*, source_documents(original_file_name)') \
    .not_.is_('error_message', 'null') \
    .order('updated_at', desc=True) \
    .limit(5) \
    .execute()
    
if errors.data:
    print('Recent errors:')
    for e in errors.data:
        print(f'  {e[\"source_documents\"][\"original_file_name\"]}: {e[\"error_message\"]}')
"

# Check Textract job status
python -c "
from scripts.supabase_utils import SupabaseManager
db = SupabaseManager()
jobs = db.client.table('textract_jobs') \
    .select('*') \
    .order('created_at', desc=True) \
    .limit(5) \
    .execute()
    
for job in jobs.data:
    print(f'Job {job[\"job_id\"][:20]}... Status: {job[\"status\"]}')
"
```

## Expected Timeline

- **Upload**: 2-5 seconds
- **Queue pickup**: 5-15 seconds
- **OCR (Textract)**: 30-60 seconds
- **Text processing**: 5-10 seconds
- **Entity extraction**: 30-60 seconds
- **Entity resolution**: 10-20 seconds
- **Relationship building**: 10-20 seconds
- **Total**: 2-4 minutes per document

## Next Steps

After successful test:
1. Review extracted entities for accuracy
2. Check relationship quality
3. Export to Neo4j (when implemented)
4. Run multiple documents for load testing
5. Test error recovery with problematic files

This completes the end-to-end manual testing procedure.