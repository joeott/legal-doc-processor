# Context 246: EC2 Migration Plan for Preprocessing Pipeline

## Executive Summary

This document outlines the comprehensive plan to migrate the PDF preprocessing pipeline from local/external execution to the EC2 bastion instance that already has direct database connectivity. This migration will eliminate SSH tunnel issues and provide stable, high-performance database access.

## Current Infrastructure

### EC2 Bastion Instance (Target)
- **Instance**: `i-0e431c454a7c3c6a1` (t3.medium)
- **Public IP**: `54.162.223.205`
- **OS**: Ubuntu
- **Direct RDS Access**: Yes (within VPC)
- **Current Role**: SSH tunnel bastion

### RDS Database
- **Endpoint**: `database1.cuviucyodbeg.us-east-1.rds.amazonaws.com:5432`
- **Direct Access from EC2**: Yes
- **Connection String**: `postgresql://app_user:LegalDoc2025!Secure@database1.cuviucyodbeg.us-east-1.rds.amazonaws.com:5432/legal_doc_processing?sslmode=require`

## Migration Strategy

### Phase 1: Infrastructure Preparation (Day 1)

#### 1.1 Upgrade EC2 Instance
```bash
# Current: t3.medium (2 vCPU, 4GB RAM)
# Recommended: t3.xlarge (4 vCPU, 16GB RAM) for Celery workers
aws ec2 modify-instance-attribute \
    --instance-id i-0e431c454a7c3c6a1 \
    --instance-type "{\"Value\": \"t3.xlarge\"}"
```

#### 1.2 Install System Dependencies
```bash
# Connect to EC2
ssh -i resources/aws/legal-doc-processor-bastion.pem ubuntu@54.162.223.205

# Update system
sudo apt-get update && sudo apt-get upgrade -y

# Install Python 3.11
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt-get install python3.11 python3.11-venv python3.11-dev -y

# Install system dependencies
sudo apt-get install -y \
    postgresql-client \
    redis-tools \
    git \
    nginx \
    supervisor \
    build-essential \
    libpq-dev \
    poppler-utils \
    tesseract-ocr
```

#### 1.3 Setup Storage
```bash
# Create application directories
sudo mkdir -p /opt/legal-doc-processor
sudo mkdir -p /var/log/legal-doc-processor
sudo mkdir -p /var/lib/legal-doc-processor/cache
sudo chown -R ubuntu:ubuntu /opt/legal-doc-processor
sudo chown -R ubuntu:ubuntu /var/log/legal-doc-processor
```

### Phase 2: Code Deployment (Day 1-2)

#### 2.1 Repository Structure on EC2
```
/opt/legal-doc-processor/
   scripts/              # Core processing scripts
      core/            # Models and validators
      database/        # Database utilities
      services/        # Business logic services
      monitoring/      # CloudWatch integration
      cli/             # Command-line tools
      *.py            # Main processing scripts
   config/              # Configuration files
      .env            # Environment variables
      celery.conf     # Celery configuration
      supervisord.conf # Process management
   logs/                # Application logs
   venv/                # Python virtual environment
   data/                # Temporary processing data
```

#### 2.2 Deployment Script
```bash
#!/bin/bash
# deploy_to_ec2.sh

EC2_HOST="ubuntu@54.162.223.205"
EC2_KEY="resources/aws/legal-doc-processor-bastion.pem"
REMOTE_DIR="/opt/legal-doc-processor"

# Create deployment package
echo "Creating deployment package..."
tar -czf deployment.tar.gz \
    scripts/ \
    requirements.txt \
    --exclude="__pycache__" \
    --exclude="*.pyc" \
    --exclude="archive_pre_consolidation"

# Copy to EC2
echo "Copying to EC2..."
scp -i $EC2_KEY deployment.tar.gz $EC2_HOST:/tmp/

# Deploy on EC2
echo "Deploying on EC2..."
ssh -i $EC2_KEY $EC2_HOST << 'EOF'
    cd /opt/legal-doc-processor
    tar -xzf /tmp/deployment.tar.gz
    python3.11 -m venv venv
    source venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
    rm /tmp/deployment.tar.gz
EOF
```

### Phase 3: Service Configuration (Day 2)

