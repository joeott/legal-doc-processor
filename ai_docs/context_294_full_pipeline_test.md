# Full Pipeline Test After S3 Permissions Fix

## Date: 2025-06-02
## Purpose: Test complete document processing pipeline after S3-Textract permissions update
## Status: READY FOR EXECUTION

## Overview

This document provides a comprehensive test mechanism to validate the entire document processing pipeline after applying the S3 bucket policy changes. The test will verify that documents can now proceed through all stages: OCR → Chunking → Entity Extraction → Entity Resolution → Relationship Building.

## Pre-Test Verification

### 1. Verify Bucket Policy is Applied

```bash
# Check that the bucket policy exists
aws s3api get-bucket-policy \
    --bucket samu-docs-private-upload \
    --query Policy \
    --output text | python -m json.tool
```

Expected output should show the Textract permissions policy.

### 2. Test Direct Textract Access

Create a quick test script to verify Textract can now access S3:

```bash
cat > /opt/legal-doc-processor/scripts/test_textract_access.py << 'EOF'
#!/usr/bin/env python3
"""
Test Textract access to S3 bucket after permissions update
"""
import boto3
import sys
from scripts.config import AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_DEFAULT_REGION

# Initialize clients
s3_client = boto3.client('s3',
    region_name=AWS_DEFAULT_REGION,
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY
)

textract_client = boto3.client('textract',
    region_name=AWS_DEFAULT_REGION,
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY
)

# Test with an existing document
test_key = "documents/519fd8c1-40fc-4671-b20b-12a3bb919634.pdf"  # From previous test

try:
    # First verify object exists
    response = s3_client.head_object(
        Bucket='samu-docs-private-upload',
        Key=test_key
    )
    print(f"✅ S3 object exists: {test_key}")
    print(f"   Size: {response['ContentLength']} bytes")
    
    # Now test Textract access
    response = textract_client.start_document_text_detection(
        DocumentLocation={
            'S3Object': {
                'Bucket': 'samu-docs-private-upload',
                'Name': test_key
            }
        }
    )
    print(f"✅ Textract job started successfully!")
    print(f"   Job ID: {response['JobId']}")
    print("\nS3-Textract permissions are correctly configured!")
    
except Exception as e:
    print(f"❌ Error: {e}")
    sys.exit(1)
EOF

chmod +x /opt/legal-doc-processor/scripts/test_textract_access.py
```

Run the test:
```bash
cd /opt/legal-doc-processor && source load_env.sh && python3 scripts/test_textract_access.py
```

## Full Pipeline Test Script

Create the comprehensive test script:

```bash
cat > /opt/legal-doc-processor/scripts/full_pipeline_test.py << 'EOF'
#!/usr/bin/env python3
"""
Full Pipeline Test - Validate complete document processing after S3 fix
"""
import os
import sys
import time
import json
from datetime import datetime, timedelta
from pathlib import Path

# Set environment variables
os.environ['USE_MINIMAL_MODELS'] = 'true'
os.environ['SKIP_CONFORMANCE_CHECK'] = 'true'

from scripts.db import DatabaseManager
from scripts.s3_storage import S3StorageManager
from scripts.pdf_tasks import extract_text_from_document
from scripts.cache import get_redis_manager
from scripts.core.model_factory import get_source_document_model
from sqlalchemy import text

class PipelineTestRunner:
    def __init__(self):
        self.db_manager = DatabaseManager()
        self.s3_manager = S3StorageManager()
        self.redis_manager = get_redis_manager()
        self.test_results = {
            'start_time': datetime.utcnow().isoformat(),
            'tests': []
        }
    
    def run_full_test(self):
        """Run complete pipeline test"""
        print("="*80)
        print("FULL PIPELINE TEST - POST S3 PERMISSIONS FIX")
        print("="*80)
        print(f"Start time: {datetime.now()}")
        
        # Test 1: Upload new document
        print("\n1️⃣ TEST 1: Upload New Document")
        doc_uuid = self.test_document_upload()
        
        if doc_uuid:
            # Test 2: Submit for OCR
            print("\n2️⃣ TEST 2: Submit for OCR Processing")
            task_id = self.test_ocr_submission(doc_uuid)
            
            if task_id:
                # Test 3: Monitor pipeline progression
                print("\n3️⃣ TEST 3: Monitor Pipeline Progression")
                success = self.monitor_pipeline(doc_uuid, timeout=300)
                
                if success:
                    # Test 4: Verify data quality
                    print("\n4️⃣ TEST 4: Verify Data Quality")
                    self.verify_data_quality(doc_uuid)
        
        # Generate report
        self.generate_report()
    
    def test_document_upload(self):
        """Test document upload with a sample PDF"""
        test_file = "/opt/legal-doc-processor/input_docs/Paul, Michael (Acuity)/Paul, Michael - Wombat Corp Disclosure Stmt 10-23-24.pdf"
        
        if not os.path.exists(test_file):
            print(f"❌ Test file not found: {test_file}")
            return None
        
        try:
            # Generate document UUID
            import uuid
            doc_uuid = str(uuid.uuid4())
            file_name = os.path.basename(test_file)
            
            # Upload to S3
            print(f"📤 Uploading {file_name} to S3...")
            upload_result = self.s3_manager.upload_document_with_uuid_naming(
                test_file, 
                doc_uuid,
                file_name
            )
            
            s3_key = upload_result['s3_key']
            print(f"✅ Uploaded to S3: {s3_key}")
            
            # Create database record
            DocumentModel = get_source_document_model()
            doc_model = DocumentModel(
                document_uuid=doc_uuid,
                project_uuid="e0c57112-c755-4798-bc1f-4ecc3f0eec78",  # Test project
                file_name=file_name,
                original_file_name=file_name,
                file_path=test_file,
                file_size=os.path.getsize(test_file),
                mime_type='application/pdf',
                s3_key=s3_key,
                s3_bucket=self.s3_manager.private_bucket_name,
                upload_timestamp=datetime.utcnow(),
                processing_status='pending'
            )
            
            doc = self.db_manager.create_source_document(doc_model)
            print(f"✅ Created document record: {doc.document_uuid}")
            
            # Store metadata in Redis
            metadata_key = f"doc:metadata:{doc.document_uuid}"
            self.redis_manager.store_dict(metadata_key, {
                'project_uuid': "e0c57112-c755-4798-bc1f-4ecc3f0eec78",
                'document_metadata': {
                    'title': file_name,
                    'test_run': True,
                    'created_at': datetime.utcnow().isoformat()
                }
            })
            
            self.test_results['tests'].append({
                'test': 'document_upload',
                'status': 'success',
                'document_uuid': doc_uuid,
                's3_key': s3_key
            })
            
            return doc_uuid
            
        except Exception as e:
            print(f"❌ Upload failed: {e}")
            self.test_results['tests'].append({
                'test': 'document_upload',
                'status': 'failed',
                'error': str(e)
            })
            return None
    
    def test_ocr_submission(self, doc_uuid):
        """Test OCR task submission with S3 URI"""
        try:
            # Get document info
            for session in self.db_manager.get_session():
                result = session.execute(
                    text("SELECT s3_key, s3_bucket FROM source_documents WHERE document_uuid = :uuid"),
                    {"uuid": doc_uuid}
                )
                row = result.first()
                if row:
                    s3_key, s3_bucket = row
                break
            
            # Submit OCR task with S3 URI
            s3_uri = f"s3://{s3_bucket}/{s3_key}"
            print(f"🚀 Submitting OCR for: {s3_uri}")
            
            task = extract_text_from_document.apply_async(
                args=[doc_uuid, s3_uri]
            )
            
            print(f"✅ OCR task submitted: {task.id}")
            
            self.test_results['tests'].append({
                'test': 'ocr_submission',
                'status': 'success',
                'task_id': task.id,
                's3_uri': s3_uri
            })
            
            return task.id
            
        except Exception as e:
            print(f"❌ OCR submission failed: {e}")
            self.test_results['tests'].append({
                'test': 'ocr_submission',
                'status': 'failed',
                'error': str(e)
            })
            return None
    
    def monitor_pipeline(self, doc_uuid, timeout=300):
        """Monitor pipeline progression"""
        start_time = time.time()
        stages = ["ocr", "chunking", "entity_extraction", "entity_resolution", "relationships"]
        completed_stages = set()
        
        print(f"⏳ Monitoring pipeline for up to {timeout} seconds...")
        print("-" * 60)
        
        while time.time() - start_time < timeout:
            # Get pipeline state
            current_state = {}
            for stage in stages:
                state_key = f"doc:state:{doc_uuid}:{stage}"
                stage_data = self.redis_manager.get_dict(state_key) or {}
                current_state[stage] = stage_data.get('status', 'none')
            
            # Display current state
            status_line = f"[{int(time.time() - start_time):3d}s] "
            for stage in stages:
                status = current_state[stage]
                symbol = {'none': '⬜', 'pending': '🟨', 'in_progress': '🔄', 
                         'completed': '✅', 'failed': '❌'}.get(status, '❓')
                status_line += f"{stage}: {symbol}  "
            
            print(f"\r{status_line}", end='', flush=True)
            
            # Track completed stages
            for stage in stages:
                if current_state[stage] == 'completed':
                    completed_stages.add(stage)
            
            # Check if all complete
            if len(completed_stages) == len(stages):
                print(f"\n✅ Pipeline completed successfully in {int(time.time() - start_time)} seconds!")
                self.test_results['tests'].append({
                    'test': 'pipeline_progression',
                    'status': 'success',
                    'duration': int(time.time() - start_time),
                    'completed_stages': list(completed_stages)
                })
                return True
            
            # Check for failures
            failed_stages = [s for s in stages if current_state[s] == 'failed']
            if failed_stages:
                print(f"\n❌ Pipeline failed at stage(s): {', '.join(failed_stages)}")
                self.test_results['tests'].append({
                    'test': 'pipeline_progression',
                    'status': 'failed',
                    'failed_stages': failed_stages,
                    'completed_stages': list(completed_stages)
                })
                return False
            
            time.sleep(5)
        
        print(f"\n⏱️ Timeout reached. Completed stages: {completed_stages}")
        self.test_results['tests'].append({
            'test': 'pipeline_progression',
            'status': 'timeout',
            'completed_stages': list(completed_stages),
            'duration': timeout
        })
        return False
    
    def verify_data_quality(self, doc_uuid):
        """Verify the quality of processed data"""
        try:
            metrics = {}
            
            # Check chunks
            for session in self.db_manager.get_session():
                result = session.execute(
                    text("SELECT COUNT(*), AVG(word_count) FROM document_chunks WHERE document_uuid = :uuid"),
                    {"uuid": doc_uuid}
                )
                chunk_count, avg_words = result.first()
                metrics['chunks'] = {'count': chunk_count, 'avg_words': float(avg_words or 0)}
                
                # Check entities
                result = session.execute(
                    text("""
                        SELECT COUNT(DISTINCT em.entity_mention_uuid), 
                               COUNT(DISTINCT em.canonical_entity_uuid)
                        FROM entity_mentions em
                        WHERE em.document_uuid = :uuid
                    """),
                    {"uuid": doc_uuid}
                )
                mention_count, canonical_count = result.first()
                metrics['entities'] = {'mentions': mention_count, 'canonical': canonical_count}
                
                # Check relationships
                result = session.execute(
                    text("SELECT COUNT(*) FROM relationship_staging WHERE source_entity_uuid IN (SELECT canonical_entity_uuid FROM entity_mentions WHERE document_uuid = :uuid)"),
                    {"uuid": doc_uuid}
                )
                rel_count = result.scalar()
                metrics['relationships'] = rel_count
                
                break
            
            # Evaluate quality
            quality_passed = (
                metrics['chunks']['count'] > 0 and
                metrics['entities']['mentions'] > 5 and
                metrics['entities']['canonical'] > 0
            )
            
            print(f"\n📊 Data Quality Metrics:")
            print(f"   Chunks: {metrics['chunks']['count']} (avg {metrics['chunks']['avg_words']:.1f} words)")
            print(f"   Entity Mentions: {metrics['entities']['mentions']}")
            print(f"   Canonical Entities: {metrics['entities']['canonical']}")
            print(f"   Relationships: {metrics['relationships']}")
            print(f"   Quality: {'✅ PASSED' if quality_passed else '❌ FAILED'}")
            
            self.test_results['tests'].append({
                'test': 'data_quality',
                'status': 'success' if quality_passed else 'failed',
                'metrics': metrics
            })
            
        except Exception as e:
            print(f"❌ Quality verification failed: {e}")
            self.test_results['tests'].append({
                'test': 'data_quality',
                'status': 'error',
                'error': str(e)
            })
    
    def generate_report(self):
        """Generate final test report"""
        self.test_results['end_time'] = datetime.utcnow().isoformat()
        
        # Save results
        report_file = '/opt/legal-doc-processor/full_pipeline_test_results.json'
        with open(report_file, 'w') as f:
            json.dump(self.test_results, f, indent=2)
        
        print(f"\n{'='*80}")
        print("TEST SUMMARY")
        print("="*80)
        
        total_tests = len(self.test_results['tests'])
        passed_tests = sum(1 for t in self.test_results['tests'] if t['status'] == 'success')
        
        print(f"Total Tests: {total_tests}")
        print(f"Passed: {passed_tests}")
        print(f"Failed: {total_tests - passed_tests}")
        print(f"\nDetailed results saved to: {report_file}")
        
        # Overall success
        if passed_tests == total_tests:
            print("\n🎉 ALL TESTS PASSED! Pipeline is fully operational!")
        else:
            print("\n⚠️ Some tests failed. Review the results above.")

if __name__ == "__main__":
    runner = PipelineTestRunner()
    runner.run_full_test()
EOF

chmod +x /opt/legal-doc-processor/scripts/full_pipeline_test.py
```

