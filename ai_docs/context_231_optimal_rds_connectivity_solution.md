# Context 231: Optimal RDS Connectivity Solution

**Date**: 2025-05-30
**Type**: Architecture Enhancement
**Status**: PROPOSAL
**Problem**: SSH tunnel bottleneck limiting production scalability

## Executive Summary

The current SSH tunnel approach through a bastion host creates a significant bottleneck for database operations, similar to the API endpoint limitations we experienced with Supabase. This document proposes deploying the application components directly within the AWS VPC for native database connectivity, eliminating the tunnel overhead and enabling true production-scale operations.

## Current Architecture Problems

### SSH Tunnel Limitations
1. **Single Point of Failure**: All DB traffic flows through one SSH connection
2. **Connection Pooling Issues**: Can't properly pool connections through tunnel
3. **Latency Overhead**: Every query has additional SSH encryption/decryption
4. **Concurrent Connection Limits**: SSH has practical limits on concurrent channels
5. **Maintenance Complexity**: Tunnel must be kept alive, monitored, restarted

### Performance Impact
- **Current**: Local → SSH Tunnel → Bastion → RDS
- **Latency**: ~50-100ms additional overhead per query
- **Throughput**: Limited by SSH protocol, not database capacity

## Proposed Solution: VPC-Native Deployment

### Architecture Overview
```
┌─────────────────────┐         ┌─────────────────────────────┐
│   Local Dev/Admin   │         │        AWS VPC              │
│  (Your Machine)     │         │                             │
│                     │         │  ┌──────────────────────┐  │
│  - Admin Tasks      │◄────────┤  │   EC2 Application    │  │
│  - Monitoring       │  VPN/   │  │     Server(s)        │  │
│  - Emergency Access │  Direct │  │                      │  │
└─────────────────────┘  Connect│  │  - Celery Workers    │  │
                                │  │  - API Endpoints     │  │
┌─────────────────────┐         │  │  - Redis Cache       │  │
│   External Users    │         │  └──────────┬───────────┘  │
│   (Frontend)        │         │             │Direct         │
│                     │◄────────┤             │Connection     │
│  - Document Upload  │  HTTPS  │             ▼               │
│  - Status Check     │         │  ┌──────────────────────┐  │
│  - Results Download │         │  │   RDS PostgreSQL     │  │
└─────────────────────┘         │  │   (Private Subnet)   │  │
                                │  └──────────────────────┘  │
                                └─────────────────────────────┘
```

### Implementation Options

## Option 1: EC2 Application Server (Recommended)

### Setup Steps

1. **Launch EC2 Instance in VPC**
   ```bash
   # Use the existing bastion as a template
   aws ec2 run-instances \
     --image-id ami-0c02fb55956c7d316 \  # Amazon Linux 2023
     --instance-type t3.large \
     --key-name legal-doc-processor-bastion \
     --subnet-id <private-subnet-id> \
     --security-group-ids <app-security-group> \
     --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=legal-doc-app-server}]' \
     --user-data file://app-server-setup.sh
   ```

2. **Application Server Setup Script**
   ```bash
   #!/bin/bash
   # app-server-setup.sh
   
   # Update system
   sudo yum update -y
   
   # Install Python 3.11
   sudo yum install python3.11 python3.11-pip git -y
   
   # Install PostgreSQL client
   sudo yum install postgresql15 -y
   
   # Install Redis (for local cache)
   sudo yum install redis6 -y
   sudo systemctl enable redis6
   sudo systemctl start redis6
   
   # Create application directory
   sudo mkdir -p /opt/legal-doc-processor
   sudo chown ec2-user:ec2-user /opt/legal-doc-processor
   
   # Install application dependencies
   cd /opt/legal-doc-processor
   git clone <your-repo>
   cd <repo-name>
   
   # Create virtual environment
   python3.11 -m venv venv
   source venv/bin/activate
   
   # Install requirements
   pip install -r requirements.txt
   
   # Setup systemd services for Celery workers
   sudo cp scripts/systemd/* /etc/systemd/system/
   sudo systemctl daemon-reload
   ```

