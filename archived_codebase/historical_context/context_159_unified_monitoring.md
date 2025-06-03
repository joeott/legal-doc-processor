# Context 159: Unified Monitoring Solution

## Summary

Created a comprehensive unified monitoring script at `/scripts/cli/monitor.py` that consolidates all monitoring functionality into one reliable tool, addressing timeout issues and providing real-time pipeline visibility.

## Problem Addressed

- Multiple monitoring scripts causing confusion
- Celery worker timeouts when using monitoring tools
- Scattered monitoring functionality across different scripts
- Lack of comprehensive real-time monitoring

## Solution Implementation

### 1. Unified Monitor Script Location
```
/scripts/cli/monitor.py
```

### 2. Key Features

#### A. Live Dashboard Mode
```bash
# Real-time monitoring with auto-refresh
python scripts/cli/monitor.py live

# Custom refresh interval
python scripts/cli/monitor.py live --refresh 3

# Run once and exit
python scripts/cli/monitor.py live --once
```

#### B. Component-Specific Commands
```bash
# Pipeline statistics
python scripts/cli/monitor.py pipeline

# Celery worker status
python scripts/cli/monitor.py workers

# Redis cache statistics
python scripts/cli/monitor.py cache

# Document details
python scripts/cli/monitor.py document <uuid>

# System health check
python scripts/cli/monitor.py health
```

### 3. Technical Improvements

#### A. Timeout Handling
- Set 2-second timeout for Celery inspect operations
- Graceful fallback when operations timeout
- Non-blocking Redis operations with limits

#### B. Comprehensive Statistics
- Document status counts with emojis
- Processing stage detection
- Worker and queue monitoring
- Redis cache performance metrics
- Stuck document detection (>30 min)

#### C. Live Dashboard Layout
```
┌─────────────────────────────────────────┐
│  📊 Pipeline Monitor    2025-05-28      │
├──────────────┬──────────────────────────┤
│ Documents    │ Workers & System         │
│ ─────────    │ ────────────────         │
│ ✅ Complete  │ Workers: 2 active        │
│ 🔄 Process   │ Queues: OCR(5), Text(2)  │
│ ❌ Failed    │ Redis: 45MB, 95% hit     │
└──────────────┴──────────────────────────┘
```

### 4. Error Handling

- Connection failures handled gracefully
- Warning messages for degraded functionality
- Health check command for quick diagnostics

### 5. Usage Examples

#### Monitor Single Document
```bash
# By UUID
python scripts/cli/monitor.py document abc-123-def

# Shows:
# - Document metadata
# - Current processing stage
# - Error details if failed
# - Progress through pipeline stages
```

#### Check System Health
```bash
python scripts/cli/monitor.py health

# Output:
# ✅ Supabase: Connected
# ✅ Redis: Connected
# ❌ Celery: No workers detected
```

#### Export Stats as JSON
```bash
python scripts/cli/monitor.py health --format json
```

## Benefits

1. **Single Source of Truth**: One monitor script instead of multiple
2. **No Timeouts**: Proper timeout handling prevents hanging
3. **Real-time Updates**: Live dashboard with configurable refresh
4. **Comprehensive View**: All components in one place
5. **User-Friendly**: Rich formatting with colors and emojis

## Migration from Old Scripts

Old scripts (now in `/scripts/legacy/monitoring/`):
- `standalone_pipeline_monitor.py`
- `enhanced_pipeline_monitor.py`
- `pipeline_monitor.py`
- `redis_monitor.py`
- `live_monitor.py`

All functionality now available in the unified monitor.

## Integration with CLI

The monitor is part of the broader CLI structure:
```
scripts/cli/
├── monitor.py    # Unified monitoring
├── import.py     # Document import operations
└── admin.py      # Administrative tasks
```

## Next Steps

1. Update documentation to reference new monitor
2. Remove legacy monitoring scripts after verification
3. Add monitor command to quick reference guides
4. Consider adding alerting capabilities for failures

## Performance Notes

- Minimal overhead with 2-second timeouts
- Efficient Redis key counting with limits
- Batch queries to Supabase for performance
- Non-blocking architecture for live updates