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
psql -h $DATABASE_HOST -p $DATABASE_PORT -U $DATABASE_USER -d $DATABASE_NAME -c "SELECT status, stage FROM processing_tasks WHERE document_uuid = '<uuid>' ORDER BY created_at DESC LIMIT 1;"

# Clear test data
python clear_rds_test_data.py
python clear_redis_cache.py
```

## Architecture

### Core Processing Flow
1. **Document Intake** → Uploaded to S3 bucket
2. **OCR Processing** → AWS Textract (async-only, no scanned PDF detection)
3. **Text Chunking** → Semantic chunking with configurable overlap
4. **Entity Extraction** → OpenAI gpt-4o-mini
5. **Entity Resolution** → Deduplication and canonical entity creation
6. **Relationship Building** → Graph staging for Neo4j
7. **Pipeline Finalization** → Cleanup and completion

### Key Components

**Task Processing** (`scripts/pdf_tasks.py`):
- Celery tasks for each pipeline stage
- Automatic task chaining (OCR → Chunking → Entity Extraction → Resolution → Relationships)
- Redis-based state management
- Comprehensive error handling with retries

**Database Layer** (`scripts/db.py`):
- PostgreSQL via SQLAlchemy 2.0
- Connection pooling and retry logic
- Direct RDS connectivity (no SSH tunnel needed when on VPN)

**Models** (`scripts/models.py`):
- Consolidated Pydantic models (single source of truth)
- Minimal models with only essential fields
- Backward compatibility properties

**OCR Processing** (`scripts/textract_utils.py`):
- AWS Textract async-only processing
- No scanned PDF detection or fallbacks
- Automatic job polling with non-blocking workers

**Entity Extraction** (`scripts/entity_service.py`):
- OpenAI integration with quota management
- Batch processing for efficiency
- Automatic database persistence

**Caching** (`scripts/cache.py`):
- Redis Cloud integration
- Pipeline state tracking
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
S3_BUCKET_REGION=us-east-2  # Must match actual bucket region

# Redis
REDIS_HOST=
REDIS_PORT=
REDIS_PASSWORD=

# OpenAI
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o-mini

# Pipeline Configuration
ENABLE_SCANNED_PDF_DETECTION=false  # Critical: must be false
SKIP_PDF_PREPROCESSING=true
FORCE_PROCESSING=true
SKIP_CONFORMANCE_CHECK=true  # For minimal models

# Deployment
DEPLOYMENT_STAGE=1  # 1=Cloud, 2=Hybrid, 3=Local
```

### Deployment Stages
- **Stage 1**: Cloud-only (OpenAI/Textract) - Current production
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
- `textract_jobs`: OCR job tracking

## Current Issues and Solutions

### Entity Extraction Not Triggering
The pipeline currently stops after chunking. To fix:
1. Check task chaining in `continue_pipeline_after_ocr`
2. Ensure `extract_entities_from_chunks` is called after chunking
3. Verify OpenAI credentials are available to workers

### Textract Configuration
- Must use async-only processing (no sync fallbacks)
- Region must match S3 bucket region (us-east-2)
- No scanned PDF detection or image conversion

## Monitoring

Use the unified monitor for real-time insights:
```bash
# Live monitoring dashboard
python scripts/cli/monitor.py live

# Check specific document status
python scripts/cli/monitor.py doc-status <document_id>

# Worker health check
python scripts/cli/monitor.py health

# Check logs
tail -f monitoring/logs/pipeline_$(date +%Y%m%d).log
tail -f monitoring/logs/errors_$(date +%Y%m%d).log
```

## Performance Considerations

- Redis caching reduces database load by 90%+
- Chunking strategy optimized for legal documents (4-6 chunks typical)
- Batch operations for entity extraction
- Connection pooling for all external services
- Worker memory limit: 512MB per worker

## Development Guidelines

- Plan and carefully consider each script in the context of the whole
- Prefer simple solutions that produce reliable functioning code
- Always document on an ongoing basis any planning, conceptualization and verification of outcomes as a new note in /ai_docs/ subdirectory
- Each note should be context_[k+1]_[description].md
- Do not create scripts to get around issues. Fix the root cause in existing scripts
- Do not create new scripts. Use only the existing scripts. Modify them to work properly

## Critical Implementation Notes

### Entity Resolution NoneType Fix
When implementing entity resolution, ensure all entity texts are validated:
```python
# In resolve_entities_simple function, add null checks:
text1 = mention1.get('entity_text') or mention1.get('text')
text2 = mention2.get('entity_text') or mention2.get('text')
if not text1 or not text2:
    continue  # Skip entities with null text
```

