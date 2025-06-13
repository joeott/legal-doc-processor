# Context 224: Simplified Schema Analysis for Core Pipeline Functions

**Date**: 2025-01-29
**Type**: Simplification Analysis
**Status**: COMPLETE
**Analyst**: Claude Opus 4

## Executive Summary

After analyzing the actual scripts in `/scripts/`, I've identified that the proposed RDS schema from context_222/223 is **over-engineered** for the current codebase. The scripts perform straightforward document processing that requires only basic database operations. This analysis recommends a simplified approach that maintains robustness while eliminating unnecessary complexity.

## Core Functions Analysis

### What the Scripts Actually Do

1. **Document Intake** (`pdf_pipeline.py`, `pdf_tasks.py`)
   - Accept PDF/DOCX files
   - Store in S3
   - Track processing status

2. **Text Extraction** (`ocr_extraction.py`, `textract_utils.py`)
   - Call AWS Textract
   - Store extracted text
   - Handle errors with fallbacks

3. **Text Processing** (`text_processing.py`, `chunking_utils.py`)
   - Split text into chunks
   - Maintain document structure
   - Simple boundary detection

4. **Entity Extraction** (`entity_service.py`)
   - Use OpenAI to find entities
   - Store entity mentions
   - Basic type classification

5. **Graph Building** (`graph_service.py`)
   - Identify relationships
   - Create simple connections
   - No complex graph operations

### What the Scripts DON'T Do

- ❌ Complex graph traversals
- ❌ Real-time analytics
- ❌ Multi-tenant isolation
- ❌ Advanced search queries
- ❌ Workflow orchestration beyond Celery

## Database Requirements: Simple vs Proposed

### Current Proposed Schema (Overly Complex)
- 14 tables with complex relationships
- 5 custom enum types
- Partitioned tables
- Materialized views
- Audit trails
- Neo4j staging tables

### What's Actually Needed (Simple)

```sql
-- Just 5 core tables
CREATE TABLE projects (
    project_uuid UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE documents (
    document_uuid UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_uuid UUID REFERENCES projects(project_uuid),
    filename TEXT NOT NULL,
    s3_path TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE chunks (
    chunk_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_uuid UUID REFERENCES documents(document_uuid),
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    metadata JSONB DEFAULT '{}'
);

CREATE TABLE entities (
    entity_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_uuid UUID REFERENCES documents(document_uuid),
    entity_type TEXT NOT NULL,
    entity_text TEXT NOT NULL,
    confidence FLOAT,
    metadata JSONB DEFAULT '{}'
);

CREATE TABLE relationships (
    relationship_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    from_entity_id UUID REFERENCES entities(entity_id),
    to_entity_id UUID REFERENCES entities(entity_id),
    relationship_type TEXT NOT NULL,
    metadata JSONB DEFAULT '{}'
);
```

## Why Simpler is Better

### 1. **Code-Database Alignment**
The scripts use basic CRUD operations:
```python
# From entity_service.py
def store_entity(entity_data):
    # Simple INSERT
    db.execute("INSERT INTO entities ...")
    
# From pdf_tasks.py
def update_status(doc_id, status):
    # Simple UPDATE
    db.execute("UPDATE documents SET status = ? ...")
```

No complex queries, no stored procedures, no triggers.

### 2. **Maintenance Simplicity**
- Fewer tables = fewer migration issues
- TEXT instead of enums = flexibility without schema changes
- No partitioning = simpler backups and queries
- No materialized views = no refresh scheduling

### 3. **Performance is Adequate**
- Current volume: ~450 documents
- Simple indexes sufficient
- Redis handles caching
- No need for complex optimizations

### 4. **Extensibility Preserved**
- JSONB metadata fields allow evolution
- Can add columns without breaking code
- Can add tables when actually needed
- UUID keys support future sharding

## Risk Analysis

### Risks of Over-Engineering
1. **Migration Complexity**: 14 tables harder to migrate than 5
2. **Development Friction**: Developers must understand complex schema
3. **Bug Surface**: More constraints = more edge cases
4. **Performance Overhead**: Unnecessary joins and checks

### Risks of Simplification
1. **Future Scaling**: May need to add features later (acceptable)
2. **Type Safety**: TEXT instead of enums (mitigated by app validation)
3. **Query Performance**: No pre-optimization (Redis cache mitigates)

## Recommendation

### Use Simplified Schema with These Principles:

1. **Start Simple**: 5 tables, basic types, minimal constraints
2. **Add When Needed**: Only add complexity when required
3. **Validate in App**: Use Pydantic for type safety, not database
4. **Cache Aggressively**: Redis for read performance
5. **Monitor First**: Add optimizations based on actual usage

### Immediate Benefits:
- Deploy in 30 minutes vs 3 hours
- Understand schema in 5 minutes
- Debug issues easily
- Migrate data simply

### Migration Path:
If complexity needed later:
1. Add new tables (don't modify existing)
2. Migrate data incrementally
3. Use feature flags for transitions
4. Keep old schema as fallback

## Simplified Deployment Script

```bash
# 1. Connect to RDS
psql -h $RDS_ENDPOINT -U postgres

# 2. Create database
CREATE DATABASE legal_docs;

# 3. Run simple schema (50 lines vs 1500)
\i simple_schema.sql

# 4. Verify
\dt
# Should see: projects, documents, chunks, entities, relationships

# 5. Done!
```

## Conclusion

The current scripts implement a straightforward document processing pipeline that needs only basic database support. The proposed 14-table schema adds complexity without providing value for the actual operations performed. 

**Recommendation**: Use the 5-table simplified schema. It fully supports all current functionality while being:
- Easier to understand
- Faster to deploy  
- Simpler to debug
- Just as extensible

Remember: **You can always add complexity later, but you can't remove it once data is in production.**