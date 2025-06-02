# Context 272: Pydantic Models as Source of Truth - Testing Plan

## Core Principle
**Pydantic models are the source of truth** - All scripts, database schemas, and mappings must conform to the Pydantic model definitions, not the other way around.

## Testing Strategy

### 1. Test Hierarchy
1. **Pydantic Model Tests** (`tests/core/test_schemas.py`)
   - Validate model structure and field definitions
   - Ensure all required fields are present
   - Verify field types and constraints
   - Test model serialization/deserialization

2. **Processing Model Tests** (`tests/core/test_processing_models.py`)
   - Validate import/export models
   - Test validation result models
   - Verify task and status models

3. **Database Layer Tests** (`tests/test_db.py`)
   - Ensure DatabaseManager correctly uses Pydantic models
   - Verify CRUD operations preserve model integrity
   - Test that database operations accept and return valid Pydantic models

4. **Task Tests** (`tests/test_pdf_tasks.py`)
   - Verify tasks use Pydantic models for all data operations
   - Ensure task inputs/outputs conform to model schemas
   - Test error handling with invalid model data

### 2. Database Schema Alignment Approach

Since Pydantic models are the truth, we will:

1. **Identify Mismatches**
   - Run tests to find where RDS schema differs from Pydantic models
   - Document each mismatch with specific column/table differences

2. **Generate Migration Scripts**
   - Create SQL ALTER statements to modify RDS schema
   - Add missing columns with appropriate types
   - Rename columns to match Pydantic field names
   - Create missing tables based on model definitions

3. **Apply Changes Incrementally**
   - Test each migration before applying
   - Verify data integrity is maintained
   - Ensure no data loss during schema changes

### 3. Key Pydantic Models to Validate

1. **SourceDocumentModel**
   - Primary document tracking model
   - Must have all fields for S3, processing status, OCR metadata

2. **ChunkModel**
   - Document chunk representation
   - Requires text content, indices, metadata

3. **EntityMentionModel**
   - Entity extraction results
   - Links to documents and chunks

4. **ProcessingTaskModel**
   - Celery task tracking
   - Status, retries, error handling

5. **ProjectModel**
   - Project/matter organization
   - Client and matter metadata

### 4. Expected Schema Modifications

Based on current findings, we expect to:

1. **source_documents table**
   - Already fixed: `filename` → `file_name`
   - Already fixed: `processing_status` → `status`
   - May need: Additional metadata columns

2. **processing_tasks table**
   - Already created with proper structure
   - Verify all Pydantic fields are present

3. **document_chunks table**
   - May need: `text` → `text_content` mapping verification
   - Check metadata_json structure

4. **entity_mentions table**
   - Verify canonical_entity_id references
   - Check confidence score fields

### 5. Testing Execution Plan

1. **Phase 1: Model Validation**
   ```bash
   pytest tests/core/test_schemas.py -v
   ```
   - Ensure all Pydantic models are valid
   - Document any model issues

2. **Phase 2: Database Conformance**
   ```bash
   pytest tests/test_db.py -v -k "conformance"
   ```
   - Run database conformance tests
   - Generate list of schema mismatches

3. **Phase 3: Apply Schema Fixes**
   - Create SQL migration scripts
   - Apply to RDS database
   - Re-run conformance tests

4. **Phase 4: Integration Testing**
   ```bash
   pytest tests/test_pdf_tasks.py -v
   ```
   - Verify tasks work with aligned schema
   - Test full document processing

### 6. Success Criteria

1. All Pydantic model tests pass
2. Database schema exactly matches Pydantic model fields
3. No column mapping hacks needed in code
4. Scripts can use models directly without transformation
5. Full document processing pipeline works end-to-end

### 7. Current Status

- **Completed**: Initial schema fixes (filename, status columns)
- **Pending**: Full test suite execution
- **Blocked**: Celery task discovery issue (separate concern)

## Important Notes

1. **No Compromises**: If a script doesn't work with the Pydantic model, fix the script, not the model
2. **Column Mappings**: Should eventually be removed once RDS fully conforms
3. **Validation**: Re-enable conformance validation once schema is aligned
4. **Documentation**: Each schema change must be documented in migration scripts