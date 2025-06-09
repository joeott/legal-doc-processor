# Context 448: Schema Inspector Utility Complete

## Date: June 8, 2025

## Executive Summary

Successfully created a comprehensive **schema inspector utility** at `/opt/legal-doc-processor/scripts/utils/schema_inspector.py` that captures the complete RDS PostgreSQL database schema as machine-readable JSON, including tables, triggers, functions, sequences, views, and extensions.

## Implementation Details

### Script Location and Purpose
- **File:** `/opt/legal-doc-processor/scripts/utils/schema_inspector.py`
- **Purpose:** Export complete database schema as JSON for documentation, migration planning, and validation
- **Scope:** Captures ALL database objects, not just tables

### Key Features

#### 1. Complete Schema Coverage ✅
```python
schema_info = {
    "tables": {},      # All table definitions with columns, constraints, indexes
    "triggers": [],    # Database triggers with definitions
    "functions": [],   # User-defined functions and stored procedures  
    "sequences": [],   # Auto-increment sequences
    "views": [],       # Database views
    "schemas": [],     # Schema namespaces
    "extensions": [],  # PostgreSQL extensions
    "summary": {}      # Aggregate statistics
}
```

#### 2. Robust Error Handling ✅
**Critical Design Feature:** Script continues and produces JSON output even if individual components fail
- Individual error handling for each database object type
- Fallback mechanisms for connection failures
- Error details included in output JSON
- Always produces valid JSON regardless of failures

#### 3. Production Environment Integration ✅
- Uses existing environment variables (DATABASE_URL, DATABASE_URL_DIRECT)
- Integrates with legal-doc-processor configuration
- Supports our minimal models validation
- Compatible with RDS PostgreSQL setup

### Usage Examples

#### Basic Schema Export
```bash
cd /opt/legal-doc-processor
source load_env.sh
python3 scripts/utils/schema_inspector.py -o current_schema.json
```

#### Full Featured Export
```bash
python3 scripts/utils/schema_inspector.py \
    -o schema_with_counts.json \
    --include-counts \
    --validate \
    --verbose
```

#### Direct Database URI
```bash
python3 scripts/utils/schema_inspector.py \
    --uri "postgresql://user:pass@host:5432/db" \
    -o custom_schema.json
```

## Current Production Results

### Schema Statistics (June 8, 2025)
```
✅ Schema written to current_schema.json
   Tables: 14
   Columns: 187
   Foreign Keys: 17
   Indexes: 35
   Triggers: 6
   Functions: 12
   Sequences: 12
   Views: 0
   Schemas: 1
   Extensions: 2
```

### Database Objects Captured

#### Tables (14)
- `canonical_entities` - Deduplicated entity storage
- `canonical_entity_embeddings` - Vector embeddings for entities
- `chunk_embeddings` - Document chunk vectors  
- `document_chunks` - Text chunks from documents
- `document_processing_history` - Processing audit trail
- `entity_mentions` - Raw extracted entities
- `import_sessions` - Document import tracking
- `neo4j_documents` - Graph database integration
- `processing_tasks` - Celery task tracking
- `projects` - Legal matter/case organization
- `relationship_staging` - Entity relationships
- `schema_version` - Database version tracking
- `source_documents` - Original document metadata
- `textract_jobs` - OCR job tracking

#### Triggers (6)
All are `update_*_updated_at` triggers that automatically maintain timestamp columns

#### Functions (12)
Including `update_updated_at_column()`, `populate_integer_fks()`, and other database utilities

#### Extensions (2)
- `uuid-ossp` for UUID generation
- Other PostgreSQL extensions

### Model Validation Results
```
ℹ️ Extra tables: document_processing_history, chunk_embeddings, schema_version, 
                 canonical_entity_embeddings, processing_tasks, textract_jobs, 
                 neo4j_documents, import_sessions, projects
```

**Analysis:** Our production database has evolved beyond the minimal Pydantic models to include:
- Audit/history tables
- Vector embedding storage  
- Processing task management
- Graph database integration
- Import session tracking

## Technical Implementation

### Error Resilience Architecture
```python
# Each component wrapped in try/catch
try:
    schema_info["triggers"] = get_database_triggers(engine)
    schema_info["summary"]["total_triggers"] = len(schema_info["triggers"])
except Exception as e:
    logger.error(f"Failed to get triggers: {e}")
    schema_info["triggers"] = []
    schema_info["errors"] = schema_info.get("errors", [])
    schema_info["errors"].append(f"Triggers: {str(e)}")
```

### SQL Queries for PostgreSQL-Specific Objects
- **Triggers:** `information_schema.triggers`
- **Functions:** `information_schema.routines`  
- **Sequences:** `information_schema.sequences`
- **Views:** `information_schema.views`
- **Extensions:** `pg_extension` catalog

### JSON Serialization Safety
```python
# Fallback serialization handles complex PostgreSQL types
schema_json = json.dumps(schema_data, indent=2, default=str)
```

## Utility Benefits

### 1. Documentation and Compliance ✅
- Complete schema snapshot for audit purposes
- Version-controlled schema evolution tracking
- Compliance documentation for legal industry requirements

### 2. Migration Planning ✅  
- Baseline for database migrations
- Schema comparison between environments
- Change impact analysis

### 3. Development and Debugging ✅
- Quick schema reference for developers
- Debugging aid for relationship issues
- Validation against Pydantic models

### 4. Production Monitoring ✅
- Regular schema health checks
- Trigger and function validation
- Index and constraint verification

## File Structure Integration

```
/opt/legal-doc-processor/
├── scripts/
│   └── utils/
│       ├── schema_inspector.py  ← NEW UTILITY
│       ├── error_handler.py
│       ├── param_validator.py
│       └── schema_reference.py
├── current_schema.json          ← GENERATED OUTPUT
└── ai_docs/
    └── context_448_schema_inspector_utility_complete.md
```

## Future Enhancements

### Planned Features (Optional)
1. **Schema Diff Tool** - Compare schemas between environments
2. **Migration Generator** - Auto-generate migration scripts from differences
3. **Performance Analysis** - Index usage and query optimization suggestions
4. **Automated Monitoring** - Scheduled schema health checks

### Integration Opportunities
- CI/CD pipeline integration for schema validation
- Automated documentation generation
- Migration testing workflows

## Production Usage Guidelines

### Regular Maintenance
```bash
# Weekly schema snapshots
python3 scripts/utils/schema_inspector.py -o weekly_schema_$(date +%Y%m%d).json --validate

# Pre-migration baseline
python3 scripts/utils/schema_inspector.py -o pre_migration_schema.json --include-counts

# Post-deployment verification
python3 scripts/utils/schema_inspector.py -o post_deploy_schema.json --validate
```

### Troubleshooting
The utility includes comprehensive error handling and will output meaningful JSON even during:
- Network connectivity issues
- Permission problems  
- Partial database access
- PostgreSQL version differences

## Conclusion

The schema inspector utility is **production ready** and provides complete visibility into our RDS PostgreSQL database structure. It successfully captures all database objects with robust error handling, ensuring reliable documentation and migration planning capabilities.

**Key Achievement:** Unlike basic schema tools, this utility captures the complete database ecosystem including triggers, functions, and PostgreSQL-specific features while maintaining resilience against partial failures.

**Immediate Value:** The current schema snapshot shows our database has evolved significantly beyond minimal models, providing insight into the actual production complexity and integration requirements.