# Context 430: Batch Performance Test - Single Document Processing

## Date: June 5, 2025

## Executive Summary

Implementing batch performance testing with increasing batch sizes (1, 3, 10, 20 documents) to evaluate system performance and scalability. This document captures the detailed output and analysis from the first single document run through the complete pipeline.

## Test Configuration

### Environment Settings
```bash
FORCE_PROCESSING=true              # Bypass non-critical validation
SKIP_PDF_PREPROCESSING=true        # Let Textract handle PDFs directly
PARAMETER_DEBUG=false              # Reduced logging for performance test
VALIDATION_REDIS_METADATA_LEVEL=optional
VALIDATION_PROJECT_ASSOCIATION_LEVEL=optional
```

### Test Parameters
- **Batch Sizes**: 1, 3, 10, 20 documents
- **Document Selection**: Smallest PDFs first (for faster testing)
- **Size Limit**: < 100MB per document
- **Timeout**: 600 seconds (10 minutes) per document
- **Worker Configuration**: 4 concurrent Celery workers

## Initial Run Issues

### Problem Identified
The S3StorageManager's `upload_document_with_uuid_naming` method returns:
```python
{
    's3_key': 'documents/uuid.pdf',
    's3_bucket': 'bucket-name',
    's3_region': 'us-east-2',
    'md5_hash': 'hash',
    'file_size': 12345,
    'metadata': {...}
}
```

But our code expected an `s3_url` key, causing all uploads to fail.

### Fix Applied
Modified batch_performance_test.py to construct the S3 URL:
```python
# Extract S3 info from result
s3_key = result['s3_key']
s3_bucket = result['s3_bucket']

# Construct S3 URL
s3_url = f"s3://{s3_bucket}/{s3_key}"
```

## Single Document Test Run (Pending)

The test will process a single document through all pipeline stages:
1. **Upload to S3** - Document storage with UUID naming
2. **Database Record Creation** - Source document entry
3. **OCR Processing** - AWS Textract text extraction
4. **Text Chunking** - Semantic chunking with overlap
5. **Entity Extraction** - OpenAI-based entity recognition
6. **Entity Resolution** - Deduplication and canonicalization
7. **Relationship Building** - Graph staging

### Expected Metrics
- Upload time
- OCR processing time (Textract async)
- Chunking performance
- Entity extraction rate
- Resolution efficiency
- Total pipeline time

## Performance Monitoring

The test monitors each stage through:
1. **Redis State Tracking** - Real-time stage completion
2. **Database Queries** - Final counts for chunks, entities, relationships
3. **Timing Metrics** - Per-stage performance data

## Next Steps

1. Run the fixed batch_performance_test.py
2. Capture detailed metrics for single document
3. Analyze performance bottlenecks
4. Scale up to batch sizes 3, 10, 20
5. Generate comprehensive performance report

## Implementation Status

✅ Test script created with batch size progression
✅ S3 upload issue identified and fixed
⏳ Single document test execution pending
⏳ Performance metrics collection pending
⏳ Batch scaling tests pending