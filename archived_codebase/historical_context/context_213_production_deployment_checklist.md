
# Context 213: Production Deployment End-to-End Checklist

## Date: 2025-05-30

## Reference
**Infrastructure Status**: context_209_production_verification_status.md (Production Ready)
**Schema Compliance**: context_211_schema_verification_complete.md
**Service Verification**: context_212_redis_authentication_issue.md (Resolved)

## Executive Summary

This checklist provides a step-by-step procedure for validating production deployment by processing a single document from `/input/` through the complete legal document processing pipeline. This end-to-end test confirms all systems are operational before scaling to the full 450+ document workload.

## Pre-Deployment Verification

### ✅ Infrastructure Readiness Check
```bash
# Verify all services are operational
python scripts/cli/admin.py verify-services
# Expected: ✓ Supabase, ✓ Redis, ✓ S3, ✓ OpenAI

# Verify schema compliance
python scripts/cli/admin.py verify-schema
# Expected: ✓ Schema verification passed (10/10 tables)

# Check current document count (should be 0)
python scripts/cli/admin.py documents list
# Expected: No documents found
```

### ✅ Environment Configuration Check
```bash
# Verify critical environment variables
echo "DEPLOYMENT_STAGE: $DEPLOYMENT_STAGE"  # Should be: 1
echo "SUPABASE_URL: ${SUPABASE_URL:0:30}..."
echo "REDIS_HOST: $REDIS_HOST"
echo "S3_BUCKET_NAME: $S3_BUCKET_NAME"
echo "OPENAI_API_KEY: ${OPENAI_API_KEY:0:10}..."
```

### ✅ Celery Workers Status
```bash
# Check if Celery workers are running
ps aux | grep celery
# Or start workers if needed:
# celery -A scripts.celery_app worker --loglevel=info -Q ocr &
# celery -A scripts.celery_app worker --loglevel=info -Q text &
# celery -A scripts.celery_app worker --loglevel=info -Q embeddings &
# celery -A scripts.celery_app worker --loglevel=info -Q graph &
```

## Document Selection and Preparation

### 📋 Step 1: Select Test Document
```bash
# List available documents in input directory
ls -la /Users/josephott/Documents/phase_1_2_3_process_v5/input/

# Choose a representative PDF document for testing
# Recommended: Select a document that represents typical legal content
```

**Checklist**:
- [ ] Document selected from `/input/` directory
- [ ] Document is a PDF file (primary supported format)
- [ ] Document size is reasonable (< 50MB for initial test)
- [ ] Document filename noted for tracking

**Selected Document**: `____________________`
**File Size**: `____________________`
**Selected Time**: `____________________`

### 📋 Step 2: Verify Document Accessibility
```bash
# Verify document exists and is readable
TEST_DOC="[path to selected document]"
ls -la "$TEST_DOC"
file "$TEST_DOC"
```

**Checklist**:
- [ ] Document file exists and is accessible
- [ ] File type confirmed as PDF
- [ ] File permissions allow reading
- [ ] No corruption detected

## End-to-End Processing Pipeline

### 📋 Step 3: Document Upload and Initial Processing
```bash
# Method 1: Using CLI import tool (recommended)
python scripts/cli/import.py create-session \
    --project-uuid "[project-uuid]" \
    --session-name "E2E Test $(date +%Y%m%d_%H%M%S)" \
    --manifest-file "[generated-manifest]"

# Method 2: Direct Python processing
python -c "
from scripts.pdf_pipeline import process_single_document
from scripts.database import get_supabase_client
import os

doc_path = '$TEST_DOC'
result = process_single_document(doc_path)
print(f'Processing initiated: {result}')
"
```

**Checklist**:
- [ ] Document upload successful
- [ ] Document UUID generated and recorded
- [ ] Initial database entry created
- [ ] Processing status set to 'pending'

**Document UUID**: `____________________`
**Upload Time**: `____________________`

