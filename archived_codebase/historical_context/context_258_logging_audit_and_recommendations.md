# Logging Audit and Testing Recommendations

## Date: May 31, 2025
## Scope: /opt/legal-doc-processor/scripts Logging Infrastructure

## Executive Summary

The legal document processor has a sophisticated logging infrastructure with both basic and advanced features. However, several critical gaps exist that will impact debugging during testing. The system includes structured logging, performance tracking, and CloudWatch integration, but the log directories are not created, and error visibility could be significantly improved for rapid debugging.

## Current Logging Architecture

### 1. Core Logging Configuration (`logging_config.py`)

**Strengths:**
- Comprehensive logging setup with file rotation
- Separate error logs for quick error scanning
- Structured logging with JSON output
- Thread-safe context management
- Performance tracking with timing utilities
- Module-specific log directories

**Critical Issues:**
- Log directories are NOT created on disk (despite mkdir in code)
- Console output uses simple formatting (missing context)
- No log aggregation for distributed Celery workers
- Default log level is INFO (misses crucial DEBUG info)

### 2. Logging Usage Patterns

**Standard Python Logging:**
```python
import logging
logger = logging.getLogger(__name__)
```
- Used in: `pdf_tasks.py`, `cache.py`, `db.py`, `entity_service.py`, etc.
- Most modules use basic logging without structured context

**Structured Logging (Advanced):**
```python
from scripts.logging_config import get_module_logger
logger = get_module_logger(__name__, 'cache')
```
- Available but underutilized
- Provides timing, context, and performance metrics

### 3. Error Handling Infrastructure

**ErrorHandler Class (`core/error_handler.py`):**
- Sophisticated error categorization
- Recovery strategy recommendations
- Error pattern matching
- Database logging of errors
- Error report generation

**Issues:**
- Not integrated with main pipeline tasks
- Requires database connection (may fail during DB errors)
- No real-time error notifications

### 4. CloudWatch Integration

**CloudWatchLogger (`monitoring/cloudwatch_logger.py`):**
- Textract-specific logging
- Structured JSON logs
- API call tracking
- Performance metrics

**Limitations:**
- Only for Textract operations
- Requires AWS permissions
- No local fallback

## Critical Gaps for Testing

### 1. **Log Directory Creation Failure**
```bash
# Expected directories (from logging_config.py):
/opt/legal-doc-processor/monitoring/logs/
/opt/legal-doc-processor/monitoring/logs/cache/
/opt/legal-doc-processor/monitoring/logs/database/
# etc.

# Actual: NONE EXIST
```

### 2. **Missing Debug Information**
- No request/response logging for external APIs
- No SQL query logging
- No Redis command logging
- No detailed error stack traces in logs

### 3. **Celery Task Visibility**
- No task start/complete logging
- No task retry information
- No task performance metrics
- No worker identification

### 4. **Error Context Missing**
- Document UUID not consistently logged
- Processing stage not always identified
- No breadcrumb trail for debugging

## Recommendations for Testing Phase

### 1. **Immediate Fixes (Before Testing)**

```python
# Create enhanced logging setup script
# /opt/legal-doc-processor/scripts/setup_logging.py

import os
import logging
from pathlib import Path

def setup_test_logging():
    """Enhanced logging setup for testing."""
    # 1. Create all directories
    base_dir = Path("/opt/legal-doc-processor/monitoring/logs")
    subdirs = ['cache', 'database', 'entity', 'graph', 'pdf_tasks', 'tests']
    
    base_dir.mkdir(parents=True, exist_ok=True)
    for subdir in subdirs:
        (base_dir / subdir).mkdir(exist_ok=True)
    
    # 2. Set DEBUG level for testing
    logging.getLogger().setLevel(logging.DEBUG)
    
    # 3. Add console handler with detailed format
    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        '%(asctime)s [%(levelname)8s] %(name)s - %(funcName)s:%(lineno)d - %(message)s'
    )
    console.setFormatter(formatter)
    logging.getLogger().addHandler(console)
    
    # 4. Enable SQL logging
    logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)
    
    # 5. Enable Redis logging
    logging.getLogger('redis').setLevel(logging.DEBUG)
    
    print(f"✅ Logging configured for testing at: {base_dir}")
```

### 2. **Task Decorator for Visibility**

