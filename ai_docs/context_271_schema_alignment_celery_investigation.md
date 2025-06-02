# Context 271: Schema Alignment and Celery Investigation

## Overview
This session focused on resolving deployment stage confusion and fixing schema mismatches between Pydantic models and the RDS database that were preventing document processing.

## Key Issues Addressed

### 1. Deployment Stage Correction
- **Issue**: System was configured as Stage 3 (local models) but actually using Stage 1 (cloud models)
- **Fix**: Changed DEPLOYMENT_STAGE from 3 to 1 in .env file
- **Impact**: Resolved environment variable requirements mismatch

### 2. Environment Variable Propagation
- **Issue**: Celery workers weren't receiving environment variables (OPENAI_API_KEY, etc.)
- **Fix**: Updated Supervisor configuration to properly pass all env vars to workers
- **Location**: `/etc/supervisor/conf.d/celery-workers.conf`

### 3. Schema Mismatch Resolution
- **Issue**: Multiple column name mismatches between Pydantic models and RDS schema
  - `filename` vs `file_name`
  - `processing_status` vs `status`
  - Missing `processing_tasks` table entirely
- **Fix**: Created and executed SQL migration to align RDS schema with Pydantic models
- **Decision**: User explicitly chose to modify database schema rather than code

### 4. Column Mapping Updates
- **File**: `/opt/legal-doc-processor/scripts/enhanced_column_mappings.py`
- **Changes**: Updated mappings to reflect renamed columns
  ```python
  "filename": "file_name",  # Map to renamed column
  "file_name": "file_name",  # Direct mapping for new name
  "processing_status": "status",  # Map to renamed column
  "status": "status",  # Direct mapping for new name
  ```

## Technical Discoveries

### 1. Document Lookup Investigation
- Added debug logging throughout the database access layers
- Created test script that confirmed document lookups work correctly
- Document UUID `4dcc5583-b2cc-4d68-bdd0-6e227a98cf8b` successfully found in database
- The lookup chain works: PDFTask → DatabaseManager → PydanticDatabase → rds_utils

### 2. Celery Task Registration
- Discovered tasks weren't being registered with Celery workers
- Manual import test showed tasks register correctly when imported
- All 8 PDF processing tasks confirmed present:
  - `extract_text_from_document` (queue: ocr)
  - `chunk_document_text` (queue: text)
  - `extract_entities_from_chunks` (queue: entity)
  - `resolve_document_entities` (queue: entity)
  - `build_document_relationships` (queue: graph)
  - `process_pdf_document` (queue: default)
  - `cleanup_failed_document` (queue: cleanup)
  - `cleanup_old_cache_entries` (queue: cleanup)

## Current Status

### Working:
- ✅ Environment variables properly configured
- ✅ Database schema aligned with Pydantic models
- ✅ Document lookups functioning correctly
- ✅ Celery tasks register when manually imported
- ✅ All workers restarted with new configuration

### Pending Investigation:
- ❓ Why Celery workers aren't auto-discovering tasks from `scripts.pdf_tasks`
- ❓ Possible issue with worker startup command or Python path

## SQL Migrations Applied

```sql
-- Renamed columns in source_documents
ALTER TABLE source_documents RENAME COLUMN filename TO file_name;
ALTER TABLE source_documents RENAME COLUMN processing_status TO status;

-- Created missing processing_tasks table
CREATE TABLE IF NOT EXISTS processing_tasks (
    id SERIAL PRIMARY KEY,
    document_uuid UUID NOT NULL,
    task_type VARCHAR(50) NOT NULL,
    task_status VARCHAR(50) NOT NULL,
    celery_task_id VARCHAR(255),
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    error_message TEXT,
    result JSONB,
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (document_uuid) REFERENCES source_documents(document_uuid) ON DELETE CASCADE
);
```

## Helper Scripts Created

1. **load_env.sh** - Simple environment variable loader
2. **test_document_lookup.py** - Validates database connectivity and document queries
3. **test_celery_tasks.py** - Confirms Celery task registration

## Next Steps

1. Investigate why Celery workers aren't auto-importing tasks
2. Check Supervisor command configuration for workers
3. Verify PYTHONPATH is set correctly for worker processes
4. Once tasks are loading, test full document processing pipeline

## Key Learnings

1. Schema alignment is critical - even minor column name differences break the pipeline
2. Environment variable propagation to subprocess workers requires explicit configuration
3. Celery task discovery can fail silently if imports aren't configured correctly
4. Debug logging at multiple layers is essential for troubleshooting distributed systems