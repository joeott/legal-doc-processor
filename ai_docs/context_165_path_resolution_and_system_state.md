# Context 165: Path Resolution Issues and System State Update

## Date: 2025-01-28

## Executive Summary

After implementing comprehensive monitoring enhancements and fixing S3 permissions for Textract, we've identified the final blocker: file path resolution between the document submission and OCR processing stages. The system is failing at the OCR stage with "N/A_PATH_NOT_FOUND" because of a mismatch between how paths are stored (relative) and how they're being passed to workers (absolute).

## Current System State

### 1. Infrastructure Status ✅
- **Celery Workers**: 7 workers running across different queues (ocr, text, entity, graph, embeddings, general)
- **Redis**: Connected and operational for message brokering
- **S3 Bucket**: `samu-docs-private-upload` configured with proper Textract permissions
- **Supabase**: Database accessible with proper schema
- **AWS Textract**: Confirmed working with async API for PDFs

### 2. Monitoring Enhancements ✅
- **Unified Monitor** (`/scripts/cli/monitor.py`):
  - Live dashboard with real-time updates
  - Recent activity feed showing last 5 minutes of processing
  - Textract job tracking panel
  - Stage-specific error categorization
  - Document control commands (stop/start/retry)
  - Worker and queue status monitoring
  - Redis cache statistics

### 3. Fixed Issues ✅
- **S3 Permissions**: Applied bucket policy allowing `textract.amazonaws.com` service principal
- **Monitor Column Names**: Fixed schema mismatches (documentId, job_status, etc.)
- **Redis Configuration**: Properly parsing `REDIS_PUBLIC_ENDPOINT` environment variable
- **Deprecated Code**: Updated Pydantic validators and datetime usage throughout codebase

### 4. Remaining Issue: Path Resolution 🔴

#### Problem Description
When processing documents, the system stores relative paths in the database:
```
original_file_path: "input/Paul, Michael (Acuity)/Paul, Michael - JDH EOA 1-27-25.pdf"
```

However, when resubmitting via the monitor's control command, the path is converted to absolute:
```python
# In monitor.py control command
file_path = doc['original_file_name']
if not os.path.isabs(file_path):
    file_path = os.path.abspath(file_path)  # Creates absolute path
```

This absolute path may not be valid from the Celery worker's perspective, especially if:
1. Workers run in different directories
2. Workers run in containers
3. The working directory differs between submission and execution

#### Root Cause Analysis
The issue stems from inconsistent path handling across the system:

1. **Initial Submission** (`test_single_document.py`):
   - Accepts file path (relative or absolute)
   - Stores relative path in database
   - Passes absolute path to Celery task

2. **Monitor Resubmission** (`monitor.py`):
   - Reads relative path from database
   - Converts to absolute using current working directory
   - Passes potentially invalid absolute path to Celery

3. **OCR Processing** (`ocr_extraction.py`):
   - Expects valid file path (absolute or relative)
   - Fails with "File not found" if path invalid
   - Sets textract_job_id to "N/A_PATH_NOT_FOUND"

## Proposed Solution

### 1. Standardize Path Handling

#### Option A: Always Use Relative Paths (Recommended)
```python
# In monitor.py control command
file_path = doc['original_file_name']
# Don't convert to absolute - keep as stored
# Ensure workers run from consistent directory

# In OCR task, resolve relative to project root
if not os.path.isabs(file_path):
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    file_path = os.path.join(project_root, file_path)
```

#### Option B: Store Absolute Paths
```python
# In create_source_document_entry
# Convert to absolute before storing
if not os.path.isabs(original_file_path):
    original_file_path = os.path.abspath(original_file_path)
```

### 2. Add Path Validation

```python
# In OCR task startup
def validate_file_access(file_path: str) -> tuple[bool, str]:
    """Validate file path and access before processing."""
    # Try relative to project root first
    if not os.path.isabs(file_path):
        project_root = get_project_root()
        full_path = os.path.join(project_root, file_path)
        if os.path.exists(full_path):
            return True, full_path
    
    # Try as-is
    if os.path.exists(file_path):
        return True, file_path
        
    # Try common base paths
    for base in ['/app', os.getcwd(), os.path.expanduser('~')]:
        test_path = os.path.join(base, file_path)
        if os.path.exists(test_path):
            return True, test_path
            
    return False, None
```