#### 3.1 Environment Configuration
```bash
# /opt/legal-doc-processor/config/.env
# Database (Direct connection - no SSH tunnel needed!)
DATABASE_URL=postgresql://app_user:LegalDoc2025!Secure@database1.cuviucyodbeg.us-east-1.rds.amazonaws.com:5432/legal_doc_processing?sslmode=require
DATABASE_URL_DIRECT=postgresql://app_user:LegalDoc2025!Secure@database1.cuviucyodbeg.us-east-1.rds.amazonaws.com:5432/legal_doc_processing?sslmode=require

# Redis (using ElastiCache or Redis Cloud)
REDIS_HOST=redis-cloud-endpoint
REDIS_PORT=6379
REDIS_PASSWORD=your-redis-password

# AWS Configuration
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=your-key
AWS_SECRET_ACCESS_KEY=your-secret
S3_BUCKET_NAME=ott-law-documents

# OpenAI
OPENAI_API_KEY=your-openai-key

# Deployment
DEPLOYMENT_STAGE=2
WORKER_CONCURRENCY=4
```

#### 3.2 Celery Configuration
```ini
# /opt/legal-doc-processor/config/celery.conf
[program:celery-ocr]
command=/opt/legal-doc-processor/venv/bin/celery -A scripts.celery_app worker --loglevel=info -Q ocr -n worker.ocr@%%h
directory=/opt/legal-doc-processor
user=ubuntu
autostart=true
autorestart=true
stdout_logfile=/var/log/legal-doc-processor/celery-ocr.log
stderr_logfile=/var/log/legal-doc-processor/celery-ocr-error.log

[program:celery-text]
command=/opt/legal-doc-processor/venv/bin/celery -A scripts.celery_app worker --loglevel=info -Q text -n worker.text@%%h
directory=/opt/legal-doc-processor
user=ubuntu
autostart=true
autorestart=true
stdout_logfile=/var/log/legal-doc-processor/celery-text.log
stderr_logfile=/var/log/legal-doc-processor/celery-text-error.log

[program:celery-embeddings]
command=/opt/legal-doc-processor/venv/bin/celery -A scripts.celery_app worker --loglevel=info -Q embeddings -n worker.embeddings@%%h
directory=/opt/legal-doc-processor
user=ubuntu
autostart=true
autorestart=true
stdout_logfile=/var/log/legal-doc-processor/celery-embeddings.log
stderr_logfile=/var/log/legal-doc-processor/celery-embeddings-error.log

[program:celery-graph]
command=/opt/legal-doc-processor/venv/bin/celery -A scripts.celery_app worker --loglevel=info -Q graph -n worker.graph@%%h
directory=/opt/legal-doc-processor
user=ubuntu
autostart=true
autorestart=true
stdout_logfile=/var/log/legal-doc-processor/celery-graph.log
stderr_logfile=/var/log/legal-doc-processor/celery-graph-error.log
```

### Phase 4: Code Modifications (Day 2-3)

#### 4.1 Update Database Configuration
```python
# scripts/config.py - Add EC2-specific configuration
import os

def is_ec2_environment():
    """Check if running on EC2."""
    return os.path.exists('/opt/legal-doc-processor')

# Use direct connection on EC2
if is_ec2_environment():
    DATABASE_URL = os.getenv('DATABASE_URL_DIRECT')
else:
    DATABASE_URL = os.getenv('DATABASE_URL')  # SSH tunnel for local dev
```

#### 4.2 Update File Paths
```python
# scripts/config.py - EC2 file paths
if is_ec2_environment():
    BASE_DIR = '/opt/legal-doc-processor'
    LOG_DIR = '/var/log/legal-doc-processor'
    TEMP_DIR = '/var/lib/legal-doc-processor/temp'
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    LOG_DIR = os.path.join(BASE_DIR, 'logs')
    TEMP_DIR = os.path.join(BASE_DIR, 'temp')
```

#### 4.3 Create EC2 Health Check
```python
# scripts/monitoring/ec2_health.py
import psutil
import redis
from scripts.db import get_engine
from scripts.cache import get_redis_client

def check_ec2_health():
    """Health check for EC2 deployment."""
    health = {
        'cpu_percent': psutil.cpu_percent(interval=1),
        'memory_percent': psutil.virtual_memory().percent,
        'disk_usage': psutil.disk_usage('/').percent,
        'database': False,
        'redis': False,
        'celery_workers': {}
    }
    
    # Check database
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute("SELECT 1")
        health['database'] = True
    except Exception as e:
        health['database_error'] = str(e)
    
    # Check Redis
    try:
        r = get_redis_client()
        r.ping()
        health['redis'] = True
    except Exception as e:
        health['redis_error'] = str(e)
    
    # Check Celery workers
    for queue in ['ocr', 'text', 'embeddings', 'graph']:
        try:
            result = subprocess.check_output(
                f"supervisorctl status celery-{queue}", 
                shell=True
            ).decode()
            health['celery_workers'][queue] = 'RUNNING' in result
        except:
            health['celery_workers'][queue] = False
    
    return health
```

