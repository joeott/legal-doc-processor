#!/usr/bin/env python3
"""
Final reorganization plan for scripts directory
"""

# Essential Infrastructure (KEEP in scripts/ - used by everything)
ESSENTIAL_INFRASTRUCTURE = [
    'celery_app.py',         # Celery configuration - needed for workers
    'config.py',             # Configuration - used everywhere
    'supabase_utils.py',     # Database access - used everywhere
    'redis_utils.py',        # Redis/caching - used everywhere  
    'cache_keys.py',         # Cache key definitions - used with redis
    'logging_config.py',     # Logging setup - used everywhere
]

# Core Processing (KEEP in scripts/ - used by Celery tasks)
CORE_PROCESSING = [
    'ocr_extraction.py',     # OCR logic - used by ocr_tasks
    'text_processing.py',    # Text processing - used by text_tasks
    'entity_extraction.py',  # Entity extraction - used by entity_tasks
    'entity_resolution.py',  # Entity resolution - used by entity_tasks
    'entity_resolution_enhanced.py',  # Enhanced resolution - used by entity_tasks
    'relationship_builder.py',        # Relationships - used by graph_tasks
    'chunking_utils.py',     # Chunking - used by text_tasks
    'structured_extraction.py',       # Structured extraction - used by text_tasks
    'image_processing.py',   # Image processing - used by ocr_tasks
    'textract_utils.py',     # AWS Textract - used by ocr_tasks
    's3_storage.py',         # S3 storage - used by ocr_tasks
    'models_init.py',        # ML model initialization - used by multiple
]

# Utilities (COULD MOVE to core/ or archive)
UTILITIES = [
    'health_check.py',       # Health checking - standalone utility
    'task_coordinator.py',   # Task coordination - not actively used?
    'queue_processor.py',    # Queue processing - replaced by Celery?
    'main_pipeline.py',      # Main pipeline - replaced by Celery?
]

# Non-Python files
OTHER_FILES = [
    'fix_timestamp_triggers.sql',  # SQL script - archive
    'celery.conf.template',        # Config template - keep
    'scripts_index.json',          # Generated index - archive
]

def print_reorganization_plan():
    """Print the reorganization plan"""
    
    print("=== FINAL REORGANIZATION PLAN ===\n")
    
    print("1. KEEP in scripts/ (Essential Infrastructure):")
    for script in ESSENTIAL_INFRASTRUCTURE:
        print(f"   ✓ {script}")
    
    print("\n2. KEEP in scripts/ (Core Processing - used by Celery):")
    for script in CORE_PROCESSING:
        print(f"   ✓ {script}")
    
    print("\n3. EVALUATE for archival:")
    for script in UTILITIES:
        print(f"   ? {script}")
    
    print("\n4. ARCHIVE these files:")
    for file in OTHER_FILES:
        if file != 'celery.conf.template':
            print(f"   → legacy/utilities/{file}")
    
    print("\n5. FINAL STRUCTURE:")
    print("   scripts/")
    print("   ├── cli/              (3 unified CLIs)")
    print("   ├── core/             (4 shared modules)")
    print("   ├── celery_tasks/     (7 task modules)")
    print("   ├── legacy/           (archived scripts)")
    print("   └── [19 essential scripts + celery.conf.template]")
    
    total_active = len(ESSENTIAL_INFRASTRUCTURE) + len(CORE_PROCESSING) + 3 + 4 + 7
    print(f"\n   Total active Python files: {total_active}")

if __name__ == '__main__':
    print_reorganization_plan()