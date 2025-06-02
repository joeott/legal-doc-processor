# Context 300: Pipeline Success Criteria and Document Completion Tasks

## Executive Summary
The database visibility fix has been successfully implemented. Celery workers can now find documents created by test scripts. The next blocker is "Failed to start Textract job" which indicates we need to fix the Textract configuration. This document defines success criteria and provides a task list to achieve full document processing completion.

## Current Status
✅ **FIXED**: Database visibility - Celery workers can see documents
❌ **NEW BLOCKER**: Textract job submission failing
⏳ **UNTESTED**: Remaining pipeline stages (chunking, entities, relationships)

## Success Criteria for Complete Pipeline

### 1. Document Upload & Creation (✅ WORKING)
- Document uploaded to S3 with correct region (us-east-2)
- Database record created with proper metadata
- Document visible to Celery workers

### 2. OCR Processing (❌ BLOCKED)
**Success Indicators:**
- Textract job ID created and stored
- Job status transitions: SUBMITTED → IN_PROGRESS → SUCCEEDED
- Raw text extracted and stored in database
- OCR completion timestamp recorded

**Monitoring Points:**
```python
# Check Textract job submission
SELECT textract_job_id, textract_job_status, error_message 
FROM source_documents WHERE document_uuid = ?

# Monitor Redis state
doc:state:{document_uuid} → ocr → processing/completed
```

### 3. Text Chunking (⏳ UNTESTED)
**Success Indicators:**
- Chunks created in document_chunks table
- Chunk count > 0 (typically 5-20 for legal documents)
- Each chunk has embeddings generated
- Chunk metadata includes position and context

**Monitoring Points:**
```python
# Check chunk creation
SELECT COUNT(*) FROM document_chunks WHERE document_id = ?

# Redis cache verification
chunks:{document_uuid} → list of chunk data
```

### 4. Entity Extraction (⏳ UNTESTED)
**Success Indicators:**
- Raw entities extracted in entity_mentions table
- Entity types include: PERSON, ORGANIZATION, LOCATION, DATE, etc.
- Confidence scores recorded
- Entity context preserved

**Monitoring Points:**
```python
# Check entity extraction
SELECT COUNT(*), entity_type FROM entity_mentions 
WHERE document_chunk_id IN (SELECT id FROM document_chunks WHERE document_id = ?)
GROUP BY entity_type
```

### 5. Entity Resolution (⏳ UNTESTED)
**Success Indicators:**
- Canonical entities created from mentions
- Duplicate entities merged
- Canonical forms established
- Cross-document entity linking

**Monitoring Points:**
```python
# Check canonical entities
SELECT COUNT(*) FROM canonical_entities 
WHERE id IN (SELECT canonical_entity_id FROM entity_mentions WHERE document_chunk_id IN ...)
```

### 6. Relationship Building (⏳ UNTESTED)
**Success Indicators:**
- Relationships staged in relationship_staging table
- Relationship types identified
- Confidence scores assigned
- Ready for Neo4j export

**Monitoring Points:**
```python
# Check relationships
SELECT COUNT(*), relationship_type FROM relationship_staging
WHERE project_id = ? GROUP BY relationship_type
```

## Immediate Action Items

### Task 1: Fix Textract Job Submission
**Issue**: "Failed to start Textract job"
**Likely Causes**:
1. AWS credentials not available to Celery workers
2. S3 bucket permissions for Textract
3. Region mismatch in Textract client
4. Missing IAM permissions

**Debug Steps**:
```bash
# 1. Check if Celery workers have AWS credentials
python3 -c "
from scripts.celery_app import app
@app.task
def check_aws_creds():
    import os
    return {
        'AWS_ACCESS_KEY_ID': bool(os.getenv('AWS_ACCESS_KEY_ID')),
        'AWS_SECRET_ACCESS_KEY': bool(os.getenv('AWS_SECRET_ACCESS_KEY')),
        'AWS_DEFAULT_REGION': os.getenv('AWS_DEFAULT_REGION'),
        'S3_BUCKET_REGION': os.getenv('S3_BUCKET_REGION')
    }
result = check_aws_creds.apply_async()
print(result.get(timeout=10))
"

# 2. Test Textract permissions directly
python3 scripts/test_textract_access.py

# 3. Check S3 bucket policy
python3 scripts/verify_bucket_policy.py
```

