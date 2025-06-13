# Context 455: Comprehensive Pydantic Compliance Audit Plan

## Date: January 9, 2025

## Executive Summary

This document outlines an optimal, iterative approach to audit the entire ~200k token codebase for compliance with Pydantic model changes and schema corrections implemented in Context 454. The plan employs targeted search strategies, efficient batch processing, and systematic verification to ensure all deprecated column references and non-compliant code patterns are identified and corrected.

## Audit Scope and Objectives

### Primary Objectives
1. **Identify all references to deprecated column names** from Context 454 corrections
2. **Verify Pydantic model compliance** across all scripts  
3. **Ensure database operations use correct column names**
4. **Update any hardcoded SQL queries** with deprecated references
5. **Validate model imports** use consolidated `scripts.models` module

### Codebase Statistics
- **Estimated Size**: ~200k tokens
- **Key Directories**: scripts/, tests/, archived_codebase/, monitoring/
- **File Types**: Python (.py), SQL (.sql), JSON (.json)
- **Critical Scripts**: ~50 production scripts in scripts/

## Deprecated Patterns Reference

### Column Name Changes (from Context 454)
1. **document_chunks**:
   - ❌ `text_content` → ✅ `cleaned_text` or `text`
   
2. **canonical_entities**:
   - ❌ `created_from_document_uuid` → ✅ Does not exist (removed)
   - ❌ `entity_name` → ✅ `canonical_name`

3. **relationship_staging**:
   - ❌ `document_uuid` → ✅ `source_chunk_uuid`
   - ❌ `source_entity_id` → ✅ `source_entity_uuid`
   - ❌ `target_entity_id` → ✅ `target_entity_uuid`

4. **Model Import Patterns**:
   - ❌ `from scripts.core.models_minimal import ...`
   - ❌ `from scripts.core.pdf_models import ...`
   - ✅ `from scripts.models import ...`

## Efficient Search Strategy

### Phase 1: High-Priority Pattern Detection
**Objective**: Quickly identify files containing deprecated patterns

```bash
# Create working directory for audit results
mkdir -p /opt/legal-doc-processor/monitoring/audit_results

# Search for each deprecated pattern and capture results
grep -r "text_content" scripts/ tests/ --include="*.py" > monitoring/audit_results/text_content_refs.txt
grep -r "created_from_document_uuid" scripts/ tests/ --include="*.py" > monitoring/audit_results/created_from_refs.txt
grep -r "entity_name" scripts/ tests/ --include="*.py" | grep -v "entity_name_display" > monitoring/audit_results/entity_name_refs.txt
grep -r "source_entity_id\|target_entity_id" scripts/ tests/ --include="*.py" > monitoring/audit_results/entity_id_refs.txt
grep -r "models_minimal\|pdf_models" scripts/ tests/ --include="*.py" > monitoring/audit_results/deprecated_imports.txt
```

### Phase 2: SQL Query Analysis
**Objective**: Find hardcoded SQL with deprecated columns

```bash
# Search for SQL queries in Python files
grep -r "SELECT\|INSERT\|UPDATE\|DELETE\|FROM\|WHERE\|JOIN" scripts/ --include="*.py" -A 3 -B 1 > monitoring/audit_results/sql_queries.txt

# Search for specific table references
grep -r "document_chunks\|canonical_entities\|relationship_staging" scripts/ --include="*.py" -A 2 -B 2 > monitoring/audit_results/table_refs.txt
```

### Phase 3: Pydantic Model Usage Verification
**Objective**: Ensure correct model imports and field usage

```bash
# Find all model imports
grep -r "^from.*models.*import\|^import.*models" scripts/ tests/ --include="*.py" > monitoring/audit_results/model_imports.txt

# Find model instantiations
grep -r "Minimal(" scripts/ tests/ --include="*.py" > monitoring/audit_results/model_usage.txt

# Find dictionary-to-model conversions
grep -r "\.dict()\|\.model_dump()\|from_dict\|to_dict" scripts/ tests/ --include="*.py" > monitoring/audit_results/dict_conversions.txt
```

## Detailed Task Implementation Plan

### Task 1: Column Reference Corrections
**Files to Check First** (based on likely usage):
1. `scripts/db.py` - Database operations
2. `scripts/entity_service.py` - Entity operations
3. `scripts/pdf_tasks.py` - Core pipeline tasks
4. `scripts/cli/monitor.py` - Monitoring queries
5. `scripts/utils/schema_reference.py` - Already corrected
6. `scripts/batch_processor.py` - Batch operations
7. `scripts/production_processor.py` - Production pipeline

**Verification Steps**:
1. For each file with deprecated references:
   - Open file and locate exact usage
   - Determine if it's a column reference, variable name, or comment
   - Apply appropriate correction
   - Test correction doesn't break functionality

### Task 2: Model Import Consolidation
**Target Patterns**:
```python
# OLD (to be replaced)
from scripts.core.models_minimal import SourceDocumentMinimal
from scripts.core.pdf_models import PDFDocument
from scripts.core.schemas import *

# NEW (correct pattern)
from scripts.models import (
    SourceDocumentMinimal,
    DocumentChunkMinimal,
    EntityMentionMinimal,
    CanonicalEntityMinimal,
    RelationshipStagingMinimal
)
```

