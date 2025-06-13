# Context 262: RDS Direct Access Configuration and Legacy Cleanup

## Date: May 31, 2025
## Purpose: Document proper RDS configuration for EC2 environment and remove legacy connection methods

## Current Environment

### EC2 Instance Details
- **Instance ID**: i-0e431c454a7c3c6a1
- **Instance Type**: t3.medium (2 vCPUs, 3.7GB RAM)
- **Network**: Direct VPC access to RDS instance
- **Security Group**: Allows direct connection to RDS on port 5432

### RDS Instance Details
- **Endpoint**: database1.cuviucyodbeg.us-east-1.rds.amazonaws.com
- **Port**: 5432
- **Database**: legal_doc_processing
- **SSL**: Required
- **Users**:
  - `postgres` (master user)
  - `app_user` (application user)

## Legacy Connection Methods to Remove

### 1. SSH Tunnel Configuration (No Longer Needed)

The codebase contains remnants of SSH tunnel configuration from when developers were accessing the RDS instance from local machines through a bastion host. These are **NOT NEEDED** when running on EC2.

#### Files with SSH Tunnel Logic:
```
scripts/start_rds_tunnel.sh          # DELETE
scripts/stop_rds_tunnel.sh           # DELETE
scripts/monitoring/ssh_monitor.py    # DELETE
scripts/bastion_setup.sh            # DELETE
scripts/deploy_via_bastion.sh       # DELETE
scripts/init_rds_database.sh        # REVIEW - may contain tunnel logic
scripts/init_rds_interactive.sh     # REVIEW - may contain tunnel logic
```

#### Configuration Variables to Remove from .env:
```
RDS_TUNNEL_LOCAL_PORT=5433          # REMOVE
RDS_BASTION_HOST=54.162.223.205    # REMOVE
RDS_BASTION_USER=ubuntu             # REMOVE
RDS_BASTION_KEY=resources/aws/...   # REMOVE
```

#### Code Patterns to Remove:

1. **Tunnel Status Checks** (scripts/check_rds_connection.py):
```python
def check_tunnel_status():  # DELETE THIS FUNCTION
    """Check if SSH tunnel is active."""
    try:
        result = subprocess.run(
            ['lsof', f'-ti:{RDS_TUNNEL_LOCAL_PORT}'], 
            capture_output=True, text=True
        )
        return bool(result.stdout.strip())
    except:
        return False
```

2. **Localhost Connection Strings**:
```python
# WRONG - uses SSH tunnel
DATABASE_URL = 'postgresql://user:pass@localhost:5433/dbname'

# CORRECT - direct RDS connection
DATABASE_URL = 'postgresql://user:pass@database1.cuviucyodbeg.us-east-1.rds.amazonaws.com:5432/dbname?sslmode=require'
```

3. **Stage-Based URL Selection** (scripts/config.py):
```python
def get_database_url():  # SIMPLIFY THIS
    """Get appropriate database URL based on deployment stage."""
    # Remove all tunnel logic - always use direct connection on EC2
    return DATABASE_URL_DIRECT or DATABASE_URL
```

### 2. Supabase API Configuration (Legacy)

The codebase migrated from Supabase to RDS but still contains Supabase configuration and connection attempts.

#### Configuration Variables to Remove from .env:
```
SUPABASE_URL=...                    # REMOVE
SUPABASE_ANON_KEY=...              # REMOVE
SUPABASE_SERVICE_ROLE_KEY=...      # REMOVE
SUPABASE_JWT_SECRET=...            # REMOVE
SUPABASE_PAT=...                   # REMOVE
SUPABASE_PASSWORD=...              # REMOVE
```

#### Files to Review/Remove:
```
scripts/archive_pre_consolidation/supabase_utils.py    # DELETE if not used
scripts/database/supabase_introspector.py              # DELETE
scripts/database/supabase_reflection.py                # DELETE
scripts/database/conformance_engine_supabase.py        # DELETE
```

#### Code Patterns to Remove:
```python
# REMOVE any imports like:
from supabase import create_client, Client

# REMOVE any Supabase client initialization:
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# REMOVE any Supabase API calls:
result = supabase.table('documents').select().execute()
```

## Correct RDS Configuration for EC2

### 1. Environment Variables (.env)

```bash
# General Settings - Use Stage 3 for production EC2
DEPLOYMENT_STAGE=3
USE_DIRECT_DATABASE_CONNECTION=true

# RDS PostgreSQL - Direct Connection Only
DATABASE_URL=postgresql://app_user:LegalDoc2025%21Secure@database1.cuviucyodbeg.us-east-1.rds.amazonaws.com:5432/legal_doc_processing?sslmode=require
DATABASE_URL_DIRECT=postgresql://app_user:LegalDoc2025%21Secure@database1.cuviucyodbeg.us-east-1.rds.amazonaws.com:5432/legal_doc_processing?sslmode=require

# Master credentials (for schema changes only)
RDS_MASTER_USER=postgres
RDS_MASTER_PASSWORD=BSdANjJDdtApMpoepjQxnNzD5RonT

# Connection pool settings
DB_POOL_SIZE=20
DB_MAX_OVERFLOW=40
DB_POOL_TIMEOUT=30
DB_POOL_RECYCLE=3600
DB_SSL_MODE=require
```

