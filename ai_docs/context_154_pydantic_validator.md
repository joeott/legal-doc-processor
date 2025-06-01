# Context 154: Pydantic Validation Fixes - Comprehensive Plan

## Overview

This document outlines the critical fixes needed to complete the Pydantic v2 migration and ensure full type safety throughout the legal document processing pipeline. Based on the comprehensive review conducted on January 28, 2025, approximately 80% of the Pydantic integration is complete, but critical issues remain that must be addressed for production readiness.

## Priority 1: Critical Pydantic v2 Migration Fixes

### 1.1 Update @validator to @field_validator (45 instances)

**Files affected:**
- `scripts/core/schemas.py` (15 instances)
- `scripts/core/processing_models.py` (23 instances)
- `scripts/core/cache_models.py` (1 instance)
- `scripts/core/task_models.py` (6 instances)

**Fix pattern:**
```python
# OLD (Pydantic v1)
@validator('field_name')
def validate_field(cls, v):
    return v

# NEW (Pydantic v2)
@field_validator('field_name')
@classmethod
def validate_field(cls, v):
    return v

# For pre=True validators
# OLD
@validator('field_name', pre=True)
def validate_field(cls, v):
    return v

# NEW
@field_validator('field_name', mode='before')
@classmethod
def validate_field(cls, v):
    return v
```

### 1.2 Update .dict() to .model_dump() (5 instances)

**Files affected:**
- `scripts/structured_extraction.py` (lines 550-551)
- `scripts/image_processing.py` (caching logic)
- Various other locations

**Fix pattern:**
```python
# OLD
model.dict()
model.dict(exclude_none=True)

# NEW
model.model_dump()
model.model_dump(exclude_none=True)
```

### 1.3 Update .json() to .model_dump_json() (3 instances)

**Files affected:**
- Various model serialization locations

**Fix pattern:**
```python
# OLD
model.json()

# NEW
model.model_dump_json()
```

## Priority 2: Type Safety Violations

### 2.1 Fix SupabaseManager Return Type Annotations

**File:** `scripts/supabase_utils.py`

**Issue:** `get_or_create_project()` returns `None` on validation failure but type annotation says `ProjectModel`

**Fix:**
```python
# Line 187 - Change return type
def get_or_create_project(self, project_name: str) -> Tuple[Optional[ProjectModel], int, str]:
    """Get or create project with Pydantic model validation"""
    try:
        # ... existing code ...
        if validation fails:
            return (None, 0, "")  # This matches Optional[ProjectModel]
    except Exception as e:
        logger.error(f"Error in get_or_create_project: {e}")
        return (None, 0, "")
```

### 2.2 Add Model Validation to Update Methods

**File:** `scripts/supabase_utils.py`

**Add validation before updates:**
```python
def update_source_document_text(self, document_uuid: str, extracted_text: str, 
                                ocr_metadata: Optional[Dict[str, Any]] = None) -> bool:
    """Update document with validation"""
    # Validate the update data against the model
    try:
        # Create partial model to validate the update fields
        update_data = {
            'raw_extracted_text': extracted_text,
            'ocr_metadata_json': ocr_metadata or {}
        }
        # Validate against SourceDocumentModel fields
        SourceDocumentModel.model_validate_partial(update_data)
    except ValidationError as e:
        logger.error(f"Invalid update data: {e}")
        return False
    
    # Proceed with update...
```

## Priority 3: Integration Issues

### 3.1 Fix OCR Cache Handling

**File:** `scripts/celery_tasks/ocr_tasks.py`

**Issue:** Lines 130-132, 334-335, 456-458 use dictionary access on cached results

**Fix:**
```python
# OLD (treating as dictionary)
cached_result = cache_manager.get_cached_ocr_result(cache_key)
if cached_result:
    extracted_text = cached_result.get('extracted_text', '')
    metadata = cached_result.get('metadata', {})

# NEW (treating as Pydantic model)
from scripts.core.cache_models import CachedOCRResultModel

cached_result = cache_manager.get_cached_model(cache_key, CachedOCRResultModel)
if cached_result and cached_result.is_valid():
    extracted_text = cached_result.result.extracted_text
    metadata = cached_result.result.metadata
```

### 3.2 Fix Entity Tasks Result Handling

**File:** `scripts/celery_tasks/entity_tasks.py`

**Issue:** Line 158 expects list but gets EntityExtractionResultModel

**Fix:**
```python
# OLD
for mention_attrs in mentions_in_chunk:
    # process mention

# NEW
result = extract_entities_from_chunk(chunk_text, chunk_id=chunk_index, db_manager=self.db_manager)
if result.status == ProcessingResultStatus.SUCCESS:
    mentions_in_chunk = result.entities
    for mention_attrs in mentions_in_chunk:
        # process mention
else:
    logger.warning(f"Entity extraction failed for chunk {chunk_index}: {result.error_message}")
    mentions_in_chunk = []
```

### 3.3 Fix Image Processing Method Name

**File:** `scripts/image_processing.py`

**Issue:** Line 190 calls `_create_image_processing_result` but method is `_structure_processing_result`

**Fix:**
```python
# Line 190
# OLD
result = self._create_image_processing_result(...)

# NEW
result = self._structure_processing_result(...)

# Also ensure the method returns ImageProcessingResultModel directly:
def _structure_processing_result(self, ...) -> ImageProcessingResultModel:
    # ... existing logic ...
    return ImageProcessingResultModel(
        status=status,
        results=results,
        # ... other fields ...
    )
```