### 📋 Step 4: Monitor OCR Processing Stage
```bash
# Monitor document processing status
python scripts/cli/admin.py documents list --status processing

# Check processing pipeline status
python -c "
from scripts.database import get_supabase_client
supabase = get_supabase_client()
result = supabase.table('processing_pipeline').select('*').eq('document_uuid', '$DOC_UUID').execute()
for stage in result.data:
    print(f'Stage: {stage[\"stage_name\"]} - Status: {stage[\"stage_status\"]}')
"
```

**Checklist**:
- [ ] OCR stage initiated
- [ ] AWS Textract processing started
- [ ] No authentication errors with AWS
- [ ] Processing status updated in database

**OCR Stage Results**:
- Start Time: `____________________`
- Status: `____________________`
- Error Messages (if any): `____________________`

### 📋 Step 5: Verify Text Extraction and Chunking
```bash
# Check if chunks were created
python -c "
from scripts.database import get_supabase_client
supabase = get_supabase_client()
result = supabase.table('document_chunks').select('*').eq('document_uuid', '$DOC_UUID').execute()
print(f'Chunks created: {len(result.data)}')
for chunk in result.data[:3]:  # Show first 3 chunks
    print(f'Chunk {chunk[\"chunk_index\"]}: {chunk[\"chunk_text\"][:100]}...')
"
```

**Checklist**:
- [ ] Text successfully extracted from PDF
- [ ] Document chunked into logical segments
- [ ] Chunks stored in `document_chunks` table
- [ ] Chunk boundaries respect semantic structure

**Chunking Results**:
- Total Chunks: `____________________`
- Average Chunk Size: `____________________`
- Chunking Errors (if any): `____________________`

### 📋 Step 6: Monitor Entity Extraction
```bash
# Check entity extraction progress
python -c "
from scripts.database import get_supabase_client
supabase = get_supabase_client()

# Check entity mentions
mentions = supabase.table('entity_mentions').select('*').eq('chunk_uuid', '[chunk-uuid]').execute()
print(f'Entity mentions found: {len(mentions.data)}')

# Check canonical entities
entities = supabase.table('canonical_entities').select('*').execute()
print(f'Canonical entities: {len(entities.data)}')
"
```

**Checklist**:
- [ ] Entity extraction stage completed
- [ ] Entity mentions identified and stored
- [ ] Entity resolution performed
- [ ] Canonical entities created

**Entity Extraction Results**:
- Entity Mentions: `____________________`
- Canonical Entities: `____________________`
- Entity Types Found: `____________________`
- Extraction Errors (if any): `____________________`

### 📋 Step 7: Verify Relationship Building
```bash
# Check relationship staging
python -c "
from scripts.database import get_supabase_client
supabase = get_supabase_client()
result = supabase.table('relationship_staging').select('*').eq('source_document_uuid', '$DOC_UUID').execute()
print(f'Relationships found: {len(result.data)}')
for rel in result.data[:5]:  # Show first 5 relationships
    print(f'{rel[\"from_entity_type\"]} -> {rel[\"relationship_type\"]} -> {rel[\"to_entity_type\"]}')
"
```

**Checklist**:
- [ ] Relationship extraction completed
- [ ] Relationships stored in staging table
- [ ] Relationship types identified correctly
- [ ] Graph-ready format prepared

**Relationship Results**:
- Total Relationships: `____________________`
- Relationship Types: `____________________`
- Graph Readiness: `____________________`

### 📋 Step 8: Verify Complete Processing
```bash
# Check final document status
python scripts/cli/admin.py documents list --status completed

# Verify processing completion
python -c "
from scripts.database import get_supabase_client
supabase = get_supabase_client()
doc = supabase.table('documents').select('*').eq('document_uuid', '$DOC_UUID').execute()
if doc.data:
    d = doc.data[0]
    print(f'Status: {d[\"processing_status\"]}')
    print(f'Stage: {d[\"processing_stage\"]}')
    print(f'Chunks: {d[\"chunk_count\"]}')
    print(f'Entities: {d[\"entity_count\"]}')
    print(f'Relationships: {d[\"relationship_count\"]}')
    print(f'Completed: {d[\"processing_completed_at\"]}')
"
```

