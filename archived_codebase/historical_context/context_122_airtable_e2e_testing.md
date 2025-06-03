# Context 122: Airtable Integration End-to-End Testing Protocol

## Executive Summary

This document provides a comprehensive end-to-end testing protocol for the Airtable integration system implemented in context_121. The testing will verify:
1. Airtable to Supabase synchronization
2. Recursive document processing from `/input/` directory
3. Project mapping functionality with special focus on "Zwicky, Jessica" files
4. Entity caching conformance

## Testing Environment Setup

### Prerequisites Checklist
- [ ] Python environment with all dependencies installed
- [ ] Environment variables configured:
  ```bash
  export AIRTABLE_API_KEY="patFmBsmzrXokkUeq.be9f131cd726d2d247a38c53a89f930cd03061d28fabbbfa6d4020ea6d89baf3"
  export AIRTABLE_BASE_ID="appe2xz7Uc26o3imd"
  export AIRTABLE_PROJECT_NAME="Case Management System"
  ```
- [ ] Supabase connection configured and tested
- [ ] Redis/Celery workers running (if using async mode)
- [ ] `/input/` directory populated with test documents

### Pre-Test Database Preparation

1. **Apply Required Database Migrations**:
   ```sql
   -- Run from scripts/ directory
   python apply_migration.py <<EOF
   -- Add Airtable tracking columns to projects table
   ALTER TABLE projects 
   ADD COLUMN IF NOT EXISTS airtable_id TEXT UNIQUE,
   ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}',
   ADD COLUMN IF NOT EXISTS active BOOLEAN DEFAULT true,
   ADD COLUMN IF NOT EXISTS last_synced_at TIMESTAMP WITH TIME ZONE;

   -- Add Airtable tracking to canonical entities
   ALTER TABLE neo4j_canonical_entities
   ADD COLUMN IF NOT EXISTS airtable_person_id TEXT UNIQUE,
   ADD COLUMN IF NOT EXISTS entity_source TEXT DEFAULT 'document_extraction',
   ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}';

   -- Create sync tracking table
   CREATE TABLE IF NOT EXISTS airtable_sync_log (
       id SERIAL PRIMARY KEY,
       sync_type TEXT NOT NULL,
       started_at TIMESTAMP WITH TIME ZONE NOT NULL,
       completed_at TIMESTAMP WITH TIME ZONE,
       records_processed INTEGER DEFAULT 0,
       records_created INTEGER DEFAULT 0,
       records_updated INTEGER DEFAULT 0,
       errors INTEGER DEFAULT 0,
       status TEXT NOT NULL,
       details JSONB,
       created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
   );
   EOF
   ```

2. **Verify Database Schema**:
   ```bash
   python -c "
   from scripts.supabase_utils import SupabaseManager
   db = SupabaseManager()
   # Check if columns exist
   result = db.client.table('projects').select('airtable_id').limit(1).execute()
   print('✅ Database schema updated successfully' if result else '❌ Schema update failed')
   "
   ```

## Phase 1: Airtable to Supabase Synchronization

### Test 1.1: Initial Airtable Connection Test
```bash
# From project root directory
cd /Users/josephott/Documents/phase_1_2_3_process_v5

# Test Airtable connectivity
python -c "
from airtable.airtable_client import AirtableProjectManager
manager = AirtableProjectManager()
projects = manager.get_all_projects()
print(f'✅ Connected to Airtable. Found {len(projects)} projects')
for p in projects[:3]:
    print(f'  - {p[\"project_name\"]} (UUID: {p.get(\"project_uuid\", \"NO UUID\")})')
"
```

**Expected Output**:
- Connection successful message
- List of projects with UUIDs
- Should include "Zwicky v. Jacquet Ott" project

### Test 1.2: Dry-Run Synchronization
```bash
# Run sync in dry-run mode first
python airtable/test_airtable_integration.py --test sync --dry-run
```

**Verification Steps**:
1. Check console output for sync preview
2. Verify no actual database changes occurred
3. Review proposed changes for accuracy
4. Confirm "Zwicky v. Jacquet Ott" project would be synced

