# Context 220: RDS PostgreSQL Configuration Requirements

## Implementation Status

### Tasks
- [x] 1. Security Group Configuration - Added IP 108.210.14.204 and VPC CIDR 172.31.0.0/16
- [x] 2. Parameter Group Settings - Created legal-doc-processing-pg15 (note: instance uses PostgreSQL 17)
- [x] 3. Database Setup Script - Created setup_rds_database.sql
- [ ] 4. Environment Configuration
- [x] 5. Test Connection Script - Created test_rds_connection.py
- [x] 6. Schema Creation - Created create_schema.sql
- [ ] 7. Index Creation - Included in schema
- [ ] 8. Monitoring Setup - CloudWatch alarms partially configured
- [ ] 9. Backup Configuration - Already enabled (7-day retention)
- [ ] 10. Application Code Updates

### Important Findings
- Instance ID: database1
- PostgreSQL Version: 17.2 (not 15)
- Master Username: postgres
- Security Group: sg-793c5523
- VPC: vpc-53107829 (172.31.0.0/16)
- **PubliclyAccessible: false** - This is why external connections fail
- Instance Status: backing-up (may affect modifications)

## Database Connection Details

```
Endpoint: database1.cuviucyodbeg.us-east-1.rds.amazonaws.com
Port: 5432
Database Name: postgres (default) - will create 'legal_doc_processing'
```

## 1. Security Group Configuration (CRITICAL)

Your RDS instance needs proper security group rules:

```yaml
Inbound Rules:
  - Type: PostgreSQL
    Protocol: TCP
    Port: 5432
    Source: 
      - Your application server's security group OR
      - Your application server's IP addresses OR
      - Your VPC CIDR block (for internal access)
      - Your development machine IP (for setup only)
    
  # Example rules:
  - PostgreSQL | TCP | 5432 | sg-xxxxx (App Server SG)
  - PostgreSQL | TCP | 5432 | 10.0.0.0/16 (VPC CIDR)
  - PostgreSQL | TCP | 5432 | YOUR.IP.ADDRESS/32 (Dev machine - temporary)
```

## 2. Parameter Group Settings

Create a custom parameter group for optimal performance:

```sql
-- Key parameters to modify:
shared_buffers = 256MB              -- 25% of instance memory
max_connections = 200               -- Sufficient for app + monitoring
work_mem = 4MB                      -- Per operation memory
maintenance_work_mem = 64MB         -- For VACUUM, CREATE INDEX
effective_cache_size = 1GB          -- 75% of instance memory
checkpoint_completion_target = 0.9  -- Spread out checkpoints
wal_buffers = 16MB                  -- Write-ahead log buffers
random_page_cost = 1.1              -- SSD optimization

-- Logging parameters (for debugging)
log_statement = 'mod'               -- Log DDL and DML
log_duration = on                   -- Log query durations
log_min_duration_statement = 1000   -- Log queries > 1 second
```

## 3. Database Setup Script

Run this script after connecting to create the application database:

```sql
-- Connect as master user first
\c postgres

-- Create application database
CREATE DATABASE legal_doc_processing;

-- Create application user (don't use master credentials in app)
CREATE USER app_user WITH PASSWORD 'STRONG_PASSWORD_HERE';

-- Grant permissions
GRANT CONNECT ON DATABASE legal_doc_processing TO app_user;

-- Switch to new database
\c legal_doc_processing

-- Enable extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
CREATE EXTENSION IF NOT EXISTS "btree_gist";

-- Grant schema permissions
GRANT ALL ON SCHEMA public TO app_user;
GRANT ALL ON ALL TABLES IN SCHEMA public TO app_user;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO app_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO app_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO app_user;
```

## 4. Environment Configuration

Update your `.env` file:

```bash
# Database Configuration
DATABASE_URL=postgresql://app_user:STRONG_PASSWORD_HERE@database1.cuviucyodbeg.us-east-1.rds.amazonaws.com:5432/legal_doc_processing

# Connection Pool Settings
DB_POOL_SIZE=20
DB_MAX_OVERFLOW=40
DB_POOL_TIMEOUT=30
DB_POOL_RECYCLE=3600

# SSL Configuration (if enforced)
DB_SSL_MODE=require

# Remove old Supabase variables
# SUPABASE_URL=xxx  # DELETE THIS
# SUPABASE_ANON_KEY=xxx  # DELETE THIS
```

## 5. Test Connection Script

Create this script to verify connectivity:

```python
# test_rds_setup.py
import os
import psycopg2
from sqlalchemy import create_engine

def test_direct_connection():
    """Test with psycopg2"""
    try:
        conn = psycopg2.connect(
            host="database1.cuviucyodbeg.us-east-1.rds.amazonaws.com",
            port=5432,
            database="legal_doc_processing",
            user="app_user",
            password="STRONG_PASSWORD_HERE"
        )
        cur = conn.cursor()
        cur.execute("SELECT version();")
        version = cur.fetchone()
        print(f"✅ Direct connection successful: {version[0]}")
        conn.close()
        return True
    except Exception as e:
        print(f"❌ Direct connection failed: {e}")
        return False

def test_sqlalchemy_connection():
    """Test with SQLAlchemy"""
    try:
        DATABASE_URL = os.getenv('DATABASE_URL')
        engine = create_engine(DATABASE_URL)
        with engine.connect() as conn:
            result = conn.execute("SELECT 1")
            assert result.scalar() == 1
            print("✅ SQLAlchemy connection successful")
        return True
    except Exception as e:
        print(f"❌ SQLAlchemy connection failed: {e}")
        return False

if __name__ == "__main__":
    print("Testing RDS connections...")
    test_direct_connection()
    test_sqlalchemy_connection()
```

## 6. Schema Creation Order

Due to foreign key constraints, create tables in this order:

```sql
-- 1. Independent tables first
CREATE TABLE projects (...);
CREATE TABLE canonical_entities (...);

-- 2. Tables with single dependencies
CREATE TABLE documents (...);  -- depends on projects

-- 3. Tables with multiple dependencies  
CREATE TABLE processing_tasks (...);  -- depends on documents
CREATE TABLE chunks (...);  -- depends on documents
CREATE TABLE entities (...);  -- depends on documents, canonical_entities

-- 4. Junction tables last
CREATE TABLE entity_relationships (...);  -- depends on entities
CREATE TABLE chunk_entities (...);  -- depends on chunks, entities
```

## 7. Required Indexes for Performance

```sql
-- Critical performance indexes
CREATE INDEX idx_documents_project_id ON documents(project_id);
CREATE INDEX idx_documents_status ON documents(status);
CREATE INDEX idx_processing_tasks_document_id ON processing_tasks(document_id);
CREATE INDEX idx_processing_tasks_status ON processing_tasks(task_status);
CREATE INDEX idx_chunks_document_id ON chunks(document_id);
CREATE INDEX idx_entities_document_id ON entities(document_id);

-- Text search indexes
CREATE INDEX idx_chunks_content_gin ON chunks USING gin(to_tsvector('english', content));
CREATE INDEX idx_entities_name_trgm ON entities USING gin(name gin_trgm_ops);

-- Timestamp indexes for queries
CREATE INDEX idx_documents_created_at ON documents(created_at DESC);
CREATE INDEX idx_processing_tasks_created_at ON processing_tasks(created_at DESC);
```

## 8. Monitoring Setup

### CloudWatch Alarms to Configure

```yaml
High CPU Utilization:
  Metric: CPUUtilization
  Threshold: > 80%
  Period: 5 minutes

High Database Connections:
  Metric: DatabaseConnections
  Threshold: > 150
  Period: 5 minutes

Low Free Storage:
  Metric: FreeStorageSpace
  Threshold: < 10GB
  Period: 5 minutes

High Read Latency:
  Metric: ReadLatency
  Threshold: > 0.2 seconds
  Period: 5 minutes
```

