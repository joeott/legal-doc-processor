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
cp .env.example .env  # Then edit with your credentials

# Initialize database schema
psql -h localhost -p 5433 -U app_user -d legal_doc_processing -f scripts/create_schema.sql
```

### Running the System
```bash
# Start Celery worker
celery -A scripts.celery_app worker --loglevel=info

# Monitor pipeline status
python scripts/cli/monitor.py live

# Import documents
python scripts/cli/import.py --manifest path/to/manifest.json

# Run tests
python -m pytest scripts/test_*.py
python scripts/test_schema_conformance.py  # Schema validation
```

### Database Operations
```bash
# Apply migrations
python scripts/database/apply_migration_210.py

# Check database connection
python scripts/check_rds_connection.py

# Verify schema conformance
python scripts/verify_rds_schema_conformance.py
```

## Architecture

### Core Processing Flow
1. **Document Intake** → Uploaded to S3 bucket
2. **OCR Processing** → AWS Textract (with fallback options)
3. **Text Chunking** → Semantic chunking with configurable overlap
4. **Entity Extraction** → OpenAI + local NER models
5. **Entity Resolution** → Deduplication and canonical entity creation
6. **Relationship Building** → Graph staging for Neo4j
7. **Caching** → Redis for all intermediate results

### Key Components

**Task Processing** (`scripts/pdf_tasks.py`):
- Celery tasks for each pipeline stage
- Idempotent operations with comprehensive error handling
- Redis-based state management

**Database Layer** (`scripts/db.py`):
- PostgreSQL via SQLAlchemy 2.0
- Pydantic models for validation (`scripts/core/`)
- Schema conformance engine

**Caching** (`scripts/cache.py`):
- Redis Cloud integration
- Hierarchical cache invalidation
- Performance monitoring

**CLI Tools** (`scripts/cli/`):
- `monitor.py`: Live monitoring, health checks, worker status
- `admin.py`: Administrative operations
- `import.py`: Document import utilities

### Configuration

**Environment Variables** (required in `.env`):
```
# Database
DATABASE_URL=postgresql://user:pass@host:port/dbname
DATABASE_URL_DIRECT=postgresql://user:pass@host:port/dbname

# AWS
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_DEFAULT_REGION=us-east-1
S3_PRIMARY_DOCUMENT_BUCKET=

# Redis
REDIS_HOST=
REDIS_PORT=
REDIS_PASSWORD=

# OpenAI
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o-mini

# Deployment
DEPLOYMENT_STAGE=1  # 1=Cloud, 2=Hybrid, 3=Local
```

### Deployment Stages
- **Stage 1**: Cloud-only (OpenAI/Textract)
- **Stage 2**: Hybrid (local models with cloud fallback)
- **Stage 3**: Local production (EC2 with full local models)

## Database Schema

Key tables:
- `projects`: Legal matters/projects
- `source_documents`: Original document metadata
- `document_chunks`: Processed text chunks
- `entity_mentions`: Raw extracted entities
- `canonical_entities`: Deduplicated entities
- `relationship_staging`: Entity relationships
- `processing_tasks`: Celery task tracking

## Error Handling

The system includes comprehensive error handling:
- Automatic retries with exponential backoff
- Dead letter queues for failed tasks
- Detailed error logging to CloudWatch
- Recovery scripts in `scripts/legacy/fixes/`

## Testing

Run specific test scenarios:
```bash
# Test single document processing
python scripts/legacy/testing/test_single_document.py

# Test full pipeline
python scripts/legacy/testing/test_full_pipeline.py

# Test schema conformance
python scripts/test_schema_conformance.py
```

## Monitoring

Use the unified monitor for real-time insights:
```bash
# Live monitoring dashboard
python scripts/cli/monitor.py live

# Check specific document status
python scripts/cli/monitor.py doc-status <document_id>

# Worker health check
python scripts/cli/monitor.py health
```

## Performance Considerations

- Redis caching reduces database load by 90%+
- Chunking strategy optimized for legal documents
- Batch operations for entity extraction
- Connection pooling for all external services
- Comprehensive metrics via CloudWatch

## Development Guidelines

- Plan and carefully consider each script in the context of the whole
- Prefer simple solutions that produce reliable functioning code and not complex ones
- Always document on an ongoing basis any planning, conceptualization and verification of outcomes as a new note in /ai_docs/ subdirectory
- Each note should be context_[k+1]_[description].md
- Do not create scripts to get around issues. If there is an issue - like a remaining legacy import - in the codebase, fix that issue and do not take short cuts to code around it.

## Memory Management

- Actively manage your memory and context using /ai_docs/
- Store plans, concepts, notes and results in dedicated documentation files