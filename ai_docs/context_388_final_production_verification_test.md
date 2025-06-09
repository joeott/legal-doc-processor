# Context 388: Final Production Verification Test - Complete System Reset and Validation

## Date: 2025-06-04 09:30

### 🎯 MISSION: Execute Complete Production Verification with Database Reset

## Executive Summary

This document provides step-by-step instructions for an agentic coding tool to perform a complete production verification test. This includes resetting the database, processing all 201 Paul, Michael (Acuity) documents with our enhanced system, and validating output at each pipeline stage.

## 📋 PHASE 1: Database Reset and Preparation

### Step 1.1: Stop All Workers
```bash
# Kill any existing Celery workers
ps aux | grep "[c]elery" | awk '{print $2}' | xargs -r kill -9

# Verify workers stopped
ps aux | grep celery
# Expected: No celery processes running
```

### Step 1.2: Clear Redis Cache
```bash
# Clear all Redis keys (WARNING: This removes all cached data)
redis-cli FLUSHDB

# Verify Redis is empty
redis-cli DBSIZE
# Expected output: (integer) 0
```

### Step 1.3: Reset Database Tables
```sql
-- Connect to database
psql -h localhost -p 5433 -U app_user -d legal_doc_processing

-- Delete all processing data (maintain schema)
TRUNCATE TABLE 
    source_documents,
    document_chunks,
    entity_mentions,
    canonical_entities,
    relationship_staging,
    processing_tasks,
    textract_jobs
CASCADE;

-- Verify empty tables
SELECT 
    schemaname,
    tablename,
    n_live_tup as row_count
FROM pg_stat_user_tables
WHERE schemaname = 'public'
ORDER BY tablename;
-- Expected: All tables should have 0 rows
```

### Step 1.4: Start Fresh Workers
```bash
# Start Celery workers with all queues
celery -A scripts.celery_app worker \
    --loglevel=info \
    --queues=default,ocr,text,entity,graph,cleanup \
    --concurrency=8 \
    --pool=prefork &

# Verify workers started
sleep 5
celery -A scripts.celery_app inspect active
# Expected: Empty active tasks list
```

## 📋 PHASE 2: Process All Documents with Enhanced System

### Step 2.1: Prepare Document Manifest
```python
#!/usr/bin/env python3
# create_production_manifest.py

import json
import uuid
from pathlib import Path

# Load discovered documents
with open('paul_michael_discovery_20250604_032359.json', 'r') as f:
    discovery = json.load(f)

# Create processing manifest with all 201 documents
manifest = {
    'id': f'production_test_{datetime.now().strftime("%Y%m%d_%H%M%S")}',
    'name': 'Final Production Verification Test',
    'project_uuid': 'paul-michael-acuity-prod-test',
    'documents': []
}

for doc in discovery['documents']:
    manifest['documents'].append({
        'document_uuid': str(uuid.uuid4()),
        'file_path': doc['file_path'],
        'project_uuid': manifest['project_uuid'],
        'metadata': {
            'original_filename': doc['filename'],
            'size_mb': doc['size_mb'],
            'sha256': doc['sha256'],
            'category': doc.get('category', 'unknown')
        }
    })

# Save manifest
output_path = f'production_test_manifest_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
with open(output_path, 'w') as f:
    json.dump(manifest, f, indent=2)

print(f"Created manifest with {len(manifest['documents'])} documents")
print(f"Saved to: {output_path}")
```

