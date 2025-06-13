# Context 241: Schema Mapping Implementation Plan

**Date**: 2025-05-30
**Type**: Implementation Strategy
**Status**: URGENT - Required for System Operation
**Component**: Database Table and Column Mapping

## Critical Discovery

The scripts and RDS database use **completely different table names** for the same logical entities. This is causing immediate failures when scripts attempt database operations.

## Table Name Mapping Required

| Script Expects | RDS Has | Purpose |
|----------------|---------|---------|
| `source_documents` | `documents` | Document metadata and status |
| `document_chunks` | `chunks` | Text segments |
| `entity_mentions` | `entities` | Extracted entities |
| `canonical_entities` | `entities` | Canonical entity resolution |
| `relationship_staging` | `relationships` | Entity relationships |
| `neo4j_documents` | `documents` | Graph-ready documents |
| `neo4j_chunks` | `chunks` | Graph-ready chunks |

## Immediate Fix: Table Mapping Layer

### Option 1: Database Views (Recommended for Quick Fix)

Create views in RDS that map expected names to actual tables:

```sql
-- Execute these in RDS to create compatibility views
CREATE OR REPLACE VIEW source_documents AS SELECT * FROM documents;
CREATE OR REPLACE VIEW document_chunks AS SELECT * FROM chunks;
CREATE OR REPLACE VIEW entity_mentions AS SELECT * FROM entities;
CREATE OR REPLACE VIEW canonical_entities AS SELECT * FROM entities;
CREATE OR REPLACE VIEW relationship_staging AS SELECT * FROM relationships;
CREATE OR REPLACE VIEW neo4j_documents AS SELECT * FROM documents;
CREATE OR REPLACE VIEW neo4j_chunks AS SELECT * FROM chunks;

-- Also need these tables that don't exist
CREATE TABLE IF NOT EXISTS textract_jobs (
    id SERIAL PRIMARY KEY,
    job_id TEXT,
    document_uuid UUID REFERENCES documents(document_uuid),
    status TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,
    metadata JSONB DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS import_sessions (
    id SERIAL PRIMARY KEY,
    session_uuid UUID DEFAULT gen_random_uuid(),
    project_uuid UUID REFERENCES projects(project_uuid),
    created_at TIMESTAMP DEFAULT NOW(),
    metadata JSONB DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS chunk_embeddings (
    id SERIAL PRIMARY KEY,
    chunk_uuid UUID REFERENCES chunks(chunk_uuid),
    embedding_vector FLOAT[],
    model_name TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS canonical_entity_embeddings (
    id SERIAL PRIMARY KEY,
    entity_uuid UUID REFERENCES entities(entity_uuid),
    embedding_vector FLOAT[],
    model_name TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS document_processing_history (
    id SERIAL PRIMARY KEY,
    document_uuid UUID REFERENCES documents(document_uuid),
    event_type TEXT,
    event_data JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### Option 2: Code-Level Mapping

Add a mapping configuration to `scripts/config.py`:

```python
# Table name mapping for RDS compatibility
TABLE_MAPPING = {
    'source_documents': 'documents',
    'document_chunks': 'chunks',
    'entity_mentions': 'entities',
    'canonical_entities': 'entities',
    'relationship_staging': 'relationships',
    'neo4j_documents': 'documents',
    'neo4j_chunks': 'chunks',
    'neo4j_entity_mentions': 'entities',
    'neo4j_canonical_entities': 'entities',
    'neo4j_relationships_staging': 'relationships'
}

def get_table_name(script_table_name: str) -> str:
    """Map script table names to actual RDS table names."""
    return TABLE_MAPPING.get(script_table_name, script_table_name)
```

Update `scripts/db.py` to use mapping:

```python
# In DatabaseManager class
def _map_table_name(self, table_name: str) -> str:
    """Map script table names to actual database tables."""
    from scripts.config import get_table_name
    return get_table_name(table_name)

