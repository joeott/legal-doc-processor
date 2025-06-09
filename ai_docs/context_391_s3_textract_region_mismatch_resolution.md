# Context 391: S3-Textract Region Mismatch Resolution

## Date: 2025-06-04 15:00

### Executive Summary
Production test stalled at OCR stage due to S3-Textract region mismatch. S3 bucket is in `us-east-2` while Textract was using `us-east-1`. This is a recurring issue we've solved multiple times.

### Problem Diagnosis

#### Error Message
```
Textract returned InvalidS3ObjectException. Ensure that the s3 path is correct 
and that both the Textract API and the bucket are in the same region.
```

#### Root Cause Analysis
1. **S3 Bucket Location**: `samu-docs-private-upload` is in `us-east-2`
2. **AWS Default Region**: Set to `us-east-1` in environment
3. **S3_BUCKET_REGION**: Not explicitly set in environment (relies on default in config.py)
4. **Worker Environment**: Workers started without S3_BUCKET_REGION environment variable

### Historical Context

#### Previous Solutions (from context_290_textract_region_fix.md)
1. Added `S3_BUCKET_REGION` configuration in `scripts/config.py`
2. Modified TextractProcessor to use S3_BUCKET_REGION
3. Created test scripts to verify region configuration

#### Current Implementation Status
- **config.py**: Correctly sets `S3_BUCKET_REGION = os.getenv('S3_BUCKET_REGION', 'us-east-2')`
- **textract_utils.py**: Correctly uses S3_BUCKET_REGION in TextractProcessor initialization
- **Environment**: S3_BUCKET_REGION not explicitly set, relying on default

### Solution Steps

#### 1. Set S3_BUCKET_REGION Explicitly
```bash
# Add to .env file or load_env.sh
export S3_BUCKET_REGION="us-east-2"
```

#### 2. Kill Existing Workers
```bash
# Kill all running Celery workers
ps aux | grep "[c]elery" | awk '{print $2}' | xargs -r kill -9
```

#### 3. Restart Workers with Correct Region
```bash
# Source environment with S3_BUCKET_REGION
source load_env.sh
export S3_BUCKET_REGION="us-east-2"

# Start workers with proper environment
celery -A scripts.celery_app worker --loglevel=info --queues=default,ocr,text,entity,graph,cleanup --concurrency=8 > celery_worker.log 2>&1 &
```

#### 4. Verify Region Configuration
```bash
# Check environment
echo "AWS_DEFAULT_REGION: $AWS_DEFAULT_REGION"
echo "S3_BUCKET_REGION: $S3_BUCKET_REGION"

# Verify S3 bucket location
aws s3api get-bucket-location --bucket samu-docs-private-upload
```

### Alternative Solutions

#### Option A: Change AWS_DEFAULT_REGION
```bash
# Set all AWS services to use us-east-2
export AWS_DEFAULT_REGION="us-east-2"
```

#### Option B: Use Direct Configuration
```python
# In scripts/textract_utils.py, hardcode the region
self.client = boto3.client('textract', region_name='us-east-2')
self.textractor = Textractor(region_name='us-east-2')
```

### Verification Steps

1. **Check Worker Logs**:
   ```bash
   tail -f celery_worker.log | grep "TextractProcessor initialized for region"
   ```

2. **Test Single Document**:
   ```bash
   python3 scripts/test_ocr_fallback.py
   ```

3. **Monitor Redis State**:
   ```bash
   # Check for successful OCR status
   REDISCLI_AUTH="BHMbnJHyf&9!4TT" redis-cli -h redis-12696.c325.us-east-1-4.ec2.redns.redis-cloud.com -p 12696 --user joe_ott get "doc:state:<document_uuid>" | python3 -m json.tool
   ```

### Production Test Recovery

After fixing the region issue:

1. **Clear Failed States** (Optional):
   ```bash
   # Reset failed OCR states in Redis
   for key in $(REDISCLI_AUTH="BHMbnJHyf&9!4TT" redis-cli -h redis-12696.c325.us-east-1-4.ec2.redns.redis-cloud.com -p 12696 --user joe_ott keys "doc:state:*"); do
     # Update failed OCR states to retry
   done
   ```

2. **Resubmit Failed Documents**:
   ```bash
   # Use existing run_production_test.py which should retry failed documents
   python3 run_production_test.py
   ```

3. **Monitor Progress**:
   ```bash
   python3 monitor_production_test.py
   ```

### Expected Outcomes

Once region is properly configured:
- OCR tasks will start succeeding
- Textract will process documents and extract text
- Pipeline will continue to chunking → entity extraction → resolution → relationships
- All 201 documents should process successfully

### Key Learnings

1. **Environment Variables**: Always explicitly set S3_BUCKET_REGION in production
2. **Worker Restarts**: Ensure workers inherit correct environment variables
3. **Region Consistency**: AWS services must use same region as S3 bucket
4. **Error Messages**: "InvalidS3ObjectException" usually means region mismatch

### Monitoring Commands

```bash
# Check OCR progress
PGPASSWORD="LegalDoc2025\!Secure" psql -h database1.cuviucyodbeg.us-east-1.rds.amazonaws.com -p 5432 -U app_user -d legal_doc_processing -c "SELECT COUNT(*) as total, COUNT(raw_extracted_text) as with_text FROM source_documents WHERE project_uuid = '4a0db6b4-7f77-4d51-9920-22fdd34eaac8';"

# Check processing tasks
PGPASSWORD="LegalDoc2025\!Secure" psql -h database1.cuviucyodbeg.us-east-1.rds.amazonaws.com -p 5432 -U app_user -d legal_doc_processing -c "SELECT task_type, status, COUNT(*) FROM processing_tasks WHERE document_id IN (SELECT document_uuid FROM source_documents WHERE project_uuid = '4a0db6b4-7f77-4d51-9920-22fdd34eaac8') GROUP BY task_type, status;"

# Check Redis document states
REDISCLI_AUTH="BHMbnJHyf&9!4TT" redis-cli -h redis-12696.c325.us-east-1-4.ec2.redns.redis-cloud.com -p 12696 --user joe_ott eval "local count = 0; local cursor = '0'; repeat local result = redis.call('SCAN', cursor, 'MATCH', 'doc:state:*', 'COUNT', 100); cursor = result[1]; count = count + #result[2]; until cursor == '0'; return count" 0
```

### Next Steps

1. Apply region fix immediately
2. Restart workers with correct configuration
3. Monitor OCR processing resumption
4. Wait for full pipeline completion
5. Generate validation report per context_388

This region mismatch issue has blocked production tests multiple times. The permanent solution is to ensure S3_BUCKET_REGION is always explicitly set in the environment configuration.