# Batch Processing Guide

This guide covers the batch processing capabilities of the legal document processing pipeline, including priority-based processing, error recovery, metrics collection, and cache optimization.

## Table of Contents

1. [Overview](#overview)
2. [Batch Submission](#batch-submission)
3. [Priority Levels](#priority-levels)
4. [Cache Warming](#cache-warming)
5. [Monitoring and Metrics](#monitoring-and-metrics)
6. [Error Recovery](#error-recovery)
7. [Examples](#examples)

## Overview

The batch processing system provides:

- **Priority-based processing** with three levels (high, normal, low)
- **Parallel document processing** using Celery chord patterns
- **Automatic cache warming** for improved performance
- **Comprehensive metrics collection** for monitoring
- **Intelligent error recovery** with retry strategies
- **Real-time progress tracking** via Redis

## Batch Submission

### Basic Usage

```python
from scripts.batch_tasks import submit_batch

# Prepare documents
documents = [
    {
        'document_uuid': 'doc-123',
        'file_path': 's3://bucket/path/to/document.pdf'
    },
    # ... more documents
]

# Submit batch
result = submit_batch(
    documents=documents,
    project_uuid='project-456',
    priority='normal',  # 'high', 'normal', or 'low'
    options={
        'warm_cache': True,
        'entity_resolution': True
    }
)

print(f"Batch ID: {result['batch_id']}")
print(f"Task ID: {result['task_id']}")
```

### Batch Manifest Structure

```python
batch_manifest = {
    'batch_id': 'unique-batch-id',
    'documents': [
        {
            'document_uuid': 'doc-uuid',
            'file_path': 'path/to/file.pdf',
            # Optional fields:
            'metadata': {...}
        }
    ],
    'project_uuid': 'project-uuid',
    'options': {
        'warm_cache': True,  # Enable cache warming
        'entity_resolution': True,  # Enable entity resolution
        'max_retries': 3,  # Maximum retry attempts
        # ... other processing options
    }
}
```

## Priority Levels

### High Priority (9)
- For urgent/time-sensitive batches
- Immediate cache warming (synchronous)
- Processed before normal and low priority tasks
- Use sparingly for critical documents

### Normal Priority (5)
- Default priority level
- Standard cache warming
- Balanced processing speed
- Suitable for most use cases

### Low Priority (1)
- For background/non-urgent batches
- Asynchronous cache warming (doesn't wait)
- Processed when system is less busy
- Ideal for bulk historical processing

## Cache Warming

Cache warming pre-loads frequently accessed data before batch processing begins:

### Automatic Warming

```python
# Enabled by default for batches > 5 documents
options = {'warm_cache': True}
```

### Manual Warming

```python
from scripts.cache_warmer import warm_cache_before_batch

# Synchronous warming (waits for completion)
result = warm_cache_before_batch(batch_manifest, wait=True)

# Asynchronous warming (returns immediately)
warm_cache_before_batch(batch_manifest, wait=False)
```

### What Gets Warmed

1. **Project data** - Project metadata and settings
2. **Document metadata** - Existing document information
3. **Chunks** - Previously processed text chunks
4. **Entities** - Frequently referenced entities
5. **Resolution mappings** - Entity name to canonical entity mappings

## Monitoring and Metrics

### Real-time Progress Tracking

```python
from scripts.batch_tasks import get_batch_status

# Get current batch status
status = get_batch_status.apply_async(args=[batch_id]).get()

print(f"Status: {status['status']}")
print(f"Progress: {status['progress_percentage']}%")
print(f"Completed: {status['completed']}/{status['total']}")
print(f"Success Rate: {status['success_rate']}%")
print(f"ETA: {status.get('estimated_time_remaining', 'Unknown')}")
```

### Batch Metrics Collection

```python
from scripts.batch_metrics import BatchMetricsCollector

collector = BatchMetricsCollector()

# Get metrics for time range
metrics = collector.get_batch_metrics(start_time, end_time)

# Get performance report for specific batch
report = collector.get_performance_report(batch_id)

# Get error summary
errors = collector.get_error_summary(hours=24)
```

### Monitor Integration

The batch processing stats are integrated into the main monitor dashboard:

```bash
# View batch stats in live monitor
python scripts/cli/monitor.py live
```

## Error Recovery

### Automatic Recovery

The system automatically categorizes errors and determines retry strategies:

#### Error Categories

1. **TRANSIENT** - Network issues, timeouts (immediate retry)
2. **RESOURCE** - Memory/disk issues (linear backoff)
3. **RATE_LIMIT** - API limits (exponential backoff)
4. **CONFIGURATION** - Missing credentials (manual intervention)
5. **DATA** - Corrupt files (manual intervention)
6. **PERMANENT** - Unrecoverable errors (no retry)

### Manual Recovery

```python
from scripts.batch_recovery import recover_failed_batch, analyze_batch_failures

# Analyze failures
analysis = analyze_batch_failures.apply_async(args=[batch_id]).get()
print(f"Total failures: {analysis['total_failures']}")
print(f"Recoverable: {analysis['recoverable_count']}")

# Recover failed documents
result = recover_failed_batch.apply_async(
    args=[batch_id],
    kwargs={
        'options': {
            'max_retries': 3,
            'retry_all': False,  # Skip manual intervention errors
            'priority': 'high'   # Recovery priority
        }
    }
).get()

print(f"Recovery batch: {result['recovery_batch_id']}")
print(f"Documents retrying: {result['documents_to_retry']}")
```

### Recovery Strategies

| Strategy | Description | Use Case |
|----------|-------------|----------|
| IMMEDIATE | Retry right away | Network glitches |
| EXPONENTIAL | Double delay each retry | Rate limits |
| LINEAR | Fixed delay increase | Resource constraints |
| SCHEDULED | Retry at specific time | Maintenance windows |
| MANUAL | Requires intervention | Config/data errors |

## Examples

### Example 1: High-Priority Legal Brief Processing

```python
# Process urgent legal briefs with high priority
briefs = [
    {'document_uuid': str(uuid4()), 'file_path': f's3://legal-briefs/urgent/{i}.pdf'}
    for i in range(3)
]

result = submit_batch(
    documents=briefs,
    project_uuid='urgent-project',
    priority='high',
    options={
        'warm_cache': True,
        'entity_resolution': True,
        'max_retries': 5  # More retries for critical docs
    }
)

# Monitor closely
while True:
    status = get_batch_status.apply_async(args=[result['batch_id']]).get()
    if status['status'] == 'completed':
        break
    time.sleep(2)
```

### Example 2: Bulk Historical Document Import

```python
# Process large historical archive with low priority
archive_docs = load_archive_manifest()  # 1000+ documents

# Split into smaller batches
batch_size = 100
for i in range(0, len(archive_docs), batch_size):
    batch = archive_docs[i:i+batch_size]
    
    submit_batch(
        documents=batch,
        project_uuid='historical-archive',
        priority='low',
        options={
            'warm_cache': False,  # Skip for low priority
            'entity_resolution': True
        }
    )
```

### Example 3: Recovery with Custom Logic

```python
# Custom recovery for specific error types
def custom_recovery(batch_id):
    analysis = analyze_batch_failures.apply_async(args=[batch_id]).get()
    
    # Group failures by error type
    by_error = {}
    for doc in analysis['failed_documents']:
        error_type = doc['error_type']
        if error_type not in by_error:
            by_error[error_type] = []
        by_error[error_type].append(doc)
    
    # Handle rate limit errors differently
    if 'RateLimitError' in by_error:
        # Wait longer and retry with lower priority
        time.sleep(300)  # 5 minutes
        recover_failed_batch.apply_async(
            args=[batch_id],
            kwargs={
                'options': {
                    'priority': 'low',
                    'retry_all': False
                }
            }
        )
```

### Example 4: Performance Monitoring

```python
# Monitor batch performance over time
from datetime import datetime, timedelta
import matplotlib.pyplot as plt

collector = BatchMetricsCollector()

# Collect daily metrics for a week
daily_metrics = []
for days_ago in range(7, 0, -1):
    date = datetime.utcnow() - timedelta(days=days_ago)
    start = date.replace(hour=0, minute=0, second=0)
    end = start + timedelta(days=1)
    
    metrics = collector.get_batch_metrics(start, end)
    daily_metrics.append({
        'date': date.strftime('%Y-%m-%d'),
        'total': metrics['summary']['total_documents'],
        'success_rate': metrics['summary']['overall_success_rate']
    })

# Plot results
dates = [m['date'] for m in daily_metrics]
totals = [m['total'] for m in daily_metrics]
success_rates = [m['success_rate'] for m in daily_metrics]

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8))

ax1.bar(dates, totals)
ax1.set_ylabel('Documents Processed')
ax1.set_title('Daily Document Processing Volume')

ax2.plot(dates, success_rates, 'g-o')
ax2.set_ylabel('Success Rate (%)')
ax2.set_xlabel('Date')
ax2.set_ylim(0, 100)
ax2.set_title('Processing Success Rate')

plt.tight_layout()
plt.show()
```

## Best Practices

1. **Batch Size**: Keep batches between 10-100 documents for optimal performance
2. **Priority Usage**: Reserve high priority for truly urgent documents
3. **Cache Warming**: Enable for batches > 5 documents with repeated data access
4. **Error Handling**: Implement custom recovery logic for domain-specific errors
5. **Monitoring**: Use metrics to identify bottlenecks and optimize
6. **Resource Planning**: Monitor Redis memory usage when warming large batches

## Configuration

### Environment Variables

```bash
# Redis configuration for batch processing
REDIS_PREFIX_BATCH=batch:
REDIS_PREFIX_METRICS=metrics:

# Worker configuration
CELERY_WORKER_MAX_TASKS_PER_CHILD=50
CELERY_WORKER_MAX_MEMORY_PER_CHILD=200000

# Batch processing defaults
BATCH_DEFAULT_PRIORITY=normal
BATCH_CACHE_WARM_THRESHOLD=5
BATCH_METRICS_TTL_DAYS=7
```

### Celery Queue Configuration

```python
# In celery_app.py
task_routes = {
    'scripts.batch_tasks.process_batch_high': {'queue': 'batch.high', 'priority': 9},
    'scripts.batch_tasks.process_batch_normal': {'queue': 'batch.normal', 'priority': 5},
    'scripts.batch_tasks.process_batch_low': {'queue': 'batch.low', 'priority': 1},
}
```

### Worker Deployment

```bash
# Start workers for each priority queue
celery -A scripts.celery_app worker -Q batch.high -n batch-high@%h --concurrency=4
celery -A scripts.celery_app worker -Q batch.normal -n batch-normal@%h --concurrency=2
celery -A scripts.celery_app worker -Q batch.low -n batch-low@%h --concurrency=1
```

## Troubleshooting

### Common Issues

1. **Batch stuck in processing**
   - Check worker logs for errors
   - Verify Redis connectivity
   - Use `analyze_batch_failures` to identify issues

2. **High failure rate**
   - Review error categories in metrics
   - Check for rate limiting or resource constraints
   - Adjust retry strategies

3. **Slow processing**
   - Enable cache warming
   - Increase worker concurrency
   - Check for memory/CPU bottlenecks

4. **Memory issues with cache warming**
   - Reduce batch size
   - Disable cache warming for low priority
   - Monitor Redis memory usage

### Debug Commands

```bash
# Check batch status
redis-cli HGETALL "batch:progress:BATCH_ID"

# View batch errors
redis-cli ZRANGE "metrics:errors:HOUR_BUCKET" 0 -1

# Monitor worker activity
celery -A scripts.celery_app inspect active

# Check queue lengths
redis-cli LLEN "celery.batch.high"
```