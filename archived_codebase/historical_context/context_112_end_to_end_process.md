# Context 112: End-to-End Celery System Verification Plan

## Executive Summary

This document outlines a systematic approach to verify the complete functionality of the newly migrated Celery-based document processing pipeline. The plan includes testing documents from `/Users/josephott/Documents/phase_1_2_3_process_v5/input/`, monitoring each processing stage, logging errors, and implementing fixes while maintaining system integrity.

## System Architecture Review

Before testing, let's review the complete flow:

```
Document Input → Source Documents Table → Celery Submission → Redis Queue
                                              ↓
                                          OCR Task (Textract/Others)
                                              ↓
                                          Text Processing/Chunking
                                              ↓
                                          Entity Extraction (OpenAI)
                                              ↓
                                          Entity Resolution
                                              ↓
                                          Graph Relationship Building
                                              ↓
                                          Status: 'completed'
```

## Phase 1: Pre-Test Setup and Verification

### 1.1 System Health Check
```bash
# Verify Redis is running
redis-cli ping

# Check Celery workers status
celery -A scripts.celery_app status

# Verify database connectivity
python scripts/verify_celery_migration.py

# Check AWS credentials for Textract
aws sts get-caller-identity

# Verify OpenAI API key
python -c "import os; print('OpenAI configured' if os.getenv('OPENAI_API_KEY') else 'Missing OpenAI key')"
```

### 1.2 Create Test Infrastructure
```python
# Create test_celery_e2e.py
import os
import sys
import time
import json
from datetime import datetime
from pathlib import Path

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.celery_submission import submit_document_to_celery
from scripts.supabase_utils import SupabaseManager
from scripts.redis_utils import get_redis_manager, CacheKeys

class CeleryE2ETester:
    def __init__(self):
        self.db = SupabaseManager()
        self.redis_mgr = get_redis_manager()
        self.test_results = []
        self.input_dir = Path("/Users/josephott/Documents/phase_1_2_3_process_v5/input_docs")
        
    def test_document(self, file_path: Path) -> dict:
        """Test a single document through the pipeline"""
        # Implementation details in section 2
```

## Phase 2: Document Processing Tests

### 2.1 Test Document Categories
Test different document types to ensure comprehensive coverage:

1. **PDF Documents** - Primary use case, uses Textract
2. **DOCX Documents** - Uses python-docx parser
3. **Text Files** - Simple text extraction
4. **Email Files (.eml)** - Email parser
5. **Audio Files** - Transcription (if any)

### 2.2 Test Implementation
```python
def run_e2e_tests():
    """Run end-to-end tests on all documents"""
    tester = CeleryE2ETester()
    
    # Get all test documents
    test_files = []
    for ext in ['*.pdf', '*.docx', '*.txt', '*.eml']:
        test_files.extend(tester.input_dir.glob(ext))
    
    print(f"Found {len(test_files)} test documents")
    
    # Test each document
    for file_path in test_files:
        print(f"\n{'='*60}")
        print(f"Testing: {file_path.name}")
        print(f"{'='*60}")
        
        result = tester.test_document(file_path)
        tester.test_results.append(result)
        
        # Brief pause between submissions
        time.sleep(2)
    
    # Generate report
    tester.generate_report()
```

### 2.3 Stage-by-Stage Verification
For each document, verify:

1. **Submission Stage**
   - Document registered in source_documents
   - celery_task_id populated
   - celery_status = 'processing'

2. **OCR Stage**
   - celery_status transitions to 'ocr_processing'
   - For PDFs: textract_jobs entry created
   - Raw text extracted and stored
   - celery_status = 'ocr_complete'

3. **Text Processing Stage**
   - neo4j_documents entry created
   - Chunks created in neo4j_chunks
   - celery_status = 'text_processing'

4. **Entity Extraction Stage**
   - Entity mentions created
   - celery_status = 'entity_extraction'

5. **Entity Resolution Stage**
   - Canonical entities created
   - celery_status = 'entity_resolution'

6. **Graph Building Stage**
   - Relationships staged
   - celery_status = 'graph_building' → 'completed'

## Phase 3: Monitoring and Logging

### 3.1 Real-time Monitoring Setup
```bash
# Terminal 1: Pipeline Monitor
python scripts/standalone_pipeline_monitor.py

# Terminal 2: Celery Worker Logs
celery -A scripts.celery_app worker --loglevel=info

# Terminal 3: Redis Monitor
redis-cli monitor | grep -E "DOC_STATE|TEXTRACT"

# Terminal 4: Test Runner
python scripts/test_celery_e2e.py
```

### 3.2 Error Logging Strategy
```python
class ErrorLogger:
    def __init__(self, log_file="celery_e2e_errors.log"):
        self.log_file = log_file
        self.errors = []
        
    def log_error(self, doc_id, stage, error_type, details):
        error_entry = {
            "timestamp": datetime.now().isoformat(),
            "document_id": doc_id,
            "stage": stage,
            "error_type": error_type,
            "details": details,
            "stack_trace": traceback.format_exc() if sys.exc_info()[0] else None
        }
        self.errors.append(error_entry)
        
        # Write to file immediately
        with open(self.log_file, 'a') as f:
            f.write(json.dumps(error_entry) + '\n')
```