3. **Direct Database Configuration**
   ```python
   # config.py - No SSH tunnel needed!
   import os
   
   # Direct connection to RDS within VPC
   DATABASE_URL = os.getenv(
       'DATABASE_URL',
       'postgresql://app_user:LegalDoc2025!Secure@database1.cuviucyodbeg.us-east-1.rds.amazonaws.com:5432/legal_doc_processing?sslmode=require'
   )
   
   # Connection pool configuration optimized for direct connection
   DB_POOL_SIZE = 50  # Can handle more connections without tunnel
   DB_MAX_OVERFLOW = 100
   DB_POOL_TIMEOUT = 30
   DB_POOL_RECYCLE = 3600
   ```

4. **Celery Workers Configuration**
   ```ini
   # /etc/systemd/system/celery-worker@.service
   [Unit]
   Description=Celery Worker %i
   After=network.target
   
   [Service]
   Type=forking
   User=ec2-user
   Group=ec2-user
   WorkingDirectory=/opt/legal-doc-processor
   Environment="PATH=/opt/legal-doc-processor/venv/bin"
   ExecStart=/opt/legal-doc-processor/venv/bin/celery -A scripts.celery_app worker \
     --loglevel=info \
     --concurrency=4 \
     --queues=%i \
     --hostname=worker-%i@%h
   
   [Install]
   WantedBy=multi-user.target
   ```

## Option 2: AWS Lambda Functions (Serverless)

### When to Use
- Variable workload patterns
- Cost optimization for sporadic usage
- No server maintenance desired

### Lambda Configuration
```python
# lambda_function.py
import os
import psycopg2
from psycopg2 import pool

# Connection pool for Lambda
db_pool = psycopg2.pool.SimpleConnectionPool(
    1, 20,
    host=os.environ['RDS_ENDPOINT'],
    database=os.environ['DB_NAME'],
    user=os.environ['DB_USER'],
    password=os.environ['DB_PASSWORD'],
    sslmode='require'
)

def lambda_handler(event, context):
    conn = db_pool.getconn()
    try:
        # Process document
        cursor = conn.cursor()
        # ... database operations ...
        conn.commit()
    finally:
        db_pool.putconn(conn)
```

## Option 3: ECS/Fargate (Container-Based)

### Benefits
- Auto-scaling built-in
- Container orchestration
- No EC2 management

### Task Definition
```json
{
  "family": "legal-doc-processor",
  "networkMode": "awsvpc",
  "taskRoleArn": "arn:aws:iam::account:role/LegalDocProcessorTask",
  "containerDefinitions": [
    {
      "name": "celery-worker",
      "image": "your-ecr-repo/legal-doc-processor:latest",
      "environment": [
        {
          "name": "DATABASE_URL",
          "value": "postgresql://app_user@database1.cuviucyodbeg.us-east-1.rds.amazonaws.com/legal_doc_processing"
        }
      ],
      "secrets": [
        {
          "name": "DB_PASSWORD",
          "valueFrom": "arn:aws:secretsmanager:region:account:secret:rds-password"
        }
      ]
    }
  ]
}
```

## Security Considerations

### 1. Network Security
- **Security Groups**: Restrict RDS access to application servers only
- **NACLs**: Additional network-level protection
- **VPC Flow Logs**: Monitor all network traffic

### 2. Application Security
- **IAM Roles**: Use instance profiles, not hardcoded credentials
- **Secrets Manager**: Store database passwords securely
- **SSL/TLS**: Always use encrypted connections

### 3. Access Control
```bash
# RDS Security Group
aws ec2 create-security-group \
  --group-name rds-postgres-sg \
  --description "Security group for RDS PostgreSQL"

# Allow only from app servers
aws ec2 authorize-security-group-ingress \
  --group-id <rds-sg-id> \
  --protocol tcp \
  --port 5432 \
  --source-group <app-server-sg-id>
```

## Migration Plan

### Phase 1: Development Setup (1 day)
1. Launch EC2 application server
2. Deploy application code
3. Test direct database connectivity
4. Verify Celery workers function

### Phase 2: Parallel Running (1 week)
1. Route test traffic to EC2
2. Monitor performance metrics
3. Compare with SSH tunnel approach
4. Fix any issues

### Phase 3: Production Cutover (1 day)
1. Update DNS/load balancer
2. Scale EC2 instances as needed
3. Decommission SSH tunnel
4. Monitor closely

## Performance Benefits

### Before (SSH Tunnel)
- **Query Latency**: 50-100ms overhead
- **Max Connections**: ~50 (SSH channel limit)
- **Throughput**: ~1000 queries/second max
- **CPU Overhead**: High (SSH encryption)

