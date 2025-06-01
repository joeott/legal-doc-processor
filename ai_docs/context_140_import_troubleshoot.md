# Context 140: Import Troubleshooting & Fix Implementation

## Implementation Status: PAUSED for Photo Handling Enhancement

**Date**: 2025-05-27
**Status**: Import fixes completed and verified, but discovered photo processing failures
**Next**: Implementing context_141_photo_handling.md before resuming full import

The import system verification passed all tests:
- ✅ Database Schema: All required tables accessible  
- ✅ Project Association: Project exists with ID 606
- ✅ Single Document Import: Dry run successful

However, during testing discovered that photo files (.jpg, .heic, .png) are failing at OCR stage. These need special multimodal handling via OpenAI GPT-4V instead of text-based OCR. Implementation paused to address this critical photo handling requirement.

**Resume Point**: After photo handling is implemented, continue with full 492-document import using:
```bash
python scripts/import_from_manifest_fixed.py input_manifest.json --workers 1 --batch-size 1
```

---

## Problem Analysis

The import process failed at the document creation stage due to several schema and logic mismatches. Here's the detailed analysis:

### Core Issues Identified

#### 1. **Project UUID Schema Mismatch**
- **Problem**: `create_source_document_entry()` expects `project_uuid` parameter but projects table uses integer `id`
- **Error**: `Foreign key constraint "source_documents_project_uuid_fkey" violation`
- **Root Cause**: The projects table has integer primary keys, not UUIDs
- **Impact**: All document creation fails immediately

#### 2. **Missing Project Association Logic**
- **Problem**: Import creates new project (ID: 606) but doesn't properly link documents
- **Current**: Documents should be associated with existing project, not create new ones
- **Impact**: Creates orphaned projects and fails foreign key constraints

#### 3. **Schema Field Mismatches**
- **Problem**: Several field references don't match actual table schema
- **Examples**: 
  - `source_documents.metadata` column doesn't exist
  - UUID vs integer ID mismatches throughout
- **Impact**: Multiple constraint violations and field errors

#### 4. **Missing Project Pre-Association**
- **Problem**: Should identify and use existing project for `/input/` documents
- **Current**: Creates new project each time
- **Expected**: All `/input/` documents belong to same legal case project

## Database Schema Analysis

### Current Projects Table Structure
```sql
-- Actual projects table (integer ID)
projects (
    id INTEGER PRIMARY KEY,           -- Not UUID!
    name TEXT,
    metadata JSONB,
    -- ... other fields
)
```

### Current Source Documents Table Structure  
```sql
-- Actual source_documents table
source_documents (
    id INTEGER PRIMARY KEY,
    project_fk_id INTEGER,           -- Links to projects.id
    project_uuid VARCHAR,            -- Separate UUID field
    document_uuid VARCHAR,           -- Document's own UUID
    import_session_id UUID,          -- Links to import_sessions
    -- ... other fields
)
```

### Issue: Method Signature Mismatch
```python
# Current method signature expects UUID
def create_source_document_entry(self, project_fk_id: int, project_uuid: str, ...)

# But we're passing empty string for project_uuid
project_uuid='',  # This causes FK constraint violation
```

## Implementation Fix Plan

### Phase 1: Fix Project Association Logic

#### 1.1 Create Project Pre-Association Method
```python
def find_or_create_input_project(self) -> Tuple[int, str]:
    """Find existing project for /input/ documents or create one"""
    
    # Look for existing project for input files
    result = self.db_manager.client.table('projects')\
        .select('id, projectId')\
        .ilike('name', '%Input%')\
        .order('id', desc=True)\
        .limit(1)\
        .execute()
    
    if result.data:
        project_sql_id = result.data[0]['id']
        project_uuid = result.data[0]['projectId'] or str(uuid.uuid4())
        
        # Update project UUID if missing
        if not result.data[0]['projectId']:
            self.db_manager.client.table('projects')\
                .update({'projectId': project_uuid})\
                .eq('id', project_sql_id)\
                .execute()
        
        return project_sql_id, project_uuid
    else:
        # Create new project with proper UUID
        project_uuid = str(uuid.uuid4())
        project_data = {
            'name': 'Legal Documents - Input Collection',
            'projectId': project_uuid,
            'metadata': {
                'source': 'input_directory_import',
                'description': 'Documents from /input/ directory',
                'import_session': str(self.session_id),
                'created_at': datetime.now().isoformat()
            }
        }
        
        result = self.db_manager.client.table('projects')\
            .insert(project_data)\
            .execute()
        
        return result.data[0]['id'], project_uuid
```

