# Context 415: Tiered and Phased Testing Plan for Legal Document Processor

## Executive Summary

This document provides a comprehensive, production-conformant testing plan for the legal document processing pipeline. The plan progresses through 5 tiers, starting with a single document and scaling to full production loads, with detailed verification criteria and implementation guidance suitable for autonomous execution.

## Testing Philosophy

1. **Production Conformance**: All tests use actual production scripts and workflows
2. **Progressive Complexity**: Start simple, add complexity only after success
3. **Full Pipeline Coverage**: Every stage must be verified before proceeding
4. **Data Integrity**: Verify data persistence and correctness at each step
5. **Observable Progress**: Clear monitoring and verification at all stages

## Tier 1: Single Document Processing

### Objective
Successfully process one document through the entire pipeline with full verification at each stage.

### Test Document
```
input_docs/Paul, Michael (Acuity)/Paul, Michael - Lora Prop Disclosure Stmt 10-21-24.pdf
```

### Phase 1.1: Environment Setup and Validation

```bash
# 1. Source environment
cd /opt/legal-doc-processor
source load_env.sh

# 2. Verify core services
python3 -c "
from scripts.config import (
    DATABASE_URL, REDIS_HOST, S3_PRIMARY_DOCUMENT_BUCKET,
    OPENAI_API_KEY, AWS_ACCESS_KEY_ID
)
print('✅ Database URL:', 'configured' if DATABASE_URL else 'MISSING')
print('✅ Redis Host:', 'configured' if REDIS_HOST else 'MISSING')
print('✅ S3 Bucket:', S3_PRIMARY_DOCUMENT_BUCKET or 'MISSING')
print('✅ OpenAI:', 'configured' if OPENAI_API_KEY else 'MISSING')
print('✅ AWS:', 'configured' if AWS_ACCESS_KEY_ID else 'MISSING')
"

# 3. Test database connection
python3 -c "
from scripts.db import DatabaseManager
db = DatabaseManager()
session = next(db.get_session())
result = session.execute('SELECT 1').scalar()
print('✅ Database connection:', 'OK' if result == 1 else 'FAILED')
session.close()
"

# 4. Test Redis connection
python3 -c "
from scripts.cache import get_redis_manager
redis = get_redis_manager()
test_key = 'test:connection'
redis.set(test_key, 'ok', ttl=10)
result = redis.get(test_key)
print('✅ Redis connection:', 'OK' if result == 'ok' else 'FAILED')
"

# 5. Test S3 access
python3 -c "
import boto3
from scripts.config import S3_PRIMARY_DOCUMENT_BUCKET, AWS_DEFAULT_REGION
s3 = boto3.client('s3', region_name=AWS_DEFAULT_REGION)
try:
    s3.head_bucket(Bucket=S3_PRIMARY_DOCUMENT_BUCKET)
    print('✅ S3 access: OK')
except Exception as e:
    print('❌ S3 access FAILED:', str(e))
"
```

**Verification Criteria:**
- All services show "OK" or "configured"
- No connection errors
- Environment variables properly loaded

### Phase 1.2: Create Project and Manifest

```bash
# 1. Create test project
python3 -c "
from scripts.db import DatabaseManager
from uuid import uuid4
import json

db = DatabaseManager()
project_uuid = uuid4()
project_name = 'TEST_TIER1_SINGLE_DOC'

# Create project
session = next(db.get_session())
session.execute('''
    INSERT INTO projects (project_id, name, created_at)
    VALUES (%s, %s, NOW())
    ON CONFLICT (project_id) DO UPDATE SET name = EXCLUDED.name
''', (project_uuid, project_name))
session.commit()
session.close()

print(f'✅ Created project: {project_name}')
print(f'   UUID: {project_uuid}')

# Save for later use
with open('test_project_uuid.txt', 'w') as f:
    f.write(str(project_uuid))
"

# 2. Create manifest
cat > tier1_manifest.json << 'EOF'
{
  "project_name": "TEST_TIER1_SINGLE_DOC",
  "import_session": "tier1_test_001",
  "documents": [
    {
      "file_path": "input_docs/Paul, Michael (Acuity)/Paul, Michael - Lora Prop Disclosure Stmt 10-21-24.pdf",
      "document_name": "Paul Michael - Lora Prop Disclosure Statement",
      "document_type": "disclosure_statement",
      "metadata": {
        "client": "Paul, Michael",
        "matter": "Acuity",
        "date": "2024-10-21",
        "test_tier": "1",
        "test_phase": "1.2"
      }
    }
  ]
}
EOF

echo "✅ Created manifest: tier1_manifest.json"
```

