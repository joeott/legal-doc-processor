# Context 251: RDS Verification and Conformance Implementation Plan

## Executive Summary

This document outlines a systematic approach to verify the current state of the RDS database and implement conformance with the script requirements. The plan addresses critical schema mismatches between the deployed RDS instance and the application's expectations.

## Current State Analysis

### 1. Critical Issues Identified

#### Schema Mismatch
- **RDS Has**: Simplified 7-table schema (projects, documents, chunks, entities, relationships, processing_logs, schema_version)
- **Scripts Expect**: Complex 15+ table schema with different naming conventions
- **Impact**: Complete database operation failure - no table/column mapping exists

#### Naming Convention Conflicts
- Scripts use verbose naming: `source_documents`, `document_chunks`, `entity_mentions`
- RDS uses simplified naming: `documents`, `chunks`, `entities`
- No mapping layer currently exists

#### Model Misalignment
- SQLAlchemy models in `db.py` expect original schema
- Pydantic models in `core/schemas.py` validate against wrong structure
- PDF pipeline tasks fail due to missing tables

### 2. Working Infrastructure
- RDS Connection: Verified working via SSH tunnel
- Bastion Host: Operational (54.162.223.205)
- Port Forwarding: Local 5433 → RDS 5432
- Credentials: Confirmed valid

## Implementation Plan

### Phase 1: Verification (Day 1)

#### 1.1 Current State Documentation
```bash
# Connect to RDS and document actual schema
psql -h localhost -p 5433 -U app_user -d legal_doc_processing

# Export current schema
pg_dump --schema-only -h localhost -p 5433 -U app_user -d legal_doc_processing > current_rds_schema.sql

# Generate schema report
python scripts/database/schema_reflection.py > schema_analysis.json
```

#### 1.2 Gap Analysis
- Compare `current_rds_schema.sql` with `scripts/create_rds_schema.sql`
- Document all table/column differences
- Identify missing constraints, indexes, and triggers
- Create conformance report

#### 1.3 Risk Assessment
- Identify data migration requirements
- Assess impact on running systems
- Plan rollback procedures
- Document dependencies

### Phase 2: Quick Fixes (Day 1-2)

#### 2.1 Database Views Implementation
Create mapping views for immediate functionality:

```sql
-- Core mapping views
CREATE OR REPLACE VIEW source_documents AS 
SELECT 
    uuid as id,
    uuid,
    project_uuid as project_id,
    name as file_name,
    type as document_type,
    status as processing_status,
    created_at,
    updated_at
FROM documents;

CREATE OR REPLACE VIEW document_chunks AS
SELECT 
    uuid as id,
    uuid,
    document_uuid as source_document_id,
    chunk_index,
    content as text,
    metadata,
    created_at,
    updated_at
FROM chunks;

CREATE OR REPLACE VIEW entity_mentions AS
SELECT 
    uuid as id,
    uuid,
    chunk_uuid as chunk_id,
    name as text,
    type as entity_type,
    metadata as confidence,
    created_at,
    updated_at
FROM entities;

-- Additional required views
CREATE OR REPLACE VIEW canonical_entities AS
SELECT DISTINCT ON (name, type)
    uuid as id,
    uuid,
    name,
    type as entity_type,
    metadata as attributes,
    created_at,
    updated_at
FROM entities
ORDER BY name, type, created_at;

CREATE OR REPLACE VIEW relationship_staging AS
SELECT 
    uuid as id,
    uuid,
    source_entity_uuid,
    target_entity_uuid,
    type as relationship_type,
    metadata as properties,
    created_at,
    updated_at
FROM relationships;
```

#### 2.2 Missing Tables Creation
Add critical missing tables:

