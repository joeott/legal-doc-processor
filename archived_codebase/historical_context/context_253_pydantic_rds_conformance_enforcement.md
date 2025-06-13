# Pydantic-RDS Conformance Enforcement Strategy

## Executive Summary

This document details the precise changes required to achieve absolute conformance between Pydantic models in `/scripts/` and the RDS PostgreSQL instance. The goal is to establish a single source of truth where models and database schema are perfectly synchronized, eliminating all runtime errors from schema mismatches.

## Current State Analysis

### 1. Multiple Schema Definitions Problem

The codebase currently has **four different schema files**, each with varying table names and structures:

```
scripts/create_schema.sql              # Uses 'documents' table
scripts/create_rds_schema.sql          # Uses 'source_documents' with advanced features
scripts/create_simple_rds_schema.sql   # Minimal schema, missing many fields
scripts/database/create_conformant_schema.sql  # Designed to match Pydantic models
```

**Critical Issue**: Scripts expect specific table names that don't exist in some schemas:
- Scripts expect: `source_documents`
- Some schemas have: `documents`
- Scripts expect: `document_chunks`
- Some schemas have: `chunks` or `neo4j_chunks`

### 2. Pydantic Model Structure

**Model Files**:
- `/scripts/core/schemas.py` - Primary database models
- `/scripts/core/processing_models.py` - Processing state models
- `/scripts/core/pdf_models.py` - PDF-specific models
- `/scripts/core/task_models.py` - Celery task models

**Key Models**:
1. `SourceDocumentModel` - Document metadata
2. `ChunkModel` - Text chunks
3. `EntityMentionModel` - Extracted entities
4. `CanonicalEntityModel` - Deduplicated entities
5. `RelationshipModel` - Entity relationships
6. `ProcessingTaskModel` - Task tracking

### 3. Critical Conformance Issues

#### A. Table Name Mismatches
```python
# Pydantic Model expects:
__tablename__ = "source_documents"

# But schema might have:
CREATE TABLE documents (...)  # WRONG!
CREATE TABLE neo4j_source_documents (...)  # WRONG!
```

#### B. Field Name Inconsistencies
```python
# Pydantic Model has:
original_file_name: str

# But schema has:
original_filename TEXT  # Different name!
filename VARCHAR(255)   # Completely different!
```

#### C. Type Mismatches
```python
# Pydantic Model:
document_uuid: UUID4  # Expects UUID type

# Database might have:
document_uuid TEXT    # String type - needs conversion
document_uuid VARCHAR(36)  # Wrong type definition
```

#### D. Missing Required Fields
```python
# Model requires these fields:
class SourceDocumentModel(BaseModel):
    document_uuid: UUID4  # Required
    original_file_name: str  # Required
    processing_status: ProcessingStatus  # Required with enum
    
# But schema might be missing them entirely!
```

#### E. Foreign Key Chaos
```python
# Models maintain dual foreign keys:
project_uuid: Optional[UUID4]  # UUID reference
project_fk_id: Optional[int]   # Integer reference

# This creates complexity and potential inconsistency
```

## Required Changes for Absolute Conformance

### 1. Establish Single Source of Truth

**Decision**: Use Pydantic models as the source of truth and generate database schema from them.

**Implementation**:
```python
# scripts/core/schema_generator.py
from sqlalchemy import MetaData, create_engine
from scripts.core.schemas import Base

def generate_schema_from_models():
    """Generate SQL from Pydantic/SQLAlchemy models"""
    engine = create_engine('postgresql://...')
    metadata = MetaData()
    
    # Create all tables from models
    Base.metadata.create_all(engine)
    
    # Export to SQL file
    with open('generated_schema.sql', 'w') as f:
        for table in metadata.sorted_tables:
            f.write(str(CreateTable(table).compile(engine)))
```

### 2. Implement Strict Validation Layer

**Create a validation system that runs before any database operation**:

