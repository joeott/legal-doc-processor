# Celery Integration for NLP Document Processing Pipeline

This document describes the Celery-based distributed task queue implementation for the document processing pipeline.

## Overview

The pipeline has been refactored from a monolithic `main_pipeline.py` to a distributed Celery-based system with the following benefits:

- **Scalability**: Easy horizontal scaling by adding more workers
- **Reliability**: Built-in retry mechanisms with exponential backoff
- **Monitoring**: Real-time task monitoring via Flower dashboard
- **Flexibility**: Different worker types optimized for specific tasks
- **Fault Tolerance**: Tasks automatically retry on failure

## Architecture

### Task Flow

```
Document Upload → Queue Processor → Celery Tasks:
                                    ├─→ OCR Task (process_ocr)
                                    ├─→ Text Processing Task (create_document_node, process_chunking)
                                    ├─→ Entity Extraction Task (extract_entities, resolve_entities)
                                    └─→ Graph Building Task (build_relationships)
```

### Task Queues

- **ocr**: Heavy OCR processing (Textract, audio transcription)
- **text**: Text processing and chunking
- **entity**: Entity extraction and resolution
- **graph**: Relationship building
- **default**: General tasks

## Quick Start

### 1. Start Redis (Required)

```bash
# Using Docker
docker run -d -p 6379:6379 redis:alpine

# Or using local Redis
redis-server
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Start Celery Workers

```bash
# Start all workers
./scripts/start_celery_workers.sh

# Start with Flower monitoring
./scripts/start_celery_workers.sh --with-flower
```

### 4. Start Queue Processor

```bash
python scripts/queue_processor.py
```

### 5. Monitor Progress

- Flower Dashboard: http://localhost:5555
- Command Line: `./scripts/monitor_celery_workers.sh`
- Live Monitor: `python monitoring/live_monitor.py`

## Worker Configuration

### OCR Worker
- **Concurrency**: 2 (CPU-intensive)
- **Pool**: prefork
- **Tasks**: PDF OCR, audio transcription

### Text Worker
- **Concurrency**: 4
- **Pool**: prefork
- **Tasks**: Document cleaning, chunking

### Entity Worker
- **Concurrency**: 100 (I/O-bound)
- **Pool**: gevent
- **Tasks**: NER, entity resolution

### Graph Worker
- **Concurrency**: 4
- **Pool**: prefork
- **Tasks**: Relationship building

## Task Details

### OCR Tasks (`scripts/celery_tasks/ocr_tasks.py`)

**process_ocr**: Main OCR task
- Handles PDF (Textract), DOCX, TXT, EML, audio files
- Retries: 3 times with exponential backoff
- Chains to: `create_document_node`

**check_textract_job_status**: Async Textract monitoring
- Polls Textract job status
- Retries: 5 times with 5-minute intervals

### Text Tasks (`scripts/celery_tasks/text_tasks.py`)

**create_document_node**: Creates Neo4j document entry
- Cleans text and categorizes document
- Chains to: `process_chunking`

**process_chunking**: Semantic text chunking
- Creates chunks with embeddings
- Chains to: `extract_entities`

### Entity Tasks (`scripts/celery_tasks/entity_tasks.py`)

**extract_entities**: NER from chunks
- Uses OpenAI or local models
- Creates entity mentions
- Chains to: `resolve_entities`

**resolve_entities**: Entity canonicalization
- Groups related entities
- Chains to: `build_relationships`

### Graph Tasks (`scripts/celery_tasks/graph_tasks.py`)

**build_relationships**: Creates graph relationships
- Links documents, chunks, entities
- Marks processing complete

## Migration Guide

### Migrate Existing Documents

```bash
# Dry run to see what would be migrated
python scripts/migrate_to_celery.py --dry-run

# Migrate all pending documents
python scripts/migrate_to_celery.py

# Include stalled documents (processing > 24 hours)
python scripts/migrate_to_celery.py --include-stalled

# Migrate specific statuses
python scripts/migrate_to_celery.py --status pending ocr_failed
```

## Production Deployment

### Systemd Service

```bash
# Copy service file
sudo cp scripts/celery-nlp.service /etc/systemd/system/

