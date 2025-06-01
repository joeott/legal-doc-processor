# Context 39: End-to-End Stage 1 Deployment Test Plan

## Overview
This document outlines a comprehensive end-to-end test plan for Stage 1 deployment, tracking a document from upload through the Vercel frontend to complete processing via cloud services.

## Test Environment Setup

### 1. Environment Configuration
```bash
# Stage 1 Configuration
export DEPLOYMENT_STAGE=1
export OPENAI_API_KEY="your-openai-key"
export MISTRAL_API_KEY="your-mistral-key"

# Database Configuration
export SUPABASE_URL="your-supabase-url"
export SUPABASE_KEY="your-supabase-anon-key"

# Optional: Frontend Configuration
export NEXT_PUBLIC_SUPABASE_URL="your-supabase-url"
export NEXT_PUBLIC_SUPABASE_ANON_KEY="your-supabase-anon-key"
```

### 2. Pre-deployment Validation
```bash
# Verify Stage 1 configuration
python -c "from scripts.config import get_stage_info; print(get_stage_info())"

# Validate Stage 1 requirements
python -c "from scripts.main_pipeline import validate_stage1_requirements; validate_stage1_requirements()"

# Check database connectivity
python -c "from scripts.supabase_utils import SupabaseManager; db = SupabaseManager(); print('Database connected')"
```

## End-to-End Test Flow

### Phase 1: Frontend Upload via Vercel

#### 1.1 Deploy Frontend to Vercel

**Prerequisites:**
- Node.js v20.17.0 or higher (npm v11+ requires Node v20+)
- Vercel CLI installed globally

```bash
# Install Vercel CLI if not already installed
npm install -g vercel

# IMPORTANT: Navigate to the correct frontend directory first!
cd /Users/josephott/Documents/phase_1_2_3_process_v5/frontend/vercel-deploy

# Verify you're in the correct directory (should show package.json, public/, etc.)
ls -la

# Install dependencies
npm install

# Deploy to Vercel (make sure you're still in vercel-deploy directory)
vercel --prod

# Alternative: Use npm script after Vercel CLI is installed
npm run deploy
```

**Common Issues:**
- If Vercel tries to deploy your home directory, you're not in the correct folder
- Always use the full path to ensure you're in the right location
- The deployment should only include the frontend files (public/, package.json, etc.)

**Note**: The frontend uses a build script to generate `env-config.js` from environment variables. This runs automatically during Vercel deployment.

#### 1.2 Test Document Upload
1. Navigate to deployed Vercel URL
2. Select test document: `/Users/josephott/Documents/phase_1_2_3_process_v5/input/Verified+Petition+for+Discovery+of+Assets (1).PDF`
3. Click "Upload Document"
4. Verify upload success message

#### 1.3 Verify Database Entry
```sql
-- Check source_documents table
SELECT * FROM source_documents 
WHERE file_name LIKE '%Verified%Petition%' 
ORDER BY created_at DESC LIMIT 1;

-- Check document_queue entry
SELECT * FROM document_queue 
WHERE source_document_id = (
    SELECT id FROM source_documents 
    WHERE file_name LIKE '%Verified%Petition%' 
    ORDER BY created_at DESC LIMIT 1
);
```

### Phase 2: Queue Processing Initiation

#### 2.1 Start Queue Processor
```bash
# Start queue processor in Stage 1 mode
python scripts/main_pipeline.py --mode queue
```

#### 2.2 Monitor Queue Status
```bash
# In another terminal, start live monitor
python monitoring/live_monitor.py
```

### Phase 3: Document Processing Pipeline

#### 3.1 OCR Extraction (Mistral)
- **Expected**: Document picked up from queue
- **Service**: Mistral OCR API
- **Verification**:
  ```sql
  -- Check extracted text
  SELECT extracted_text, extraction_status 
  FROM source_documents 
  WHERE id = [document_id];
  ```

#### 3.2 Document Node Creation
- **Expected**: Neo4j document entry created
- **Verification**:
  ```sql
  SELECT * FROM neo4j_documents 
  WHERE source_document_id = [document_id];
  ```

