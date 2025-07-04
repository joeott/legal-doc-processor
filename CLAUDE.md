# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a legal document processing pipeline that handles OCR, entity extraction, and knowledge graph building for legal documents. The system uses Celery for distributed task processing, Redis for caching, PostgreSQL (RDS) for persistence, and AWS services (S3, Textract) for document storage and OCR.

## Common Commands

### Development Setup
```bash
# Install dependencies
pip install -r requirements.txt

# Set up environment variables
source load_env.sh  # Loads from .env file

# Initialize database schema
psql -h localhost -p 5433 -U app_user -d legal_doc_processing -f scripts/create_schema.sql
```

### Running the System
```bash
# Start Celery worker (all queues)
celery -A scripts.celery_app worker --loglevel=info --queues=default,ocr,text,entity,graph,cleanup &

# Start batch processing workers (priority-specific)
celery -A scripts.celery_app worker -Q batch.high -n batch-high@%h --concurrency=4 &
celery -A scripts.celery_app worker -Q batch.normal -n batch-normal@%h --concurrency=2 &
celery -A scripts.celery_app worker -Q batch.low -n batch-low@%h --concurrency=1 &

# Kill existing workers before restart
ps aux | grep "[c]elery" | awk '{print $2}' | xargs -r kill -9

# Monitor pipeline status
python scripts/cli/monitor.py live

# Import documents
python scripts/cli/import.py --manifest path/to/manifest.json

# Process a single document
python process_test_document.py /path/to/document.pdf

# Submit batch of documents
python batch_submit_2_documents.py

# Check Redis state for document
redis-cli -h $REDIS_HOST -p $REDIS_PORT -a $REDIS_PASSWORD get "doc:state:<document_uuid>" | jq .

# Monitor full pipeline processing
python monitor_full_pipeline.py

# Test Redis acceleration
python test_redis_acceleration.py
```

### Testing Commands
```bash
# Run unit tests
pytest tests/unit/

# Run integration tests  
pytest tests/integration/

# Run end-to-end tests
pytest tests/e2e/

# Run specific test file
pytest tests/unit/test_pdf_tasks.py

# Run specific test function
pytest tests/unit/test_pdf_tasks.py::test_extract_text_from_document

# Run with coverage
pytest --cov=scripts tests/

# Test single document processing
python test_single_doc/test_document.py

# Monitor batch processing
python monitor_batch_processing.py

# Run batch processing tests
./scripts/run_batch_tests.sh
```

### Database Operations
```bash
# Check database connection
python scripts/db.py  # Will test connection and show conformance status

# Check schema
python scripts/check_schema.py

# Query entity mentions for a document
psql -h $DATABASE_HOST -p $DATABASE_PORT -U $DATABASE_USER -d $DATABASE_NAME -c "SELECT COUNT(*) FROM entity_mentions WHERE document_uuid = '<uuid>';"

# Check processing status  
psql -h $DATABASE_HOST -p $DATABASE_PORT -U $DATABASE_USER -d $DATABASE_NAME -c "SELECT status, task_type FROM processing_tasks WHERE document_id = '<uuid>' ORDER BY created_at DESC LIMIT 1;"

# Clear test data
python clear_rds_test_data.py
python clear_redis_cache.py
```

### Lint and Type Checking
```bash
# Run linting (if configured)
npm run lint  # or appropriate linting command

# Run type checking (if configured) 
npm run typecheck  # or appropriate type checking command
```

## High-Level Architecture

### Pipeline Flow
```
Document Upload → OCR → Chunking → Entity Extraction → Entity Resolution → Relationship Building → Finalization
       ↓            ↓         ↓             ↓                    ↓                    ↓              ↓
   S3 Storage   Textract  Semantic     OpenAI NER         Fuzzy Matching      Graph Creation   Database
                          Chunking     + Spacy            + Canonicalization                   + Cache
```

### Core Components

#### Task Orchestration (Celery)
- **scripts/celery_app.py**: Celery configuration with Redis broker/backend, priority queue support
- **scripts/pdf_tasks.py**: Main pipeline tasks (6 stages)
- **scripts/batch_tasks.py**: Priority-based batch processing (high/normal/low)
- **scripts/batch_recovery.py**: Intelligent error recovery with retry strategies
- Queues: `default`, `ocr`, `text`, `entity`, `graph`, `cleanup`, `batch.high`, `batch.normal`, `batch.low`
- Memory limit: 512MB per worker process
- Priority levels: 0-9 (9 highest)

#### Data Layer
- **scripts/models.py**: Consolidated Pydantic models (single source of truth)
  - Database models end with "Minimal" suffix (e.g., SourceDocumentMinimal, DocumentChunkMinimal)
  - Backward compatibility via @property decorators
  - Field names match exact database column names
