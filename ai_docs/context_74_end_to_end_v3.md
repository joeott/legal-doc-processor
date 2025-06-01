# Context 78: End-to-End Pipeline Testing Guide v3

## Overview

This document provides a comprehensive step-by-step guide for manually testing the entire document processing pipeline from frontend deployment through knowledge graph construction. This guide incorporates all recent changes including the unified document UUID schema.

## Prerequisites

1. **Environment Setup**
   ```bash
   # Verify all environment variables are set
   python verify_env.py
   
   # Ensure virtual environment is activated
   source venv/bin/activate  # or your virtual environment
   ```

2. **Database State**
   - Ensure migration 00006_add_documentid_constraints.sql has been applied
   - Verify clean database state or note existing documents

## Phase 1: Frontend Deployment

### Step 1.1: Build and Deploy Frontend

```bash
# Navigate to frontend directory
cd frontend

# Install dependencies if needed
npm install

# Generate environment configuration
npm run generate:env

# Deploy to Vercel (stays in frontend directory)
npm run deploy
# OR directly:
# vercel --prod

# Note the deployment URL
# Example: https://your-project.vercel.app
```

### Step 1.2: Verify Deployment

1. Open deployment URL in browser
2. Check browser console for errors
3. Verify environment variables loaded:
   - Open DevTools Console
   - Type: `window.SUPABASE_URL` (should show your Supabase URL)
   - Type: `window.SUPABASE_ANON_KEY` (should show your anon key)

## Phase 2: Document Upload

### Step 2.1: Prepare Test Document

```bash
# Use existing test document or create new one
ls input_docs/
# Should see: Pre-Trial Order - Ory v. Roeslein.pdf
```

### Step 2.2: Upload via Frontend

1. Navigate to your deployment URL
2. Click "Choose File" button
3. Select test PDF document
4. Enter project name: "test-e2e-pipeline"
5. Click "Upload and Process"
6. Note the displayed document UUID

### Step 2.3: Verify Upload

```bash
# Check source_documents table
python -c "
from scripts.supabase_utils import SupabaseManager
db = SupabaseManager()
docs = db.client.table('source_documents').select('*').order('created_at', desc=True).limit(1).execute()
print('Latest document:', docs.data[0] if docs.data else 'No documents')
"

# Check document_queue entry
python -c "
from scripts.supabase_utils import SupabaseManager
db = SupabaseManager()
queue = db.client.table('document_queue').select('*').order('created_at', desc=True).limit(1).execute()
print('Latest queue entry:', queue.data[0] if queue.data else 'No queue entries')
"
```

## Phase 3: Queue Processing

### Step 3.1: Start Queue Processor

```bash
# In a new terminal, start the queue processor
python scripts/queue_processor.py

# You should see:
# Starting queue processor...
# Checking for documents to process...
```

### Step 3.2: Monitor Processing

```bash
# In another terminal, start the live monitor
python monitoring/live_monitor.py

# Monitor shows real-time status updates
```

### Step 3.3: Verify OCR Extraction

```bash
# Check if OCR completed
python -c "
from scripts.supabase_utils import SupabaseManager
db = SupabaseManager()
docs = db.client.table('source_documents').select('extracted_text').order('created_at', desc=True).limit(1).execute()
text = docs.data[0]['extracted_text'] if docs.data else None
print('Text extracted:', 'Yes' if text else 'No')
print('First 200 chars:', text[:200] if text else 'No text')
"
```

## Phase 4: Entity Processing

### Step 4.1: Verify Neo4j Document Creation

```bash
# Check neo4j_documents
python -c "
from scripts.supabase_utils import SupabaseManager
db = SupabaseManager()
neo_docs = db.client.table('neo4j_documents').select('*').order('created_at', desc=True).limit(1).execute()
if neo_docs.data:
    doc = neo_docs.data[0]
    print(f'Neo4j document created: {doc[\"documentId\"]}')
    print(f'Title: {doc[\"title\"]}')
    print(f'UUID matches source: {doc[\"documentId\"] == doc.get(\"source_document_uuid\", doc[\"documentId\"])}')
"
```

### Step 4.2: Verify Chunking

```bash
# Check chunks created
python -c "
from scripts.supabase_utils import SupabaseManager
db = SupabaseManager()
chunks = db.client.table('neo4j_chunks').select('chunk_id, chunk_index, text').order('created_at', desc=True).limit(5).execute()
print(f'Chunks created: {len(chunks.data)}')
for chunk in chunks.data:
    print(f'  Chunk {chunk[\"chunk_index\"]}: {chunk[\"text\"][:50]}...')
"
```

### Step 4.3: Verify Entity Extraction

```bash
# Check entity mentions
python -c "
from scripts.supabase_utils import SupabaseManager
db = SupabaseManager()
entities = db.client.table('neo4j_entity_mentions').select('*').order('created_at', desc=True).limit(10).execute()
print(f'Entity mentions found: {len(entities.data)}')
for ent in entities.data[:5]:
    print(f'  {ent[\"entity_type\"]}: {ent[\"text\"]}')
"
```

### Step 4.4: Verify Entity Resolution

```bash
# Check canonical entities
python -c "
from scripts.supabase_utils import SupabaseManager
db = SupabaseManager()
canonical = db.client.table('neo4j_canonical_entities').select('*').order('created_at', desc=True).limit(10).execute()
print(f'Canonical entities: {len(canonical.data)}')
for ent in canonical.data[:5]:
    print(f'  {ent[\"entity_type\"]}: {ent[\"name\"]} (members: {ent.get(\"member_count\", 0)})')
"
```

## Phase 5: Relationship Building

### Step 5.1: Verify Relationships

