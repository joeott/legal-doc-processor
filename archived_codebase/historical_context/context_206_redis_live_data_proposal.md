# Context 206: Redis Configuration for Live Data Testing - Implementation Proposal

## Overview

This proposal outlines the Redis schema considerations and configuration changes needed before processing live data (450+ documents). Instead of creating additional scripts, we'll leverage the existing Model Context Protocol (MCP) Redis integration and existing configuration.

## Current State Assessment

### Existing Infrastructure
1. **MCP Redis Pipeline** - Already configured at `/resources/mcp-redis-pipeline/`
2. **Redis Manager** - Existing at `/scripts/cache.py` with comprehensive functionality
3. **Configuration** - Already in `/scripts/config.py` with TTL settings
4. **Cache Models** - Defined in `/scripts/core/cache_models.py`

### Key Patterns in Use
- Document state tracking
- OCR result caching (7 days TTL)
- Entity caching (12 hours TTL)
- Chunk caching (2 days TTL)
- Rate limiting with sorted sets
- Distributed locks

## Identified Risks for Live Data

### 1. Memory Accumulation
- **Risk**: 450 documents × ~10MB OCR cache × 7 days = potential 4.5GB+ memory usage
- **Impact**: Redis instance could hit memory limits causing evictions

### 2. Lock Contention
- **Risk**: 5-minute lock timeout might be insufficient for large documents
- **Impact**: Processing failures due to lock timeouts

### 3. Cache Invalidation
- **Risk**: No automatic cleanup of orphaned keys
- **Impact**: Memory bloat from failed processing attempts

## Proposed Solution

### Option 1: Configuration-Only Changes (Recommended)

**1. Update existing `/scripts/config.py`:**
```python
# Add memory management settings
REDIS_MAX_MEMORY_MB = int(os.getenv('REDIS_MAX_MEMORY_MB', '1024'))  # 1GB default
REDIS_EVICTION_POLICY = os.getenv('REDIS_EVICTION_POLICY', 'allkeys-lru')

# Adjust TTLs for production
if os.getenv('ENVIRONMENT') == 'production':
    REDIS_OCR_CACHE_TTL = 3 * 24 * 60 * 60  # 3 days instead of 7
    REDIS_CHUNK_CACHE_TTL = 1 * 24 * 60 * 60  # 1 day instead of 2
```

**2. Extend MCP Redis Pipeline capabilities:**
- Add memory monitoring commands
- Add bulk cleanup operations
- Add cache statistics reporting

**3. Use existing cache manager more effectively:**
- Implement document-level cache size limits
- Add pre-processing cache cleanup
- Monitor cache hit rates

### Option 2: MCP Extension Approach

Extend the existing MCP Redis Pipeline with new tools:

```typescript
// In /resources/mcp-redis-pipeline/src/index.ts
{
  name: "monitor_memory_usage",
  description: "Monitor Redis memory usage and key distribution",
  parameters: {
    detailed: { type: "boolean", default: false }
  }
},
{
  name: "cleanup_old_cache",
  description: "Clean up cache entries older than specified hours",
  parameters: {
    older_than_hours: { type: "number", required: true },
    dry_run: { type: "boolean", default: true }
  }
},
{
  name: "set_memory_limit",
  description: "Configure Redis memory limit and eviction policy",
  parameters: {
    max_memory_mb: { type: "number", required: true },
    policy: { type: "string", default: "allkeys-lru" }
  }
}
```

## Implementation Steps

### Phase 1: Pre-Production Configuration (Before Live Data)

1. **Memory Configuration**
   ```bash
   # Via MCP
   mcp_redis-pipeline.set_memory_limit(max_memory_mb=1024, policy="allkeys-lru")
   ```

2. **TTL Adjustments**
   - Update `config.py` with production TTL values
   - No code changes needed, just environment variables

3. **Monitoring Setup**
   ```bash
   # Via existing CLI
   python scripts/cli/monitor.py redis --watch
   ```

### Phase 2: Live Data Testing Safeguards

1. **Pre-Processing Cleanup**
   ```python
   # Use existing CacheManager
   from scripts.cache import get_cache_manager
   cache_mgr = get_cache_manager()
   
   # Before each import session
   cache_mgr.clear_pattern("doc:*:temp")  # Clear temporary data
   ```

2. **Memory Monitoring**
   ```python
   # Via MCP during processing
   mcp_redis-pipeline.monitor_memory_usage(detailed=True)
   ```

3. **Automatic Cleanup**
   - Use existing `cleanup_old_cache_entries` Celery task
   - Schedule to run every hour during processing

## Benefits of This Approach

1. **No New Scripts** - Uses existing infrastructure
2. **MCP Integration** - Leverages Model Context Protocol for monitoring
3. **Minimal Changes** - Configuration-driven adjustments
4. **Production Ready** - Builds on tested components

## Monitoring During Live Data

### Key Metrics to Track
1. Memory usage percentage
2. Cache hit/miss rates
3. Lock contention events
4. Eviction counts
5. Slow command alerts

### Alert Thresholds
- Memory > 80%: Warning
- Memory > 90%: Critical
- Lock timeouts > 5/hour: Investigation needed
- Cache hit rate < 20%: Performance review

## Rollback Plan

If issues arise:
1. Flush specific key patterns (not entire cache)
2. Reduce TTLs dynamically
3. Increase memory limit temporarily
4. Switch to no-cache mode for problem documents

## Recommendation

**Use Option 1** - Configuration-only changes:
- Minimal risk
- No new code to test
- Leverages existing, tested infrastructure
- Can be adjusted without code deployment

The existing Redis schema is well-designed for document processing. We only need to:
1. Set appropriate memory limits
2. Adjust TTLs for production scale
3. Monitor actively during processing
4. Use existing cleanup mechanisms

## Next Steps

1. Review and approve this proposal
2. Update production configuration values
3. Test with 10-document batch
4. Monitor metrics
5. Proceed with full 450+ document processing

No schema changes are needed - the current structure is production-ready with appropriate configuration.