- **scripts/db.py**: SQLAlchemy database operations
- **scripts/cache.py**: Redis caching with automatic expiration
- **scripts/cache_warmer.py**: Pre-processing cache optimization for batch operations
- **scripts/batch_metrics.py**: Time-series metrics collection in Redis

#### Processing Services
- **scripts/ocr_extraction.py**: PDF text extraction with multiple fallbacks
- **scripts/textract_utils.py**: AWS Textract async job management
- **scripts/chunking_utils.py**: Semantic text chunking with overlap
- **scripts/entity_service.py**: Entity extraction (OpenAI/Spacy) and resolution
- **scripts/graph_service.py**: Relationship extraction and graph building

#### Storage & Infrastructure
- **scripts/s3_storage.py**: S3 document storage operations
- **scripts/config.py**: Environment and stage configuration
- **scripts/logging_config.py**: CloudWatch integrated logging

### Model Organization

All database models are in `scripts/models.py`. Processing models for pipeline data transfer remain in `scripts/core/processing_models.py`.

**Important**: Do NOT import from `scripts.core.*` for new code. Use:
- Database models: `from scripts.models import ...`
- JSON serializer: `from scripts.utils.json_serializer import ...`
- Conformance: `from scripts.validation.conformance_validator import ...`

### Database Schema

The database schema is tracked in `/monitoring/reports/*/schema_export_database_schema.json`. Key tables:
- `source_documents`: Document metadata and processing status
- `document_chunks`: Semantic text chunks
- `entity_mentions`: Extracted entities from text
- `canonical_entities`: Deduplicated entities
- `relationship_staging`: Entity relationships
- `processing_tasks`: Task tracking (note: uses `document_id` not `document_uuid`, `task_type` not `stage`)
- `textract_jobs`: AWS Textract job tracking

## Critical Field Mappings

Be aware of these field name differences between models and database:
- ProcessingTaskMinimal: `document_id` (NOT `document_uuid`), `task_type` (NOT `stage`)
- All models use UUID for id fields, not integers

## Batch Processing

### Submit Batch with Priority
```python
from scripts.batch_tasks import submit_batch

# Submit high priority batch
result = submit_batch(
    documents=[{'document_uuid': 'uuid', 'file_path': 's3://path'}],
    project_uuid='project-id',
    priority='high',  # 'high', 'normal', 'low'
    options={'warm_cache': True}
)
```

### Monitor Batch Progress
```python
from scripts.batch_tasks import get_batch_status

status = get_batch_status.apply_async(args=[batch_id]).get()
print(f"Progress: {status['progress_percentage']}%")
```

### Recover Failed Documents
```python
from scripts.batch_recovery import recover_failed_batch

recovery = recover_failed_batch.apply_async(
    args=[batch_id],
    kwargs={'options': {'max_retries': 3}}
).get()
```

## Memory Management Guidelines

- Always test the production scripts
- Only create test scripts when you really need to isolate something
- Save all test scripts in /tests/
- Always search for tests in /tests/ before creating new test scripts
- All scripts MUST have a purpose
- Test using production documents from /opt/legal-doc-processor/input_docs/Paul, Michael (Acuity)
- Robustly and frequently create detailed, sequentially numbered notes (new notes higher number) in ai_docs

## Environment Configuration

Required environment variables:
```bash
# Database
DATABASE_URL=postgresql://user:pass@host:port/dbname
DATABASE_URL_DIRECT=postgresql://user:pass@host:port/dbname

# Redis
REDIS_HOST=redis-host
REDIS_PORT=port
REDIS_PASSWORD=password

# AWS Services
AWS_ACCESS_KEY_ID=key
AWS_SECRET_ACCESS_KEY=secret
AWS_DEFAULT_REGION=us-east-1
S3_PRIMARY_DOCUMENT_BUCKET=bucket-name

# AI Services
OPENAI_API_KEY=key
OPENAI_MODEL=gpt-4o-mini

# Deployment
DEPLOYMENT_STAGE=1
SKIP_CONFORMANCE_CHECK=true  # Currently bypassed for Minimal models

# Batch Processing
REDIS_PREFIX_BATCH=batch:
REDIS_PREFIX_METRICS=metrics:
```

## Recent Architecture Changes

1. **Pydantic Model Consolidation** - All database models moved to scripts/models.py with "Minimal" suffix
2. **Redis Acceleration** - Implemented comprehensive caching strategy
3. **Deprecated Scripts Removal** - scripts/core/* utilities moved to scripts/utils/* and scripts/validation/*
4. **Minimal Models Strategy** - Using models with "Minimal" suffix to match exact database schema
5. **Batch Processing Enhancement** - Added priority queues, error recovery, metrics, and cache warming

## Development Context

- Historical context and decisions are documented in `/ai_docs/context_*.md` files
- The system has undergone significant consolidation (264 → 98 production scripts)
- Currently in production with 99%+ success rate for all 6 pipeline stages