## Priority 4: Missing Pydantic Integration

### 4.1 Update entity_resolution_enhanced.py

**File:** `scripts/entity_resolution_enhanced.py`

**Issue:** Completely missing Pydantic model usage

**Fix:**
```python
# Add imports
from scripts.core.processing_models import (
    EntityResolutionResultModel, CanonicalEntity, ProcessingResultStatus
)

# Update return type
def enhanced_resolve_entities(
    document_uuid: str,
    entity_mentions: List[Dict[str, Any]]
) -> EntityResolutionResultModel:
    """Enhanced entity resolution with Pydantic models"""
    
    try:
        # ... existing resolution logic ...
        
        # Convert results to Pydantic models
        canonical_entities = []
        for entity_data in resolved_entities:
            canonical = CanonicalEntity(
                canonical_entity_id=entity_data['id'],
                canonical_name=entity_data['name'],
                entity_type=entity_data['type'],
                # ... other fields ...
            )
            canonical_entities.append(canonical)
        
        return EntityResolutionResultModel(
            status=ProcessingResultStatus.SUCCESS,
            canonical_entities=canonical_entities,
            resolution_metrics={
                'total_mentions': len(entity_mentions),
                'unique_entities': len(canonical_entities),
                'resolution_ratio': len(canonical_entities) / len(entity_mentions)
            }
        )
    except Exception as e:
        return EntityResolutionResultModel(
            status=ProcessingResultStatus.FAILED,
            canonical_entities=[],
            error_message=str(e)
        )
```

## Priority 5: Import Path Fixes

### 5.1 Fix Missing Module Prefixes

**Files affected:**
- `scripts/celery_tasks/ocr_tasks.py` (line 126)
- Various other import statements

**Fix pattern:**
```python
# OLD
from celery_tasks.task_utils import update_status_on_cache_hit

# NEW
from scripts.celery_tasks.task_utils import update_status_on_cache_hit
```

## Implementation Strategy

### Phase 1: Automated Fixes (1-2 hours)
1. Use regex replacement for @validator → @field_validator
2. Use regex replacement for .dict() → .model_dump()
3. Use regex replacement for .json() → .model_dump_json()
4. Fix import paths with scripts. prefix

### Phase 2: Manual Integration Fixes (2-3 hours)
1. Fix OCR cache handling
2. Fix entity tasks result handling
3. Fix image processing method name
4. Update entity_resolution_enhanced.py

### Phase 3: Type Safety Fixes (1-2 hours)
1. Fix return type annotations
2. Add validation to update methods
3. Test all type contracts

### Phase 4: Verification (1 hour)
1. Run all imports test
2. Run unit tests
3. Test end-to-end pipeline
4. Verify Pydantic v2 compliance

## Validation Script

Create a script to verify all fixes:

```python
#!/usr/bin/env python3
"""Validate Pydantic v2 migration fixes"""

import subprocess
import re
from pathlib import Path

def check_validator_usage():
    """Check for old @validator usage"""
    cmd = ['grep', '-r', '@validator(', 'scripts/', '--include=*.py']
    result = subprocess.run(cmd, capture_output=True, text=True)
    return len(result.stdout.strip().split('\n')) if result.stdout else 0

def check_dict_usage():
    """Check for .dict() usage"""
    cmd = ['grep', '-r', '.dict()', 'scripts/', '--include=*.py']
    result = subprocess.run(cmd, capture_output=True, text=True)
    # Filter out false positives
    lines = [l for l in result.stdout.split('\n') if '__dict__' not in l]
    return len(lines)

def check_imports():
    """Test all imports"""
    test_imports = [
        "from scripts.core.schemas import *",
        "from scripts.core.processing_models import *",
        "from scripts.celery_tasks.ocr_tasks import process_ocr",
        "from scripts.entity_extraction import extract_entities_from_chunk",
        "from scripts.entity_resolution_enhanced import enhanced_resolve_entities"
    ]
    
    for imp in test_imports:
        try:
            exec(imp)
            print(f"✅ {imp}")
        except ImportError as e:
            print(f"❌ {imp}: {e}")
            return False
    return True

if __name__ == "__main__":
    print("Pydantic v2 Migration Validation")
    print("=" * 50)
    
    validators = check_validator_usage()
    print(f"@validator usage: {validators} (should be 0)")
    
    dicts = check_dict_usage()
    print(f".dict() usage: {dicts} (should be 0)")
    
    print("\nImport tests:")
    imports_ok = check_imports()
    
    if validators == 0 and dicts == 0 and imports_ok:
        print("\n✅ All Pydantic v2 migration fixes complete!")
    else:
        print("\n❌ Migration fixes incomplete")
```

## Success Criteria

1. **Zero Pydantic v1 syntax** remaining in codebase
2. **All imports work** without errors
3. **Type safety maintained** throughout pipeline
4. **All tests pass** with Pydantic v2
5. **Cache operations** use model validation
6. **Entity pipeline** handles models correctly
7. **No runtime ValidationErrors** in normal operation

## Risk Mitigation

1. **Backup current code** before applying fixes
2. **Test each fix incrementally** 
3. **Run integration tests** after each phase
4. **Monitor logs** for new validation errors
5. **Have rollback plan** if issues arise

This comprehensive fix plan addresses all identified issues and ensures the Pydantic v2 migration is completed successfully with full type safety.