**Verification Criteria:**
- Project created in database
- Project UUID saved for reference
- Manifest file created with correct structure

### Phase 1.3: Submit Document for Processing

```bash
# 1. Submit using production processor
python3 scripts/production_processor.py \
    --manifest tier1_manifest.json \
    --mode async \
    --verbose \
    2>&1 | tee tier1_submission.log

# 2. Extract document UUID from log
DOCUMENT_UUID=$(grep "Document UUID:" tier1_submission.log | awk '{print $3}')
echo "Document UUID: $DOCUMENT_UUID" > tier1_document_uuid.txt

# 3. Verify initial database state
python3 -c "
import sys
doc_uuid = sys.argv[1]
from scripts.db import DatabaseManager
db = DatabaseManager()
session = next(db.get_session())

# Check source_documents
result = session.execute('''
    SELECT document_uuid, status, file_name, s3_key, celery_task_id
    FROM source_documents 
    WHERE document_uuid = %s
''', (doc_uuid,)).fetchone()

if result:
    print('✅ Document in database:')
    print(f'   Status: {result.status}')
    print(f'   File: {result.file_name}')
    print(f'   S3 Key: {result.s3_key}')
    print(f'   Task ID: {result.celery_task_id}')
else:
    print('❌ Document not found in database!')
" "$DOCUMENT_UUID"
```

**Verification Criteria:**
- Document successfully submitted
- Document UUID captured
- Database record created
- Initial status is "pending" or "processing"
- S3 key populated
- Celery task ID assigned

### Phase 1.4: Monitor OCR Processing

```bash
# 1. Monitor OCR status
python3 scripts/monitor_document_complete.py "$DOCUMENT_UUID" \
    --stage ocr \
    --timeout 300 \
    --interval 10

# 2. Verify OCR completion
python3 -c "
import sys
from scripts.db import DatabaseManager
from scripts.cache import get_redis_manager

doc_uuid = sys.argv[1]
db = DatabaseManager()
redis = get_redis_manager()

# Check database
session = next(db.get_session())
result = session.execute('''
    SELECT raw_extracted_text, ocr_completed_at, ocr_provider, 
           textract_job_id, char_length(raw_extracted_text) as text_length
    FROM source_documents 
    WHERE document_uuid = %s
''', (doc_uuid,)).fetchone()

print('📊 OCR Results:')
print(f'   Provider: {result.ocr_provider}')
print(f'   Completed: {result.ocr_completed_at}')
print(f'   Text Length: {result.text_length} characters')
print(f'   Textract Job: {result.textract_job_id}')

# Check Redis state
state_key = f'doc:state:{doc_uuid}'
state = redis.get_dict(state_key)
if state and 'ocr' in state:
    print(f'   Redis State: {state[\"ocr\"][\"status\"]}')

# Verify text quality
if result.text_length > 100:
    print('✅ OCR completed successfully')
else:
    print('⚠️  OCR completed but text seems short')
" "$DOCUMENT_UUID"
```

**Verification Criteria:**
- OCR stage completed within timeout
- Raw text extracted and stored
- Text length > 100 characters
- OCR provider recorded (likely "textract")
- Timestamp recorded
- Redis state shows "completed"

### Phase 1.5: Verify Text Chunking