### Test 1.3: Full Airtable Synchronization
```bash
# Execute full synchronization
python -c "
from airtable.airtable_sync import AirtableSync
sync = AirtableSync()

print('Starting Airtable synchronization...')
print('=' * 60)

# Sync projects
project_results = sync.sync_projects()
print(f'Projects: {project_results[\"created\"]} created, {project_results[\"updated\"]} updated')

# Sync people to entities
people_results = sync.sync_people_to_entities()
print(f'People/Entities: {people_results[\"created\"]} created, {people_results[\"updated\"]} updated')

# Sync relationships
rel_results = sync.sync_project_relationships()
print(f'Relationships: {rel_results[\"created\"]} created')

print('=' * 60)
print('✅ Synchronization complete!')
"
```

**Verification Queries**:
```sql
-- Check synchronized projects
SELECT project_id, name, airtable_id, project_uuid, active, last_synced_at
FROM projects 
WHERE airtable_id IS NOT NULL
ORDER BY name;

-- Verify Zwicky project
SELECT * FROM projects 
WHERE project_uuid = '5ac45531-c06f-43e5-a41b-f38ec8f239ce';

-- Check synchronized entities
SELECT id, name, entity_type, airtable_person_id, entity_source
FROM neo4j_canonical_entities
WHERE airtable_person_id IS NOT NULL
ORDER BY name;

-- Check sync log
SELECT * FROM airtable_sync_log
ORDER BY created_at DESC
LIMIT 5;
```

## Phase 2: Document Processing with Project Mapping

### Test 2.1: Verify Input Directory Structure
```bash
# List all files in input directory recursively
find /Users/josephott/Documents/phase_1_2_3_process_v5/input -type f -name "*.pdf" | head -20

# Count files by directory
find /Users/josephott/Documents/phase_1_2_3_process_v5/input -type f -name "*.pdf" | \
  awk -F'/' '{print $(NF-1)}' | sort | uniq -c
```

### Test 2.2: Test Fuzzy Matching for Zwicky Files
```bash
# Test specific Zwicky file matching
python -c "
from airtable.fuzzy_matcher import FuzzyMatcher
from airtable.airtable_client import AirtableProjectManager

# Initialize components
manager = AirtableProjectManager()
matcher = FuzzyMatcher(manager)

# Test files that should match Zwicky project
test_files = [
    'Zwicky, Jessica/Motion for Summary Judgment.pdf',
    'ZWICKY JESSICA - Court Filing 2024.pdf',
    'Zwicky v. Jacquet Ott - Discovery.pdf',
    'J. Zwicky Deposition.pdf'
]

print('Testing fuzzy matching for Zwicky files:')
print('=' * 60)
for file_path in test_files:
    match = matcher.find_matching_project(file_path.split('/')[-1], file_path)
    if match:
        print(f'✅ {file_path}')
        print(f'   → Matched: {match[\"project_name\"]} (Score: {match[\"score\"]})')
        print(f'   → UUID: {match[\"project_uuid\"]}')
    else:
        print(f'❌ {file_path} - NO MATCH')
    print()
"
```

### Test 2.3: Process Single Zwicky Document
```bash
# Process a single document to verify flow
python -c "
import os
from airtable.document_ingestion import ProjectAwareDocumentIngestion

ingestion = ProjectAwareDocumentIngestion()

# Find a Zwicky file
zwicky_files = []
for root, dirs, files in os.walk('/Users/josephott/Documents/phase_1_2_3_process_v5/input'):
    if 'Zwicky' in root or any('Zwicky' in f for f in files):
        for f in files:
            if f.endswith('.pdf'):
                zwicky_files.append(os.path.join(root, f))

if zwicky_files:
    test_file = zwicky_files[0]
    print(f'Processing test file: {test_file}')
    
    # Submit with project matching
    result = ingestion.submit_document_with_project_matching(
        file_path=test_file,
        process_mode='direct'  # Use direct mode for immediate processing
    )
    
    print(f'Document UUID: {result[\"document_uuid\"]}')
    print(f'Assigned Project: {result[\"project_name\"]} ({result[\"project_id\"]})')
    print(f'Match Score: {result.get(\"match_score\", \"N/A\")}')
else:
    print('No Zwicky files found in input directory')
"
```

