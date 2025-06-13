# Context 515: Script Comparison Analysis

## Date: 2025-01-06

### Overview
This document analyzes recently created scripts and compares them with existing functionality to identify duplications and opportunities for consolidation.

## 1. submit_batch_10_docs.py Analysis

### Script Purpose
- Submits 10 specific Paul, Michael (Acuity) documents for batch processing
- Hardcoded list of PDF files from the input_docs directory
- Creates project, uploads to S3, creates database records, and submits batch

### Comparison with Existing Scripts

#### vs. scripts/production_processor.py
**Duplicated Functionality:**
- Document discovery (hardcoded vs. dynamic directory scanning)
- S3 upload functionality
- Database record creation
- Project creation/verification
- Batch submission logic

**Unique to submit_batch_10_docs.py:**
- Hardcoded list of specific files
- Simpler, single-purpose script
- Direct batch submission without monitoring

**Unique to production_processor.py:**
- Full directory scanning with recursive option
- Document validation before upload
- Comprehensive monitoring and reporting
- CLI interface with multiple commands
- Batch strategy selection (balanced, priority_first, size_optimized)
- Campaign tracking and management
- Validation and quality reporting

**Could production_processor.py replace it?**
YES - Using: `python scripts/production_processor.py process /opt/legal-doc-processor/input_docs/Paul, Michael (Acuity)/ --max-batches 1`

#### vs. scripts/cli/import.py
**Duplicated Functionality:**
- S3 upload with UUID naming
- Database record creation
- Document metadata handling

**Unique to submit_batch_10_docs.py:**
- Direct batch submission
- Hardcoded file list
- Uses batch_tasks.submit_batch()

**Unique to import.py:**
- Manifest-based import with validation
- Pydantic model validation
- Import session tracking
- Progress reporting per document
- Directory import capability
- Cost estimation

**Could import.py replace it?**
PARTIALLY - Would need to create a manifest file first, then use: `python scripts/cli/import.py from-manifest manifest.json --project-uuid <uuid>`

#### vs. examples/batch_processing_example.py
**Duplicated Functionality:**
- Uses batch_tasks.submit_batch()
- Creates batch manifest
- Submits with priority settings

**Unique to submit_batch_10_docs.py:**
- Actual file handling and S3 upload
- Database record creation
- Real document processing

**Unique to batch_processing_example.py:**
- Example/demo code with fake data
- Shows multiple priority submissions
- Includes monitoring, recovery, and metrics examples
- Educational purpose

**Could batch_processing_example.py replace it?**
NO - It's an example script with fake data, not meant for production use

### Recommendation for submit_batch_10_docs.py
**DELETE and REPLACE** with production_processor.py, which provides all the same functionality plus:
- Better error handling
- Progress monitoring
- Flexible file selection
- Proper CLI interface

## 2. check_batch_status.py Analysis

### Script Purpose
- Checks status of a specific batch (hardcoded batch_id)
- Shows batch progress from Redis
- Lists document status from database
- Shows active processing tasks

### Comparison with Existing Scripts

#### vs. scripts/batch_tasks.py (get_batch_status function)
**Duplicated Functionality:**
- Redis batch progress retrieval
- Progress percentage calculation

**Unique to check_batch_status.py:**
- Database queries for document details
- Active task monitoring
- Formatted console output
- Hardcoded batch_id

**Unique to get_batch_status:**
- Celery task implementation
- Time remaining estimation
- Success rate calculation
- Can be called programmatically

**Could get_batch_status replace it?**
PARTIALLY - For the batch progress part only, not for the detailed document status

#### vs. scripts/cli/monitor.py
**Duplicated Functionality:**
- Batch status monitoring
- Document status display
- Active task tracking
- Redis data retrieval

**Unique to check_batch_status.py:**
- Simple, focused on single batch
- Direct SQL queries
- Hardcoded batch_id

**Unique to monitor.py:**
- Comprehensive monitoring dashboard
- Live updates with auto-refresh
- Multiple monitoring modes (live, pipeline, workers, cache)
- Rich terminal UI
- System-wide monitoring
- No hardcoded values

**Could monitor.py replace it?**
YES - The functionality exists but would need a batch-specific command like: `python scripts/cli/monitor.py batch <batch_id>`

### Recommendation for check_batch_status.py
**DELETE** - The functionality is better served by:
1. Using `scripts/cli/monitor.py live` for general monitoring
2. Calling `get_batch_status` task for programmatic access
3. Could add a `monitor.py batch <batch_id>` command if single-batch monitoring is frequently needed

## 3. monitor_pipeline_progress.py Analysis

### Script Purpose
- Monitors processing progress for 10 specific document UUIDs (hardcoded)
- Shows document status, processing stages, and summary
- One-time execution (no auto-refresh)

### Comparison with Existing Scripts

#### vs. scripts/monitoring/monitor_full_pipeline.py
**Duplicated Functionality:**
- Document status monitoring
- Processing stage tracking
- Database queries

**Unique to monitor_pipeline_progress.py:**
- Monitors multiple specific documents (hardcoded UUIDs)
- Simple status display
- Summary statistics

**Unique to monitor_full_pipeline.py:**
- Full pipeline execution and monitoring
- Redis cache monitoring
- Detailed event logging
- Performance metrics
- Report generation
- Single document focus

**Could monitor_full_pipeline.py replace it?**
NO - Different purposes (execution+monitoring vs. status checking)

#### vs. scripts/cli/monitor.py
**Duplicated Functionality:**
- Document status display
- Processing stage detection
- Database queries

**Unique to monitor_pipeline_progress.py:**
- Hardcoded list of document UUIDs
- Simple one-time execution
- Focused output

**Unique to monitor.py:**
- Live monitoring with refresh
- System-wide view
- Multiple monitoring modes
- Rich UI with panels and tables
- No hardcoded values

**Could monitor.py replace it?**
PARTIALLY - Would need to add support for monitoring specific document lists

### Recommendation for monitor_pipeline_progress.py
**KEEP but MODIFY** to:
1. Accept document UUIDs as command-line arguments
2. Remove hardcoded values
3. Add as a command to monitor.py: `monitor.py documents <uuid1> <uuid2> ...`

## Summary of Recommendations

### Scripts to Delete:
1. **submit_batch_10_docs.py** - Use `scripts/production_processor.py` instead
2. **check_batch_status.py** - Use `scripts/cli/monitor.py` instead

### Scripts to Modify:
1. **monitor_pipeline_progress.py** - Remove hardcoded values, integrate into monitor.py

### Suggested Enhancements to Existing Scripts:
1. Add `monitor.py batch <batch_id>` command for single batch monitoring
2. Add `monitor.py documents <uuid1> <uuid2>...` command for specific document monitoring
3. Consider adding a simple batch submission command to production_processor.py for quick testing

### Benefits of Consolidation:
- Reduced code duplication
- Consistent interfaces
- Better maintainability
- Centralized monitoring
- Reusable components

### Migration Commands:
```bash
# Instead of submit_batch_10_docs.py:
python scripts/production_processor.py process "input_docs/Paul, Michael (Acuity)/" --max-batches 1

# Instead of check_batch_status.py:
python scripts/cli/monitor.py live  # For general monitoring
# Or implement: python scripts/cli/monitor.py batch <batch_id>

# Instead of monitor_pipeline_progress.py:
python scripts/cli/monitor.py live  # For general monitoring
# Or implement: python scripts/cli/monitor.py documents <uuid1> <uuid2>...
```