```python
# scripts/core/conformance_validator.py
class ConformanceValidator:
    def __init__(self, db_url: str):
        self.engine = create_engine(db_url)
        self.inspector = inspect(self.engine)
    
    def validate_complete_conformance(self) -> ConformanceReport:
        """Validate every aspect of conformance"""
        errors = []
        
        # 1. Check table names
        for model in [SourceDocumentModel, ChunkModel, ...]:
            table_name = model.__tablename__
            if table_name not in self.inspector.get_table_names():
                errors.append(f"Missing table: {table_name}")
        
        # 2. Check column names and types
        for model in all_models:
            self._validate_columns(model, errors)
        
        # 3. Check constraints
        for model in all_models:
            self._validate_constraints(model, errors)
        
        return ConformanceReport(errors=errors)
    
    def enforce_conformance(self):
        """Auto-fix any conformance issues"""
        report = self.validate_complete_conformance()
        for error in report.errors:
            self._fix_error(error)
```

### 3. Type Mapping System

**Implement bidirectional type mapping**:

```python
# scripts/core/type_mapper.py
class TypeMapper:
    # Pydantic to PostgreSQL
    PYDANTIC_TO_PG = {
        "UUID4": "UUID",
        "str": "TEXT",
        "int": "INTEGER",
        "float": "DOUBLE PRECISION",
        "datetime": "TIMESTAMP WITH TIME ZONE",
        "List[float]": "DOUBLE PRECISION[]",
        "Dict[str, Any]": "JSONB",
        "ProcessingStatus": "TEXT CHECK (processing_status IN (...))"
    }
    
    # PostgreSQL to Pydantic
    PG_TO_PYDANTIC = {
        "uuid": UUID4,
        "text": str,
        "varchar": str,
        "integer": int,
        "bigint": int,
        "jsonb": Dict[str, Any],
        "timestamp with time zone": datetime
    }
    
    @classmethod
    def validate_field_type(cls, pydantic_type, pg_type) -> bool:
        """Check if types are compatible"""
        expected_pg = cls.PYDANTIC_TO_PG.get(pydantic_type.__name__)
        return pg_type.upper() == expected_pg
```

### 4. Migration Strategy

**Step 1: Backup current data**
```bash
pg_dump -h $RDS_HOST -U $RDS_USER -d $RDS_DB > backup_before_conformance.sql
```

**Step 2: Generate conformant schema**
```python
# scripts/database/generate_conformant_schema.py
def generate_conformant_schema():
    """Generate schema that exactly matches Pydantic models"""
    
    sql = []
    
    # 1. Drop non-conformant tables
    sql.append("-- Drop non-conformant tables")
    for old_name in ['documents', 'chunks', 'neo4j_chunks']:
        sql.append(f"DROP TABLE IF EXISTS {old_name} CASCADE;")
    
    # 2. Create tables from models
    for model in [SourceDocumentModel, ChunkModel, ...]:
        sql.append(create_table_from_model(model))
    
    # 3. Add indexes
    sql.append(generate_indexes())
    
    # 4. Add triggers
    sql.append(generate_triggers())
    
    return '\n'.join(sql)
```

**Step 3: Apply migration with validation**
```python
# scripts/database/apply_conformance.py
def apply_conformance_migration():
    """Apply schema changes with validation"""
    
    # 1. Validate current state
    validator = ConformanceValidator(db_url)
    before_report = validator.validate_complete_conformance()
    
    # 2. Apply migration
    execute_sql_file('conformant_schema.sql')
    
    # 3. Validate after migration
    after_report = validator.validate_complete_conformance()
    
    # 4. Ensure no errors remain
    if after_report.has_errors():
        raise ConformanceError("Migration failed to achieve conformance")
```

### 5. Runtime Enforcement

**Implement decorator for all database operations**:

```python
# scripts/core/conformance_decorator.py
def ensure_conformance(func):
    """Decorator that validates conformance before DB operations"""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # 1. Get model from function context
        model = extract_model_from_args(args, kwargs)
        
        # 2. Validate model fields match database
        validator = get_conformance_validator()
        if not validator.validate_model(model):
            raise ConformanceError(f"Model {model.__name__} not conformant")
        
        # 3. Execute function
        return func(*args, **kwargs)
    
    return wrapper

# Usage in db.py
@ensure_conformance
def create_document(self, document: SourceDocumentModel):
    """Create document with conformance guarantee"""
    return self.db.add(document)
```

### 6. Continuous Integration Checks

**Add pre-commit hooks**:
```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: check-schema-conformance
        name: Check Pydantic-RDS Conformance
        entry: python scripts/test_schema_conformance.py
        language: system
        files: '^scripts/core/.*\.py$'
```

