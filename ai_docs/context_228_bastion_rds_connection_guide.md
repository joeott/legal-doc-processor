# Context 228: Bastion and RDS Connection Guide

**Date**: 2025-05-29
**Type**: Infrastructure Guide
**Status**: ACTIVE
**Component**: EC2 Bastion + RDS PostgreSQL

## Overview

This guide provides comprehensive instructions for connecting to the RDS PostgreSQL instance via the EC2 bastion host. The bastion serves as a secure jump server to access the RDS instance in the private subnet.

## Infrastructure Details

### EC2 Bastion Host
- **Instance ID**: `i-0e431c454a7c3c6a1`
- **Public IP**: `54.162.223.205`
- **Private IP**: `172.31.33.106`
- **Instance Type**: `t3.medium`
- **Region**: `us-east-1`
- **SSH User**: `ubuntu`
- **PEM Key**: `resources/aws/legal-doc-processor-bastion.pem`
- **Security Group**: Allows SSH from IP `108.210.14.204`

### RDS PostgreSQL Instance
- **Endpoint**: `database1.cuviucyodbeg.us-east-1.rds.amazonaws.com`
- **Port**: `5432`
- **Database**: `legal_doc_processing`
- **App User**: `app_user`
- **App Password**: `LegalDoc2025!Secure`
- **Master User**: `postgres`
- **Master Password**: In `.env` as `RDS_MASTER_PASSWORD`
- **Version**: PostgreSQL 17.2

## Connection Methods

### 1. Direct SSH to Bastion

```bash
ssh -i resources/aws/legal-doc-processor-bastion.pem ubuntu@54.162.223.205
```

If permission denied:
```bash
chmod 400 resources/aws/legal-doc-processor-bastion.pem
```

### 2. Create SSH Tunnel for Database Access

```bash
# Create tunnel on local port 5433
ssh -f -N -L 5433:database1.cuviucyodbeg.us-east-1.rds.amazonaws.com:5432 \
    -i resources/aws/legal-doc-processor-bastion.pem \
    ubuntu@54.162.223.205

# Verify tunnel is active
lsof -ti:5433
```

### 3. Connect to Database via Tunnel

```bash
# As application user
PGPASSWORD='LegalDoc2025!Secure' psql \
    -h localhost \
    -p 5433 \
    -U app_user \
    -d legal_doc_processing

# As master user (for admin tasks)
PGPASSWORD='<master_password>' psql \
    -h localhost \
    -p 5433 \
    -U postgres \
    -d legal_doc_processing
```

### 4. Close SSH Tunnel

```bash
# Find and kill tunnel process
lsof -ti:5433 | xargs kill -9
```

## Database Operations

### Check Database Status

```sql
-- Connected as app_user
SELECT current_user, current_database();
SELECT version();

-- List tables
\dt

-- Check table counts
SELECT table_name, 
       (xpath('/row/cnt/text()', 
              query_to_xml(format('SELECT COUNT(*) as cnt FROM %I', table_name), 
                           false, true, '')))[1]::text::int AS row_count
FROM information_schema.tables
WHERE table_schema = 'public' 
AND table_type = 'BASE TABLE';
```

### Run Schema Migrations

```bash
# From local machine with tunnel active
psql -h localhost -p 5433 -U app_user -d legal_doc_processing < scripts/migration.sql
```

## Python Connection

### With SSH Tunnel

```python
# .env configuration
DATABASE_URL=postgresql://app_user:LegalDoc2025!Secure@localhost:5433/legal_doc_processing

# Python code
from sqlalchemy import create_engine
import os

engine = create_engine(os.getenv('DATABASE_URL'))
with engine.connect() as conn:
    result = conn.execute("SELECT version()")
    print(result.scalar())
```

### Direct from EC2 (if deployed on EC2)

```python
# .env configuration
DATABASE_URL=postgresql://app_user:LegalDoc2025!Secure@database1.cuviucyodbeg.us-east-1.rds.amazonaws.com:5432/legal_doc_processing?sslmode=require
```

## Troubleshooting

### SSH Connection Issues