## Phase 4: Common Error Patterns and Fixes

### 4.1 Anticipated Issues

1. **Import/Module Errors**
   - Issue: "No module named 'scripts'" in Celery tasks
   - Fix: Ensure PYTHONPATH includes project root
   - Verification: Check celery worker startup logs

2. **AWS Textract Errors**
   - Issue: S3 access denied or bucket not found
   - Fix: Verify S3 bucket permissions and file paths
   - Verification: Test S3 upload separately

3. **OpenAI API Errors**
   - Issue: Rate limits or invalid responses
   - Fix: Implement exponential backoff
   - Verification: Check retry logic in tasks

4. **Database Connection Errors**
   - Issue: Connection pool exhausted
   - Fix: Implement connection pooling in tasks
   - Verification: Monitor connection count

5. **Task Chaining Failures**
   - Issue: Next task not triggered
   - Fix: Verify .delay() calls and imports
   - Verification: Check task dependencies

### 4.2 Systematic Debugging Approach

```python
def debug_stuck_document(doc_uuid: str):
    """Debug a document that's stuck in processing"""
    db = SupabaseManager()
    redis_mgr = get_redis_manager()
    
    # 1. Check database status
    doc = db.client.table('source_documents').select('*').eq('document_uuid', doc_uuid).single().execute()
    print(f"DB Status: {doc.data.get('celery_status')}")
    print(f"Task ID: {doc.data.get('celery_task_id')}")
    
    # 2. Check Redis state
    state_key = CacheKeys.format_key(CacheKeys.DOC_STATE, document_uuid=doc_uuid)
    state_data = redis_mgr.hgetall(state_key)
    print(f"Redis State: {json.dumps(state_data, indent=2)}")
    
    # 3. Check Celery task status
    from celery.result import AsyncResult
    if doc.data.get('celery_task_id'):
        result = AsyncResult(doc.data['celery_task_id'])
        print(f"Celery Status: {result.status}")
        print(f"Celery Info: {result.info}")
    
    # 4. Check for errors in related tables
    # ... additional checks
```

## Phase 5: Fix Implementation Strategy

### 5.1 Fix Prioritization
1. **Critical**: Fixes that prevent any document processing
2. **High**: Fixes for specific document types or stages
3. **Medium**: Performance or efficiency improvements
4. **Low**: Cosmetic or logging improvements

### 5.2 Safe Fix Guidelines
1. **Always test fixes in isolation** before applying to main code
2. **Maintain backwards compatibility** with existing documents
3. **Add error handling** rather than removing it
4. **Document all changes** with clear comments
5. **Verify no regression** in previously working features

### 5.3 Fix Verification Process
```bash
# After implementing a fix:
1. Restart Celery workers
2. Clear Redis cache for affected documents
3. Retest failed documents
4. Run full test suite
5. Monitor for 10+ successful completions
```

## Phase 6: Success Criteria

### 6.1 Individual Document Success
- Document progresses through all stages
- Final celery_status = 'completed'
- All expected database entries created
- No errors in logs

### 6.2 System Success Metrics
- 95%+ documents complete successfully
- Average processing time < 5 minutes
- No stuck documents after 30 minutes
- All document types supported
- Graceful error handling for failures

### 6.3 Robustness Verification
- System handles concurrent submissions
- Recovers from worker restarts
- Handles malformed documents gracefully
- Retry mechanism works correctly
- No memory leaks or resource exhaustion

## Phase 7: Final Validation

### 7.1 Complete Test Suite
```python
def run_final_validation():
    """Run comprehensive validation after fixes"""
    
    # 1. Test all document types
    test_results = run_document_type_tests()
    
    # 2. Test error scenarios
    error_test_results = run_error_scenario_tests()
    
    # 3. Test concurrent processing
    concurrent_results = run_concurrent_tests()
    
    # 4. Test system recovery
    recovery_results = run_recovery_tests()
    
    # 5. Performance benchmarks
    performance_results = run_performance_tests()
    
    # Generate final report
    generate_validation_report(
        test_results,
        error_test_results,
        concurrent_results,
        recovery_results,
        performance_results
    )
```

### 7.2 Documentation Updates
After successful validation:
1. Update CLAUDE.md with Celery-specific commands
2. Document any new error codes or states
3. Add troubleshooting guide
4. Update performance benchmarks

## Implementation Checklist

- [ ] Start Celery workers with proper logging
- [ ] Run standalone_pipeline_monitor.py
- [ ] Test first PDF document
- [ ] Monitor all processing stages
- [ ] Log any errors encountered
- [ ] Implement fixes for critical issues
- [ ] Test remaining document types
- [ ] Verify concurrent processing
- [ ] Run stress tests
- [ ] Document all findings
- [ ] Update system documentation
- [ ] Create runbook for operations

## Summary

This plan provides a systematic approach to verify and fix the Celery-based document processing system. By following these phases, we can ensure robust, reliable document processing while maintaining system integrity throughout the testing and fixing process.