### Enable Performance Insights

1. In RDS Console → Modify Instance
2. Enable Performance Insights
3. Retention period: 7 days (free tier)
4. Enable all SQL statistics

## 9. Backup Configuration

```yaml
Automated Backups:
  - Already enabled by default
  - Retention: 7 days minimum
  - Backup window: Choose low-traffic time
  
Manual Snapshot Before:
  - Schema changes
  - Major application updates
  - Data migrations
```

## 10. Connection Pooling Best Practices

```python
# scripts/database/connection_manager.py
from sqlalchemy import create_engine
from sqlalchemy.pool import QueuePool
import os

class ConnectionManager:
    def __init__(self):
        self.DATABASE_URL = os.getenv('DATABASE_URL')
        
        # Production-grade connection pool
        self.engine = create_engine(
            self.DATABASE_URL,
            poolclass=QueuePool,
            pool_size=20,          # Number of persistent connections
            max_overflow=40,       # Maximum overflow connections
            pool_timeout=30,       # Timeout for getting connection
            pool_recycle=3600,     # Recycle connections after 1 hour
            pool_pre_ping=True,    # Test connections before use
            echo=False,            # Set True for SQL debugging
            connect_args={
                "sslmode": "require",  # Force SSL
                "connect_timeout": 10,
                "application_name": "legal_doc_processing"
            }
        )
```

## 11. SSL/TLS Configuration

For production, enforce SSL:

```python
# Add to connection string
DATABASE_URL = "postgresql://user:pass@host:5432/db?sslmode=require"

# Or in connect_args
connect_args = {
    "sslmode": "require",  # or "verify-full" for strictest
    "sslrootcert": "/path/to/rds-ca-2019-root.pem"  # Optional
}
```

## 12. Initial Health Checks

Run these checks after setup:

```sql
-- Check extensions
SELECT * FROM pg_extension;

-- Check users and permissions
\du

-- Check database size
SELECT pg_database.datname,
       pg_size_pretty(pg_database_size(pg_database.datname)) AS size
FROM pg_database;

-- Check table creation
\dt

-- Check indexes
\di

-- Check current connections
SELECT pid, usename, application_name, client_addr, state
FROM pg_stat_activity
WHERE datname = 'legal_doc_processing';
```

## 13. Application Code Updates

Update your database initialization:

```python
# scripts/database.py
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from contextlib import contextmanager

# Remove Supabase imports
# from supabase import create_client  # DELETE

class Database:
    def __init__(self):
        self.database_url = os.getenv('DATABASE_URL')
        if not self.database_url:
            raise ValueError("DATABASE_URL environment variable not set")
            
        self.engine = create_engine(
            self.database_url,
            pool_size=int(os.getenv('DB_POOL_SIZE', '20')),
            max_overflow=int(os.getenv('DB_MAX_OVERFLOW', '40')),
            pool_timeout=int(os.getenv('DB_POOL_TIMEOUT', '30')),
            pool_recycle=int(os.getenv('DB_POOL_RECYCLE', '3600')),
            pool_pre_ping=True,
            echo=os.getenv('DB_ECHO', 'false').lower() == 'true'
        )
        
        self.SessionLocal = sessionmaker(
            bind=self.engine,
            autocommit=False,
            autoflush=False
        )
    
    @contextmanager
    def get_session(self):
        """Database session context manager"""
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
```

## 14. Migration Commands

Once configured, run in order:

```bash
# 1. Test connection
python test_rds_setup.py

# 2. Create schema (use the SQL from context_203)
psql -h database1.cuviucyodbeg.us-east-1.rds.amazonaws.com -U app_user -d legal_doc_processing -f schema.sql

# 3. Verify schema conformance
python -m scripts.database.cli check

# 4. Generate Pydantic models
python -m scripts.database.cli generate

# 5. Test with a document
python scripts/test_single_document.py
```