### 3. Enhanced Error Logging

```python
# In ocr_extraction.py
if not os.path.exists(file_path):
    error_metadata = [{
        "status": "error",
        "stage": "file_validation",
        "error_message": f"File not found: {file_path}",
        "attempted_paths": [
            file_path,
            os.path.abspath(file_path),
            os.path.join(get_project_root(), file_path)
        ],
        "working_directory": os.getcwd(),
        "project_root": get_project_root(),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }]
```

## Implementation Plan

### Phase 1: Immediate Fix (Quick Win)
1. Modify monitor.py to NOT convert paths to absolute
2. Ensure OCR task handles relative paths correctly
3. Add detailed logging for path resolution

### Phase 2: Robust Solution
1. Implement path validation function
2. Add project root detection utility
3. Standardize path handling across all components
4. Add path resolution tests

### Phase 3: Long-term Improvements
1. Consider storing files in S3 immediately upon intake
2. Use S3 URIs instead of file paths for processing
3. Implement file existence pre-checks before task submission

## Testing Strategy

### 1. Path Resolution Tests
```python
# Test various path formats
test_paths = [
    "input/test.pdf",  # Relative
    "/absolute/path/test.pdf",  # Absolute
    "./input/test.pdf",  # Relative with dot
    "~/Documents/test.pdf",  # Home directory
]
```

### 2. Worker Environment Tests
- Test with workers in different directories
- Test with PYTHONPATH variations
- Test with Docker containers

### 3. End-to-End Validation
- Submit document with relative path
- Verify S3 upload
- Confirm Textract processing
- Check all pipeline stages

## Configuration Recommendations

### 1. Environment Variables
```bash
# Add to .env
PROJECT_ROOT=/path/to/phase_1_2_3_process_v5
CELERY_WORKING_DIR=/path/to/phase_1_2_3_process_v5
```

### 2. Celery Worker Configuration
```bash
# In start_celery_workers.sh
cd $PROJECT_ROOT
export PYTHONPATH=$PROJECT_ROOT:$PYTHONPATH
celery -A scripts.celery_app worker ...
```

### 3. Systemd Service (if applicable)
```ini
[Service]
WorkingDirectory=/path/to/phase_1_2_3_process_v5
Environment="PYTHONPATH=/path/to/phase_1_2_3_process_v5"
```

## Monitoring Insights

### Recent Observations
1. Documents fail immediately (< 1 second) indicating early-stage failure
2. No Textract jobs created (no S3 upload occurring)
3. Error consistently shows "N/A_PATH_NOT_FOUND"
4. Workers are healthy and responsive

### Success Metrics
Once fixed, we should see:
1. S3 upload confirmation in logs
2. Textract job creation in `textract_jobs` table
3. Document status progressing through stages
4. OCR metadata populated with extraction details

## Next Immediate Steps

1. **Fix Path Resolution** ⏳
   - Modify monitor.py control command
   - Update OCR task path handling
   - Add comprehensive logging

2. **Test Single Document** ⏳
   - Submit via fixed monitor
   - Track through all stages
   - Verify S3 upload and Textract processing

3. **Document Success Pattern** ⏳
   - Create reference implementation
   - Update developer guidelines
   - Add to CLAUDE.md

## System Health Summary

| Component | Status | Notes |
|-----------|--------|-------|
| Celery Workers | ✅ Healthy | 7 workers across queues |
| Redis | ✅ Connected | Broker operational |
| Supabase | ✅ Accessible | Schema mostly correct |
| S3 | ✅ Configured | Bucket policy applied |
| Textract | ✅ Permissions OK | Async API confirmed working |
| OCR Pipeline | 🔴 Path Issues | File resolution failing |
| Monitor | ✅ Enhanced | Full visibility achieved |

## Conclusion

We're one fix away from a fully operational pipeline. The path resolution issue is well-understood and has clear solutions. Once implemented, the comprehensive monitoring system will provide excellent visibility into document processing, and the enhanced error logging will help diagnose any future issues quickly.

The system architecture is sound, permissions are correct, and all components are operational. We just need to ensure consistent path handling between document submission and processing.