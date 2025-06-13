# Context 219: AWS RDS PostgreSQL Migration Plan

## Executive Summary

This document outlines a comprehensive migration plan from Supabase to AWS RDS PostgreSQL for the legal document processing pipeline. The migration will enable direct database connections for schema introspection, improve production monitoring capabilities, and provide better integration with our Redis and Neo4j infrastructure.

## Migration Objectives

1. **Enable Direct Database Access**: Support SQLAlchemy introspection for schema conformance (context_217)
2. **Improve Production Operations**: Direct query monitoring, performance tuning, and debugging
3. **Maintain High Availability**: Multi-AZ deployment for production reliability
4. **Optimize Integration**: Better coupling with Redis (ElastiCache) and future Neo4j deployment
5. **Preserve Data Integrity**: Zero data loss during migration

## Architecture Overview

### Current State (Supabase)
```
Frontend → Supabase REST API → PostgreSQL (Hidden)
                ↓
        PostgREST Layer
                ↓
        Authentication/RLS
```

### Target State (AWS RDS)
```
Frontend → Application Layer → AWS RDS PostgreSQL
                ↓                      ↓
        Direct SQL Access      Connection Pooling
                ↓                      ↓
        Schema Introspection    Performance Insights
```

## Phase 1: AWS Infrastructure Setup

### 1.1 RDS Instance Configuration

```yaml
RDS Configuration:
  Engine: PostgreSQL 15.x
  Instance Class: db.m6g.large (production) / db.t4g.medium (staging)
  Storage: 100GB SSD (gp3) with autoscaling to 1TB
  Multi-AZ: Yes (production)
  Backup Retention: 7 days
  Maintenance Window: Sunday 3:00-4:00 AM UTC
```

### 1.2 Network Configuration

```yaml
VPC Setup:
  - Create or use existing VPC with private subnets
  - RDS Subnet Group spanning 2+ AZs
  - Security Groups:
    - Inbound: PostgreSQL (5432) from application servers
    - Inbound: PostgreSQL (5432) from bastion host (management)
    - Outbound: All traffic (for updates)
```

### 1.3 Parameter Group Configuration

```sql
-- Custom Parameter Group: legal-doc-processing-pg15
max_connections = 200
shared_buffers = 256MB
effective_cache_size = 1GB
work_mem = 4MB
maintenance_work_mem = 64MB
wal_buffers = 16MB
checkpoint_completion_target = 0.9
random_page_cost = 1.1  -- For SSD storage
```

### 1.4 IAM Configuration

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "rds:DescribeDBInstances",
        "rds:DescribeDBSnapshots",
        "rds:CreateDBSnapshot",
        "rds:RestoreDBInstanceFromDBSnapshot"
      ],
      "Resource": "arn:aws:rds:*:*:db:legal-doc-processing-*"
    }
  ]
}
```

## Phase 2: Database Schema Migration

### 2.1 Export Schema from Context 203

```sql
-- Create database and extensions
CREATE DATABASE legal_doc_processing;

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";  -- For fuzzy text search
CREATE EXTENSION IF NOT EXISTS "btree_gist";  -- For exclusion constraints

-- Create custom types
CREATE TYPE processing_status AS ENUM (
    'pending',
    'processing',
    'completed',
    'failed',
    'reprocessing'
);

CREATE TYPE task_status AS ENUM (
    'pending',
    'in_progress',
    'completed',
    'failed',
    'retrying'
);
```

### 2.2 Table Creation Script

```sql
-- Projects table
CREATE TABLE projects (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    description TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Documents table
CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    file_name VARCHAR(500) NOT NULL,
    file_path VARCHAR(1000) NOT NULL,
    file_size BIGINT,
    mime_type VARCHAR(100),
    status processing_status DEFAULT 'pending',
    error_message TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMP WITH TIME ZONE
);

-- Continue with all tables from context_203...
```

### 2.3 Index Creation

```sql
-- Performance indexes
CREATE INDEX idx_documents_project_id ON documents(project_id);
CREATE INDEX idx_documents_status ON documents(status);
CREATE INDEX idx_documents_created_at ON documents(created_at DESC);
CREATE INDEX idx_processing_tasks_document_id ON processing_tasks(document_id);
CREATE INDEX idx_processing_tasks_status ON processing_tasks(task_status);
CREATE INDEX idx_entities_document_id ON entities(document_id);
CREATE INDEX idx_chunks_document_id ON chunks(document_id);