#### 1.2 Fix Document Creation Logic
```python
def _process_file(self, file_info: Dict) -> Dict:
    """Process a single file with correct project association"""
    file_path = self.base_path / file_info['path']
    
    try:
        # Get proper project IDs
        if not hasattr(self, 'project_sql_id') or not hasattr(self, 'project_uuid'):
            self.project_sql_id, self.project_uuid = self.find_or_create_input_project()
        
        # Create document entry with correct parameters
        source_doc_id, doc_uuid = self.db_manager.create_source_document_entry(
            project_fk_id=self.project_sql_id,      # Integer ID
            project_uuid=self.project_uuid,         # Proper UUID string
            original_file_path=file_info['path'],
            original_file_name=file_info['filename'],
            detected_file_type=file_info.get('mime_type', 'unknown')
        )
        
        # Upload to S3 with UUID naming
        s3_result = self.s3_storage.upload_document_with_uuid_naming(
            str(file_path),
            doc_uuid,
            file_info['filename']
        )
        s3_key = s3_result['s3_key']
        
        # Update document with S3 key and session info
        self.db_manager.client.table('source_documents')\
            .update({
                's3_key': s3_key,
                'import_session_id': self.session_id
            })\
            .eq('document_uuid', doc_uuid)\
            .execute()
        
        # Submit to Celery for processing
        task_id = submit_document_to_celery(
            doc_uuid,
            source_doc_id,
            s3_key,
            file_info.get('mime_type', 'unknown')
        )
        
        # Record estimated costs
        self._record_file_costs(doc_uuid, file_info)
        
        print(f"    ✓ {file_info['filename']} queued successfully")
        
        return {
            'status': 'success',
            'document_uuid': doc_uuid,
            'source_doc_id': source_doc_id,
            'task_id': task_id
        }
        
    except Exception as e:
        print(f"    ✗ {file_info['filename']}: {str(e)}")
        return {
            'status': 'failed',
            'error': str(e)
        }
```

### Phase 2: Update Import Session Logic

#### 2.1 Fix Session Creation
```python
def create_import_session(self) -> str:
    """Create import session with proper project association"""
    try:
        # Ensure we have project IDs
        if not hasattr(self, 'project_sql_id'):
            self.project_sql_id, self.project_uuid = self.find_or_create_input_project()
        
        session_data = {
            'case_name': 'Legal Documents - Input Collection',
            'project_id': self.project_sql_id,  # Use integer ID
            'manifest': self.manifest,
            'total_files': len(self.manifest['files']),
            'status': 'active'
        }
        
        result = self.db_manager.service_client.table('import_sessions')\
            .insert(session_data)\
            .execute()
        
        self.session_id = result.data[0]['id']
        print(f"Created import session: {self.session_id}")
        print(f"Associated with project: {self.project_sql_id} ({self.project_uuid})")
        return self.session_id
        
    except Exception as e:
        print(f"Error creating import session: {e}")
        raise
```

### Phase 3: Remove Redundant Project Creation

#### 3.1 Update Main Import Logic
```python
def import_files(self, dry_run: bool = False):
    """Import all files with proper project association"""
    print("\n" + "="*60)
    print("STARTING IMPORT")
    print("="*60)
    
    # Find or create project FIRST
    self.project_sql_id, self.project_uuid = self.find_or_create_input_project()
    print(f"Using project: {self.project_sql_id} ({self.project_uuid})")
    
    # Create import session
    self.create_import_session()
    
    if dry_run:
        print("DRY RUN - No files will be processed")
        self._print_summary()
        return
    
    # Continue with existing import logic...
    # (rest of method unchanged)
```

#### 3.2 Remove Old Project Creation Methods
- Remove `create_or_get_project()` method
- Remove redundant project creation logic
- Consolidate to single project association point

## Verification Plan

### Test Strategy: Progressive Validation

#### Phase 1: Single Document Test
```bash
# 1. Create minimal test manifest with 1 file
python scripts/analyze_client_files.py input/folder_a_pleadings \
    --case-name "Test Single Document" \
    --output test_single_manifest.json

# 2. Test import with fixed script
python scripts/import_from_manifest_fixed.py test_single_manifest.json \
    --dry-run --workers 1 --batch-size 1

# 3. Real import of single document
python scripts/import_from_manifest_fixed.py test_single_manifest.json \
    --workers 1 --batch-size 1
```