### Step 2.2: Start Processing with Monitoring
```python
#!/usr/bin/env python3
# run_production_test.py

import json
import time
from datetime import datetime
from scripts.pdf_tasks import process_pdf_batch, create_document_batches
from scripts.cli.monitor import ProductionMonitor

# Load manifest
manifest_path = 'production_test_manifest_[TIMESTAMP].json'
with open(manifest_path, 'r') as f:
    manifest = json.load(f)

# Initialize monitoring
monitor = ProductionMonitor()
monitor.start_test(manifest['id'], len(manifest['documents']))

# Create optimal batches (10 documents per batch)
batches = create_document_batches(manifest['documents'], batch_size=10)
print(f"Processing {len(manifest['documents'])} documents in {len(batches)} batches")

# Process each batch with parallel workers
start_time = time.time()
all_results = []

for i, batch in enumerate(batches):
    print(f"\n{'='*60}")
    print(f"Processing Batch {i+1}/{len(batches)} ({len(batch)} documents)")
    print(f"{'='*60}")
    
    # Process batch with 5 concurrent workers
    batch_result = process_pdf_batch.apply_async(
        args=[batch, 5]  # 5 concurrent workers per batch
    ).get(timeout=600)  # 10 minute timeout per batch
    
    all_results.append(batch_result)
    
    # Update monitor
    monitor.update_batch_complete(i+1, batch_result)
    
    # Show progress
    elapsed = time.time() - start_time
    docs_processed = (i + 1) * 10
    rate = docs_processed / (elapsed / 3600) if elapsed > 0 else 0
    eta_hours = (len(manifest['documents']) - docs_processed) / rate if rate > 0 else 0
    
    print(f"Progress: {docs_processed}/{len(manifest['documents'])} documents")
    print(f"Success Rate: {monitor.get_success_rate():.1f}%")
    print(f"Throughput: {rate:.1f} documents/hour")
    print(f"ETA: {eta_hours:.1f} hours")

# Final statistics
total_time = time.time() - start_time
final_stats = monitor.get_final_statistics()

print(f"\n{'='*60}")
print(f"PRODUCTION TEST COMPLETE")
print(f"{'='*60}")
print(f"Total Documents: {final_stats['total_documents']}")
print(f"Successful: {final_stats['successful']} ({final_stats['success_rate']:.1f}%)")
print(f"Failed: {final_stats['failed']}")
print(f"Total Time: {total_time/60:.1f} minutes")
print(f"Average Throughput: {final_stats['avg_throughput']:.1f} documents/hour")
print(f"{'='*60}")

# Save results
with open(f'production_test_results_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json', 'w') as f:
    json.dump({
        'manifest_id': manifest['id'],
        'statistics': final_stats,
        'batch_results': all_results
    }, f, indent=2)
```

### Step 2.3: Monitor Real-Time Progress
```bash
# In a separate terminal, run live monitoring
python scripts/cli/monitor.py live

# Or watch specific metrics
watch -n 5 'redis-cli get "batch:processing:*" | jq .'

# Monitor worker activity
watch -n 2 'celery -A scripts.celery_app inspect active'

# Check database population
watch -n 10 'psql -h localhost -p 5433 -U app_user -d legal_doc_processing -c "
SELECT 
    '\''source_documents'\'' as table_name, COUNT(*) as count FROM source_documents
UNION ALL
SELECT '\''document_chunks'\'', COUNT(*) FROM document_chunks  
UNION ALL
SELECT '\''entity_mentions'\'', COUNT(*) FROM entity_mentions
UNION ALL
SELECT '\''canonical_entities'\'', COUNT(*) FROM canonical_entities
UNION ALL
SELECT '\''textract_jobs'\'', COUNT(*) FROM textract_jobs;"'
```

## 📋 PHASE 3: Pipeline Stage Validation

### Step 3.1: Verify OCR/Text Extraction Stage
```sql
-- Random sample of extracted text
SELECT 
    document_uuid,
    original_file_name,
    LENGTH(raw_extracted_text) as text_length,
    LEFT(raw_extracted_text, 200) as text_preview,
    ocr_provider,
    page_count,
    textract_confidence,
    ocr_completed_at
FROM source_documents
WHERE raw_extracted_text IS NOT NULL
ORDER BY RANDOM()
LIMIT 5;

-- Verify all documents have text
SELECT 
    COUNT(*) as total_documents,
    COUNT(raw_extracted_text) as documents_with_text,
    COUNT(CASE WHEN LENGTH(raw_extracted_text) > 100 THEN 1 END) as substantial_text,
    AVG(LENGTH(raw_extracted_text)) as avg_text_length,
    MIN(textract_confidence) as min_confidence,
    AVG(textract_confidence) as avg_confidence
FROM source_documents;
```