-- Full text search indexes
CREATE INDEX idx_chunks_content_gin ON chunks USING gin(to_tsvector('english', content));
CREATE INDEX idx_entities_name_trgm ON entities USING gin(name gin_trgm_ops);
```

### 2.4 Migration Functions

```sql
-- Update timestamp trigger
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Apply to all tables
CREATE TRIGGER update_projects_updated_at BEFORE UPDATE ON projects
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
-- Repeat for all tables...
```

## Phase 3: Data Migration Strategy

### 3.1 Migration Approach

Since this is a new system without production data in Supabase:

1. **Schema-Only Migration**: Focus on schema setup without data transfer
2. **Validation Testing**: Run test documents through both systems in parallel
3. **Cutover Strategy**: Switch connection strings once validated

### 3.2 Connection String Updates

```python
# Old (Supabase)
SUPABASE_URL = "https://[project-id].supabase.co"
SUPABASE_KEY = "eyJ..."

# New (RDS)
DATABASE_URL = "postgresql://username:password@legal-doc-processing.cluster-xxxxx.us-east-1.rds.amazonaws.com:5432/legal_doc_processing"

# Connection pool configuration
SQLALCHEMY_DATABASE_URL = DATABASE_URL
SQLALCHEMY_POOL_SIZE = 20
SQLALCHEMY_MAX_OVERFLOW = 40
SQLALCHEMY_POOL_TIMEOUT = 30
```

## Phase 4: Application Updates

### 4.1 Database Connection Layer

```python
# scripts/database/connection.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
import os

class DatabaseConnection:
    def __init__(self):
        self.database_url = os.getenv('DATABASE_URL')
        self.engine = create_engine(
            self.database_url,
            pool_size=20,
            max_overflow=40,
            pool_timeout=30,
            pool_pre_ping=True,  # Verify connections before use
            echo=False  # Set to True for SQL debugging
        )
        self.SessionLocal = sessionmaker(
            autocommit=False, 
            autoflush=False, 
            bind=self.engine
        )
    
    def get_session(self):
        """Get a database session"""
        return self.SessionLocal()
```

### 4.2 Update Configuration Files

```python
# scripts/config.py updates
class Config:
    # Database configuration
    DATABASE_URL = os.getenv('DATABASE_URL')
    
    # Remove Supabase-specific configs
    # SUPABASE_URL = os.getenv('SUPABASE_URL')  # REMOVED
    # SUPABASE_KEY = os.getenv('SUPABASE_ANON_KEY')  # REMOVED
    
    # Add RDS-specific configs
    DB_POOL_SIZE = int(os.getenv('DB_POOL_SIZE', '20'))
    DB_MAX_OVERFLOW = int(os.getenv('DB_MAX_OVERFLOW', '40'))
    DB_POOL_TIMEOUT = int(os.getenv('DB_POOL_TIMEOUT', '30'))
    
    # Redis configuration (unchanged)
    REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
    REDIS_PORT = int(os.getenv('REDIS_PORT', '6379'))
```

### 4.3 Update Database Operations

```python
# scripts/database.py updates
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session
from contextlib import contextmanager

class Database:
    def __init__(self):
        self.engine = create_engine(
            Config.DATABASE_URL,
            pool_size=Config.DB_POOL_SIZE,
            max_overflow=Config.DB_MAX_OVERFLOW,
            pool_timeout=Config.DB_POOL_TIMEOUT,
            pool_pre_ping=True
        )
    
    @contextmanager
    def get_db(self):
        """Context manager for database sessions"""
        db = Session(self.engine)
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
    
    def verify_connection(self):
        """Verify database connectivity"""
        try:
            with self.engine.connect() as conn:
                result = conn.execute("SELECT version()")
                version = result.scalar()
                print(f"Connected to PostgreSQL: {version}")
                return True
        except Exception as e:
            print(f"Database connection failed: {e}")
            return False
```

## Phase 5: Integration Updates

### 5.1 Redis Integration (ElastiCache)

```yaml
ElastiCache Configuration:
  Engine: Redis 7.0
  Node Type: cache.m6g.large
  Cluster Mode: Disabled (for simplicity)
  Multi-AZ: Yes
  Automatic Failover: Enabled
  
Security Group:
  - Same VPC as RDS
  - Inbound: 6379 from application servers
