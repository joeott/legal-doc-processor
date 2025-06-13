# Context 486: Pydantic Models vs Schema Mismatches Analysis

## Date: January 9, 2025

## Executive Summary

This document provides a detailed comparison between the Pydantic models in `/opt/legal-doc-processor/scripts/models.py` and the schema mismatches identified in context_485. The analysis confirms where models are correct and identifies areas that need attention.

## 1. Projects Table Analysis

### Schema Mismatch Identified:
- **Issue**: Code uses `project_name` but column is `name`
- **Model Check**: `ProjectMinimal` (line 227-236)
```python
class ProjectMinimal(BaseModel):
    id: int
    project_id: UUID
    name: str  # ✅ CORRECT - uses 'name' not 'project_name'
    active: bool = True
    created_at: Optional[datetime] = None
```
**Verdict**: ✅ Model is correct. The issue is in SQL queries, not the model.

## 2. Source Documents Table Analysis

### Schema Mismatch Identified:
- **Issue**: Code uses `processing_status` but column is `status`
- **Model Check**: `SourceDocumentMinimal` (line 41-82)
```python
status: str = ProcessingStatus.PENDING.value  # ✅ CORRECT - uses 'status'
```
**Verdict**: ✅ Model is correct. The field is properly named `status`.

### Additional Observations:
- Model includes `processing_completed_at` (line 81) which may not exist in database
- Model correctly uses `status` not `processing_status`

## 3. Processing Tasks Table Analysis

### Schema Mismatch Identified:
- **Issue**: `id` is UUID in database but `Optional[int]` in model
- **Model Check**: `ProcessingTaskMinimal` (line 213-226)
```python
id: Optional[int] = None  # ❌ INCORRECT - should be Optional[UUID]
```
**Verdict**: ❌ Model needs fixing. The `id` field should be `Optional[UUID]`.

### Correct Model Should Be:
```python
class ProcessingTaskMinimal(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    
    id: Optional[UUID] = None  # Fixed: Changed from int to UUID
    task_uuid: UUID
    document_uuid: UUID
    stage: str
    status: str = ProcessingStatus.PENDING.value
    celery_task_id: Optional[str] = None
    error_message: Optional[str] = None
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
```

## 4. Document Chunks Table Analysis

### Schema Mismatch Identified:
- **Issue**: Database uses `char_start_index`/`char_end_index` but code expects `start_char`/`end_char`
- **Model Check**: `DocumentChunkMinimal` (line 83-122)
```python
# Position tracking - MUST match database column names
char_start_index: int  # Database column name
char_end_index: int    # Database column name

# Backward compatibility properties for code expecting old names
@property
def start_char(self) -> int:
    """Backward compatibility for code expecting start_char"""
    return self.char_start_index

@property
def end_char(self) -> int:
    """Backward compatibility for code expecting end_char"""
    return self.char_end_index
```
**Verdict**: ✅ Model is perfectly implemented with backward compatibility.

### Text Field:
```python
text: str  # Main content field in database
@property
def text_content(self) -> str:
    """Backward compatibility for code expecting text_content"""
    return self.text
```
**Verdict**: ✅ Correctly uses `text` with backward compatibility for `text_content`.

## 5. Entity Mentions Table Analysis

### Schema Mismatch Identified:
- **Issue**: Code uses `chunk_id` but should use `chunk_uuid`
- **Model Check**: `EntityMentionMinimal` (line 123-150)
```python
# Associations
document_uuid: UUID
chunk_uuid: UUID  # ✅ CORRECT - uses chunk_uuid
chunk_fk_id: Optional[int] = None
```
**Verdict**: ✅ Model is correct. Uses `chunk_uuid` properly.

### Position Fields:
```python
# Position in chunk - matches database columns
start_char: int  # ✅ CORRECT - matches entity_mentions table
end_char: int    # ✅ CORRECT - matches entity_mentions table
```
**Note**: Entity mentions use `start_char`/`end_char` while chunks use `char_start_index`/`char_end_index`. This is correct per the database schema.

## 6. Canonical Entities Table Analysis

### Schema Mismatch Identified:
- **Issue**: Code queries for `document_uuid` but table has no such column
- **Model Check**: `CanonicalEntityMinimal` (line 151-184)
```python
class CanonicalEntityMinimal(BaseModel):
    # Primary identifiers
    canonical_entity_uuid: UUID
    id: Optional[int] = None
    
    # Entity data - MUST use canonical_name to match database
    canonical_name: str  # ✅ CORRECT - Database column name
    entity_type: str
    
    # No document_uuid field # ✅ CORRECT - matches schema
```
**Verdict**: ✅ Model is correct. It properly excludes `document_uuid` since canonical entities are not tied to specific documents.

### Backward Compatibility:
```python
@property
def entity_name(self) -> str:
    """Backward compatibility for code expecting entity_name"""
    return self.canonical_name
```
**Verdict**: ✅ Excellent backward compatibility implementation.

## 7. Relationship Staging Table Analysis

### Model Check: `RelationshipStagingMinimal` (line 185-208)
```python
# Primary identifier - NO relationship_uuid in database!
id: Optional[int] = None  # ✅ CORRECT - comment explicitly notes no relationship_uuid
```
**Verdict**: ✅ Model correctly excludes `relationship_uuid` with clear documentation.

## 8. Textract Jobs Table

### Schema Mismatch Identified:
- **Issue**: Code uses `job_status` but column is `status`
- **Model Check**: No TextractJob model found in models.py
**Verdict**: ⚠️ Missing model. Should be added for consistency.

## Summary of Findings

### ✅ Correctly Implemented Models:
1. **ProjectMinimal** - Correctly uses `name` not `project_name`
2. **SourceDocumentMinimal** - Correctly uses `status` not `processing_status`
3. **DocumentChunkMinimal** - Perfect backward compatibility implementation
4. **EntityMentionMinimal** - Correctly uses `chunk_uuid`
5. **CanonicalEntityMinimal** - Correctly uses `canonical_name` with backward compatibility
6. **RelationshipStagingMinimal** - Correctly excludes `relationship_uuid`

### ❌ Models Needing Fixes:
1. **ProcessingTaskMinimal** - Change `id: Optional[int]` to `id: Optional[UUID]`

### ⚠️ Missing Models:
1. **TextractJobMinimal** - Should be added for completeness

## Backward Compatibility Excellence

The models demonstrate excellent backward compatibility patterns:
- `chunk.start_char` → `chunk.char_start_index`
- `chunk.end_char` → `chunk.char_end_index`
- `chunk.text_content` → `chunk.text`
- `entity.entity_name` → `entity.canonical_name`

## Recommendations

1. **Fix ProcessingTaskMinimal.id type** - Change from `Optional[int]` to `Optional[UUID]`
2. **Add TextractJobMinimal model** for consistency
3. **Document the backward compatibility** properties in code comments where they're used
4. **Consider adding a schema validation test** that compares models to actual database schema

## Code Quality Assessment

The models.py file shows:
- Clear documentation and comments
- Proper use of Pydantic v2 ConfigDict
- Thoughtful backward compatibility
- Single source of truth approach
- Comprehensive ModelFactory pattern

Overall, the Pydantic models are well-designed and mostly correct, with only minor fixes needed.