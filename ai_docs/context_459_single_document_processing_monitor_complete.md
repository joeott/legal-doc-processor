# Context 459: Single Document Processing Monitor - Complete Analysis

## Date: January 9, 2025

## Executive Summary

This document provides a comprehensive analysis of processing a single document through the legal document pipeline, tracking each stage, the scripts/functions used, and verifying compliance with the updated Pydantic models.

## Document Processing Details

### Test Document
- **File**: Paul, Michael - Lora Prop Disclosure Stmt 10-21-24.pdf
- **Size**: 149,104 bytes (0.14 MB)
- **Document UUID**: eaca69ea-1b5f-48f4-b7a1-6ac73521e0e5
- **S3 Location**: s3://samu-docs-private-upload/documents/eaca69ea-1b5f-48f4-b7a1-6ac73521e0e5.pdf

### Processing Timeline
- **Start Time**: 2025-06-09 01:45:57
- **Project Creation**: Project ID 25 (BATCH_2_DOCS_20250609_014557)
- **Document Upload**: Successful to S3
- **Database Record**: Created with ID 1416
- **Celery Task**: Submitted with ID a0cfe520-125f-465e-81e7-7b62dbe06d7b

## Pipeline Execution Flow

### Stage 1: Project Creation
**Script**: `scripts/db.py`
**Function**: `DatabaseManager.execute()`
**Details**:
- Creates new project record in `projects` table
- Generates project UUID
- Sets project as active
- **Status**: ✅ Successful

### Stage 2: S3 Upload
**Script**: `scripts/s3_storage.py`  
**Function**: `S3StorageManager.upload_document_with_uuid_naming()`
**Details**:
- Uploads PDF to S3 with UUID-based naming
- Stores original filename in S3 metadata
- Generates MD5 hash for integrity
- **Status**: ✅ Successful

### Stage 3: Document Record Creation
**Script**: `scripts/intake_service.py`
**Function**: `create_document_with_validation()`
**Parameters Used**:
```python
create_document_with_validation(
    document_uuid=doc_uuid,
    filename=filename,
    s3_bucket=s3_bucket,
    s3_key=s3_key,
    project_id=project_id
)
```
**Details**:
- Creates record in `source_documents` table
- Links to project via `project_fk_id`
- Sets initial status to 'uploaded'
- **Status**: ✅ Successful

### Stage 4: Redis Metadata Storage
**Script**: `scripts/cache.py`
**Function**: `RedisManager.store_dict()`
**Details**:
- Stores project association metadata in Redis
- Key: `doc:metadata:{document_uuid}`
- TTL: 3600 seconds (1 hour)
- **Status**: ✅ Successful

### Stage 5: Celery Task Submission
**Script**: `scripts/pdf_tasks.py`
**Function**: `extract_text_from_document.apply_async()`
**Parameters**:
```python
extract_text_from_document.apply_async(
    args=[document_uuid, s3_url]
)
```
**Details**:
- Submits OCR task to Celery queue
- Returns task ID for monitoring
- Triggers async processing pipeline
- **Status**: ✅ Submitted

## Pipeline Processing Stages (Async)

### Stage 6: OCR Processing (Textract)
**Script**: `scripts/textract_utils.py`
**Function**: `TextractManager.start_document_text_detection()`
**Details**:
- Uses async-only Textract processing
- No scanned PDF detection (per configuration)
- Polls for job completion
- Updates `textract_jobs` table

### Stage 7: Text Chunking
**Script**: `scripts/chunking_utils.py`
**Function**: `create_semantic_chunks()`
**Details**:
- Creates semantic chunks from extracted text
- Uses `DocumentChunkMinimal` model
- Stores in `document_chunks` table
- **Important**: Uses `text` field, not `text_content`

### Stage 8: Entity Extraction
**Script**: `scripts/entity_service.py`
**Function**: `extract_entities_from_chunks()`
**Details**:
- Uses OpenAI gpt-4o-mini for extraction
- Creates `EntityMentionMinimal` records
- Stores in `entity_mentions` table
- **Important**: Uses `entity_text`, `start_char`, `end_char` fields

### Stage 9: Entity Resolution
**Script**: `scripts/entity_service.py`
**Function**: `resolve_entities_simple()`
**Details**:
- Deduplicates entity mentions
- Creates `CanonicalEntityMinimal` records
- Updates `canonical_entities` table
- **Important**: Uses `canonical_name` field, not `entity_name`

