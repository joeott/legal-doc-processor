# Context 353: Supplemental Implementation Plan - From Recovery to Full Pipeline

## Executive Summary

We've successfully restarted document processing after identifying and fixing the core issues. This supplemental plan outlines the systematic steps to achieve full pipeline functionality (6/6 stages) and ensure sustainable operations.

## Current State Assessment

### Working (✓)
1. Document creation in database
2. S3 file uploads  
3. Celery task submission
4. Worker processes running

### Unknown/Pending (?)
1. OCR/Textract execution
2. Text chunking
3. Entity extraction
4. Entity resolution
5. Relationship building

### Known Issues (✗)
1. Monitoring queries using wrong column names
2. Potential Textract permissions issue (from context_292)
3. Incomplete API compatibility coverage

## Phase 1: Fix Monitoring and Visibility (30 minutes)

### Step 1.1: Create Schema Reference
```python
# scripts/utils/schema_reference.py
"""
Authoritative schema reference based on actual database
Generated from information_schema queries
"""

SCHEMA_REFERENCE = {
    'source_documents': {
        'primary_key': 'document_uuid',  # NOT 'uuid'
        'foreign_keys': {
            'project_uuid': 'projects.project_id'  # Note: misnamed column
        },
        'status_columns': [
            'status',
            'textract_job_status',  # NOT 'ocr_status'
            'celery_status'
        ]
    },
    'document_chunks': {
        'primary_key': 'id',
        'foreign_key': 'document_uuid',  # NOT 'source_document_uuid'
        'content_column': 'text_content'  # NOT 'content'
    },
    'entity_mentions': {
        'foreign_key': 'document_uuid',  # NOT 'source_document_uuid'
    },
    'canonical_entities': {
        'foreign_key': 'created_from_document_uuid'
    },
    'relationship_staging': {
        'foreign_key': 'document_uuid'  # NOT 'source_document_uuid'
    }
}
```

### Step 1.2: Create Universal Monitoring Tool
```python
# scripts/monitor_document_complete.py
"""
Comprehensive document monitoring with correct schema
"""
import sys
from datetime import datetime
from scripts.db import get_db
from sqlalchemy import text

def monitor_document(doc_uuid):
    """Monitor document with proper column names"""
    session = next(get_db())
    try:
        # Main document status
        doc_query = """
        SELECT 
            sd.document_uuid,
            sd.file_name,
            sd.status,
            sd.textract_job_status,
            sd.textract_job_id,
            sd.created_at,
            sd.s3_key,
            sd.s3_bucket
        FROM source_documents sd
        WHERE sd.document_uuid = :uuid
        """
        
        doc = session.execute(text(doc_query), {"uuid": doc_uuid}).fetchone()
        
        if not doc:
            print(f"Document {doc_uuid} not found!")
            return
            
        print(f"\nDocument: {doc.file_name}")
        print(f"Status: {doc.status}")
        print(f"Textract: {doc.textract_job_status} (Job: {doc.textract_job_id})")
        print(f"S3: s3://{doc.s3_bucket}/{doc.s3_key}")
        
        # Pipeline stages - using correct column names
        stages_query = """
        SELECT 
            (SELECT COUNT(*) FROM document_chunks WHERE document_uuid = :uuid) as chunks,
            (SELECT COUNT(*) FROM entity_mentions WHERE document_uuid = :uuid) as entities,
            (SELECT COUNT(*) FROM canonical_entities WHERE created_from_document_uuid = :uuid) as canonical,
            (SELECT COUNT(*) FROM relationship_staging WHERE document_uuid = :uuid) as relationships
        """
        
        stages = session.execute(text(stages_query), {"uuid": doc_uuid}).fetchone()
        
        print(f"\nPipeline Progress:")
        print(f"  1. Document Created: ✓")
        print(f"  2. OCR: {'✓' if doc.textract_job_status == 'SUCCEEDED' else '○ pending'}")
        print(f"  3. Chunks: {'✓' if stages.chunks > 0 else '○'} ({stages.chunks})")
        print(f"  4. Entities: {'✓' if stages.entities > 0 else '○'} ({stages.entities})")
        print(f"  5. Canonical: {'✓' if stages.canonical > 0 else '○'} ({stages.canonical})")
        print(f"  6. Relationships: {'✓' if stages.relationships > 0 else '○'} ({stages.relationships})")
        
        # Check for errors
        errors_query = """
        SELECT task_type, status, error_message, created_at
        FROM processing_tasks
        WHERE document_uuid = :uuid AND status = 'failed'
        ORDER BY created_at DESC
        LIMIT 5
        """
        
        errors = session.execute(text(errors_query), {"uuid": doc_uuid}).fetchall()
        if errors:
            print(f"\nErrors Found:")
            for err in errors:
                print(f"  - {err.task_type}: {err.error_message}")
                
    finally:
        session.close()

if __name__ == "__main__":
    doc_uuid = sys.argv[1] if len(sys.argv) > 1 else input("Enter document UUID: ")
    monitor_document(doc_uuid)
```

