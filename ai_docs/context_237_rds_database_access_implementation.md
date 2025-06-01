# Context 237: RDS Database Access Implementation Guide

**Date**: 2025-05-30
**Type**: Implementation Guide
**Status**: ACTIVE
**Component**: RDS PostgreSQL Database Access

## Overview

This guide provides comprehensive instructions for implementing RDS PostgreSQL database access both in Python scripts and from CLI tools. The setup includes SSH tunnel configuration, environment variable management, and practical usage patterns.

## Database Infrastructure

### RDS Instance Details
- **Endpoint**: `database1.cuviucyodbeg.us-east-1.rds.amazonaws.com`
- **Port**: `5432`
- **Database**: `legal_doc_processing`
- **Version**: PostgreSQL 17.2
- **Region**: `us-east-1`

### Bastion Host Details
- **Instance ID**: `i-0e431c454a7c3c6a1`
- **Public IP**: `54.162.223.205`
- **SSH User**: `ubuntu`
- **PEM Key**: `resources/aws/legal-doc-processor-bastion.pem`

### Database Users
- **Master User**: `postgres`
- **Application User**: `app_user`
- **Password**: `LegalDoc2025!Secure` (verified working)

## Environment Configuration

### Required Environment Variables

Add these to your `.env` file:

```bash
# RDS Database Configuration (Primary)
DATABASE_URL=postgresql://app_user:LegalDoc2025!Secure@localhost:5433/legal_doc_processing

# RDS Direct Connection (Production/EC2)
DATABASE_URL_DIRECT=postgresql://app_user:LegalDoc2025!Secure@database1.cuviucyodbeg.us-east-1.rds.amazonaws.com:5432/legal_doc_processing?sslmode=require

# Master credentials for admin operations
RDS_MASTER_USER=postgres
RDS_MASTER_PASSWORD=BSdANjJDdtApMpoepjQxnNzD5RonT

# Connection pool settings
DB_POOL_SIZE=20
DB_MAX_OVERFLOW=40
DB_POOL_TIMEOUT=30
DB_POOL_RECYCLE=3600
DB_SSL_MODE=require

# Tunnel configuration
RDS_TUNNEL_LOCAL_PORT=5433
RDS_BASTION_HOST=54.162.223.205
RDS_BASTION_USER=ubuntu
RDS_BASTION_KEY=resources/aws/legal-doc-processor-bastion.pem
```

## SSH Tunnel Management

### 1. Create SSH Tunnel

```bash
# Create tunnel (run from project root)
ssh -f -N -L 5433:database1.cuviucyodbeg.us-east-1.rds.amazonaws.com:5432 \
    -i resources/aws/legal-doc-processor-bastion.pem \
    ubuntu@54.162.223.205
```

### 2. Verify Tunnel Status

```bash
# Check if tunnel is active
lsof -ti:5433

# Test tunnel with psql
PGPASSWORD='LegalDoc2025!Secure' psql \
    -h localhost -p 5433 -U app_user \
    -d legal_doc_processing -c "SELECT version();"
```

### 3. Close Tunnel

```bash
# Kill tunnel process
lsof -ti:5433 | xargs kill -9
```

### 4. Automated Tunnel Script

Create `scripts/start_rds_tunnel.sh`:

```bash
#!/bin/bash
# Check if tunnel already exists
if lsof -ti:5433 > /dev/null; then
    echo "Tunnel already active on port 5433"
    exit 0
fi

# Create tunnel
echo "Creating SSH tunnel to RDS..."
ssh -f -N -L 5433:database1.cuviucyodbeg.us-east-1.rds.amazonaws.com:5432 \
    -i resources/aws/legal-doc-processor-bastion.pem \
    ubuntu@54.162.223.205

# Verify tunnel
if lsof -ti:5433 > /dev/null; then
    echo "✓ SSH tunnel active on port 5433"
else
    echo "✗ Failed to create SSH tunnel"
    exit 1
fi
```

## Script Implementation

### 1. Using Existing RDS Utils

Your `scripts/rds_utils.py` already provides the interface:

```python
from scripts.rds_utils import test_connection, health_check, execute_query

# Test connection
if test_connection():
    print("✓ Database connected")
else:
    print("✗ Database connection failed")

# Get health status
health = health_check()
print(f"Database status: {health['status']}")

# Execute queries
results = execute_query("SELECT COUNT(*) FROM projects")
```