```sql
-- Textract job tracking
CREATE TABLE IF NOT EXISTS textract_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES documents(uuid),
    job_id VARCHAR(255) NOT NULL,
    status VARCHAR(50) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP WITH TIME ZONE,
    error_message TEXT,
    result_data JSONB
);

-- Import sessions
CREATE TABLE IF NOT EXISTS import_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_name VARCHAR(255) NOT NULL,
    manifest_data JSONB NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    started_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP WITH TIME ZONE,
    documents_processed INTEGER DEFAULT 0,
    documents_total INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0
);

-- Processing tasks (Celery)
CREATE TABLE IF NOT EXISTS processing_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id VARCHAR(255) UNIQUE NOT NULL,
    task_name VARCHAR(255) NOT NULL,
    document_id UUID REFERENCES documents(uuid),
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP WITH TIME ZONE,
    result JSONB,
    error_message TEXT,
    retry_count INTEGER DEFAULT 0
);
```

### Phase 3: Code Layer Adaptation (Day 2-3)

#### 3.1 Database Connection Layer
Create adaptive database manager:

```python
# scripts/database/adaptive_db_manager.py
class AdaptiveDBManager:
    """Database manager that adapts between schema versions"""
    
    TABLE_MAPPING = {
        'source_documents': 'documents',
        'document_chunks': 'chunks',
        'entity_mentions': 'entities',
        'canonical_entities': 'entities',  # Uses view
        'relationship_staging': 'relationships'
    }
    
    COLUMN_MAPPING = {
        'source_documents': {
            'id': 'uuid',
            'project_id': 'project_uuid',
            'file_name': 'name',
            'document_type': 'type',
            'processing_status': 'status'
        },
        'document_chunks': {
            'id': 'uuid',
            'source_document_id': 'document_uuid',
            'text': 'content'
        }
    }
    
    def get_table_name(self, model_table: str) -> str:
        """Map model table name to actual RDS table"""
        return self.TABLE_MAPPING.get(model_table, model_table)
    
    def map_columns(self, model_table: str, data: dict) -> dict:
        """Map model columns to RDS columns"""
        if model_table in self.COLUMN_MAPPING:
            mapping = self.COLUMN_MAPPING[model_table]
            return {mapping.get(k, k): v for k, v in data.items()}
        return data
```

#### 3.2 Model Updates
Update Pydantic models to handle both schemas:

```python
# scripts/core/adaptive_models.py
class AdaptiveBaseModel(BaseModel):
    """Base model that adapts between schema versions"""
    
    class Config:
        allow_population_by_field_name = True
        
    @validator('*', pre=True)
    def map_field_names(cls, v, field):
        """Map between different field naming conventions"""
        # Implementation for field mapping
        return v
```

### Phase 4: Schema Conformance Engine (Day 3-4)

#### 4.1 Automated Conformance Validator
Implement comprehensive validation:

```python
# scripts/database/conformance_engine.py
class RDSConformanceEngine:
    """Validates and enforces schema conformance"""
    
    def validate_schema(self) -> ConformanceReport:
        """Complete schema validation"""
        report = ConformanceReport()
        
        # Check tables
        report.tables = self._validate_tables()
        
        # Check columns
        report.columns = self._validate_columns()
        
        # Check constraints
        report.constraints = self._validate_constraints()
        
        # Check indexes
        report.indexes = self._validate_indexes()
        
        # Check permissions
        report.permissions = self._validate_permissions()
        
        return report
    
    def apply_fixes(self, report: ConformanceReport):
        """Apply automatic fixes where possible"""
        for issue in report.get_fixable_issues():
            self._apply_fix(issue)
```

#### 4.2 Migration Scripts
Create incremental migration scripts:

```sql
-- migrations/001_add_missing_columns.sql
ALTER TABLE documents ADD COLUMN IF NOT EXISTS s3_key VARCHAR(500);
ALTER TABLE documents ADD COLUMN IF NOT EXISTS ocr_status VARCHAR(50);
ALTER TABLE documents ADD COLUMN IF NOT EXISTS processing_metadata JSONB;

-- migrations/002_add_indexes.sql
CREATE INDEX IF NOT EXISTS idx_documents_project_uuid ON documents(project_uuid);
CREATE INDEX IF NOT EXISTS idx_chunks_document_uuid ON chunks(document_uuid);
CREATE INDEX IF NOT EXISTS idx_entities_chunk_uuid ON entities(chunk_uuid);

-- migrations/003_add_constraints.sql
ALTER TABLE documents ADD CONSTRAINT check_status 
CHECK (status IN ('pending', 'processing', 'completed', 'failed'));
```