## Phase 2: Verify Pipeline Execution (45 minutes)

### Step 2.1: Create Pipeline Health Check
```python
# scripts/check_pipeline_health.py
"""
Comprehensive pipeline health verification
"""
import time
from scripts.celery_app import app
from scripts.cache import get_redis_manager
from scripts.db import get_db
from sqlalchemy import text

def check_pipeline_health():
    """Full pipeline health check"""
    print("Pipeline Health Check")
    print("=" * 60)
    
    # 1. Check Celery Workers
    print("\n1. Celery Workers:")
    try:
        i = app.control.inspect()
        stats = i.stats()
        if stats:
            for worker, info in stats.items():
                print(f"   ✓ {worker}: {info.get('pool', {}).get('max-concurrency', 'N/A')} workers")
        else:
            print("   ✗ No workers found!")
    except Exception as e:
        print(f"   ✗ Error: {e}")
    
    # 2. Check Redis
    print("\n2. Redis Cache:")
    try:
        redis = get_redis_manager()
        redis.client.ping()
        print("   ✓ Redis connected")
    except Exception as e:
        print(f"   ✗ Redis error: {e}")
    
    # 3. Check Database
    print("\n3. Database:")
    try:
        session = next(get_db())
        result = session.execute(text("SELECT COUNT(*) FROM source_documents")).scalar()
        print(f"   ✓ Database connected ({result} documents)")
        session.close()
    except Exception as e:
        print(f"   ✗ Database error: {e}")
    
    # 4. Check Recent Processing
    print("\n4. Recent Processing (last hour):")
    try:
        session = next(get_db())
        recent = session.execute(text("""
            SELECT 
                COUNT(DISTINCT sd.document_uuid) as docs,
                COUNT(DISTINCT CASE WHEN sd.textract_job_status = 'SUCCEEDED' THEN sd.document_uuid END) as ocr_complete,
                COUNT(DISTINCT dc.document_uuid) as chunked,
                COUNT(DISTINCT em.document_uuid) as with_entities
            FROM source_documents sd
            LEFT JOIN document_chunks dc ON sd.document_uuid = dc.document_uuid
            LEFT JOIN entity_mentions em ON sd.document_uuid = em.document_uuid
            WHERE sd.created_at > NOW() - INTERVAL '1 hour'
        """)).fetchone()
        
        print(f"   Documents: {recent.docs}")
        print(f"   OCR Complete: {recent.ocr_complete}")
        print(f"   Chunked: {recent.chunked}")
        print(f"   With Entities: {recent.with_entities}")
        session.close()
    except Exception as e:
        print(f"   ✗ Error: {e}")

if __name__ == "__main__":
    check_pipeline_health()
```