### Model Type Conversions
Entity extraction returns ExtractedEntity but database expects EntityMentionMinimal. Convert between them:
```python
# Convert EntityMentionMinimal to ExtractedEntity for result model
extracted = ExtractedEntity(
    text=entity.entity_text,
    type=entity.entity_type,
    start_offset=entity.start_char,
    end_offset=entity.end_char,
    confidence=entity.confidence_score,
    attributes={
        "mention_uuid": str(entity.mention_uuid),
        "chunk_uuid": str(entity.chunk_uuid),
        "document_uuid": str(entity.document_uuid)
    }
)
```

### Pipeline Recovery Philosophy
After code consolidation, some modules are expected to be missing. The solution is NOT to recreate them but to:
1. Implement missing functionality inline where needed
2. Keep each script focused on its single responsibility
3. Maintain the clean architecture achieved through consolidation

## Memory Management

- Actively manage your memory and context using /ai_docs/
- Store plans, concepts, notes and results in dedicated documentation files

## Development Principles

- The consolidated Pydantic models in `scripts/models.py` are the single source of truth
- All models use minimal fields based on actual production usage
- Database column names must match model field names exactly
- Use backward compatibility properties for smooth migration

## Minimal Models and Async Processing

### Consolidated Models (June 2025 Update)
All Pydantic models have been consolidated into a single file `scripts/models.py`:

**Available Models:**
- `SourceDocumentMinimal` - Document metadata (15 essential fields)
- `DocumentChunkMinimal` - Text chunks (9 fields, uses `char_start_index`/`char_end_index`)
- `EntityMentionMinimal` - Extracted entities (10 fields)
- `CanonicalEntityMinimal` - Deduplicated entities (10 fields, uses `canonical_name`)
- `RelationshipStagingMinimal` - Entity relationships (9 fields, no `relationship_uuid`)

**Import Pattern:**
```python
# Always import from scripts.models
from scripts.models import (
    SourceDocumentMinimal,
    DocumentChunkMinimal,
    EntityMentionMinimal,
    CanonicalEntityMinimal,
    RelationshipStagingMinimal,
    ProcessingStatus,
    ModelFactory
)
```

**Backward Compatibility:**
- `chunk.start_char` → maps to `chunk.char_start_index`
- `chunk.text_content` → maps to `chunk.text`
- `entity.entity_name` → maps to `entity.canonical_name`

See `ai_docs/context_419_model_consolidation_implementation_complete.md` for details.

### Async OCR Processing
The system uses asynchronous Textract processing to prevent worker blocking:
1. Submit document → Get job ID
2. Poll for completion (non-blocking)
3. Process results when ready
4. Pipeline continues automatically

See `ai_docs/context_431_textract_async_only_directive.md` for critical configuration.

## CODEBASE MAINTENANCE DIRECTIVE

### FILE CREATION RESTRICTIONS
- NEVER create test_*.py files in root directory or scripts/ directory
- NEVER create temporary debug files in production locations
- NEVER create one-off experimental scripts
- ALL tests must go in organized tests/ structure

### TEST ORGANIZATION REQUIREMENTS
- Unit tests: tests/unit/ (isolated component testing)
- Integration tests: tests/integration/ (multi-component interactions)
- E2E tests: tests/e2e/ (full pipeline scenarios)
- Use pytest framework exclusively
- All tests must have clear docstrings explaining purpose

### CORE SCRIPT PROTECTION
- scripts/ directory contains ONLY production code
- Modifications to core scripts must be minimal and well-documented
- New functionality added through configuration, not new files
- Core scripts: celery_app.py, pdf_tasks.py, textract_utils.py, db.py, cache.py, entity_service.py

### DEBUGGING PROTOCOL
- For debugging: use existing tests in tests/ structure
- For exploration: create temporary files with explicit deletion plan
- For verification: add to existing test suites, don't create new files
- Document debugging findings in ai_docs/ context files

### WHEN TO CREATE NEW FILES
- Only when implementing new core functionality
- Only when approved through architectural review
- Only when no existing file can be extended
- Must follow established naming conventions

### CLEANUP RESPONSIBILITY
- Always clean up temporary files
- Archive obsolete code instead of leaving in place
- Consolidate duplicate functionality
- Maintain documentation of changes

### ERROR RESPONSE
If you find yourself creating test_*.py files outside tests/ structure, STOP and:
1. Explain why existing test structure doesn't meet needs
2. Propose proper location in tests/ hierarchy
3. Get approval before proceeding

REMEMBER: This is production code serving legal document processing. Maintain discipline and organization at all times.