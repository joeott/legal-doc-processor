# Context 505: Comprehensive Worker Configuration Analysis and Recommendations

## Date: 2025-06-11
## Author: System Architecture Analysis

## Executive Summary

This document provides a detailed analysis of the Celery worker configuration for the legal document processing pipeline, including current issues, architectural considerations, and specific recommendations for optimal performance and reliability.

## Current State Analysis

### 1. Queue Architecture

The system implements a sophisticated multi-queue architecture with task-specific routing:

```python
# From scripts/celery_app.py (lines 110-146)
task_routes={
    # Core processing tasks
    'scripts.pdf_tasks.extract_text_from_document': {'queue': 'ocr'},
    'scripts.pdf_tasks.chunk_document_text': {'queue': 'text'},
    'scripts.pdf_tasks.extract_entities_from_chunks': {'queue': 'entity'},
    'scripts.pdf_tasks.resolve_entities_simple': {'queue': 'entity'},
    'scripts.pdf_tasks.resolve_document_entities': {'queue': 'entity'},
    'scripts.pdf_tasks.build_document_relationships': {'queue': 'graph'},
    
    # Orchestration
    'scripts.pdf_tasks.process_pdf_document': {'queue': 'default'},
    'scripts.pdf_tasks.continue_pipeline_after_ocr': {'queue': 'default'},
    'scripts.pdf_tasks.finalize_document_pipeline': {'queue': 'default'},
    
    # Batch processing with priority
    'scripts.batch_tasks.process_batch_high': {'queue': 'batch.high', 'priority': 9},
    'scripts.batch_tasks.process_batch_normal': {'queue': 'batch.normal', 'priority': 5},
    'scripts.batch_tasks.process_batch_low': {'queue': 'batch.low', 'priority': 1},
}
```

### 2. Memory Configuration Evidence

```python
# From scripts/celery_app.py (lines 17-20)
# Memory limit configuration
WORKER_MAX_MEMORY_MB = 512  # 512MB per worker
WORKER_MEMORY_LIMIT = WORKER_MAX_MEMORY_MB * 1024 * 1024  # Convert to bytes
```

Worker configuration shows careful memory management:
```python
# From scripts/celery_app.py (lines 78-87)
app.conf.update(
    # Worker settings
    worker_prefetch_multiplier=1,  # Process one task at a time
    task_acks_late=True,           # Acknowledge after completion
    worker_max_tasks_per_child=50, # Restart worker after 50 tasks to prevent memory leaks
    worker_max_memory_per_child=200000,  # Restart worker after 200MB (in KB)
    
    # Task execution limits
    task_soft_time_limit=240,      # 4 minute soft limit
    task_time_limit=300,           # 5 minute hard limit
)
```

### 3. Production Test Findings

From our production test (Context 504), we discovered:

```
# Current worker configuration (INSUFFICIENT)
ubuntu    279458  ... celery -A scripts.celery_app worker --loglevel=info --queues=default,ocr,text,entity,graph,cleanup
```

**Critical Issue**: No workers listening to batch queues, causing batch processing failure:
```
2025-06-11 20:17:54,403 - __main__ - INFO - Batch submitted successfully:
2025-06-11 20:17:54,403 - __main__ - INFO -   Batch ID: 7bfd9fb9-1975-457a-886f-24cff2d6f9f3
2025-06-11 20:17:54,403 - __main__ - INFO -   Task ID: 24b47ec1-2efb-41ff-bd5c-a0b9b7047ec8
2025-06-11 20:17:54,403 - __main__ - INFO -   Priority: high
[Test timeout - no workers processing batch.high queue]
```

### 4. Supervisor Configuration Analysis

From `scripts/supervisor_celery_config.conf`:

```ini
# OCR Worker - Heavy memory usage for document processing
[program:celery_ocr_worker]
command=/usr/bin/celery -A scripts.celery_app worker -Q ocr -n worker.ocr@%%h --concurrency=1 --max-memory-per-child=1000000
numprocs=1
autostart=true
autorestart=true
startsecs=10
stopwaitsecs=600
killasgroup=true

# Text Worker - Moderate memory for chunking
[program:celery_text_worker]
command=/usr/bin/celery -A scripts.celery_app worker -Q text -n worker.text@%%h --concurrency=2 --max-memory-per-child=500000
numprocs=1

# Entity Worker - High memory for NLP/AI operations
[program:celery_entity_worker]
command=/usr/bin/celery -A scripts.celery_app worker -Q entity -n worker.entity@%%h --concurrency=1 --max-memory-per-child=800000
numprocs=1
```

## Architectural Considerations

### 1. Task Dependencies and Flow

The pipeline follows a strict sequential flow with dependencies:

```
┌─────────────────┐
│ process_pdf_doc │ (default queue)
└────────┬────────┘
         │
    ┌────▼─────┐
    │   OCR    │ (ocr queue) - Memory intensive
    └────┬─────┘
         │
    ┌────▼─────┐
    │ Chunking │ (text queue) - CPU bound
    └────┬─────┘
         │
    ┌────▼─────┐
    │ Entities │ (entity queue) - API intensive
    └────┬─────┘
         │
    ┌────▼─────┐
    │Resolution│ (entity queue) - Memory/CPU
    └────┬─────┘
         │
    ┌────▼─────┐
    │Relations │ (graph queue) - CPU bound
    └────┬─────┘
         │
    ┌────▼─────┐
    │Finalize  │ (default queue)
    └──────────┘
```

### 2. Resource Constraints

Based on EC2 t3.medium instance (2 vCPU, 3.7 GB RAM):

```python
# Total available memory: ~3.7 GB
# System overhead: ~0.7 GB
# Available for workers: ~3.0 GB

# Current memory allocation:
# - OCR worker: 1000 MB (1 concurrent)
# - Text worker: 500 MB × 2 = 1000 MB (2 concurrent)
# - Entity worker: 800 MB (1 concurrent)
# - Other workers: 500 MB each
# Total: ~3.3 GB (OVER LIMIT)
```

### 3. Queue Priority Analysis

From `scripts/batch_tasks.py`:

```python
# Priority levels defined in batch processing
@app.task(bind=True, base=BatchTask, queue='batch.high', priority=9)
def process_batch_high(self, batch_manifest: Dict[str, Any]) -> Dict[str, Any]:
    # High priority - urgent/time-sensitive batches

@app.task(bind=True, base=BatchTask, queue='batch.normal', priority=5)
def process_batch_normal(self, batch_manifest: Dict[str, Any]) -> Dict[str, Any]:
    # Normal priority - standard processing

@app.task(bind=True, base=BatchTask, queue='batch.low', priority=1)
def process_batch_low(self, batch_manifest: Dict[str, Any]) -> Dict[str, Any]:
    # Low priority - background/non-urgent
```

## Recommended Configuration

### 1. Optimal Worker Setup for Production

```bash
#!/bin/bash
# File: start_production_workers.sh

# Kill any existing workers
echo "Stopping existing workers..."
ps aux | grep "[c]elery" | awk '{print $2}' | xargs -r kill -9
sleep 5

# Set environment
source /opt/legal-doc-processor/.env

# Start specialized workers with optimal configuration

# 1. OCR Worker - Single concurrency, high memory
echo "Starting OCR worker..."
celery -A scripts.celery_app worker \
    -Q ocr \
    -n worker.ocr@%h \
    --concurrency=1 \
    --max-memory-per-child=800000 \
    --loglevel=info \
    > /var/log/celery/ocr_worker.log 2>&1 &

# 2. Text Processing Worker - Dual concurrency
echo "Starting text processing worker..."
celery -A scripts.celery_app worker \
    -Q text \
    -n worker.text@%h \
    --concurrency=2 \
    --max-memory-per-child=400000 \
    --loglevel=info \
    > /var/log/celery/text_worker.log 2>&1 &

# 3. Entity Worker - Single concurrency, moderate memory
echo "Starting entity worker..."
celery -A scripts.celery_app worker \
    -Q entity \
    -n worker.entity@%h \
    --concurrency=1 \
    --max-memory-per-child=600000 \
    --loglevel=info \
    > /var/log/celery/entity_worker.log 2>&1 &

# 4. Graph Worker - Single concurrency
echo "Starting graph worker..."
celery -A scripts.celery_app worker \
    -Q graph \
    -n worker.graph@%h \
    --concurrency=1 \
    --max-memory-per-child=400000 \
    --loglevel=info \
    > /var/log/celery/graph_worker.log 2>&1 &

# 5. Default/Orchestration Worker
echo "Starting default worker..."
celery -A scripts.celery_app worker \
    -Q default,cleanup \
    -n worker.default@%h \
    --concurrency=1 \
    --max-memory-per-child=300000 \
    --loglevel=info \
    > /var/log/celery/default_worker.log 2>&1 &

# 6. Batch Processing Workers (Critical Missing Component)
echo "Starting batch workers..."

# High priority batch worker
celery -A scripts.celery_app worker \
    -Q batch.high \
    -n worker.batch.high@%h \
    --concurrency=2 \
    --max-memory-per-child=300000 \
    --loglevel=info \
    > /var/log/celery/batch_high_worker.log 2>&1 &

# Normal priority batch worker
celery -A scripts.celery_app worker \
    -Q batch.normal \
    -n worker.batch.normal@%h \
    --concurrency=1 \
    --max-memory-per-child=300000 \
    --loglevel=info \
    > /var/log/celery/batch_normal_worker.log 2>&1 &

# Low priority batch worker (optional, can be combined with normal)
celery -A scripts.celery_app worker \
    -Q batch.low \
    -n worker.batch.low@%h \
    --concurrency=1 \
    --max-memory-per-child=200000 \
    --loglevel=info \
    > /var/log/celery/batch_low_worker.log 2>&1 &

echo "All workers started. Checking status..."
sleep 5
ps aux | grep "[c]elery.*worker" | wc -l
echo "workers running"
```