### Step 2.2: Create Continuous Pipeline Monitor
```python
# scripts/monitor_pipeline_live.py
"""
Live pipeline monitoring showing real-time progress
"""
import time
import os
from datetime import datetime
from scripts.db import get_db
from sqlalchemy import text

def monitor_live(refresh_seconds=5):
    """Monitor pipeline in real-time"""
    while True:
        os.system('clear' if os.name == 'posix' else 'cls')
        
        print(f"Pipeline Monitor - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 80)
        
        session = next(get_db())
        try:
            # Recent documents
            recent_docs = session.execute(text("""
                SELECT 
                    sd.document_uuid,
                    sd.file_name,
                    sd.status,
                    sd.textract_job_status,
                    sd.created_at,
                    COUNT(DISTINCT dc.id) as chunks,
                    COUNT(DISTINCT em.id) as entities
                FROM source_documents sd
                LEFT JOIN document_chunks dc ON sd.document_uuid = dc.document_uuid
                LEFT JOIN entity_mentions em ON sd.document_uuid = em.document_uuid
                WHERE sd.created_at > NOW() - INTERVAL '2 hours'
                GROUP BY sd.document_uuid, sd.file_name, sd.status, sd.textract_job_status, sd.created_at
                ORDER BY sd.created_at DESC
                LIMIT 10
            """)).fetchall()
            
            if recent_docs:
                print("\nRecent Documents:")
                print("-" * 80)
                for doc in recent_docs:
                    age = (datetime.now() - doc.created_at.replace(tzinfo=None)).total_seconds()
                    age_str = f"{int(age/60)}m ago" if age > 60 else f"{int(age)}s ago"
                    
                    print(f"{doc.document_uuid[:8]}... | {doc.file_name[:30]:.<30} | "
                          f"OCR: {doc.textract_job_status or 'pending':.<10} | "
                          f"Chunks: {doc.chunks:<3} | Entities: {doc.entities:<3} | {age_str}")
            else:
                print("\nNo recent documents.")
                
            # Active tasks
            active_tasks = session.execute(text("""
                SELECT task_type, COUNT(*) as count
                FROM processing_tasks
                WHERE status = 'processing'
                GROUP BY task_type
            """)).fetchall()
            
            if active_tasks:
                print("\nActive Tasks:")
                for task in active_tasks:
                    print(f"  - {task.task_type}: {task.count}")
                    
        finally:
            session.close()
            
        print(f"\nRefreshing in {refresh_seconds} seconds... (Ctrl+C to stop)")
        time.sleep(refresh_seconds)

if __name__ == "__main__":
    monitor_live()
```

## Phase 3: Handle Textract Permissions (30 minutes)

### Step 3.1: Check and Fix S3-Textract Access
Based on context_292, we need to ensure Textract can access S3 objects.

```python
# scripts/fix_textract_permissions.py
"""
Fix S3-Textract permissions based on historical context
"""
import boto3
import json
from scripts.config import S3_PRIMARY_DOCUMENT_BUCKET

def check_and_fix_textract_permissions():
    """Ensure Textract can access S3 bucket"""
    s3 = boto3.client('s3')
    
    # Get current bucket policy
    try:
        policy_result = s3.get_bucket_policy(Bucket=S3_PRIMARY_DOCUMENT_BUCKET)
        current_policy = json.loads(policy_result['Policy'])
        print("Current bucket policy found")
    except s3.exceptions.NoSuchBucketPolicy:
        current_policy = {"Version": "2012-10-17", "Statement": []}
        print("No bucket policy found, creating new one")
    
    # Check if Textract access exists
    textract_statement = {
        "Sid": "AllowTextractAccess",
        "Effect": "Allow",
        "Principal": {
            "Service": "textract.amazonaws.com"
        },
        "Action": "s3:GetObject",
        "Resource": f"arn:aws:s3:::{S3_PRIMARY_DOCUMENT_BUCKET}/*"
    }
    
    # Add if not present
    has_textract = any(
        stmt.get('Principal', {}).get('Service') == 'textract.amazonaws.com'
        for stmt in current_policy.get('Statement', [])
    )
    
    if not has_textract:
        print("Adding Textract permissions...")
        current_policy['Statement'].append(textract_statement)
        
        s3.put_bucket_policy(
            Bucket=S3_PRIMARY_DOCUMENT_BUCKET,
            Policy=json.dumps(current_policy)
        )
        print("✓ Textract permissions added")
    else:
        print("✓ Textract permissions already configured")

if __name__ == "__main__":
    check_and_fix_textract_permissions()
```

