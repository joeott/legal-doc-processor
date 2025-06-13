# Context 416: Pydantic Models and Database Schema Alignment Analysis

## Executive Summary

A critical analysis of the Pydantic model definitions reveals significant inconsistencies between different model files and misalignments with the actual database schema. The codebase currently has multiple competing model definitions that create confusion and potential runtime errors. This analysis identifies specific discrepancies and recommends a path to the simplest possible working model definitions.

## Current State of Pydantic Models

### 1. Multiple Model Definitions

The codebase contains at least three sets of model definitions:

1. **`/scripts/models.py`** - Claims to be "the single source of truth derived from working code"
2. **`/scripts/core/models_minimal.py`** - Another set of minimal models with different field names
3. **`/scripts/core/schemas.py`** - A deprecated shim file with stub classes lacking proper Pydantic definitions

### 2. Configuration and Model Selection

- `USE_MINIMAL_MODELS=true` is set in `.env`, forcing use of minimal models
- `scripts/core/model_factory.py` attempts to switch between full and minimal models
- Full models from `schemas.py` are just empty stub classes, causing Pydantic schema generation errors

## Critical Discrepancies Found

### 1. Document Chunks Table

**Database Schema:**
```sql
-- The database has DUPLICATE columns for character positions:
char_start_index: INTEGER NULL
char_end_index: INTEGER NULL
start_char_index: INTEGER NULL  -- Duplicate!
end_char_index: INTEGER NULL    -- Duplicate!
```

**Model Conflicts:**
- `scripts/models.py` uses: `char_start_index`, `char_end_index`
- `scripts/core/models_minimal.py` uses: `start_char`, `end_char`
- **Neither matches the database exactly!**

### 2. Canonical Entities Table

**Database Schema:**
```sql
canonical_name: TEXT NOT NULL  -- Database uses this
```

**Model Conflicts:**
- `scripts/models.py` uses: `canonical_name` ✓ (Correct)
- `scripts/core/models_minimal.py` uses: `entity_name` ✗ (Wrong)

### 3. Entity Mentions Table

**Database Schema:**
```sql
start_char: INTEGER NULL
end_char: INTEGER NULL
```

**Model Status:**
- Both model files correctly use `start_char` and `end_char` ✓

### 4. Source Documents Table

**Database Schema:**
The database has 45+ columns including many legacy/unused fields:
- Multiple status fields: `status`, `celery_status`, `initial_processing_status`
- Duplicate text fields: `raw_extracted_text`, `markdown_text`, `cleaned_text`
- Extensive Textract tracking fields
- Many nullable fields that seem unused

**Model Issues:**
- Models only include subset of fields (which is good)
- But field selection seems arbitrary rather than based on actual usage

### 5. Relationship Staging Table

**Database Schema:**
```sql
-- Note: No relationship_uuid in database!
id: INTEGER NOT NULL
source_entity_uuid: UUID NULL
target_entity_uuid: UUID NULL
relationship_type: TEXT NOT NULL
```

**Model Issues:**
- `scripts/core/models_minimal.py` includes `relationship_uuid` which doesn't exist in DB
- `scripts/models.py` correctly omits this field ✓

## Root Causes of Issues

1. **Historical Evolution**: The database schema has accumulated fields over time without cleanup
2. **Multiple Refactoring Attempts**: Different developers created different "minimal" models
3. **Lack of Single Source of Truth**: No clear ownership of model definitions
4. **Incomplete Migration**: The move from full to minimal models was never completed
5. **No Validation**: Models aren't validated against actual database schema

## Recommendations for Simplest Working Models

### 1. Consolidate to Single Model File

Delete all model files except `/scripts/models.py` and fix the issues there:

```python
# Fix for DocumentChunkMinimal
class DocumentChunkMinimal(BaseModel):
    # Use the non-duplicate columns from database
    char_start_index: int  # Keep these as they appear first in schema
    char_end_index: int
    
    # Add properties for backward compatibility
    @property
    def start_char(self) -> int:
        return self.char_start_index
    
    @property  
    def end_char(self) -> int:
        return self.char_end_index
```

### 2. Remove Unused Fields

The database has many unused columns. The models should only include fields that are:
- Actually used in the codebase
- Required for the pipeline to function
- Necessary for data integrity

### 3. Fix Import Paths

Update all imports to use the single model file:
```python
from scripts.models import (
    SourceDocumentMinimal,
    DocumentChunkMinimal,
    EntityMentionMinimal,
    CanonicalEntityMinimal,
    RelationshipStagingMinimal
)
```

### 4. Add Database Validation

Create a validation script that:
- Queries actual database schema
- Compares with Pydantic models
- Reports any mismatches
- Runs as part of CI/CD

### 5. Document Field Usage

For each model field, document:
- Is it required by the pipeline?
- Which components use it?
- Can it be safely removed?

## Immediate Actions Required

1. **Fix Critical Mismatches**:
   - Update `DocumentChunkMinimal` to use `char_start_index`/`char_end_index`
   - Update `CanonicalEntityMinimal` in core/models_minimal.py to use `canonical_name`
   - Remove `relationship_uuid` from `RelationshipStagingMinimal`

2. **Delete Redundant Files**:
   - Remove `/scripts/core/schemas.py` (just causes errors)
   - Remove `/scripts/core/models_minimal.py` (duplicates main models)
   - Update `model_factory.py` to only use `/scripts/models.py`

3. **Clean Up Imports**:
   - Fix `cache_models.py` circular import issue
   - Update all files importing from `schemas.py`

## Verification Queries

To verify model alignment, run these queries:

```sql
-- Check which char_index columns have data
SELECT 
    COUNT(*) as total_rows,
    COUNT(char_start_index) as has_char_start_index,
    COUNT(start_char_index) as has_start_char_index,
    COUNT(char_end_index) as has_char_end_index,
    COUNT(end_char_index) as has_end_char_index
FROM document_chunks;

-- Check canonical entity field usage
SELECT COUNT(*) as total, 
       COUNT(canonical_name) as has_canonical_name
FROM canonical_entities;

-- Check relationship staging
SELECT COUNT(*) FROM relationship_staging;
```

## Conclusion

The current state of Pydantic models is a significant impediment to system reliability. Multiple competing definitions, misaligned field names, and circular imports create a fragile foundation. By consolidating to a single, validated set of minimal models that exactly match the database schema, we can eliminate a major source of errors and confusion.

The principle should be: **One model file, one source of truth, validated against the database.**