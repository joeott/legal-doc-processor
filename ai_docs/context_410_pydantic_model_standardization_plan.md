# Context 410: Pydantic Model Standardization and UUID Consistency Plan

## Executive Summary

This plan addresses critical inconsistencies in Pydantic models and UUID handling across the legal document processing pipeline. The goal is to establish a SINGLE, SIMPLE, WORKING set of models that accurately reflect the database schema and ensure consistent UUID handling throughout the system.

## Current State Analysis

### Critical Issues Identified

1. **Multiple Model Definitions**
   - `scripts/models.py`: "Minimal" models (currently working)
   - `scripts/core/schemas.py`: Full models with aliases
   - `scripts/core/pdf_models.py`: PDF-specific models
   - Result: Confusion, type mismatches, and maintenance burden

2. **UUID Field Name Inconsistencies**
   - DB: `chunk_uuid` → Models: `chunk_id` and `chunk_uuid`
   - DB: `mention_uuid` → Models: `entity_mention_id` and `mention_uuid`
   - DB: `canonical_entity_uuid` → Models: `canonical_entity_id`, `resolved_canonical_id`
   - DB: `project_id` (UUID) → Models: confusingly named `project_id`

3. **UUID Type Handling Issues**
   - Celery tasks receive strings, models expect UUID objects
   - Inconsistent conversion at boundaries
   - Database operations sometimes get strings, sometimes UUID objects

4. **Database Column Name Mismatches**
   - DB: `char_start_index/char_end_index` → Models: `start_char/end_char`
   - DB: `text` → Models: sometimes `text`, sometimes `text_content`
   - DB: `entity_text` → Models: sometimes `text`, sometimes `entity_text`

## Proposed Solution: SIMPLEST Model That WORKS

### Core Principles

1. **Single Source of Truth**: Use ONLY the minimal models in `scripts/models.py`
2. **Match Database Exactly**: Field names must match database column names
3. **Explicit UUID Handling**: Clear conversion at Celery boundaries
4. **Remove Complexity**: No aliases, no multiple model sets

### Standardized Model Definitions

Based on the actual database schema, here are the corrected models:

```python
# Standard UUID type handling
from uuid import UUID
from typing import Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict

# Base configuration for all models
class MinimalBaseModel(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,  # For SQLAlchemy compatibility
        populate_by_name=True,  # Accept both field name and alias
        arbitrary_types_allowed=True
    )

# 1. Source Documents (matches DB exactly)
class SourceDocumentMinimal(MinimalBaseModel):
    # Primary keys
    id: Optional[int] = None
    document_uuid: UUID
    
    # Foreign keys
    project_uuid: Optional[UUID] = None
    project_fk_id: Optional[int] = None
    
    # File information
    file_name: str
    original_file_name: Optional[str] = None
    file_path: Optional[str] = None
    file_size_bytes: Optional[int] = None
    
    # S3 information
    s3_key: Optional[str] = None
    s3_bucket: Optional[str] = None
    s3_region: Optional[str] = None
    
    # Status fields
    status: str = "pending"
    celery_task_id: Optional[str] = None
    
    # OCR fields
    raw_extracted_text: Optional[str] = None
    ocr_completed_at: Optional[datetime] = None
    ocr_provider: Optional[str] = None
    textract_job_id: Optional[str] = None
    
    # Timestamps
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

# 2. Document Chunks (matches DB exactly)
class DocumentChunkMinimal(MinimalBaseModel):
    # Primary keys
    id: Optional[int] = None
    chunk_uuid: UUID
    
    # Foreign keys
    document_uuid: UUID
    document_fk_id: Optional[int] = None
    
    # Chunk data
    chunk_index: int
    text: str  # This is the main text field in DB
    char_start_index: int  # Match DB column name
    char_end_index: int    # Match DB column name
    
    # Timestamps
    created_at: Optional[datetime] = None

# 3. Entity Mentions (matches DB exactly)
class EntityMentionMinimal(MinimalBaseModel):
    # Primary keys
    id: Optional[int] = None
    mention_uuid: UUID
    
    # Foreign keys
    document_uuid: UUID
    chunk_uuid: UUID
    canonical_entity_uuid: Optional[UUID] = None
    
    # Entity data
    entity_text: str
    entity_type: str
    start_char: int
    end_char: int
    confidence_score: Optional[float] = 0.9
    
    # Timestamps
    created_at: Optional[datetime] = None

# 4. Canonical Entities (matches DB exactly)
class CanonicalEntityMinimal(MinimalBaseModel):
    # Primary keys
    id: Optional[int] = None
    canonical_entity_uuid: UUID
    
    # Entity data
    entity_type: str
    canonical_name: str
    mention_count: Optional[int] = 0
    confidence_score: Optional[float] = None
    
    # JSON fields
    aliases: Optional[Dict[str, Any]] = None
    properties: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    
    # Timestamps
    created_at: Optional[datetime] = None

# 5. Relationship Staging (matches DB exactly)
class RelationshipStagingMinimal(MinimalBaseModel):
    # Primary keys
    id: Optional[int] = None
    
    # Relationship data
    source_entity_uuid: UUID
    target_entity_uuid: UUID
    relationship_type: str
    confidence_score: Optional[float] = None
    source_chunk_uuid: Optional[UUID] = None
    evidence_text: Optional[str] = None
    
    # JSON fields
    properties: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    
    # Timestamps
    created_at: Optional[datetime] = None
```

