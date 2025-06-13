# Context 523: Monitor Update Recommendations - Comprehensive Overhaul Plan

**Date**: 2025-06-13 04:50 UTC  
**Purpose**: Provide detailed recommendations for updating the monitor to accurately reflect current system state  
**Priority**: High - Monitor is primary visibility tool for batch processing

## Executive Summary

The monitor application requires significant updates to align with the current codebase. Key issues include incorrect table/column references, missing async OCR tracking, and lack of visibility into the actual processing bottleneck. This document provides a comprehensive update plan.

## Current System Status Summary

### Redis Cache Status
- **Architecture**: All databases on DB 0 (not separated)
- **Key Patterns**: 
  - `doc:state:*` - Document processing state
  - `doc:ocr:*` - OCR results cache
  - `batch:progress:*` - Batch job tracking
  - `rate:limit:*` - API rate limiting
- **Performance**: Operational with good hit rates

### Processing Stage Status
- **Stage 1 (OCR)**: Initiating successfully, but async polling broken in batch
- **Stage 2 (Chunking)**: Failing - missing text parameter from OCR
- **Stage 3 (Entity Extraction)**: Working but with memory errors
- **Stage 4 (Resolution)**: Functional with fuzzy matching
- **Stage 5 (Relationships)**: Limited by FK constraints
- **Stage 6 (Finalization)**: Not reached due to early failures

### Database Output Status
- **source_documents**: 459 documents in "pending" status
- **processing_tasks**: Shows OCR tasks started
- **textract_jobs**: Active jobs awaiting completion
- **document_chunks**: Empty (chunking failing)
- **entity_mentions**: Sparse (few documents complete)
- **canonical_entities**: Limited data
- **relationship_staging**: Minimal relationships

## Monitor Update Recommendations

### 1. Fix Database Queries

#### Current (Incorrect)
```python
# From monitor.py
query = """
SELECT sd.document_id, sd.processing_status, ...
FROM source_documents sd
"""
```

#### Updated (Correct)
```python
query = """
SELECT 
    sd.document_uuid,
    sd.status,
    sd.project_uuid,
    sd.created_at,
    sd.updated_at,
    pt.task_type as current_stage,
    pt.status as stage_status,
    tj.job_id as textract_job_id,
    tj.status as ocr_status
FROM source_documents sd
LEFT JOIN processing_tasks pt ON sd.document_uuid = pt.document_id 
    AND pt.created_at = (
        SELECT MAX(created_at) 
        FROM processing_tasks 
        WHERE document_id = sd.document_uuid
    )
LEFT JOIN textract_jobs tj ON sd.document_uuid = tj.document_uuid
WHERE sd.created_at > NOW() - INTERVAL '24 hours'
ORDER BY sd.created_at DESC
"""
```

### 2. Add Async OCR Tracking

```python
def get_ocr_status(self) -> Dict:
    """Track Textract job status."""
    query = """
    SELECT 
        status,
        COUNT(*) as count,
        AVG(EXTRACT(EPOCH FROM (NOW() - created_at))) as avg_wait_time
    FROM textract_jobs
    WHERE created_at > NOW() - INTERVAL '1 hour'
    GROUP BY status
    """
    
    results = execute_query(query)
    return {
        'active_jobs': sum(r['count'] for r in results if r['status'] in ['PENDING', 'IN_PROGRESS']),
        'completed_jobs': sum(r['count'] for r in results if r['status'] == 'SUCCEEDED'),
        'failed_jobs': sum(r['count'] for r in results if r['status'] == 'FAILED'),
        'avg_wait_time': max(r['avg_wait_time'] for r in results) if results else 0
    }
```

### 3. Fix Redis Monitoring