```bash
# 1. Check chunking status
python3 -c "
import sys
from scripts.db import DatabaseManager

doc_uuid = sys.argv[1]
db = DatabaseManager()
session = next(db.get_session())

# Count chunks
chunk_count = session.execute('''
    SELECT COUNT(*) FROM document_chunks 
    WHERE document_uuid = %s
''', (doc_uuid,)).scalar()

# Get chunk details
chunks = session.execute('''
    SELECT chunk_index, char_start_index, char_end_index, 
           length(text) as text_length
    FROM document_chunks 
    WHERE document_uuid = %s
    ORDER BY chunk_index
''', (doc_uuid,)).fetchall()

print(f'📊 Chunking Results:')
print(f'   Total Chunks: {chunk_count}')
print(f'   Chunk Details:')
for chunk in chunks[:5]:  # Show first 5
    print(f'     Chunk {chunk.chunk_index}: {chunk.text_length} chars ' +
          f'[{chunk.char_start_index}:{chunk.char_end_index}]')

if chunk_count > 0:
    print('✅ Chunking completed successfully')
else:
    print('❌ No chunks found!')
" "$DOCUMENT_UUID"
```

**Verification Criteria:**
- At least 1 chunk created
- Chunks have sequential indices
- Character positions are valid
- No gaps in character coverage

### Phase 1.6: Verify Entity Extraction

```bash
# 1. Check entity extraction
python3 -c "
import sys
from scripts.db import DatabaseManager

doc_uuid = sys.argv[1]
db = DatabaseManager()
session = next(db.get_session())

# Count entity mentions
mention_count = session.execute('''
    SELECT COUNT(*) FROM entity_mentions 
    WHERE document_uuid = %s
''', (doc_uuid,)).scalar()

# Get entity type distribution
type_dist = session.execute('''
    SELECT entity_type, COUNT(*) as count
    FROM entity_mentions 
    WHERE document_uuid = %s
    GROUP BY entity_type
    ORDER BY count DESC
''', (doc_uuid,)).fetchall()

print(f'📊 Entity Extraction Results:')
print(f'   Total Mentions: {mention_count}')
print(f'   Entity Types:')
for row in type_dist:
    print(f'     {row.entity_type}: {row.count}')

# Sample entities
samples = session.execute('''
    SELECT entity_text, entity_type, confidence_score
    FROM entity_mentions 
    WHERE document_uuid = %s
    ORDER BY confidence_score DESC
    LIMIT 5
''', (doc_uuid,)).fetchall()

print(f'   Top Entities:')
for entity in samples:
    print(f'     "{entity.entity_text}" ({entity.entity_type}) - {entity.confidence_score:.2f}')

if mention_count > 0:
    print('✅ Entity extraction completed successfully')
else:
    print('❌ No entities found!')
" "$DOCUMENT_UUID"
```

**Verification Criteria:**
- At least 5 entities extracted
- Multiple entity types present
- Confidence scores between 0 and 1
- Entity text is not empty

### Phase 1.7: Verify Entity Resolution

```bash
# 1. Check canonical entities
python3 -c "
import sys
from scripts.db import DatabaseManager

doc_uuid = sys.argv[1]
db = DatabaseManager()
session = next(db.get_session())

# Count canonical entities
canonical_count = session.execute('''
    SELECT COUNT(DISTINCT ce.canonical_entity_uuid)
    FROM canonical_entities ce
    JOIN entity_mentions em ON em.canonical_entity_uuid = ce.canonical_entity_uuid
    WHERE em.document_uuid = %s
''', (doc_uuid,)).scalar()

# Get resolution stats
resolution_stats = session.execute('''
    SELECT 
        COUNT(*) as total_mentions,
        COUNT(canonical_entity_uuid) as resolved_mentions,
        COUNT(DISTINCT canonical_entity_uuid) as unique_entities
    FROM entity_mentions
    WHERE document_uuid = %s
''', (doc_uuid,)).fetchone()

print(f'📊 Entity Resolution Results:')
print(f'   Total Mentions: {resolution_stats.total_mentions}')
print(f'   Resolved Mentions: {resolution_stats.resolved_mentions}')
print(f'   Unique Canonical Entities: {resolution_stats.unique_entities}')
print(f'   Resolution Rate: {resolution_stats.resolved_mentions/resolution_stats.total_mentions*100:.1f}%')

# Show some canonical entities
canonicals = session.execute('''
    SELECT ce.canonical_name, ce.entity_type, COUNT(em.mention_uuid) as mention_count
    FROM canonical_entities ce
    JOIN entity_mentions em ON em.canonical_entity_uuid = ce.canonical_entity_uuid
    WHERE em.document_uuid = %s
    GROUP BY ce.canonical_entity_uuid, ce.canonical_name, ce.entity_type
    ORDER BY mention_count DESC
    LIMIT 5
''', (doc_uuid,)).fetchall()

print(f'   Top Canonical Entities:')
for entity in canonicals:
    print(f'     "{entity.canonical_name}" ({entity.entity_type}) - {entity.mention_count} mentions')

if canonical_count > 0:
    print('✅ Entity resolution completed successfully')
else:
    print('⚠️  No canonical entities found')
" "$DOCUMENT_UUID"
```

