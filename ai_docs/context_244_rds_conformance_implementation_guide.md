# Context 244: RDS Conformance Implementation Guide

**Date**: 2025-05-30
**Type**: Implementation Strategy
**Status**: CRITICAL PATH
**Component**: Complete RDS Schema Conformance to Script Requirements

## Executive Summary

This guide details the implementation strategy to conform the RDS PostgreSQL database to match the exact requirements of the existing scripts, preserving the SSH-based connection advantages while supporting the sophisticated document processing pipeline.

## Core Principle

**Scripts Define Reality**: The scripts represent hundreds of hours of development and testing. We will conform the database to match their expectations exactly, rather than rewriting proven code.

## Complete Schema Requirements

### 1. Primary Tables (Expected by Scripts)

```sql
-- 1. Projects table with script-expected structure
CREATE TABLE IF NOT EXISTS projects (
    id SERIAL PRIMARY KEY,
    project_uuid UUID UNIQUE NOT NULL DEFAULT gen_random_uuid(),
    supabase_project_id UUID,  -- Legacy compatibility
    name TEXT NOT NULL,
    client_name TEXT,
    matter_type TEXT,
    data_layer TEXT DEFAULT 'production',
    airtable_id TEXT,
    metadata JSONB DEFAULT '{}',
    active BOOLEAN DEFAULT true,
    script_run_count INTEGER DEFAULT 0,
    processed_by_scripts BOOLEAN DEFAULT false,
    last_synced_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 2. Source documents (main document table)
CREATE TABLE IF NOT EXISTS source_documents (
    id SERIAL PRIMARY KEY,
    document_uuid UUID UNIQUE NOT NULL DEFAULT gen_random_uuid(),
    project_uuid UUID REFERENCES projects(project_uuid) ON DELETE CASCADE,
    project_fk_id INTEGER REFERENCES projects(id),  -- Scripts expect integer FK
    import_session_id UUID,
    
    -- File information
    filename TEXT NOT NULL,
    original_filename TEXT,
    original_file_path TEXT,
    file_path TEXT,
    file_type TEXT,
    detected_file_type TEXT,
    file_size_bytes BIGINT,
    
    -- S3 storage
    s3_key TEXT,
    s3_bucket TEXT,
    s3_region TEXT DEFAULT 'us-east-1',
    s3_key_public TEXT,
    s3_bucket_public TEXT,
    
    -- Processing status
    processing_status TEXT DEFAULT 'pending',
    initial_processing_status TEXT,
    celery_status TEXT,
    celery_task_id TEXT,
    
    -- Extracted content
    raw_extracted_text TEXT,
    markdown_text TEXT,
    cleaned_text TEXT,
    
    -- OCR metadata
    ocr_metadata_json JSONB DEFAULT '{}',
    ocr_provider TEXT,
    ocr_completed_at TIMESTAMP WITH TIME ZONE,
    ocr_processing_seconds NUMERIC,
    ocr_confidence_score NUMERIC,
    
    -- Textract specific
    textract_job_id TEXT,
    textract_job_status TEXT,
    textract_start_time TIMESTAMP WITH TIME ZONE,
    textract_end_time TIMESTAMP WITH TIME ZONE,
    textract_page_count INTEGER,
    textract_error_message TEXT,
    
    -- Audio/transcription
    transcription_metadata_json JSONB DEFAULT '{}',
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 3. Import sessions
CREATE TABLE IF NOT EXISTS import_sessions (
    id SERIAL PRIMARY KEY,
    session_uuid UUID UNIQUE NOT NULL DEFAULT gen_random_uuid(),
    project_uuid UUID REFERENCES projects(project_uuid),
    manifest_data JSONB NOT NULL,
    total_documents INTEGER DEFAULT 0,
    processed_documents INTEGER DEFAULT 0,
    failed_documents INTEGER DEFAULT 0,
    status TEXT DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP WITH TIME ZONE
);

-- 4. Neo4j documents (for graph representation)
CREATE TABLE IF NOT EXISTS neo4j_documents (
    id SERIAL PRIMARY KEY,
    document_uuid UUID REFERENCES source_documents(document_uuid) ON DELETE CASCADE,
    neo4j_node_id TEXT,
    title TEXT,
    document_type TEXT,
    summary TEXT,
    key_entities JSONB DEFAULT '[]',
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 5. Document chunks
CREATE TABLE IF NOT EXISTS document_chunks (
    id SERIAL PRIMARY KEY,
    chunk_uuid UUID UNIQUE NOT NULL DEFAULT gen_random_uuid(),
    document_uuid UUID REFERENCES source_documents(document_uuid) ON DELETE CASCADE,
    document_fk_id INTEGER REFERENCES source_documents(id),
    chunk_index INTEGER NOT NULL,
    chunk_number INTEGER,
    
    -- Content
    text_content TEXT NOT NULL,
    cleaned_text TEXT,
    
    -- Position
    char_start_index INTEGER,
    char_end_index INTEGER,
    start_page INTEGER,
    end_page INTEGER,
    
    -- Metadata
    metadata_json JSONB DEFAULT '{}',
    chunk_type TEXT DEFAULT 'text',
    
    -- Embeddings (can be stored here or separate table)
    embedding_vector FLOAT[],
    embedding_model TEXT,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 6. Entity mentions (raw entities)
CREATE TABLE IF NOT EXISTS entity_mentions (
    id SERIAL PRIMARY KEY,
    mention_uuid UUID UNIQUE NOT NULL DEFAULT gen_random_uuid(),
    document_uuid UUID REFERENCES source_documents(document_uuid) ON DELETE CASCADE,
    chunk_uuid UUID REFERENCES document_chunks(chunk_uuid) ON DELETE CASCADE,
    chunk_fk_id INTEGER REFERENCES document_chunks(id),
    
    -- Entity data
    entity_text TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_subtype TEXT,
    
    -- Position
    start_char INTEGER,
    end_char INTEGER,
    
    -- Confidence and metadata
    confidence_score FLOAT DEFAULT 0.0,
    extraction_method TEXT,
    processing_metadata JSONB DEFAULT '{}',
    
    -- Canonical reference
    canonical_entity_uuid UUID,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 7. Canonical entities (resolved entities)
CREATE TABLE IF NOT EXISTS canonical_entities (
    id SERIAL PRIMARY KEY,
    canonical_entity_uuid UUID UNIQUE NOT NULL DEFAULT gen_random_uuid(),
    entity_type TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    
    -- Resolution data
    mention_count INTEGER DEFAULT 1,
    confidence_score FLOAT DEFAULT 0.0,
    resolution_method TEXT,
    
    -- Additional info
    aliases JSONB DEFAULT '[]',
    properties JSONB DEFAULT '{}',
    metadata JSONB DEFAULT '{}',
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 8. Relationship staging
CREATE TABLE IF NOT EXISTS relationship_staging (
    id SERIAL PRIMARY KEY,
    source_entity_uuid UUID REFERENCES canonical_entities(canonical_entity_uuid),
    target_entity_uuid UUID REFERENCES canonical_entities(canonical_entity_uuid),
    relationship_type TEXT NOT NULL,
    confidence_score FLOAT DEFAULT 0.0,
    
    -- Context
    source_chunk_uuid UUID REFERENCES document_chunks(chunk_uuid),
    evidence_text TEXT,
    
    -- Metadata
    properties JSONB DEFAULT '{}',
    metadata JSONB DEFAULT '{}',
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(source_entity_uuid, target_entity_uuid, relationship_type)
);

-- 9. Textract jobs
CREATE TABLE IF NOT EXISTS textract_jobs (
    id SERIAL PRIMARY KEY,
    job_id TEXT UNIQUE NOT NULL,
    document_uuid UUID REFERENCES source_documents(document_uuid),
    job_type TEXT DEFAULT 'DetectDocumentText',
    status TEXT DEFAULT 'IN_PROGRESS',
    
    -- Timing
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    
    -- Results
    page_count INTEGER,
    result_s3_key TEXT,
    error_message TEXT,
    metadata JSONB DEFAULT '{}'
);

-- 10. Chunk embeddings
CREATE TABLE IF NOT EXISTS chunk_embeddings (
    id SERIAL PRIMARY KEY,
    chunk_uuid UUID REFERENCES document_chunks(chunk_uuid) ON DELETE CASCADE,
    embedding_vector FLOAT[] NOT NULL,
    model_name TEXT NOT NULL,
    model_version TEXT,
    dimensions INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(chunk_uuid, model_name)
);

-- 11. Canonical entity embeddings
CREATE TABLE IF NOT EXISTS canonical_entity_embeddings (
    id SERIAL PRIMARY KEY,
    canonical_entity_uuid UUID REFERENCES canonical_entities(canonical_entity_uuid) ON DELETE CASCADE,
    embedding_vector FLOAT[] NOT NULL,
    model_name TEXT NOT NULL,
    model_version TEXT,
    dimensions INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(canonical_entity_uuid, model_name)
);

-- 12. Document processing history
CREATE TABLE IF NOT EXISTS document_processing_history (
    id SERIAL PRIMARY KEY,
    document_uuid UUID REFERENCES source_documents(document_uuid) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    event_status TEXT,
    event_data JSONB DEFAULT '{}',
    error_message TEXT,
    processing_time_seconds NUMERIC,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

### 2. Indexes for Performance

```sql
-- Critical performance indexes
CREATE INDEX idx_source_documents_project_uuid ON source_documents(project_uuid);
CREATE INDEX idx_source_documents_processing_status ON source_documents(processing_status);
CREATE INDEX idx_source_documents_created_at ON source_documents(created_at DESC);