```python
def get_redis_stats(self) -> Dict:
    """Get Redis statistics with correct DB configuration."""
    stats = {}
    
    # All databases are on DB 0
    try:
        # Document states
        doc_states = len(self.redis_client.keys("doc:state:*"))
        
        # Batch progress
        batch_keys = self.redis_client.keys("batch:progress:*")
        active_batches = 0
        for key in batch_keys:
            try:
                data = self.redis_client.get(key)
                if data:
                    batch_data = json.loads(data)
                    if batch_data.get('status') == 'processing':
                        active_batches += 1
            except:
                pass
        
        # Rate limiting
        rate_limit_keys = len(self.redis_client.keys("rate:limit:*"))
        
        stats = {
            'document_states': doc_states,
            'active_batches': active_batches,
            'rate_limited_endpoints': rate_limit_keys,
            'cache_info': self.redis_client.info()
        }
    except Exception as e:
        logger.error(f"Redis stats error: {e}")
        
    return stats
```

### 4. Add Pipeline Bottleneck Detection

```python
def identify_bottlenecks(self) -> Dict:
    """Identify where documents are getting stuck."""
    
    # Check for stuck OCR jobs
    stuck_ocr_query = """
    SELECT COUNT(*) as count
    FROM processing_tasks pt
    JOIN textract_jobs tj ON pt.document_id = tj.document_uuid
    WHERE pt.task_type = 'extract_text'
    AND pt.status = 'completed'
    AND tj.status IN ('PENDING', 'IN_PROGRESS')
    AND tj.created_at < NOW() - INTERVAL '30 minutes'
    """
    
    # Check for missing chunk tasks
    missing_chunks_query = """
    SELECT COUNT(*) as count
    FROM source_documents sd
    LEFT JOIN document_chunks dc ON sd.document_uuid = dc.document_uuid
    WHERE sd.status = 'pending'
    AND dc.chunk_uuid IS NULL
    AND sd.created_at < NOW() - INTERVAL '1 hour'
    """
    
    # Check for batch processor errors
    batch_errors_query = """
    SELECT task_type, error_message, COUNT(*) as count
    FROM processing_tasks
    WHERE status = 'failed'
    AND created_at > NOW() - INTERVAL '1 hour'
    GROUP BY task_type, error_message
    ORDER BY count DESC
    LIMIT 5
    """
    
    return {
        'stuck_ocr_jobs': execute_query(stuck_ocr_query)[0]['count'],
        'missing_chunks': execute_query(missing_chunks_query)[0]['count'],
        'recent_errors': execute_query(batch_errors_query)
    }
```

### 5. Enhanced Live Dashboard