## Phase 4: Create Integration Test Suite (45 minutes)

### Step 4.1: Comprehensive E2E Test
```python
# scripts/test_e2e_complete.py
"""
Complete end-to-end test with proper error handling and monitoring
"""
import os
import sys
import time
import uuid
from pathlib import Path
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.celery_app import app
from scripts.pdf_tasks import process_pdf_document
from scripts.db import get_db, DatabaseManager
from scripts.s3_storage import S3StorageManager
from scripts.monitor_document_complete import monitor_document
from sqlalchemy import text

class CompleteE2ETest:
    def __init__(self):
        self.test_file = "input_docs/Paul, Michael (Acuity)/Paul, Michael - Wombat Corp Disclosure Stmt 10-23-24.pdf"
        self.timeout = 600  # 10 minutes
        
    def run_test(self):
        """Run complete E2E test"""
        print("\n" + "="*60)
        print("COMPLETE END-TO-END PIPELINE TEST")
        print("="*60)
        
        # 1. Verify prerequisites
        if not self.verify_prerequisites():
            return False
            
        # 2. Create and upload document
        doc_uuid = str(uuid.uuid4())
        print(f"\nDocument UUID: {doc_uuid}")
        
        if not self.create_and_upload_document(doc_uuid):
            return False
            
        # 3. Submit to pipeline
        task_id = self.submit_to_pipeline(doc_uuid)
        if not task_id:
            return False
            
        # 4. Monitor until completion or timeout
        success = self.monitor_until_complete(doc_uuid, task_id)
        
        # 5. Final report
        print("\n" + "="*60)
        print("FINAL RESULTS")
        print("="*60)
        monitor_document(doc_uuid)
        
        return success
    
    def verify_prerequisites(self):
        """Check all systems are ready"""
        print("\nVerifying prerequisites...")
        
        # Check file exists
        if not os.path.exists(self.test_file):
            print(f"✗ Test file not found: {self.test_file}")
            return False
        print("✓ Test file exists")
        
        # Check Celery
        try:
            i = app.control.inspect()
            if not i.stats():
                print("✗ No Celery workers running")
                return False
            print("✓ Celery workers active")
        except:
            print("✗ Cannot connect to Celery")
            return False
            
        # Check database
        try:
            session = next(get_db())
            session.execute(text("SELECT 1"))
            session.close()
            print("✓ Database connected")
        except:
            print("✗ Database connection failed")
            return False
            
        return True
    
    def create_and_upload_document(self, doc_uuid):
        """Create document and upload to S3"""
        print("\nCreating document...")
        
        try:
            # Get project
            session = next(get_db())
            project = session.execute(text(
                "SELECT project_id FROM projects LIMIT 1"
            )).fetchone()
            session.close()
            
            if not project:
                print("✗ No projects found")
                return False
                
            project_uuid = str(project.project_id)
            
            # Create document
            db = DatabaseManager()
            session = next(get_db())
            session.execute(text("""
                INSERT INTO source_documents (
                    document_uuid, project_uuid, file_name, file_path,
                    file_type, status, created_at
                ) VALUES (
                    :doc_uuid, :project_uuid, :file_name, :file_path,
                    'pdf', 'pending', NOW()
                )
            """), {
                "doc_uuid": doc_uuid,
                "project_uuid": project_uuid,
                "file_name": Path(self.test_file).name,
                "file_path": self.test_file
            })
            session.commit()
            session.close()
            print("✓ Document created")
            
            # Upload to S3
            s3 = S3StorageManager()
            result = s3.upload_document_with_uuid_naming(
                self.test_file, doc_uuid, project_uuid
            )
            
            if not result:
                print("✗ S3 upload failed")
                return False
                
            # Update S3 info
            session = next(get_db())
            s3_key = result['s3_key'] if isinstance(result, dict) else result
            session.execute(text("""
                UPDATE source_documents
                SET s3_key = :key, s3_bucket = :bucket, s3_region = :region
                WHERE document_uuid = :uuid
            """), {
                "key": s3_key,
                "bucket": result.get('s3_bucket', 'samu-docs-private-upload'),
                "region": result.get('s3_region', 'us-east-1'),
                "uuid": doc_uuid
            })
            session.commit()
            session.close()
            print("✓ Uploaded to S3")
            
            return True
            
        except Exception as e:
            print(f"✗ Error: {e}")
            return False
    
    def submit_to_pipeline(self, doc_uuid):
        """Submit document to processing pipeline"""
        print("\nSubmitting to pipeline...")
        
        try:
            # Get S3 info
            session = next(get_db())
            doc = session.execute(text(
                "SELECT s3_bucket, s3_key, project_uuid FROM source_documents WHERE document_uuid = :uuid"
            ), {"uuid": doc_uuid}).fetchone()
            session.close()
            
            if not doc:
                print("✗ Document not found")
                return None
                
            s3_uri = f"s3://{doc.s3_bucket}/{doc.s3_key}"
            
            # Submit task
            task = process_pdf_document.delay(
                doc_uuid, s3_uri, str(doc.project_uuid)
            )
            
            print(f"✓ Task submitted: {task.id}")
            return task.id
            
        except Exception as e:
            print(f"✗ Error: {e}")
            return None
    
    def monitor_until_complete(self, doc_uuid, task_id):
        """Monitor document processing until complete or timeout"""
        print(f"\nMonitoring progress (timeout: {self.timeout}s)...")
        
        start_time = time.time()
        last_stage = 0
        
        while time.time() - start_time < self.timeout:
            # Check stage progress
            session = next(get_db())
            result = session.execute(text("""
                SELECT 
                    sd.textract_job_status,
                    (SELECT COUNT(*) FROM document_chunks WHERE document_uuid = :uuid) as chunks,
                    (SELECT COUNT(*) FROM entity_mentions WHERE document_uuid = :uuid) as entities,
                    (SELECT COUNT(*) FROM canonical_entities WHERE created_from_document_uuid = :uuid) as canonical,
                    (SELECT COUNT(*) FROM relationship_staging WHERE document_uuid = :uuid) as relationships
                FROM source_documents sd
                WHERE sd.document_uuid = :uuid
            """), {"uuid": doc_uuid}).fetchone()
            session.close()
            
            if not result:
                print("✗ Document not found!")
                return False
                
            # Count completed stages
            stages_complete = sum([
                1,  # Document created
                1 if result.textract_job_status == 'SUCCEEDED' else 0,
                1 if result.chunks > 0 else 0,
                1 if result.entities > 0 else 0,
                1 if result.canonical > 0 else 0,
                1 if result.relationships > 0 else 0
            ])
            
            # Report progress
            if stages_complete > last_stage:
                elapsed = int(time.time() - start_time)
                print(f"[{elapsed}s] Stage {stages_complete}/6 complete")
                last_stage = stages_complete
                
                if stages_complete == 6:
                    print("\n✓ ALL STAGES COMPLETE!")
                    return True
                    
            time.sleep(10)  # Check every 10 seconds
            
        print(f"\n✗ Timeout after {self.timeout} seconds")
        return False

if __name__ == "__main__":
    test = CompleteE2ETest()
    success = test.run_test()
    sys.exit(0 if success else 1)
```

