# Context 157: Single PDF Document Processing Checklist

## Overview
This document provides a detailed checklist of every step required for processing a single PDF document through the legal document processing pipeline, including where errors are logged at each stage.

## Prerequisites

### System Requirements
- [ ] Redis server running (local or Redis Cloud)
- [ ] PostgreSQL/Supabase database accessible
- [ ] AWS credentials configured for S3 and Textract
- [ ] OpenAI API key set for GPT-4 entity extraction
- [ ] Python environment with all dependencies installed

### Celery Workers Required
- [ ] **OCR Worker**: `celery -A scripts.celery_app worker -Q ocr -n ocr_worker@%h --concurrency=2`
- [ ] **Text Worker**: `celery -A scripts.celery_app worker -Q text -n text_worker@%h --concurrency=4`
- [ ] **Entity Worker**: `celery -A scripts.celery_app worker -Q entity -n entity_worker@%h --concurrency=100 -P gevent`
- [ ] **Graph Worker**: `celery -A scripts.celery_app worker -Q graph -n graph_worker@%h --concurrency=4`

### Monitoring Tools
- [ ] Flower dashboard: `celery -A scripts.celery_app flower` (http://localhost:5555)
- [ ] Redis monitoring available
- [ ] Database query access

## Processing Pipeline Stages

### Stage 1: Document Intake
**Location**: `scripts/supabase_utils.py::create_source_document_entry()`

#### Checklist:
- [ ] Create or retrieve project record
  - Project UUID generated if not exists
  - Project name set
- [ ] Create source_documents entry
  - [ ] Generate document_uuid
  - [ ] Set project_fk_id and project_uuid
  - [ ] Store original_file_path
  - [ ] Store original_file_name
  - [ ] Set detected_file_type (must include dot, e.g., ".pdf")
  - [ ] Set initial_processing_status = "pending_intake"
  - [ ] Set celery_status = "pending"

#### Error Logging:
- **Database**: `source_documents.error_message`
- **Python Logs**: `logger.error()` in supabase_utils.py
- **Validation Errors**: Pydantic ValidationError if model fields invalid

### Stage 2: Celery Task Submission
**Location**: `scripts/celery_tasks/ocr_tasks.py::process_ocr()`

#### Checklist:
- [ ] Submit task to Celery with correct parameters:
  - document_uuid
  - source_doc_sql_id
  - file_path
  - file_name
  - detected_file_type
  - project_sql_id
- [ ] Update source_documents with celery_task_id
- [ ] Set celery_status = "processing"

#### Error Logging:
- **Celery Logs**: Task submission errors
- **Database**: `source_documents.celery_task_id`
- **Redis**: Task state in result backend

### Stage 3: OCR Processing
**Location**: `scripts/celery_tasks/ocr_tasks.py::process_ocr()` → `scripts/ocr_extraction.py`

#### Checklist:
- [ ] Validate file type is supported
- [ ] Update initial_processing_status = "ocr_processing"
- [ ] **For PDF files**:
  - [ ] Upload to S3 if local file
    - Generate S3 key with document UUID
    - Upload to S3_PRIMARY_DOCUMENT_BUCKET
    - Store s3_key, s3_bucket in database
  - [ ] Submit to AWS Textract
    - [ ] Create Textract job
    - [ ] Store textract_job_id
    - [ ] Poll for completion (async) or wait (sync)
  - [ ] Extract text from Textract response
  - [ ] Calculate average confidence score
  - [ ] Store raw_extracted_text
  - [ ] Store ocr_metadata_json

#### Error Logging:
- **Database Fields**:
  - `source_documents.error_message`: High-level error description
  - `source_documents.ocr_metadata_json`: Detailed OCR metadata including errors
  - `source_documents.textract_job_status`: Textract-specific status
  - `source_documents.textract_warnings`: Any Textract warnings
- **S3 Upload Errors**: Logged in celery worker logs
- **Textract Errors**: 
  - Job submission errors
  - Processing errors
  - Confidence threshold warnings
- **File Access Errors**: Local file not found, permissions

### Stage 4: Document Node Creation
**Location**: `scripts/celery_tasks/text_tasks.py::create_document_node()`

#### Checklist:
- [ ] Clean extracted text
  - Remove excessive whitespace
  - Normalize line endings
  - Remove non-printable characters
- [ ] Categorize document type
- [ ] Create neo4j_documents entry
  - [ ] Copy document metadata
  - [ ] Set cleaned_text_for_chunking
  - [ ] Set status = "ready_for_chunking"
- [ ] Update initial_processing_status = "chunking"

#### Error Logging:
- **Database**: `neo4j_documents.status`
- **Processing History**: `document_processing_history` table entry
- **Redis Cache**: Processing state cached with version

### Stage 5: Text Chunking
**Location**: `scripts/celery_tasks/text_tasks.py::process_chunking()`

#### Checklist:
- [ ] Apply semantic chunking algorithm
  - Target chunk size: 800-1200 tokens
  - Maintain sentence boundaries
  - Preserve context
- [ ] Create neo4j_chunks entries for each chunk
  - [ ] Generate chunk_id (UUID)
  - [ ] Set chunk_index (sequential)
  - [ ] Store chunk_text
  - [ ] Calculate token_count
  - [ ] Set char_start_index and char_end_index
- [ ] Create chunk relationships (NEXT_CHUNK, PREVIOUS_CHUNK)
- [ ] Update document status = "chunked"

#### Error Logging:
- **Database**: Each chunk has its own record
- **Redis Cache**: Chunk list cached
- **Validation**: Token count validation errors

### Stage 6: Entity Extraction
**Location**: `scripts/celery_tasks/entity_tasks.py::extract_entities()`

#### Checklist:
- [ ] For each chunk:
  - [ ] Send to OpenAI GPT-4 for NER
  - [ ] Parse JSON response
  - [ ] Validate entity format
  - [ ] Create neo4j_entity_mentions entries
    - Entity text
    - Entity type
    - Confidence score
    - Character positions
- [ ] Cache entity mentions in Redis
- [ ] Update chunk processing status

#### Error Logging:
- **Database**: `neo4j_entity_mentions` records
- **OpenAI API Errors**: 
  - Rate limiting
  - Token limits
  - JSON parsing errors
- **Redis Cache**: Failed extraction attempts

### Stage 7: Entity Resolution
**Location**: `scripts/celery_tasks/entity_tasks.py::resolve_entities()`

#### Checklist:
- [ ] Group entity mentions by type
- [ ] Apply fuzzy matching algorithms
- [ ] Create canonical entities
  - [ ] Generate canonical form
  - [ ] Assign canonical_id
  - [ ] Calculate confidence scores
- [ ] Update entity mentions with resolved_canonical_id
- [ ] Generate entity embeddings (if enabled)

#### Error Logging:
- **Database**: `neo4j_canonical_entities`
- **Resolution Conflicts**: Logged when ambiguous matches
- **Embedding Errors**: Vector generation failures

### Stage 8: Relationship Building
**Location**: `scripts/celery_tasks/graph_tasks.py::build_relationships()`

#### Checklist:
- [ ] Identify entity co-occurrences within chunks
- [ ] Calculate relationship strengths
- [ ] Create neo4j_relationship_staging entries
  - Source and target entities
  - Relationship type
  - Confidence score
  - Supporting chunk references
- [ ] Apply relationship inference rules

#### Error Logging:
- **Database**: `neo4j_relationship_staging`
- **Graph Validation**: Circular relationship warnings
- **Memory Errors**: Large document relationship limits

### Stage 9: Completion
**Location**: Various status updates

#### Checklist:
- [ ] Update source_documents:
  - [ ] celery_status = "completed"
  - [ ] initial_processing_status = "completed"
  - [ ] last_successful_stage = "graph_completed"
- [ ] Clear temporary Redis caches
- [ ] Record final metrics:
  - Total processing time
  - Token usage
  - Entity count
  - Relationship count

#### Error Logging:
- **Final Status**: `source_documents.celery_status`
- **Processing History**: Complete audit trail
- **Metrics**: `document_processing_history`

## Common Error Scenarios

### 1. File Type Errors
- **Issue**: detected_file_type missing dot (e.g., "pdf" instead of ".pdf")
- **Location**: Document intake
- **Fix**: Ensure file type includes dot prefix

### 2. S3 Upload Failures
- **Issue**: Local file cannot be uploaded to S3
- **Symptoms**: Textract job fails to start
- **Logs**: Check AWS credentials, bucket permissions
- **Location**: `source_documents.error_message`

### 3. Textract Processing Errors
- **Issue**: PDF corrupted or unsupported
- **Symptoms**: textract_job_status = "failed"
- **Logs**: `textract_warnings`, `ocr_metadata_json`

### 4. Memory/Timeout Issues
- **Issue**: Large documents exceed processing limits
- **Symptoms**: Celery task killed or timed out
- **Logs**: Celery worker logs, system memory logs

### 5. OpenAI API Failures
- **Issue**: Rate limiting or API errors
- **Symptoms**: Entity extraction incomplete
- **Logs**: Celery retry logs, API response errors

## Monitoring Commands

### Check Document Status
```bash
python -c "
from scripts.supabase_utils import SupabaseManager
db = SupabaseManager()
result = db.client.table('source_documents').select('*').eq('document_uuid', 'YOUR_UUID').execute()
print(result.data[0] if result.data else 'Not found')
"
```

### Check Celery Task
```bash
celery -A scripts.celery_app inspect active
celery -A scripts.celery_app inspect reserved
```

### View Processing History
```sql
SELECT * FROM document_processing_history 
WHERE document_uuid = 'YOUR_UUID' 
ORDER BY timestamp DESC;
```

### Redis Cache Status
```bash
redis-cli
> KEYS doc:*YOUR_UUID*
> TTL key_name
```

## Recovery Procedures

### Retry Failed Document
1. Reset status in source_documents
2. Clear error_message
3. Resubmit to Celery

### Force Reprocess
1. Set force_reprocess = true
2. Increment processing_version
3. Clear all cached data
4. Submit new Celery task

### Skip Failed Stage
1. Manually update last_successful_stage
2. Submit next stage task directly
3. Monitor for downstream issues

## Performance Metrics

### Expected Processing Times
- **OCR (Textract)**: 10-60 seconds per page
- **Text Cleaning**: < 1 second
- **Chunking**: 1-5 seconds
- **Entity Extraction**: 2-10 seconds per chunk
- **Entity Resolution**: 5-30 seconds total
- **Relationship Building**: 5-20 seconds

### Resource Usage
- **Memory**: ~500MB per worker
- **CPU**: Varies by stage
- **Network**: S3 uploads, API calls
- **Redis**: ~10KB per document cached

This checklist ensures comprehensive monitoring and debugging capabilities throughout the document processing pipeline.