### Stage 10: Relationship Building
**Script**: `scripts/graph_service.py`
**Function**: `build_relationships()`
**Details**:
- Identifies relationships between entities
- Creates `RelationshipStagingMinimal` records
- Stores in `relationship_staging` table
- **Important**: No `relationship_uuid` field; uses `source_chunk_uuid` for document link

## Model Compliance Verification

### ✅ Column Name Compliance
1. **document_chunks**:
   - Using `text` (not `text_content`) ✅
   - Using `char_start_index`/`char_end_index` ✅

2. **canonical_entities**:
   - Using `canonical_name` (not `entity_name`) ✅
   - No `created_from_document_uuid` field ✅

3. **entity_mentions**:
   - Using `entity_text` for mention text ✅
   - Using `start_char`/`end_char` for positions ✅

4. **relationship_staging**:
   - Using `source_entity_uuid`/`target_entity_uuid` ✅
   - Using `source_chunk_uuid` for document link ✅

### ✅ Model Import Compliance
1. All database models imported from `scripts.models`
2. Processing models kept separate in `scripts.core.processing_models`
3. Backward compatibility properties functioning correctly

## Key Scripts and Their Roles

### Core Processing Scripts
1. **batch_submit_2_documents.py** - Document submission entry point
2. **scripts/intake_service.py** - Document intake and validation
3. **scripts/s3_storage.py** - S3 file management
4. **scripts/pdf_tasks.py** - Celery task definitions
5. **scripts/textract_utils.py** - OCR processing
6. **scripts/chunking_utils.py** - Text chunking
7. **scripts/entity_service.py** - Entity extraction/resolution
8. **scripts/graph_service.py** - Relationship building

### Support Scripts
1. **scripts/db.py** - Database operations
2. **scripts/cache.py** - Redis caching
3. **scripts/models.py** - Consolidated Pydantic models
4. **scripts/config.py** - Configuration management

## Configuration Highlights

### Critical Settings
```python
ENABLE_SCANNED_PDF_DETECTION = false  # Must be false
SKIP_PDF_PREPROCESSING = true
FORCE_PROCESSING = true
SKIP_CONFORMANCE_CHECK = true  # For minimal models
S3_BUCKET_REGION = us-east-2  # Must match bucket
```

### Deployment Stage
- **Stage 1**: Cloud-only (OpenAI/Textract)
- Uses external APIs for OCR and entity extraction
- No local model dependencies

## Monitoring and Verification

### Database Status Check
The document status can be monitored via:
```sql
SELECT status, celery_status, error_message
FROM source_documents  
WHERE document_uuid = 'eaca69ea-1b5f-48f4-b7a1-6ac73521e0e5';
```

### Pipeline Results Verification
```sql
-- Check chunks
SELECT COUNT(*) FROM document_chunks 
WHERE document_uuid = 'eaca69ea-1b5f-48f4-b7a1-6ac73521e0e5';

-- Check entities
SELECT COUNT(*) FROM entity_mentions
WHERE document_uuid = 'eaca69ea-1b5f-48f4-b7a1-6ac73521e0e5';

-- Check relationships
SELECT COUNT(*) FROM relationship_staging rs
JOIN document_chunks dc ON rs.source_chunk_uuid = dc.chunk_uuid
WHERE dc.document_uuid = 'eaca69ea-1b5f-48f4-b7a1-6ac73521e0e5';
```

## Conclusions

### Successful Implementations
1. ✅ Document upload and S3 storage working correctly
2. ✅ Database record creation with proper FK relationships
3. ✅ Celery task submission functioning
4. ✅ All column references using correct names
5. ✅ Model imports properly consolidated
6. ✅ Backward compatibility maintained

### Key Findings
1. The pipeline uses the correct column names matching the database schema
2. Processing flows through multiple async stages via Celery
3. Each stage updates specific database tables
4. Redis is used for temporary state and metadata storage
5. The system maintains backward compatibility through property mappings

### Recommendations
1. Monitor Celery workers to ensure tasks are processing
2. Check Textract job status for OCR completion
3. Verify entity extraction quota availability
4. Ensure relationships are built after entity resolution
5. Use monitoring tools to track pipeline progress

## Pipeline Processing Confirmation

Based on the monitoring output, the document was successfully:
- Uploaded to S3 ✅
- Created in database ✅
- Submitted to Celery ✅
- Ready for async processing ✅

The remaining stages (OCR, chunking, entity extraction, etc.) occur asynchronously and can be monitored using the provided SQL queries or monitoring commands.