```python
def render_live_dashboard(self):
    """Enhanced dashboard with better visibility."""
    
    console = Console()
    
    while True:
        console.clear()
        
        # Header
        console.print(Panel.fit("📊 Legal Document Pipeline Monitor", style="bold blue"))
        
        # System Health
        health = self.get_health_status()
        health_table = Table(title="System Health")
        health_table.add_column("Component", style="cyan")
        health_table.add_column("Status", style="green")
        health_table.add_row("Database", "✅ Connected" if health['database'] else "❌ Disconnected")
        health_table.add_row("Redis", "✅ Connected" if health['redis'] else "❌ Disconnected")
        health_table.add_row("Workers", f"✅ {health['workers']} active" if health['workers'] > 0 else "❌ No workers")
        console.print(health_table)
        
        # OCR Status
        ocr_status = self.get_ocr_status()
        ocr_table = Table(title="🔍 OCR Processing")
        ocr_table.add_column("Metric", style="cyan")
        ocr_table.add_column("Value", style="yellow")
        ocr_table.add_row("Active Jobs", str(ocr_status['active_jobs']))
        ocr_table.add_row("Completed", str(ocr_status['completed_jobs']))
        ocr_table.add_row("Failed", str(ocr_status['failed_jobs']))
        ocr_table.add_row("Avg Wait Time", f"{ocr_status['avg_wait_time']:.1f}s")
        console.print(ocr_table)
        
        # Pipeline Stages
        pipeline_stats = self.get_pipeline_statistics()
        stage_table = Table(title="📈 Pipeline Stages")
        stage_table.add_column("Stage", style="cyan")
        stage_table.add_column("Pending", style="yellow")
        stage_table.add_column("Processing", style="blue")
        stage_table.add_column("Completed", style="green")
        stage_table.add_column("Failed", style="red")
        
        for stage in ['ocr', 'chunking', 'entity_extraction', 'resolution', 'relationships', 'finalization']:
            stats = pipeline_stats.get(stage, {})
            stage_table.add_row(
                stage.title(),
                str(stats.get('pending', 0)),
                str(stats.get('processing', 0)),
                str(stats.get('completed', 0)),
                str(stats.get('failed', 0))
            )
        console.print(stage_table)
        
        # Bottleneck Detection
        bottlenecks = self.identify_bottlenecks()
        if bottlenecks['stuck_ocr_jobs'] > 0 or bottlenecks['missing_chunks'] > 0:
            console.print(Panel(
                f"⚠️  BOTTLENECKS DETECTED:\n"
                f"- {bottlenecks['stuck_ocr_jobs']} OCR jobs stuck\n"
                f"- {bottlenecks['missing_chunks']} documents missing chunks\n"
                f"- Recent errors: {len(bottlenecks['recent_errors'])}",
                style="bold red"
            ))
        
        # Batch Progress
        batch_progress = self.get_batch_progress()
        if batch_progress:
            batch_table = Table(title="📦 Active Batches")
            batch_table.add_column("Batch ID", style="cyan")
            batch_table.add_column("Progress", style="yellow")
            batch_table.add_column("Status", style="green")
            
            for batch_id, progress in batch_progress.items():
                batch_table.add_row(
                    batch_id[:8],
                    f"{progress.get('completed', 0)}/{progress.get('total', 0)}",
                    progress.get('status', 'unknown')
                )
            console.print(batch_table)
        
        time.sleep(self.refresh_interval)
```

## Monitoring Targets

### Key Metrics to Track

1. **OCR Pipeline Health**
   - Textract job completion rate
   - Average OCR processing time
   - Stuck job detection (>30 min)

2. **Document Flow**
   - Documents per stage
   - Stage transition times
   - Bottleneck identification

3. **Error Tracking**
   - Error rate by stage
   - Common error patterns
   - Memory error frequency

4. **Resource Utilization**
   - Redis memory usage
   - Worker CPU/memory
   - Queue depths

5. **Batch Performance**
   - Batch completion rate
   - Documents per minute
   - Failed document recovery

### Alert Thresholds

```python
ALERT_THRESHOLDS = {
    'stuck_ocr_minutes': 30,
    'error_rate_percent': 5,
    'queue_depth_max': 1000,
    'memory_usage_percent': 80,
    'worker_min_count': 1
}
```

## Implementation Priority

### Phase 1: Critical Fixes (Immediate)
1. Fix SQL queries to use correct column names
2. Add Textract job monitoring
3. Fix Redis connection to use DB 0
4. Remove deprecated module imports

### Phase 2: Enhanced Visibility (Next Session)
1. Add bottleneck detection
2. Implement stage-specific monitoring
3. Create batch progress tracking
4. Add error categorization

### Phase 3: Advanced Features (Future)
1. Historical trend analysis
2. Predictive completion times
3. Auto-scaling recommendations
4. Slack/email alerts

## Testing the Updated Monitor

```bash
# Test individual components
python -c "from scripts.cli.monitor import UnifiedMonitor; m = UnifiedMonitor(); print(m.get_health_status())"

# Run updated monitor
python scripts/cli/monitor.py live

# Verify specific commands
python scripts/cli/monitor.py pipeline
python scripts/cli/monitor.py workers
python scripts/cli/monitor.py cache
```

## Conclusion

The monitor needs significant updates to accurately reflect the current system architecture. The primary focus should be on tracking the async OCR pipeline and identifying where documents get stuck in the batch processing chain. With these updates, operators will have clear visibility into system health and processing bottlenecks.