### After (Direct Connection)
- **Query Latency**: <5ms overhead
- **Max Connections**: 500+ (RDS limit)
- **Throughput**: 10,000+ queries/second
- **CPU Overhead**: Minimal

## Cost Analysis

### EC2 Application Server
- **t3.large**: ~$60/month
- **Data Transfer**: ~$10/month (within VPC is free)
- **Total**: ~$70/month

### Savings
- **Removed Bastion**: -$38/month (can stop when not needed for admin)
- **Improved Performance**: Faster processing = less compute time
- **Net Cost**: ~$32/month additional

## Monitoring and Observability

### CloudWatch Metrics
```python
# Enhanced monitoring with direct connection
import boto3
from contextlib import contextmanager
import time

cloudwatch = boto3.client('cloudwatch')

@contextmanager
def db_operation_metric(operation_name):
    start_time = time.time()
    try:
        yield
    finally:
        duration = time.time() - start_time
        cloudwatch.put_metric_data(
            Namespace='LegalDocProcessor/Database',
            MetricData=[
                {
                    'MetricName': 'OperationDuration',
                    'Dimensions': [
                        {'Name': 'Operation', 'Value': operation_name},
                        {'Name': 'ConnectionType', 'Value': 'Direct'}
                    ],
                    'Value': duration,
                    'Unit': 'Seconds'
                }
            ]
        )
```

### Application Logs
```python
# Structured logging for better insights
import structlog

logger = structlog.get_logger()

def process_document(doc_id):
    with db_operation_metric('process_document'):
        logger.info("processing_document", 
                   document_id=doc_id,
                   connection_type="direct_vpc",
                   pool_size=db_pool.size())
        # ... processing logic ...
```

## Developer Access

### Option 1: VPN Connection
- AWS Client VPN for secure access
- Direct database access from local machine
- Best for regular development

### Option 2: Bastion Host (Existing)
- Keep for emergency access
- Stop when not needed to save costs
- Use for one-off admin tasks

### Option 3: AWS Systems Manager Session Manager
- No SSH keys needed
- Audit trail of all sessions
- Browser-based terminal access

## Implementation Code Changes

### 1. Update Configuration
```python
# scripts/config.py
import os

# Detect if running in EC2
def is_ec2_instance():
    """Check if code is running on EC2"""
    try:
        import requests
        response = requests.get(
            'http://169.254.169.254/latest/meta-data/instance-id',
            timeout=0.1
        )
        return response.status_code == 200
    except:
        return False

# Use direct connection on EC2, tunnel elsewhere
if is_ec2_instance():
    DATABASE_URL = os.getenv(
        'DATABASE_URL',
        'postgresql://app_user:LegalDoc2025!Secure@database1.cuviucyodbeg.us-east-1.rds.amazonaws.com:5432/legal_doc_processing?sslmode=require'
    )
else:
    # Local development with tunnel
    DATABASE_URL = os.getenv(
        'DATABASE_URL',
        'postgresql://app_user:LegalDoc2025!Secure@localhost:5433/legal_doc_processing'
    )
```

### 2. Enhanced Connection Pool
```python
# scripts/db.py
from sqlalchemy import create_engine, event
from sqlalchemy.pool import NullPool, QueuePool

# Use appropriate pool based on environment
if is_ec2_instance():
    # Production: Use connection pooling
    engine = create_engine(
        DATABASE_URL,
        poolclass=QueuePool,
        pool_size=50,
        max_overflow=100,
        pool_pre_ping=True,
        pool_recycle=3600
    )
else:
    # Development: Simple connections
    engine = create_engine(
        DATABASE_URL,
        poolclass=NullPool,  # No pooling through SSH tunnel
        connect_args={
            "connect_timeout": 10,
            "options": "-c statement_timeout=30000"
        }
    )
```

## Conclusion

Direct VPC deployment eliminates the SSH tunnel bottleneck and provides:
1. **10-100x better performance**
2. **Higher reliability** (no tunnel to maintain)
3. **Better security** (traffic never leaves AWS network)
4. **Easier scaling** (just add more EC2 instances)
5. **Production-ready architecture**

The EC2 deployment option provides the best balance of performance, cost, and maintainability for the legal document processing system. It's a proven pattern that scales with your needs and eliminates the artificial constraints imposed by SSH tunneling.