### Test 2.4: Batch Process All Documents Recursively
```bash
# Create a test script for recursive processing
cat > test_recursive_processing.py << 'EOF'
import os
import sys
from pathlib import Path
from collections import defaultdict

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from airtable.document_ingestion import ProjectAwareDocumentIngestion
from scripts.supabase_utils import SupabaseManager

def process_directory_recursively(base_dir, process_mode='direct'):
    """Process all documents in directory recursively with project mapping."""
    ingestion = ProjectAwareDocumentIngestion()
    db = SupabaseManager()
    
    # Statistics
    stats = defaultdict(int)
    project_assignments = defaultdict(list)
    errors = []
    
    # Find all processable files
    processable_extensions = {'.pdf', '.docx', '.txt', '.doc', '.rtf'}
    files_to_process = []
    
    for root, dirs, files in os.walk(base_dir):
        for file in files:
            if any(file.lower().endswith(ext) for ext in processable_extensions):
                files_to_process.append(os.path.join(root, file))
    
    print(f"Found {len(files_to_process)} documents to process")
    print("=" * 60)
    
    # Process each file
    for i, file_path in enumerate(files_to_process, 1):
        try:
            print(f"\n[{i}/{len(files_to_process)}] Processing: {file_path}")
            
            # Check if already processed
            filename = os.path.basename(file_path)
            existing = db.client.table('source_documents').select('*').eq('filename', filename).execute()
            
            if existing.data:
                print(f"  → Already processed (UUID: {existing.data[0]['uuid']})")
                stats['skipped'] += 1
                continue
            
            # Submit with project matching
            result = ingestion.submit_document_with_project_matching(
                file_path=file_path,
                process_mode=process_mode
            )
            
            stats['processed'] += 1
            project_name = result.get('project_name', 'Unknown')
            project_assignments[project_name].append(filename)
            
            print(f"  → Success! Document UUID: {result['document_uuid']}")
            print(f"  → Assigned to: {project_name}")
            print(f"  → Match score: {result.get('match_score', 'N/A')}")
            
        except Exception as e:
            print(f"  → ERROR: {str(e)}")
            stats['errors'] += 1
            errors.append({'file': file_path, 'error': str(e)})
    
    # Print summary
    print("\n" + "=" * 60)
    print("PROCESSING SUMMARY")
    print("=" * 60)
    print(f"Total files found: {len(files_to_process)}")
    print(f"Successfully processed: {stats['processed']}")
    print(f"Skipped (already processed): {stats['skipped']}")
    print(f"Errors: {stats['errors']}")
    
    print("\nPROJECT ASSIGNMENTS:")
    for project, files in sorted(project_assignments.items()):
        print(f"\n{project}: {len(files)} documents")
        for f in files[:5]:  # Show first 5
            print(f"  - {f}")
        if len(files) > 5:
            print(f"  ... and {len(files) - 5} more")
    
    if errors:
        print("\nERRORS:")
        for err in errors[:5]:
            print(f"  - {err['file']}: {err['error']}")
    
    # Verify Zwicky assignments
    print("\n" + "=" * 60)
    print("ZWICKY PROJECT VERIFICATION")
    print("=" * 60)
    zwicky_docs = db.client.table('source_documents').select(
        'filename, project_id, created_at'
    ).eq('project_id', '5ac45531-c06f-43e5-a41b-f38ec8f239ce').execute()
    
    if zwicky_docs.data:
        print(f"✅ Found {len(zwicky_docs.data)} documents assigned to Zwicky project:")
        for doc in zwicky_docs.data[:10]:
            print(f"  - {doc['filename']}")
    else:
        print("❌ No documents found assigned to Zwicky project!")
    
    return stats

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['direct', 'celery'], default='direct',
                       help='Processing mode (direct for immediate, celery for async)')
    parser.add_argument('--dir', default='/Users/josephott/Documents/phase_1_2_3_process_v5/input',
                       help='Directory to process')
    args = parser.parse_args()
    
    print(f"Processing all documents in: {args.dir}")
    print(f"Mode: {args.mode}")
    print()
    
    process_directory_recursively(args.dir, args.mode)
EOF

# Run the recursive processing
python test_recursive_processing.py --mode direct
```

