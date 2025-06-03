# Context 147: Autonomous Codebase Simplification Task List

**Date**: 2025-05-27  
**Objective**: Reduce codebase from 101 to ~50 files while fixing 99.6% failure rate  
**Approach**: Detailed, verifiable tasks executable by autonomous coding tools

## Phase 1: Immediate Error Fix (Fix Silent Failures)

### Task 1.1: Add Error Capture to OCR Tasks
**File**: `scripts/celery_tasks/ocr_tasks.py`
**Line**: ~280-300 (in `process_ocr` function)
**Action**: Wrap the entire function body in try-except with database error logging

```python
# Add after line 264 (logger.info statement):
try:
    # [existing function body]
except Exception as e:
    error_msg = f"{type(e).__name__}: {str(e)}"
    logger.exception(f"OCR failed for document {document_uuid}")
    
    # Save error to database
    try:
        self.db_manager.client.table('source_documents').update({
            'error_message': error_msg[:500],  # Truncate long errors
            'celery_status': 'ocr_failed',
            'last_modified_at': datetime.now().isoformat()
        }).eq('id', source_doc_sql_id).execute()
    except:
        logger.error("Failed to save error to database")
    
    # Update state for monitoring
    update_document_state(document_uuid, "ocr", "failed", {
        "error": error_msg,
        "task_id": self.request.id
    })
    
    # Re-raise for Celery retry
    raise
```

**Verification**: 
1. Run `grep -n "except Exception" scripts/celery_tasks/ocr_tasks.py`
2. Should see new exception handler in process_ocr function

### Task 1.2: Fix Function Signature Mismatch
**File**: `scripts/celery_tasks/ocr_tasks.py`
**Line**: ~350-370 (where `extract_text_from_pdf_textract` is called)
**Action**: Pass db_manager correctly to extraction functions

```python
# Find the line that calls extract_text_from_pdf_textract
# Change from:
result = extract_text_from_pdf_textract(file_path, document_uuid)

# To:
result = extract_text_from_pdf_textract(
    db_manager=self.db_manager,
    s3_key=file_path,
    document_uuid=document_uuid,
    source_doc_sql_id=source_doc_sql_id
)
```

**Verification**:
1. Run `grep -A2 -B2 "extract_text_from_pdf_textract" scripts/celery_tasks/ocr_tasks.py`
2. Confirm db_manager is passed as first parameter

### Task 1.3: Add Error Capture to All Celery Tasks
**Files to modify**:
- `scripts/celery_tasks/text_tasks.py`
- `scripts/celery_tasks/entity_tasks.py`
- `scripts/celery_tasks/graph_tasks.py`
- `scripts/celery_tasks/embedding_tasks.py`

**Action**: Add same try-except pattern to main task functions
**Pattern**: Look for `@app.task` decorators and wrap function bodies

**Verification**:
1. Run `grep -l "@app.task" scripts/celery_tasks/*.py | xargs grep -l "except Exception"`
2. All task files should have exception handling

