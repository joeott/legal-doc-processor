# Context 392: Production Pipeline Recovery Implementation Plan

## Date: 2025-06-04 20:00

### Executive Summary
This document provides a comprehensive plan to restore the legal document processing pipeline to full operational status. The pipeline is currently blocked at the OCR stage due to API mismatches following script consolidation. This plan addresses immediate fixes, restored functionality, and verification steps to achieve 100% pipeline completion for all 201 test documents.

### Current Pipeline State Analysis

#### Working Components ✅
1. **Infrastructure**
   - Database (RDS PostgreSQL) - Connected and operational
   - Redis Cache - Connected and functional
   - S3 Storage - Accessible with correct region (us-east-2)
   - Celery Workers - Running with proper configuration

2. **Initial Stages**
   - Document Creation - Documents successfully created in database
   - S3 Upload - All 201 files uploaded successfully
   - OCR Initiation - Textract jobs start successfully with region fix

#### Blocked Components ❌
1. **OCR Completion** - API mismatch prevents saving extracted text
2. **Text Chunking** - Waiting for OCR text
3. **Entity Extraction** - Waiting for chunks
4. **Entity Resolution** - Function exists but not properly integrated
5. **Relationship Building** - Waiting for resolved entities

### Root Cause Analysis

#### Primary Issues
1. **API Parameter Mismatch**
   - `confidence_score` vs `avg_confidence` in update_textract_job_status
   - Prevents OCR results from being saved to database

2. **Missing Service Integration**
   - Entity resolution implemented inline rather than as service method
   - Lacks caching and advanced LLM features from original

3. **Simplified Chunking**
   - Lost legal document awareness (citations, sections)
   - Basic chunking may miss important document structure

### Implementation Plan

## Phase 1: Immediate OCR Pipeline Fix (30 minutes)

### Task 1.1: Fix API Parameter Mismatch
**File**: `scripts/textract_utils.py`
**Line**: 596
**Change**:
```python
# FROM:
confidence_score=confidence,
# TO:
avg_confidence=confidence,
```

**Verification**:
```bash
# Confirm the fix
grep -n "confidence_score" scripts/textract_utils.py
# Should return no results

grep -n "avg_confidence" scripts/textract_utils.py
# Should show the corrected line
```

### Task 1.2: Restart Workers
```bash
# Kill existing workers
ps aux | grep "[c]elery" | awk '{print $2}' | xargs -r kill -9

# Start with environment
source load_env.sh
export S3_BUCKET_REGION="us-east-2"
celery -A scripts.celery_app worker --loglevel=info \
  --queues=default,ocr,text,entity,graph,cleanup \
  --concurrency=8 > celery_worker.log 2>&1 &
```

### Task 1.3: Clear Failed States (Optional)
```python
# Script: clear_failed_ocr_states.py
from scripts.cache import get_redis_manager
import json

redis_manager = get_redis_manager()
failed_docs = []

# Find all documents with failed OCR
for key in redis_manager.client.scan_iter("doc:state:*"):
    state = redis_manager.get_dict(key.decode())
    if state and state.get('ocr', {}).get('status') == 'failed':
        doc_uuid = key.decode().split(':')[-1]
        failed_docs.append(doc_uuid)
        
        # Reset to allow retry
        state['ocr']['status'] = 'pending'
        state['last_update']['status'] = 'pending'
        redis_manager.set_dict(key.decode(), state)

print(f"Reset {len(failed_docs)} failed documents")
```

### Task 1.4: Resubmit Test Document
```python
# Test single document
from scripts.pdf_tasks import extract_text_from_document
doc_uuid = '6c097038-f5a2-46aa-aa6f-43b4d150afa4'
s3_path = 's3://samu-docs-private-upload/documents/6c097038-f5a2-46aa-aa6f-43b4d150afa4/IMG_0836.pdf'
result = extract_text_from_document.delay(doc_uuid, s3_path)
print(f"Task ID: {result.id}")
```

**Success Criteria**:
- Textract job completes without error
- raw_extracted_text populated in database
- Redis state shows ocr status as "completed"

## Phase 2: Entity Resolution Service Integration (1 hour)