## Implementation Tasks

### Phase 1: Model Consolidation (Priority: CRITICAL)

#### Task 1.1: Update models.py with Correct Field Names
**File**: `scripts/models.py`
**Changes**:
1. Update `DocumentChunkMinimal`:
   - Change `start_char` → `char_start_index`
   - Change `end_char` → `char_end_index`
   - Remove alias usage
2. Ensure all UUID fields are typed as `UUID` not `str`
3. Add missing `id` fields where needed

**Verification**:
```bash
# Test model instantiation
python3 -c "
from scripts.models import DocumentChunkMinimal
from uuid import uuid4
chunk = DocumentChunkMinimal(
    chunk_uuid=uuid4(),
    document_uuid=uuid4(),
    chunk_index=0,
    text='test',
    char_start_index=0,
    char_end_index=10
)
print('✓ Model instantiation successful')
print(chunk.model_dump())
"
```

#### Task 1.2: Remove Conflicting Models
**Files to Update**:
1. Delete or archive `scripts/core/schemas.py` (replace with models.py imports)
2. Delete or archive `scripts/core/pdf_models.py`
3. Update all imports to use `scripts.models`

**Verification**:
```bash
# Check for remaining imports
grep -r "from scripts.core.schemas import" scripts/
grep -r "from scripts.core.pdf_models import" scripts/
# Should return no results
```

### Phase 2: UUID Handling Standardization (Priority: HIGH)

#### Task 2.1: Fix Celery Task UUID Handling
**File**: `scripts/pdf_tasks.py`
**Pattern to Apply**:
```python
from uuid import UUID as UUID_TYPE

@app.task
def any_task(self, document_uuid: str, ...):
    # Convert at entry point
    document_uuid_obj = UUID_TYPE(document_uuid)
    
    # Use UUID object internally
    model = SomeModel(document_uuid=document_uuid_obj, ...)
    
    # Convert to string only for cache keys
    cache_key = f"doc:{str(document_uuid_obj)}"
```

**Specific Changes**:
1. `extract_text_from_document`: Convert document_uuid string to UUID object
2. `chunk_document_text`: Convert UUIDs before model instantiation
3. `extract_entities_from_chunks`: Convert chunk_uuid strings to UUID objects
4. `resolve_document_entities`: Handle UUID conversions for canonical entities

**Verification**:
```python
# Test UUID conversion
python3 -c "
from uuid import UUID
test_str = '550e8400-e29b-41d4-a716-446655440000'
uuid_obj = UUID(test_str)
print(f'String: {test_str}')
print(f'UUID: {uuid_obj}')
print(f'Back to string: {str(uuid_obj)}')
print('✓ UUID conversion working')
"
```

#### Task 2.2: Fix Database Operation UUID Handling
**Files**: `scripts/db.py`, `scripts/rds_utils.py`
**Changes**:
1. Ensure all database operations accept UUID objects
2. Let psycopg2 handle UUID to string conversion for PostgreSQL
3. Update type hints to reflect UUID usage

**Verification**:
```python
# Test database UUID handling
from scripts.db import DatabaseManager
from uuid import uuid4
db = DatabaseManager()
# Insert with UUID object
test_uuid = uuid4()
# Should work without explicit string conversion
```

### Phase 3: Field Name Alignment (Priority: HIGH)