### Step 3.2: Verify Chunking Stage
```sql
-- Random sample of chunks
SELECT 
    dc.chunk_uuid,
    dc.document_uuid,
    dc.chunk_index,
    LENGTH(dc.text) as chunk_length,
    LEFT(dc.text, 150) as chunk_preview,
    sd.original_file_name
FROM document_chunks dc
JOIN source_documents sd ON dc.document_uuid = sd.document_uuid
ORDER BY RANDOM()
LIMIT 5;

-- Chunk statistics
SELECT 
    sd.document_uuid,
    sd.original_file_name,
    COUNT(dc.chunk_uuid) as chunk_count,
    AVG(LENGTH(dc.text)) as avg_chunk_size,
    SUM(LENGTH(dc.text)) as total_text_length
FROM source_documents sd
LEFT JOIN document_chunks dc ON sd.document_uuid = dc.document_uuid
GROUP BY sd.document_uuid, sd.original_file_name
ORDER BY RANDOM()
LIMIT 10;
```

### Step 3.3: Verify Entity Extraction Stage
```sql
-- Random sample of entities
SELECT 
    em.entity_text,
    em.entity_type,
    em.confidence_score,
    sd.original_file_name,
    dc.chunk_index
FROM entity_mentions em
JOIN document_chunks dc ON em.chunk_uuid = dc.chunk_uuid
JOIN source_documents sd ON em.document_uuid = sd.document_uuid
ORDER BY RANDOM()
LIMIT 10;

-- Entity type distribution
SELECT 
    entity_type,
    COUNT(*) as count,
    AVG(confidence_score) as avg_confidence
FROM entity_mentions
GROUP BY entity_type
ORDER BY count DESC;

-- Documents with most entities
SELECT 
    sd.original_file_name,
    COUNT(DISTINCT em.mention_uuid) as entity_count,
    COUNT(DISTINCT em.entity_type) as unique_types
FROM source_documents sd
JOIN entity_mentions em ON sd.document_uuid = em.document_uuid
GROUP BY sd.document_uuid, sd.original_file_name
ORDER BY entity_count DESC
LIMIT 5;
```

### Step 3.4: Verify Entity Resolution Stage
```sql
-- Random sample of canonical entities
SELECT 
    ce.canonical_name,
    ce.entity_type,
    ce.mention_count,
    ce.confidence_score,
    ce.resolution_method,
    ARRAY_AGG(DISTINCT em.entity_text) as variations
FROM canonical_entities ce
JOIN entity_mentions em ON ce.canonical_entity_uuid = em.canonical_entity_uuid
GROUP BY ce.canonical_entity_uuid, ce.canonical_name, ce.entity_type, 
         ce.mention_count, ce.confidence_score, ce.resolution_method
ORDER BY RANDOM()
LIMIT 10;

-- Resolution effectiveness
SELECT 
    COUNT(DISTINCT ce.canonical_entity_uuid) as unique_entities,
    COUNT(DISTINCT em.mention_uuid) as total_mentions,
    CAST(COUNT(DISTINCT em.mention_uuid) AS FLOAT) / COUNT(DISTINCT ce.canonical_entity_uuid) as avg_mentions_per_entity
FROM canonical_entities ce
JOIN entity_mentions em ON ce.canonical_entity_uuid = em.canonical_entity_uuid;
```

### Step 3.5: Verify Relationship Building Stage
```sql
-- Sample relationships
SELECT 
    rs.subject_id,
    ce1.canonical_name as subject_name,
    rs.relationship_type,
    rs.object_id,
    ce2.canonical_name as object_name,
    rs.confidence_score,
    sd.original_file_name
FROM relationship_staging rs
JOIN canonical_entities ce1 ON rs.subject_id = ce1.canonical_entity_uuid
JOIN canonical_entities ce2 ON rs.object_id = ce2.canonical_entity_uuid
JOIN source_documents sd ON rs.document_uuid = sd.document_uuid
ORDER BY RANDOM()
LIMIT 10;

-- Relationship statistics
SELECT 
    relationship_type,
    COUNT(*) as count,
    AVG(confidence_score) as avg_confidence
FROM relationship_staging
GROUP BY relationship_type
ORDER BY count DESC;
```

