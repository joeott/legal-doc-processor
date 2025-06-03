# Context 300: Optimal Pipeline Completion Tasks

## Current State Summary

### ✅ RESOLVED: Database Visibility Issue
- Celery workers can now see documents created by test scripts
- Retry logic implemented with 3 attempts and 1-second delays
- Connection freshness checking every 60 seconds
- Database pool optimized for multi-process access

### ❌ CURRENT BLOCKER: Textract Job Submission
**Error**: "Failed to start Textract job"
**Root Cause**: Celery workers don't have AWS credentials in their environment

### ⏳ UNTESTED: Remaining Pipeline Stages
- Text chunking
- Entity extraction  
- Entity resolution
- Relationship building

## Optimal Task List for Pipeline Completion

### Task 1: Fix Celery Worker Environment (CRITICAL - 15 minutes)

**1.1 Create proper supervisor environment configuration**
```bash
# Create environment wrapper script
cat > /opt/legal-doc-processor/scripts/celery_worker_env.sh << 'EOF'
#!/bin/bash
# Load environment variables for Celery workers

# Source the .env file
if [ -f /opt/legal-doc-processor/.env ]; then
    set -a
    source /opt/legal-doc-processor/.env
    set +a
fi

# Ensure critical variables are exported
export PYTHONPATH="/opt/legal-doc-processor:${PYTHONPATH}"
export S3_BUCKET_REGION="us-east-2"

# Verify AWS credentials are loaded
if [ -z "$AWS_ACCESS_KEY_ID" ]; then
    echo "ERROR: AWS_ACCESS_KEY_ID not set" >&2
    exit 1
fi

# Execute the command passed as arguments
exec "$@"
EOF

chmod +x /opt/legal-doc-processor/scripts/celery_worker_env.sh
```

**1.2 Update supervisor configuration**
```bash
# Update each worker in /etc/supervisor/conf.d/celery-workers.conf
# Change command from:
#   command=celery -A scripts.celery_app worker ...
# To:
#   command=/opt/legal-doc-processor/scripts/celery_worker_env.sh celery -A scripts.celery_app worker ...

sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl restart celery:*
```

**1.3 Verify environment in workers**
```python
# scripts/verify_worker_env.py
from scripts.celery_app import app
import os

@app.task
def check_worker_env():
    return {
        'AWS_ACCESS_KEY_ID': bool(os.getenv('AWS_ACCESS_KEY_ID')),
        'AWS_SECRET_ACCESS_KEY': bool(os.getenv('AWS_SECRET_ACCESS_KEY')),
        'S3_BUCKET_REGION': os.getenv('S3_BUCKET_REGION'),
        'OPENAI_API_KEY': bool(os.getenv('OPENAI_API_KEY')),
        'PYTHONPATH': os.getenv('PYTHONPATH')
    }

# Run: python3 scripts/verify_worker_env.py
```

### Task 2: Implement Textract Debugging (10 minutes)

**2.1 Add detailed logging to textract_job_manager.py**
```python
def start_textract_job(self, document_uuid: str, file_path: str) -> Optional[str]:
    try:
        # Add logging
        logger.info(f"Starting Textract job - Region: {self.textract_client.meta.region_name}")
        logger.info(f"S3 URI: {file_path}")
        
        # Log AWS credentials status
        import boto3
        session = boto3.Session()
        credentials = session.get_credentials()
        if credentials:
            logger.info("AWS credentials available")
        else:
            logger.error("NO AWS CREDENTIALS FOUND")
            
        # ... rest of method
```

**2.2 Create Textract test script**
```python
# scripts/test_textract_directly.py
import boto3
import os

# Test Textract directly
textract = boto3.client('textract', region_name='us-east-2')
bucket = 'samu-docs-private-upload'
key = 'documents/test-document.pdf'

try:
    response = textract.start_document_text_detection(
        DocumentLocation={
            'S3Object': {
                'Bucket': bucket,
                'Name': key
            }
        }
    )
    print(f"✅ Textract job started: {response['JobId']}")
except Exception as e:
    print(f"❌ Textract error: {e}")
```

