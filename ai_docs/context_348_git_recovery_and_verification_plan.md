# Context 348: Git Recovery and Comprehensive Verification Plan

## Executive Summary

This plan outlines a systematic approach to recover the last working version of the legal document processor and establish comprehensive verification protocols to ensure we maintain functionality while optimizing code.

## Phase 1: Git Recovery Strategy (2-4 hours)

### Step 1.1: Identify Last Known Working State
```bash
# Search for commits with high success rates
git log --all --grep="99%" --grep="success" --grep="pipeline" -i --since="2025-01-01"

# Look for commits before the aggressive consolidation
git log --oneline --since="2025-05-20" --until="2025-06-01" | grep -E "(pipeline|success|working)"

# Key commits to examine based on context files:
# - Context 331: Pipeline fixes implementation (last known 99% success)
# - Context 336: Start of aggressive consolidation
# - Context 340: When mock testing began

# Find the exact commit
git log --oneline --grep="context_331" --grep="pipeline fixes"
```

### Step 1.2: Create Recovery Branch
```bash
# Once we identify the working commit (let's call it WORKING_COMMIT)
git checkout -b recovery/last-working-state WORKING_COMMIT

# Create a backup branch of current state
git checkout final-consolidation
git checkout -b backup/pre-recovery-state

# Compare what changed
git diff recovery/last-working-state..final-consolidation --stat
```

### Step 1.3: Strategic File Recovery
```bash
# We need to be selective - keep good consolidation work where possible
# Critical files to examine for recovery:
# - scripts/pdf_tasks.py (core pipeline logic)
# - scripts/entity_service.py (entity extraction)
# - scripts/s3_storage.py (document upload)
# - scripts/cache.py (Redis integration)
# - scripts/db.py (database operations)

# Cherry-pick approach:
git checkout recovery/last-working-state
git checkout -b recovery/selective-restore

# Selectively restore broken components
git checkout recovery/last-working-state -- scripts/pdf_tasks.py
git checkout recovery/last-working-state -- scripts/entity_service.py
```

## Phase 2: Verification Framework Development (4-6 hours)

