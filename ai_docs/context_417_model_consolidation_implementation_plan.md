# Context 417: Model Consolidation Implementation Plan

## Executive Summary

This document provides a systematic implementation plan for consolidating all Pydantic models into a single, minimal, database-conformant definition file. The plan follows a test-driven approach using actual production data to determine required fields and ensure the simplest possible working models.

## Implementation Philosophy

1. **Minimize First**: Remove all unnecessary fields
2. **Conform to Database**: Match actual column names and types
3. **Conform Scripts**: Update scripts to use consolidated models
4. **Test Continuously**: Verify each change with production data

## Phase 1: Field Usage Analysis (2 hours)

### 1.1 Analyze Core Script Usage

**Scripts to Analyze:**
- `pdf_tasks.py` - Core processing tasks
- `textract_utils.py` - OCR operations
- `entity_service.py` - Entity extraction
- `chunking_utils.py` - Text chunking
- `intake_service.py` - Document creation
- `batch_processor.py` - Batch operations

**Verification Script:**
```python
# analyze_field_usage.py
import re
from pathlib import Path

scripts = ['pdf_tasks.py', 'textract_utils.py', 'entity_service.py', 
           'chunking_utils.py', 'intake_service.py', 'batch_processor.py']

field_usage = {}
for script in scripts:
    with open(f'/opt/legal-doc-processor/scripts/{script}', 'r') as f:
        content = f.read()
        # Find all field accesses
        matches = re.findall(r'\.(\w+)', content)
        field_usage[script] = set(matches)

# Report findings
print("FIELD USAGE BY SCRIPT:")
for script, fields in field_usage.items():
    print(f"\n{script}:")
    for field in sorted(fields):
        print(f"  - {field}")
```

### 1.2 Database Column Usage Analysis

**Query to Run:**
```sql
-- Check which columns have data
SELECT 
    'source_documents' as table_name,
    COUNT(*) as total_rows,
    COUNT(document_uuid) as has_document_uuid,
    COUNT(file_name) as has_file_name,
    COUNT(original_file_name) as has_original_file_name,
    COUNT(s3_key) as has_s3_key,
    COUNT(status) as has_status,
    COUNT(raw_extracted_text) as has_raw_text,
    COUNT(textract_job_id) as has_textract_job
FROM source_documents
WHERE created_at > NOW() - INTERVAL '30 days';
```

**Success Criteria:**
- Identified all fields actually used in production code
- Documented which database columns contain data
- Created matrix of field usage

## Phase 2: Model Consolidation (3 hours)

### 2.1 Create Consolidated Model File

**Location:** `/opt/legal-doc-processor/scripts/models_consolidated.py`

**Structure:**
```python
"""
Consolidated minimal models for legal document processing.
Single source of truth for all Pydantic models.
"""

from datetime import datetime
from typing import Optional, Dict, Any, List
from uuid import UUID
from enum import Enum
from pydantic import BaseModel, Field, ConfigDict

# Enums (keep existing)
class ProcessingStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing" 
    COMPLETED = "completed"
    FAILED = "failed"

# Models with ONLY required fields
class SourceDocumentMinimal(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    # Required for creation
    document_uuid: UUID
    project_fk_id: int
    original_file_name: str
    s3_bucket: str
    s3_key: str
    status: str = "pending"
    
    # Required for processing
    id: Optional[int] = None
    raw_extracted_text: Optional[str] = None
    textract_job_id: Optional[str] = None
    ocr_completed_at: Optional[datetime] = None
    
    # Timestamps
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
```

### 2.2 Fix Database Column Mismatches