### Phase 5: Testing & Validation (Day 3)

#### 5.1 Deployment Validation Script
```bash
#!/bin/bash
# validate_deployment.sh

echo "=== EC2 Deployment Validation ==="

# Check Python environment
echo "1. Python Environment:"
/opt/legal-doc-processor/venv/bin/python --version

# Check database connectivity
echo "2. Database Connectivity:"
/opt/legal-doc-processor/venv/bin/python -c "
from scripts.db import get_engine
engine = get_engine()
print('Database connected successfully')
"

# Check Redis connectivity
echo "3. Redis Connectivity:"
/opt/legal-doc-processor/venv/bin/python -c "
from scripts.cache import get_redis_client
r = get_redis_client()
r.ping()
print('Redis connected successfully')
"

# Check Celery workers
echo "4. Celery Workers:"
sudo supervisorctl status

# Check S3 access
echo "5. S3 Access:"
/opt/legal-doc-processor/venv/bin/python -c "
from scripts.s3_storage import S3Storage
s3 = S3Storage()
print('S3 connected successfully')
"

# Run test document
echo "6. Test Document Processing:"
/opt/legal-doc-processor/venv/bin/python scripts/cli/admin.py test-pipeline
```

#### 5.2 Performance Testing
```python
# scripts/test_ec2_performance.py
import time
from scripts.pdf_tasks import process_pdf_document

def test_performance():
    """Test processing performance on EC2."""
    test_doc = {
        'document_uuid': 'test-' + str(uuid.uuid4()),
        'filename': 'test.pdf',
        's3_key': 'test/sample.pdf'
    }
    
    start_time = time.time()
    result = process_pdf_document(test_doc)
    end_time = time.time()
    
    print(f"Processing time: {end_time - start_time:.2f} seconds")
    print(f"Result: {result}")
```

### Phase 6: Monitoring & Maintenance (Ongoing)

#### 6.1 CloudWatch Integration
```python
# Already configured in scripts/monitoring/cloudwatch_logger.py
# Ensure logs are shipping to CloudWatch from EC2
```

#### 6.2 Automated Backups
```bash
# Cron job for log rotation and backup
0 0 * * * /usr/sbin/logrotate /opt/legal-doc-processor/config/logrotate.conf
0 2 * * * aws s3 sync /var/log/legal-doc-processor/ s3://ott-law-logs/ec2-processor/
```

#### 6.3 Auto-scaling Configuration
```yaml
# Future enhancement: Auto-scaling group configuration
# Scale based on queue depth in Redis
```

## Migration Checklist

- [ ] Upgrade EC2 instance type
- [ ] Install system dependencies
- [ ] Deploy code to EC2
- [ ] Configure environment variables
- [ ] Setup Supervisor for Celery workers
- [ ] Update database connection strings
- [ ] Test all components
- [ ] Configure monitoring
- [ ] Document access procedures
- [ ] Create runbooks for common operations

## Rollback Plan

If issues arise:
1. Stop Celery workers on EC2
2. Revert to local processing with SSH tunnel
3. Investigate and fix issues
4. Retry migration with fixes

## Benefits of EC2 Migration

1. **Direct Database Access**: No SSH tunnel required
2. **Better Performance**: ~10x faster database queries
3. **Higher Reliability**: No tunnel disconnections
4. **Scalability**: Easy to add more workers
5. **Cost Efficiency**: Better resource utilization
6. **Simplified Architecture**: Fewer moving parts

## Security Considerations

1. **Network Security**: EC2 and RDS in same VPC
2. **Access Control**: IAM roles for AWS services
3. **Encryption**: TLS for all connections
4. **Secrets Management**: Consider AWS Secrets Manager
5. **Audit Logging**: CloudWatch for all activities

## Next Steps

1. Review and approve migration plan
2. Schedule migration window
3. Execute Phase 1-3 (Infrastructure & Deployment)
4. Test with sample documents
5. Gradually migrate production workload
6. Monitor and optimize performance