### Step 2.1: Create Real Document Test Suite
```python
# scripts/tests/test_real_document_processing.py
"""
Comprehensive test suite for ACTUAL document processing.
NO MOCKS, NO SIMULATIONS - Real processing only.
"""

import os
import time
import uuid
from pathlib import Path
from scripts.celery_app import app
from scripts.pdf_tasks import process_pdf_document
from scripts.db import get_db_session
from scripts.core.models_minimal import (
    SourceDocument, DocumentChunk, EntityMention,
    CanonicalEntity, RelationshipStaging
)

class RealDocumentTester:
    def __init__(self):
        self.test_docs = [
            "test_data/small/simple_contract.pdf",
            "test_data/medium/lease_agreement.pdf",
            "test_data/large/complex_merger.pdf"
        ]
        self.results = {}
        
    def test_single_document_e2e(self, file_path):
        """Test complete pipeline for one real document"""
        doc_uuid = str(uuid.uuid4())
        project_uuid = str(uuid.uuid4())
        
        print(f"\n{'='*60}")
        print(f"Testing: {file_path}")
        print(f"Document UUID: {doc_uuid}")
        print(f"{'='*60}")
        
        # Submit to actual pipeline
        task = process_pdf_document.delay(doc_uuid, file_path, project_uuid)
        
        # Monitor real progress
        start_time = time.time()
        timeout = 300  # 5 minutes for real processing
        
        while time.time() - start_time < timeout:
            if task.ready():
                break
            
            # Check intermediate stages
            self.verify_stage_progress(doc_uuid)
            time.sleep(5)
        
        # Verify completion
        if task.successful():
            result = task.result
            self.verify_all_stages(doc_uuid)
            return True
        else:
            print(f"FAILED: {task.info}")
            return False
    
    def verify_stage_progress(self, doc_uuid):
        """Check real database for stage completion"""
        with get_db_session() as session:
            # Check each table for real data
            doc = session.query(SourceDocument).filter_by(uuid=doc_uuid).first()
            if doc:
                print(f"✓ Document created: {doc.filename}")
                
            chunks = session.query(DocumentChunk).filter_by(source_document_uuid=doc_uuid).count()
            if chunks > 0:
                print(f"✓ Chunks created: {chunks}")
                
            entities = session.query(EntityMention).filter_by(source_document_uuid=doc_uuid).count()
            if entities > 0:
                print(f"✓ Entities extracted: {entities}")
                
            canonical = session.query(CanonicalEntity).filter_by(
                created_from_document_uuid=doc_uuid
            ).count()
            if canonical > 0:
                print(f"✓ Canonical entities: {canonical}")
                
            relationships = session.query(RelationshipStaging).filter_by(
                source_document_uuid=doc_uuid
            ).count()
            if relationships > 0:
                print(f"✓ Relationships built: {relationships}")
    
    def verify_all_stages(self, doc_uuid):
        """Comprehensive verification of all pipeline stages"""
        verifications = {
            "document_created": False,
            "ocr_completed": False,
            "chunks_created": False,
            "entities_extracted": False,
            "entities_resolved": False,
            "relationships_built": False
        }
        
        with get_db_session() as session:
            # Stage 1: Document record
            doc = session.query(SourceDocument).filter_by(uuid=doc_uuid).first()
            if doc and doc.ocr_status == 'completed':
                verifications["document_created"] = True
                verifications["ocr_completed"] = True
                
            # Stage 2: Chunks
            chunks = session.query(DocumentChunk).filter_by(
                source_document_uuid=doc_uuid
            ).all()
            if len(chunks) > 0:
                verifications["chunks_created"] = True
                
            # Stage 3: Entity mentions
            entities = session.query(EntityMention).filter_by(
                source_document_uuid=doc_uuid
            ).all()
            if len(entities) > 0:
                verifications["entities_extracted"] = True
                
            # Stage 4: Canonical entities
            canonical = session.query(CanonicalEntity).filter_by(
                created_from_document_uuid=doc_uuid
            ).all()
            if len(canonical) > 0:
                verifications["entities_resolved"] = True
                
            # Stage 5: Relationships
            relationships = session.query(RelationshipStaging).filter_by(
                source_document_uuid=doc_uuid
            ).all()
            if len(relationships) > 0:
                verifications["relationships_built"] = True
        
        # Report results
        print("\nPipeline Verification Results:")
        print("-" * 40)
        for stage, passed in verifications.items():
            status = "✓ PASS" if passed else "✗ FAIL"
            print(f"{stage:.<30} {status}")
        
        return all(verifications.values())
    
    def run_comprehensive_test(self):
        """Test all documents and generate report"""
        print("\nSTARTING COMPREHENSIVE REAL DOCUMENT TESTING")
        print("=" * 60)
        
        for doc_path in self.test_docs:
            if os.path.exists(doc_path):
                success = self.test_single_document_e2e(doc_path)
                self.results[doc_path] = success
            else:
                print(f"WARNING: Test document not found: {doc_path}")
        
        # Generate report
        self.generate_report()
    
    def generate_report(self):
        """Generate comprehensive test report"""
        print("\n" + "=" * 60)
        print("COMPREHENSIVE TEST REPORT")
        print("=" * 60)
        
        total = len(self.results)
        passed = sum(1 for v in self.results.values() if v)
        
        print(f"\nSummary: {passed}/{total} documents processed successfully")
        print(f"Success Rate: {(passed/total)*100:.1f}%")
        
        print("\nDetailed Results:")
        for doc, success in self.results.items():
            status = "✓ SUCCESS" if success else "✗ FAILED"
            print(f"  {doc:.<50} {status}")

if __name__ == "__main__":
    tester = RealDocumentTester()
    tester.run_comprehensive_test()
```