def insert_record(self, table: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Insert with table name mapping."""
    actual_table = self._map_table_name(table)
    return self._execute_with_conformance(
        "insert", actual_table, data=data
    )
```

## Column Mapping Issues

### Critical Column Differences

1. **Primary Keys**
   - Scripts expect: `id` (SERIAL) + `document_uuid` (UUID)
   - RDS has: `document_uuid` (UUID PRIMARY KEY)

2. **Foreign Keys**
   - Scripts expect: `document_fk_id` (INTEGER)
   - RDS has: `document_uuid` (UUID)

3. **Missing Columns in RDS**
   - `s3_key`, `s3_bucket` (document storage)
   - `ocr_metadata_json` (OCR details)
   - `celery_status` (task tracking)
   - Many processing status fields

### Column Mapping Strategy

```python
# scripts/database/column_mapper.py
class ColumnMapper:
    """Maps between script column names and RDS columns."""
    
    COLUMN_MAPPINGS = {
        'documents': {
            'id': None,  # Doesn't exist in RDS
            'document_fk_id': 'document_uuid',
            'original_file_path': 'file_path',
            'initial_processing_status': 'processing_status',
            'project_fk_id': 'project_uuid'
        },
        'chunks': {
            'id': None,
            'document_fk_id': 'document_uuid',
            'start_position': 'char_start_index',
            'end_position': 'char_end_index',
            'content': 'text_content'
        }
    }
    
    @classmethod
    def map_insert_data(cls, table: str, data: Dict) -> Dict:
        """Map column names for insert operations."""
        if table not in cls.COLUMN_MAPPINGS:
            return data
            
        mapped = {}
        mappings = cls.COLUMN_MAPPINGS[table]
        
        for key, value in data.items():
            if key in mappings:
                mapped_key = mappings[key]
                if mapped_key:  # Skip if None
                    mapped[mapped_key] = value
            else:
                mapped[key] = value
                
        return mapped
```

## Recommended Implementation Order

### Phase 1: Emergency Fix (Today)
1. **Create database views** (Option 1 SQL above)
2. **Test basic operations** work with views
3. **Document known limitations**

### Phase 2: Proper Mapping (Week 1)
1. **Implement ColumnMapper class**
2. **Update DatabaseManager** to use mappers
3. **Add missing columns** to RDS tables
4. **Create missing tables**

### Phase 3: Schema Alignment (Week 2-3)
1. **Choose target schema** (simplified RDS vs complex script schema)
2. **Update Pydantic models** to match chosen schema
3. **Refactor scripts** to use consistent names
4. **Remove mapping layer** once aligned

## Testing Strategy

```python
# scripts/tests/test_schema_mapping.py
def test_table_mapping():
    """Verify all expected tables are accessible."""
    db = DatabaseManager()
    
    expected_tables = [
        'source_documents',
        'document_chunks', 
        'entity_mentions',
        'canonical_entities',
        'relationship_staging'
    ]
    
    for table in expected_tables:
        # Should not raise exception
        result = db.select_records(table, limit=1)
        assert isinstance(result, list)

def test_document_insert():
    """Test document insertion with mapping."""
    db = DatabaseManager()
    
    # Script-style data
    doc_data = {
        'document_uuid': str(uuid.uuid4()),
        'project_fk_id': str(uuid.uuid4()),  # Will map to project_uuid
        'filename': 'test.pdf',
        'original_file_path': '/tmp/test.pdf',  # Will map to file_path
        'initial_processing_status': 'pending'  # Will map to processing_status
    }
    
    result = db.insert_record('source_documents', doc_data)
    assert result is not None
```

## Risk Assessment

### High Risk Issues
1. **Foreign key constraints** may fail with mapping
2. **Triggers** won't fire on views (need instead rules)
3. **Performance** impact of view layer
4. **Transaction boundaries** with views

### Mitigation Strategies
1. Use **INSTEAD OF triggers** on views for DML operations
2. Add **indexes** on mapped columns
3. **Monitor query performance** with EXPLAIN ANALYZE
4. **Test transaction rollbacks** thoroughly

## Monitoring Implementation

```python
# scripts/monitoring/schema_monitor.py
class SchemaMonitor:
    """Monitor schema mapping performance and issues."""
    
    def check_mapping_health(self):
        """Verify all mappings are working."""
        issues = []
        
        # Check views exist
        for view in ['source_documents', 'document_chunks']:
            if not self.view_exists(view):
                issues.append(f"Missing view: {view}")
                
        # Check performance
        slow_queries = self.get_slow_mapped_queries()
        if slow_queries:
            issues.append(f"Slow queries: {len(slow_queries)}")
            
        return issues
```

## Decision Matrix

| Approach | Implementation Time | Risk | Long-term Maintenance |
|----------|-------------------|------|---------------------|
| Database Views | 1 hour | Medium | High |
| Code Mapping | 4 hours | Low | Medium |
| Schema Migration | 2 weeks | High | Low |
| Hybrid (Views + Code) | 6 hours | Low | Medium |

## Recommendation

**Immediate Action**: Implement database views (1 hour fix)
**This Week**: Add code-level mapping for robustness
**This Month**: Plan and execute schema alignment to eliminate mapping

This approach provides immediate functionality while building toward a sustainable solution.