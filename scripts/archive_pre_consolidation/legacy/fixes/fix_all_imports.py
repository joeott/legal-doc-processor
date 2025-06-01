#!/usr/bin/env python3
"""Fix all import statements to use absolute imports"""
import os
import re
import glob

def fix_imports_in_file(filepath):
    """Fix imports in a single file"""
    try:
        with open(filepath, 'r') as f:
            content = f.read()
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
        return False
    
    original_content = content
    
    # Define import patterns to fix
    import_patterns = [
        # Core modules - from X import Y
        (r'^from (config|redis_utils|cache_keys|supabase_utils|celery_app) import', r'from scripts.\1 import'),
        
        # Core modules - import X
        (r'^import (config|redis_utils|cache_keys|supabase_utils|celery_app)$', r'import scripts.\1'),
        (r'^import (config|redis_utils|cache_keys|supabase_utils|celery_app)\s*#', r'import scripts.\1 #'),
        
        # Processing modules - from X import Y
        (r'^from (ocr_extraction|text_processing|entity_extraction|entity_resolution) import', r'from scripts.\1 import'),
        (r'^from (relationship_builder|chunking_utils|structured_extraction) import', r'from scripts.\1 import'),
        (r'^from (textract_utils|s3_storage|models_init|celery_submission) import', r'from scripts.\1 import'),
        (r'^from (logging_config|pipeline_monitor|queue_processor) import', r'from scripts.\1 import'),
        
        # Import statements with 'as'
        (r'^import (config|redis_utils|cache_keys|supabase_utils|celery_app) as', r'import scripts.\1 as'),
        
        # From . imports (relative imports in same package)
        (r'^from \.(config|redis_utils|cache_keys|supabase_utils|celery_app) import', r'from scripts.\1 import'),
    ]
    
    # Apply replacements
    for pattern, replacement in import_patterns:
        content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
    
    # Write back if changed
    if content != original_content:
        try:
            with open(filepath, 'w') as f:
                f.write(content)
            return True
        except Exception as e:
            print(f"Error writing {filepath}: {e}")
            return False
    return False

def main():
    """Fix imports in all Python files"""
    # Change to scripts directory
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(scripts_dir)
    
    # Get all Python files in scripts directory
    script_files = []
    
    # Add files in scripts/
    script_files.extend(glob.glob('*.py'))
    
    # Add files in scripts/celery_tasks/
    script_files.extend(glob.glob('celery_tasks/*.py'))
    
    # Filter out this script itself
    script_files = [f for f in script_files if not f.endswith('fix_all_imports.py')]
    
    print(f"Found {len(script_files)} Python files to check")
    
    fixed_files = []
    for filepath in script_files:
        if fix_imports_in_file(filepath):
            fixed_files.append(filepath)
            print(f"✅ Fixed imports in: {filepath}")
    
    print(f"\n📊 Summary:")
    print(f"   Total files checked: {len(script_files)}")
    print(f"   Files with fixes: {len(fixed_files)}")
    
    if fixed_files:
        print("\n📝 Fixed files:")
        for f in sorted(fixed_files):
            print(f"   - {f}")

if __name__ == "__main__":
    main()