CREATE INDEX idx_document_chunks_document_uuid ON document_chunks(document_uuid);
CREATE INDEX idx_document_chunks_chunk_index ON document_chunks(document_uuid, chunk_index);

CREATE INDEX idx_entity_mentions_document_uuid ON entity_mentions(document_uuid);
CREATE INDEX idx_entity_mentions_chunk_uuid ON entity_mentions(chunk_uuid);
CREATE INDEX idx_entity_mentions_canonical ON entity_mentions(canonical_entity_uuid);
CREATE INDEX idx_entity_mentions_type ON entity_mentions(entity_type);

CREATE INDEX idx_canonical_entities_type ON canonical_entities(entity_type);
CREATE INDEX idx_canonical_entities_name ON canonical_entities(canonical_name);

CREATE INDEX idx_relationship_staging_source ON relationship_staging(source_entity_uuid);
CREATE INDEX idx_relationship_staging_target ON relationship_staging(target_entity_uuid);
CREATE INDEX idx_relationship_staging_type ON relationship_staging(relationship_type);

CREATE INDEX idx_textract_jobs_document ON textract_jobs(document_uuid);
CREATE INDEX idx_textract_jobs_status ON textract_jobs(status);

-- Full text search indexes
CREATE INDEX idx_source_documents_text_search ON source_documents USING gin(to_tsvector('english', raw_extracted_text));
CREATE INDEX idx_document_chunks_text_search ON document_chunks USING gin(to_tsvector('english', text_content));
```

### 3. Triggers and Functions

```sql
-- Update timestamp trigger
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Apply to relevant tables
CREATE TRIGGER update_projects_updated_at BEFORE UPDATE ON projects
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_source_documents_updated_at BEFORE UPDATE ON source_documents
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_neo4j_documents_updated_at BEFORE UPDATE ON neo4j_documents
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_document_chunks_updated_at BEFORE UPDATE ON document_chunks
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_canonical_entities_updated_at BEFORE UPDATE ON canonical_entities
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Auto-populate integer foreign keys
CREATE OR REPLACE FUNCTION populate_integer_fks()
RETURNS TRIGGER AS $$
BEGIN
    -- For source_documents
    IF TG_TABLE_NAME = 'source_documents' AND NEW.project_uuid IS NOT NULL THEN
        SELECT id INTO NEW.project_fk_id FROM projects WHERE project_uuid = NEW.project_uuid;
    END IF;
    
    -- For document_chunks
    IF TG_TABLE_NAME = 'document_chunks' AND NEW.document_uuid IS NOT NULL THEN
        SELECT id INTO NEW.document_fk_id FROM source_documents WHERE document_uuid = NEW.document_uuid;
    END IF;
    
    -- For entity_mentions
    IF TG_TABLE_NAME = 'entity_mentions' AND NEW.chunk_uuid IS NOT NULL THEN
        SELECT id INTO NEW.chunk_fk_id FROM document_chunks WHERE chunk_uuid = NEW.chunk_uuid;
    END IF;
    
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER populate_source_documents_fks BEFORE INSERT OR UPDATE ON source_documents
    FOR EACH ROW EXECUTE FUNCTION populate_integer_fks();

