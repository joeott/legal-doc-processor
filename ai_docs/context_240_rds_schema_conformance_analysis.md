# Context 240: RDS Schema Conformance Analysis and Automated Validation Strategy

**Date**: 2025-05-30
**Type**: Technical Analysis
**Status**: CRITICAL - Major Conformance Issues Identified
**Component**: Database Schema Validation and Script Conformance

## Executive Summary

A comprehensive analysis reveals significant misalignment between the RDS database schema and the expectations of the Python scripts. The current simplified 7-table schema does not match the complex 15+ table structure expected by the Pydantic models, creating a critical impediment to system functionality.

## Current State Analysis

### RDS Database Schema (Actual)
```
7 tables deployed:
- projects (legal matters)
- documents (source files)
- chunks (text segments)
- entities (extracted entities)
- relationships (entity connections)
- processing_logs (audit trail)
- schema_version (migration tracking)
```

### Script Expectations (From Pydantic Models)
```
15+ tables expected:
- source_documents (legacy document table)
- neo4j_documents, neo4j_chunks (graph-specific tables)
- neo4j_entity_mentions, neo4j_canonical_entities
- neo4j_relationships_staging
- textract_jobs (OCR job tracking)
- chunk_embeddings, canonical_entity_embeddings
- document_processing_history
- import_sessions (batch import tracking)
```

## Critical Conformance Issues

### 1. Architectural Mismatch
The scripts expect a **hybrid architecture** with:
- Legacy `source_documents` table
- Neo4j-prefixed tables for graph operations
- Separate embedding storage tables
- Detailed processing history tracking

The RDS has a **simplified architecture** with:
- Direct document storage
- Unified entity/relationship tables
- No separate embedding storage
- Basic processing logs

### 2. Primary Key Strategy Conflict
- **Scripts expect**: Integer primary keys with separate UUID fields
- **Database has**: UUID primary keys directly

### 3. Foreign Key Type Mismatch
- **Scripts expect**: Integer foreign keys (e.g., `project_fk_id`)
- **Database has**: UUID foreign keys (e.g., `project_uuid`)

### 4. Missing Critical Fields
Major fields missing from database tables:
- Document OCR metadata and status tracking
- Celery task tracking fields
- S3 storage location fields
- Processing timing and provider information
- Import session tracking

## Proposed Automated Schema Conformance Mechanism

### Architecture Design