### Task 1.4: Create Diagnostic Script
**Create new file**: `scripts/diagnose_document_failure.py`
```python
#!/usr/bin/env python3
"""Diagnose why a specific document failed processing."""
import sys
import os
from dotenv import load_dotenv
load_dotenv(override=True)

from scripts.supabase_utils import SupabaseManager
from scripts.s3_storage import S3StorageManager
from scripts.config import *
import boto3
import logging

logging.basicConfig(level=logging.DEBUG)

def diagnose_document(doc_id: int = None, doc_uuid: str = None):
    """Run comprehensive diagnostics on a failed document."""
    db = SupabaseManager()
    
    # Get document
    if doc_id:
        doc_result = db.client.table('source_documents').select('*').eq('id', doc_id).execute()
    elif doc_uuid:
        doc_result = db.client.table('source_documents').select('*').eq('document_uuid', doc_uuid).execute()
    else:
        # Get first failed document
        doc_result = db.client.table('source_documents').select('*').eq('celery_status', 'ocr_failed').limit(1).execute()
    
    if not doc_result.data:
        print("No document found")
        return
    
    doc = doc_result.data[0]
    print(f"\nDocument: {doc['original_file_name']}")
    print(f"Status: {doc['celery_status']}")
    print(f"S3 Key: {doc['s3_key']}")
    
    # Test S3 access
    print("\n1. Testing S3 Access...")
    try:
        s3 = boto3.client('s3')
        response = s3.head_object(Bucket=S3_PRIMARY_DOCUMENT_BUCKET, Key=doc['s3_key'])
        print(f"✅ S3 object exists, size: {response['ContentLength']} bytes")
    except Exception as e:
        print(f"❌ S3 access failed: {e}")
        return
    
    # Test Textract access
    print("\n2. Testing AWS Textract...")
    try:
        textract = boto3.client('textract')
        # Just test that we can call the service
        print("✅ Textract client created successfully")
    except Exception as e:
        print(f"❌ Textract access failed: {e}")
    
    # Test OpenAI access
    print("\n3. Testing OpenAI API...")
    try:
        import openai
        openai.api_key = OPENAI_API_KEY
        # Test with a simple completion
        response = openai.ChatCompletion.create(
            model="gpt-4-turbo-preview",
            messages=[{"role": "user", "content": "Say 'API working'"}],
            max_tokens=10
        )
        print("✅ OpenAI API working")
    except Exception as e:
        print(f"❌ OpenAI API failed: {e}")
    
    # Test direct OCR
    print("\n4. Testing direct OCR extraction...")
    try:
        from scripts.ocr_extraction import extract_text_from_pdf_textract
        result = extract_text_from_pdf_textract(
            db_manager=db,
            s3_key=doc['s3_key'],
            document_uuid=doc['document_uuid'],
            source_doc_sql_id=doc['id']
        )
        print(f"✅ OCR extraction returned: {type(result)}")
    except Exception as e:
        print(f"❌ OCR extraction failed: {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    doc_id = int(sys.argv[1]) if len(sys.argv) > 1 else None
    diagnose_document(doc_id)
```

**Verification**:
1. Run `python scripts/diagnose_document_failure.py`
2. Should output diagnostic information for a failed document

## Phase 2: Consolidate Import Scripts

### Task 2.1: Create Unified Import CLI
**Create new file**: `scripts/cli/import.py`
```python
#!/usr/bin/env python3
"""Unified document import CLI replacing 6 separate scripts."""
import click
import json
from pathlib import Path
from typing import Optional, List
import sys
sys.path.append(str(Path(__file__).parent.parent.parent))

from scripts.supabase_utils import SupabaseManager
from scripts.celery_tasks.ocr_tasks import process_ocr, process_image
from scripts.ocr_extraction import detect_file_category

@click.group()
def cli():
    """Document import management commands."""
    pass

@cli.command()
@click.argument('manifest_file', type=click.Path(exists=True))
@click.option('--project-uuid', required=True, help='Target project UUID')
@click.option('--batch-size', default=50, help='Documents per batch')
@click.option('--dry-run', is_flag=True, help='Show what would be imported')
def from_manifest(manifest_file, project_uuid, batch_size, dry_run):
    """Import documents from a manifest file."""
    # Consolidate logic from:
    # - import_from_manifest.py
    # - import_from_manifest_fixed.py
    # - import_from_manifest_targeted.py
    
    with open(manifest_file) as f:
        manifest = json.load(f)
    
    click.echo(f"Loading manifest with {len(manifest['files'])} files")
    
    if dry_run:
        click.echo("DRY RUN - no files will be imported")
        for file in manifest['files'][:10]:
            click.echo(f"  Would import: {file['name']}")
        return
    
    # Implementation from import_from_manifest_targeted.py
    db = SupabaseManager()
    
    # Verify project exists
    project_result = db.client.table('projects').select('id').eq('projectId', project_uuid).execute()
    if not project_result.data:
        click.echo(f"Error: Project {project_uuid} not found", err=True)
        return
    
    project_sql_id = project_result.data[0]['id']
    
    # Import logic here...
    click.echo(f"Imported {len(manifest['files'])} documents to project {project_uuid}")

@cli.command()
@click.argument('directory', type=click.Path(exists=True))
@click.option('--project-uuid', required=True, help='Target project UUID')
@click.option('--recursive', is_flag=True, help='Include subdirectories')
def from_directory(directory, project_uuid, recursive):
    """Import documents from a directory."""
    # Consolidate logic from import_client_files.py
    click.echo(f"Importing from {directory}")
    # Implementation here...

@cli.command()
@click.option('--project-uuid', help='Filter by project')
@click.option('--status', help='Filter by status')
def status(project_uuid, status):
    """Check import status."""
    # Consolidate logic from import_tracker.py and import_dashboard.py
    db = SupabaseManager()
    # Implementation here...

if __name__ == '__main__':
    cli()
```