**Checklist**:
- [ ] Document status changed to 'completed'
- [ ] All processing stages finished successfully
- [ ] Summary counts populated correctly
- [ ] Completion timestamp recorded

**Final Processing Results**:
- Status: `____________________`
- Total Processing Time: `____________________`
- Chunks: `____________________`
- Entities: `____________________`
- Relationships: `____________________`

## Quality Assurance Verification

### 📋 Step 9: Content Quality Check
```bash
# Spot check extracted content quality
python -c "
from scripts.database import get_supabase_client
supabase = get_supabase_client()

# Get sample chunk
chunks = supabase.table('document_chunks').select('*').eq('document_uuid', '$DOC_UUID').limit(1).execute()
if chunks.data:
    print('Sample extracted text:')
    print(chunks.data[0]['chunk_text'][:500])
    print('...')
"
```

**Checklist**:
- [ ] Extracted text is readable and accurate
- [ ] No major OCR errors observed
- [ ] Text structure preserved appropriately
- [ ] Content matches source document

**Quality Assessment**:
- Text Accuracy: `____________________`
- Structure Preservation: `____________________`
- OCR Quality: `____________________`

### 📋 Step 10: Entity Quality Verification
```bash
# Check entity extraction quality
python -c "
from scripts.database import get_supabase_client
supabase = get_supabase_client()

entities = supabase.table('canonical_entities').select('*').execute()
for entity in entities.data[:10]:  # Show first 10 entities
    print(f'{entity[\"entity_type\"]}: {entity[\"entity_name\"]} (confidence: {entity[\"confidence_score\"]})')
"
```

**Checklist**:
- [ ] Entities identified are relevant and accurate
- [ ] Entity types classified correctly
- [ ] Confidence scores are reasonable (>0.7)
- [ ] No major false positives observed

**Entity Quality Assessment**:
- Accuracy: `____________________`
- Relevance: `____________________`
- False Positives: `____________________`

## Performance and Monitoring

### 📋 Step 11: Performance Metrics Collection
```bash
# Check processing metrics
python -c "
from scripts.database import get_supabase_client
supabase = get_supabase_client()

pipeline = supabase.table('processing_pipeline').select('*').eq('document_uuid', '$DOC_UUID').execute()
for stage in pipeline.data:
    if stage['stage_duration_ms']:
        print(f'{stage[\"stage_name\"]}: {stage[\"stage_duration_ms\"]}ms')
"
```

**Checklist**:
- [ ] Performance metrics captured for all stages
- [ ] Processing times within acceptable ranges
- [ ] No performance bottlenecks identified
- [ ] Resource utilization appropriate

**Performance Results**:
- OCR Time: `____________________`
- Chunking Time: `____________________`
- Entity Extraction Time: `____________________`
- Relationship Building Time: `____________________`
- Total Time: `____________________`

### 📋 Step 12: Error Handling Verification
```bash
# Check for any errors during processing
python -c "
from scripts.database import get_supabase_client
supabase = get_supabase_client()

# Check for processing errors
doc = supabase.table('documents').select('processing_error').eq('document_uuid', '$DOC_UUID').execute()
if doc.data and doc.data[0]['processing_error']:
    print('Processing errors found:')
    print(doc.data[0]['processing_error'])
else:
    print('No processing errors detected')

# Check pipeline errors
pipeline = supabase.table('processing_pipeline').select('*').eq('document_uuid', '$DOC_UUID').execute()
errors = [p for p in pipeline.data if p['error_data']]
if errors:
    print(f'Pipeline errors: {len(errors)}')
    for error in errors:
        print(f'{error[\"stage_name\"]}: {error[\"error_data\"]}')
else:
    print('No pipeline errors detected')
"
```

**Checklist**:
- [ ] No critical errors encountered
- [ ] Error handling functioned correctly
- [ ] Recovery mechanisms worked as expected
- [ ] Error logging captured appropriately

**Error Assessment**:
- Critical Errors: `____________________`
- Warnings: `____________________`
- Recovery Success: `____________________`

## Production Readiness Validation