#### Task 3.1: Update All References to Renamed Fields
**Global Search and Replace**:
1. `chunk.start_char` → `chunk.char_start_index`
2. `chunk.end_char` → `chunk.char_end_index`
3. `chunk_id` → `chunk_uuid` (for UUID fields)
4. `entity_mention_id` → `mention_uuid`
5. `canonical_entity_id` → `canonical_entity_uuid`
6. `resolved_canonical_id` → `canonical_entity_uuid`

**Files to Update**:
- `scripts/pdf_tasks.py`
- `scripts/entity_service.py`
- `scripts/graph_service.py`
- `scripts/chunking_utils.py`

**Verification**:
```bash
# Check for old field names
grep -r "start_char" scripts/ | grep -v "char_start_index"
grep -r "chunk_id" scripts/ | grep -v "chunk_uuid"
# Should return minimal results
```

### Phase 4: Service Layer Updates (Priority: MEDIUM)

#### Task 4.1: Update Entity Service
**File**: `scripts/entity_service.py`
**Changes**:
1. Use consistent UUID handling pattern
2. Update field references to match new models
3. Remove any schema/pdf_models imports

#### Task 4.2: Update Graph Service
**File**: `scripts/graph_service.py`
**Changes**:
1. Convert string UUIDs to UUID objects for RelationshipStagingMinimal
2. Update field references

### Phase 5: Testing and Validation (Priority: HIGH)

#### Task 5.1: Create Model Validation Tests
**New File**: `scripts/test_model_consistency.py`
```python
#!/usr/bin/env python3
"""Test model consistency with database schema"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.models import *
from scripts.db import DatabaseManager
from sqlalchemy import text
from uuid import uuid4

def test_model_db_consistency():
    """Verify models match database schema"""
    db = DatabaseManager()
    session = next(db.get_session())
    
    # Test each model against its table
    tests = [
        ("source_documents", SourceDocumentMinimal),
        ("document_chunks", DocumentChunkMinimal),
        ("entity_mentions", EntityMentionMinimal),
        ("canonical_entities", CanonicalEntityMinimal),
        ("relationship_staging", RelationshipStagingMinimal)
    ]
    
    for table_name, model_class in tests:
        print(f"\nTesting {model_class.__name__} against {table_name}")
        
        # Get DB columns
        result = session.execute(text(f"""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = '{table_name}'
        """)).fetchall()
        
        db_columns = {row.column_name for row in result}
        model_fields = set(model_class.model_fields.keys())
        
        # Check for mismatches
        only_in_db = db_columns - model_fields
        only_in_model = model_fields - db_columns
        
        if only_in_db:
            print(f"  ⚠️  In DB but not model: {only_in_db}")
        if only_in_model:
            print(f"  ⚠️  In model but not DB: {only_in_model}")
        if not (only_in_db or only_in_model):
            print(f"  ✅ Model matches database perfectly")

if __name__ == "__main__":
    test_model_db_consistency()
```

#### Task 5.2: End-to-End UUID Flow Test
**New File**: `scripts/test_uuid_flow.py`
```python
#!/usr/bin/env python3
"""Test UUID handling through the pipeline"""

from uuid import uuid4, UUID
from scripts.models import *

def test_uuid_flow():
    """Test UUID handling at each stage"""
    
    # 1. Document creation
    doc_uuid = uuid4()
    doc = SourceDocumentMinimal(
        document_uuid=doc_uuid,
        file_name="test.pdf",
        status="pending"
    )
    assert isinstance(doc.document_uuid, UUID)
    print("✅ Document model UUID handling correct")
    
    # 2. Celery serialization simulation
    doc_uuid_str = str(doc_uuid)
    doc_uuid_restored = UUID(doc_uuid_str)
    assert doc_uuid == doc_uuid_restored
    print("✅ UUID string round-trip successful")
    
    # 3. Chunk creation
    chunk_uuid = uuid4()
    chunk = DocumentChunkMinimal(
        chunk_uuid=chunk_uuid,
        document_uuid=doc_uuid,
        chunk_index=0,
        text="Test chunk",
        char_start_index=0,
        char_end_index=10
    )
    assert isinstance(chunk.chunk_uuid, UUID)
    assert isinstance(chunk.document_uuid, UUID)
    print("✅ Chunk model UUID handling correct")
    
    # 4. Entity mention
    mention = EntityMentionMinimal(
        mention_uuid=uuid4(),
        chunk_uuid=chunk_uuid,
        document_uuid=doc_uuid,
        entity_text="Test Entity",
        entity_type="PERSON",
        start_char=0,
        end_char=11
    )
    assert isinstance(mention.mention_uuid, UUID)
    print("✅ Entity mention UUID handling correct")
    
    print("\n✅ All UUID handling tests passed!")

if __name__ == "__main__":
    test_uuid_flow()
```

