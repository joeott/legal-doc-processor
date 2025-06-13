# Context 113: Import Fix Summary

## Overview
This document summarizes the import path issues in the Celery-based document processing pipeline and the fixes applied to enable proper module loading when running Celery workers.

## Problem Statement
When attempting to start Celery workers with `celery -A scripts.celery_app worker`, the following issues occur:
1. ModuleNotFoundError: No module named 'config'
2. ModuleNotFoundError: No module named 'celery_app'
3. Various other import errors due to relative imports

## Root Cause
Python modules are using relative imports (e.g., `from config import`) which fail when Celery tries to load them from a different working directory. All imports need to be absolute imports from the project root.

## Files Requiring Import Fixes

### Core Configuration Files
1. **scripts/celery_app.py**
   - Fixed: `from config import` → `from scripts.config import`

2. **scripts/redis_utils.py**
   - Fixed: `from config import` → `from scripts.config import`
   - Fixed: `from cache_keys import` → `from scripts.cache_keys import`

### Celery Task Files
3. **scripts/celery_tasks/__init__.py**
   - Fixed: `from celery_app import` → `from scripts.celery_app import`

4. **scripts/celery_tasks/ocr_tasks.py**
   - Fixed: `from celery_app import` → `from scripts.celery_app import`
   - Fixed: `from ocr_extraction import` → `from scripts.ocr_extraction import`
   - Fixed: `from supabase_utils import` → `from scripts.supabase_utils import`
   - Fixed: `from redis_utils import` → `from scripts.redis_utils import`
   - Fixed: `from config import` → `from scripts.config import`

5. **scripts/celery_tasks/text_tasks.py**
   - Fixed: `from celery_app import` → `from scripts.celery_app import`
   - Fixed: `from text_processing import` → `from scripts.text_processing import`
   - Fixed: `from supabase_utils import` → `from scripts.supabase_utils import`
   - Fixed: `from redis_utils import` → `from scripts.redis_utils import`
   - Fixed: `from config import` → `from scripts.config import`

6. **scripts/celery_tasks/entity_tasks.py**
   - Fixed: `from celery_app import` → `from scripts.celery_app import`
   - Fixed: `from entity_extraction import` → `from scripts.entity_extraction import`
   - Fixed: `from entity_resolution import` → `from scripts.entity_resolution import`
   - Fixed: `from supabase_utils import` → `from scripts.supabase_utils import`
   - Fixed: `from redis_utils import` → `from scripts.redis_utils import`

7. **scripts/celery_tasks/graph_tasks.py**
   - Fixed: `from celery_app import` → `from scripts.celery_app import`
   - Fixed: `from relationship_builder import` → `from scripts.relationship_builder import`
   - Fixed: `from supabase_utils import` → `from scripts.supabase_utils import`
   - Fixed: `from redis_utils import` → `from scripts.redis_utils import`

### Processing Module Files
Additional files that may need import fixes:
- scripts/ocr_extraction.py
- scripts/text_processing.py
- scripts/entity_extraction.py
- scripts/entity_resolution.py
- scripts/relationship_builder.py
- scripts/chunking_utils.py
- scripts/structured_extraction.py
- scripts/textract_utils.py
- scripts/s3_storage.py
- scripts/models_init.py
- scripts/celery_submission.py

## Import Fix Script
Created a script to automatically fix all imports:

```python
#!/usr/bin/env python3
"""Fix all import statements to use absolute imports"""
import os
import re
import glob

def fix_imports_in_file(filepath):
    """Fix imports in a single file"""
    with open(filepath, 'r') as f:
        content = f.read()
    
    original_content = content
    
    # Define import patterns to fix
    import_patterns = [
        # Core modules
        (r'^from (config|redis_utils|cache_keys|supabase_utils|celery_app) import', r'from scripts.\1 import'),
        (r'^import (config|redis_utils|cache_keys|supabase_utils|celery_app)$', r'import scripts.\1'),
        
        # Processing modules
        (r'^from (ocr_extraction|text_processing|entity_extraction|entity_resolution) import', r'from scripts.\1 import'),
        (r'^from (relationship_builder|chunking_utils|structured_extraction) import', r'from scripts.\1 import'),
        (r'^from (textract_utils|s3_storage|models_init|celery_submission) import', r'from scripts.\1 import'),
        
        # Import statements with 'as'
        (r'^import (config|redis_utils|cache_keys|supabase_utils|celery_app) as', r'import scripts.\1 as'),
    ]
    
    # Apply replacements
    for pattern, replacement in import_patterns:
        content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
    
    # Write back if changed
    if content != original_content:
        with open(filepath, 'w') as f:
            f.write(content)
        return True
    return False

def main():
    """Fix imports in all Python files"""
    # Get all Python files in scripts directory
    script_files = glob.glob('scripts/**/*.py', recursive=True)
    
    fixed_files = []
    for filepath in script_files:
        if fix_imports_in_file(filepath):
            fixed_files.append(filepath)
            print(f"Fixed imports in: {filepath}")
    
    print(f"\nTotal files fixed: {len(fixed_files)}")

if __name__ == "__main__":
    main()
```

## Testing Import Fixes

### Step 1: Verify Imports
```bash
# Test that imports work
python -c "from scripts.celery_app import app; print('Celery app imported successfully')"
python -c "from scripts.redis_utils import get_redis_manager; print('Redis utils imported successfully')"
```

### Step 2: Start Celery Worker
```bash
# Set PYTHONPATH
export PYTHONPATH=/Users/josephott/Documents/phase_1_2_3_process_v5:$PYTHONPATH

# Start worker
celery -A scripts.celery_app worker --loglevel=info --concurrency=2
```

### Step 3: Test Document Processing
```bash
# Submit a test document
python scripts/test_single_document.py
```

## Common Issues and Solutions

### Issue 1: Circular Imports
Some modules may have circular import dependencies. Solutions:
- Use lazy imports (import inside functions)
- Restructure code to break circular dependencies
- Use TYPE_CHECKING for type hints only

### Issue 2: Missing __init__.py Files
Ensure all directories have __init__.py files:
- scripts/__init__.py
- scripts/celery_tasks/__init__.py

### Issue 3: PYTHONPATH Not Set
Always set PYTHONPATH before running Celery:
```bash
export PYTHONPATH=/path/to/project:$PYTHONPATH
```

## Verification Checklist

- [ ] All imports in celery_app.py use absolute paths
- [ ] All imports in celery_tasks/*.py use absolute paths
- [ ] Redis connection works with fixed imports
- [ ] Celery workers start without import errors
- [ ] Test document processes successfully
- [ ] Monitoring tools work with fixed imports

## Next Steps

1. Run the import fix script on all files
2. Test Celery worker startup
3. Process test document through pipeline
4. Fix any remaining import issues
5. Document any additional fixes needed