# Context 160: Monitor Refinement and Operation Guide

## Overview

Refined and consolidated the monitoring functionality into a single, reliable script at `/scripts/cli/monitor.py`. This unified monitor replaces multiple legacy monitoring scripts and provides comprehensive pipeline visibility without timeouts.

## Problem Solved

- Multiple monitoring scripts causing confusion and maintenance overhead
- Celery inspection timeouts blocking script execution
- Incorrect Redis configuration preventing connection to Redis Cloud
- Inconsistent database column references causing query failures

## Key Refinements Made

### 1. Redis Configuration Fix
- Correctly parses `REDIS_PUBLIC_ENDPOINT` environment variable
- Falls back to `REDIS_HOST`/`REDIS_PORT` if endpoint not available
- Properly handles Redis Cloud authentication with username and password

### 2. Timeout Prevention
- Set 2-second timeout on all Celery inspect operations
- Graceful degradation when operations timeout
- Non-blocking architecture prevents hanging

### 3. Database Column Corrections
- Fixed column references: `created_at` → `intake_timestamp`
- Fixed column references: `updated_at` → `last_modified_at`
- Proper handling of Supabase timestamp formats

## Monitor Commands

### 1. Health Check
```bash
python scripts/cli/monitor.py health
```
Shows status of all system components:
- Supabase database connection
- Redis cache availability
- Celery worker presence

### 2. Pipeline Statistics
```bash
python scripts/cli/monitor.py pipeline
```
Displays:
- Document counts by status (completed, failed, processing, pending)
- File type distribution
- Processing stage breakdown for active documents
- Recent failures with error messages
- Stuck documents (processing >30 minutes)

### 3. Worker Status
```bash
python scripts/cli/monitor.py workers
```
Shows:
- Active worker count
- Tasks currently executing
- Queue lengths by type
- Worker pool configuration

### 4. Cache Statistics
```bash
python scripts/cli/monitor.py cache
```
Provides:
- Redis memory usage
- Cache hit rate
- Key counts by type
- Connection statistics

### 5. Document Details
```bash
python scripts/cli/monitor.py document <uuid_or_id>
```
Shows comprehensive information for a specific document:
- Metadata and status
- Current processing stage
- Error details if failed
- Progress through pipeline stages
- OCR metadata including error details

### 6. Live Dashboard
```bash
python scripts/cli/monitor.py live
python scripts/cli/monitor.py live --refresh 3  # Custom refresh interval
python scripts/cli/monitor.py live --once       # Run once and exit
```
Real-time dashboard with:
- Document status overview
- Currently processing documents with duration
- Recent errors
- Worker and queue status
- Redis cache metrics

## Technical Implementation Details

### Class Structure
- `UnifiedMonitor`: Main monitoring class handling all connections and data gathering
- Initialization creates connections to Supabase, Redis, and Celery
- Each stats method is independent with its own error handling

### Error Handling
- Connection failures are logged as warnings, not fatal errors
- Each component can fail independently without breaking the monitor
- Graceful fallbacks for missing data

### Performance Optimizations
- Batch queries to minimize database calls
- Limited Redis key scanning to prevent blocking
- Efficient counter operations for statistics
- Timeout limits on all external operations

## Usage Examples

### Monitoring a Specific Document Through Processing
```bash
# Submit document for processing
python scripts/legacy/testing/test_single_document.py /path/to/document.pdf

# Get the document UUID from the output, then monitor
python scripts/cli/monitor.py document <uuid>

# Watch live updates
python scripts/cli/monitor.py live --refresh 2
```

### Debugging Failed Documents
```bash
# See all recent failures
python scripts/cli/monitor.py pipeline

# Get details on a specific failure
python scripts/cli/monitor.py document <uuid>
```

### System Health Monitoring
```bash
# Quick health check
python scripts/cli/monitor.py health

# Detailed system state
python scripts/cli/monitor.py live --once
```

## Integration with Existing Scripts

The monitor integrates seamlessly with:
- Document submission scripts in `/scripts/legacy/testing/`
- Celery task processing in `/scripts/celery_tasks/`
- Redis caching in `/scripts/redis_utils.py`
- Database operations in `/scripts/supabase_utils.py`

## Benefits Over Legacy Scripts

1. **Single entry point**: One command with subcommands instead of multiple scripts
2. **Consistent interface**: Unified CLI structure using Click
3. **Better error handling**: Timeouts and failures don't crash the monitor
4. **Rich formatting**: Color-coded output with tables and emojis
5. **Comprehensive coverage**: All monitoring needs in one tool

## Future Enhancements (Not Implemented)

- Export statistics to JSON/CSV
- Historical trend analysis
- Alerting for failures or stuck documents
- Integration with external monitoring systems
- Performance metrics tracking

## Maintenance Notes

- The monitor reads directly from database tables, so schema changes may require updates
- Redis key patterns are hardcoded and should match those used in caching
- Celery configuration must match that used by workers
- All timestamps are converted to UTC for consistency

## Conclusion

The unified monitor provides a reliable, comprehensive view of the document processing pipeline without the timeout issues that plagued previous monitoring scripts. It serves as the primary tool for operational visibility and debugging.