CREATE TRIGGER populate_document_chunks_fks BEFORE INSERT OR UPDATE ON document_chunks
    FOR EACH ROW EXECUTE FUNCTION populate_integer_fks();

CREATE TRIGGER populate_entity_mentions_fks BEFORE INSERT OR UPDATE ON entity_mentions
    FOR EACH ROW EXECUTE FUNCTION populate_integer_fks();
```

## RDS Configuration Optimization

### 1. Instance Configuration

```yaml
Instance Type: db.r6g.xlarge  # 4 vCPU, 32 GB RAM
Storage: 500 GB gp3 (3000 IOPS, 125 MB/s throughput)
PostgreSQL Version: 17.2

Parameter Group Settings:
  shared_buffers: 8GB  # 25% of RAM
  effective_cache_size: 24GB  # 75% of RAM
  work_mem: 64MB
  maintenance_work_mem: 2GB
  max_connections: 200
  max_parallel_workers: 4
  max_parallel_workers_per_gather: 2
  
  # For large text operations
  temp_buffers: 32MB
  max_wal_size: 4GB
  min_wal_size: 1GB
  checkpoint_completion_target: 0.9
  
  # For JSONB operations
  gin_fuzzy_search_limit: 1000
  
  # Connection pooling
  idle_in_transaction_session_timeout: 300000  # 5 minutes
  statement_timeout: 300000  # 5 minutes