### Task 2.1: Create Proper Entity Resolution Method
**File**: `scripts/entity_service.py`
**Add Method**:
```python
def resolve_entities(self, document_uuid: str, entity_mentions: List[Dict]) -> Dict[str, Any]:
    """
    Resolve entity mentions to canonical entities with caching.
    
    Args:
        document_uuid: Document UUID
        entity_mentions: List of entity mention dictionaries
        
    Returns:
        Dictionary with canonical entities and resolution metadata
    """
    # Check cache first
    cache_key = CacheKeys.DOC_ENTITIES_RESOLVED.format(document_uuid=document_uuid)
    cached_result = self.redis_manager.get_dict(cache_key)
    if cached_result:
        return cached_result
    
    # Import resolution logic from pdf_tasks.py
    # Add proper caching, LLM support, and error handling
    # Return structured result
```

### Task 2.2: Update pdf_tasks.py to Use Service
**File**: `scripts/pdf_tasks.py`
**Function**: `resolve_document_entities`
**Change**: Replace inline resolution with service call
```python
# Instead of inline resolution
entity_service = EntityService(db_manager, use_openai=True)
result = entity_service.resolve_entities(document_uuid, entity_mentions)
```

### Task 2.3: Add Advanced Resolution Features
- Restore LLM-based similarity checking
- Implement confidence thresholds
- Add legal entity type awareness

**Verification**:
```python
# Test entity resolution
from scripts.entity_service import EntityService
from scripts.db import DatabaseManager

db = DatabaseManager(validate_conformance=False)
service = EntityService(db)

# Get test entities
entities = db.session.query(...).filter_by(document_uuid='...').all()
result = service.resolve_entities(document_uuid, entities)
print(f"Resolved {len(result['canonical_entities'])} canonical entities")
```

## Phase 3: Restore Advanced Chunking (Optional - 2 hours)

### Task 3.1: Analyze Legal Document Structure
Review `archived_codebase/archive_pre_consolidation/plain_text_chunker.py` for:
- Citation detection patterns
- Section boundary detection
- Legal paragraph handling

### Task 3.2: Enhance simple_chunk_text Function
**File**: `scripts/chunking_utils.py`
Add legal document awareness:
```python
def chunk_legal_document(text: str, chunk_size: int = 1000) -> List[Dict]:
    """Enhanced chunking for legal documents."""
    # Detect document sections
    # Preserve citation integrity
    # Maintain paragraph boundaries
    # Return structured chunks with metadata
```

### Task 3.3: Update chunk_document_text Task
Detect document type and use appropriate chunking strategy

## Phase 4: Complete Pipeline Execution (1 hour)

### Task 4.1: Run Full Production Test
```python
# Script: run_complete_production_test.py
import json
from scripts.pdf_tasks import process_pdf_document

# Load manifest
with open('production_test_manifest_20250604_142117.json', 'r') as f:
    manifest = json.load(f)

# Process all documents
for doc in manifest['documents']:
    result = process_pdf_document.delay(
        document_uuid=doc['document_uuid'],
        file_path=doc['s3_uri'],
        project_uuid=manifest['project']['project_uuid']
    )
    print(f"Submitted {doc['document_uuid']}: {result.id}")
```

### Task 4.2: Monitor Pipeline Progress
```python
# Script: monitor_pipeline_progress.py
from scripts.db import DatabaseManager
import time

db = DatabaseManager(validate_conformance=False)
project_uuid = '4a0db6b4-7f77-4d51-9920-22fdd34eaac8'

while True:
    stats = db.session.execute("""
        SELECT 
            COUNT(*) as total,
            COUNT(raw_extracted_text) as ocr_complete,
            COUNT(DISTINCT dc.document_uuid) as chunked,
            COUNT(DISTINCT em.document_uuid) as entities_extracted,
            COUNT(DISTINCT ce.id) as canonical_entities
        FROM source_documents sd
        LEFT JOIN document_chunks dc ON sd.document_uuid = dc.document_uuid
        LEFT JOIN entity_mentions em ON sd.document_uuid = em.document_uuid
        LEFT JOIN canonical_entities ce ON em.canonical_entity_uuid = ce.entity_uuid
        WHERE sd.project_uuid = :project_uuid
    """, {'project_uuid': project_uuid}).fetchone()
    
    print(f"Progress: OCR={stats.ocr_complete}/{stats.total}, "
          f"Chunks={stats.chunked}, Entities={stats.entities_extracted}, "
          f"Canonical={stats.canonical_entities}")
    
    if stats.ocr_complete == stats.total:
        break
    time.sleep(10)
```

## Phase 5: Verification and Validation (30 minutes)

### Task 5.1: Verify OCR Completion
```sql
-- Check OCR results
SELECT COUNT(*) as total, 
       COUNT(raw_extracted_text) as completed,
       AVG(LENGTH(raw_extracted_text)) as avg_text_length
FROM source_documents 
WHERE project_uuid = '4a0db6b4-7f77-4d51-9920-22fdd34eaac8';
```

