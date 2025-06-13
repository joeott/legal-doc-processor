# Context 184: Single Document End-to-End Test Checklist

## Overview
This checklist provides a comprehensive step-by-step guide for testing a single document through the entire legal document processing pipeline, from intake to Neo4j export.

## Pre-Test Setup

### 1. Environment Verification
```bash
# Verify environment variables
cd /Users/josephott/Documents/phase_1_2_3_process_v5
grep -E "SUPABASE_URL|OPENAI_API_KEY|AWS_ACCESS_KEY|REDIS_HOST" .env | wc -l
# Expected: 4 or more lines
```

### 2. Clean Database State
```bash
# Run full cleanup script
python scripts/recovery/full_cleanup.py

# Verify cleanup
python scripts/recovery/quick_status_check.py
# Expected: All documents in "pending" status, no chunks, no entities
```

### 3. Clear Redis Cache
```bash
python -c "
from scripts.redis_utils import get_redis_manager
redis_manager = get_redis_manager()
client = redis_manager.get_client()
# Clear queues
for q in ['ocr', 'text', 'embeddings', 'graph', 'default']:
    client.delete(f'celery:queue:{q}')
print('Redis queues cleared')
"
```

### 4. Verify Workers Running
```bash
# Check worker status
celery -A scripts.celery_app inspect active

# Expected output should show 5 nodes:
# - ocr@Mac
# - text@Mac
# - embeddings@Mac
# - graph@Mac
# - general@Mac
```

## Document Selection and Submission

### 5. Select Test Document
```bash
# Choose a PDF document
TEST_FILE="input/Paul, Michael (Acuity)/Paul, Michael - Plaintiff Acuity Amend Disclosure Stmt 9-23-24.pdf"

# Verify file exists
ls -la "$TEST_FILE"
```

### 6. Submit Document
```bash
# Submit using test script
python scripts/legacy/testing/test_single_document.py "$TEST_FILE"

# Capture the document UUID from output
# Example: ✅ Document created: ID=1463, UUID=46601ab9-1926-49ca-b533-210d4f0a5181
DOCUMENT_UUID="[PASTE UUID HERE]"
```

## Stage-by-Stage Verification

### 7. Stage 1: Intake Verification (0-5 seconds)
```bash
# Check initial status
python -c "
from scripts.supabase_utils import get_supabase_client
client = get_supabase_client()
doc = client.table('source_documents').select('*').eq('document_uuid', '$DOCUMENT_UUID').single().execute()
print(f'Status: {doc.data[\"initial_processing_status\"]}')
print(f'Task ID: {doc.data.get(\"celery_task_id\")}')
"
```
✅ **Success Criteria**: Status should change from "pending_intake" to "pending_ocr"

### 8. Stage 2: OCR Processing (5-30 seconds for Textract)
```bash
# Monitor OCR progress
python -c "
import time
from scripts.supabase_utils import get_supabase_client
client = get_supabase_client()
for i in range(10):
    doc = client.table('source_documents').select('*').eq('document_uuid', '$DOCUMENT_UUID').single().execute()
    status = doc.data['initial_processing_status']
    print(f'Check {i+1}: {status}')
    if status != 'pending_ocr':
        break
    time.sleep(3)
"
```
✅ **Success Criteria**: Status should change to "pending_text_processing"

### 9. Verify OCR Output
```bash
# Check OCR cache
python -c "
from scripts.redis_utils import get_redis_manager
from scripts.cache_keys import CacheKeys
redis_manager = get_redis_manager()
key = CacheKeys.ocr_result('$DOCUMENT_UUID')
result = redis_manager.get_cached_value(key)
if result:
    print(f'OCR text length: {len(result.get(\"text\", \"\"))} characters')
else:
    print('No OCR cache found')
"
```
✅ **Success Criteria**: OCR cache should contain extracted text

### 10. Stage 3: Text Processing & Chunking (2-5 seconds)
```bash
# Check chunk creation
python -c "
from scripts.supabase_utils import get_supabase_client
client = get_supabase_client()
chunks = client.table('neo4j_chunks').select('*').eq('document_uuid', '$DOCUMENT_UUID').execute()
print(f'Chunks created: {len(chunks.data)}')
for i, chunk in enumerate(chunks.data[:3]):
    print(f'  Chunk {i+1}: {len(chunk[\"content\"])} chars')
"
```
✅ **Success Criteria**: 
- Multiple chunks created (typically 5-20 for a legal document)
- Each chunk should have content, embeddings_metadata

### 11. Stage 4: Entity Extraction (10-30 seconds)
```bash
# Monitor entity extraction
python -c "
from scripts.supabase_utils import get_supabase_client
client = get_supabase_client()
# Check document status
doc = client.table('source_documents').select('initial_processing_status').eq('document_uuid', '$DOCUMENT_UUID').single().execute()
print(f'Document status: {doc.data[\"initial_processing_status\"]}')
# Check entities
entities = client.table('neo4j_entity_mentions').select('*').eq('document_uuid', '$DOCUMENT_UUID').execute()
print(f'Entities extracted: {len(entities.data)}')
"
```
✅ **Success Criteria**: 
- Status should progress to "pending_graph_creation"
- Multiple entities extracted (persons, organizations, locations, etc.)

### 12. Stage 5: Neo4j Document Node Creation
```bash
# Check document node
python -c "
from scripts.supabase_utils import get_supabase_client
client = get_supabase_client()
doc_node = client.table('neo4j_documents').select('*').eq('document_uuid', '$DOCUMENT_UUID').execute()
if doc_node.data:
    print(f'Document node created: {doc_node.data[0][\"title\"]}')
else:
    print('No document node found')
"
```
✅ **Success Criteria**: Document node created with metadata