```

### 5.2 Update Redis Configuration

```python
# scripts/redis_config_production.py
REDIS_CONFIG = {
    'host': os.getenv('ELASTICACHE_ENDPOINT'),
    'port': 6379,
    'db': 0,
    'password': os.getenv('ELASTICACHE_AUTH_TOKEN'),  # If AUTH enabled
    'ssl': True,
    'ssl_cert_reqs': 'required',
    'decode_responses': True,
    'socket_keepalive': True,
    'socket_keepalive_options': {
        1: 1,  # TCP_KEEPIDLE
        2: 1,  # TCP_KEEPINTVL
        3: 5,  # TCP_KEEPCNT
    }
}
```

### 5.3 Future Neo4j Integration

```yaml
Neo4j Deployment Options:
  1. Neo4j Aura (Managed):
     - Fully managed graph database
     - AWS-hosted for low latency
     
  2. Self-hosted on EC2:
     - Full control over configuration
     - Same VPC as RDS/ElastiCache
     
  3. Amazon Neptune:
     - AWS-native graph database
     - Different query language (Gremlin/SPARQL)
```

## Phase 6: Schema Conformance Implementation

### 6.1 Enable SQLAlchemy Introspection

With RDS PostgreSQL, the context_217 implementation works without modification:

```python
# Now works directly!
from scripts.database.schema_reflection import SchemaReflector
from scripts.database.conformance_engine import ConformanceEngine

# Initialize with RDS connection
reflector = SchemaReflector(DATABASE_URL)
engine = ConformanceEngine(DATABASE_URL)

# All introspection features work
tables = reflector.get_tables()
columns = reflector.get_columns('documents')
```

### 6.2 Automated Schema Validation

```bash
# CLI commands now work without modification
python -m scripts.database.cli check
python -m scripts.database.cli generate -o scripts/core/models.py
python -m scripts.database.cli validate scripts/pdf_tasks.py
```

## Phase 7: Monitoring and Operations

### 7.1 AWS CloudWatch Integration

```python
# Automatic RDS metrics in CloudWatch:
- CPUUtilization
- DatabaseConnections
- FreeableMemory
- ReadLatency / WriteLatency
- DiskQueueDepth

# Custom metrics
cloudwatch = boto3.client('cloudwatch')
cloudwatch.put_metric_data(
    Namespace='LegalDocProcessing',
    MetricData=[
        {
            'MetricName': 'DocumentsProcessed',
            'Value': count,
            'Unit': 'Count'
        }
    ]
)
```

### 7.2 Performance Insights

```sql
-- Enable Performance Insights in RDS console
-- Key queries to monitor:

-- Slow queries
SELECT query, calls, mean_time
FROM pg_stat_statements
WHERE mean_time > 1000  -- queries taking > 1 second
ORDER BY mean_time DESC;

-- Table sizes
SELECT schemaname, tablename, 
       pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;
```

### 7.3 Backup Strategy

```yaml
Backup Configuration:
  Automated Backups: 
    - Retention: 7 days
    - Backup Window: 3:00-4:00 AM UTC
    
  Manual Snapshots:
    - Before major updates
    - Monthly archives
    
  Point-in-Time Recovery:
    - Available for any second within retention period
```

## Phase 8: Testing and Validation

### 8.1 Connection Testing

```python
# test_rds_connection.py
import os
from sqlalchemy import create_engine

