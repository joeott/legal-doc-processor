# Context 145: Error Fix, Verification, and Reset Process

## Problem Summary

The document processing pipeline experienced a 99.8% failure rate (463/464 documents) due to Celery workers using an incorrect Supabase instance. The workers were connecting to the old instance (`zwixwazwmaipzzcrwhzr`) instead of the correct one (`yalswdiexcuanszujjhl`).

## Root Cause

1. **Environment Variable Mismatch**: The .env file used `SUPABASE_ANON_PUBLIC_KEY` and `SUPABASE_SECRET_KEY`, but the code expected `SUPABASE_ANON_KEY` and `SUPABASE_SERVICE_ROLE_KEY`.

2. **Worker Startup Issue**: The `start_celery_workers.sh` script didn't load the .env file, causing workers to use stale system environment variables.

## Fix Applied

### 1. Environment Variable Mapping
Added compatibility mappings to .env:
```bash
# Original variables (keep these)
SUPABASE_ANON_PUBLIC_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
SUPABASE_SECRET_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...

# Add these for backward compatibility
SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
SUPABASE_SERVICE_ROLE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

### 2. Worker Startup Script Update
Modified `scripts/start_celery_workers.sh` to load .env:
```bash
# Load environment variables from .env file
if [ -f .env ]; then
    echo -e "${YELLOW}Loading environment from .env file...${NC}"
    set -a
    source .env
    set +a
    echo -e "${GREEN}Environment loaded. Using SUPABASE_URL: ${SUPABASE_URL}${NC}"
fi
```

## Complete Reset and Verification Task List

### Phase 1: Environment Verification ✅
- [x] Verify correct Supabase URL in .env
- [x] Add environment variable mappings
- [x] Fix worker startup script
- [x] Test database connectivity
- [x] Test AWS/S3 connectivity

### Phase 2: Worker Management
- [ ] Stop all existing Celery workers
- [ ] Clear any stuck tasks from Redis
- [ ] Start fresh Celery workers with correct environment
- [ ] Verify workers are using correct Supabase instance

### Phase 3: Document Reset
- [ ] Reset all failed documents to pending status
- [ ] Clear error messages and task IDs
- [ ] Verify no documents are stuck in processing states

### Phase 4: Reprocess Documents
- [ ] Submit all documents for processing
- [ ] Monitor processing progress
- [ ] Handle any new errors that arise
- [ ] Verify all documents complete successfully

### Phase 5: Final Verification
- [ ] Confirm all documents processed
- [ ] Check for complete pipeline execution (OCR → Text → Entity → Graph)
- [ ] Generate processing report
- [ ] Archive successful import manifest

## Execution Commands

### 1. Stop and Restart Workers
```bash
# Stop all workers
cd /Users/josephott/Documents/phase_1_2_3_process_v5
./scripts/stop_celery_workers.sh

# Force kill if needed
pkill -9 -f celery

# Clear Redis queues (optional but recommended)
python -c "
from scripts.redis_utils import get_redis_manager
redis = get_redis_manager()
if redis.is_available():
    redis.flushdb()
    print('Redis queues cleared')
"

# Start workers with monitoring
./scripts/start_celery_workers.sh --with-flower
```

### 2. Reset Failed Documents
```bash
cd /Users/josephott/Documents/phase_1_2_3_process_v5
python -c "
from dotenv import load_dotenv
load_dotenv(override=True)

from scripts.supabase_utils import SupabaseManager

db = SupabaseManager()
target_project = 'e74deac0-1f9e-45a9-9b5f-9fa08d67527c'

# Get project ID
project_result = db.client.table('projects').select('id').eq('projectId', target_project).execute()
project_sql_id = project_result.data[0]['id']

# Reset ALL documents for this project
reset_result = db.client.table('source_documents').update({
    'celery_status': 'pending',
    'celery_task_id': None,
    'initial_processing_status': 'pending',
    'error_message': None,
    'processing_version': 2  # Increment to force reprocessing
}).eq('project_fk_id', project_sql_id).execute()

print(f'Reset {len(reset_result.data)} documents to pending status')
"
```

### 3. Submit Documents for Processing
```bash
cd /Users/josephott/Documents/phase_1_2_3_process_v5
python scripts/queue_processor.py --project-uuid e74deac0-1f9e-45a9-9b5f-9fa08d67527c --batch-size 50
```

### 4. Monitor Processing Progress
```bash
# Option 1: Flower Dashboard (recommended)
# Open browser to http://localhost:5555

# Option 2: Standalone Monitor
cd /Users/josephott/Documents/phase_1_2_3_process_v5
python scripts/standalone_pipeline_monitor.py --refresh-interval 5

# Option 3: Quick Status Check
python -c "
from dotenv import load_dotenv
load_dotenv(override=True)

from scripts.supabase_utils import SupabaseManager
from collections import Counter

db = SupabaseManager()
project_sql_id = 339

status_result = db.client.table('source_documents')\
    .select('celery_status')\
    .eq('project_fk_id', project_sql_id)\
    .execute()