## Phase 3: Entity Caching Conformance Testing

### Test 3.1: Verify Entity Cache Population
```bash
python -c "
from scripts.redis_utils import get_redis_client
import json

redis_client = get_redis_client()

# Check cache keys
all_keys = redis_client.keys('entity:*')
print(f'Found {len(all_keys)} cached entities')

# Sample some cached entities
if all_keys:
    for key in all_keys[:5]:
        entity_data = redis_client.get(key)
        if entity_data:
            entity = json.loads(entity_data)
            print(f'\\nCached Entity: {key.decode()}')
            print(f'  Name: {entity.get(\"name\")}')
            print(f'  Type: {entity.get(\"entity_type\")}')
            print(f'  Source: {entity.get(\"entity_source\", \"unknown\")}')
"
```

### Test 3.2: Verify Project-Entity Relationships
```sql
-- Check relationships for Zwicky project
SELECT 
    r.id,
    r.source_type,
    r.source_uuid,
    r.target_type,
    r.target_uuid,
    r.relationship_type,
    ce.name as entity_name,
    p.name as project_name
FROM neo4j_relationship_staging r
JOIN neo4j_canonical_entities ce ON ce.canonical_entity_id::text = r.target_uuid
JOIN projects p ON p.project_uuid::text = r.source_uuid
WHERE p.project_uuid = '5ac45531-c06f-43e5-a41b-f38ec8f239ce'
ORDER BY ce.name;
```

### Test 3.3: Cache Performance Verification
```bash
python -c "
from airtable.airtable_client import AirtableProjectManager
import time

manager = AirtableProjectManager()

# First call - should hit API
start = time.time()
projects1 = manager.get_all_projects()
time1 = time.time() - start

# Second call - should hit cache
start = time.time()
projects2 = manager.get_all_projects()
time2 = time.time() - start

print(f'First call (API): {time1:.3f} seconds')
print(f'Second call (cache): {time2:.3f} seconds')
print(f'Cache speedup: {time1/time2:.1f}x faster')
print(f'✅ Cache working correctly' if time2 < time1/2 else '❌ Cache may not be working')

# Clear cache and verify
manager.clear_cache()
start = time.time()
projects3 = manager.get_all_projects()
time3 = time.time() - start
print(f'\\nAfter cache clear: {time3:.3f} seconds')
"
```

## Phase 4: End-to-End Integration Verification

### Test 4.1: Complete Workflow Test
```bash
# Run the comprehensive integration test
python airtable/test_airtable_integration.py --all
```

### Test 4.2: Verify Data Consistency
```sql
-- Check overall statistics
SELECT 
    (SELECT COUNT(*) FROM projects WHERE airtable_id IS NOT NULL) as synced_projects,
    (SELECT COUNT(*) FROM neo4j_canonical_entities WHERE airtable_person_id IS NOT NULL) as synced_people,
    (SELECT COUNT(*) FROM source_documents WHERE project_id IS NOT NULL) as documents_with_projects,
    (SELECT COUNT(*) FROM source_documents WHERE project_id = '5ac45531-c06f-43e5-a41b-f38ec8f239ce') as zwicky_documents;

-- Check for any orphaned documents
SELECT filename, created_at, processing_status
FROM source_documents
WHERE project_id IS NULL
ORDER BY created_at DESC
LIMIT 10;
```

