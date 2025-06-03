#!/usr/bin/env python3
"""
Fix import statements to remove 'scripts.' prefix.
This updates all Python files to use relative imports within the scripts directory.
"""
import os
import re
import sys
from pathlib import Path

def fix_imports_in_file(filepath):
    """Fix imports in a single file."""
    with open(filepath, 'r') as f:
        content = f.read()
    
    original_content = content
    
    # Pattern to match 'from XXX import' or 'import XXX'
    patterns = [
        (r'from scripts\.(\w+)', r'from \1'),  # from module import
        (r'import scripts\.(\w+)', r'import \1'),  # import module
        (r'from scripts\.(\w+)\.(\w+)', r'from \1.\2'),  # from pkg.module import
    ]
    
    for pattern, replacement in patterns:
        content = re.sub(pattern, replacement, content)
    
    # Special case for celery_tasks imports - these need to stay as is in some cases
    # Revert changes for celery task includes in celery_app.py
    if 'celery_app.py' in str(filepath):
        # These need to keep the scripts prefix for Celery to find them
        content = re.sub(
            r"include=\[\s*'celery_tasks\.",
            "include=[\n        'scripts.celery_tasks.",
            content
        )
    
    if content != original_content:
        with open(filepath, 'w') as f:
            f.write(content)
        return True
    return False

def main():
    """Fix imports in all Python files."""
    fixed_count = 0
    checked_count = 0
    
    # Directories to process
    dirs_to_process = ['scripts', 'tests']
    
    for dir_name in dirs_to_process:
        if not os.path.exists(dir_name):
            continue
            
        for root, dirs, files in os.walk(dir_name):
            # Skip legacy directories
            if 'legacy' in root or '__pycache__' in root:
                continue
                
            for file in files:
                if file.endswith('.py'):
                    filepath = os.path.join(root, file)
                    checked_count += 1
                    
                    if fix_imports_in_file(filepath):
                        fixed_count += 1
                        print(f"Fixed: {filepath}")
    
    print(f"\nSummary:")
    print(f"Files checked: {checked_count}")
    print(f"Files fixed: {fixed_count}")

if __name__ == '__main__':
    main()