## Phase 5: Production Readiness (30 minutes)

### Step 5.1: Create Health Dashboard
```python
# scripts/dashboard.py
"""
Simple terminal dashboard for pipeline health
"""
import time
import os
from datetime import datetime, timedelta
from scripts.db import get_db
from sqlalchemy import text

def show_dashboard():
    """Display pipeline dashboard"""
    while True:
        os.system('clear' if os.name == 'posix' else 'cls')
        
        print("Legal Document Processing Pipeline Dashboard")
        print("=" * 80)
        print(f"Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print()
        
        session = next(get_db())
        try:
            # Overall stats
            stats = session.execute(text("""
                SELECT 
                    COUNT(*) as total_docs,
                    COUNT(CASE WHEN created_at > NOW() - INTERVAL '24 hours' THEN 1 END) as docs_24h,
                    COUNT(CASE WHEN created_at > NOW() - INTERVAL '1 hour' THEN 1 END) as docs_1h,
                    COUNT(CASE WHEN textract_job_status = 'SUCCEEDED' THEN 1 END) as ocr_complete,
                    COUNT(CASE WHEN textract_job_status = 'FAILED' THEN 1 END) as ocr_failed
                FROM source_documents
            """)).fetchone()
            
            print("📊 Document Statistics")
            print(f"   Total Documents: {stats.total_docs}")
            print(f"   Last 24 Hours: {stats.docs_24h}")
            print(f"   Last Hour: {stats.docs_1h}")
            print(f"   OCR Complete: {stats.ocr_complete}")
            print(f"   OCR Failed: {stats.ocr_failed}")
            print()
            
            # Pipeline stages
            stages = session.execute(text("""
                SELECT 
                    COUNT(DISTINCT dc.document_uuid) as chunked,
                    COUNT(DISTINCT em.document_uuid) as with_entities,
                    COUNT(DISTINCT ce.created_from_document_uuid) as resolved,
                    COUNT(DISTINCT rs.document_uuid) as with_relationships
                FROM document_chunks dc
                FULL OUTER JOIN entity_mentions em ON dc.document_uuid = em.document_uuid
                FULL OUTER JOIN canonical_entities ce ON dc.document_uuid = ce.created_from_document_uuid
                FULL OUTER JOIN relationship_staging rs ON dc.document_uuid = rs.document_uuid
            """)).fetchone()
            
            print("🔄 Pipeline Stages")
            print(f"   Documents Chunked: {stages.chunked}")
            print(f"   With Entities: {stages.with_entities}")
            print(f"   Entities Resolved: {stages.resolved}")
            print(f"   With Relationships: {stages.with_relationships}")
            print()
            
            # Recent errors
            errors = session.execute(text("""
                SELECT task_type, COUNT(*) as count
                FROM processing_tasks
                WHERE status = 'failed' AND created_at > NOW() - INTERVAL '1 hour'
                GROUP BY task_type
                ORDER BY count DESC
                LIMIT 5
            """)).fetchall()
            
            if errors:
                print("⚠️  Recent Errors (Last Hour)")
                for err in errors:
                    print(f"   {err.task_type}: {err.count}")
            else:
                print("✅ No Recent Errors")
                
        finally:
            session.close()
            
        print("\nRefreshing in 30 seconds... (Ctrl+C to exit)")
        time.sleep(30)

if __name__ == "__main__":
    show_dashboard()
```

## Implementation Order

1. **Immediate (Now)**
   - Fix monitoring queries with correct column names
   - Check current document processing status
   - Verify Textract permissions

2. **Next 30 minutes**
   - Run complete E2E test
   - Monitor for OCR completion
   - Fix any errors that appear

3. **Following Hour**
   - Verify all 6 stages working
   - Run multiple documents
   - Set up continuous monitoring

4. **Production Ready**
   - Deploy dashboard
   - Document recovery process
   - Create runbook for common issues

## Success Criteria

- [ ] At least one document completes all 6 stages
- [ ] Monitoring tools work without column errors  
- [ ] Can process multiple documents concurrently
- [ ] Error recovery documented and tested
- [ ] Dashboard shows real-time pipeline health

## Risk Mitigation

1. **If Textract fails**: Use pre-signed URLs or implement OCR fallback
2. **If entities don't extract**: Check OpenAI API key and quotas
3. **If relationships fail**: Verify Neo4j connectivity (if used)
4. **If performance degrades**: Add worker scaling documentation

This plan builds on our recovery success and provides concrete tools to achieve full pipeline functionality.