```python
# scripts/database/schema_conformance_engine.py
from sqlalchemy import create_engine, MetaData, inspect
from sqlalchemy.schema import CreateTable, DropTable
from typing import Dict, List, Tuple, Optional
import logging
from pathlib import Path
import json

class SchemaConformanceEngine:
    """
    Automated schema conformance validation and migration engine.
    Uses SQLAlchemy introspection to compare expected vs actual schemas.
    """
    
    def __init__(self, database_url: str):
        self.engine = create_engine(database_url)
        self.metadata = MetaData()
        self.inspector = inspect(self.engine)
        self.logger = logging.getLogger(__name__)
        
    def extract_actual_schema(self) -> Dict[str, Dict]:
        """Extract current database schema using SQLAlchemy inspection."""
        schema = {}
        
        for table_name in self.inspector.get_table_names():
            columns = {}
            for col in self.inspector.get_columns(table_name):
                columns[col['name']] = {
                    'type': str(col['type']),
                    'nullable': col['nullable'],
                    'default': col['default'],
                    'primary_key': col.get('primary_key', False)
                }
            
            foreign_keys = []
            for fk in self.inspector.get_foreign_keys(table_name):
                foreign_keys.append({
                    'constrained_columns': fk['constrained_columns'],
                    'referred_table': fk['referred_table'],
                    'referred_columns': fk['referred_columns']
                })
            
            schema[table_name] = {
                'columns': columns,
                'foreign_keys': foreign_keys,
                'indexes': self.inspector.get_indexes(table_name),
                'primary_key': self.inspector.get_pk_constraint(table_name)
            }
            
        return schema
    
    def extract_expected_schema(self) -> Dict[str, Dict]:
        """Extract expected schema from Pydantic models and SQLAlchemy tables."""
        from scripts.core import schemas
        from scripts.db import DatabaseType
        
        expected = {}
        
        # Get all expected tables from DatabaseType enum
        for table_enum in DatabaseType:
            table_name = table_enum.value
            
            # Map to corresponding Pydantic model
            model_mapping = {
                'projects': schemas.ProjectModel,
                'source_documents': schemas.SourceDocumentModel,
                'neo4j_documents': schemas.Neo4jDocumentModel,
                'neo4j_chunks': schemas.ChunkModel,
                'neo4j_entity_mentions': schemas.EntityMentionModel,
                'neo4j_canonical_entities': schemas.CanonicalEntityModel,
                'neo4j_relationships_staging': schemas.RelationshipStagingModel,
                'textract_jobs': schemas.TextractJobModel,
                'import_sessions': schemas.ImportSessionModel,
                'chunk_embeddings': schemas.ChunkEmbeddingModel,
                'canonical_entity_embeddings': schemas.CanonicalEntityEmbeddingModel,
                'document_processing_history': schemas.DocumentProcessingHistoryModel
            }
            
            if table_name in model_mapping:
                model = model_mapping[table_name]
                expected[table_name] = self._pydantic_to_schema(model)
                
        return expected
    
    def _pydantic_to_schema(self, model_class) -> Dict:
        """Convert Pydantic model to schema definition."""
        columns = {}
        
        for field_name, field_info in model_class.model_fields.items():
            field_type = field_info.annotation
            
            # Map Python types to SQL types
            sql_type = self._python_to_sql_type(field_type)
            
            columns[field_name] = {
                'type': sql_type,
                'nullable': not field_info.is_required(),
                'default': field_info.default,
                'primary_key': field_name in ['id', 'uuid']
            }
            
        return {'columns': columns, 'foreign_keys': [], 'indexes': []}
    
    def compare_schemas(self, actual: Dict, expected: Dict) -> Dict[str, List]:
        """Compare actual vs expected schemas and identify differences."""
        issues = {
            'missing_tables': [],
            'extra_tables': [],
            'missing_columns': {},
            'extra_columns': {},
            'type_mismatches': {},
            'constraint_differences': {}
        }
        
        # Check for missing/extra tables
        actual_tables = set(actual.keys())
        expected_tables = set(expected.keys())
        
        issues['missing_tables'] = list(expected_tables - actual_tables)
        issues['extra_tables'] = list(actual_tables - expected_tables)
        
        # Check columns in common tables
        for table in actual_tables & expected_tables:
            actual_cols = set(actual[table]['columns'].keys())
            expected_cols = set(expected[table]['columns'].keys())
            
            missing = list(expected_cols - actual_cols)
            if missing:
                issues['missing_columns'][table] = missing
                
            extra = list(actual_cols - expected_cols)
            if extra:
                issues['extra_columns'][table] = extra
                
            # Check type mismatches
            for col in actual_cols & expected_cols:
                if actual[table]['columns'][col]['type'] != expected[table]['columns'][col]['type']:
                    if table not in issues['type_mismatches']:
                        issues['type_mismatches'][table] = {}
                    issues['type_mismatches'][table][col] = {
                        'actual': actual[table]['columns'][col]['type'],
                        'expected': expected[table]['columns'][col]['type']
                    }
                    
        return issues
    
    def generate_migration_script(self, issues: Dict) -> str:
        """Generate SQL migration script to fix conformance issues."""
        sql_statements = []
        
        # Create missing tables
        for table in issues['missing_tables']:
            # This would need to generate CREATE TABLE statements
            sql_statements.append(f"-- TODO: CREATE TABLE {table}")
            
        # Add missing columns
        for table, columns in issues['missing_columns'].items():
            for col in columns:
                sql_statements.append(f"-- TODO: ALTER TABLE {table} ADD COLUMN {col}")
                
        return '\n'.join(sql_statements)
    
    def validate_conformance(self) -> Tuple[bool, Dict]:
        """Main validation method."""
        actual = self.extract_actual_schema()
        expected = self.extract_expected_schema()
        issues = self.compare_schemas(actual, expected)
        
        is_conformant = not any(issues.values())
        
        return is_conformant, issues
```

### Integration Strategy

```python
# scripts/cli/schema.py
import click
from scripts.database.schema_conformance_engine import SchemaConformanceEngine

@click.group()
def schema():
    """Database schema management commands."""
    pass

@schema.command()
@click.option('--fix', is_flag=True, help='Attempt to fix issues')
def validate():
    """Validate schema conformance."""
    engine = SchemaConformanceEngine(DATABASE_URL)
    is_conformant, issues = engine.validate_conformance()
    
    if is_conformant:
        click.echo("✓ Schema is fully conformant")
    else:
        click.echo("✗ Schema conformance issues found:")
        
        if issues['missing_tables']:
            click.echo(f"\nMissing tables: {', '.join(issues['missing_tables'])}")
            
        if issues['missing_columns']:
            click.echo("\nMissing columns:")
            for table, cols in issues['missing_columns'].items():
                click.echo(f"  {table}: {', '.join(cols)}")
                
        if fix:
            click.echo("\nGenerating migration script...")
            script = engine.generate_migration_script(issues)
            # Save or execute migration
```

## Feasibility Assessment

