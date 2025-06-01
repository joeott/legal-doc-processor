# Context 162: Enhanced Monitor and Control System

## Date: 2025-01-28

## Overview
Implemented comprehensive enhancements to the unified monitoring system (`/scripts/cli/monitor.py`) with:
1. Live feed showing recently processed documents
2. Stage-specific error tracking and categorization
3. Individual document control commands (stop/start/retry)
4. Real-time activity monitoring

## Key Features Added

### 1. Recent Document Feed
- Shows last 10 documents processed in the past 5 minutes
- Displays: Time, UUID (shortened), Filename, Status (✅/❌)
- Auto-updates in live mode
- Located in left panel of dashboard

### 2. Stage-Specific Error Tracking
The monitor now categorizes errors by pipeline stage:
- **OCR Upload**: S3 upload failures
- **OCR/Textract**: AWS Textract processing errors
- **Chunking**: Text segmentation failures
- **Entity Extraction**: NER processing errors
- **Entity Resolution**: Deduplication failures
- **Graph Building**: Relationship creation errors

Error detection uses:
- Specific `celery_status` values (e.g., `ocr_failed`, `chunking_failed`)
- Error message content analysis
- OCR metadata JSON inspection
- Processing stage determination

### 3. Document Control Commands

New `control` command allows individual document management:

```bash
# Stop a document's processing
python scripts/cli/monitor.py control stop <document_uuid>

# Start/restart processing
python scripts/cli/monitor.py control start <document_uuid>

# Retry from specific stage
python scripts/cli/monitor.py control retry <document_uuid> --stage ocr
python scripts/cli/monitor.py control retry <document_uuid> --stage chunking
python scripts/cli/monitor.py control retry <document_uuid> --stage entity_extraction
```

Control actions:
- **Stop**: Revokes active Celery task, marks document as 'stopped'
- **Start**: Submits document to OCR processing queue
- **Retry**: Clears error state and optionally removes downstream data

### 4. Enhanced Live Dashboard

The live monitoring dashboard (`monitor.py live`) now shows:

**Left Panel**:
- Document status counts with percentages
- Recent activity feed (last 5 minutes)
- Currently processing documents with duration
- Recent errors with truncated messages

**Right Panel**:
- Worker status and concurrency
- Queue lengths by type
- Errors grouped by pipeline stage
- Redis cache statistics

## Technical Implementation

### Data Collection
- Orders documents by `last_modified_at DESC` for recent activity
- Tracks documents modified in last 5 minutes
- Categorizes failures using `_determine_failure_stage()` method
- Maintains stage error dictionaries

### Stage Detection Logic
```python
def _determine_failure_stage(self, doc: Dict) -> str:
    # Checks celery_status for specific failure types
    # Analyzes error_message content
    # Inspects ocr_metadata_json for detailed errors
    # Falls back to processing stage detection
```

### Document Control Flow
1. Retrieves document from database
2. For stop: Revokes Celery task via control.revoke()
3. For start: Imports task module and submits via .delay()
4. For retry: Clears downstream data based on stage

## Usage Examples

### Monitor Recently Processed Documents
```bash
# Live dashboard with auto-refresh
python scripts/cli/monitor.py live

# Single snapshot
python scripts/cli/monitor.py live --once
```

### Debug Failed Documents
```bash
# View all failed documents
python scripts/cli/monitor.py pipeline

# Check specific document
python scripts/cli/monitor.py document <uuid>

# Retry failed document
python scripts/cli/monitor.py control retry <uuid>
```

### Stage-Specific Recovery
```bash
# Document failed at entity extraction
python scripts/cli/monitor.py control retry <uuid> --stage entity_extraction

# This will:
# 1. Clear neo4j_entity_mentions for this document
# 2. Clear neo4j_relationship_staging for this document
# 3. Set status to 'pending'
# 4. Clear error message
```

## Benefits

1. **Visibility**: Real-time view of document flow and bottlenecks
2. **Control**: Stop/start individual documents without affecting others
3. **Recovery**: Retry from specific stages without full reprocessing
4. **Diagnostics**: Stage-specific error tracking helps identify systemic issues
5. **Non-blocking**: Operations don't interfere with other documents in pipeline

## Integration with Pipeline

The monitor integrates with:
- Celery task control for stopping active tasks
- Direct task submission for starting processing
- Database cleanup for stage-specific retries
- Redis for queue length monitoring
- Real-time status updates via Supabase

## Next Steps

With this enhanced monitoring in place, we can now:
1. Submit documents for processing
2. Monitor their progress in real-time
3. Identify and fix failures at specific stages
4. Retry documents without full reprocessing
5. Stop problematic documents from blocking the pipeline

The system is ready for processing documents from `/input/` with full visibility and control over each document's journey through the pipeline.