### 2. Supervisor Configuration (Recommended for Production)

```ini
# File: /etc/supervisor/conf.d/celery_workers.conf

[group:celery_workers]
programs=celery_ocr,celery_text,celery_entity,celery_graph,celery_default,celery_batch_high,celery_batch_normal

# OCR Worker - Optimized for Textract operations
[program:celery_ocr]
command=/usr/bin/celery -A scripts.celery_app worker -Q ocr -n worker.ocr@%%h --concurrency=1 --max-memory-per-child=800000
directory=/opt/legal-doc-processor
user=ubuntu
numprocs=1
stdout_logfile=/var/log/celery/ocr_worker.log
stderr_logfile=/var/log/celery/ocr_worker_error.log
autostart=true
autorestart=true
startsecs=10
stopwaitsecs=600
killasgroup=true
priority=999

# Batch High Priority Worker
[program:celery_batch_high]
command=/usr/bin/celery -A scripts.celery_app worker -Q batch.high -n worker.batch.high@%%h --concurrency=2 --max-memory-per-child=300000
directory=/opt/legal-doc-processor
user=ubuntu
numprocs=1
stdout_logfile=/var/log/celery/batch_high_worker.log
stderr_logfile=/var/log/celery/batch_high_worker_error.log
autostart=true
autorestart=true
startsecs=10
stopwaitsecs=60
killasgroup=true
priority=998

# Batch Normal Priority Worker
[program:celery_batch_normal]
command=/usr/bin/celery -A scripts.celery_app worker -Q batch.normal,batch.low -n worker.batch.normal@%%h --concurrency=1 --max-memory-per-child=300000
directory=/opt/legal-doc-processor
user=ubuntu
numprocs=1
stdout_logfile=/var/log/celery/batch_normal_worker.log
stderr_logfile=/var/log/celery/batch_normal_worker_error.log
autostart=true
autorestart=true
startsecs=10
stopwaitsecs=60
killasgroup=true
priority=997
```

### 3. Memory Allocation Strategy

```
Total Available: 3.7 GB
System Reserved: 0.7 GB
Worker Budget: 3.0 GB

Allocation:
├── OCR Worker:        800 MB (1 process)
├── Text Worker:       800 MB (2 × 400 MB)
├── Entity Worker:     600 MB (1 process)
├── Graph Worker:      400 MB (1 process)
├── Default Worker:    300 MB (1 process)
├── Batch High:        600 MB (2 × 300 MB)
└── Batch Normal/Low:  300 MB (1 process)
                      --------
Total:                3.0 GB (within budget)
```

### 4. Queue Processing Strategy

```python
# Recommended queue priorities and concurrency
QUEUE_CONFIG = {
    'ocr': {
        'concurrency': 1,      # Sequential to avoid Textract throttling
        'memory_limit': 800,   # MB - Large PDFs need memory
        'prefetch': 1,         # One at a time
        'timeout': 300         # 5 minutes for large documents
    },
    'text': {
        'concurrency': 2,      # Parallel chunking is safe
        'memory_limit': 400,   # MB per worker
        'prefetch': 2,         # Can prefetch
        'timeout': 120         # 2 minutes
    },
    'entity': {
        'concurrency': 1,      # API rate limits
        'memory_limit': 600,   # MB - NLP models
        'prefetch': 1,         # Avoid API throttling
        'timeout': 180         # 3 minutes
    },
    'graph': {
        'concurrency': 1,      # Database consistency
        'memory_limit': 400,   # MB
        'prefetch': 1,         
        'timeout': 120         # 2 minutes
    },
    'batch.high': {
        'concurrency': 2,      # Parallel batch coordination
        'memory_limit': 300,   # MB per worker
        'prefetch': 1,         
        'timeout': 60          # 1 minute for coordination
    },
    'batch.normal': {
        'concurrency': 1,      # Standard processing
        'memory_limit': 300,   # MB
        'prefetch': 1,         
        'timeout': 60          # 1 minute
    }
}
```

## Performance Optimization Strategies

### 1. Worker Pool Optimization

