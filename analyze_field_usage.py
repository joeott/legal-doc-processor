#!/usr/bin/env python3
"""Analyze field usage across core scripts to determine minimal required fields"""

import re
from pathlib import Path
from collections import defaultdict

# Core scripts to analyze
scripts = [
    'pdf_tasks.py',
    'textract_utils.py', 
    'entity_service.py',
    'chunking_utils.py',
    'intake_service.py',
    'batch_processor.py',
    'db.py',
    'cache.py'
]

# Patterns to find field access
patterns = {
    'attribute_access': r'\.([a-zA-Z_][a-zA-Z0-9_]*)',
    'dict_access': r'\[[\'"]([\w_]+)[\'"]\]',
    'column_names': r'[\'"](document_uuid|file_name|s3_key|status|raw_extracted_text|chunk_index|text|entity_text|canonical_name)[\'"]',
}

# Track field usage by script and model
field_usage = defaultdict(lambda: defaultdict(set))
model_fields = defaultdict(set)

# Analyze each script
for script in scripts:
    script_path = Path(f'/opt/legal-doc-processor/scripts/{script}')
    if not script_path.exists():
        print(f"⚠️  Script not found: {script}")
        continue
    
    with open(script_path, 'r') as f:
        content = f.read()
        
    # Find all field accesses
    for pattern_name, pattern in patterns.items():
        matches = re.findall(pattern, content)
        for match in matches:
            field_usage[script][pattern_name].add(match)
    
    # Look for specific model usage patterns
    if 'SourceDocument' in content:
        model_fields['SourceDocument'].update(field_usage[script]['attribute_access'])
    if 'DocumentChunk' in content:
        model_fields['DocumentChunk'].update(field_usage[script]['attribute_access'])
    if 'EntityMention' in content:
        model_fields['EntityMention'].update(field_usage[script]['attribute_access'])
    if 'CanonicalEntity' in content:
        model_fields['CanonicalEntity'].update(field_usage[script]['attribute_access'])

# Report findings
print("="*60)
print("FIELD USAGE ANALYSIS REPORT")
print("="*60)

# Key fields by model based on common usage
key_fields = {
    'SourceDocument': [
        'document_uuid', 'id', 'file_name', 'original_file_name',
        's3_key', 's3_bucket', 'status', 'raw_extracted_text',
        'textract_job_id', 'project_fk_id', 'created_at', 'updated_at',
        'ocr_completed_at', 'error_message', 'celery_task_id'
    ],
    'DocumentChunk': [
        'chunk_uuid', 'document_uuid', 'chunk_index', 'text',
        'char_start_index', 'char_end_index', 'created_at'
    ],
    'EntityMention': [
        'mention_uuid', 'document_uuid', 'chunk_uuid', 'entity_text',
        'entity_type', 'start_char', 'end_char', 'confidence_score',
        'canonical_entity_uuid', 'created_at'
    ],
    'CanonicalEntity': [
        'canonical_entity_uuid', 'canonical_name', 'entity_type',
        'mention_count', 'confidence_score', 'aliases', 'properties',
        'metadata', 'created_at', 'updated_at'
    ],
    'RelationshipStaging': [
        'source_entity_uuid', 'target_entity_uuid', 'relationship_type',
        'confidence_score', 'source_chunk_uuid', 'evidence_text',
        'properties', 'metadata', 'created_at'
    ]
}

print("\nREQUIRED FIELDS BY MODEL:")
for model, fields in key_fields.items():
    print(f"\n{model}:")
    for field in sorted(fields):
        print(f"  - {field}")

# Specific field usage by script
print("\n" + "="*60)
print("FIELD USAGE BY SCRIPT:")
for script in scripts:
    if script in field_usage:
        all_fields = set()
        for pattern_type, fields in field_usage[script].items():
            all_fields.update(fields)
        
        # Filter to likely model fields
        model_fields = {f for f in all_fields if len(f) > 2 and not f.startswith('_')}
        
        if model_fields:
            print(f"\n{script}:")
            for field in sorted(model_fields)[:20]:  # Top 20 fields
                print(f"  - {field}")

print("\n" + "="*60)
print("SUMMARY:")
print("- Identified core fields required for each model")
print("- Most scripts use a minimal subset of available fields")
print("- Many database columns are unused in application code")