### Task 3: Create Comprehensive Pipeline Monitor (20 minutes)

**3.1 Implement robust monitoring script**
```python
# scripts/monitor_pipeline_complete.py
import time
from datetime import datetime
from scripts.db import DatabaseManager
from scripts.cache import get_redis_manager
from sqlalchemy import text

class PipelineMonitor:
    def __init__(self, document_uuid: str):
        self.document_uuid = document_uuid
        self.db = DatabaseManager(validate_conformance=False)
        self.redis = get_redis_manager()
        self.start_time = time.time()
        
    def check_ocr_status(self):
        """Check OCR processing status"""
        session = next(self.db.get_session())
        result = session.execute(
            text("""
                SELECT textract_job_id, textract_job_status, 
                       ocr_completed_at, error_message,
                       raw_extracted_text IS NOT NULL as has_text
                FROM source_documents 
                WHERE document_uuid = :uuid
            """),
            {"uuid": self.document_uuid}
        ).first()
        session.close()
        
        return {
            'job_id': result[0],
            'status': result[1],
            'completed': result[2],
            'error': result[3],
            'has_text': result[4]
        }
    
    def check_chunks(self):
        """Check chunking status"""
        session = next(self.db.get_session())
        count = session.execute(
            text("SELECT COUNT(*) FROM document_chunks WHERE document_uuid = :uuid"),
            {"uuid": self.document_uuid}
        ).scalar()
        session.close()
        return {'count': count}
    
    def monitor(self, timeout=300):
        """Monitor pipeline until completion or timeout"""
        while time.time() - self.start_time < timeout:
            ocr = self.check_ocr_status()
            chunks = self.check_chunks()
            
            elapsed = int(time.time() - self.start_time)
            print(f"\n[{elapsed}s] Pipeline Status:")
            print(f"  OCR: {ocr}")
            print(f"  Chunks: {chunks}")
            
            if ocr['completed'] and chunks['count'] > 0:
                print("\n✅ PIPELINE COMPLETED!")
                return True
                
            if ocr['error']:
                print(f"\n❌ ERROR: {ocr['error']}")
                return False
                
            time.sleep(5)
            
        print("\n⏰ TIMEOUT")
        return False
```

### Task 4: Production Deployment Steps (30 minutes)

**4.1 Environment Setup**
```bash
# 1. Backup current configuration
sudo cp -r /etc/supervisor/conf.d /etc/supervisor/conf.d.backup

# 2. Create production environment file
cat > /opt/legal-doc-processor/scripts/production.env << 'EOF'
# Production environment overrides
export ENVIRONMENT=production
export DEPLOYMENT_STAGE=1
export LOG_LEVEL=INFO
export CELERY_WORKER_CONCURRENCY=4
export CELERY_WORKER_PREFETCH_MULTIPLIER=1
EOF

# 3. Update systemd service (if using)
sudo systemctl daemon-reload
```

**4.2 Health Check Implementation**
```python
# scripts/health_check.py
from scripts.celery_app import app
from scripts.db import DatabaseManager
from scripts.cache import get_redis_manager
import boto3

def check_all_services():
    health = {
        'database': False,
        'redis': False,
        's3': False,
        'textract': False,
        'celery': False
    }
    
    # Database
    try:
        db = DatabaseManager(validate_conformance=False)
        session = next(db.get_session())
        session.execute(text("SELECT 1"))
        session.close()
        health['database'] = True
    except:
        pass
    
    # Redis
    try:
        redis = get_redis_manager()
        redis.ping()
        health['redis'] = True
    except:
        pass
    
    # S3
    try:
        s3 = boto3.client('s3', region_name='us-east-2')
        s3.head_bucket(Bucket='samu-docs-private-upload')
        health['s3'] = True
    except:
        pass
    
    # Textract
    try:
        textract = boto3.client('textract', region_name='us-east-2')
        # Just create client, don't make API call
        health['textract'] = True
    except:
        pass
    
    # Celery
    try:
        i = app.control.inspect()
        stats = i.stats()
        if stats:
            health['celery'] = True
    except:
        pass
    
    return health
```