```python
# Add to celery_app.py for better performance
app.conf.update(
    # Connection pooling
    broker_pool_limit=50,  # Reduced from 100 for t3.medium
    redis_max_connections=50,
    
    # Task execution
    task_ignore_result=False,  # We need results for pipeline
    task_store_eager_result=True,
    
    # Optimized serialization
    task_serializer='json',
    result_serializer='json',
    accept_content=['json'],
    
    # Rate limiting for API calls
    task_annotations={
        'scripts.pdf_tasks.extract_entities_from_chunks': {
            'rate_limit': '30/m'  # 30 per minute for OpenAI
        },
        'scripts.pdf_tasks.extract_text_from_document': {
            'rate_limit': '10/m'  # 10 per minute for Textract
        }
    }
)
```

### 2. Circuit Breaker Implementation

From the codebase analysis:
```python
# PDFTask base class implements circuit breaker
class PDFTask(Task):
    """Base task class with circuit breaker pattern"""
    
    def __init__(self):
        super().__init__()
        self.failure_count = 0
        self.last_failure_time = None
        self.circuit_open = False
        self.failure_threshold = 5
        self.reset_timeout = 300  # 5 minutes
```

### 3. Monitoring and Health Checks

```bash
#!/bin/bash
# health_check.sh - Add to cron for every 5 minutes

# Check worker health
WORKER_COUNT=$(ps aux | grep "[c]elery.*worker" | wc -l)
EXPECTED_WORKERS=8

if [ $WORKER_COUNT -lt $EXPECTED_WORKERS ]; then
    echo "WARNING: Only $WORKER_COUNT workers running, expected $EXPECTED_WORKERS"
    # Restart workers
    supervisorctl restart celery_workers:*
fi

# Check queue depths
redis-cli -h $REDIS_HOST -a $REDIS_PASSWORD llen default
redis-cli -h $REDIS_HOST -a $REDIS_PASSWORD llen ocr
redis-cli -h $REDIS_HOST -a $REDIS_PASSWORD llen batch.high
```

## Scaling Considerations

### 1. Horizontal Scaling Strategy

For larger deployments:
```
t3.medium (current) → t3.large → t3.xlarge
2 vCPU, 4GB RAM → 2 vCPU, 8GB RAM → 4 vCPU, 16GB RAM
```

### 2. Multi-Instance Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Web/API   │     │  Worker 1   │     │  Worker 2   │
│  Instance   │     │  (OCR/Text) │     │(Entity/Graph)│
└──────┬──────┘     └──────┬──────┘     └──────┬──────┘
       │                   │                    │
       └───────────────────┴────────────────────┘
                           │
                    ┌──────▼──────┐
                    │    Redis    │
                    │   (Shared)  │
                    └─────────────┘
```

### 3. Queue-Specific Scaling

```python
# Scale based on queue depth
SCALING_THRESHOLDS = {
    'ocr': {
        'scale_up': 50,    # Queue depth to add worker
        'scale_down': 10,  # Queue depth to remove worker
        'max_workers': 3   # Maximum concurrent workers
    },
    'entity': {
        'scale_up': 100,   # Higher threshold due to API limits
        'scale_down': 20,
        'max_workers': 2
    },
    'batch.high': {
        'scale_up': 10,    # Quick response for high priority
        'scale_down': 2,
        'max_workers': 4
    }
}
```

## Troubleshooting Guide

### Common Issues and Solutions

1. **Workers Not Processing Batch Queues**
```bash
# Symptom: Batch submitted but not processed
# Check: redis-cli llen batch.high
# Fix: Ensure batch workers are running
ps aux | grep "batch\." || echo "No batch workers found!"
```

2. **Memory Errors**
```
# Symptom: Worker killed with signal 9
# Check: dmesg | grep "Out of memory"
# Fix: Reduce concurrency or memory limits
```

3. **Task Timeouts**
```python
# Symptom: Tasks timing out frequently
# Check: Logs for "SoftTimeLimitExceeded"
# Fix: Increase task_time_limit for specific queues
```

## Final Recommendations

1. **Immediate Actions**:
   - Implement the recommended worker configuration script
   - Set up supervisor for automatic worker management
   - Configure health monitoring

2. **Short-term Improvements**:
   - Implement rate limiting for API-dependent tasks
   - Add queue depth monitoring
   - Set up alerts for worker failures

3. **Long-term Optimization**:
   - Consider moving to container-based deployment (Docker/K8s)
   - Implement auto-scaling based on queue metrics
   - Separate API-intensive tasks to dedicated workers

## Conclusion

The current worker configuration lacks critical batch processing workers, leading to the production test failure. The recommended configuration provides:
- Complete queue coverage
- Optimized memory allocation for t3.medium instance
- Proper priority handling
- Resilience through supervisor management
- Clear scaling path for growth

Implementation of this configuration will ensure reliable processing of all document types through the complete pipeline.