**Important Notes**:
- The `!` in the password must be URL-encoded as `%21`
- Both DATABASE_URL and DATABASE_URL_DIRECT should be identical on EC2
- Always use `sslmode=require` for security

### 2. Simplified Database Configuration (scripts/config.py)

```python
# Simplified configuration for EC2 environment
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Database Configuration - Direct RDS Connection
DATABASE_URL = os.getenv("DATABASE_URL")
DATABASE_URL_DIRECT = os.getenv("DATABASE_URL_DIRECT", DATABASE_URL)

# Since we're on EC2, always use direct connection
def get_database_url():
    """Get database URL for EC2 environment."""
    return DATABASE_URL_DIRECT or DATABASE_URL

# Connection pool settings optimized for EC2
DB_POOL_CONFIG = {
    'pool_size': int(os.getenv("DB_POOL_SIZE", "20")),
    'max_overflow': int(os.getenv("DB_MAX_OVERFLOW", "40")),
    'pool_timeout': int(os.getenv("DB_POOL_TIMEOUT", "30")),
    'pool_recycle': int(os.getenv("DB_POOL_RECYCLE", "3600")),
    'pool_pre_ping': True,
    'connect_args': {
        'connect_timeout': 10,
        'options': '-c statement_timeout=300000',
        'keepalives': 1,
        'keepalives_idle': 30,
        'keepalives_interval': 10,
        'keepalives_count': 5,
        'sslmode': 'require'
    }
}
```

### 3. Database Connection Testing

Create a simple test script for EC2 environment:

```python
#!/usr/bin/env python3
"""Test RDS connection in EC2 environment."""

import os
import psycopg2
from sqlalchemy import create_engine
from dotenv import load_dotenv

load_dotenv()

def test_rds_connection():
    """Test direct RDS connection."""
    db_url = os.getenv('DATABASE_URL_DIRECT') or os.getenv('DATABASE_URL')
    
    print(f"Testing RDS connection...")
    print(f"Database URL: {db_url.split('@')[1]}")  # Hide credentials
    
    try:
        # Test with psycopg2
        engine = create_engine(db_url)
        with engine.connect() as conn:
            result = conn.execute("SELECT version();")
            version = result.fetchone()[0]
            print(f"✅ Connected to PostgreSQL: {version}")
            
        # Test specific queries
        with engine.connect() as conn:
            # Check schema
            result = conn.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public' 
                ORDER BY table_name;
            """)
            tables = [row[0] for row in result]
            print(f"\nTables found: {len(tables)}")
            for table in tables:
                print(f"  - {table}")
                
        return True
        
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        return False

if __name__ == "__main__":
    test_rds_connection()
```

## Migration Checklist

### Phase 1: Remove SSH Tunnel Dependencies
- [ ] Delete SSH tunnel shell scripts
- [ ] Remove SSH tunnel monitoring scripts
- [ ] Update config.py to remove tunnel logic
- [ ] Remove tunnel-related environment variables
- [ ] Update check_rds_connection.py to remove tunnel checks
- [ ] Fix test_schema_simple.py hardcoded localhost connection

### Phase 2: Remove Supabase Dependencies
- [ ] Remove Supabase environment variables
- [ ] Delete Supabase utility files
- [ ] Remove Supabase imports from all Python files
- [ ] Update any Supabase API calls to use SQLAlchemy/psycopg2

### Phase 3: Validate Direct RDS Access
- [ ] Test database connection with simplified config
- [ ] Run schema conformance tests
- [ ] Verify all CRUD operations work
- [ ] Test connection pooling under load
- [ ] Ensure SSL connections are enforced

### Phase 4: Update Documentation
- [ ] Update README with EC2-specific instructions
- [ ] Remove references to SSH tunnels in docs
- [ ] Remove Supabase migration guides
- [ ] Add troubleshooting for common RDS issues

## Common Issues and Solutions

### 1. Password Authentication Failed
**Issue**: Special characters in password not properly encoded
**Solution**: URL-encode special characters (e.g., `!` becomes `%21`)

### 2. No pg_hba.conf Entry
**Issue**: Security group or VPC configuration blocking access
**Solution**: Ensure EC2 instance is in same VPC as RDS and security groups allow port 5432

### 3. SSL Connection Required
**Issue**: Connection rejected without SSL
**Solution**: Always include `?sslmode=require` in connection string

### 4. Connection Timeouts
**Issue**: Network connectivity or DNS resolution
**Solution**: Use RDS endpoint directly, verify VPC routing

## Security Best Practices

1. **Never commit credentials** - Use environment variables
2. **Always use SSL** - Set `sslmode=require`
3. **Use connection pooling** - Prevents connection exhaustion
4. **Implement retry logic** - Handle transient network issues
5. **Monitor connections** - Track active connections in CloudWatch

## Summary

When running on EC2 with direct RDS access:
1. Remove all SSH tunnel configuration and code
2. Remove all Supabase dependencies
3. Use direct RDS connection strings with proper URL encoding
4. Set `DEPLOYMENT_STAGE=3` and `USE_DIRECT_DATABASE_CONNECTION=true`
5. Ensure security groups allow EC2-to-RDS communication
6. Always use SSL for database connections

This configuration provides optimal performance and security for the production environment without the complexity of SSH tunnels or external API dependencies.