```python
# Add to pdf_tasks.py
from functools import wraps
import time

def log_task_execution(func):
    """Decorator to log task execution details."""
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        task_id = self.request.id
        doc_uuid = kwargs.get('document_uuid', 'unknown')
        
        logger.info(f"🚀 TASK START: {func.__name__} | Doc: {doc_uuid} | Task: {task_id}")
        start_time = time.time()
        
        try:
            result = func(self, *args, **kwargs)
            elapsed = time.time() - start_time
            logger.info(f"✅ TASK SUCCESS: {func.__name__} | Doc: {doc_uuid} | Time: {elapsed:.2f}s")
            return result
            
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"❌ TASK FAILED: {func.__name__} | Doc: {doc_uuid} | Time: {elapsed:.2f}s | Error: {str(e)}")
            logger.exception("Full traceback:")
            raise
    
    return wrapper
```

### 3. **Real-time Log Monitoring Script**

```python
# /opt/legal-doc-processor/scripts/monitor_logs.py

#!/usr/bin/env python3
import time
import os
from pathlib import Path

def tail_logs():
    """Monitor all log files in real-time."""
    log_dir = Path("/opt/legal-doc-processor/monitoring/logs")
    
    # Find today's logs
    from datetime import datetime
    date_str = datetime.now().strftime("%Y%m%d")
    
    log_files = list(log_dir.rglob(f"*{date_str}.log"))
    error_files = list(log_dir.rglob(f"errors_{date_str}.log"))
    
    print(f"Monitoring {len(log_files)} log files and {len(error_files)} error files...")
    
    # Use tail -f for real-time monitoring
    import subprocess
    cmd = ["tail", "-f"] + [str(f) for f in log_files + error_files]
    subprocess.run(cmd)
```

### 4. **Error Visibility Enhancements**

```python
# Add to each major function
def process_with_context(document_uuid: str, stage: str):
    """Enhanced error context for debugging."""
    try:
        logger.info(f"📄 Processing {document_uuid} - Stage: {stage}")
        # ... processing logic ...
        
    except Exception as e:
        # Log with full context
        logger.error(
            f"Failed processing document",
            extra={
                'document_uuid': document_uuid,
                'stage': stage,
                'error_type': type(e).__name__,
                'error_message': str(e),
                'traceback': traceback.format_exc()
            }
        )
        # Re-raise with context
        raise ProcessingError(f"{stage} failed for {document_uuid}: {str(e)}") from e
```

### 5. **Testing-Specific Configuration**

```python
# Add to .env for testing
LOG_LEVEL=DEBUG
LOG_TO_CONSOLE=true
LOG_SQL_QUERIES=true
LOG_REDIS_COMMANDS=true
LOG_API_CALLS=true
ENABLE_PERFORMANCE_LOGGING=true
```

### 6. **Quick Debugging Commands**

```bash
# View all errors from today
grep -h ERROR /opt/legal-doc-processor/monitoring/logs/*/errors_*.log | tail -50

# Track specific document
grep -r "document_uuid.*YOUR_UUID" /opt/legal-doc-processor/monitoring/logs/

# Monitor Celery tasks
grep -E "(TASK START|TASK SUCCESS|TASK FAILED)" /opt/legal-doc-processor/monitoring/logs/pdf_tasks/*.log

# Performance issues
grep -E "duration_seconds|elapsed|Time:" /opt/legal-doc-processor/monitoring/logs/*/*.log | awk '$NF > 5'
```

## Implementation Priority

1. **Critical (Do First):**
   - Create log directories
   - Set DEBUG logging level
   - Add task execution logging

2. **Important (For Debugging):**
   - Enable SQL/Redis logging
   - Add error context
   - Create monitoring script

3. **Nice to Have:**
   - CloudWatch integration
   - Performance dashboards
   - Log aggregation

## Testing Checklist

Before processing test documents:

- [ ] Run `setup_logging.py` to create directories
- [ ] Verify log files are being created
- [ ] Test error logging with intentional failure
- [ ] Confirm Celery task visibility
- [ ] Set up log monitoring terminal

## Summary

The logging infrastructure is well-designed but requires activation and enhancement for effective testing. The main issues are missing directories and insufficient debug visibility. Implementing the recommended changes will dramatically improve debugging speed during document processing tests.