```

### 2. Connection Pool Configuration

```python
# scripts/config.py additions
# Optimized for SSH tunnel operations
DB_POOL_CONFIG = {
    'pool_size': 20,  # Base connections
    'max_overflow': 30,  # Additional connections under load
    'pool_timeout': 30,  # Wait time for connection
    'pool_recycle': 3600,  # Recycle connections hourly
    'pool_pre_ping': True,  # Verify connections before use
    'connect_args': {
        'connect_timeout': 10,
        'options': '-c statement_timeout=300000',  # 5 min timeout
        'keepalives': 1,
        'keepalives_idle': 30,
        'keepalives_interval': 10,
        'keepalives_count': 5
    }
}
```

### 3. SSH Tunnel Optimization

```bash
# Enhanced SSH tunnel with compression and keep-alive
ssh -f -N -C \
    -o ServerAliveInterval=60 \
    -o ServerAliveCountMax=3 \
    -o TCPKeepAlive=yes \
    -o Compression=yes \
    -o CompressionLevel=6 \
    -L 5433:database1.cuviucyodbeg.us-east-1.rds.amazonaws.com:5432 \
    -i resources/aws/legal-doc-processor-bastion.pem \
    ubuntu@54.162.223.205
```

## Script Conformance Updates

### 1. Database Connection Enhancement

```python
# scripts/db.py modifications
import psycopg2.pool
from contextlib import contextmanager