**Add CI/CD validation**:
```yaml
# .github/workflows/conformance.yml
name: Schema Conformance Check
on: [push, pull_request]

jobs:
  check-conformance:
    runs-on: ubuntu-latest
    steps:
      - name: Check out code
        uses: actions/checkout@v2
      
      - name: Set up test database
        run: |
          docker run -d -p 5432:5432 postgres:15
          psql -f scripts/database/create_conformant_schema.sql
      
      - name: Run conformance tests
        run: |
          python scripts/test_schema_conformance.py
          python scripts/verify_rds_schema_conformance.py
```

### 7. Model Evolution Process

**When adding new fields or models**:

1. **Update Pydantic model first**:
```python
# scripts/core/schemas.py
class SourceDocumentModel(BaseModel):
    # New field
    vector_embedding: Optional[List[float]] = Field(None, description="Document embedding")
```

2. **Generate migration**:
```python
# scripts/database/generate_migration.py
def generate_migration_for_model_changes():
    """Compare models to database and generate migration"""
    
    current_schema = inspect_database()
    model_schema = extract_schema_from_models()
    
    migration = []
    for diff in compare_schemas(current_schema, model_schema):
        if diff.type == 'add_column':
            migration.append(f"ALTER TABLE {diff.table} ADD COLUMN {diff.column} {diff.type};")
    
    return migration
```

3. **Validate migration**:
```python
def validate_migration(migration_sql):
    """Test migration on copy of database"""
    
    # Create test database
    create_test_db_from_backup()
    
    # Apply migration
    execute_migration(migration_sql)
    
    # Run conformance check
    validator = ConformanceValidator(test_db_url)
    report = validator.validate_complete_conformance()
    
    if report.has_errors():
        raise MigrationError("Migration breaks conformance")
```

## Implementation Checklist

1. **Immediate Actions**:
   - [ ] Run `test_schema_conformance.py` to identify all current mismatches
   - [ ] Backup existing RDS data
   - [ ] Choose `create_conformant_schema.sql` as the target schema

2. **Schema Alignment**:
   - [ ] Update all Pydantic models to match conformant schema exactly
   - [ ] Remove duplicate foreign key fields (keep only UUID versions)
   - [ ] Ensure all enum values are defined in CHECK constraints

3. **Validation Implementation**:
   - [ ] Implement `ConformanceValidator` class
   - [ ] Add conformance checking to all database operations
   - [ ] Create automated tests for each model

4. **Migration Execution**:
   - [ ] Generate migration script from model differences
   - [ ] Test migration on staging environment
   - [ ] Apply migration to production RDS

5. **Continuous Enforcement**:
   - [ ] Add pre-commit hooks for model changes
   - [ ] Implement CI/CD conformance checks
   - [ ] Document model evolution process

## Success Criteria

Absolute conformance is achieved when:

1. **Zero Runtime Errors**: No `AttributeError`, `KeyError`, or type conversion errors
2. **All Tests Pass**: `test_schema_conformance.py` reports 100% conformance
3. **Bidirectional Compatibility**: 
   - All model fields exist in database
   - All database columns have corresponding model fields
   - All types are perfectly mapped
4. **Automated Enforcement**: Any deviation is caught before deployment

## Monitoring Conformance

```python
# scripts/cli/admin.py conformance-check
def conformance_check():
    """Real-time conformance monitoring"""
    
    validator = ConformanceValidator(get_db_url())
    report = validator.validate_complete_conformance()
    
    print(f"Conformance Status: {'✅ PERFECT' if not report.has_errors() else '❌ ERRORS'}")
    
    if report.has_errors():
        for error in report.errors:
            print(f"  - {error}")
    
    return 0 if not report.has_errors() else 1
```

## Conclusion

Achieving absolute Pydantic-RDS conformance requires:

1. **Single source of truth** (Pydantic models)
2. **Automated validation** at multiple levels
3. **Strict type mapping** between Python and PostgreSQL
4. **Continuous enforcement** through CI/CD
5. **Clear evolution process** for model changes

With these changes implemented, the system will have zero tolerance for schema mismatches, ensuring perfect reliability of database operations.