# Utility Scripts

Diagnostic and maintenance utilities for the legal document processing system.

## Check Scripts

### Batch Processing
- `check_batch_details.py` - Detailed batch information
- `check_batch_simple.py` - Simple batch status check
- `check_batch_status.py` - Batch processing status

### Redis/Cache
- `check_all_redis_keys.py` - List all Redis keys
- `check_ocr_cache.py` - Check OCR cache status
- `check_redis_info.py` - Redis connection and info

### Pipeline/Tasks
- `check_pipeline_status.py` - Pipeline execution status
- `check_task_error.py` - Task error details

### Database
- `check_project_schema.py` - Project table schema verification

## Maintenance Scripts

- `clear_rds_test_data.py` - Clear test data from RDS
- `clear_redis_cache.py` - Clear Redis cache

## Usage

```bash
# Check batch status
python scripts/utilities/check_batch_status.py <batch_id>

# Clear test data
python scripts/utilities/clear_rds_test_data.py

# Check Redis keys
python scripts/utilities/check_all_redis_keys.py
```