### 2. Database Configuration in Scripts

Update `scripts/config.py` to handle RDS:

```python
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(env_path)

class DatabaseConfig:
    # Use tunnel URL for local development
    DATABASE_URL = os.getenv('DATABASE_URL', 
        'postgresql://app_user:LegalDoc2025!Secure@localhost:5433/legal_doc_processing')
    
    # Direct URL for production
    DATABASE_URL_DIRECT = os.getenv('DATABASE_URL_DIRECT',
        'postgresql://app_user:LegalDoc2025!Secure@database1.cuviucyodbeg.us-east-1.rds.amazonaws.com:5432/legal_doc_processing?sslmode=require')
    
    # Master credentials
    MASTER_USER = os.getenv('RDS_MASTER_USER', 'postgres')
    MASTER_PASSWORD = os.getenv('RDS_MASTER_PASSWORD')
    
    @classmethod
    def get_url(cls, use_direct=False):
        """Get appropriate database URL based on environment"""
        if use_direct or os.getenv('DEPLOYMENT_STAGE') == '3':
            return cls.DATABASE_URL_DIRECT
        return cls.DATABASE_URL
```

### 3. Script Database Connection Pattern

```python
# In any script that needs database access
import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from scripts.rds_utils import test_connection, execute_query, insert_record

def main():
    # Test connection first
    if not test_connection():
        print("Database connection failed. Is SSH tunnel active?")
        print("Run: ssh -f -N -L 5433:database1.cuviucyodbeg.us-east-1.rds.amazonaws.com:5432 -i resources/aws/legal-doc-processor-bastion.pem ubuntu@54.162.223.205")
        return 1
    
    # Your database operations here
    results = execute_query("SELECT * FROM projects LIMIT 5")
    print(f"Found {len(results)} projects")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

## CLI Implementation

### 1. Enhanced Admin CLI

Update `scripts/cli/admin.py` to include RDS verification:

```python
import click
from scripts.rds_utils import test_connection, health_check

@cli.command()
def verify_rds():
    """Verify RDS database connection and health"""
    click.echo("Testing RDS Database Connection...")
    
    if test_connection():
        click.echo("✓ RDS Connection: SUCCESS", color='green')
        
        health = health_check()
        click.echo(f"Database Status: {health['status']}")
        if 'version' in health:
            click.echo(f"PostgreSQL Version: {health['version']}")
        
        if 'tables' in health:
            click.echo("\nTable Row Counts:")
            for table, count in health['tables'].items():
                click.echo(f"  {table}: {count}")
    else:
        click.echo("✗ RDS Connection: FAILED", color='red')
        click.echo("Ensure SSH tunnel is active:")
        click.echo("ssh -f -N -L 5433:database1.cuviucyodbeg.us-east-1.rds.amazonaws.com:5432 -i resources/aws/legal-doc-processor-bastion.pem ubuntu@54.162.223.205")
```

### 2. Database Management CLI

Create `scripts/cli/database.py`:

```python
import click
import subprocess
import os
from scripts.rds_utils import test_connection, execute_query

@click.group()
def database():
    """Database management commands"""
    pass

@database.command()
def tunnel():
    """Create SSH tunnel to RDS"""
    # Check if tunnel exists
    try:
        result = subprocess.run(['lsof', '-ti:5433'], capture_output=True, text=True)
        if result.stdout.strip():
            click.echo("Tunnel already active on port 5433")
            return
    except:
        pass
    
    # Create tunnel
    cmd = [
        'ssh', '-f', '-N', 
        '-L', '5433:database1.cuviucyodbeg.us-east-1.rds.amazonaws.com:5432',
        '-i', 'resources/aws/legal-doc-processor-bastion.pem',
        'ubuntu@54.162.223.205'
    ]
    
    try:
        subprocess.run(cmd, check=True)
        click.echo("✓ SSH tunnel created on port 5433")
    except subprocess.CalledProcessError:
        click.echo("✗ Failed to create SSH tunnel")

@database.command()
def status():
    """Check database status"""
    if test_connection():
        click.echo("✓ Database: Connected")
        health = health_check()
        click.echo(f"Status: {health['status']}")
        if 'tables' in health:
            for table, count in health['tables'].items():
                click.echo(f"  {table}: {count} rows")
    else:
        click.echo("✗ Database: Disconnected")