**Verification**:
1. Run `python scripts/cli/import.py --help`
2. Should show three subcommands: from-manifest, from-directory, status

### Task 2.2: Migrate Import Logic
**Action**: Copy implementation from old files to new CLI commands

**Old files to extract from**:
- `scripts/import_from_manifest_targeted.py` → `from_manifest` command
- `scripts/import_client_files.py` → `from_directory` command  
- `scripts/import_tracker.py` → `status` command

**Verification**:
1. Run `diff -u scripts/import_from_manifest_targeted.py scripts/cli/import.py`
2. Ensure all core logic is migrated

### Task 2.3: Archive Old Import Scripts
**Create directory**: `scripts/legacy/import/`
**Move files**:
```bash
mkdir -p scripts/legacy/import/
mv scripts/import_*.py scripts/legacy/import/
```

**Verification**:
1. Run `ls scripts/import_*.py 2>/dev/null | wc -l` - should return 0
2. Run `ls scripts/legacy/import/*.py | wc -l` - should return 6

## Phase 3: Consolidate Monitoring Scripts

### Task 3.1: Create Unified Monitor CLI
**Create new file**: `scripts/cli/monitor.py`
```python
#!/usr/bin/env python3
"""Unified pipeline monitoring replacing 5 separate scripts."""
import click
import time
from rich.console import Console
from rich.table import Table
from rich.live import Live
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent))

from scripts.supabase_utils import SupabaseManager
from scripts.redis_utils import get_redis_manager

console = Console()

@click.group()
def cli():
    """Pipeline monitoring commands."""
    pass

@cli.command()
@click.option('--project-uuid', help='Filter by project')
@click.option('--refresh', default=5, help='Refresh interval in seconds')
def live(project_uuid, refresh):
    """Live pipeline monitoring dashboard."""
    # Consolidate from standalone_pipeline_monitor.py
    db = SupabaseManager()
    
    def generate_table():
        table = Table(title="Pipeline Status")
        table.add_column("Status", style="cyan")
        table.add_column("Count", style="magenta")
        table.add_column("Percentage", style="green")
        
        # Get status counts
        if project_uuid:
            # Get project ID first
            project_result = db.client.table('projects').select('id').eq('projectId', project_uuid).execute()
            if project_result.data:
                project_sql_id = project_result.data[0]['id']
                docs = db.client.table('source_documents').select('celery_status').eq('project_fk_id', project_sql_id).execute()
            else:
                docs = []
        else:
            docs = db.client.table('source_documents').select('celery_status').execute()
        
        # Count statuses
        from collections import Counter
        status_counts = Counter(doc['celery_status'] for doc in docs.data)
        total = len(docs.data)
        
        for status, count in sorted(status_counts.items()):
            percentage = (count / total * 100) if total > 0 else 0
            table.add_row(status, str(count), f"{percentage:.1f}%")
        
        table.add_row("TOTAL", str(total), "100%", style="bold")
        return table
    
    with Live(generate_table(), refresh_per_second=1/refresh) as live:
        while True:
            time.sleep(refresh)
            live.update(generate_table())

@cli.command()
def cache():
    """Monitor cache performance."""
    # Consolidate from monitor_cache_performance.py
    redis = get_redis_manager()
    if not redis.is_available():
        click.echo("Redis not available", err=True)
        return
    
    # Implementation here...

@cli.command()
@click.option('--export', type=click.Path(), help='Export metrics to file')
def metrics(export):
    """Show detailed pipeline metrics."""
    # Consolidate from enhanced_pipeline_monitor.py and pipeline_monitor.py
    # Implementation here...

if __name__ == '__main__':
    cli()
```