**Verification Criteria:**
- At least 50% of mentions resolved
- Canonical entities created
- Multiple mentions mapped to same canonical entity (deduplication working)

### Phase 1.8: Verify Relationship Building

```bash
# 1. Check relationships
python3 -c "
import sys
from scripts.db import DatabaseManager

doc_uuid = sys.argv[1]
db = DatabaseManager()
session = next(db.get_session())

# Count relationships
rel_count = session.execute('''
    SELECT COUNT(*) 
    FROM relationship_staging rs
    WHERE EXISTS (
        SELECT 1 FROM entity_mentions em
        WHERE em.document_uuid = %s
        AND (em.canonical_entity_uuid = rs.source_entity_uuid
             OR em.canonical_entity_uuid = rs.target_entity_uuid)
    )
''', (doc_uuid,)).scalar()

# Get relationship types
rel_types = session.execute('''
    SELECT DISTINCT relationship_type, COUNT(*) as count
    FROM relationship_staging rs
    WHERE EXISTS (
        SELECT 1 FROM entity_mentions em
        WHERE em.document_uuid = %s
        AND (em.canonical_entity_uuid = rs.source_entity_uuid
             OR em.canonical_entity_uuid = rs.target_entity_uuid)
    )
    GROUP BY relationship_type
''', (doc_uuid,)).fetchall()

print(f'📊 Relationship Building Results:')
print(f'   Total Relationships: {rel_count}')
print(f'   Relationship Types:')
for rel in rel_types:
    print(f'     {rel.relationship_type}: {rel.count}')

if rel_count > 0:
    print('✅ Relationship building completed successfully')
else:
    print('⚠️  No relationships found (may be normal for single document)')
" "$DOCUMENT_UUID"
```

**Verification Criteria:**
- Relationships created (if applicable)
- Valid relationship types
- Source and target entities exist

### Phase 1.9: Final Verification

```bash
# Generate comprehensive report
python3 -c "
import sys
from scripts.db import DatabaseManager
from scripts.cache import get_redis_manager
from datetime import datetime

doc_uuid = sys.argv[1]
db = DatabaseManager()
redis = get_redis_manager()
session = next(db.get_session())

print('='*60)
print('TIER 1 SINGLE DOCUMENT TEST - FINAL REPORT')
print('='*60)
print(f'Document UUID: {doc_uuid}')
print(f'Report Generated: {datetime.now()}')
print()

# Document status
doc = session.execute('''
    SELECT * FROM source_documents WHERE document_uuid = %s
''', (doc_uuid,)).fetchone()

print(f'📄 Document Status:')
print(f'   File: {doc.file_name}')
print(f'   Status: {doc.status}')
print(f'   Created: {doc.created_at}')
print(f'   OCR Completed: {doc.ocr_completed_at}')
print()

# Pipeline metrics
metrics = session.execute('''
    SELECT 
        (SELECT COUNT(*) FROM document_chunks WHERE document_uuid = %s) as chunks,
        (SELECT COUNT(*) FROM entity_mentions WHERE document_uuid = %s) as mentions,
        (SELECT COUNT(DISTINCT canonical_entity_uuid) FROM entity_mentions 
         WHERE document_uuid = %s AND canonical_entity_uuid IS NOT NULL) as canonicals
''', (doc_uuid, doc_uuid, doc_uuid)).fetchone()

print(f'📊 Pipeline Metrics:')
print(f'   Text Length: {len(doc.raw_extracted_text or \"\")} characters')
print(f'   Chunks Created: {metrics.chunks}')
print(f'   Entities Extracted: {metrics.mentions}')
print(f'   Canonical Entities: {metrics.canonicals}')
print()

# Success criteria
success_criteria = [
    ('Document in database', doc is not None),
    ('Status is completed', doc.status in ['completed', 'processed']),
    ('Text extracted', len(doc.raw_extracted_text or '') > 100),
    ('Chunks created', metrics.chunks > 0),
    ('Entities extracted', metrics.mentions > 0),
    ('Resolution performed', metrics.canonicals > 0)
]

print(f'✅ Success Criteria:')
all_passed = True
for criterion, passed in success_criteria:
    status = '✅' if passed else '❌'
    print(f'   {status} {criterion}')
    if not passed:
        all_passed = False

print()
if all_passed:
    print('🎉 TIER 1 TEST PASSED! Ready for Tier 2.')
else:
    print('❌ TIER 1 TEST FAILED! Fix issues before proceeding.')

# Save results
with open('tier1_results.json', 'w') as f:
    import json
    json.dump({
        'document_uuid': str(doc_uuid),
        'status': 'passed' if all_passed else 'failed',
        'metrics': {
            'chunks': metrics.chunks,
            'entities': metrics.mentions,
            'canonicals': metrics.canonicals
        }
    }, f, indent=2)
" "$DOCUMENT_UUID"
```