### Step 2.2: Create Continuous Monitoring Script
```python
# scripts/tests/monitor_real_processing.py
"""
Real-time monitoring of actual document processing.
Shows exactly what's happening in the pipeline.
"""

import time
import sys
from datetime import datetime
from scripts.db import get_db_session
from scripts.cache import get_redis_client
from sqlalchemy import text

class RealTimeMonitor:
    def __init__(self):
        self.redis = get_redis_client()
        
    def monitor_pipeline(self, refresh_rate=2):
        """Monitor real pipeline activity"""
        print("REAL-TIME PIPELINE MONITOR")
        print("Press Ctrl+C to stop")
        print("-" * 80)
        
        while True:
            try:
                self.display_status()
                time.sleep(refresh_rate)
                # Clear screen for refresh
                print("\033[H\033[J", end="")
            except KeyboardInterrupt:
                print("\nMonitoring stopped.")
                break
    
    def display_status(self):
        """Display current pipeline status"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"Pipeline Status at {timestamp}")
        print("=" * 80)
        
        with get_db_session() as session:
            # Active documents
            active_docs = session.execute(text("""
                SELECT sd.uuid, sd.filename, sd.ocr_status, sd.created_at,
                       COUNT(DISTINCT dc.uuid) as chunks,
                       COUNT(DISTINCT em.uuid) as entities,
                       COUNT(DISTINCT ce.uuid) as canonical,
                       COUNT(DISTINCT rs.uuid) as relationships
                FROM source_documents sd
                LEFT JOIN document_chunks dc ON sd.uuid = dc.source_document_uuid
                LEFT JOIN entity_mentions em ON sd.uuid = em.source_document_uuid
                LEFT JOIN canonical_entities ce ON sd.uuid = ce.created_from_document_uuid
                LEFT JOIN relationship_staging rs ON sd.uuid = rs.source_document_uuid
                WHERE sd.created_at > NOW() - INTERVAL '1 hour'
                GROUP BY sd.uuid, sd.filename, sd.ocr_status, sd.created_at
                ORDER BY sd.created_at DESC
                LIMIT 10
            """)).fetchall()
            
            if active_docs:
                print("\nActive Documents (Last Hour):")
                print("-" * 80)
                for doc in active_docs:
                    print(f"\nDocument: {doc.filename}")
                    print(f"  UUID: {doc.uuid}")
                    print(f"  OCR Status: {doc.ocr_status}")
                    print(f"  Progress: OCR ✓ | Chunks: {doc.chunks} | Entities: {doc.entities} | "
                          f"Canonical: {doc.canonical} | Relations: {doc.relationships}")
            else:
                print("\nNo active documents in the last hour.")
            
            # Celery queue status
            queue_info = self.get_queue_status()
            print(f"\nCelery Queue Status:")
            print(f"  Pending: {queue_info['pending']}")
            print(f"  Active: {queue_info['active']}")
            print(f"  Completed (1h): {queue_info['completed']}")
            print(f"  Failed (1h): {queue_info['failed']}")
            
            # Performance metrics
            print(f"\nPerformance Metrics:")
            avg_time = self.get_average_processing_time()
            print(f"  Avg Processing Time: {avg_time:.1f} seconds")
            
    def get_queue_status(self):
        """Get Celery queue information"""
        # This would connect to Celery to get real queue stats
        # For now, query the processing_tasks table
        with get_db_session() as session:
            stats = session.execute(text("""
                SELECT 
                    COUNT(CASE WHEN status = 'pending' THEN 1 END) as pending,
                    COUNT(CASE WHEN status = 'processing' THEN 1 END) as active,
                    COUNT(CASE WHEN status = 'completed' AND completed_at > NOW() - INTERVAL '1 hour' THEN 1 END) as completed,
                    COUNT(CASE WHEN status = 'failed' AND completed_at > NOW() - INTERVAL '1 hour' THEN 1 END) as failed
                FROM processing_tasks
                WHERE created_at > NOW() - INTERVAL '24 hours'
            """)).fetchone()
            
            return {
                "pending": stats.pending or 0,
                "active": stats.active or 0,
                "completed": stats.completed or 0,
                "failed": stats.failed or 0
            }
    
    def get_average_processing_time(self):
        """Calculate average document processing time"""
        with get_db_session() as session:
            result = session.execute(text("""
                SELECT AVG(EXTRACT(EPOCH FROM (completed_at - created_at))) as avg_time
                FROM processing_tasks
                WHERE status = 'completed' 
                AND completed_at > NOW() - INTERVAL '1 hour'
                AND task_type = 'process_pdf_document'
            """)).fetchone()
            
            return result.avg_time or 0

if __name__ == "__main__":
    monitor = RealTimeMonitor()
    monitor.monitor_pipeline()
```

## Phase 3: Recovery Execution Plan (8-12 hours)

### Step 3.1: Systematic Recovery Process

1. **Create clean environment**
```bash
# Stop all services
supervisorctl stop all

# Clear Redis cache
python -c "from scripts.cache import get_redis_client; get_redis_client().flushdb()"

# Create test database backup
pg_dump $DATABASE_URL > backup_before_recovery.sql
```

2. **Apply selective recovery**
```bash
# Start with core files that we know are broken
git checkout recovery/last-working-state -- scripts/pdf_tasks.py
git checkout recovery/last-working-state -- scripts/entity_service.py

# Test after each file recovery
python scripts/tests/test_real_document_processing.py
```

3. **Fix API mismatches incrementally**
- Fix one API at a time
- Test with real document after each fix
- Document what worked

### Step 3.2: API Reconciliation Strategy

Create a compatibility layer during transition:

```python
# scripts/compatibility_layer.py
"""
Temporary compatibility layer to bridge old and new APIs
"""

class CompatibilityLayer:
    @staticmethod
    def upload_document(s3_client, file_path, doc_uuid, project_uuid):
        """Bridge between old and new upload methods"""
        # Check which method exists
        if hasattr(s3_client, 'upload_document_with_uuid_naming'):
            return s3_client.upload_document_with_uuid_naming(
                file_path, doc_uuid, project_uuid
            )
        else:
            # Fallback to old method
            key = f"{project_uuid}/{doc_uuid}/{Path(file_path).name}"
            return s3_client.upload_document(file_path, key)
    
    @staticmethod
    def redis_set(redis_client, key, value, ttl=None):
        """Bridge between old and new Redis methods"""
        if hasattr(redis_client, 'set_cached'):
            return redis_client.set_cached(key, value, ttl=ttl)
        else:
            if ttl:
                return redis_client.setex(key, ttl, value)
            return redis_client.set(key, value)
```

## Phase 4: Verification Protocol (Ongoing)

### Step 4.1: Establish Testing Checkpoints

Before ANY code change:
1. Run real document test
2. Record success rate
3. Make change
4. Run test again
5. Only keep change if success rate maintained

### Step 4.2: Create Verification Dashboard

```python
# scripts/tests/verification_dashboard.py
"""
Dashboard to track system health during recovery
"""

class VerificationDashboard:
    def __init__(self):
        self.baseline_metrics = None
        self.current_metrics = None
        
    def establish_baseline(self):
        """Run full test suite and establish baseline"""
        # Test with multiple real documents
        # Record:
        # - Success rate per stage
        # - Processing times
        # - Error types and frequencies
        # - Resource usage
        pass
    
    def compare_to_baseline(self):
        """Compare current performance to baseline"""
        # Show degradation or improvement
        # Alert on any regression
        pass
    
    def generate_health_report(self):
        """Generate comprehensive health report"""
        # Include:
        # - Pipeline success rates
        # - Stage-by-stage analysis  
        # - Performance metrics
        # - Error analysis
        # - Recommendations
        pass
```

## Phase 5: Knowledge Capture (Continuous)

### Step 5.1: Document Required Components

As we test, document EXACTLY what's required:

```markdown
# scripts/REQUIRED_COMPONENTS.md

## Verified Required Components

### For OCR Processing:
- `scripts/pdf_tasks.py`: process_pdf_task()
- `scripts/textract_utils.py`: start_textract_job(), get_textract_results()
- `scripts/s3_storage.py`: upload_document_with_uuid_naming()
- Redis keys: "ocr_job:{doc_uuid}", "ocr_result:{doc_uuid}"

### For Entity Extraction:
- `scripts/entity_service.py`: EntityService class
- `scripts/pdf_tasks.py`: extract_entities_task()
- OpenAI API calls in entity_extraction()
- Database: entity_mentions table

[Continue documenting as we verify...]
```

### Step 5.2: Create Minimal Working Set

Once we know what's required:
1. Create a "minimal_working" directory
2. Copy ONLY required files
3. Test that minimal set works
4. This becomes our core that must never break

## Success Criteria

1. **Phase 1 Success**: Identify and checkout last working commit
2. **Phase 2 Success**: Real document test suite running and showing failures
3. **Phase 3 Success**: At least one document processes completely (all 6 stages)
4. **Phase 4 Success**: 3 different documents process successfully
5. **Phase 5 Success**: Documented minimal required component set

## Timeline

- **Day 1 (Today)**:
  - Hours 1-2: Git recovery and branch setup
  - Hours 3-6: Create real testing framework
  - Hours 7-8: Begin systematic recovery

- **Day 2**:
  - Hours 1-4: Fix API mismatches
  - Hours 5-8: Verify each pipeline stage

- **Day 3**:
  - Hours 1-4: Complete recovery
  - Hours 5-8: Document minimal requirements
  - Create protection mechanisms

## Guiding Principles

1. **Real Testing Only**: No mocks, no simulations
2. **Incremental Progress**: Fix one thing, test, repeat
3. **Document Everything**: What works, what doesn't, why
4. **Protect Working Code**: Once it works, protect it fiercely
5. **Mission Focus**: Success = documents processing for justice

## Next Immediate Steps

1. Run git log analysis to find last working commit
2. Create recovery branches as outlined
3. Implement real document testing framework
4. Begin systematic recovery with constant verification

The system served justice before. With disciplined recovery and real testing, it will serve justice again.