**Critical Fixes:**
1. **DocumentChunkMinimal**: Use `char_start_index` and `char_end_index` (not `start_char`)
2. **CanonicalEntityMinimal**: Use `canonical_name` (not `entity_name`)
3. **RelationshipStagingMinimal**: Remove `relationship_uuid` (doesn't exist in DB)

**Backward Compatibility Properties:**
```python
class DocumentChunkMinimal(BaseModel):
    char_start_index: int
    char_end_index: int
    
    # Backward compatibility
    @property
    def start_char(self) -> int:
        return self.char_start_index
        
    @property
    def end_char(self) -> int:
        return self.char_end_index
```

### 2.3 Delete Redundant Files

**Files to Remove:**
- `/scripts/core/schemas.py` - Just causes errors
- `/scripts/core/models_minimal.py` - Duplicate definitions
- `/scripts/core/cache_models.py` - Circular import issues

**Update model_factory.py:**
```python
# Simplified to use only consolidated models
from scripts.models_consolidated import (
    SourceDocumentMinimal,
    DocumentChunkMinimal,
    EntityMentionMinimal,
    CanonicalEntityMinimal,
    RelationshipStagingMinimal
)

def get_source_document_model():
    return SourceDocumentMinimal
# etc...
```

**Success Criteria:**
- Single model file created with minimal fields
- All database column names match exactly
- Backward compatibility maintained
- No circular imports

## Phase 3: Import Updates (2 hours)

### 3.1 Update All Import Statements

**Search and Replace:**
```bash
# Find all model imports
grep -r "from scripts.core.schemas import" scripts/
grep -r "from scripts.core.models_minimal import" scripts/
grep -r "from scripts.models import" scripts/

# Update to use consolidated models
# FROM: from scripts.core.schemas import SourceDocumentModel
# TO: from scripts.models_consolidated import SourceDocumentMinimal
```

### 3.2 Fix Specific Files

**Priority Files to Update:**
1. `db.py` - Database manager
2. `pdf_tasks.py` - Core processing
3. `entity_service.py` - Entity operations
4. `batch_processor.py` - Batch operations
5. `intake_service.py` - Document intake

**Success Criteria:**
- All imports updated
- No import errors
- Code runs without model-related exceptions

## Phase 4: Tiered Testing (4 hours)

### 4.1 Test Infrastructure (Tier 1)

**Test Script:**
```python
# test_tier1_models.py
import sys
sys.path.insert(0, '/opt/legal-doc-processor')

# Test basic imports
try:
    from scripts.models_consolidated import (
        SourceDocumentMinimal,
        DocumentChunkMinimal,
        EntityMentionMinimal,
        CanonicalEntityMinimal,
        RelationshipStagingMinimal
    )
    print("✅ Model imports successful")
except Exception as e:
    print(f"❌ Import failed: {e}")
    sys.exit(1)

# Test model creation
try:
    doc = SourceDocumentMinimal(
        document_uuid="550e8400-e29b-41d4-a716-446655440000",
        project_fk_id=1,
        original_file_name="test.pdf",
        s3_bucket="test-bucket",
        s3_key="test/key.pdf"
    )
    print("✅ Model instantiation successful")
except Exception as e:
    print(f"❌ Model creation failed: {e}")
    sys.exit(1)

# Test database roundtrip
from scripts.db import DatabaseManager
db = DatabaseManager(validate_conformance=False)
session = next(db.get_session())
# ... test database operations
```

### 4.2 Single Document Processing (Tier 1 Continued)

**Use Existing Test Document:**
- File: `input_docs/Paul, Michael (Acuity)/Paul, Michael - Lora Prop Disclosure Stmt 10-21-24.pdf`
- Project: TEST_TIER1_SINGLE_DOC

**Test Steps:**
1. Create document record using new models
2. Submit for OCR processing
3. Verify text extraction
4. Test chunking
5. Test entity extraction
6. Verify all fields populated correctly

**Success Criteria:**
- Document processes through entire pipeline
- All database fields populated correctly
- No model-related errors

### 4.3 Batch Processing Test (Tier 2)

**Test with 5 Documents:**
- Use Paul, Michael documents from `input_docs/`
- Process as batch
- Verify cross-document entity resolution

**Success Criteria:**
- Batch processing works
- Entity resolution across documents
- Performance acceptable

## Phase 5: Validation and Cleanup (1 hour)

### 5.1 Database Validation Script

```python
# validate_models_db_alignment.py
"""Validate that models match database schema exactly"""

from sqlalchemy import inspect, create_engine
from scripts.config import get_database_url
from scripts.models_consolidated import (
    SourceDocumentMinimal,
    DocumentChunkMinimal,
    # ... all models
)

engine = create_engine(get_database_url())
inspector = inspect(engine)

# For each model, verify columns match
models_to_tables = {
    SourceDocumentMinimal: 'source_documents',
    DocumentChunkMinimal: 'document_chunks',
    # ...
}

for model, table in models_to_tables.items():
    print(f"\nValidating {model.__name__} against {table}")
    
    # Get model fields
    model_fields = set(model.model_fields.keys())
    
    # Get database columns
    db_columns = {col['name'] for col in inspector.get_columns(table)}
    
    # Check for mismatches
    in_model_not_db = model_fields - db_columns
    in_db_not_model = db_columns - model_fields
    
    if in_model_not_db:
        print(f"  ❌ Fields in model but not database: {in_model_not_db}")
    if len(in_db_not_model) > 10:  # Many optional fields expected
        print(f"  ℹ️  Database has {len(in_db_not_model)} additional columns (expected)")
    
    print(f"  ✅ Model has {len(model_fields)} fields, DB has {len(db_columns)} columns")
```

### 5.2 Performance Testing

**Measure Impact:**
- Model instantiation speed
- Memory usage
- Database query performance

**Success Criteria:**
- No performance degradation
- Reduced memory usage (fewer fields)
- Faster model operations

## Phase 6: Documentation and Rollout (1 hour)

### 6.1 Update Documentation

**Files to Update:**
- `CLAUDE.md` - Update model guidance
- `README.md` - Update import examples
- Create migration guide for any breaking changes

### 6.2 Staged Rollout

**Step 1:** Test in development
**Step 2:** Process test batch
**Step 3:** Process full production batch
**Step 4:** Monitor for 24 hours
**Step 5:** Remove old model files

## Verification Criteria Summary

### Phase 1 Success:
- [ ] All field usage documented
- [ ] Database column usage analyzed
- [ ] Required fields identified

### Phase 2 Success:
- [ ] Single consolidated model file created
- [ ] All column names match database
- [ ] Backward compatibility maintained
- [ ] No circular imports

### Phase 3 Success:
- [ ] All imports updated
- [ ] No import errors
- [ ] Code runs without exceptions

### Phase 4 Success:
- [ ] Tier 1: Single document processes
- [ ] Tier 2: Batch processing works
- [ ] Tier 3: Full pipeline validated

### Phase 5 Success:
- [ ] Models validated against database
- [ ] Performance acceptable
- [ ] No regressions

### Phase 6 Success:
- [ ] Documentation updated
- [ ] Rollout completed
- [ ] Old files removed

## Risk Mitigation

1. **Backup Current State**: Create backup of all model files before changes
2. **Feature Flag**: Use environment variable to switch between old/new models
3. **Rollback Plan**: Keep old files until new models proven in production
4. **Gradual Migration**: Update one component at a time
5. **Continuous Testing**: Run tests after each change

## Timeline

- **Phase 1**: 2 hours - Analysis
- **Phase 2**: 3 hours - Model consolidation
- **Phase 3**: 2 hours - Import updates
- **Phase 4**: 4 hours - Testing
- **Phase 5**: 1 hour - Validation
- **Phase 6**: 1 hour - Documentation

**Total**: 13 hours of focused work

## Next Steps

1. Begin with Phase 1 field usage analysis
2. Create consolidated model file based on findings
3. Test with single document first
4. Gradually expand testing
5. Roll out when all tests pass

This plan ensures we achieve the simplest possible working models while maintaining system functionality and data integrity.