## Tier 2: Small Batch Processing (5 Documents)

### Objective
Process a small batch of related documents to test batch operations and cross-document entity resolution.

### Test Documents
```
input_docs/Paul, Michael (Acuity)/Paul, Michael - Lora Prop Disclosure Stmt 10-21-24.pdf
input_docs/Paul, Michael (Acuity)/Paul, Michael - Plaintiff Acuity Amend Disclosure Stmt 9-23-24.pdf
input_docs/Paul, Michael (Acuity)/Paul, Michael - Plaintiff Acuity Disclosure Stmt 9-20-24.pdf
input_docs/Paul, Michael (Acuity)/Paul, Michael - Riverdale Disclosure Stmt 10-25-24.pdf
input_docs/Paul, Michael (Acuity)/Paul, Michael - Wombat Corp Disclosure Stmt 10-23-24.pdf
```

### Phase 2.1: Create Batch Manifest

```bash
cat > tier2_manifest.json << 'EOF'
{
  "project_name": "TEST_TIER2_BATCH",
  "import_session": "tier2_test_001",
  "documents": [
    {
      "file_path": "input_docs/Paul, Michael (Acuity)/Paul, Michael - Lora Prop Disclosure Stmt 10-21-24.pdf",
      "document_name": "Lora Property Disclosure Statement"
    },
    {
      "file_path": "input_docs/Paul, Michael (Acuity)/Paul, Michael - Plaintiff Acuity Amend Disclosure Stmt 9-23-24.pdf",
      "document_name": "Acuity Amended Disclosure Statement"
    },
    {
      "file_path": "input_docs/Paul, Michael (Acuity)/Paul, Michael - Plaintiff Acuity Disclosure Stmt 9-20-24.pdf",
      "document_name": "Acuity Initial Disclosure Statement"
    },
    {
      "file_path": "input_docs/Paul, Michael (Acuity)/Paul, Michael - Riverdale Disclosure Stmt 10-25-24.pdf",
      "document_name": "Riverdale Disclosure Statement"
    },
    {
      "file_path": "input_docs/Paul, Michael (Acuity)/Paul, Michael - Wombat Corp Disclosure Stmt 10-23-24.pdf",
      "document_name": "Wombat Corp Disclosure Statement"
    }
  ]
}
EOF
```

### Phase 2.2: Submit and Monitor Batch

```bash
# Submit batch
python3 scripts/production_processor.py \
    --manifest tier2_manifest.json \
    --mode async \
    --batch-size 2 \
    --verbose \
    2>&1 | tee tier2_submission.log

# Monitor all documents
python3 -c "
from scripts.db import DatabaseManager
import time

db = DatabaseManager()
project_name = 'TEST_TIER2_BATCH'

while True:
    session = next(db.get_session())
    stats = session.execute('''
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
            SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
            SUM(CASE WHEN status IN ('pending', 'processing') THEN 1 ELSE 0 END) as in_progress
        FROM source_documents sd
        JOIN projects p ON sd.project_fk_id = p.id
        WHERE p.name = %s
    ''', (project_name,)).fetchone()
    
    print(f'\\rBatch Progress: {stats.completed}/{stats.total} completed, ' +
          f'{stats.in_progress} in progress, {stats.failed} failed', end='')
    
    if stats.completed + stats.failed == stats.total:
        print('\\n✅ Batch processing complete!')
        break
        
    time.sleep(10)
    session.close()
"
```