class DatabaseManager:
    """Enhanced database manager for SSH-based RDS connections."""
    
    def __init__(self, validate_conformance=True):
        # Use connection pooling for SSH connections
        self.pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=5,
            maxconn=50,
            host='localhost',  # SSH tunnel
            port=5433,         # Tunnel port
            database='legal_doc_processing',
            user='app_user',
            password='LegalDoc2025!Secure',
            **DB_POOL_CONFIG['connect_args']
        )
        
        # SQLAlchemy engine for ORM operations
        self.engine = create_engine(
            DATABASE_URL,
            **DB_POOL_CONFIG
        )
        
        if validate_conformance:
            self._validate_schema_conformance()
    
    @contextmanager
    def get_connection(self):
        """Get connection from pool with automatic return."""
        conn = self.pool.getconn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self.pool.putconn(conn)
    
    def bulk_insert(self, table: str, records: List[Dict]) -> int:
        """Optimized bulk insert for SSH connections."""
        if not records:
            return 0
            
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                # Use COPY for maximum performance
                columns = list(records[0].keys())
                
                # Create temp file for COPY
                import io
                import csv
                
                output = io.StringIO()
                writer = csv.DictWriter(output, fieldnames=columns)
                writer.writerows(records)
                output.seek(0)
                
                # COPY data
                cur.copy_expert(
                    f"COPY {table} ({','.join(columns)}) FROM STDIN WITH CSV",
                    output
                )
                
                return cur.rowcount
```

### 2. Optimized Chunking for Large Documents

```python
# scripts/chunking_utils.py enhancements
def chunk_document_optimized(text: str, max_chunk_size: int = 2000) -> List[Dict]:
    """Optimized chunking for SSH-based operations."""
    chunks = []
    
    # Use connection-efficient batch processing
    with DatabaseManager().get_connection() as conn:
        with conn.cursor() as cur:
            # Create temporary table for processing
            cur.execute("""
                CREATE TEMP TABLE temp_chunks (
                    chunk_index INTEGER,
                    text_content TEXT,
                    char_start INTEGER,
                    char_end INTEGER
                )
            """)
            
            # Process chunks in database
            for i, chunk in enumerate(semantic_chunk_text(text, max_chunk_size)):
                cur.execute("""
                    INSERT INTO temp_chunks VALUES (%s, %s, %s, %s)
                """, (i, chunk['text'], chunk['start'], chunk['end']))
            
            # Retrieve processed chunks
            cur.execute("SELECT * FROM temp_chunks ORDER BY chunk_index")
            chunks = [
                {
                    'chunk_index': row[0],
                    'text_content': row[1],
                    'char_start_index': row[2],
                    'char_end_index': row[3]
                }
                for row in cur.fetchall()
            ]
    
    return chunks
```

### 3. Monitoring SSH Connection Health

```python
# scripts/monitoring/ssh_monitor.py
import subprocess
import time
from scripts.db import DatabaseManager

class SSHTunnelMonitor:
    """Monitor and maintain SSH tunnel health."""
    
    def __init__(self):
        self.tunnel_port = 5433
        self.bastion_host = "54.162.223.205"
        
    def check_tunnel_health(self) -> bool:
        """Check if SSH tunnel is active and responsive."""
        try:
            # Check if port is listening
            result = subprocess.run(
                ['lsof', f'-ti:{self.tunnel_port}'],
                capture_output=True,
                text=True
            )
            
            if not result.stdout.strip():
                return False
            
            # Test database connection
            db = DatabaseManager()
            with db.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    return cur.fetchone()[0] == 1
                    
        except Exception:
            return False
    
    def restart_tunnel_if_needed(self):
        """Restart tunnel if health check fails."""
        if not self.check_tunnel_health():
            self.restart_tunnel()
    
    def restart_tunnel(self):
        """Restart SSH tunnel."""
        # Kill existing tunnel
        subprocess.run(['pkill', '-f', f'ssh.*{self.tunnel_port}'])
        time.sleep(2)
        
        # Start new tunnel
        subprocess.run([
            'ssh', '-f', '-N', '-C',
            '-o', 'ServerAliveInterval=60',
            '-o', 'ServerAliveCountMax=3',
            '-L', f'{self.tunnel_port}:database1.cuviucyodbeg.us-east-1.rds.amazonaws.com:5432',
            '-i', 'resources/aws/legal-doc-processor-bastion.pem',
            f'ubuntu@{self.bastion_host}'
        ])