#### 3.3 Semantic Chunking
- **Expected**: Document split into semantic chunks
- **Verification**:
  ```sql
  SELECT COUNT(*), MIN(chunk_index), MAX(chunk_index) 
  FROM neo4j_chunks 
  WHERE document_uuid = [neo4j_document_uuid];
  ```

#### 3.4 Entity Extraction (OpenAI)
- **Expected**: Entities extracted via OpenAI GPT-4
- **Service**: OpenAI API
- **Verification**:
  ```sql
  SELECT entity_value, entity_type, COUNT(*) 
  FROM neo4j_entity_mentions 
  WHERE document_uuid = [neo4j_document_uuid]
  GROUP BY entity_value, entity_type;
  ```

#### 3.5 Entity Resolution
- **Expected**: Duplicate entities consolidated
- **Verification**:
  ```sql
  SELECT canonical_name, entity_type, mention_count_in_doc 
  FROM neo4j_canonical_entities 
  WHERE document_uuid = [neo4j_document_uuid];
  ```

#### 3.6 Relationship Staging
- **Expected**: Graph relationships created
- **Verification**:
  ```sql
  SELECT relationship_type, COUNT(*) 
  FROM neo4j_relationship_staging 
  WHERE source_entity_uuid IN (
      SELECT uuid FROM neo4j_canonical_entities 
      WHERE document_uuid = [neo4j_document_uuid]
  )
  GROUP BY relationship_type;
  ```

### Phase 4: Audio File Testing (Optional)

#### 4.1 Upload Audio File
1. Use frontend to upload test audio file
2. Verify OpenAI Whisper transcription

#### 4.2 Verify Whisper Processing
```sql
-- Check audio transcription
SELECT file_name, extracted_text, extraction_metadata 
FROM source_documents 
WHERE file_name LIKE '%.wav' OR file_name LIKE '%.mp3'
ORDER BY created_at DESC LIMIT 1;
```

## Expected Results Summary

### Database State After Processing
```sql
-- Summary query
WITH doc AS (
    SELECT id, uuid, file_name, extracted_text IS NOT NULL as has_text
    FROM source_documents 
    WHERE file_name LIKE '%Verified%Petition%' 
    ORDER BY created_at DESC LIMIT 1
),
neo4j AS (
    SELECT COUNT(*) as neo4j_docs
    FROM neo4j_documents 
    WHERE source_document_id = (SELECT id FROM doc)
),
chunks AS (
    SELECT COUNT(*) as chunk_count
    FROM neo4j_chunks 
    WHERE document_uuid = (
        SELECT uuid FROM neo4j_documents 
        WHERE source_document_id = (SELECT id FROM doc)
    )
),
entities AS (
    SELECT COUNT(DISTINCT entity_value) as unique_entities,
           COUNT(*) as total_mentions
    FROM neo4j_entity_mentions 
    WHERE document_uuid = (
        SELECT uuid FROM neo4j_documents 
        WHERE source_document_id = (SELECT id FROM doc)
    )
),
canonical AS (
    SELECT COUNT(*) as canonical_count
    FROM neo4j_canonical_entities 
    WHERE document_uuid = (
        SELECT uuid FROM neo4j_documents 
        WHERE source_document_id = (SELECT id FROM doc)
    )
)
SELECT 
    doc.file_name,
    doc.has_text,
    neo4j.neo4j_docs,
    chunks.chunk_count,
    entities.unique_entities,
    entities.total_mentions,
    canonical.canonical_count
FROM doc, neo4j, chunks, entities, canonical;
```

### Expected Metrics
- **OCR Success**: Text extracted via Mistral
- **Chunks Created**: 5-15 semantic chunks (depends on document)
- **Entities Found**: 10-50 unique entities
- **Entity Types**: PERSON, ORGANIZATION, LOCATION, DATE, MONEY
- **Relationships**: MENTIONED_IN, NEXT_CHUNK, PREVIOUS_CHUNK

## Monitoring & Debugging

### 1. Real-time Monitoring
```bash
# Terminal 1: Queue processor with verbose logging
DEPLOYMENT_STAGE=1 python scripts/main_pipeline.py --mode queue

# Terminal 2: Live monitor
python monitoring/live_monitor.py

# Terminal 3: Watch logs
tail -f logs/document_processing.log
```