## 15. Common Issues and Solutions

### Connection Timeout
- Check security group rules
- Verify RDS is publicly accessible (if connecting from outside VPC)
- Check network ACLs

### Authentication Failed
- Verify username/password
- Check if user exists: `\du` in psql
- Verify database exists: `\l` in psql

### SSL Required Error
- Add `?sslmode=require` to connection string
- Download RDS certificate bundle if needed

### Too Many Connections
- Check current connections: `SELECT count(*) FROM pg_stat_activity;`
- Increase max_connections in parameter group
- Implement connection pooling

## Current Status Summary

### ✅ Completed
1. **Security Group Configuration**
   - Added your IP: 108.210.14.204/32
   - Added VPC CIDR: 172.31.0.0/16
   - Security Group ID: sg-793c5523

2. **Parameter Group Configuration**
   - Created: legal-doc-processing-pg17
   - Optimized for PostgreSQL 17.2
   - Applied to instance (may require reboot)

3. **Scripts Created**
   - `/scripts/setup_rds_database.sql` - Database and user creation
   - `/scripts/create_schema.sql` - Full schema from context_203
   - `/scripts/test_rds_connection.py` - Connection testing
   - `/scripts/configure_rds_aws.sh` - AWS configuration
   - `/scripts/enable_rds_public_access.sh` - Enable public access
   - `/scripts/configure_pg17_parameters.sh` - Parameter tuning

4. **Environment Configuration**
   - Created `.env.rds` with connection settings
   - App user: `app_user`
   - App password: `LegalDoc2025!Secure`
   - Database: `legal_doc_processing`

### ⚠️ Critical Issue: Public Access Disabled

The RDS instance is not publicly accessible. You have two options:

**Option 1: Enable Public Access (Development)**
```bash
./scripts/enable_rds_public_access.sh
# Wait for status to be 'available', then proceed with setup
```

**Option 2: Use AWS Session Manager or EC2 Bastion**
- Connect through an EC2 instance in the same VPC
- Use AWS Systems Manager Session Manager
- Set up an SSH tunnel through a bastion host

### 📋 Next Steps (After Resolving Access)

1. **Get Master Password**
   ```bash
   # Get from AWS Console or whoever created the instance
   export RDS_MASTER_PASSWORD='your-master-password'
   ```

2. **Test Connection and Setup Database**
   ```bash
   python scripts/test_rds_connection.py
   ```

3. **Create Schema**
   ```bash
   psql -h database1.cuviucyodbeg.us-east-1.rds.amazonaws.com \
        -U app_user -d legal_doc_processing \
        -f scripts/create_schema.sql
   ```

4. **Update Application .env**
   ```bash
   # Copy settings from .env.rds to your main .env file
   cat .env.rds >> .env
   ```

5. **Test Schema Conformance**
   ```bash
   python -m scripts.database.cli check
   ```

6. **Process Test Document**
   ```bash
   python scripts/test_single_document.py
   ```

### 🔒 Security Considerations

- If you enable public access, disable it after setup:
  ```bash
  aws rds modify-db-instance --db-instance-identifier database1 \
      --no-publicly-accessible --apply-immediately
  ```
- Use strong passwords for all database users
- Regularly rotate credentials
- Monitor access logs via CloudWatch

### 📊 Instance Details

- **Endpoint**: database1.cuviucyodbeg.us-east-1.rds.amazonaws.com
- **Port**: 5432
- **Engine**: PostgreSQL 17.2
- **Instance Class**: db.m5.large
- **Storage**: 200GB gp2 (auto-scaling to 1TB)
- **Backup Retention**: 7 days
- **Deletion Protection**: Enabled
- **Encryption**: Enabled (KMS)

This configuration provides a production-ready PostgreSQL database that fully supports your schema introspection needs and integrates well with your existing Redis infrastructure.