### Task 2: Complete Pipeline Test Script
Create a comprehensive test that tracks all stages:

```python
# scripts/test_complete_pipeline.py
import time
from scripts.db import DatabaseManager
from scripts.cache import get_redis_manager
from sqlalchemy import text

def monitor_pipeline_completion(document_uuid: str, timeout: int = 300):
    """Monitor all pipeline stages until completion or timeout"""
    db = DatabaseManager(validate_conformance=False)
    redis = get_redis_manager()
    start_time = time.time()
    
    stages = {
        'ocr': {'status': 'pending', 'details': {}},
        'chunking': {'status': 'pending', 'details': {}},
        'entities': {'status': 'pending', 'details': {}},
        'resolution': {'status': 'pending', 'details': {}},
        'relationships': {'status': 'pending', 'details': {}}
    }
    
    while time.time() - start_time < timeout:
        # Check document status
        session = next(db.get_session())
        
        # 1. OCR Status
        doc_result = session.execute(
            text("""SELECT textract_job_id, textract_job_status, ocr_completed_at,
                           raw_extracted_text IS NOT NULL as has_text
                    FROM source_documents WHERE document_uuid = :uuid"""),
            {"uuid": document_uuid}
        ).first()
        
        if doc_result:
            stages['ocr']['details'] = {
                'job_id': doc_result[0],
                'status': doc_result[1],
                'completed': doc_result[2],
                'has_text': doc_result[3]
            }
            if doc_result[2]:  # ocr_completed_at
                stages['ocr']['status'] = 'completed'
        
        # 2. Chunking Status
        chunk_count = session.execute(
            text("SELECT COUNT(*) FROM document_chunks WHERE document_id = :uuid"),
            {"uuid": document_uuid}
        ).scalar()
        
        stages['chunking']['details'] = {'chunk_count': chunk_count}
        if chunk_count > 0:
            stages['chunking']['status'] = 'completed'
        
        # 3. Entity Status
        entity_count = session.execute(
            text("""SELECT COUNT(*) FROM entity_mentions em
                    JOIN document_chunks dc ON em.document_chunk_id = dc.id
                    WHERE dc.document_id = :uuid"""),
            {"uuid": document_uuid}
        ).scalar()
        
        stages['entities']['details'] = {'entity_count': entity_count}
        if entity_count > 0:
            stages['entities']['status'] = 'completed'
        
        # 4. Check Redis state
        state_key = f"doc:state:{document_uuid}"
        doc_state = redis.get_dict(state_key)
        
        session.close()
        
        # Print status
        print(f"\n[{int(time.time() - start_time)}s] Pipeline Status:")
        for stage, info in stages.items():
            status_icon = '✅' if info['status'] == 'completed' else '⏳'
            print(f"  {status_icon} {stage}: {info['status']} - {info['details']}")
        
        # Check if all completed
        if all(s['status'] == 'completed' for s in stages.values()):
            print("\n🎉 PIPELINE COMPLETED SUCCESSFULLY!")
            return True
            
        time.sleep(5)
    
    print("\n⏰ TIMEOUT: Pipeline did not complete in time")
    return False
```

### Task 3: Environment Setup for Celery Workers
Ensure Celery workers have all required environment variables:

```bash
# 1. Create supervisor environment file
cat > /opt/legal-doc-processor/scripts/celery_env.sh << 'EOF'
#!/bin/bash
# Source main environment
set -a
source /opt/legal-doc-processor/.env
set +a

# Ensure critical variables are exported
export S3_BUCKET_REGION=us-east-2
export AWS_DEFAULT_REGION=us-east-1
export PYTHONPATH=/opt/legal-doc-processor:$PYTHONPATH
export USE_MINIMAL_MODELS=true
export SKIP_CONFORMANCE_CHECK=true

# Start worker with environment
exec "$@"
EOF

chmod +x /opt/legal-doc-processor/scripts/celery_env.sh

# 2. Update supervisor config to use env wrapper
# Edit /etc/supervisor/conf.d/celery.conf to use:
# command=/opt/legal-doc-processor/scripts/celery_env.sh celery -A scripts.celery_app worker ...
```