### 13. Final Status Check
```bash
# Verify completion
python -c "
from scripts.supabase_utils import get_supabase_client
client = get_supabase_client()
doc = client.table('source_documents').select('*').eq('document_uuid', '$DOCUMENT_UUID').single().execute()
print(f'Final status: {doc.data[\"initial_processing_status\"]}')
if doc.data.get('error_message'):
    print(f'Error: {doc.data[\"error_message\"]}')
"
```
✅ **Success Criteria**: Status should be "completed"

## Error Troubleshooting

### If Document Stuck in "pending_ocr":
1. Check OCR worker logs:
   ```bash
   tail -100 logs/celery-ocr-*.log | grep -E "ERROR|WARNING|$DOCUMENT_UUID"
   ```

2. Verify S3 access:
   ```bash
   aws s3 ls s3://your-bucket-name/documents/
   ```

3. Check MIME type issue:
   ```bash
   python -c "
   from scripts.supabase_utils import get_supabase_client
   client = get_supabase_client()
   doc = client.table('source_documents').select('detected_file_type').eq('document_uuid', '$DOCUMENT_UUID').single().execute()
   print(f'File type: {doc.data[\"detected_file_type\"]}')
   "
   ```

### If Document Stuck in "pending_text_processing":
1. Check text worker logs:
   ```bash
   tail -100 logs/celery-text-*.log | grep -E "ERROR|WARNING|$DOCUMENT_UUID"
   ```

2. Verify OCR output exists:
   ```bash
   python -c "
   from scripts.celery_tasks.text_tasks import create_document_node
   # Check if task can access OCR result
   "
   ```

### Common Issues and Fixes:
1. **MIME type error**: Ensure `ocr_tasks.py` has MIME-to-extension conversion
2. **S3 access error**: Verify AWS credentials and bucket permissions
3. **Worker not picking up tasks**: Restart workers with `./scripts/stop_celery_workers.sh && ./scripts/start_celery_workers.sh`
4. **Redis connection issues**: Check Redis connection with `redis-cli ping`

## Success Metrics

A successful single document test should show:
1. **Total processing time**: 30-60 seconds for a typical legal PDF
2. **All stages completed**: Document progresses through all status states
3. **Data created**:
   - 1 document node in `neo4j_documents`
   - 5-20 chunks in `neo4j_chunks`
   - 10-50 entity mentions in `neo4j_entity_mentions`
   - Cached OCR result in Redis
4. **No errors**: `error_message` field remains null

## Next Steps After Success

1. Run multiple document test:
   ```bash
   python scripts/legacy/testing/test_multiple_documents.py --batch-size 5
   ```

2. Test error recovery:
   ```bash
   # Submit invalid file type
   python scripts/legacy/testing/test_single_document.py "test.xyz"
   ```

3. Test reprocessing:
   ```bash
   # Reprocess same document
   python scripts/legacy/testing/test_single_document.py "$TEST_FILE" --force-reprocess
   ```

## Monitoring During Test

Keep these monitoring tools running in separate terminals:

1. **Live Monitor**:
   ```bash
   python scripts/cli/monitor.py live
   ```

2. **Flower Dashboard**:
   ```bash
   # Access at http://localhost:5555
   celery -A scripts.celery_app flower
   ```

3. **Worker Logs**:
   ```bash
   tail -f logs/celery-*.log | grep -E "ERROR|WARNING|Processing|Completed"
   ```

## Test Report Template

After completing the test, document results:

```
Test Date: [DATE]
Document: [FILENAME]
Document UUID: [UUID]

Stage Results:
- Intake: ✅/❌ [TIME]
- OCR: ✅/❌ [TIME] 
- Text Processing: ✅/❌ [TIME]
- Entity Extraction: ✅/❌ [TIME]
- Graph Creation: ✅/❌ [TIME]

Total Time: [TOTAL]
Chunks Created: [COUNT]
Entities Extracted: [COUNT]

Issues Encountered:
- [Issue 1]
- [Issue 2]

Resolution Steps:
- [Step 1]
- [Step 2]
```

## Verification Script

Save this as `verify_single_doc.py` for quick checks:

```python
#!/usr/bin/env python3
import sys
import time
from scripts.supabase_utils import get_supabase_client
from scripts.redis_utils import get_redis_manager
from scripts.cache_keys import CacheKeys

def verify_document(doc_uuid):
    client = get_supabase_client()
    redis_manager = get_redis_manager()
    
    # Get document
    doc = client.table('source_documents').select('*').eq('document_uuid', doc_uuid).single().execute()
    print(f"Document: {doc.data['original_file_name']}")
    print(f"Status: {doc.data['initial_processing_status']}")
    
    # Check chunks
    chunks = client.table('neo4j_chunks').select('chunk_uuid').eq('document_uuid', doc_uuid).execute()
    print(f"Chunks: {len(chunks.data)}")
    
    # Check entities
    entities = client.table('neo4j_entity_mentions').select('entity_name').eq('document_uuid', doc_uuid).execute()
    print(f"Entities: {len(entities.data)}")
    
    # Check cache
    ocr_cache = redis_manager.get_cached_value(CacheKeys.ocr_result(doc_uuid))
    print(f"OCR Cache: {'Found' if ocr_cache else 'Missing'}")
    
    # Check document node
    doc_node = client.table('neo4j_documents').select('title').eq('document_uuid', doc_uuid).execute()
    print(f"Document Node: {'Created' if doc_node.data else 'Missing'}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        verify_document(sys.argv[1])
    else:
        print("Usage: python verify_single_doc.py <document_uuid>")
```

This checklist ensures thorough testing of each pipeline stage and provides clear troubleshooting steps for common issues.