# Copy configuration
sudo mkdir -p /etc/nlp-pipeline
sudo cp scripts/celery.conf.template /etc/nlp-pipeline/celery.conf
# Edit /etc/nlp-pipeline/celery.conf with your settings

# Enable and start service
sudo systemctl enable celery-nlp
sudo systemctl start celery-nlp
```

### Docker Deployment

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY scripts/ scripts/
COPY monitoring/ monitoring/

# Start workers
CMD ["celery", "-A", "scripts.celery_app", "worker", "--loglevel=INFO"]
```

## Monitoring & Debugging

### Check Worker Status

```bash
# Show active workers
celery -A scripts.celery_app inspect active

# Show registered tasks
celery -A scripts.celery_app inspect registered

# Show task statistics
celery -A scripts.celery_app inspect stats
```

### Debug Failed Tasks

```python
# Check task result
from scripts.celery_app import app
result = app.AsyncResult('task-id-here')
print(result.state, result.info)

# Retry failed task
result.retry()
```

### Redis Monitoring

```bash
# Monitor Redis keys
redis-cli monitor | grep celery

# Check queue lengths
redis-cli llen celery:queue:ocr
redis-cli llen celery:queue:text
```

## Configuration

### Environment Variables

```bash
# Redis
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=your-password

# Celery
CELERY_REDIS_URL=redis://localhost:6379/0

# Task limits
CELERY_TASK_SOFT_TIME_LIMIT=3600
CELERY_TASK_TIME_LIMIT=3900
```

### Celery Settings (`scripts/celery_app.py`)

- `task_acks_late=True`: Acknowledge after completion
- `worker_prefetch_multiplier=1`: One task at a time for long tasks
- `task_track_started=True`: Track when tasks start
- `result_expires=604800`: Keep results for 7 days

## Testing

### Unit Tests

```bash
pytest tests/unit/test_celery_tasks.py -v
```

### Integration Tests

```bash
pytest tests/integration/test_celery_pipeline.py -v
```

### Load Testing

```python
# Enqueue multiple documents
from scripts.celery_tasks.ocr_tasks import process_ocr

for i in range(100):
    process_ocr.delay(
        document_uuid=f"test-{i}",
        source_doc_sql_id=i,
        file_path=f"test-{i}.pdf",
        file_name=f"test-{i}.pdf",
        detected_file_type=".pdf",
        project_sql_id=1
    )
```

## Troubleshooting

### Workers Not Starting

1. Check Redis connection: `redis-cli ping`
2. Check Python path: `export PYTHONPATH=/path/to/project`
3. Check logs: `tail -f logs/celery-*.log`

### Tasks Not Processing

1. Check worker queues: `celery -A scripts.celery_app inspect active_queues`
2. Check for errors: `celery -A scripts.celery_app events`
3. Verify task registration: `celery -A scripts.celery_app inspect registered`

### Memory Issues

1. Restart workers periodically: `worker_max_tasks_per_child=50`
2. Use gevent for I/O tasks: `--pool=gevent`
3. Monitor with: `celery -A scripts.celery_app inspect memory`

### Performance Tuning

1. Adjust concurrency: `--concurrency=N`
2. Use appropriate pool:
   - CPU-bound: `--pool=prefork`
   - I/O-bound: `--pool=gevent` or `--pool=eventlet`
3. Enable task compression for large payloads

## Best Practices

1. **Task Design**
   - Keep tasks focused and atomic
   - Pass IDs, not large objects
   - Use task chains for workflows

2. **Error Handling**
   - Always set `max_retries`
   - Use exponential backoff
   - Log errors with context

3. **Monitoring**
   - Use Flower in production
   - Set up alerts for failed tasks
   - Monitor queue lengths

4. **Security**
   - Use Redis AUTH
   - Enable SSL for Redis Cloud
   - Restrict Flower access

## Support

For issues or questions:
1. Check logs in `logs/` directory
2. Review Celery documentation: https://docs.celeryproject.org/
3. Check task status in Flower dashboard
4. Review error details in Supabase `document_processing_history` table