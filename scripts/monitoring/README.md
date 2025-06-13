# Monitoring Scripts

Production monitoring utilities for the legal document processing pipeline.

## Scripts

### Pipeline Monitoring
- `monitor_full_pipeline.py` - Monitor complete pipeline execution
- `process_with_redis_monitoring.py` - Process documents with Redis monitoring enabled

### Performance Monitoring  
- `monitor_redis_acceleration.py` - Monitor Redis acceleration performance

### Worker Monitoring
- `monitor_workers.sh` - Check worker health and queue status

## Usage

```bash
# Monitor full pipeline
python scripts/monitoring/monitor_full_pipeline.py

# Check worker health
./scripts/monitoring/monitor_workers.sh

# Monitor Redis performance
python scripts/monitoring/monitor_redis_acceleration.py
```