### Phase 5: Testing and Validation (Day 4-5)

#### 5.1 Unit Tests
```python
# tests/test_schema_conformance.py
def test_view_mapping():
    """Test that views correctly map to underlying tables"""
    
def test_column_mapping():
    """Test that column mappings work correctly"""
    
def test_model_operations():
    """Test CRUD operations through adapted models"""
```

#### 5.2 Integration Tests
```python
# tests/test_pipeline_integration.py
def test_document_processing_flow():
    """Test complete document processing through adapted schema"""
    
def test_entity_extraction_flow():
    """Test entity extraction with schema mapping"""
```

#### 5.3 Performance Testing
- Measure view performance impact
- Test query optimization
- Validate index effectiveness

### Phase 6: Deployment (Day 5)

#### 6.1 Deployment Steps
1. **Backup Current RDS**
   ```bash
   pg_dump -h localhost -p 5433 -U app_user -d legal_doc_processing > backup_$(date +%Y%m%d).sql
   ```

2. **Apply Schema Changes**
   ```bash
   # Apply views
   psql -h localhost -p 5433 -U app_user -d legal_doc_processing -f create_mapping_views.sql
   
   # Apply missing tables
   psql -h localhost -p 5433 -U app_user -d legal_doc_processing -f create_missing_tables.sql
   
   # Apply migrations
   for f in migrations/*.sql; do
     psql -h localhost -p 5433 -U app_user -d legal_doc_processing -f "$f"
   done
   ```

3. **Deploy Code Changes**
   ```bash
   # Update database manager
   cp scripts/database/adaptive_db_manager.py scripts/db.py
   
   # Update models
   cp scripts/core/adaptive_models.py scripts/core/schemas.py
   ```

4. **Verify Deployment**
   ```bash
   python scripts/verify_rds_schema_conformance.py
   python scripts/test_schema_conformance.py
   ```

#### 6.2 Rollback Plan
1. Restore from backup if critical issues
2. Remove views if performance problems
3. Revert code changes if functionality breaks

### Phase 7: Long-term Solutions (Week 2+)

#### 7.1 Schema Standardization
- Decision: Align on single schema standard
- Migration: Gradual transition to chosen schema
- Documentation: Update all schema documentation

#### 7.2 Performance Optimization
- Replace views with native tables
- Optimize queries for new structure
- Implement query caching

#### 7.3 Monitoring Implementation
- Schema drift detection
- Performance monitoring
- Automated conformance checks

## Success Criteria

### Immediate (Phase 1-2)
- [ ] Database operations functional through views
- [ ] PDF pipeline can process documents
- [ ] No data loss or corruption

### Short-term (Phase 3-4)
- [ ] All models work with adapted schema
- [ ] Conformance engine operational
- [ ] Automated validation passing

### Long-term (Phase 5+)
- [ ] Single standardized schema
- [ ] Full test coverage
- [ ] Performance metrics met
- [ ] Zero schema drift

## Risk Mitigation

### High-Risk Areas
1. **View Performance**: Monitor query times, optimize as needed
2. **Data Integrity**: Validate all mappings preserve data
3. **Transaction Boundaries**: Test view transactions thoroughly
4. **Cascade Operations**: Verify foreign key behaviors

### Mitigation Strategies
1. Comprehensive backup before changes
2. Staged rollout with testing
3. Monitoring at each phase
4. Clear rollback procedures

## Timeline Summary

- **Day 1**: Verification and documentation
- **Day 1-2**: Quick fixes (views and missing tables)
- **Day 2-3**: Code layer adaptation
- **Day 3-4**: Conformance engine implementation
- **Day 4-5**: Testing and validation
- **Day 5**: Production deployment
- **Week 2+**: Long-term standardization

## Next Steps

1. Execute Phase 1 verification immediately
2. Prepare SQL scripts for Phase 2
3. Begin code adaptation in parallel
4. Schedule testing resources
5. Plan deployment window

This plan provides a path from the current non-functional state to a fully conformant and operational RDS database while minimizing risk and downtime.