# Context 155: Legal Document Processing System - CLI Usage Guide

## Overview

This guide provides comprehensive documentation for all CLI commands and scripts available in the legal document processing pipeline. The system uses Celery for distributed task processing with Redis as the message broker.

## Table of Contents

1. [Environment Setup](#environment-setup)
2. [Starting the System](#starting-the-system)
3. [Document Processing Commands](#document-processing-commands)
4. [Monitoring Commands](#monitoring-commands)
5. [Testing Commands](#testing-commands)
6. [Database Management](#database-management)
7. [Cache Management](#cache-management)
8. [Import Operations](#import-operations)
9. [Debugging Commands](#debugging-commands)
10. [Common Workflows](#common-workflows)

## Environment Setup

### Required Environment Variables

```bash
# Create .env file with these variables
export SUPABASE_URL="your_supabase_url"
export SUPABASE_KEY="your_supabase_anon_key"
export SUPABASE_SERVICE_ROLE_KEY="your_service_role_key"
export OPENAI_API_KEY="your_openai_key"
export AWS_ACCESS_KEY_ID="your_aws_key"
export AWS_SECRET_ACCESS_KEY="your_aws_secret"
export AWS_DEFAULT_REGION="us-east-2"
export S3_PRIMARY_DOCUMENT_BUCKET="your_s3_bucket"
export REDIS_HOST="localhost"
export REDIS_PORT="6379"
export REDIS_PASSWORD=""  # Set if using Redis Cloud
export AIRTABLE_API_KEY="your_airtable_key"
export AIRTABLE_BASE_ID="your_base_id"
export DEPLOYMENT_STAGE="1"  # 1, 2, or 3
```

### Python Path Setup

```bash
# Always set PYTHONPATH before running scripts
export PYTHONPATH=/path/to/phase_1_2_3_process_v5:$PYTHONPATH
```

## Starting the System

### 1. Start Redis (if running locally)

```bash
# Using Docker
docker run -d -p 6379:6379 redis:latest

# Or using system Redis
redis-server
```

### 2. Start Celery Workers

```bash
# Start all workers with default configuration
./scripts/start_celery_workers.sh

# Or start individual worker types
# OCR Worker (2 concurrent)
celery -A scripts.celery_app worker --loglevel=info --concurrency=2 -Q ocr -n ocr_worker@%h

# Text Processing Worker (4 concurrent)
celery -A scripts.celery_app worker --loglevel=info --concurrency=4 -Q text -n text_worker@%h

# Entity Worker (100 concurrent with gevent)
celery -A scripts.celery_app worker --loglevel=info --concurrency=100 -Q entity -P gevent -n entity_worker@%h

# Graph Worker (4 concurrent)
celery -A scripts.celery_app worker --loglevel=info --concurrency=4 -Q graph -n graph_worker@%h
```

### 3. Start Flower Monitoring Dashboard

```bash
# Start Flower on default port 5555
celery -A scripts.celery_app flower

# Or specify custom port
celery -A scripts.celery_app flower --port=5556

# Access at http://localhost:5555
```

## Document Processing Commands

### Process Single Document

```bash
# Process a single PDF file
python scripts/test_single_document.py /path/to/document.pdf

# Process with specific project
python scripts/test_single_document.py /path/to/document.pdf --project-uuid "uuid-here"

# Process image file
python scripts/test_single_document.py /path/to/image.jpg
```

### Process Multiple Documents

```bash
# Process all documents in input_docs folder
python scripts/test_celery_e2e.py

# Process specific folder
python scripts/test_celery_e2e.py --input-dir /path/to/documents

# Process with batch size control
python scripts/test_celery_e2e.py --batch-size 10 --delay 0.5
```

### Submit Documents in Batch

```bash
# Submit documents using the batch processor
python submit_documents_batch.py --input-dir input_docs --project-name "Legal Case XYZ"

# With custom batch size and delay
python submit_documents_batch.py --input-dir input_docs --batch-size 25 --delay 1.0
```

## Monitoring Commands

### Live Pipeline Monitor

```bash
# Start comprehensive pipeline monitor (Flower-inspired)
python scripts/standalone_pipeline_monitor.py

# With custom refresh interval
python scripts/standalone_pipeline_monitor.py --refresh-interval 3

# Monitor specific document
python scripts/standalone_pipeline_monitor.py --document-uuid "uuid-here"
```

### Database Monitor

```bash
# Monitor processing status in database
python monitoring/live_monitor.py

# With specific refresh rate
python monitoring/live_monitor.py --refresh 5
```

### Redis Queue Monitor

```bash
# Monitor Redis queues and cache
python monitoring/redis_monitor.py

# Show detailed metrics
python monitoring/redis_monitor.py --detailed
```

### Pipeline Analysis

```bash
# Analyze pipeline performance
python monitoring/pipeline_analysis.py

# Generate performance report
python monitoring/pipeline_analysis.py --report output_report.json
```

### Check Celery Status

```bash
# Check active tasks
celery -A scripts.celery_app inspect active

# Check worker stats
celery -A scripts.celery_app inspect stats

# Check scheduled tasks
celery -A scripts.celery_app inspect scheduled

# Check task queue lengths
celery -A scripts.celery_app inspect reserved
```

## Testing Commands

### Unit Tests

```bash
# Run all tests
python -m pytest

# Run with coverage
python -m pytest --cov=scripts tests/

# Run specific test file
python -m pytest tests/unit/test_text_processing.py -v

# Run specific test
python -m pytest tests/unit/test_text_processing.py::test_semantic_chunking -v
```

### Integration Tests

```bash
# Run all integration tests
python -m pytest tests/integration/

# Test Celery pipeline
python -m pytest tests/integration/test_celery_pipeline.py -v

# Test image processing
python -m pytest tests/integration/test_image_pipeline.py -v
```

### End-to-End Tests

```bash
# Test complete pipeline
python scripts/test_e2e_with_caching.py

# Test Airtable integration
python scripts/test_airtable_e2e.py

# Test multiple document processing
python scripts/test_multiple_documents.py
```

## Database Management

### Migration Commands

```bash
# Apply database migrations
python scripts/core/db_migration_helper.py validate

# Check specific table
python scripts/core/db_migration_helper.py validate --table source_documents

# Generate migration report
python scripts/core/db_migration_helper.py report --output migration_report.json
```

### Database Utilities

```bash
# List all projects
python scripts/list_projects.py

# Clean up test documents
python scripts/cleanup_test_documents.py

# Backfill project UUIDs
python scripts/backfill_project_uuids.py
```

## Cache Management

### Cache Operations

```bash
# Warm cache for specific project
python scripts/cache_warmer.py --project-uuid "uuid-here"

# Clear cache for document
python scripts/cache_warmer.py --clear --document-uuid "uuid-here"

# Monitor cache performance
python scripts/monitor_cache_performance.py
```

### Redis Management

```bash
# Test Redis connection
python scripts/test_redis_connection.py

# Flush specific cache pattern
redis-cli --scan --pattern "doc:*" | xargs redis-cli del

# Monitor Redis in real-time
redis-cli monitor
```

## Import Operations

### Import from Manifest

```bash
# Import documents from manifest file
python scripts/cli/import.py from-manifest manifest.json --project-uuid "uuid-here"

# Dry run to validate manifest
python scripts/cli/import.py from-manifest manifest.json --project-uuid "uuid-here" --dry-run

# Import with custom batch size
python scripts/cli/import.py from-manifest manifest.json --project-uuid "uuid-here" --batch-size 25
```

### Import Client Files

```bash
# Import specific client folder
python scripts/import_client_files.py --client-name "Paul, Michael (Acuity)" --project-uuid "uuid-here"

# Import with pattern matching
python scripts/import_client_files.py --client-name "Paul, Michael" --pattern "*.pdf"
```

### Monitor Import Progress

```bash
# Check import session status
python scripts/check_import_completion.py --session-id "session-uuid"

# Monitor all active imports
python scripts/import_dashboard.py
```

## Debugging Commands

### Debug Stuck Documents

```bash
# Debug specific document by UUID
python scripts/debug_celery_document.py --uuid "document-uuid"

# Debug by filename
python scripts/debug_celery_document.py --file "document.pdf"

# Find documents stuck for more than 30 minutes
python scripts/debug_celery_document.py --stuck 30
```

### Process Stuck Documents

```bash
# Retry stuck documents
python scripts/process_stuck_documents.py

# Force reprocess specific document
python scripts/process_stuck_documents.py --document-uuid "uuid-here" --force
```

### Check Document Status

```bash
# Simple status check
python scripts/check_doc_status_simple.py "document-uuid"

# Detailed status with history
python scripts/check_doc_status_simple.py "document-uuid" --detailed
```

### Health Check

```bash
# Run system health check
python scripts/health_check.py

# With detailed component checks
python scripts/health_check.py --detailed
```

## Common Workflows

### 1. Complete Document Processing Workflow

```bash
# Step 1: Start the system
export PYTHONPATH=/path/to/project:$PYTHONPATH
./scripts/start_celery_workers.sh
celery -A scripts.celery_app flower

# Step 2: Submit documents
python submit_documents_batch.py --input-dir input_docs --project-name "New Case"

# Step 3: Monitor progress
python scripts/standalone_pipeline_monitor.py

# Step 4: Check completion
python scripts/check_import_completion.py
```

### 2. Debug Failed Document

```bash
# Step 1: Find the document
python scripts/debug_celery_document.py --file "problematic.pdf"

# Step 2: Check detailed status
python scripts/check_doc_status_simple.py "document-uuid" --detailed

# Step 3: Check logs
grep "document-uuid" logs/celery_*.log

# Step 4: Retry processing
python scripts/process_stuck_documents.py --document-uuid "uuid" --force
```

### 3. Import Client Documents

```bash
# Step 1: Create manifest
python scripts/analyze_client_files.py --client-path "input/ClientName" --output manifest.json

# Step 2: Validate manifest
python scripts/cli/import.py from-manifest manifest.json --project-uuid "uuid" --validate-only

# Step 3: Import documents
python scripts/cli/import.py from-manifest manifest.json --project-uuid "uuid"

# Step 4: Monitor import
python scripts/import_dashboard.py
```

### 4. Performance Testing

```bash
# Step 1: Prepare test documents
cp test_documents/* input_docs/

# Step 2: Clear previous runs
python scripts/cleanup_test_documents.py

# Step 3: Run performance test
time python scripts/test_celery_e2e.py --batch-size 100

# Step 4: Analyze results
python monitoring/pipeline_analysis.py --report performance_report.json
```

## Advanced Options

### Custom Worker Configuration

```bash
# High-memory OCR worker
celery -A scripts.celery_app worker -Q ocr --max-memory-per-child=2000000

# CPU-optimized text worker
celery -A scripts.celery_app worker -Q text --max-tasks-per-child=100

# Gevent-based entity worker for I/O
celery -A scripts.celery_app worker -Q entity -P gevent --concurrency=200
```

### Task Routing

```bash
# Submit to specific queue
from scripts.celery_tasks.ocr_tasks import process_ocr
process_ocr.apply_async(args=[...], queue='ocr.priority')
```

### Monitoring with Systemd

```bash
# Create service file: /etc/systemd/system/celery-nlp.service
sudo systemctl start celery-nlp
sudo systemctl status celery-nlp
sudo journalctl -u celery-nlp -f
```

## Troubleshooting

### Common Issues

1. **Import Errors**: Always set PYTHONPATH
   ```bash
   export PYTHONPATH=/path/to/project:$PYTHONPATH
   ```

2. **Redis Connection**: Check Redis is running
   ```bash
   redis-cli ping  # Should return PONG
   ```

3. **Worker Not Processing**: Check worker logs
   ```bash
   celery -A scripts.celery_app inspect active_queues
   ```

4. **Memory Issues**: Restart workers
   ```bash
   celery -A scripts.celery_app control pool_restart
   ```

## Best Practices

1. **Always monitor with Flower** during batch processing
2. **Use appropriate batch sizes** (25-50 for OCR-heavy documents)
3. **Set reasonable delays** between submissions (0.5-1.0 seconds)
4. **Check system health** before large imports
5. **Monitor Redis memory** usage during processing
6. **Use dry-run** options before actual imports
7. **Keep logs** for debugging (`--loglevel=info`)

## Quick Reference

```bash
# Most common commands
./scripts/start_celery_workers.sh                    # Start workers
celery -A scripts.celery_app flower                  # Start monitor
python submit_documents_batch.py --input-dir docs    # Process documents
python scripts/standalone_pipeline_monitor.py        # Monitor progress
python scripts/health_check.py                       # Check system
```

This guide covers the essential CLI commands for operating the legal document processing system. For detailed API documentation, refer to the codebase documentation.