### Phase 2.3: Verify Cross-Document Resolution

```bash
# Check entity overlap
python3 -c "
from scripts.db import DatabaseManager

db = DatabaseManager()
session = next(db.get_session())

# Find entities that appear in multiple documents
shared_entities = session.execute('''
    SELECT 
        ce.canonical_name,
        ce.entity_type,
        COUNT(DISTINCT em.document_uuid) as doc_count,
        COUNT(em.mention_uuid) as total_mentions
    FROM canonical_entities ce
    JOIN entity_mentions em ON em.canonical_entity_uuid = ce.canonical_entity_uuid
    JOIN source_documents sd ON sd.document_uuid = em.document_uuid
    JOIN projects p ON p.id = sd.project_fk_id
    WHERE p.name = 'TEST_TIER2_BATCH'
    GROUP BY ce.canonical_entity_uuid, ce.canonical_name, ce.entity_type
    HAVING COUNT(DISTINCT em.document_uuid) > 1
    ORDER BY doc_count DESC, total_mentions DESC
    LIMIT 10
''').fetchall()

print('📊 Cross-Document Entity Resolution:')
print(f'Entities appearing in multiple documents:')
for entity in shared_entities:
    print(f'  "{entity.canonical_name}" ({entity.entity_type}): ' +
          f'{entity.doc_count} docs, {entity.total_mentions} total mentions')

if len(shared_entities) > 0:
    print('\\n✅ Cross-document resolution working!')
else:
    print('\\n⚠️  No shared entities found')
"
```

**Tier 2 Success Criteria:**
- All 5 documents processed successfully
- Batch operations handle concurrent processing
- Common entities resolved across documents
- No resource exhaustion or timeouts

## Tier 3: Medium Batch Processing (20 Documents)

### Objective
Test system performance with medium-sized batch, including error handling and recovery.

### Implementation
1. Include documents from multiple subdirectories
2. Test worker scaling
3. Monitor resource usage
4. Verify error recovery mechanisms

## Tier 4: Large Batch Processing (100 Documents)

### Objective
Test production-scale processing with performance monitoring and optimization.

### Key Metrics to Monitor
- Processing throughput (docs/hour)
- Memory usage patterns
- Database connection pooling
- Redis cache hit rates
- S3 upload performance

## Tier 5: Production Simulation (Full Load)

### Objective
Simulate actual production workload with mixed document types and sizes.

### Test Scenarios
1. Mixed file sizes (small to large PDFs)
2. Concurrent project processing
3. System recovery from failures
4. Performance under sustained load

## Monitoring and Verification Tools

### Real-time Pipeline Monitor
```bash
# Start monitoring dashboard
python3 scripts/cli/monitor.py live --refresh 5
```

### Document Status Checker
```bash
# Check specific document
python3 scripts/check_doc_status.py <document_uuid>
```

### Database Health Monitor
```bash
# Monitor database metrics
python3 -c "
from scripts.db import DatabaseManager
db = DatabaseManager()
session = next(db.get_session())

stats = session.execute('''
    SELECT 
        (SELECT COUNT(*) FROM source_documents) as total_docs,
        (SELECT COUNT(*) FROM document_chunks) as total_chunks,
        (SELECT COUNT(*) FROM entity_mentions) as total_mentions,
        (SELECT COUNT(*) FROM canonical_entities) as total_canonicals,
        (SELECT COUNT(*) FROM relationship_staging) as total_relationships,
        (SELECT pg_database_size(current_database())/1024/1024) as db_size_mb
''').fetchone()

print('📊 Database Statistics:')
for key, value in stats._mapping.items():
    print(f'   {key}: {value:,}')
"
```

## Error Recovery Procedures

### Failed OCR Recovery
```bash
# Retry failed OCR
python3 scripts/retry_textract.py --document-uuid <uuid> --force
```