## 📋 PHASE 4: System Performance Validation

### Step 4.1: Processing Performance Metrics
```sql
-- Document processing times
SELECT 
    sd.original_file_name,
    sd.file_size_bytes / 1048576.0 as size_mb,
    sd.page_count,
    EXTRACT(EPOCH FROM (sd.ocr_completed_at - sd.created_at)) as ocr_time_seconds,
    tj.job_status,
    tj.confidence_score
FROM source_documents sd
LEFT JOIN textract_jobs tj ON sd.document_uuid = tj.document_uuid
ORDER BY sd.file_size_bytes DESC
LIMIT 10;

-- Large file handling verification
SELECT 
    original_file_name,
    file_size_bytes / 1048576.0 as size_mb,
    page_count,
    ocr_provider,
    CASE 
        WHEN file_size_bytes > 500 * 1048576 THEN 'LARGE FILE - SPLIT'
        ELSE 'Normal Processing'
    END as processing_method
FROM source_documents
WHERE file_size_bytes > 100 * 1048576  -- Files over 100MB
ORDER BY file_size_bytes DESC;
```

### Step 4.2: Error Analysis
```sql
-- Check for any failures
SELECT 
    pt.task_name,
    pt.status,
    pt.error_message,
    pt.retry_count,
    sd.original_file_name
FROM processing_tasks pt
JOIN source_documents sd ON pt.document_uuid = sd.document_uuid
WHERE pt.status IN ('failed', 'error')
ORDER BY pt.created_at DESC;

-- Retry success analysis
SELECT 
    task_name,
    COUNT(CASE WHEN retry_count = 0 THEN 1 END) as first_attempt_success,
    COUNT(CASE WHEN retry_count > 0 AND status = 'completed' THEN 1 END) as retry_success,
    COUNT(CASE WHEN status = 'failed' THEN 1 END) as failed,
    MAX(retry_count) as max_retries
FROM processing_tasks
GROUP BY task_name;
```

## 📋 PHASE 5: Final Validation Report

### Step 5.1: Generate Comprehensive Report
```python
#!/usr/bin/env python3
# generate_validation_report.py

import psycopg2
import json
from datetime import datetime

# Database connection
conn = psycopg2.connect(
    host='localhost',
    port=5433,
    database='legal_doc_processing',
    user='app_user',
    password='your_password'
)

def execute_query(query):
    with conn.cursor() as cur:
        cur.execute(query)
        return cur.fetchall()

# Collect all validation metrics
report = {
    'test_date': datetime.now().isoformat(),
    'summary': {},
    'stage_validation': {},
    'performance_metrics': {},
    'sample_outputs': {}
}

# Overall summary
summary_query = """
SELECT 
    (SELECT COUNT(*) FROM source_documents) as total_documents,
    (SELECT COUNT(*) FROM source_documents WHERE raw_extracted_text IS NOT NULL) as documents_with_text,
    (SELECT COUNT(*) FROM document_chunks) as total_chunks,
    (SELECT COUNT(*) FROM entity_mentions) as total_entity_mentions,
    (SELECT COUNT(*) FROM canonical_entities) as unique_entities,
    (SELECT COUNT(*) FROM relationship_staging) as total_relationships,
    (SELECT COUNT(*) FROM processing_tasks WHERE status = 'failed') as failed_tasks
"""
summary = execute_query(summary_query)[0]
report['summary'] = {
    'total_documents': summary[0],
    'documents_with_text': summary[1],
    'text_extraction_rate': (summary[1] / summary[0] * 100) if summary[0] > 0 else 0,
    'total_chunks': summary[2],
    'total_entity_mentions': summary[3],
    'unique_entities': summary[4],
    'total_relationships': summary[5],
    'failed_tasks': summary[6]
}

# Performance metrics
perf_query = """
SELECT 
    AVG(EXTRACT(EPOCH FROM (ocr_completed_at - created_at))) as avg_ocr_time,
    MIN(textract_confidence) as min_confidence,
    AVG(textract_confidence) as avg_confidence,
    MAX(file_size_bytes) / 1048576.0 as max_file_size_mb,
    COUNT(CASE WHEN file_size_bytes > 500 * 1048576 THEN 1 END) as large_files_processed
FROM source_documents
WHERE ocr_completed_at IS NOT NULL
"""
perf = execute_query(perf_query)[0]
report['performance_metrics'] = {
    'avg_ocr_time_seconds': round(perf[0], 2) if perf[0] else None,
    'min_confidence': round(perf[1], 3) if perf[1] else None,
    'avg_confidence': round(perf[2], 3) if perf[2] else None,
    'max_file_size_mb': round(perf[3], 2) if perf[3] else None,
    'large_files_processed': perf[4]
}

# Save report
report_path = f'production_validation_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
with open(report_path, 'w') as f:
    json.dump(report, f, indent=2)

print(f"\n{'='*60}")
print("PRODUCTION VALIDATION REPORT")
print(f"{'='*60}")
print(f"Documents Processed: {report['summary']['total_documents']}")
print(f"Text Extraction Rate: {report['summary']['text_extraction_rate']:.1f}%")
print(f"Entities Extracted: {report['summary']['total_entity_mentions']}")
print(f"Unique Entities: {report['summary']['unique_entities']}")
print(f"Relationships Built: {report['summary']['total_relationships']}")
print(f"Failed Tasks: {report['summary']['failed_tasks']}")
print(f"\nAverage OCR Time: {report['performance_metrics']['avg_ocr_time_seconds']} seconds")
print(f"Average Confidence: {report['performance_metrics']['avg_confidence']:.3f}")
print(f"Large Files Handled: {report['performance_metrics']['large_files_processed']}")
print(f"{'='*60}")
print(f"\nFull report saved to: {report_path}")

conn.close()
```