**4.3 Monitoring Dashboard**
```bash
# Create monitoring script
cat > /opt/legal-doc-processor/scripts/monitor_dashboard.sh << 'EOF'
#!/bin/bash
while true; do
    clear
    echo "=== PIPELINE MONITORING DASHBOARD ==="
    echo "Time: $(date)"
    echo ""
    
    # Worker status
    echo "CELERY WORKERS:"
    sudo supervisorctl status celery:*
    echo ""
    
    # Recent documents
    echo "RECENT DOCUMENTS:"
    psql -U app_user -d legal_doc_processing -h localhost -p 5432 -c "
        SELECT document_uuid, celery_status, textract_job_status, 
               created_at, error_message
        FROM source_documents 
        ORDER BY created_at DESC 
        LIMIT 5;
    "
    
    # Redis info
    echo "REDIS STATUS:"
    redis-cli -h $REDIS_HOST -p $REDIS_PORT -a $REDIS_PASSWORD info keyspace
    
    sleep 10
done
EOF

chmod +x /opt/legal-doc-processor/scripts/monitor_dashboard.sh
```

### Task 5: Final Testing Protocol (15 minutes)

**5.1 Single Document Test**
```bash
# Test with proper environment
cd /opt/legal-doc-processor
source scripts/production.env
python3 scripts/test_region_fix_complete.py
```

**5.2 Load Test**
```python
# scripts/load_test_pipeline.py
import concurrent.futures
from scripts.test_region_fix_complete import create_test_document

def test_document(index):
    print(f"Creating document {index}...")
    doc_uuid = create_test_document()
    monitor = PipelineMonitor(doc_uuid)
    success = monitor.monitor(timeout=300)
    return {'index': index, 'uuid': doc_uuid, 'success': success}

# Test with 5 concurrent documents
with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
    futures = [executor.submit(test_document, i) for i in range(5)]
    results = [f.result() for f in futures]
    
print(f"Success rate: {sum(r['success'] for r in results)}/5")
```

## Success Metrics

### Immediate Success (Task 1-2)
- [ ] Celery workers have AWS credentials
- [ ] Textract job submission succeeds
- [ ] Job ID stored in database

### Pipeline Success (Task 3)
- [ ] OCR completes within 2 minutes
- [ ] Text extracted and stored
- [ ] Chunks created (>5 per document)
- [ ] Entities extracted (>10 per document)
- [ ] Relationships identified

### Production Success (Task 4-5)
- [ ] 95% success rate on document processing
- [ ] Average processing time < 5 minutes
- [ ] No memory leaks after 100 documents
- [ ] Graceful error handling and recovery

## Emergency Rollback Plan

If issues occur:
```bash
# 1. Stop workers
sudo supervisorctl stop celery:*

# 2. Restore configuration
sudo cp -r /etc/supervisor/conf.d.backup/* /etc/supervisor/conf.d/

# 3. Clear Redis cache
redis-cli -h $REDIS_HOST -p $REDIS_PORT -a $REDIS_PASSWORD FLUSHDB

# 4. Restart workers
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl start celery:*
```

## Next Actions Priority

1. **IMMEDIATE**: Fix Celery worker environment (Task 1)
2. **HIGH**: Verify Textract works (Task 2)  
3. **HIGH**: Monitor full pipeline (Task 3)
4. **MEDIUM**: Production deployment (Task 4)
5. **LOW**: Load testing (Task 5)

The key insight is that we're very close - just need to ensure Celery workers have the proper environment variables to access AWS services.