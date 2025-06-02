# Context 272: Schema Modification Tasks - Complete Action List

## Date: May 31, 2025
## Purpose: Actionable list of all schema modifications needed to align Pydantic models with RDS

## Priority 1: Critical Fixes (Blocking Pipeline)

### 1. Fix SourceDocumentModel Field Mappings
```python
# In enhanced_column_mappings.py, update:
ENHANCED_COLUMN_MAPPINGS = {
    "source_documents": {
        # Fix field name mismatch
        "original_file_name": "original_filename",  # was looking for wrong column
        
        # Keep correct mappings
        "document_uuid": "document_uuid",
        "detected_file_type": "detected_file_type",
        "file_size_bytes": "file_size_bytes",
        "s3_key": "s3_key",
        "s3_bucket": "s3_bucket",
        "s3_region": "s3_region",
        
        # Map status fields properly
        "initial_processing_status": "initial_processing_status",
        "celery_status": "celery_status",
        
        # Map text content
        "raw_extracted_text": "raw_extracted_text",
        "markdown_text": "markdown_text",
        
        # Map metadata
        "ocr_metadata_json": "ocr_metadata_json",
        "transcription_metadata_json": "transcription_metadata_json",
        
        # Timestamps
        "created_at": "created_at",
        "updated_at": "updated_at",
        "ocr_completed_at": "ocr_completed_at"
    }
}
```

### 2. Add ProcessingTaskModel to schemas.py
```python
class ProcessingTaskModel(BaseTimestampModel):
    """Model for processing_tasks table"""
    # Foreign key
    document_id: uuid.UUID = Field(..., description="Document UUID reference")
    
    # Task details
    task_type: str = Field(..., description="Type of processing task")
    task_status: str = Field("pending", description="Current task status")
    celery_task_id: Optional[str] = Field(None, description="Celery task ID")
    
    # Retry logic
    retry_count: int = Field(0, description="Number of retries")
    max_retries: int = Field(3, description="Maximum retry attempts")
    
    # Results
    error_message: Optional[str] = Field(None, description="Error if failed")
    result: Optional[Dict[str, Any]] = Field(None, description="Task result data")
    
    # Timestamps
    started_at: Optional[datetime] = Field(None)
    completed_at: Optional[datetime] = Field(None)
```

### 3. Fix ChunkModel to Match RDS
```python
# Update ChunkModel in schemas.py:
class ChunkModel(BaseTimestampModel):
    """Model for chunks table - matches RDS schema"""
    # Required fields
    document_id: uuid.UUID = Field(..., description="Document UUID (not int!)")
    chunk_index: int = Field(..., description="Order in document")
    content: str = Field(..., description="Chunk text content")  # was 'text'
    
    # Page references
    start_page: Optional[int] = Field(None)
    end_page: Optional[int] = Field(None)
    
    # Optional fields
    metadata: Optional[Dict[str, Any]] = Field(None)  # was metadata_json
    embedding: Optional[List[float]] = Field(None)
    
    # Remove fields not in RDS:
    # - chunk_id (use id from base model)
    # - char_start_index
    # - char_end_index
    # - embedding_model
    # - previous_chunk_id
    # - next_chunk_id
```

## Priority 2: Add Missing Fields to Models

### 4. Update SourceDocumentModel for Missing RDS Fields
```python
# Add to SourceDocumentModel:
file_path: Optional[str] = Field(None, description="Local file path")
cleaned_text: Optional[str] = Field(None, description="Cleaned text content")
processing_status: Optional[str] = Field(None, description="Main processing status")
```

### 5. Update Column Mappings for Missing Fields
```python
# Add to ENHANCED_COLUMN_MAPPINGS:
"source_documents": {
    # ... existing mappings ...
    "file_path": "file_path",
    "cleaned_text": "cleaned_text", 
    "processing_status": "processing_status",
}
```

## Priority 3: Handle Table Name Differences

### 6. Create Table Name Mapping
```python
# Add to enhanced_column_mappings.py:
TABLE_NAME_MAPPINGS = {
    # Pydantic model name → RDS table name
    "SourceDocumentModel": "source_documents",
    "ProjectModel": "projects",
    "ChunkModel": "chunks",
    "ProcessingTaskModel": "processing_tasks",
    "CanonicalEntityModel": "canonical_entities",
    "EntityModel": "entities",  # Note: different from Pydantic EntityMentionModel
}
```

### 7. Update Entity Models
```python
# Create new EntityModel to match RDS entities table:
class EntityModel(BaseTimestampModel):
    """Model for entities table - matches RDS schema"""
    document_id: uuid.UUID = Field(..., description="Document UUID")
    canonical_entity_id: Optional[uuid.UUID] = Field(None)
    name: str = Field(..., description="Entity name")
    entity_type: str = Field(..., description="Entity type")
    confidence_score: Optional[float] = Field(None)
    context: Optional[str] = Field(None)
    page_number: Optional[int] = Field(None)
    metadata: Optional[Dict[str, Any]] = Field(None)
```

## Priority 4: Fix Type Mismatches

### 8. Fix document_id Type Consistency
```python
# In all models referencing documents, ensure document_id is UUID:
# ChunkModel: document_id: uuid.UUID (not int)
# EntityModel: document_id: uuid.UUID (not int)
# ProcessingTaskModel: document_id: uuid.UUID
```

### 9. Fix JSON/JSONB Field Handling
```python
# Ensure all JSONB fields handle both dict and string:
@field_validator('metadata', 'result', mode='before')
@classmethod
def parse_json_field(cls, v):
    """Parse JSON fields from string if needed"""
    if isinstance(v, str):
        try:
            return json.loads(v)
        except json.JSONDecodeError:
            return {}
    return v or {}
```

## Priority 5: Remove or Map Neo4j-Specific Models

### 10. Handle Neo4j Models
Options:
1. Remove from schemas.py if not using Neo4j
2. Create separate neo4j_schemas.py file
3. Map to equivalent RDS tables where possible

```python
# Map Neo4j models to RDS equivalents:
NEO4J_TO_RDS_MAPPINGS = {
    "Neo4jDocumentModel": "source_documents",
    "Neo4jChunkModel": "chunks", 
    "Neo4jEntityMentionModel": "entities",
    "Neo4jCanonicalEntityModel": "canonical_entities",
}
```

## Implementation Order

1. **Immediate (Today)**:
   - Fix `original_file_name` → `original_filename` mapping
   - Add ProcessingTaskModel
   - Fix ChunkModel field names

2. **Next Sprint**:
   - Update all document_id references to UUID
   - Add missing fields to models
   - Create proper table name mappings

3. **Future**:
   - Consolidate Neo4j models
   - Create comprehensive validation layer
   - Add schema migration scripts

## Testing Plan

After each modification:
1. Run `test_schema_conformance.py`
2. Test basic CRUD operations
3. Run end-to-end document processing
4. Verify data integrity in RDS

## Notes

- Keep backward compatibility where possible
- Document all changes in migration notes
- Consider creating a schema version tracking system
- Update all dependent code when changing field names