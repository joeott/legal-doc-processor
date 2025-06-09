# Context 418: Model Field Usage Analysis Results

## Executive Summary

This document captures the results of analyzing field usage across the codebase and database column utilization. The analysis reveals that only a small subset of available database columns are actively used, confirming the need for minimal model definitions.

## Field Usage Analysis Results

### Required Fields by Model (Based on Code Analysis)

**SourceDocument Model:**
- `id` - Primary key, used in DB operations
- `document_uuid` - Primary identifier
- `file_name` - Used for display and logging
- `original_file_name` - Preserved from upload
- `s3_key` - Required for S3 operations
- `s3_bucket` - Required for S3 operations
- `status` - Critical for pipeline state
- `raw_extracted_text` - OCR output storage
- `textract_job_id` - Textract job tracking
- `project_fk_id` - Project association
- `created_at` - Timestamp tracking
- `updated_at` - Change tracking
- `ocr_completed_at` - OCR completion tracking
- `error_message` - Error tracking
- `celery_task_id` - Task tracking

**DocumentChunk Model:**
- `chunk_uuid` - Primary identifier
- `document_uuid` - Document association
- `chunk_index` - Ordering
- `text` - Main content field
- `char_start_index` - Position tracking
- `char_end_index` - Position tracking
- `created_at` - Timestamp

**EntityMention Model:**
- `mention_uuid` - Primary identifier
- `document_uuid` - Document association
- `chunk_uuid` - Chunk association
- `entity_text` - Extracted text
- `entity_type` - Classification
- `start_char` - Position in chunk
- `end_char` - Position in chunk
- `confidence_score` - Extraction confidence
- `canonical_entity_uuid` - Resolution link
- `created_at` - Timestamp

**CanonicalEntity Model:**
- `canonical_entity_uuid` - Primary identifier
- `canonical_name` - Normalized name
- `entity_type` - Classification
- `mention_count` - Frequency tracking
- `confidence_score` - Resolution confidence
- `aliases` - Alternative names (JSON)
- `properties` - Additional data (JSON)
- `metadata` - Extra information (JSON)
- `created_at` - Timestamp
- `updated_at` - Change tracking

**RelationshipStaging Model:**
- `source_entity_uuid` - Source entity
- `target_entity_uuid` - Target entity
- `relationship_type` - Type classification
- `confidence_score` - Relationship confidence
- `source_chunk_uuid` - Evidence location
- `evidence_text` - Supporting text
- `properties` - Additional data (JSON)
- `metadata` - Extra information (JSON)
- `created_at` - Timestamp

### Field Usage by Core Scripts

**pdf_tasks.py** - Core processing orchestrator
- Heavy use of status fields
- Document UUID for all operations
- Cache key patterns (DOC_STATE, DOC_CHUNKS, etc.)
- Error handling fields

**textract_utils.py** - OCR operations
- Textract job tracking fields
- S3 bucket/key for document access
- Raw text storage
- Error message handling

**entity_service.py** - Entity extraction
- Entity text and type fields
- Confidence scores
- Canonical entity linking
- Position tracking (start_char, end_char)

**chunking_utils.py** - Text chunking
- Character index fields (char_start_index, char_end_index)
- Chunk index for ordering
- Text content field
- Document UUID linking

**intake_service.py** - Document creation
- Basic document fields (UUID, filename, S3 location)
- Project association
- Status initialization

**batch_processor.py** - Batch operations
- Document status tracking
- Celery task management
- Error handling
- Batch completion tracking

## Database Column Usage Analysis

### SOURCE_DOCUMENTS Table (440 documents analyzed)

**Always Used (100% of rows):**
- `document_uuid` - Every document has UUID
- `file_name` - Always populated
- `original_file_name` - Preserved from upload
- `s3_key` - Required for storage
- `s3_bucket` - Required for storage
- `status` - Always has a status
- `project_fk_id` - Project association

**Sometimes Used:**
- `raw_extracted_text` - 72 rows (16%) - Only after OCR
- `textract_job_id` - 53 rows (12%) - Only for Textract jobs
- `celery_task_id` - Varies based on processing
- `error_message` - Only on failures

**Never Used (0 rows):**
- `markdown_text` - Not implemented
- `cleaned_text` - Not implemented
- `ocr_metadata_json` - Not used
- `s3_key_public` - Not used
- `initial_processing_status` - Legacy field
- `transcription_metadata_json` - Not implemented

### Key Findings

1. **Minimal Fields Actually Required**: Only 15-20 fields per model are actively used
2. **Many Legacy Columns**: Database has accumulated unused columns over time
3. **Consistent Core Fields**: All models use UUID, timestamps, and status fields
4. **JSON Fields Underutilized**: Most JSON columns are empty but could be useful

## Implications for Model Consolidation

### Fields to Include in Minimal Models

Based on actual usage, the minimal models should include only:

1. **Essential Identifiers**: UUIDs, IDs, foreign keys
2. **Core Data Fields**: The main content/text fields
3. **Status Tracking**: Status and error fields
4. **Timestamps**: Created/updated tracking
5. **Required Metadata**: S3 location, project association

### Fields to Exclude

1. **Unused Text Variants**: markdown_text, cleaned_text
2. **Legacy Status Fields**: initial_processing_status
3. **Unused Metadata**: Most JSON metadata fields
4. **Public Access Fields**: s3_key_public, s3_bucket_public
5. **Detailed Tracking**: Many timing and metric fields

### Column Name Mismatches to Fix

1. **Document Chunks**: Database uses `char_start_index`/`char_end_index`, not `start_char`/`end_char`
2. **Canonical Entities**: Database uses `canonical_name`, not `entity_name`
3. **Relationships**: No `relationship_uuid` column exists in database

## Recommendations

1. **Use Only Active Fields**: Include only the ~15 fields per model that are actually used
2. **Fix Column Names**: Ensure model fields match database column names exactly
3. **Add Compatibility Properties**: For fields that changed names, add @property methods
4. **Document Required Fields**: Clearly mark which fields are required vs optional
5. **Plan Column Cleanup**: Consider database migration to remove unused columns

This analysis confirms that minimal models with only essential fields will:
- Reduce memory usage
- Improve performance
- Simplify debugging
- Eliminate confusion from unused fields