def test_rds_connection():
    """Test RDS PostgreSQL connectivity"""
    try:
        engine = create_engine(os.getenv('DATABASE_URL'))
        with engine.connect() as conn:
            result = conn.execute("SELECT 1")
            assert result.scalar() == 1
            
            # Test table access
            result = conn.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public'
            """)
            tables = [row[0] for row in result]
            
            expected_tables = [
                'projects', 'documents', 'chunks', 
                'entities', 'processing_tasks'
            ]
            
            for table in expected_tables:
                assert table in tables, f"Missing table: {table}"
                
        print("✅ RDS connection test passed")
        return True
        
    except Exception as e:
        print(f"❌ RDS connection test failed: {e}")
        return False
```

### 8.2 Performance Benchmarking

```python
# benchmark_database_operations.py
import time
from concurrent.futures import ThreadPoolExecutor

def benchmark_concurrent_queries():
    """Test database under load"""
    def run_query():
        with database.get_db() as db:
            start = time.time()
            result = db.execute("SELECT COUNT(*) FROM documents")
            duration = time.time() - start
            return duration
    
    # Run 50 concurrent queries
    with ThreadPoolExecutor(max_workers=50) as executor:
        futures = [executor.submit(run_query) for _ in range(50)]
        durations = [f.result() for f in futures]
    
    avg_duration = sum(durations) / len(durations)
    max_duration = max(durations)
    
    print(f"Average query time: {avg_duration:.3f}s")
    print(f"Max query time: {max_duration:.3f}s")
    
    assert avg_duration < 0.1, "Queries too slow"
    assert max_duration < 0.5, "Max query time exceeded"
```

### 8.3 Schema Conformance Testing

```python
# test_schema_conformance.py
from scripts.database.conformance_engine import ConformanceEngine

def test_schema_conformance():
    """Verify schema matches Pydantic models"""
    engine = ConformanceEngine(DATABASE_URL)
    
    # Check all models
    results = engine.check_all_models()
    
    for model_name, issues in results.items():
        if issues:
            print(f"❌ {model_name}: {len(issues)} issues")
            for issue in issues:
                print(f"   - {issue}")
        else:
            print(f"✅ {model_name}: No issues")
    
    # Verify no critical issues
    critical_issues = sum(len(issues) for issues in results.values())
    assert critical_issues == 0, f"Found {critical_issues} schema issues"
```

## Phase 9: Cutover Plan

### 9.1 Pre-Cutover Checklist

- [ ] RDS instance provisioned and configured
- [ ] Schema created and validated
- [ ] Indexes and constraints applied
- [ ] Network connectivity verified
- [ ] Security groups configured
- [ ] IAM roles and policies set
- [ ] Backup strategy implemented
- [ ] Monitoring alerts configured
- [ ] Application code updated
- [ ] Environment variables updated
- [ ] Schema conformance validated
- [ ] Performance benchmarks passed

### 9.2 Cutover Steps

1. **Stop Processing** (Maintenance Window)
   ```bash
   # Stop Celery workers
   ./scripts/stop_celery_workers.sh
   ```

2. **Update Configuration**
   ```bash
   # Update .env file
   export DATABASE_URL="postgresql://..."
   # Remove SUPABASE_URL and SUPABASE_KEY
   ```

3. **Verify Connectivity**
   ```bash
   python test_rds_connection.py
   ```

4. **Run Schema Conformance**
   ```bash
   python -m scripts.database.cli check
   ```

5. **Start Services**
   ```bash
   ./scripts/start_celery_workers.sh
   ```

6. **Process Test Document**
   ```bash
   python scripts/test_single_document.py
   ```

### 9.3 Rollback Plan

If issues arise:

1. Stop all services
2. Revert environment variables to Supabase
3. Restart services with Supabase connection
4. Investigate and fix issues
5. Retry migration

## Phase 10: Post-Migration Tasks

### 10.1 Immediate Tasks

- [ ] Update all documentation
- [ ] Remove Supabase-specific code
- [ ] Update CI/CD pipelines
- [ ] Train team on RDS operations
- [ ] Document connection strings
- [ ] Update monitoring dashboards

### 10.2 First Week Tasks

- [ ] Performance tuning based on real workload
- [ ] Implement automated backup testing
- [ ] Set up query performance monitoring
- [ ] Configure slow query logging
- [ ] Implement connection pooling optimization

### 10.3 First Month Tasks

- [ ] Cost optimization review
- [ ] Security audit
- [ ] Disaster recovery drill
- [ ] Performance baseline establishment
- [ ] Capacity planning based on growth

## Cost Estimation

### Monthly Costs (Production)

```yaml
RDS PostgreSQL:
  - db.m6g.large: ~$140/month
  - Multi-AZ: 2x = ~$280/month
  - Storage (100GB): ~$12/month
  - Backups: ~$10/month
  Total: ~$302/month

ElastiCache Redis:
  - cache.m6g.large: ~$120/month
  - Multi-AZ: 2x = ~$240/month
  Total: ~$240/month

Data Transfer:
  - Within AZ: Free
  - Cross-AZ: ~$20/month (estimated)

Total Infrastructure: ~$562/month
```

### Cost Optimization Options

1. **Reserved Instances**: 30-50% savings with 1-year commitment
2. **Graviton2 Instances**: Already included (m6g series)
3. **Storage Optimization**: gp3 provides better cost/performance than gp2
4. **Right-sizing**: Start with smaller instances for staging/dev

## Conclusion

This migration plan provides a clear path from Supabase to AWS RDS PostgreSQL, enabling:

1. Direct database access for schema introspection
2. Full SQLAlchemy compatibility
3. Better integration with AWS services
4. Production-grade monitoring and operations
5. Future-proof architecture for Neo4j integration

The migration can be completed with zero data loss and minimal downtime, providing a solid foundation for the legal document processing pipeline's growth and scalability needs.

## Next Steps

1. Review and approve migration plan
2. Provision AWS infrastructure
3. Execute schema migration
4. Update application configuration
5. Perform validation testing
6. Execute cutover during maintenance window
7. Monitor and optimize post-migration

The total migration timeline is estimated at 2-3 days for infrastructure setup and testing, with the actual cutover taking less than 1 hour during a maintenance window.