@database.command()
@click.argument('query')
def query(query):
    """Execute a database query"""
    if not test_connection():
        click.echo("Database not connected")
        return
    
    try:
        results = execute_query(query)
        click.echo(f"Query returned {len(results)} rows")
        for row in results[:10]:  # Show first 10 rows
            click.echo(row)
    except Exception as e:
        click.echo(f"Query failed: {e}")
```

### 3. Environment Setup CLI

Add to `scripts/cli/admin.py`:

```python
@cli.command()
def setup_env():
    """Setup environment for RDS access"""
    env_file = Path('.env')
    
    # Check if tunnel variables exist
    env_content = env_file.read_text() if env_file.exists() else ""
    
    required_vars = [
        'DATABASE_URL',
        'DATABASE_URL_DIRECT', 
        'RDS_MASTER_USER',
        'RDS_MASTER_PASSWORD'
    ]
    
    missing = []
    for var in required_vars:
        if f"{var}=" not in env_content:
            missing.append(var)
    
    if missing:
        click.echo(f"Missing environment variables: {', '.join(missing)}")
        click.echo("Add these to your .env file:")
        click.echo("DATABASE_URL=postgresql://app_user:LegalDoc2025!Secure@localhost:5433/legal_doc_processing")
        click.echo("DATABASE_URL_DIRECT=postgresql://app_user:LegalDoc2025!Secure@database1.cuviucyodbeg.us-east-1.rds.amazonaws.com:5432/legal_doc_processing?sslmode=require")
    else:
        click.echo("✓ Environment variables configured")
```

## CLI Usage Examples

### Basic Database Operations

```bash
# Test database connection
python scripts/cli/admin.py verify-rds

# Create SSH tunnel
python scripts/cli/database.py tunnel

# Check database status
python scripts/cli/database.py status

# Execute query
python scripts/cli/database.py query "SELECT COUNT(*) FROM documents"

# Setup environment
python scripts/cli/admin.py setup-env
```

### Development Workflow

```bash
# 1. Start development session
python scripts/cli/database.py tunnel

# 2. Verify connection
python scripts/cli/admin.py verify-rds

# 3. Run your scripts
python scripts/pdf_pipeline.py

# 4. Monitor (optional)
python scripts/cli/monitor.py dashboard
```

## Production Deployment

### EC2 Instance Setup

When deploying on EC2 in the same VPC:

```bash
# Use direct connection (no tunnel needed)
export DATABASE_URL="postgresql://app_user:LegalDoc2025!Secure@database1.cuviucyodbeg.us-east-1.rds.amazonaws.com:5432/legal_doc_processing?sslmode=require"
```

### Environment Detection

```python
import os

def get_database_url():
    """Get appropriate database URL based on environment"""
    deployment_stage = os.getenv('DEPLOYMENT_STAGE', '1')
    
    if deployment_stage == '3':  # Local production
        return os.getenv('DATABASE_URL_DIRECT')
    else:  # Development/staging
        return os.getenv('DATABASE_URL')
```

## Troubleshooting

### Common Issues

1. **Connection Timeout**
   - Verify SSH tunnel: `lsof -ti:5433`
   - Check bastion host status
   - Verify security group allows your IP

2. **Authentication Failed**
   - Reset app_user password
   - Check password in environment variables
   - Try master user connection

3. **SSL Errors**
   - Use `?sslmode=require` for direct connections
   - Use `?sslmode=prefer` for flexibility

### Debug Commands

```bash
# Test SSH connectivity
ssh -i resources/aws/legal-doc-processor-bastion.pem ubuntu@54.162.223.205 "echo 'SSH working'"

# Test database with psql
PGPASSWORD='LegalDoc2025!Secure' psql -h localhost -p 5433 -U app_user -d legal_doc_processing -c "SELECT current_user;"

# Check tunnel process
ps aux | grep ssh | grep 5433
```

## Security Best Practices

1. **Never commit credentials to git**
2. **Use environment variables for all secrets**
3. **Rotate passwords regularly**
4. **Limit bastion host access to your IP**
5. **Stop bastion when not in use to save costs**

## Integration with Existing Pipeline

The RDS database integrates seamlessly with your existing pipeline:

- **Replace** `scripts/supabase_utils.py` imports with `scripts/rds_utils.py`
- **Update** connection strings in environment
- **Maintain** same function interfaces for minimal code changes
- **Use** tunnel for local development, direct connection for production

This setup provides a robust, scalable database solution for your legal document processing pipeline while maintaining development flexibility.