**Expected Results:**
- ✅ Project association successful
- ✅ Document creation successful  
- ✅ S3 upload successful
- ✅ Celery submission successful
- ✅ Import session tracking successful

#### Phase 2: Small Batch Test (5 Documents)
```bash
# Test with first 5 documents
python scripts/import_from_manifest_fixed.py input_manifest.json \
    --workers 1 --batch-size 5 \
    | head -50  # Limit output to first batch
```

**Validation Queries:**
```sql
-- Verify project association
SELECT p.id, p.name, p.projectId, 
       COUNT(sd.id) as document_count
FROM projects p
LEFT JOIN source_documents sd ON p.id = sd.project_fk_id
WHERE p.name LIKE '%Input%'
GROUP BY p.id;

-- Verify import session
SELECT s.id, s.case_name, s.total_files, s.processed_files,
       s.status, s.total_cost
FROM import_sessions s
ORDER BY s.created_at DESC
LIMIT 1;

-- Verify document creation
SELECT sd.id, sd.original_file_name, sd.document_uuid,
       sd.project_fk_id, sd.import_session_id, sd.s3_key
FROM source_documents sd
WHERE sd.import_session_id IS NOT NULL
ORDER BY sd.id DESC
LIMIT 5;
```

#### Phase 3: Full Import Test (All 492 Documents)
```bash
# Start monitoring FIRST
python scripts/standalone_pipeline_monitor.py &

# Run full import
python scripts/import_from_manifest_fixed.py input_manifest.json \
    --workers 4 --batch-size 25
```

**Verification Commands:**
```bash
# Check import session status  
python scripts/check_import_completion.py --session SESSION_ID

# Check Celery processing
python scripts/check_celery_status.py

# Monitor pipeline progress
python scripts/standalone_pipeline_monitor.py
```

### Success Criteria

#### Import Stage Success Metrics
1. **Project Association**: All documents link to same project
2. **Document Creation**: 0% foreign key constraint violations
3. **S3 Upload**: >95% successful uploads
4. **Celery Submission**: 100% successful queue submissions
5. **Cost Tracking**: Accurate cost estimation and recording

#### Processing Stage Success Metrics
1. **OCR Processing**: >90% successful text extraction
2. **Entity Extraction**: >85% successful entity identification
3. **Graph Building**: >80% successful relationship creation
4. **End-to-End**: >75% documents fully processed

#### Monitoring Verification
1. **Import Sessions**: Properly tracked in database
2. **Cost Breakdown**: Accurate service-level cost tracking
3. **Progress Monitoring**: Real-time status updates
4. **Error Reporting**: Clear identification of failed documents

## Implementation Files

### Files to Create/Modify

1. **`scripts/import_from_manifest_fixed.py`** - Fixed import script
2. **`scripts/test_import_verification.py`** - Automated verification script
3. **`scripts/check_project_association.py`** - Project validation utility

### Database Verification Queries

```sql
-- Complete import verification query
WITH import_stats AS (
    SELECT 
        s.id as session_id,
        s.case_name,
        s.total_files,
        s.processed_files,
        s.failed_files,
        s.total_cost,
        p.id as project_id,
        p.name as project_name,
        COUNT(sd.id) as documents_created
    FROM import_sessions s
    LEFT JOIN projects p ON s.project_id = p.id
    LEFT JOIN source_documents sd ON sd.import_session_id = s.id
    WHERE s.id = 'SESSION_ID'
    GROUP BY s.id, p.id
)
SELECT * FROM import_stats;

-- Document processing pipeline status
SELECT 
    sd.celery_status,
    COUNT(*) as count,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 2) as percentage
FROM source_documents sd
WHERE sd.import_session_id = 'SESSION_ID'
GROUP BY sd.celery_status
ORDER BY count DESC;
```

## Risk Mitigation

### Rollback Plan
1. **Pre-Import Backup**: Export current import_sessions and processing_costs tables
2. **Failed Import Cleanup**: Script to remove partial import data
3. **Session Isolation**: Each import session is isolated for safe cleanup

### Monitoring Safeguards
1. **Cost Limits**: Stop import if estimated costs exceed thresholds
2. **Error Rate Monitoring**: Pause import if error rate >20%
3. **Storage Monitoring**: Check S3 space before large uploads

This comprehensive fix addresses all identified issues while providing robust verification and monitoring capabilities for the 492 documents in `/input/`.