### 📋 Step 13: Database Integrity Check
```bash
# Verify database consistency
python scripts/cli/admin.py verify-schema

# Check foreign key relationships
python -c "
from scripts.database import get_supabase_client
supabase = get_supabase_client()

# Verify document->chunks relationship
chunks = supabase.table('document_chunks').select('document_uuid').eq('document_uuid', '$DOC_UUID').execute()
print(f'Chunks linked to document: {len(chunks.data)}')

# Verify chunks->mentions relationship
mentions = supabase.table('entity_mentions').select('chunk_uuid').execute()
print(f'Total mentions: {len(mentions.data)}')
"
```

**Checklist**:
- [ ] All foreign key relationships maintained
- [ ] No orphaned records created
- [ ] Data consistency verified
- [ ] Database integrity preserved

### 📋 Step 14: Scalability Assessment
```bash
# Check resource utilization
python -c "
import psutil
print(f'CPU Usage: {psutil.cpu_percent()}%')
print(f'Memory Usage: {psutil.virtual_memory().percent}%')
"

# Check Redis memory usage
python scripts/cli/monitor.py cache
```

**Checklist**:
- [ ] Resource usage within acceptable limits
- [ ] No memory leaks detected
- [ ] Redis cache performing efficiently
- [ ] System ready for scaled processing

**Resource Assessment**:
- CPU Usage: `____________________`
- Memory Usage: `____________________`
- Redis Usage: `____________________`

## Final Validation and Sign-Off

### 📋 Step 15: End-to-End Verification Complete
```bash
# Final status verification
python scripts/cli/admin.py documents list
python scripts/cli/admin.py verify-services
```

**Final Checklist**:
- [ ] Single document processed successfully end-to-end
- [ ] All pipeline stages completed without critical errors
- [ ] Data quality meets expected standards
- [ ] Performance within acceptable parameters
- [ ] No resource exhaustion or memory leaks
- [ ] Error handling and recovery verified
- [ ] Database integrity maintained
- [ ] All services remain operational post-processing

## Production Deployment Authorization

### ✅ Prerequisites Met
- [x] Infrastructure verified operational (context_209)
- [x] Schema compliance achieved (context_211)
- [x] Service connectivity confirmed (context_212)
- [ ] End-to-end processing validated (this checklist)

### 🎯 Production Readiness Decision

**Test Document**: `____________________`
**Processing Status**: `□ SUCCESS` `□ PARTIAL` `□ FAILED`
**Quality Assessment**: `□ EXCELLENT` `□ GOOD` `□ ACCEPTABLE` `□ POOR`
**Performance Assessment**: `□ EXCELLENT` `□ GOOD` `□ ACCEPTABLE` `□ POOR`

**Deployment Authorization**: `□ APPROVED` `□ APPROVED WITH CONDITIONS` `□ NOT APPROVED`

**Authorized By**: `____________________`
**Date**: `____________________`
**Conditions (if any)**: `____________________`

### 🚀 Next Steps

Upon successful completion of this checklist:

1. **Scale to Batch Processing**: Begin processing multiple documents from `/input/`
2. **Monitor Performance**: Use CLI tools to track batch processing performance
3. **Optimize as Needed**: Adjust worker counts and resource allocation based on performance
4. **Full Production Load**: Process all 450+ documents systematically

**Implementation Ready**: The legal document processing pipeline is validated and ready for full production deployment.

## Troubleshooting Quick Reference

### Common Issues and Solutions

**OCR Failures**:
```bash
# Check AWS credentials and Textract limits
aws sts get-caller-identity
```

**Entity Extraction Issues**:
```bash
# Verify OpenAI API connectivity and limits
python -c "import openai; print('OpenAI available')"
```

**Database Connection Issues**:
```bash
# Test Supabase connectivity
python scripts/cli/admin.py verify-services
```

**Redis Connection Issues**:
```bash
# Test Redis connectivity
python -c "from scripts.config import *; import redis; r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD, username=REDIS_USERNAME, ssl=REDIS_SSL); print(r.ping())"
```

This checklist ensures comprehensive validation of the entire legal document processing pipeline before full-scale production deployment.