## 📋 SUCCESS CRITERIA

### Must Pass (Any Failure = Investigation Required)
- [ ] All 201 documents successfully uploaded to S3
- [ ] ≥99% documents have extracted text
- [ ] Zero data corruption events
- [ ] All large files (>500MB) processed successfully
- [ ] Average confidence score >0.95

### Performance Targets
- [ ] Total processing time <15 minutes
- [ ] Throughput >1000 documents/hour
- [ ] <1% retry rate
- [ ] Memory usage <8GB
- [ ] No worker crashes

### Data Quality Validation
- [ ] >50,000 entities extracted
- [ ] >10,000 unique canonical entities
- [ ] >5,000 relationships identified
- [ ] Entity resolution rate >3:1
- [ ] All pipeline stages populated

## 🔍 TROUBLESHOOTING GUIDE

### If Documents Fail
```bash
# Check specific document status
python scripts/check_doc_status.py

# View error details
psql -c "SELECT * FROM processing_tasks WHERE status = 'failed' ORDER BY created_at DESC LIMIT 10;"

# Check Textract job status
python scripts/check_celery_task_status.py <task_id>
```

### If Performance Is Slow
```bash
# Check worker utilization
celery -A scripts.celery_app inspect stats

# Monitor Redis performance
redis-cli --latency

# Check database locks
psql -c "SELECT * FROM pg_stat_activity WHERE state = 'active';"
```

### If Data Is Missing
```bash
# Verify Redis state
redis-cli keys "doc:*" | wc -l

# Check incomplete tasks
celery -A scripts.celery_app inspect reserved

# Verify database foreign keys
psql -c "\d+ source_documents"
```

## 🎯 EXPECTED OUTCOMES

### Quantitative Results
- 201 documents processed
- ~99% success rate (199-201 successful)
- <15 minutes total processing time
- >50,000 entities extracted
- >5,000 relationships identified

### Qualitative Validation
- Large files handled seamlessly
- Retry logic prevents transient failures
- Text persistence enables full pipeline
- Parallel processing achieves target throughput
- Monitoring provides complete visibility

### Human Impact Demonstrated
- 47 minutes → <15 minutes (68% time reduction)
- 8 manual failures → 0-2 failures (75-100% reduction)
- 256 docs/hour → 1000+ docs/hour (4x improvement)
- Manual intervention → Fully automated

---

*"This final test proves not just that the system works, but that it works reliably, at scale, with real-world complexity. Every enhancement has measurable impact."*