```

## Migration Strategy

### Phase 1: Schema Creation (Day 1)

1. **Backup existing data**:
   ```bash
   pg_dump -h localhost -p 5433 -U app_user -d legal_doc_processing > backup_$(date +%Y%m%d).sql
   ```

2. **Create new schema**:
   ```bash
   psql -h localhost -p 5433 -U app_user -d legal_doc_processing < create_conformant_schema.sql
   ```

3. **Migrate existing data**:
   ```sql
   -- Migrate projects
   INSERT INTO projects (project_uuid, name, client_name, matter_type, created_at, updated_at)
   SELECT project_uuid, name, client_name, matter_type, created_at, updated_at
   FROM projects_old;
   
   -- Migrate documents to source_documents
   INSERT INTO source_documents (document_uuid, project_uuid, filename, file_path, file_type, 
                                processing_status, raw_extracted_text, created_at, updated_at)
   SELECT document_uuid, project_uuid, filename, file_path, file_type, 
          processing_status, extracted_text, created_at, updated_at
   FROM documents;
   ```

### Phase 2: Script Validation (Day 2-3)

1. **Test each script component**:
   ```python
   # Test script
   python scripts/test_schema_conformance.py
   ```

2. **Verify Celery tasks**:
   ```bash
   celery -A scripts.celery_app worker --loglevel=info -Q ocr,text,entity,graph
   ```

3. **Run end-to-end test**:
   ```bash
   python scripts/test_single_document.py --file test.pdf
   ```

### Phase 3: Performance Optimization (Day 4-5)

1. **Analyze query patterns**:
   ```sql
   -- Enable query logging
   ALTER SYSTEM SET log_statement = 'all';
   ALTER SYSTEM SET log_duration = on;
   SELECT pg_reload_conf();
   ```

2. **Create missing indexes**:
   ```sql
   -- Based on slow query analysis
   CREATE INDEX CONCURRENTLY idx_custom ON table(columns);
   ```

3. **Optimize connection pooling**:
   ```python
   # Adjust pool sizes based on load testing
   ```

## Monitoring and Maintenance

### 1. Performance Monitoring

```sql
-- Monitor slow queries
CREATE VIEW slow_queries AS
SELECT 
    query,
    calls,
    total_time / 1000 as total_seconds,
    mean_time / 1000 as mean_seconds,
    max_time / 1000 as max_seconds
FROM pg_stat_statements
WHERE mean_time > 1000  -- Queries taking > 1 second
ORDER BY mean_time DESC;

-- Monitor table sizes
CREATE VIEW table_sizes AS
SELECT 
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size,
    pg_total_relation_size(schemaname||'.'||tablename) AS size_bytes
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;
```

### 2. Automated Health Checks

```python
# scripts/cli/health.py
@click.command()
def check_health():
    """Comprehensive health check for RDS system."""
    checks = {
        'ssh_tunnel': check_ssh_tunnel(),
        'database_connection': check_database_connection(),
        'table_conformance': check_table_conformance(),
        'index_health': check_index_health(),
        'connection_pool': check_connection_pool_health(),
        'disk_space': check_disk_space(),
        'query_performance': check_query_performance()
    }
    
    for check, result in checks.items():
        status = "✓" if result['healthy'] else "✗"
        click.echo(f"{status} {check}: {result['message']}")
```

## Cost Optimization

### 1. Storage Optimization
- Use TOAST compression for large text fields
- Implement partitioning for document_processing_history
- Archive old data to S3 after 90 days

### 2. Connection Optimization
- Use pgBouncer on bastion for connection pooling
- Implement read replicas for analytics queries
- Use prepared statements for frequent queries

### 3. Processing Optimization
- Batch insert operations (minimum 100 records)
- Use COPY instead of INSERT for bulk operations
- Implement materialized views for complex queries

## Success Metrics

1. **Schema Conformance**: 100% of expected tables exist
2. **Query Performance**: 95% of queries < 100ms
3. **Connection Stability**: 99.9% uptime for SSH tunnel
4. **Processing Throughput**: 100+ documents/hour
5. **Error Rate**: < 0.1% processing failures

## Conclusion

This implementation plan provides a complete path to conform the RDS database to the script requirements while maintaining the SSH-based connection advantages. The enhanced schema supports all sophisticated processing features while optimizing for the specific connection patterns of SSH-based access.