### Task 5.2: Verify Chunking
```sql
-- Check chunking results
SELECT sd.document_uuid, 
       COUNT(dc.id) as chunk_count,
       AVG(LENGTH(dc.chunk_text)) as avg_chunk_size
FROM source_documents sd
LEFT JOIN document_chunks dc ON sd.document_uuid = dc.document_uuid
WHERE sd.project_uuid = '4a0db6b4-7f77-4d51-9920-22fdd34eaac8'
GROUP BY sd.document_uuid;
```

### Task 5.3: Verify Entity Extraction
```sql
-- Check entity extraction
SELECT entity_type, COUNT(*) as count
FROM entity_mentions em
JOIN source_documents sd ON em.document_uuid = sd.document_uuid
WHERE sd.project_uuid = '4a0db6b4-7f77-4d51-9920-22fdd34eaac8'
GROUP BY entity_type;
```

### Task 5.4: Verify Entity Resolution
```sql
-- Check canonical entities
SELECT ce.entity_type, COUNT(DISTINCT ce.entity_uuid) as unique_entities
FROM canonical_entities ce
JOIN entity_mentions em ON ce.entity_uuid = em.canonical_entity_uuid
JOIN source_documents sd ON em.document_uuid = sd.document_uuid
WHERE sd.project_uuid = '4a0db6b4-7f77-4d51-9920-22fdd34eaac8'
GROUP BY ce.entity_type;
```

### Task 5.5: Generate Final Report
```python
# Script: generate_final_report.py
from datetime import datetime
import json

def generate_pipeline_report(project_uuid: str):
    """Generate comprehensive pipeline execution report."""
    # Collect all metrics
    # Calculate success rates
    # Identify any failures
    # Generate recommendations
    
    report = {
        'timestamp': datetime.utcnow().isoformat(),
        'project_uuid': project_uuid,
        'total_documents': 201,
        'pipeline_stages': {
            'ocr': {'completed': 0, 'failed': 0, 'success_rate': 0},
            'chunking': {'completed': 0, 'failed': 0, 'success_rate': 0},
            'entity_extraction': {'completed': 0, 'failed': 0, 'success_rate': 0},
            'entity_resolution': {'completed': 0, 'failed': 0, 'success_rate': 0},
            'relationship_building': {'completed': 0, 'failed': 0, 'success_rate': 0}
        }
    }
    
    with open(f'final_report_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.json', 'w') as f:
        json.dump(report, f, indent=2)
    
    return report
```

## Success Criteria Checklist

### Immediate Success (Phase 1)
- [ ] API parameter mismatch fixed
- [ ] Workers restarted with correct configuration
- [ ] Test document OCR completes successfully
- [ ] Text saved to database

### Short-term Success (Phase 2-3)
- [ ] Entity resolution moved to service class
- [ ] All 201 documents process through OCR
- [ ] Chunking produces expected results
- [ ] Entity extraction identifies >50,000 entities

### Complete Success (Phase 4-5)
- [ ] 100% documents complete full pipeline
- [ ] >99% success rate per stage
- [ ] <15 minutes total processing time
- [ ] >5,000 relationships identified
- [ ] Final report generated

## Risk Mitigation

### Potential Issues and Solutions

1. **Memory Issues with Large Documents**
   - Solution: Already handled by large file splitting logic
   - Monitor: Worker memory usage during processing

2. **API Rate Limits**
   - Solution: Celery retry with exponential backoff
   - Monitor: OpenAI API usage and errors

3. **Database Connection Pool Exhaustion**
   - Solution: Pool configuration already optimized
   - Monitor: Active connections during peak processing

4. **Redis Memory Limits**
   - Solution: TTL settings already configured
   - Monitor: Redis memory usage

## Rollback Plan

If issues arise:
1. Stop all workers
2. Clear Redis cache: `FLUSHDB`
3. Reset database state: `TRUNCATE` relevant tables
4. Restore from backup if needed
5. Apply fixes and restart

## Long-term Improvements

After immediate pipeline recovery:
1. Implement comprehensive logging
2. Add Prometheus metrics
3. Create automated testing suite
4. Document all API contracts
5. Implement circuit breakers for external services

## Conclusion

This plan provides a systematic approach to recovering the production pipeline. The immediate fix (Phase 1) should unblock OCR processing within 30 minutes. Subsequent phases restore advanced functionality while maintaining pipeline operation. The verification steps ensure we can demonstrate successful processing of all 201 documents with measurable success criteria.