**Verification**:
1. Run `python scripts/cli/monitor.py --help`
2. Should show three subcommands: live, cache, metrics

### Task 3.2: Archive Old Monitor Scripts
**Move files**:
```bash
mkdir -p scripts/legacy/monitors/
mv scripts/*monitor*.py scripts/legacy/monitors/
```

**Verification**:
1. Run `ls scripts/*monitor*.py 2>/dev/null | wc -l` - should return 0
2. Run `ls scripts/legacy/monitors/*.py | wc -l` - should return 5

## Phase 4: Consolidate Processing Scripts

### Task 4.1: Create Processing Module Structure
**Create directories**:
```bash
mkdir -p scripts/processing
touch scripts/processing/__init__.py
```

### Task 4.2: Extract OCR Processing
**Create file**: `scripts/processing/ocr.py`
**Action**: Consolidate OCR logic from multiple files

```python
"""Unified OCR processing module."""
from typing import Dict, Any, Optional, Tuple
import logging
from scripts.config import *

logger = logging.getLogger(__name__)

class OCRProcessor:
    """Unified OCR processor replacing scattered implementations."""
    
    def __init__(self, db_manager):
        self.db_manager = db_manager
        self.s3_manager = None  # Lazy load
        
    def process_document(self, 
                        document_uuid: str,
                        source_doc_sql_id: int,
                        file_path: str,
                        file_name: str,
                        file_type: str) -> Dict[str, Any]:
        """
        Main entry point for OCR processing.
        Replaces logic from:
        - ocr_extraction.py::extract_text_from_pdf_textract
        - ocr_extraction.py::extract_text_from_docx
        - image_processing.py::ImageProcessor.process_image
        """
        try:
            if file_type in ['pdf', 'application/pdf']:
                return self._process_pdf(document_uuid, source_doc_sql_id, file_path)
            elif file_type in ['docx', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document']:
                return self._process_docx(document_uuid, source_doc_sql_id, file_path)
            elif file_type in ['jpg', 'jpeg', 'png', 'image/jpeg', 'image/png']:
                return self._process_image(document_uuid, source_doc_sql_id, file_path)
            else:
                raise ValueError(f"Unsupported file type: {file_type}")
                
        except Exception as e:
            logger.exception(f"OCR processing failed for {document_uuid}")
            # Always save error to database
            self._save_error(source_doc_sql_id, str(e))
            raise
    
    def _save_error(self, doc_id: int, error_msg: str):
        """Save error message to database."""
        try:
            self.db_manager.client.table('source_documents').update({
                'error_message': error_msg[:500],
                'celery_status': 'ocr_failed'
            }).eq('id', doc_id).execute()
        except:
            logger.error("Failed to save error to database")
    
    # Implementation methods here...
```

**Verification**:
1. Run `grep -n "class OCRProcessor" scripts/processing/ocr.py`
2. Should find the class definition

### Task 4.3: Update Celery Tasks to Use New Modules
**File**: `scripts/celery_tasks/ocr_tasks.py`
**Action**: Replace scattered imports with unified processor

```python
# At top of file, replace multiple imports with:
from scripts.processing.ocr import OCRProcessor

# In process_ocr function, replace extraction calls with:
processor = OCRProcessor(self.db_manager)
result = processor.process_document(
    document_uuid=document_uuid,
    source_doc_sql_id=source_doc_sql_id,
    file_path=file_path,
    file_name=file_name,
    file_type=detected_file_type
)
```

