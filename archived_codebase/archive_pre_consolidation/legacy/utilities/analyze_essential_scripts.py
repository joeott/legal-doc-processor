#!/usr/bin/env python3
"""
Analyze which scripts are essential vs. which can be archived
"""
import os
import re
import subprocess
from pathlib import Path

def find_imports(script_name):
    """Find all imports of a given script"""
    patterns = [
        f"from {script_name} import",
        f"import {script_name}",
        f"from scripts.{script_name} import",
        f"import scripts.{script_name}"
    ]
    
    total_imports = 0
    importing_files = set()
    
    for pattern in patterns:
        try:
            # Use grep to find imports
            cmd = f'grep -r "{pattern}" --include="*.py" scripts/ tests/ 2>/dev/null | grep -v legacy'
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            
            if result.stdout:
                lines = result.stdout.strip().split('\n')
                for line in lines:
                    if line:
                        file_path = line.split(':')[0]
                        importing_files.add(file_path)
                        total_imports += 1
        except:
            pass
    
    return total_imports, list(importing_files)

def analyze_scripts():
    """Analyze all scripts in the main scripts directory"""
    
    scripts_to_analyze = [
        'cache_keys',
        'celery_app',
        'chunking_utils',
        'config',
        'entity_extraction',
        'entity_resolution_enhanced',
        'entity_resolution',
        'health_check',
        'image_processing',
        'logging_config',
        'main_pipeline',
        'models_init',
        'ocr_extraction',
        'queue_processor',
        'redis_utils',
        'relationship_builder',
        's3_storage',
        'structured_extraction',
        'supabase_utils',
        'task_coordinator',
        'text_processing',
        'textract_utils'
    ]
    
    results = {}
    
    for script in scripts_to_analyze:
        count, files = find_imports(script)
        results[script] = {
            'import_count': count,
            'imported_by': files
        }
    
    # Categorize scripts
    essential_infrastructure = []  # Core infrastructure that everything depends on
    essential_processing = []      # Core processing logic used by Celery tasks
    utilities = []                 # Could potentially be moved to core/
    archivable = []              # Rarely used, could be archived
    
    for script, data in results.items():
        if data['import_count'] > 10:
            essential_infrastructure.append((script, data['import_count']))
        elif data['import_count'] >= 5:
            essential_processing.append((script, data['import_count']))
        elif data['import_count'] >= 2:
            utilities.append((script, data['import_count']))
        else:
            archivable.append((script, data['import_count']))
    
    # Print analysis
    print("=== Script Analysis ===\n")
    
    print("Essential Infrastructure (keep in scripts/):")
    for script, count in sorted(essential_infrastructure, key=lambda x: x[1], reverse=True):
        print(f"  {script}.py - {count} imports")
    
    print("\nEssential Processing (keep in scripts/):")
    for script, count in sorted(essential_processing, key=lambda x: x[1], reverse=True):
        print(f"  {script}.py - {count} imports")
    
    print("\nUtilities (could move to core/):")
    for script, count in sorted(utilities, key=lambda x: x[1], reverse=True):
        print(f"  {script}.py - {count} imports")
    
    print("\nArchivable (rarely used):")
    for script, count in sorted(archivable, key=lambda x: x[1], reverse=True):
        print(f"  {script}.py - {count} imports")
    
    # Check for Celery task dependencies
    print("\n=== Celery Task Dependencies ===")
    celery_essential = set()
    
    # Check what celery tasks import
    celery_files = [
        'scripts/celery_tasks/ocr_tasks.py',
        'scripts/celery_tasks/text_tasks.py',
        'scripts/celery_tasks/entity_tasks.py',
        'scripts/celery_tasks/graph_tasks.py',
        'scripts/celery_tasks/embedding_tasks.py'
    ]
    
    for celery_file in celery_files:
        if os.path.exists(celery_file):
            with open(celery_file, 'r') as f:
                content = f.read()
                for script in scripts_to_analyze:
                    if f"from {script} import" in content or f"import {script}" in content:
                        celery_essential.add(script)
    
    print("\nScripts used by Celery tasks:")
    for script in sorted(celery_essential):
        print(f"  {script}.py")

if __name__ == '__main__':
    analyze_scripts()