## Execution Instructions

### Step 1: Verify S3 Permissions
```bash
cd /opt/legal-doc-processor
source load_env.sh
python3 scripts/test_textract_access.py
```

### Step 2: Run Full Pipeline Test
```bash
cd /opt/legal-doc-processor
source load_env.sh
PYTHONPATH=/opt/legal-doc-processor:$PYTHONPATH python3 scripts/full_pipeline_test.py
```

### Step 3: Monitor Live Progress
In a separate terminal:
```bash
cd /opt/legal-doc-processor
source load_env.sh
python3 scripts/cli/monitor.py live
```

## Expected Results

If the S3 permissions fix was successful:

1. **Textract Access Test**: Should show "✅ Textract job started successfully!"
2. **Document Upload**: Should complete with S3 key and database record
3. **OCR Submission**: Should submit without "InvalidS3ObjectException"
4. **Pipeline Progression**: Should show all stages completing (✅) within 5 minutes
5. **Data Quality**: Should show chunks, entities, and relationships extracted

## Troubleshooting

If tests fail:

### OCR Still Failing
```bash
# Check Textract job details
aws textract get-document-text-detection --job-id YOUR-JOB-ID

# Verify bucket policy is active
aws s3api get-bucket-policy --bucket samu-docs-private-upload
```

### Pipeline Stuck
```bash
# Check Redis state
python3 scripts/check_redis_state.py

# Check worker logs
tail -f celery_worker.log | grep ERROR
```

### Data Quality Issues
```bash
# Manually check database
psql $DATABASE_URL -c "SELECT * FROM document_chunks WHERE document_uuid = 'YOUR-UUID' LIMIT 5;"
```

## Success Criteria

The pipeline is considered fully operational when:
1. ✅ Textract can access S3 objects without permission errors
2. ✅ Documents progress automatically through all stages
3. ✅ OCR completes and triggers chunking
4. ✅ Chunking triggers entity extraction
5. ✅ Entity extraction triggers resolution
6. ✅ Resolution triggers relationship building
7. ✅ Final data quality metrics meet thresholds

## Next Steps After Success

1. Process remaining test documents
2. Run concurrent document tests
3. Measure processing times for optimization
4. Deploy monitoring alerts
5. Begin production rollout

This test provides definitive validation that the S3 permissions fix has resolved the blocking issue and the pipeline is ready for production use.