**Verification**:
1. Run `grep "OCRProcessor" scripts/celery_tasks/ocr_tasks.py`
2. Should find import and usage

## Phase 5: Create Admin CLI for Maintenance

### Task 5.1: Create Admin CLI
**Create new file**: `scripts/cli/admin.py`
```python
#!/usr/bin/env python3
"""Administrative commands for pipeline maintenance."""
import click
from pathlib import Path
import sys
sys.path.append(str(Path(__file__).parent.parent.parent))

from scripts.supabase_utils import SupabaseManager
from scripts.redis_utils import get_redis_manager

@click.group()
def cli():
    """Administrative pipeline commands."""
    pass

@cli.command()
@click.option('--project-uuid', required=True, help='Project to reset')
@click.option('--status', default='ocr_failed', help='Status to reset')
def reset_failed(project_uuid, status):
    """Reset failed documents to pending."""
    # Logic from process_stuck_documents.py
    db = SupabaseManager()
    
    # Get project
    project_result = db.client.table('projects').select('id').eq('projectId', project_uuid).execute()
    if not project_result.data:
        click.echo(f"Project {project_uuid} not found", err=True)
        return
    
    project_sql_id = project_result.data[0]['id']
    
    # Reset documents
    result = db.client.table('source_documents').update({
        'celery_status': 'pending',
        'celery_task_id': None,
        'error_message': None
    }).eq('project_fk_id', project_sql_id).eq('celery_status', status).execute()
    
    click.echo(f"Reset {len(result.data)} documents from {status} to pending")

@cli.command()
def clear_redis():
    """Clear all Redis queues."""
    redis = get_redis_manager()
    if not redis.is_available():
        click.echo("Redis not available", err=True)
        return
    
    if click.confirm("This will clear ALL Redis data. Continue?"):
        client = redis.get_client()
        for key in client.scan_iter("*"):
            client.delete(key)
        click.echo("Redis cleared")

@cli.command()
@click.argument('doc_id', type=int)
def diagnose(doc_id):
    """Diagnose a specific document failure."""
    # Call the diagnostic script
    from scripts.diagnose_document_failure import diagnose_document
    diagnose_document(doc_id)

if __name__ == '__main__':
    cli()
```

**Verification**:
1. Run `python scripts/cli/admin.py --help`
2. Should show: reset-failed, clear-redis, diagnose commands

## Phase 6: Archive Legacy Files

### Task 6.1: Create Legacy Structure
```bash
mkdir -p scripts/legacy/{test,processing,utils,fixes}
```

### Task 6.2: Move Test Files
**Action**: Move non-production test files
```bash
# Move test files that aren't real tests
mv scripts/test_*.py scripts/legacy/test/

# Keep only these test files in main directory:
mkdir -p scripts/tests
mv scripts/legacy/test/test_celery_tasks.py scripts/tests/
mv scripts/legacy/test/test_redis_integration.py scripts/tests/
```

**Verification**:
1. Run `ls scripts/test_*.py 2>/dev/null | wc -l` - should return 0
2. Run `ls scripts/tests/*.py | wc -l` - should return 2

### Task 6.3: Move Duplicate Processing Files
```bash
mv scripts/process_pending_document.py scripts/legacy/processing/
mv scripts/process_stuck_documents.py scripts/legacy/processing/
mv scripts/main_pipeline.py scripts/legacy/processing/
mv scripts/queue_processor.py scripts/legacy/processing/
```

### Task 6.4: Move Fix Scripts
```bash
mv scripts/fix_*.py scripts/legacy/fixes/
```

## Phase 7: Update Imports and Dependencies

