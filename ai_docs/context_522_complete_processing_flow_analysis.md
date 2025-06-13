# Complete Processing Flow Analysis

## Analysis Date: 2025-06-13

## Executive Summary

Based on analysis of worker logs and codebase, here is the complete processing flow with all scripts and modules involved:

## Core Processing Scripts

### 1. Main Pipeline Orchestration
- **scripts/pdf_tasks.py** (9,127 log references)
  - Main pipeline task definitions for all 6 stages
  - Task decorators for monitoring and error handling
  - State management and progress tracking
  - Redis caching integration

### 2. OCR Processing
- **scripts/textract_utils.py** (1,094 log references)
  - AWS Textract integration
  - Async job management
  - Region handling for S3 buckets
  - Text extraction and confidence scoring

### 3. Entity Processing
- **scripts/entity_service.py** (554 log references)
  - OpenAI API integration for NER
  - Entity extraction, resolution, and enhancement
  - Rate limiting handling
  - Memory issues detected (jiter shared library failures)

### 4. Caching Layer
- **scripts/cache.py** (660 log references)
  - Redis connection management
  - Multi-database support (cache, batch, metrics, rate_limit)
  - Rate limiting decorator
  - Cache key management

### 5. Database Operations
- **scripts/db.py** (435 log references)
  - SQLAlchemy database operations
  - Conformance validation (currently bypassed)
  - Transaction management

### 6. Document Processing Utilities
- **scripts/chunking_utils.py** (52 log references)
  - Semantic text chunking
  - Overlap handling
  
- **scripts/utils/pdf_handler.py** (63 log references)
  - PDF file handling utilities

### 7. Graph and Relationship Building
- **scripts/graph_service.py**
  - Relationship staging
  - Structural relationships (BELONGS_TO, CONTAINS_MENTION)
  - Limited by FK constraints to canonical entities only

### 8. Batch Processing
- **scripts/batch_tasks.py**
  - Priority queue management (high/normal/low)
  - Batch status tracking
  
- **scripts/batch_recovery.py**
  - Error recovery strategies
  - Failed document reprocessing

- **scripts/batch_metrics.py**
  - Time-series metrics collection

### 9. Validation Layer
- **scripts/validation/flexible_validator.py** (41 log references)
- **scripts/validation/pipeline_validator.py** (10 log references)
- **scripts/validation/ocr_validator.py** (10 log references)
- **scripts/validation/entity_validator.py** (10 log references)

### 10. Supporting Services
- **scripts/celery_app.py** (30 log references)
  - Celery configuration
  - Queue definitions
  
- **scripts/status_manager.py** (10 log references)
  - Pipeline status tracking

- **scripts/cache_warmer.py**
  - Pre-processing cache optimization

## Key Issues Identified

### 1. Memory Issues
- **Critical**: Repeated "jiter.cpython-310-x86_64-linux-gnu.so: failed to map segment from shared object" errors
- Indicates memory pressure or shared library loading issues
- Affecting OpenAI entity extraction operations

### 2. Rate Limiting
- Extensive rate limiting on OpenAI API calls
- Wait times ranging from 0.00s to 50.06s
- Successfully handled by rate_limit decorator

### 3. Processing Failures
- Empty text extraction from some documents (0 characters)
- Chunking failures due to missing text
- Missing required arguments in some task calls

### 4. Redis Configuration
- Multi-database setup:
  - DB 0: rate_limit
  - DB 1: cache (documents, chunks, entities)
  - DB 2: batch processing
  - DB 3: metrics
  - DB 4: (not specified in logs)

## Processing Flow Sequence

1. **Document Upload** → S3 storage
2. **OCR Extraction** → textract_utils.py → AWS Textract
3. **Text Chunking** → chunking_utils.py → semantic chunks
4. **Entity Extraction** → entity_service.py → OpenAI API
5. **Entity Resolution** → entity_service.py → canonicalization
6. **Relationship Building** → graph_service.py → staging
7. **Finalization** → pdf_tasks.py → status updates

## Recommendations

1. **Address Memory Issues**
   - Investigate jiter library compatibility
   - Consider worker memory limits
   - Monitor system memory usage

2. **Optimize Rate Limiting**
   - Implement request batching
   - Add retry logic with exponential backoff
   - Consider caching entity extraction results

3. **Fix Processing Errors**
   - Add validation for empty OCR results
   - Implement fallback strategies
   - Fix missing argument issues

4. **Improve Monitoring**
   - Add memory usage tracking
   - Monitor rate limit impacts
   - Track entity extraction success rates