### Using SQLAlchemy for Conformance

**Advantages:**
1. **Introspection Capabilities**: SQLAlchemy can extract complete schema metadata
2. **Cross-Database Support**: Works with PostgreSQL, MySQL, SQLite, etc.
3. **Type System**: Strong type mapping between Python and SQL
4. **Migration Generation**: Can generate DDL statements programmatically

**Challenges:**
1. **Complex Type Mapping**: Enums, JSON fields need special handling
2. **Business Logic**: Can't capture triggers, functions, or complex constraints
3. **Performance**: Large schemas take time to introspect

**Feasibility Score: 8/10** - Highly feasible with proper implementation

## Required Script Changes

### 1. **scripts/db.py**
```python
# Current: Expects many tables that don't exist
# Change: Add schema validation on startup
def __init__(self, validate_conformance=True):
    if validate_conformance:
        from scripts.database.schema_conformance_engine import SchemaConformanceEngine
        engine = SchemaConformanceEngine(DATABASE_URL)
        is_conformant, issues = engine.validate_conformance()
        if not is_conformant:
            raise RuntimeError(f"Schema non-conformant: {issues}")
```

### 2. **scripts/pdf_tasks.py**
```python
# Current: Uses source_documents table
# Change: Map to documents table
def _get_document_table(self):
    # Add mapping layer
    if self.use_legacy_schema:
        return "source_documents"
    return "documents"
```

### 3. **scripts/entity_service.py**
```python
# Current: Uses neo4j_entity_mentions
# Change: Use entities table with type field
def save_entity(self, entity_data):
    # Transform neo4j structure to simplified structure
    simplified = self._transform_to_simple_schema(entity_data)
    return self.db.insert("entities", simplified)
```

### 4. **scripts/ocr_extraction.py**
```python
# Current: Expects textract_jobs table
# Change: Use processing_logs with type='ocr'
def log_ocr_job(self, job_data):
    log_entry = {
        'event_type': 'ocr_job',
        'metadata': json.dumps(job_data),
        'created_at': datetime.utcnow()
    }
    return self.db.insert("processing_logs", log_entry)
```

### 5. **scripts/chunking_utils.py**
```python
# Current: Uses neo4j_chunks
# Change: Use chunks table
CHUNK_TABLE = "chunks"  # Was: "neo4j_chunks"
```

### 6. **scripts/text_processing.py**
```python
# Current: Complex embedding storage
# Change: Store embeddings in chunks.embedding_vector column
def store_chunk_embedding(self, chunk_id, embedding):
    # Store directly in chunks table
    self.db.update("chunks", 
        {"embedding_vector": embedding},
        {"chunk_uuid": chunk_id}
    )
```

## Migration Strategy Options

### Option 1: Align Scripts to Database (Recommended)
**Pros:**
- Simpler schema is easier to maintain
- Less storage overhead
- Cleaner architecture

**Cons:**
- Requires updating all scripts
- May lose some tracking granularity

**Implementation Steps:**
1. Create schema mapping layer
2. Update Pydantic models to match RDS
3. Refactor scripts to use new models
4. Add compatibility shims for legacy code

### Option 2: Align Database to Scripts
**Pros:**
- No script changes needed
- Preserves all tracking features

**Cons:**
- Complex schema with 15+ tables
- Higher storage costs
- More difficult to maintain

### Option 3: Hybrid Approach
**Pros:**
- Gradual migration
- Maintains compatibility

**Cons:**
- Complex mapping logic
- Potential for inconsistencies

## Implementation Roadmap

### Phase 1: Assessment (Week 1)
1. Deploy conformance engine
2. Generate detailed schema differences report
3. Identify critical vs nice-to-have tables

### Phase 2: Mapping Layer (Week 2)
1. Create `TableMapper` class for name translation
2. Implement field mapping decorators
3. Add compatibility shims

### Phase 3: Script Updates (Week 3-4)
1. Update each script with new table names
2. Modify Pydantic models
3. Test each component

### Phase 4: Validation (Week 5)
1. Run conformance checks
2. Execute end-to-end tests
3. Performance benchmarking

## Automated Conformance Benefits

1. **Continuous Validation**: Check schema on every deployment
2. **Migration Safety**: Validate changes before applying
3. **Documentation**: Auto-generate schema docs
4. **Testing**: Ensure test databases match production
5. **Development**: Catch schema drift early

## Conclusion

The schema conformance issues are significant but manageable. The proposed automated conformance mechanism using SQLAlchemy is highly feasible and would provide ongoing benefits. The recommended approach is to align the scripts to the simpler RDS schema while adding a thin compatibility layer for legacy code.

This strategy minimizes disruption while providing a clean path forward for the document processing pipeline.