### Phase 6: Deployment Safety (Priority: CRITICAL)

#### Task 6.1: Create Migration Script
**New File**: `scripts/migrate_to_standard_models.py`
```python
#!/usr/bin/env python3
"""Safely migrate to standardized models"""

import os
import sys
import shutil
from datetime import datetime

def backup_current_models():
    """Backup current model files"""
    backup_dir = f"model_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    os.makedirs(backup_dir, exist_ok=True)
    
    files_to_backup = [
        "scripts/models.py",
        "scripts/core/schemas.py",
        "scripts/core/pdf_models.py"
    ]
    
    for file_path in files_to_backup:
        if os.path.exists(file_path):
            shutil.copy2(file_path, backup_dir)
            print(f"✅ Backed up {file_path}")
    
    return backup_dir

def update_imports():
    """Update all imports to use standardized models"""
    # Implementation would scan and update imports
    pass

if __name__ == "__main__":
    print("Starting model standardization migration...")
    backup_dir = backup_current_models()
    print(f"Backups saved to: {backup_dir}")
    # Continue with migration...
```

## Success Criteria

1. **Model Consistency**
   - [ ] All models in `scripts/models.py` match database schema exactly
   - [ ] No conflicting model definitions exist
   - [ ] All imports use `scripts.models`

2. **UUID Handling**
   - [ ] All Celery tasks convert string UUIDs to objects at entry
   - [ ] All models use UUID type for UUID fields
   - [ ] Database operations handle UUID objects correctly

3. **Field Names**
   - [ ] All field names match database column names
   - [ ] No aliases needed (except for legacy compatibility)
   - [ ] Consistent naming throughout codebase

4. **Testing**
   - [ ] Model validation tests pass
   - [ ] UUID flow tests pass
   - [ ] End-to-end document processing works

## Rollback Plan

If issues arise:
1. Restore from `model_backup_*` directory
2. Revert import changes
3. Document specific failures for targeted fixes

## Implementation Order

1. **Day 1**: Model consolidation and testing
2. **Day 2**: UUID handling fixes
3. **Day 3**: Field name alignment and service updates
4. **Day 4**: Comprehensive testing and validation
5. **Day 5**: Production deployment with monitoring

## Expected Outcomes

- **Simplified Codebase**: Single set of models reduces confusion
- **Type Safety**: Proper UUID handling prevents runtime errors
- **Maintainability**: Database-matching models ease debugging
- **Performance**: Fewer conversions and validations needed

## Current State Verification Results

Running verification script shows:
1. **Model Import Conflicts**: 8 minimal model imports, 7 core schema imports, 6 PDF model imports
2. **Field Name Issues**: `start_char/end_char` used instead of `char_start_index/char_end_index`
3. **UUID String Usage**: 27 string UUID cache keys, 28 UUID-to-string conversions in tasks
4. **Correct Usage**: Models correctly use `chunk_uuid`, `mention_uuid`, `canonical_entity_uuid`

## Quick Fix Priority

For immediate stability:
1. Update `DocumentChunkMinimal` to use `char_start_index` and `char_end_index`
2. Fix `CanonicalEntityMinimal` to match database:
   - Remove: `entity_names`, `first_seen_date`, `last_seen_date`, `document_count`
   - Add: `resolution_method`, `aliases`, `properties`, `updated_at`
3. Add UUID type conversion at Celery task entry points
4. Remove imports of `core.schemas` and `core.pdf_models`
5. Ensure all database operations use the minimal models

## Critical Model Fixes Needed

### DocumentChunkMinimal
```python
# Change from:
start_char: int
end_char: int

# To:
char_start_index: int
char_end_index: int
```

### CanonicalEntityMinimal
```python
# Current (incorrect):
entity_names: List[str]
first_seen_date: datetime
last_seen_date: datetime
document_count: int

# Should be (to match DB):
resolution_method: Optional[str] = None
aliases: Optional[Dict[str, Any]] = None
properties: Optional[Dict[str, Any]] = None
confidence_score: Optional[float] = None
updated_at: Optional[datetime] = None
```

## Conclusion

This plan provides a clear path to standardize Pydantic models and UUID handling. The focus on the SIMPLEST model that WORKS will dramatically reduce complexity while improving reliability. By matching the database schema exactly and handling UUIDs consistently, we eliminate a major source of errors in the system.