### Task 7.1: Create Import Update Script
**Create file**: `scripts/update_imports.py`
```python
#!/usr/bin/env python3
"""Update imports after reorganization."""
import os
import re
from pathlib import Path

# Map old imports to new imports
IMPORT_MAP = {
    'from scripts.import_from_manifest': 'from scripts.cli.import',
    'from scripts.standalone_pipeline_monitor': 'from scripts.cli.monitor',
    'from scripts.process_stuck_documents': 'from scripts.cli.admin',
    # Add more mappings...
}

def update_file(filepath):
    """Update imports in a single file."""
    with open(filepath, 'r') as f:
        content = f.read()
    
    original = content
    for old, new in IMPORT_MAP.items():
        content = re.sub(old, new, content)
    
    if content != original:
        with open(filepath, 'w') as f:
            f.write(content)
        print(f"Updated: {filepath}")

# Update all Python files
for root, dirs, files in os.walk('scripts'):
    # Skip legacy directory
    if 'legacy' in root:
        continue
    
    for file in files:
        if file.endswith('.py'):
            update_file(os.path.join(root, file))

print("Import updates complete")
```

**Run**: `python scripts/update_imports.py`

**Verification**:
1. Run `grep -r "from scripts.import_from_manifest" scripts/ --exclude-dir=legacy`
2. Should return no results

## Phase 8: Final Verification

### Task 8.1: Create Verification Script
**Create file**: `scripts/verify_reorganization.py`
```python
#!/usr/bin/env python3
"""Verify the reorganization was successful."""
import os
from pathlib import Path

def count_files(directory, pattern="*.py"):
    """Count Python files in directory."""
    return len(list(Path(directory).rglob(pattern)))

# Check file counts
original_count = count_files("scripts/legacy")
current_count = count_files("scripts") - count_files("scripts/legacy")

print(f"Original files (now in legacy): {original_count}")
print(f"Current files (active): {current_count}")
print(f"Reduction: {original_count - current_count} files ({(1 - current_count/original_count)*100:.1f}%)")

# Check new structure exists
required_dirs = [
    "scripts/cli",
    "scripts/processing", 
    "scripts/celery_tasks",
    "scripts/tests",
    "scripts/legacy"
]

for dir in required_dirs:
    if os.path.exists(dir):
        print(f"✅ {dir} exists")
    else:
        print(f"❌ {dir} missing")

# Test imports
try:
    from scripts.cli import import as import_cli
    from scripts.cli import monitor
    from scripts.cli import admin
    from scripts.processing.ocr import OCRProcessor
    print("✅ All imports working")
except ImportError as e:
    print(f"❌ Import error: {e}")
```

**Run**: `python scripts/verify_reorganization.py`

**Expected output**:
```
Original files (now in legacy): 51
Current files (active): 45
Reduction: 6 files (11.8%)
✅ scripts/cli exists
✅ scripts/processing exists
✅ scripts/celery_tasks exists
✅ scripts/tests exists
✅ scripts/legacy exists
✅ All imports working
```

### Task 8.2: Test Core Functionality
```bash
# Test new CLIs work
python scripts/cli/import.py --help
python scripts/cli/monitor.py --help
python scripts/cli/admin.py --help

# Test diagnostic works
python scripts/diagnose_document_failure.py

# Test Celery workers start
celery -A scripts.celery_app worker --loglevel=info --dry-run
```

## Success Criteria

1. **File count reduced**: From 101 to ~50 active files
2. **All tests pass**: `pytest scripts/tests/`
3. **Error messages captured**: Run failed document, see error in database
4. **Single import path**: Only one way to import documents
5. **Single monitor**: Only one monitoring dashboard
6. **Workers start**: Celery workers start without import errors

## Rollback Plan

If issues arise:
1. All original files are in `scripts/legacy/`
2. Can restore with: `mv scripts/legacy/* scripts/`
3. Revert import updates: `git checkout scripts/`

## Timeline

- **Hour 1-2**: Phase 1 (Fix errors)
- **Hour 3-4**: Phase 2-3 (Consolidate CLIs)
- **Hour 5-6**: Phase 4-5 (Processing modules)
- **Hour 7-8**: Phase 6-8 (Archive and verify)

Total: ~8 hours for complete reorganization