status_counts = Counter(doc['celery_status'] for doc in status_result.data)
total = len(status_result.data)

print(f'Total documents: {total}')
print('\\nStatus breakdown:')
for status, count in sorted(status_counts.items()):
    percentage = (count / total) * 100
    print(f'  {status}: {count} ({percentage:.1f}%)')

# Calculate completion
completed = status_counts.get('graph_completed', 0) + status_counts.get('completed', 0)
print(f'\\nCompletion: {completed}/{total} ({(completed/total)*100:.1f}%)')
"
```

### 5. Handle Stuck Documents
```bash
# Find and resubmit stuck documents
cd /Users/josephott/Documents/phase_1_2_3_process_v5
python scripts/recover_stuck_documents.py --project-uuid e74deac0-1f9e-45a9-9b5f-9fa08d67527c

# Or manually check for stuck docs
python -c "
from dotenv import load_dotenv
load_dotenv(override=True)

from scripts.supabase_utils import SupabaseManager
from datetime import datetime, timedelta

db = SupabaseManager()
project_sql_id = 339

# Find documents stuck in processing for over 30 minutes
stuck_cutoff = datetime.now() - timedelta(minutes=30)
stuck = db.client.table('source_documents')\
    .select('id, original_file_name, celery_status, last_modified_at')\
    .eq('project_fk_id', project_sql_id)\
    .in('celery_status', ['ocr_processing', 'text_processing', 'entity_processing', 'graph_processing'])\
    .lt('last_modified_at', stuck_cutoff.isoformat())\
    .execute()

if stuck.data:
    print(f'Found {len(stuck.data)} stuck documents:')
    for doc in stuck.data[:10]:
        print(f'  - {doc[\"original_file_name\"]} (status: {doc[\"celery_status\"]})')
else:
    print('No stuck documents found')
"
```

### 6. Generate Final Report
```bash
cd /Users/josephott/Documents/phase_1_2_3_process_v5
python -c "
from dotenv import load_dotenv
load_dotenv(override=True)

from scripts.supabase_utils import SupabaseManager
from collections import Counter
import json
from datetime import datetime

db = SupabaseManager()
project_sql_id = 339

# Get all documents
docs = db.client.table('source_documents')\
    .select('*')\
    .eq('project_fk_id', project_sql_id)\
    .execute()

# Analyze results
status_counts = Counter(doc['celery_status'] for doc in docs.data)
file_type_counts = Counter(doc['detected_file_type'] for doc in docs.data)

# Find any errors
errors = [doc for doc in docs.data if doc.get('error_message')]

# Calculate costs
total_cost = sum(doc.get('processing_cost_estimate', 0) for doc in docs.data)

# Generate report
report = {
    'timestamp': datetime.now().isoformat(),
    'project': 'Acuity v. Wombat Acquisitions',
    'project_uuid': 'e74deac0-1f9e-45a9-9b5f-9fa08d67527c',
    'total_documents': len(docs.data),
    'status_breakdown': dict(status_counts),
    'file_type_breakdown': dict(file_type_counts),
    'errors_count': len(errors),
    'total_cost_estimate': round(total_cost, 2),
    'completion_rate': f\"{(status_counts.get('graph_completed', 0) / len(docs.data)) * 100:.1f}%\"
}

# Save report
with open('acuity_import_report.json', 'w') as f:
    json.dump(report, f, indent=2)

print('Import Report Generated:')
print(json.dumps(report, indent=2))

# Show any errors
if errors:
    print(f'\\nFound {len(errors)} errors:')
    for err in errors[:5]:
        print(f'  - {err[\"original_file_name\"]}: {err[\"error_message\"]}')
"
```

## Success Criteria

The import is considered successful when:

1. **All documents reach final status**: Either `graph_completed` or `completed`
2. **No stuck documents**: No documents in processing states for >30 minutes
3. **Error rate <5%**: Acceptable error threshold for edge cases
4. **Cost tracking**: Total cost aligns with initial estimate (~$1,137)

## Troubleshooting

### If documents aren't processing:
1. Check Celery workers are running: `ps aux | grep celery`
2. Verify Redis connection: `redis-cli ping`
3. Check worker logs: `tail -f logs/celery-*.log`

### If specific file types fail:
1. Check if it's an image processing issue (o4-mini vision)
2. Verify AWS credentials for Textract
3. Check file size limits in S3

### If errors persist:
1. Check individual document errors
2. Review Celery task traces in Flower
3. Manually process problem documents

## Expected Timeline

- Environment reset: 5 minutes
- Document submission: 5 minutes
- Processing time: 2-4 hours (depending on API rate limits)
- Verification: 10 minutes

Total estimated time: 2-5 hours for complete reprocessing of 464 documents.

## Final Verification Checklist

- [ ] All 464 documents from input manifest processed
- [ ] No documents stuck in intermediate states
- [ ] Error rate below 5%
- [ ] All successful documents have complete pipeline data
- [ ] Cost tracking matches estimates
- [ ] Import report generated and archived

Once all items are checked, the import recovery is complete.