### Task 4: Production Monitoring Setup
Implement comprehensive monitoring:

```python
# scripts/monitor_pipeline_health.py
from scripts.celery_app import app
from scripts.db import DatabaseManager
from sqlalchemy import text
import json

@app.task(name='pipeline_health_check')
def pipeline_health_check():
    """Comprehensive pipeline health check"""
    db = DatabaseManager(validate_conformance=False)
    health = {
        'timestamp': datetime.utcnow().isoformat(),
        'status': 'healthy',
        'components': {}
    }
    
    try:
        # 1. Database connectivity
        session = next(db.get_session())
        db_result = session.execute(text("SELECT 1")).scalar()
        health['components']['database'] = {'status': 'ok', 'connected': True}
        
        # 2. Document processing stats
        stats = session.execute(text("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                SUM(CASE WHEN status = 'processing' THEN 1 ELSE 0 END) as processing
            FROM source_documents
            WHERE created_at > NOW() - INTERVAL '24 hours'
        """)).first()
        
        health['components']['documents'] = {
            'last_24h': {
                'total': stats[0],
                'completed': stats[1],
                'failed': stats[2],
                'processing': stats[3]
            }
        }
        
        # 3. Redis connectivity
        from scripts.cache import get_redis_manager
        redis = get_redis_manager()
        redis.ping()
        health['components']['redis'] = {'status': 'ok', 'connected': True}
        
        # 4. S3 accessibility
        from scripts.s3_storage import S3StorageManager
        s3 = S3StorageManager()
        # Quick bucket check
        health['components']['s3'] = {'status': 'ok', 'bucket': s3.bucket_name}
        
        # 5. Textract availability
        import boto3
        textract = boto3.client('textract', region_name='us-east-2')
        health['components']['textract'] = {'status': 'ok', 'region': 'us-east-2'}
        
        session.close()
        
    except Exception as e:
        health['status'] = 'unhealthy'
        health['error'] = str(e)
        
    return health
```

## Production Deployment Checklist

### Pre-deployment
- [ ] All environment variables set in supervisor config
- [ ] AWS credentials accessible to Celery workers
- [ ] S3 bucket policy allows Textract access
- [ ] Redis connection stable
- [ ] Database pool configuration optimized

### Deployment Steps
1. **Update Supervisor Configuration**
   ```bash
   sudo cp scripts/supervisor_celery_config.conf /etc/supervisor/conf.d/celery.conf
   sudo supervisorctl reread
   sudo supervisorctl update
   ```

2. **Verify Worker Health**
   ```bash
   # Check all workers started
   sudo supervisorctl status celery:*
   
   # Test database connectivity
   python3 -c "from scripts.pdf_tasks import monitor_db_connectivity; print(monitor_db_connectivity())"
   ```

3. **Run Integration Test**
   ```bash
   python3 scripts/test_complete_pipeline.py
   ```

### Post-deployment Monitoring
- [ ] Monitor error rates in CloudWatch
- [ ] Check Redis memory usage
- [ ] Verify document processing throughput
- [ ] Monitor Textract API usage and costs
- [ ] Check for stuck documents

## Success Metrics

### Real-time Metrics
- Document processing latency: < 5 minutes per document
- OCR success rate: > 95%
- Entity extraction accuracy: > 90%
- Pipeline completion rate: > 98%

### Daily Metrics
- Documents processed: Track daily volume
- Error rate by stage: Identify bottlenecks
- Average processing time by document type
- Resource utilization (CPU, memory, API calls)

## Next Steps Priority Order

1. **Fix Textract Configuration** (CRITICAL)
   - Verify AWS credentials in Celery environment
   - Check S3 bucket permissions
   - Test Textract client initialization

2. **Run Full Pipeline Test**
   - Use test_complete_pipeline.py
   - Monitor all stages to completion
   - Document any new blockers

3. **Deploy Monitoring**
   - Set up health check cron job
   - Configure alerts for failures
   - Create dashboard for metrics

4. **Performance Optimization**
   - Tune worker concurrency
   - Optimize chunk sizes
   - Implement caching strategies

5. **Production Readiness**
   - Load testing with multiple documents
   - Failure recovery procedures
   - Backup and restore processes