### Test 4.3: Generate Final Report
```bash
python -c "
from scripts.supabase_utils import SupabaseManager
from datetime import datetime

db = SupabaseManager()

print('AIRTABLE INTEGRATION E2E TEST REPORT')
print('=' * 60)
print(f'Generated: {datetime.now().strftime(\"%Y-%m-%d %H:%M:%S\")}')
print()

# Projects
projects = db.client.table('projects').select('*').not_.is_('airtable_id', 'null').execute()
print(f'Synchronized Projects: {len(projects.data)}')

# Entities
entities = db.client.table('neo4j_canonical_entities').select('*').not_.is_('airtable_person_id', 'null').execute()
print(f'Synchronized People/Entities: {len(entities.data)}')

# Documents
all_docs = db.client.table('source_documents').select('project_id').execute()
docs_with_projects = [d for d in all_docs.data if d['project_id']]
print(f'\\nDocuments with Projects: {len(docs_with_projects)}/{len(all_docs.data)} ({len(docs_with_projects)/len(all_docs.data)*100:.1f}%)')

# Zwicky verification
zwicky_docs = db.client.table('source_documents').select('filename').eq('project_id', '5ac45531-c06f-43e5-a41b-f38ec8f239ce').execute()
print(f'\\nZwicky Project Documents: {len(zwicky_docs.data)}')
if zwicky_docs.data:
    print('Sample Zwicky documents:')
    for doc in zwicky_docs.data[:5]:
        print(f'  - {doc[\"filename\"]}')

# Recent sync log
sync_logs = db.client.table('airtable_sync_log').select('*').order('created_at', desc=True).limit(5).execute()
if sync_logs.data:
    print('\\nRecent Sync Operations:')
    for log in sync_logs.data:
        print(f'  - {log[\"sync_type\"]}: {log[\"status\"]} ({log[\"records_processed\"]} processed)')

print('\\n✅ E2E Testing Complete!')
"
```

## Test Success Criteria

### 1. Airtable Synchronization
- [ ] All Airtable projects appear in Supabase projects table
- [ ] All Airtable people appear as canonical entities
- [ ] Project-person relationships are created
- [ ] Sync completes without errors
- [ ] Dry-run mode works correctly

### 2. Document Processing
- [ ] All documents in `/input/` are discovered
- [ ] Documents are correctly assigned to projects via fuzzy matching
- [ ] "Zwicky, Jessica" folder documents map to project ID `5ac45531-c06f-43e5-a41b-f38ec8f239ce`
- [ ] Match scores are reasonable (>80 for good matches)
- [ ] Default project assignment works for non-matches

### 3. Entity Caching
- [ ] Redis cache is populated with entities
- [ ] Cache TTL is respected
- [ ] Cache improves performance significantly
- [ ] Cache invalidation works correctly

### 4. Data Integrity
- [ ] No duplicate projects created
- [ ] No duplicate entities created
- [ ] All UUIDs are valid format
- [ ] Relationships have proper foreign key references
- [ ] Audit trail is complete in sync_log

## Troubleshooting Guide

### Common Issues and Solutions

1. **Airtable Connection Errors**
   ```bash
   # Verify environment variables
   env | grep AIRTABLE
   
   # Test API key directly
   curl -H "Authorization: Bearer $AIRTABLE_API_KEY" \
        "https://api.airtable.com/v0/$AIRTABLE_BASE_ID/Projects?maxRecords=1"
   ```

2. **Project Matching Failures**
   ```python
   # Debug fuzzy matching
   from airtable.fuzzy_matcher import FuzzyMatcher
   matcher = FuzzyMatcher(threshold=60)  # Lower threshold for testing
   ```

3. **Database Migration Errors**
   ```sql
   -- Check existing schema
   SELECT column_name, data_type 
   FROM information_schema.columns 
   WHERE table_name = 'projects';
   ```

4. **Redis Cache Issues**
   ```bash
   # Clear all cache
   redis-cli FLUSHDB
   
   # Monitor cache operations
   redis-cli MONITOR
   ```

## Post-Test Cleanup (Optional)

```bash
# Remove test documents from database
python scripts/cleanup_test_documents.py

# Clear Redis cache
redis-cli FLUSHDB

# Reset sync tracking
psql $DATABASE_URL -c "TRUNCATE TABLE airtable_sync_log;"
```

## Summary

This comprehensive testing protocol ensures the Airtable integration is functioning correctly end-to-end. Special attention is given to the "Zwicky, Jessica" project mapping requirement, with multiple verification points throughout the testing process. Upon successful completion of all tests, the system is ready for production deployment.