#!/usr/bin/env python3
"""Fix imports in celery tasks to be relative"""
import os
import re

def fix_imports(file_path):
    """Fix imports in a single file"""
    with open(file_path, 'r') as f:
        content = f.read()
    
    # Replace all "from scripts." imports with relative imports
    original_content = content
    content = re.sub(r'from scripts\.celery_app', 'from celery_app', content)
    content = re.sub(r'from scripts\.celery_tasks\.', 'from celery_tasks.', content)
    content = re.sub(r'from scripts\.', 'from ', content)
    
    if content != original_content:
        with open(file_path, 'w') as f:
            f.write(content)
        print(f"Fixed imports in {file_path}")
    
    return content != original_content

def main():
    # Fix imports in all celery task files
    celery_files = [
        'celery_tasks/entity_tasks.py',
        'celery_tasks/graph_tasks.py', 
        'celery_tasks/ocr_tasks.py',
        'celery_tasks/text_tasks.py'
    ]
    
    for file_path in celery_files:
        fix_imports(file_path)
    
    # Also fix imports in queue_processor.py
    fix_imports('queue_processor.py')
    
    # And live_document_test.py
    fix_imports('live_document_test.py')

if __name__ == '__main__':
    main()