### Task 3: SQL Query Updates
**Critical Queries to Fix**:
1. Pipeline summary queries
2. Entity counting queries  
3. Relationship queries
4. Monitoring dashboard queries
5. Health check queries

**Template Corrections**:
```sql
-- OLD
SELECT * FROM document_chunks WHERE text_content LIKE '%search%'
-- NEW  
SELECT * FROM document_chunks WHERE cleaned_text LIKE '%search%'

-- OLD
SELECT COUNT(*) FROM canonical_entities WHERE created_from_document_uuid = ?
-- NEW (needs logic change - no direct document link)
-- Must join through entity_mentions or other relationship
```

### Task 4: Backward Compatibility Verification
**Check Property Mappings**:
```python
# Verify these compatibility properties still work:
chunk.start_char  # → maps to chunk.char_start_index
chunk.text_content  # → maps to chunk.text
entity.entity_name  # → maps to entity.canonical_name
```

## Verification Criteria for Successful Implementation

### 1. Zero Deprecated References
- [ ] No files contain `text_content` column references
- [ ] No files reference `created_from_document_uuid`
- [ ] All `entity_name` changed to `canonical_name`
- [ ] All `document_uuid` in relationship_staging context changed
- [ ] All `*_entity_id` changed to `*_entity_uuid`

### 2. Unified Model Imports
- [ ] All imports use `from scripts.models import ...`
- [ ] No imports from `scripts.core.models_minimal`
- [ ] No imports from `scripts.core.pdf_models`
- [ ] No wildcard imports from schemas

### 3. SQL Query Compliance
- [ ] All SQL queries use correct column names
- [ ] JOIN conditions updated for new relationships
- [ ] WHERE clauses reflect actual foreign keys
- [ ] No queries will fail with "column does not exist"

### 4. Functional Testing
- [ ] Pipeline processes test document successfully
- [ ] Monitoring dashboard displays correct data
- [ ] Entity extraction creates proper records
- [ ] Relationship building uses correct columns
- [ ] No runtime AttributeError exceptions

### 5. Code Quality Metrics
- [ ] All changes maintain existing functionality
- [ ] Backward compatibility preserved where designed
- [ ] Clear documentation of breaking changes
- [ ] No hardcoded column names remain

## Implementation Workflow

### Day 1: Discovery and Analysis (2-3 hours)
1. Execute Phase 1-3 search commands
2. Analyze search results for patterns
3. Prioritize files by impact and usage
4. Create detailed correction checklist

### Day 2: Core Script Updates (3-4 hours)
1. Update critical pipeline scripts
2. Fix SQL queries in database modules
3. Consolidate model imports
4. Run basic functionality tests

### Day 3: Comprehensive Updates (2-3 hours)
1. Update remaining scripts
2. Fix test files
3. Update monitoring and CLI tools
4. Document any breaking changes

### Day 4: Verification and Testing (2 hours)
1. Run comprehensive test suite
2. Process test documents
3. Verify monitoring functionality
4. Create implementation report

## Risk Mitigation Strategies

### 1. Backup Before Changes
```bash
# Create timestamped backup
tar -czf scripts_backup_$(date +%Y%m%d_%H%M%S).tar.gz scripts/
```

### 2. Incremental Testing
- Test each major change independently
- Use version control for rollback capability
- Maintain change log for all modifications

### 3. Compatibility Layers
- Preserve backward compatibility properties
- Add deprecation warnings for old patterns
- Phase out deprecated code gradually

## Automation Tools

### Quick Validation Script
```python
# validate_compliance.py
import os
import re

deprecated_patterns = [
    r'text_content(?!.*#.*deprecated)',
    r'created_from_document_uuid',
    r'entity_name(?!.*canonical)',
    r'source_entity_id|target_entity_id',
    r'from scripts\.core\.models_minimal',
    r'from scripts\.core\.pdf_models'
]

def scan_file(filepath):
    with open(filepath, 'r') as f:
        content = f.read()
    
    issues = []
    for pattern in deprecated_patterns:
        if re.search(pattern, content):
            issues.append(f"Found deprecated pattern: {pattern}")
    
    return issues

# Run validation across codebase
```

## Success Metrics

### Quantitative Metrics
- **Files Modified**: Target < 50 files
- **Tests Passing**: 100% of existing tests
- **SQL Errors**: 0 "column does not exist" errors
- **Import Errors**: 0 module not found errors

### Qualitative Metrics
- **Code Clarity**: Improved consistency
- **Maintenance**: Easier to understand column mappings
- **Performance**: No degradation from changes
- **Documentation**: Clear migration guide

## Post-Implementation Actions

1. **Update Documentation**:
   - README files
   - API documentation
   - Developer guides
   - CLAUDE.md references

2. **Team Communication**:
   - Share change summary
   - Update coding standards
   - Review with team members

3. **Monitoring Setup**:
   - Add checks for deprecated patterns
   - Create alerts for SQL errors
   - Monitor for attribution errors

## Conclusion

This comprehensive audit plan provides a systematic approach to updating the entire codebase for Pydantic model compliance while minimizing risk and effort. The phased approach allows for incremental progress with validation at each step, ensuring production stability throughout the migration process.

**Estimated Total Effort**: 10-12 hours across 4 days
**Risk Level**: Low (with proper backups and testing)
**Impact**: High (prevents production SQL errors)