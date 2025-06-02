# Migration Guide: From Minimal to Full Models

## Overview

This guide describes how to migrate from minimal models back to full Pydantic models once schema conformance issues are resolved.

## Prerequisites

Before migrating:
1. All database schema issues must be resolved
2. Missing columns must be added to tables
3. Type mismatches must be corrected
4. Backup your database

## Migration Steps

### Step 1: Verify Schema Conformance

Run conformance check with full models:
```bash
# Temporarily disable minimal models
export USE_MINIMAL_MODELS=false
export SKIP_CONFORMANCE_CHECK=false

# Run conformance check
python scripts/test_schema_conformance.py
```

### Step 2: Add Missing Database Columns

If conformance check fails, add missing columns:

```sql
-- Example: Add missing columns to source_documents
ALTER TABLE source_documents
ADD COLUMN IF NOT EXISTS display_name TEXT,
ADD COLUMN IF NOT EXISTS description TEXT,
ADD COLUMN IF NOT EXISTS created_by UUID,
ADD COLUMN IF NOT EXISTS updated_by UUID,
ADD COLUMN IF NOT EXISTS entity_graph_uuid UUID,
ADD COLUMN IF NOT EXISTS processing_metadata JSONB DEFAULT '{}';

-- Add other missing columns as needed
```

### Step 3: Update Environment Configuration

Once schema is conformant:
```bash
# In .env
USE_MINIMAL_MODELS=false
SKIP_CONFORMANCE_CHECK=false
```

### Step 4: Test with Single Document

Before full deployment:
```python
# Test script
from scripts.db import DatabaseManager
from scripts.core.schemas import SourceDocumentModel

# This should now use full model
db = DatabaseManager()
doc = SourceDocumentModel(
    document_uuid=uuid.uuid4(),
    original_file_name="test.pdf",
    # ... all fields available
)
result = db.create_source_document(doc)
```

### Step 5: Gradual Rollout

1. **Stage 1**: Test environment only
2. **Stage 2**: Single worker with full models
3. **Stage 3**: 50% of workers
4. **Stage 4**: Full production

### Step 6: Update Monitoring

Monitor for:
- Increased memory usage
- Slower serialization
- Database query performance
- Worker throughput

## Rollback Plan

If issues occur:
```bash
# Quick rollback
export USE_MINIMAL_MODELS=true
export SKIP_CONFORMANCE_CHECK=true

# Restart workers
supervisorctl restart all
```

## Field Mapping

When migrating, these fields become available:

| Minimal Field | Full Model Additional Fields |
|---------------|----------------------------|
| SourceDocumentMinimal | display_name, description, created_by, updated_by, tags, entity_graph_uuid |
| DocumentChunkMinimal | chunk_type, metadata_json, embedding_vector, processing_metadata |
| EntityMentionMinimal | confidence_score, extraction_method, processing_metadata |
| CanonicalEntityMinimal | aliases, description, attributes, embedding_vector |

## Performance Expectations

After migration to full models:
- Memory usage: +60% increase
- CPU usage: +20% increase
- Database queries: +40% complexity
- Network traffic: +30% increase

Plan capacity accordingly.

## Verification Checklist

- [ ] All conformance tests pass
- [ ] No missing column errors
- [ ] No type mismatch errors
- [ ] Single document processes successfully
- [ ] Memory usage within limits
- [ ] Worker performance acceptable
- [ ] Monitoring dashboards updated
- [ ] Rollback tested and ready

## Common Issues

### Issue 1: UUID Fields
```sql
-- Fix UUID type mismatches
ALTER TABLE source_documents
ALTER COLUMN created_by TYPE UUID USING created_by::UUID;
```

### Issue 2: JSONB Defaults
```sql
-- Add JSONB columns with defaults
ALTER TABLE document_chunks
ADD COLUMN metadata_json JSONB DEFAULT '{}';
```

### Issue 3: Enum Values
```sql
-- Ensure enum values match
ALTER TABLE entity_mentions
ADD CONSTRAINT check_entity_type 
CHECK (entity_type IN ('PERSON', 'ORG', 'LOC', 'DATE', 'MONEY'));
```

## Support

For migration assistance:
1. Check logs in `/opt/legal-doc-processor/monitoring/logs/`
2. Run conformance validator with verbose output
3. Test with minimal dataset first
4. Document any new issues in `/ai_docs/`