```bash
# Check relationship staging
python -c "
from scripts.supabase_utils import SupabaseManager
db = SupabaseManager()
rels = db.client.table('neo4j_relationship_staging').select('*').order('created_at', desc=True).limit(10).execute()
print(f'Relationships staged: {len(rels.data)}')
for rel in rels.data[:5]:
    print(f'  {rel[\"from_entity_type\"]} -> {rel[\"to_entity_type\"]}: {rel[\"relationship_type\"][:30]}')
"
```

### Step 5.2: Check Processing Status

```bash
# Verify queue completion
python -c "
from scripts.supabase_utils import SupabaseManager
db = SupabaseManager()
queue = db.client.table('document_queue').select('*').eq('status', 'completed').order('created_at', desc=True).limit(1).execute()
if queue.data:
    q = queue.data[0]
    print(f'Processing completed: {q[\"document_id\"]}')
    print(f'Total time: {q[\"updated_at\"]}')
"
```

## Phase 6: Data Validation

### Step 6.1: Run Conformance Check

```bash
# Verify document UUID conformance
python scripts/verify_documentid_conformance.py
```

### Step 6.2: Check Pipeline Integrity

```bash
# Run comprehensive pipeline verification
python verify_pipeline.py
```

### Step 6.3: Entity Statistics

```bash
# Get processing statistics
python -c "
from scripts.supabase_utils import SupabaseManager
db = SupabaseManager()

# Document count
docs = db.client.table('neo4j_documents').select('count', count='exact').execute()
print(f'Total documents: {docs.count}')

# Chunk count
chunks = db.client.table('neo4j_chunks').select('count', count='exact').execute()
print(f'Total chunks: {chunks.count}')

# Entity mentions
mentions = db.client.table('neo4j_entity_mentions').select('count', count='exact').execute()
print(f'Total entity mentions: {mentions.count}')

# Canonical entities
canonical = db.client.table('neo4j_canonical_entities').select('count', count='exact').execute()
print(f'Total canonical entities: {canonical.count}')

# Relationships
rels = db.client.table('neo4j_relationship_staging').select('count', count='exact').execute()
print(f'Total relationships: {rels.count}')
"
```

## Phase 7: Error Handling Tests

### Step 7.1: Test Retry Logic

```bash
# Upload a problematic document to test retry
# Monitor how the system handles errors
```

### Step 7.2: Test Duplicate Prevention

```bash
# Re-upload the same document
# Verify no duplicate neo4j_documents created
# Check that documentId constraint prevents duplicates
```

## Phase 8: Performance Monitoring

### Step 8.1: Processing Time Analysis

```bash
# Analyze processing times
python monitoring/pipeline_analysis.py
```

### Step 8.2: Check Logs

```bash
# View recent processing logs
./view_logs.sh
```

## Common Issues and Solutions

### Issue 1: OCR Fails
- Check Mistral API key is valid
- Verify API rate limits not exceeded
- Check document is valid PDF

### Issue 2: Entity Extraction Fails
- Verify OpenAI API key is valid
- Check for malformed text chunks
- Review error logs for JSON parsing issues

### Issue 3: Queue Stuck
- Check for documents in 'processing' state > 10 minutes
- Run: `python scripts/recover_stuck_documents.py`

### Issue 4: Duplicate Documents
- Verify documentId constraints are applied
- Check that frontend isn't creating multiple uploads

### Issue 5: Schema Mismatch Errors
- **Error**: "Could not find the 'displayName' column"
- **Cause**: Frontend API using wrong column name
- **Fix**: The projects table uses `name` not `displayName`
- **Schema**: 
  ```sql
  projects table columns:
  - id (integer, primary key)
  - projectId (varchar, unique identifier)
  - name (text, display name)
  - createdAt, updatedAt (timestamps)
  ```

### Issue 6: Source Document UUID Column Error
- **Error**: "column 'source_document_uuid' of relation 'neo4j_documents' does not exist"
- **Cause**: Database functions still referencing removed column after schema migration
- **Fix**: Apply migration 00007_fix_functions_remove_source_document_uuid.sql
- **Impact**: This occurs when database triggers try to create neo4j_documents entries
- **Resolution**: The unified UUID schema uses `documentId` as the single identifier

### Issue 7: Trigger Field Reference Error
- **Error**: "record 'new' has no field 'source_document_uuid'"
- **Cause**: Trigger functions trying to access NEW.source_document_uuid on source_documents table
- **Fix**: Apply migration 00008_fix_triggers_document_uuid_references.sql
- **Impact**: Prevents document upload and queue creation
- **Resolution**: Triggers should use NEW.document_uuid instead of NEW.source_document_uuid

## Success Criteria

✅ **Frontend**: Document uploads successfully, queue entry created
✅ **OCR**: Text extracted and stored in source_documents
✅ **Processing**: neo4j_documents entry created with matching UUID
✅ **Chunking**: Multiple chunks created for document
✅ **Entities**: Entity mentions extracted and resolved
✅ **Relationships**: Relationships staged for Neo4j
✅ **Queue**: Status moves from pending → processing → completed
✅ **Conformance**: All document UUIDs match between tables

## Cleanup

After testing:

```bash
# Optional: Clean test data
python -c "
from scripts.supabase_utils import SupabaseManager
db = SupabaseManager()
# Add cleanup code if needed
"
```

## Next Steps

1. Export to Neo4j for graph visualization
2. Run batch processing tests with multiple documents
3. Test Stage 2/3 deployment modes
4. Performance optimization based on metrics

## Conclusion

This end-to-end test validates the entire document processing pipeline from upload through knowledge graph staging. All components should work together seamlessly with the unified document UUID schema ensuring data consistency throughout the system.