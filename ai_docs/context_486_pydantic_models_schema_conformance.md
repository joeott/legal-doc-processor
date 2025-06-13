# Context 486: Pydantic Models Schema Conformance Analysis

## Date: January 9, 2025

## Executive Summary

This document compares the Pydantic models in `/opt/legal-doc-processor/scripts/models.py` with the schema mismatches identified in context_485 to verify complete conformance. The analysis shows that most models correctly match the database schema, with only one type mismatch that needs correction.

## Model Conformance Analysis

### 1. ProjectMinimal Model ✅ CORRECT

**Model Definition** (lines 227-236):
```python
class ProjectMinimal(BaseModel):
    id: int
    project_id: UUID
    name: str  # ✅ CORRECT - uses 'name' not 'project_name'
    active: bool = True
    created_at: Optional[datetime] = None
```

**Context_485 Issue**: Code was using `project_name` instead of `name`
**Model Status**: ✅ **CORRECT** - Model properly uses `name` field
**Database Schema Match**: ✅ Confirmed

### 2. SourceDocumentMinimal Model ✅ CORRECT

**Model Definition** (lines 41-82):
```python
class SourceDocumentMinimal(BaseModel):
    # ...
    status: str = ProcessingStatus.PENDING.value  # ✅ CORRECT - uses 'status'
    # ...
```

**Context_485 Issue**: Code was using `processing_status` instead of `status`
**Model Status**: ✅ **CORRECT** - Model properly uses `status` field (line 63)
**Database Schema Match**: ✅ Confirmed

### 3. DocumentChunkMinimal Model ✅ PERFECT

**Model Definition** (lines 83-122):
```python
class DocumentChunkMinimal(BaseModel):
    # Primary identifiers
    chunk_uuid: UUID  # ✅ CORRECT
    
    # Position tracking - MUST match database column names
    char_start_index: int  # Database column name  ✅ CORRECT
    char_end_index: int    # Database column name  ✅ CORRECT
    
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

**Model Status**: ✅ **PERFECT** - Model uses correct database column names AND provides backward compatibility
**Database Schema Match**: ✅ Confirmed with excellent backward compatibility pattern

### 4. EntityMentionMinimal Model ✅ CORRECT

**Model Definition** (lines 123-150):
```python
class EntityMentionMinimal(BaseModel):
    # Associations
    document_uuid: UUID
    chunk_uuid: UUID  # ✅ CORRECT - uses chunk_uuid not chunk_id
    chunk_fk_id: Optional[int] = None
```

**Context_485 Issue**: Code/cache keys were using `chunk_id` instead of `chunk_uuid`
**Model Status**: ✅ **CORRECT** - Model properly uses `chunk_uuid` (line 133)
**Database Schema Match**: ✅ Confirmed

### 5. CanonicalEntityMinimal Model ✅ PERFECT

**Model Definition** (lines 151-183):
```python
class CanonicalEntityMinimal(BaseModel):
    # Entity data - MUST use canonical_name to match database
    canonical_name: str  # Database column name  ✅ CORRECT
    
    # Backward compatibility for code expecting entity_name
    @property
    def entity_name(self) -> str:
        """Backward compatibility for code expecting entity_name"""
        return self.canonical_name
```

**Model Status**: ✅ **PERFECT** - Uses correct `canonical_name` with backward compatibility property
**Database Schema Match**: ✅ Confirmed

**Note**: Model correctly excludes `document_uuid` field which doesn't exist in the canonical_entities table

### 6. RelationshipStagingMinimal Model ✅ CORRECT

**Model Definition** (lines 185-207):
```python
class RelationshipStagingMinimal(BaseModel):
    # Primary identifier - NO relationship_uuid in database!
    id: Optional[int] = None  # ✅ CORRECT - no relationship_uuid
    
    # Evidence tracking
    source_chunk_uuid: Optional[UUID] = None  # ✅ CORRECT
```

**Model Status**: ✅ **CORRECT** - Properly excludes non-existent `relationship_uuid`
**Comment on line 189**: Explicitly documents "NO relationship_uuid in database!"
**Database Schema Match**: ✅ Confirmed

### 7. ProcessingTaskMinimal Model ❌ NEEDS FIX

**Model Definition** (lines 213-225):
```python
class ProcessingTaskMinimal(BaseModel):
    id: Optional[int] = None  # ❌ WRONG - should be UUID
    task_uuid: UUID
    document_uuid: UUID
```

**Context_485 Issue**: Database has `id` as UUID type, not int
**Model Status**: ❌ **NEEDS FIX** - Type mismatch on line 217
**Required Fix**:
```python
id: Optional[UUID] = None  # Fixed to match database
```

### 8. TextractJobMinimal Model ⚠️ MISSING

**Context_485 Issue**: References to `textract_jobs` table with `job_status` → `status` mismatch
**Model Status**: ⚠️ **MISSING** - No model exists for textract_jobs table
**Recommendation**: Create TextractJobMinimal model if needed

## Summary of Conformance

| Model | Field Issue from Context_485 | Model Status | Line Reference |
|-------|----------------------------|--------------|----------------|
| ProjectMinimal | `project_name` → `name` | ✅ CORRECT | Line 233: `name: str` |
| SourceDocumentMinimal | `processing_status` → `status` | ✅ CORRECT | Line 63: `status: str` |
| DocumentChunkMinimal | Column names | ✅ PERFECT | Lines 100-101: `char_start_index`, `char_end_index` |
| EntityMentionMinimal | `chunk_id` → `chunk_uuid` | ✅ CORRECT | Line 133: `chunk_uuid: UUID` |
| CanonicalEntityMinimal | Missing `document_uuid` | ✅ CORRECT | Properly excluded |
| RelationshipStagingMinimal | No `relationship_uuid` | ✅ CORRECT | Line 189: Documented |
| ProcessingTaskMinimal | `id` type mismatch | ❌ NEEDS FIX | Line 217: Should be UUID |
| TextractJobMinimal | N/A | ⚠️ MISSING | No model exists |

## Key Findings

### Strengths
1. **Excellent backward compatibility pattern** using `@property` decorators
2. **Clear documentation** of database constraints (e.g., line 189)
3. **Correct field naming** in 6 out of 7 existing models
4. **Proper type annotations** with Optional where appropriate

### Issues to Address
1. **ProcessingTaskMinimal.id** must be changed from `Optional[int]` to `Optional[UUID]`
2. **TextractJobMinimal** model should be created if textract_jobs table is used

### Code vs Model Mismatches
Most issues from context_485 are in the **code using the models** rather than the models themselves:
- SQL queries using wrong column names
- Cache keys using wrong field references  
- Function parameters expecting wrong field names

The models are generally well-designed and conform to the database schema, demonstrating that the "single source of truth" approach in models.py is working effectively.