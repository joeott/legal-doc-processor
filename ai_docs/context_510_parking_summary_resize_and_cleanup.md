# Context 510: Parking Summary - Instance Resize and Codebase Cleanup

## Date: 2025-06-12
## Session Summary: EC2 Resize Planning and Essential Scripts Analysis

### What We Accomplished

1. **Worker Configuration Fixed** (Context 505-506)
   - All 8 workers now running correctly
   - Batch processing queues covered
   - Memory allocation optimized for t3.medium

2. **Codebase Organization**
   - Moved 9 test files to `/tests/integration/`
   - Moved 4 monitoring scripts to `/scripts/monitoring/`
   - Moved 11 utility scripts to `/scripts/utilities/`
   - Moved logs and reports to `/output/`
   - Clean parent directory achieved

3. **Production Testing Attempted**
   - Batch of 10 documents submitted
   - Failed due to:
     - Memory exhaustion (88.2% usage)
     - Documents not in `source_documents` table
     - Parameter mismatch in batch processing

4. **Essential Scripts Identified** (Context 507)
   - 27 core production scripts documented
   - ~30+ scripts identified for removal
   - Clear understanding of what's actually needed

5. **Hardware Analysis Completed** (Context 509)
   - Current t3.medium severely constrained
   - 53% memory used by development tools (Claude + Cursor)
   - Application needs minimum 8GB RAM
   - Recommended upgrade to t3.xlarge (16GB)

6. **Resize Instructions Created**
   - Comprehensive guide in `INSTANCE_RESIZE_INSTRUCTIONS.md`
   - Includes backup, rollback, and verification steps
   - AWS CLI and console methods documented

### Current System State

- **Workers**: All 8 running but memory-constrained
- **Memory**: 2.9GB/3.7GB used (78% baseline)
- **Node.js Processes**: 
  - Claude Code: 35.9% memory
  - Cursor IDE: 17.1% memory
  - Total: 53% (2GB)
- **Batch Status**: Failed due to memory and missing document records

### Key Findings

1. **Memory Breakdown**:
   ```
   Total:        3.7 GB
   OS/System:    0.7 GB
   Dev Tools:    2.0 GB (Claude + Cursor)
   Available:    1.0 GB (insufficient for workers)
   ```

2. **Three Issues Preventing Processing**:
   - High memory usage triggering circuit breaker
   - Documents not registered in database
   - Batch processing passing incompatible parameters

3. **Instance Comparison**:
   - Current t3.medium: 2 vCPU, 3.7 GB RAM
   - Minimum viable (t3.large): 2 vCPU, 8 GB RAM
   - Recommended (t3.xlarge): 4 vCPU, 16 GB RAM

### Next Steps When Resuming

1. **Immediate Option** (Continue on t3.medium):
   ```bash
   # Free memory by stopping dev tools
   pkill -f cursor-server
   pkill -f claude
   # This frees ~2GB
   ```

2. **Recommended: Resize Instance**:
   - Follow `INSTANCE_RESIZE_INSTRUCTIONS.md`
   - Budget 15 minutes downtime
   - Update SSH config with new IP

3. **Fix Application Issues**:
   - Fix batch_tasks.py parameter passing
   - Add document registration workflow
   - Restart workers after memory freed

4. **Complete Batch Processing**:
   - Documents already in S3
   - Batch IDs: `eac61c3d-e41d-4c54-b2ea-1e26f3b1ee9b`
   - Monitor with `./scripts/monitoring/monitor_workers.sh`

### Important Notes

- **Public IP will change** during resize (currently 54.162.223.205)
- Consider setting up Elastic IP to avoid future IP changes
- Cost increases 4x with t3.xlarge ($30→$120/month)
- All production scripts identified and organized
- Development tools using majority of system memory

### File Organization Complete

```
/opt/legal-doc-processor/
├── scripts/           # Core production scripts
├── tests/            # All tests organized
├── output/           # Logs and reports
├── archived/         # Old backups
└── [clean root]      # Only essential files
```

### Session Metrics

- Duration: ~2.5 hours
- Contexts created: 4 (507, 508, 509, 510)
- Major issues identified: Memory constraints
- Solution documented: Instance resize guide
- Codebase: Organized and cleaned