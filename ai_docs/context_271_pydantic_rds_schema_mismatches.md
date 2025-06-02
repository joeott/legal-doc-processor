# Context 271: Comprehensive Pydantic-RDS Schema Mismatch Analysis

## Date: May 31, 2025
## Purpose: Document all mismatches between Pydantic models and RDS database schema

## Summary of Analysis Approach
1. Examined all Pydantic models in `/scripts/core/schemas.py`
2. Compared with actual RDS schema findings from context_265
3. Identified field name mismatches, missing fields, and type differences

## Key Findings

### 1. SourceDocumentModel Mismatches

#### Field Name Mismatches:
```python
# Pydantic Model Field → RDS Column Name
"original_file_name" → "original_filename"  # Missing underscore in RDS
"detected_file_type" → "detected_file_type" ✓ # Match
"file_size_bytes" → "file_size_bytes" ✓ # Match
```

#### Missing in RDS but Expected by Pydantic:
- `project_fk_id` - FK to projects table (ID)
- `project_uuid` - FK to projects table (UUID)
- `original_file_path` - Separate from S3 path
- `s3_key_public` - Public S3 key
- `s3_bucket_public` - Public S3 bucket
- `md5_hash` - File hash
- `content_type` - MIME type header
- `user_defined_name` - User-provided name
- `error_message` - Error details
- `intake_timestamp` - Upload timestamp
- `last_modified_at` - Modification timestamp
- `ocr_provider` - OCR service used
- `ocr_processing_seconds` - Processing time
- `textract_job_id` - AWS Textract job ID
- `textract_job_status` - Textract status
- `textract_job_started_at` - Start time
- `textract_job_completed_at` - End time
- `textract_confidence_avg` - Average confidence
- `textract_warnings` - Warning list
- `textract_output_s3_key` - Output location
- `import_session_id` - Import batch ID

#### Present in RDS but Not in Pydantic Model:
- `file_path` - Local file path
- `cleaned_text` - Cleaned version of text
- `processing_status` - Main processing status

### 2. Processing Tasks Table Mismatch

The RDS has a `processing_tasks` table but there's no corresponding `ProcessingTaskModel` in the Pydantic schemas. The table has:
- `id` (UUID)
- `document_id` (UUID FK)
- `task_type` (VARCHAR)
- `task_status` (ENUM)
- `celery_task_id` (VARCHAR)
- `retry_count` (INTEGER)
- `max_retries` (INTEGER)
- `error_message` (TEXT)
- `result` (JSONB)
- `started_at` (TIMESTAMP)
- `completed_at` (TIMESTAMP)
- `created_at` (TIMESTAMP)
- `updated_at` (TIMESTAMP)

### 3. ProjectModel Issues

The Pydantic `ProjectModel` expects:
- `project_id` (UUID) - internal UUID
- `supabase_project_id` (UUID) - Supabase reference
- `script_run_count` (int)
- `processed_by_scripts` (bool)
- `data_layer` (Dict)
- `airtable_id` (str)
- `metadata` (Dict)
- `active` (bool)
- `last_synced_at` (datetime)

But the RDS `projects` table has:
- `id` (UUID)
- `name` (VARCHAR)
- `description` (TEXT)
- `client_name` (VARCHAR)
- `matter_number` (VARCHAR)
- `metadata` (JSONB)
- `created_at` (TIMESTAMP)
- `updated_at` (TIMESTAMP)

### 4. Neo4j Tables Don't Exist in RDS

The Pydantic models define these Neo4j-specific models, but they don't exist in the RDS schema:
- `Neo4jDocumentModel` → No `neo4j_documents` table
- `ChunkModel` → Maps to `chunks` table but with different structure
- `EntityMentionModel` → No `neo4j_entity_mentions` table
- `CanonicalEntityModel` → Maps to `canonical_entities` but different structure
- `RelationshipStagingModel` → No `neo4j_relationships_staging` table

### 5. ChunkModel vs chunks Table

Pydantic `ChunkModel` expects:
- `chunk_id` (UUID)
- `document_id` (int) - SQL ID reference
- `document_uuid` (UUID)
- `chunk_index` (int)
- `text` (str)
- `char_start_index` (int)
- `char_end_index` (int)
- `metadata_json` (Dict)
- `embedding` (List[float])
- `embedding_model` (str)
- `previous_chunk_id` (UUID)
- `next_chunk_id` (UUID)

RDS `chunks` table has:
- `id` (UUID)
- `document_id` (UUID) - UUID reference, not int!
- `chunk_index` (INTEGER)
- `content` (TEXT) - not `text`
- `start_page` (INTEGER)
- `end_page` (INTEGER)
- `metadata` (JSONB)
- `embedding` (VECTOR)
- `created_at` (TIMESTAMP)
- `updated_at` (TIMESTAMP)

### 6. Entity Model Differences

Pydantic models have separate `EntityMentionModel` and `CanonicalEntityModel`, but RDS has:
- Single `entities` table with references to `canonical_entities`
- Different field names and structure

## Required Schema Modifications

### Option 1: Modify Pydantic Models to Match RDS
1. Update field names to match actual column names
2. Remove fields that don't exist in RDS
3. Add missing fields from RDS
4. Create missing models (like ProcessingTaskModel)

### Option 2: Modify RDS Schema to Match Pydantic Models
1. Add missing columns via migrations
2. Rename columns to match Pydantic expectations
3. Create missing tables

### Option 3: Enhanced Mapping Layer (Recommended)
1. Keep Pydantic models as the "ideal" schema
2. Create a comprehensive mapping layer that handles:
   - Field name translations
   - Data type conversions
   - Missing field defaults
   - Computed/derived fields
3. Use SQLAlchemy models that match RDS exactly

## Immediate Actions Required

1. **Create ProcessingTaskModel**:
```python
class ProcessingTaskModel(BaseTimestampModel):
    """Model for processing_tasks table"""
    document_id: uuid.UUID = Field(..., description="Document UUID")
    task_type: str = Field(..., description="Type of task")
    task_status: str = Field("pending", description="Task status")
    celery_task_id: Optional[str] = Field(None)
    retry_count: int = Field(0)
    max_retries: int = Field(3)
    error_message: Optional[str] = Field(None)
    result: Optional[Dict[str, Any]] = Field(None)
    started_at: Optional[datetime] = Field(None)
    completed_at: Optional[datetime] = Field(None)
```

2. **Fix Critical Field Mappings**:
- `original_file_name` → `original_filename`
- `text` → `content` (for chunks)
- Remove references to non-existent neo4j tables
- Fix document_id types (UUID vs int inconsistency)

3. **Create Proper SQLAlchemy Models**:
Create SQLAlchemy declarative models that exactly match the RDS schema, separate from Pydantic validation models.

## Conclusion

There are significant mismatches between the Pydantic models (which appear to be based on an idealized Supabase schema) and the actual RDS PostgreSQL schema. The recommended approach is to:

1. Create a proper mapping layer
2. Add missing Pydantic models
3. Fix field name mismatches
4. Handle type conversions properly
5. Consider a phased migration to align schemas

This will require systematic updates to ensure data flows correctly through the pipeline.