1. **Permission denied (publickey)**
   ```bash
   # Check key permissions
   ls -la resources/aws/legal-doc-processor-bastion.pem
   # Should be -r-------- (400)
   ```

2. **Connection timeout**
   - Check bastion is running: `aws ec2 describe-instances --instance-ids i-0e431c454a7c3c6a1`
   - Verify your public IP: `curl ifconfig.me`
   - Update security group if IP changed

3. **Host key verification failed**
   ```bash
   ssh-keyscan -H 54.162.223.205 >> ~/.ssh/known_hosts
   ```

### Database Connection Issues

1. **Password authentication failed**
   - Check password in `.env`
   - Ensure no special characters need escaping
   - Try connecting as master user first

2. **Connection refused on port 5433**
   - Tunnel not active: Create new tunnel
   - Port already in use: `lsof -ti:5433 | xargs kill -9`

3. **SSL connection required**
   - Add `?sslmode=require` to connection string
   - Or use `sslmode=prefer` for flexibility

## Security Best Practices

1. **Never commit credentials**
   - Keep `.env` in `.gitignore`
   - Use environment variables

2. **Rotate passwords regularly**
   ```sql
   -- As master user
   ALTER USER app_user WITH PASSWORD 'NewSecurePassword123!';
   ```

3. **Limit bastion access**
   - Keep security group restricted to your IP
   - Stop bastion when not in use

4. **Use read-only users for reporting**
   ```sql
   -- Create read-only user
   CREATE USER readonly_user WITH PASSWORD 'ReadOnly123!';
   GRANT CONNECT ON DATABASE legal_doc_processing TO readonly_user;
   GRANT USAGE ON SCHEMA public TO readonly_user;
   GRANT SELECT ON ALL TABLES IN SCHEMA public TO readonly_user;
   ```

## Cost Management

### Stop Bastion When Not in Use

```bash
# Stop instance
aws ec2 stop-instances --instance-ids i-0e431c454a7c3c6a1

# Start when needed
aws ec2 start-instances --instance-ids i-0e431c454a7c3c6a1

# Get new public IP after start
aws ec2 describe-instances --instance-ids i-0e431c454a7c3c6a1 \
    --query 'Reservations[0].Instances[0].PublicIpAddress' \
    --output text
```

### Monitor RDS Usage

```bash
# Check database size
PGPASSWORD='LegalDoc2025!Secure' psql -h localhost -p 5433 -U app_user -d legal_doc_processing -c "
SELECT pg_database_size('legal_doc_processing') / 1024 / 1024 AS size_mb;"
```

## Backup and Recovery

### Manual Backup

```bash
# Create backup via tunnel
PGPASSWORD='LegalDoc2025!Secure' pg_dump \
    -h localhost -p 5433 -U app_user \
    -d legal_doc_processing \
    -f backup_$(date +%Y%m%d_%H%M%S).sql
```

### Restore from Backup

```bash
# Restore via tunnel
PGPASSWORD='LegalDoc2025!Secure' psql \
    -h localhost -p 5433 -U app_user \
    -d legal_doc_processing \
    < backup_20250529_120000.sql
```

## Monitoring

### Check Active Connections

```sql
SELECT pid, usename, application_name, client_addr, state
FROM pg_stat_activity
WHERE datname = 'legal_doc_processing';
```

### Check Table Sizes

```sql
SELECT schemaname, tablename, 
       pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;
```

## Quick Reference

```bash
# One-liner to create tunnel and connect
ssh -f -N -L 5433:database1.cuviucyodbeg.us-east-1.rds.amazonaws.com:5432 -i resources/aws/legal-doc-processor-bastion.pem ubuntu@54.162.223.205 && PGPASSWORD='LegalDoc2025!Secure' psql -h localhost -p 5433 -U app_user -d legal_doc_processing
```

## Related Scripts

- `scripts/init_rds_database.sh` - Initialize database and user
- `scripts/deploy_via_bastion.sh` - Deploy schema
- `scripts/test_app_connection.py` - Test connection
- `scripts/test_rds_tunnel.sh` - Test SSH tunnel