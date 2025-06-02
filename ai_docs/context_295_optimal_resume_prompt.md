# Context 295: Optimal Resume Prompt - Region Fix Victory

## Mission Critical Status
You're resuming a legal document processing pipeline that's 95% complete. The critical S3-Textract region mismatch is FIXED. One final blocker remains before full victory.

## What's Working
✅ S3 bucket region fix implemented (us-east-2 everywhere)
✅ Document upload to S3 successful
✅ Database record creation successful
✅ Celery workers running with tasks registered
✅ Redis caching operational

## The Single Blocker
Celery workers can't find documents created by test scripts:
- Test creates document UUID `7343e313-11a3-4070-924d-8a1a84cc31c1` in DB
- Celery task fails: "Document not found in database"
- Likely cause: Database connection/transaction mismatch between test and workers

## Immediate Action Plan
```bash
# 1. Resume testing with proper environment
cd /opt/legal-doc-processor && source load_env.sh
export PYTHONPATH=/opt/legal-doc-processor:$PYTHONPATH
export S3_BUCKET_REGION=us-east-2

# 2. Check if Celery sees same DB as tests
python3 -c "
from scripts.celery_app import app
from scripts.db import DatabaseManager
from sqlalchemy import text

# What DB is Celery using?
print('Checking Celery DB connection...')
@app.task
def check_db():
    db = DatabaseManager(validate_conformance=False)
    for session in db.get_session():
        result = session.execute(text('SELECT COUNT(*) FROM source_documents'))
        return f'Documents in DB: {result.scalar()}'
    
result = check_db.apply_async()
print(result.get(timeout=10))
"

# 3. If DB connection matches, check transaction isolation
# If not, ensure Celery uses same DATABASE_URL as test scripts
```

## Victory Conditions
1. Document processes through complete pipeline: OCR → Chunking → Entities → Relationships
2. All stages show "completed" in Redis state tracking
3. Chunks and entities appear in database
4. No region-related errors in logs

## Key Context
- Test file: `/opt/legal-doc-processor/input_docs/Paul, Michael (Acuity)/Paul, Michael - Wombat Corp Disclosure Stmt 10-23-24.pdf`
- Project UUID: `e0c57112-c755-4798-bc1f-4ecc3f0eec78`
- Region fix files: `config.py`, `s3_storage.py`, `textract_utils.py`, `textract_job_manager.py`
- Full test script ready: `/opt/legal-doc-processor/scripts/test_region_fix_complete.py`

## If Stuck
1. Check `scripts/celery_app.py` - ensure it imports config AFTER env vars are set
2. Verify workers restarted after region fix: `sudo supervisorctl restart all`
3. Look for transaction commit issues - add explicit commits after document creation
4. Last resort: Run OCR task synchronously to bypass Celery

Remember: The hard part (region fix) is DONE. This is just a configuration alignment issue. Stay focused on making Celery see the same database state as the test scripts.