### Failed Entity Extraction Recovery
```bash
# Retry entity extraction
python3 dev_tools/manual_ops/retry_entity_extraction.py --document-uuid <uuid>
```

### Clear Cache for Document
```bash
python3 -c "
from scripts.cache import get_redis_manager
import sys
redis = get_redis_manager()
doc_uuid = sys.argv[1]
keys = redis.client.keys(f'*{doc_uuid}*')
for key in keys:
    redis.client.delete(key)
print(f'Cleared {len(keys)} cache entries')
" <document_uuid>
```

## Success Metrics

### Per-Document Metrics
- OCR completion time: < 60 seconds
- Entity extraction: > 10 entities per page average
- Resolution rate: > 70% of entities resolved
- End-to-end time: < 5 minutes

### Batch Processing Metrics
- Throughput: > 100 documents/hour
- Error rate: < 5%
- Resource usage: < 80% CPU, < 70% memory
- Database connections: < 50 concurrent

## Rollback Procedures

### Tier 1 Rollback
```bash
# Remove test document
python3 -c "
from scripts.db import DatabaseManager
project_name = 'TEST_TIER1_SINGLE_DOC'
db = DatabaseManager()
session = next(db.get_session())
session.execute('DELETE FROM projects WHERE name = %s', (project_name,))
session.commit()
print('✅ Tier 1 test data removed')
"
```

### Complete Test Data Cleanup
```bash
# Remove all test data
python3 -c "
from scripts.db import DatabaseManager
db = DatabaseManager()
session = next(db.get_session())

# Remove test projects and cascade
test_projects = [
    'TEST_TIER1_SINGLE_DOC',
    'TEST_TIER2_BATCH',
    'TEST_TIER3_MEDIUM',
    'TEST_TIER4_LARGE',
    'TEST_TIER5_PRODUCTION'
]

for project in test_projects:
    result = session.execute(
        'DELETE FROM projects WHERE name = %s RETURNING id', 
        (project,)
    ).fetchone()
    if result:
        print(f'✅ Removed project: {project}')

session.commit()
print('\\n✅ All test data cleaned up')
"
```

## Implementation Notes

1. **Always use production scripts** - Never bypass the standard workflow
2. **Monitor at every stage** - Use provided verification queries
3. **Document issues immediately** - Create detailed error logs
4. **Test incrementally** - Don't skip tiers
5. **Verify data integrity** - Check database consistency after each tier

## Automation Script Template

```python
#!/usr/bin/env python3
"""
Automated test executor for Tier N
"""
import subprocess
import json
import time
import sys
from pathlib import Path

class TierNTester:
    def __init__(self, tier_number):
        self.tier = tier_number
        self.results = []
        
    def run_command(self, cmd, description):
        """Execute command and capture results"""
        print(f"\\n🔄 {description}")
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        
        self.results.append({
            'command': cmd,
            'description': description,
            'returncode': result.returncode,
            'stdout': result.stdout,
            'stderr': result.stderr,
            'timestamp': time.time()
        })
        
        if result.returncode != 0:
            print(f"❌ Failed: {result.stderr}")
            return False
        
        print(f"✅ Success")
        return True
    
    def verify_criteria(self, criteria_func):
        """Run verification function"""
        try:
            result = criteria_func()
            self.results.append({
                'verification': criteria_func.__name__,
                'result': result,
                'timestamp': time.time()
            })
            return result
        except Exception as e:
            print(f"❌ Verification failed: {e}")
            return False
    
    def save_results(self):
        """Save test results"""
        filename = f"tier{self.tier}_results_{int(time.time())}.json"
        with open(filename, 'w') as f:
            json.dump(self.results, f, indent=2)
        print(f"\\n📄 Results saved to {filename}")

# Usage
if __name__ == "__main__":
    tester = TierNTester(1)
    
    # Run test phases
    if not tester.run_command("source load_env.sh", "Loading environment"):
        sys.exit(1)
        
    # Add more test phases...
    
    tester.save_results()
```

## Conclusion

This testing plan provides a systematic approach to validating the legal document processing pipeline. Starting with a single document and progressively increasing complexity ensures that issues are caught early and the system is thoroughly validated before production use. The detailed verification criteria and implementation guidance enable autonomous execution while maintaining quality and reliability standards.