### 2. Common Issues & Solutions

#### Issue: Queue not processing
```bash
# Check queue status
python -c "from scripts.supabase_utils import SupabaseManager; db = SupabaseManager(); print(db.get_queue_status())"

# Reset stuck documents
UPDATE document_queue 
SET status = 'pending', retry_count = 0 
WHERE status = 'processing' AND updated_at < NOW() - INTERVAL '1 hour';
```

#### Issue: Mistral OCR fails
```bash
# Check Mistral API key
curl -X POST https://api.mistral.ai/v1/chat/completions \
  -H "Authorization: Bearer $MISTRAL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model": "pixtral-12b-2409", "messages": [{"role": "user", "content": "test"}]}'
```

#### Issue: OpenAI entity extraction fails
```bash
# Test OpenAI API
python -c "from openai import OpenAI; client = OpenAI(); print(client.models.list())"
```

### 3. Performance Metrics
```sql
-- Processing time analysis
SELECT 
    status,
    COUNT(*) as count,
    AVG(EXTRACT(EPOCH FROM (updated_at - created_at))) as avg_seconds,
    MAX(EXTRACT(EPOCH FROM (updated_at - created_at))) as max_seconds
FROM document_queue
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY status;
```

## Stage 1 Validation Checklist

### Pre-deployment
- [ ] Environment variables set correctly
- [ ] API keys validated (OpenAI, Mistral)
- [ ] Database connectivity confirmed
- [ ] Frontend deployed to Vercel
- [ ] Queue processor ready

### During Processing
- [ ] Document uploads successfully
- [ ] Queue entry created
- [ ] OCR extraction completes (Mistral)
- [ ] Chunks created
- [ ] Entities extracted (OpenAI)
- [ ] Entities resolved
- [ ] Relationships staged

### Post-processing
- [ ] All database tables populated
- [ ] No errors in logs
- [ ] Processing time reasonable (<5 min per document)
- [ ] Entity extraction quality good
- [ ] Relationships properly linked

## Success Criteria

1. **Upload Success**: Document uploaded via Vercel frontend appears in database
2. **Queue Processing**: Document automatically picked up and processed
3. **Cloud Services**: All processing uses cloud APIs (no local models)
4. **Data Completeness**: All pipeline phases complete successfully
5. **Error Handling**: Any errors are logged and document marked appropriately

## Test Document Characteristics

### Recommended Test Document
- **File**: `Verified+Petition+for+Discovery+of+Assets (1).PDF`
- **Type**: Legal document
- **Expected Entities**: 
  - Persons (petitioner, respondent, attorneys)
  - Organizations (courts, law firms)
  - Dates (filing dates, hearing dates)
  - Monetary amounts
  - Locations (addresses, jurisdictions)

### Alternative Test Files
1. **Simple Text**: Upload a .txt file to test basic flow
2. **Audio File**: Upload a .wav file to test Whisper integration
3. **Complex PDF**: Multi-page legal contract with tables

## Rollback Plan

If issues arise during testing:

1. **Stop queue processor**: Ctrl+C in terminal
2. **Reset queue**:
   ```sql
   UPDATE document_queue 
   SET status = 'pending', retry_count = 0 
   WHERE status IN ('processing', 'failed');
   ```
3. **Clear test data** (if needed):
   ```sql
   -- Use with caution!
   DELETE FROM neo4j_relationship_staging WHERE created_at > '2024-01-01';
   DELETE FROM neo4j_canonical_entities WHERE created_at > '2024-01-01';
   DELETE FROM neo4j_entity_mentions WHERE created_at > '2024-01-01';
   DELETE FROM neo4j_chunks WHERE created_at > '2024-01-01';
   DELETE FROM neo4j_documents WHERE created_at > '2024-01-01';
   DELETE FROM document_queue WHERE created_at > '2024-01-01';
   DELETE FROM source_documents WHERE created_at > '2024-01-01';
   ```

## Conclusion

This end-to-end test plan provides a comprehensive validation of Stage 1 deployment, ensuring all components work together seamlessly with cloud services. The test flow mimics real-world usage, from document upload through complete processing, providing confidence in the system's readiness for production deployment.